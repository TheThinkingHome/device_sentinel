// File: tools/panel_checks/check_removed_days.js, Version: 0.28.4 (2026-11-07)
// Panel checks: a day removed by hand on the device page's freeze charts
// (rule FRZ-25). In Advanced, for a person who may act, each bar can be
// pressed; a removal asks first with its warning, and counting a day again
// asks too; nothing is sent until the answer; a removed bar keeps its
// height in its own colour, never also hatched or grey; Simple offers
// nothing to press; a refusal shows under the charts.
// Run with: LC_ALL=en_US.UTF-8 node check_removed_days.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const DEVICE = payloads._ids ? payloads._ids.alpha : "alpha";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

const H = 3600;
const ACTIONS = {
  area_id: null, name_by_user: null, integration_name: "Motion Hall", labels: [],
  mutes: {
    everything: { on: false, source: null, here: false },
    freeze: { on: false, source: null, here: false },
    battery: { on: false, source: null, here: false },
    signal: { on: false, source: null, here: false },
  },
};
// Fourteen days, the eleventh removed, the fourth the hatched fluke.
const DAYS = Array.from({ length: 14 }, (_, i) => `2026-10-${String(24 + i > 31 ? 24 + i - 31 : 24 + i).padStart(2, "0")}`)
  .map((d, i) => (24 + i > 31 ? d.replace("-10-", "-11-") : d));
const GAPS = Array.from({ length: 14 }, (_, i) => (i === 10 ? 9.5 : i === 3 ? 4 : 0.9 + (i % 3) * 0.05) * H);

function page(mode, removed = [10]) {
  const p = JSON.parse(JSON.stringify(payloads.device));
  p.identity.device_id = DEVICE;
  p.identity.name = "Motion Hall";
  if (mode !== "viewer") p.identity.actions = JSON.parse(JSON.stringify(ACTIONS));
  p.status.rule = "14-Day Trimmed Maximum";
  p.status.window = 1.4 * H;
  p.rhythm.gaps = GAPS;
  p.rhythm.set_aside = [3];
  p.rhythm.gap_days = DAYS;
  p.rhythm.gaps_removed = removed;
  p.rhythm.rules = {
    trimmed: 0.95 * H, trimmed_days: 14, lognormal: null, lognormal_days: null,
    lognormal_gaps: [], lognormal_set_aside: [], lognormal_dates: [], lognormal_removed: [],
    in_use: "trimmed", counting_again: null,
  };
  return p;
}

async function open(mode, removed, answer) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/device/${DEVICE}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  const route = () => ({ prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) });
  window.addEventListener("location-changed", () => {
    if (window.location.pathname.startsWith(PREFIX)) panel.route = route();
  });
  window.document.body.append(panel);
  panel.route = route();
  const sent = [];
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "device_day") {
        sent.push(message);
        if (answer) return answer(message);
        return { removed: message.removed };
      }
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode === "simple" ? "simple" : "advanced" };
      if (kind === "device") return page(mode, removed);
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot, sent };
}

const trimmedChart = (root) => [...root.querySelectorAll(".rulebox")].find((b) => /Trimmed Maximum/.test(b.querySelector(".ruletitle").textContent));
const bars = (root) => [...trimmedChart(root).querySelectorAll(".rulechart > div:not(.ruleline)")];
const button = (root, text) => [...root.querySelectorAll("button")].find((b) => b.textContent === text);

(async () => {
  console.log("\nAdvanced, for a person who may act");
  let { root, sent, panel, window } = await open("advanced");
  let b = bars(root);
  check("fourteen bars, each pressable", b.length === 14 && b.every((x) => x.classList.contains("pressable") && x.getAttribute("role") === "button"), b.map((x) => x.className));
  check("the removed day has its own colour, kept at its height", b[10].classList.contains("removed") && parseFloat(b[10].style.height) >= 90, [b[10].className, b[10].style.height]);
  check("the removed day is neither hatched nor grey", !b[10].classList.contains("aside") && !b[10].classList.contains("grey"));
  check("the hatched day is still drawn hatched", b[3].classList.contains("aside") && !b[3].classList.contains("removed"));
  check("each bar names its day, and what pressing it does",
    /^Oct 2[0-9]: .*Press to remove this day$/.test(b[0].title) && /removed by hand, not counted\. Press to count it again$/.test(b[10].title), [b[0].title, b[10].title]);
  const note = trimmedChart(root).querySelector("p").textContent;
  check("the note names the orange days and how to press", /Orange days were removed by hand and are not counted\./.test(note) && /Press a bar to remove its day from the count\./.test(note), note);
  // The scale: the removed 9.5h day does not set it, so a normal day
  // reads well above the floor.
  check("a removed day does not set the chart's scale", parseFloat(b[0].style.height) > 15, b[0].style.height);

  console.log("\nPressing a counted bar");
  b[5].click();
  await settle();
  let ask = trimmedChart(root).querySelector(".dayask");
  check("asks first, with the warning", ask && /Remove .* from this device's rhythm\?/.test(ask.textContent)
    && /Do this only if you know what you are doing\./.test(ask.textContent) && /reported frozen too soon/.test(ask.textContent), ask ? ask.textContent : null);
  check("nothing is sent before the answer", sent.length === 0, sent);
  button(root, "Keep it").click();
  await settle();
  check("Keep it closes the question and sends nothing", !trimmedChart(root).querySelector(".dayask") && sent.length === 0);
  bars(root)[5].click();
  await settle();
  button(root, "Remove this day").click();
  await settle();
  check("Remove this day sends that day, to be removed", sent.length === 1 && sent[0].device_id === DEVICE && sent[0].day === DAYS[5] && sent[0].removed === true, sent);

  console.log("\nPressing a removed bar");
  ({ root, sent } = await open("advanced"));
  bars(root)[10].click();
  await settle();
  ask = trimmedChart(root).querySelector(".dayask");
  check("asks before counting it again", ask && /Count .* again\?/.test(ask.textContent) && !/Do this only if/.test(ask.textContent), ask ? ask.textContent : null);
  button(root, "Count it again").click();
  await settle();
  check("Count it again sends that day, to be counted", sent.length === 1 && sent[0].day === DAYS[10] && sent[0].removed === false, sent);

  console.log("\nThe keyboard");
  ({ root, sent, window } = await open("advanced"));
  bars(root)[2].dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await settle();
  check("Enter on a bar asks as a press does", Boolean(trimmedChart(root).querySelector(".dayask")));

  console.log("\nA refusal");
  ({ root, sent } = await open("advanced", [10], () => { const e = new Error("That day is not one of this device's learned days."); e.code = "refused"; throw e; }));
  bars(root)[1].click();
  await settle();
  button(root, "Remove this day").click();
  await settle();
  const refused = root.querySelector(".actnote.refused");
  check("Home Assistant's reason shows under the charts", refused && /not one of this device's learned days/.test(refused.textContent), refused ? refused.textContent : null);

  console.log("\nSimple, and a person who may not act");
  for (const mode of ["simple", "viewer"]) {
    const opened = await open(mode);
    const chart = trimmedChart(opened.root);
    if (!chart) { check(`${mode}: no chart is drawn for a device not in trouble`, true); continue; }
    const these = bars(opened.root);
    check(`${mode}: no bar can be pressed`, these.every((x) => !x.classList.contains("pressable") && x.getAttribute("role") !== "button"));
    check(`${mode}: the removed day still shows in its colour`, these[10].classList.contains("removed"));
    these[4].click();
    await settle();
    check(`${mode}: pressing asks nothing`, !opened.root.querySelector(".dayask") && opened.sent.length === 0);
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
