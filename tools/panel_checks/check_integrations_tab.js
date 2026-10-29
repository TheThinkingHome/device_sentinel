// File: tools/panel_checks/check_integrations_tab.js, Version: 0.27.14 (2026-10-29)
// Panel checks: the Integrations tab excludes and mutes whole
// integrations, one press each (rules MUTE-02, MUTE-03, MUTE-09,
// DASH-16), and Simple's Battery Trends and Devices leave columns out
// (rule DASH-04).
// Run with: LC_ALL=en_US.UTF-8 node check_integrations_tab.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
const DEVICE = payloads._ids ? payloads._ids.alpha : "alpha";

const ACTIONS = {
  area_id: "bedroom", name_by_user: "Button Randy Night Table", integration_name: "0x00158d0001",
  labels: [{ id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }, { id: "bedside", name: "Bedside", meaning: "" }],
  last_seen_off: true,
  mutes: {
    everything: { on: false, source: null, here: false },
    freeze: { on: false, source: null, here: false },
    battery: { on: true, source: "label: Quiet", here: false },
    signal: { on: true, source: "label: Quiet", here: false },
  },
};
const CHOICES = { areas: [{ id: "bedroom", name: "Master Bedroom" }, { id: "laundry", name: "Laundry" }],
  labels: [{ id: "garage", name: "Garage", meaning: "mutes freeze", devices: 3 }, { id: "quiet", name: "Quiet", meaning: "mutes battery and signal", devices: 1 }] };

async function open(answers, tweak = () => {}) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${answers.__path || `/device/${DEVICE}`}`, virtualConsole,
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
  const calls = [];
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: answers.__mode || "advanced" };
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = DEVICE;
        page.identity.name = "Button Randy Night Table";
        page.identity.area = "Master Bedroom";
        page.identity.muted = "battery (label: Quiet); signal (label: Quiet)";
        page.identity.actions = JSON.parse(JSON.stringify(ACTIONS));
        page.status.rule = "14-Day Trimmed Maximum";
        page.status.window = 43200;
        tweak(page);
        return page;
      }
      if (kind === "device_choices") return CHOICES;
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild && tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const buttonIn = (node, text) => node && [...node.querySelectorAll("button")].find((b) => b.textContent === text);
const click = async (node) => { node.click(); await settle(); };

const tabs = (root) => [...root.querySelectorAll(".tab")].map((t) => t.textContent.replace(/ \(\d+\)$/, ""));
const modeButton = (root, label) => [...root.querySelectorAll(".modes button")].find((b) => b.textContent === label);
const anyButton = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent === label);
const text = (root) => root.querySelector(".pane").textContent;
const DOOR = Array(60).fill(0).map((_, i) => 40 - 0.4 * i);
const withBattery = (p) => {
  p.battery = { daily: DOOR, now: 16.4, threshold: 15, readable: true, weeks: [20, 19, 18, 17, 16.5],
    reading: "falling", fit: null, sentence: "Falling about 2.8 points a week.", falling: true,
    left: "about 4 to 6 weeks", left_soon: true, days_setting: 30,
    projection: { curved: false, level: 16.4, near: 33, far: 41, centre: 37, near_path: [-0.5, 0], far_path: [-0.4, 0] } };
};

const labelsOf = (root) => [...root.querySelectorAll("table.kv tr")].map((tr) =>
  tr.classList.contains("kvgroup") ? `[${tr.textContent}]` : tr.firstChild.textContent);
const buttons = (cell) => (cell ? [...cell.querySelectorAll("button")].map((b) => b.textContent) : []);

const ROWS = [
  { domain: "alexa_media", name: "Alexa Media Player", standing: "watched", first_seen: false, watched: 18, muted: 0,
    set_aside: 0, problems: 1, acknowledged: 0, outages: 0, devices: 18, excluded: false,
    mutes: { everything: false, freeze: false, battery: false, signal: false },
    recommended: "Device Sentinel sees its devices only through Amazon's cloud", trouble: { never_reported: 1 }, down_since: null },
  { domain: "cast", name: "Google Cast", standing: "excluded", first_seen: false, watched: 0, muted: 0,
    set_aside: 2, problems: 0, acknowledged: 0, outages: 0, devices: 2, excluded: true,
    mutes: { everything: false, freeze: false, battery: false, signal: false },
    recommended: null, trouble: { unavailable: 1 }, down_since: null },
  { domain: "roomba", name: "iRobot Roomba", standing: "muted", first_seen: false, watched: 1, muted: 1,
    set_aside: 0, problems: 0, acknowledged: 0, outages: 0, devices: 1, excluded: false,
    mutes: { everything: true, freeze: false, battery: false, signal: false },
    recommended: null, trouble: {}, down_since: null },
  { domain: "zha", name: "ZHA", standing: "watched", first_seen: false, watched: 18, muted: 0,
    set_aside: 0, problems: 3, acknowledged: 0, outages: 1, devices: 18, excluded: false,
    mutes: { everything: false, freeze: true, battery: false, signal: false },
    recommended: null, trouble: { unavailable: 2, low_battery: 1 }, down_since: "2026-10-28T07:12:55+00:00" },
];
const integrations = () => ({ rows: JSON.parse(JSON.stringify(ROWS)) });
const rowOf = (root, name) => [...root.querySelectorAll(".pane tbody tr")].find((tr) => tr.cells[0].textContent.startsWith(name));
const buttonsOf = (tr) => [...tr.cells[1].querySelectorAll("button")];
const named = (tr, words) => buttonsOf(tr).find((b) => b.textContent.replace("✓ ", "") === words);

(async () => {
  for (const mode of ["simple", "advanced"]) {
    console.log(`The Integrations tab, ${mode}`);
    let { root, calls } = await open({ __mode: mode, __path: "/integrations", integrations });
    const heads = [...root.querySelectorAll(".pane thead th")].map((th) => th.textContent);
    check("nothing empty is drawn as text", !/null|undefined/.test(root.querySelector(".pane").textContent));
    const widths = [...root.querySelectorAll(".pane table col")].map((col) => parseFloat(col.style.width));
    check("the buttons' column is the widest, so no button breaks a word", widths.length === heads.length && widths.every((w, i) => i === 1 || widths[1] > w), widths);
    check("the buttons stay on one line", !!root.querySelector(".pane tbody .intbuttons"));
    // Advanced adds SET ASIDE and OUTAGES, 14 DAYS; TROUBLE stays last (rule DASH-16).
    const expected = mode === "simple" ? "INTEGRATION,EXCLUDE AND MUTE,TROUBLE"
      : "INTEGRATION,EXCLUDE AND MUTE,SET ASIDE,OUTAGES, 14 DAYS,TROUBLE";
    check(`${mode}: the columns`, heads.join() === expected, heads);
    const last = (row) => row.cells[row.cells.length - 1];
    const alexa = rowOf(root, "Alexa Media Player");
    check("the name carries the device count and the id", /^Alexa Media Player \(18\) alexa_media/.test(alexa.cells[0].textContent), alexa.cells[0].textContent);
    check("the recommendation reads under the name",
      alexa.cells[0].querySelector(".recommended").textContent === "Recommended: Exclude, Device Sentinel sees its devices only through Amazon's cloud");
    check("five buttons in order", buttonsOf(alexa).map((b) => b.textContent).join() === "Exclude,Mute everything,Mute freeze,Mute battery,Mute signal",
      buttonsOf(alexa).map((b) => b.textContent));
    check("the trouble is the last column", last(alexa).textContent === "1 never reported", last(alexa).textContent);
    const zha = rowOf(root, "ZHA");
    check("trouble says when it went down, then its devices, worst first",
      /^Down since .+, 2 unavailable, 1 battery low$/.test(last(zha).textContent), last(zha).textContent);
    check("a mute that is on is lit and checked", named(zha, "Mute freeze").classList.contains("on") && named(zha, "Mute freeze").textContent === "✓ Mute freeze");
    const cast = rowOf(root, "Google Cast");
    check("an excluded row is greyed, lit Excluded, with the midnight words on hover",
      cast.classList.contains("excluded") && named(cast, "Excluded").classList.contains("on")
      && named(cast, "Excluded").getAttribute("title") === "History deleted at midnight. Press again before then to keep it.");
    check("an excluded row's mutes rest", ["Mute everything", "Mute freeze", "Mute battery", "Mute signal"].every((w) => named(cast, w).getAttribute("aria-disabled") === "true"));
    check("an excluded row shows no trouble", last(cast).textContent === "");
    const roomba = rowOf(root, "iRobot Roomba");
    check("Mute everything lights the single mutes and holds them",
      ["Mute freeze", "Mute battery", "Mute signal"].every((w) => named(roomba, w).classList.contains("on") && named(roomba, w).getAttribute("aria-disabled") === "true"));

    // One press each, no question, and the press says where it was made.
    named(alexa, "Exclude").click();
    await settle();
    let sent = calls.filter((c) => c.type === "device_sentinel/integration_exclude");
    check("Exclude sends at once, from the Integrations tab", sent.length === 1 && sent[0].domain === "alexa_media" && sent[0].on === true && sent[0].source === "integrations_tab", sent);
    named(rowOf(root, "Google Cast"), "Excluded").click();
    await settle();
    sent = calls.filter((c) => c.type === "device_sentinel/integration_exclude");
    check("pressing Excluded again takes it back", sent.length === 2 && sent[1].domain === "cast" && sent[1].on === false, sent);
    named(rowOf(root, "ZHA"), "Mute freeze").click();
    await settle();
    named(rowOf(root, "ZHA"), "Mute battery").click();
    await settle();
    const muted = calls.filter((c) => c.type === "device_sentinel/integration_mute");
    check("a lit mute lifts, an unlit one sets", muted.length === 2
      && muted[0].kind === "freeze" && muted[0].on === false && muted[1].kind === "battery" && muted[1].on === true, muted);
    named(rowOf(root, "Google Cast"), "Mute signal").click();
    named(rowOf(root, "iRobot Roomba"), "Mute freeze").click();
    await settle();
    check("a resting button sends nothing", calls.filter((c) => c.type === "device_sentinel/integration_mute").length === 2);
    check("no question is ever asked", !root.querySelector(".ask"));

    const chip = (label) => [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith(label));
    check("chips: All, Recommended, Trouble, Excluded, Muted",
      [...root.querySelectorAll(".pane .chips .chip")].map((c) => c.textContent).join() === "All 4,Recommended 1,Trouble 2,Excluded 1,Muted 2",
      [...root.querySelectorAll(".pane .chips .chip")].map((c) => c.textContent));
    chip("Recommended").click();
    await settle();
    check("Recommended shows only those with a recommendation",
      [...root.querySelectorAll(".pane tbody tr")].map((tr) => tr.cells[0].querySelector("a").textContent).join() === "Alexa Media Player");
  }

  console.log("Simple's Battery Trends and Devices");
  let { root } = await open({ __mode: "simple", __path: "/battery-trends" });
  let text = root.querySelector(".pane").textContent;
  check("Simple: no TYPICAL LEVEL, LOWEST CELL or WHICH ONE", !/TYPICAL LEVEL|LOWEST CELL|WHICH ONE/.test(text));
  check("Simple: Other Cells leaves out DAYS RECORDED, STEPS and MODEL, A WEEK", !/DAYS RECORDED|STEPS|MODEL, A WEEK/.test(text));
  check("Simple: Falling leaves out the weekly levels", !/DAYS AGO|THIS WEEK/.test(text));
  check("Simple: no Not a Percentage", !/Not a Percentage/.test(text));
  // DEVICE, TYPE and LEVEL stand in the same place in each table, and a
  // short table ends short of the edge (rule DASH-04).
  // The third column counts where it is a level or a cell count; a raw
  // reading is text of another width.
  const placed = (table) => [...table.querySelectorAll("col")]
    .slice(0, /^(LEVEL|CELLS)$/.test(table.tHead.rows[0].cells[2].textContent) ? 3 : 2)
    .map((col) => (parseFloat(col.style.width) * parseFloat(table.style.width || "100")) / 100);
  const tables = [...root.querySelectorAll(".pane table")];
  const first = placed(tables[0]);
  check("each Battery Trends table is on one scale", tables.length >= 2 && tables.every((t) => t.dataset.base), tables.length);
  check("DEVICE, TYPE and LEVEL line up from table to table",
    tables.every((t) => placed(t).every((w, i) => Math.abs(w - first[i]) < 0.01)), tables.map(placed));
  check("a short table ends short of the edge", parseFloat(tables[0].style.width) < 100, tables[0].style.width);
  ({ root } = await open({ __mode: "advanced", __path: "/battery-trends" }));
  text = root.querySelector(".pane").textContent;
  check("Advanced keeps them", /TYPICAL LEVEL/.test(text) && /LOWEST CELL/.test(text) && /WHICH ONE/.test(text));
  check("Advanced keeps the measuring columns", /DAYS RECORDED/.test(text) && /STEPS/.test(text) && /MODEL, A WEEK/.test(text));
  ({ root } = await open({ __mode: "simple", __path: "/devices" }));
  let heads = [...root.querySelectorAll(".pane thead th")].map((th) => th.textContent);
  // TYPE and its filter show in Simple too (rule DASH-04).
  check("Simple Devices: DEVICE, TYPE, INTEGRATION, STANDING, PROBLEM", heads.join() === "DEVICE,TYPE,INTEGRATION,STANDING,PROBLEM", heads);
  check("Simple Devices: the type filter", [...root.querySelectorAll(".pane select")].some((s) => /All types/.test(s.textContent)));
  check("Simple Devices: no label filter", ![...root.querySelectorAll(".pane select")].some((s) => /All labels/.test(s.textContent)));
  ({ root } = await open({ __mode: "advanced", __path: "/devices" }));
  heads = [...root.querySelectorAll(".pane thead th")].map((th) => th.textContent);
  check("Advanced Devices keeps TYPE, LAST REPORT, RHYTHM and WINDOW",
    ["TYPE", "LAST REPORT", "RHYTHM", "WINDOW"].every((h) => heads.includes(h)), heads);
  check("Advanced Devices adds AREA and BATTERY", heads.includes("AREA") && heads.includes("BATTERY"), heads);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
