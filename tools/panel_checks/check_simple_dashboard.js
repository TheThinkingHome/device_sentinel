// File: tools/panel_checks/check_simple_dashboard.js, Version: 0.27.10 (2026-10-27)
// Panel checks: Simple and Advanced (rules DASH-03, DASH-04, BAT-17, MUTE-09).
// The setting opens the dashboard; the switch holds while the page is
// open, through a hidden tab, and nothing is kept; Simple's tabs, its read-only device page
// and its battery chart; Mute by label in Advanced.
// Run with: LC_ALL=en_US.UTF-8 node check_simple_dashboard.js [path/to/panel.js]
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

(async () => {
  console.log("The setting opens the dashboard");
  let { root, panel, window } = await open({ __mode: "simple", __path: "" });
  check("Simple: Signal Trends and Integrations are off the tab row",
    !tabs(root).includes("Signal Trends") && !tabs(root).includes("Integrations") && tabs(root).length === 6, tabs(root));
  check("the switch shows Simple pressed", modeButton(root, "Simple").getAttribute("aria-pressed") === "true");
  await click(modeButton(root, "Advanced"));
  check("the switch moves the page to Advanced", tabs(root).length === 8, tabs(root));
  check("and shows Advanced pressed", modeButton(root, "Advanced").getAttribute("aria-pressed") === "true");
  // A tab hidden for five minutes: Home Assistant takes the dashboard
  // out of the page and puts the same one back when it is shown (rule DASH-03).
  panel.remove();
  window.document.body.append(panel);
  await panel._refresh();
  await settle();
  check("a hidden tab shown again keeps the switch (#716)", tabs(root).length === 8
    && modeButton(root, "Advanced").getAttribute("aria-pressed") === "true", tabs(root));
  check("nothing is kept in the browser", window.localStorage.length === 0 && window.sessionStorage.length === 0);
  // Leaving for another page of Home Assistant: the dashboard opened
  // again is a new one, which starts from the setting.
  ({ root } = await open({ __mode: "simple", __path: "" }));
  check("leaving the dashboard returns it to the setting", tabs(root).length === 6, tabs(root));
  ({ root } = await open({ __mode: "simple", __path: "/signal-trends" }));
  check("a hidden tab still opens from a link, and shows while open", tabs(root).includes("Signal Trends"), tabs(root));
  ({ root } = await open({ __mode: "advanced", __path: "" }));
  check("Advanced: all eight tabs", tabs(root).length === 8, tabs(root));

  console.log("Simple's device page");
  ({ root } = await open({ __mode: "simple" }, (p) => { withBattery(p); p.status.category = "reporting"; }));
  check("Type, Area and Labels are read-only", !buttons(rowCell(root, "Type")).length
    && !buttons(rowCell(root, "Area")).length && !buttons(rowCell(root, "Labels")).length,
  [buttons(rowCell(root, "Type")), buttons(rowCell(root, "Area")), buttons(rowCell(root, "Labels"))]);
  // "Not known", as Advanced says it (rules DEV-07, DEV-10).
  check("an empty type reads Not known", rowCell(root, "Type").textContent === "Not known", rowCell(root, "Type").textContent);
  check("an unanswered Power reads Not known", rowCell(root, "Power").textContent === "Not known", rowCell(root, "Power").textContent);
  check("labels still say what they do", rowCell(root, "Labels").textContent.includes("mutes battery and signal"));
  check("Power is read-only", !buttons(rowCell(root, "Power")).length);
  check("no Exclude this device", !rowCell(root, "Excluded") && !anyButton(root, "Exclude this device"));
  check("every device mute button stays", ["Mute freeze", "Mute unavailable", "Mute everything"].every((w) => buttons(rowCell(root, "Muted")).includes(w)),
    buttons(rowCell(root, "Muted")));
  check("no Mute by label", !anyButton(root, "Mute by label"));
  check("no rhythm or wait rule for a device that is reporting", !text(root).includes("Its Rhythm") && !rowCell(root, "Wait rule"));
  // A device its hub judges shows no gaps, as in Advanced (rule STACK-10).
  ({ root } = await open({ __mode: "simple" }, (p) => {
    p.status.category = "never_reported";
    p.status.judged_by = { how: "hub", hub_id: "hub1", hub_name: "Garage Smart Bridge", hub_page: false };
  }));
  check("a device judged by its hub shows no Gaps in Simple", !text(root).includes("Gaps, Last 14 Days"));
  ({ root } = await open({ __mode: "simple" }, (p) => { withBattery(p); p.battery.now = 15.5; p.status.category = "reporting"; }));
  check("a level reads as reported, 15.5% (0.27.1)", text(root).includes("15.5% now") && !text(root).includes("16% now"));
  check("no history ranges and no signal chart", !anyButton(root, "30 Days") && !text(root).includes("Signal median") && !root.querySelector("[aria-label=\"Time range for the graphs\"]"), text(root).match(/Signal.{0,40}/g));
  check("the battery chart with its expected fall", !!root.querySelector(".futurechart polygon"));
  check("in words", text(root).includes("Expected empty in about 4 to 6 weeks."));
  check("and only once", text(root).split("about 4 to 6 weeks").length === 2, text(root).match(/.{0,30}about 4 to 6 weeks.{0,10}/g));
  // Door 2nd Bedroom: falling, not soon, and
  // no time left said anywhere in Simple.
  ({ root } = await open({ __mode: "simple" }, (p) => {
    withBattery(p); p.status.category = "reporting";
    Object.assign(p.battery, { now: 40, sentence: "Falling about 1.6 points a week, at a steady pace.", left: "about 8 to 11 weeks", left_soon: false, target: 0 });
  }));
  check("a time left that is not soon is said under the sentence", text(root).includes("at a steady pace. Empty in about 8 to 11 weeks."),
    text(root).match(/Falling.{0,80}/));
  ({ root } = await open({ __mode: "simple" }, (p) => {
    withBattery(p); p.status.category = "reporting";
    Object.assign(p.battery, { now: 40, sentence: "Falling about 1.6 points a week.", left: "about 8 to 11 weeks", left_soon: false, target: 20 });
  }));
  check("or the day it reaches your threshold", text(root).includes("Falling about 1.6 points a week. It reaches your 20% in about 8 to 11 weeks."),
    text(root).match(/Falling.{0,80}/));
  ({ root } = await open({ __mode: "simple" }, (p) => { withBattery(p); p.battery.now = 15.5; p.status.category = "reporting"; }));
  check("Last seen sensor shows while it is switched off", !!rowCell(root, "Last seen sensor"));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.identity.actions.last_seen_off = false; p.status.category = "frozen"; }));
  check("and not once it is on", !rowCell(root, "Last seen sensor"));
  check("a frozen device shows its rhythm and wait rule", text(root).includes("Its Rhythm") && !!rowCell(root, "Wait rule"));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.identity.node_status = "alive"; }));
  check("a live Z-Wave node's status row is hidden", !rowCell(root, "Z-Wave status"));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.identity.node_status = "dead"; }));
  check("a dead one's shows", !!rowCell(root, "Z-Wave status"));
  ({ root } = await open({ __mode: "simple" }, (p) => {
    p.status.category = "reporting";
    p.readings = [{ kind: "signal", entity_id: "sensor.porch_linkquality", value: 120 }];
    p.signal.railed_days = [0, 0, 0];
  }));
  check("a signal that is not the trouble is hidden", !labelsOf(root).includes("[Signal]"), labelsOf(root));
  ({ root } = await open({ __mode: "simple" }, (p) => {
    p.status.category = "reporting";
    p.readings = [{ kind: "signal", entity_id: "sensor.porch_linkquality", value: 0 }];
    p.signal.railed_days = [0, 0, 3];
  }));
  check("the signal shows when it is the trouble", labelsOf(root).includes("[Signal]") && !!rowCell(root, "Signal sensor"), labelsOf(root));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.identity.actions.excluded = { here: true, integration: false }; }));
  check("an exclusion already made still shows its way back", !!anyButton(root, "Cancel the exclusion"));

  console.log("Mute by label, in Advanced");
  let calls;
  ({ root, calls } = await open({ __mode: "advanced" }));
  check("the Muted row offers Mute by label", !!buttonIn(rowCell(root, "Muted"), "Mute by label"));
  await click(buttonIn(rowCell(root, "Muted"), "Mute by label"));
  check("the picker fetches the labels", calls.some((c) => c.type === "device_sentinel/device_choices"));
  check("each label with how many devices carry it", text(root).includes("Garage, on 3 devices") && text(root).includes("Quiet, on 1 device"));
  const kind = rowCell(root, "Muted").querySelector("select");
  kind.value = "battery";
  kind.dispatchEvent(new window.Event("change"));
  await settle();
  const garage = [...rowCell(root, "Muted").querySelectorAll("label.pick")].find((l) => l.textContent.startsWith("Garage")).querySelector("input");
  garage.checked = true;
  garage.dispatchEvent(new window.Event("change"));
  await settle();
  check("it says what the mute reaches before it saves",
    text(root).includes("Garage is on 3 devices and goes on this one too. Muting it for battery mutes all 4 for battery."), text(root).slice(0, 0));
  await click(buttonIn(rowCell(root, "Muted"), "Mute by label"));
  const sent = calls.filter((c) => c.type === "device_sentinel/device_label_mute");
  check("Mute by label sends the device, the kind and the label", sent.length === 1 && sent[0].kind === "battery"
    && sent[0].label_id === "garage" && sent[0].device_id === DEVICE, sent);

  ({ root, calls } = await open({ __mode: "advanced" }));
  await click(buttonIn(rowCell(root, "Muted"), "Mute by label"));
  const typed = rowCell(root, "Muted").querySelector('input[aria-label="New label"]');
  typed.value = "garage ";
  typed.dispatchEvent(new window.Event("input"));
  await settle();
  const sameBox = rowCell(root, "Muted").querySelector('input[aria-label="New label"]') === typed;
  check("typing repaints nothing, so the first click reaches the button", sameBox);
  check("a typed name that is already a label says how many devices carry it",
    text(root).includes("Garage is on 3 devices and goes on this one too."), text(root).slice(0, 0));
  await click(buttonIn(rowCell(root, "Muted"), "Mute by label"));
  const byName = calls.filter((c) => c.type === "device_sentinel/device_label_mute");
  check("and saves that label, not a new one", byName.length === 1 && byName[0].label_id === "garage" && !byName[0].name, byName);

  // Simple asks for nothing more than it must (rule DASH-04). No
  // Rename, no Use the 14-Day Trimmed Maximum, and no
  // turn-on buttons; those sensors are turned on from the
  // Recommendations cards. The Mute buttons stay.
  console.log("Simple's device page asks for nothing extra (rule DASH-04)");
  ({ root } = await open({ __mode: "simple" }, (p) => { p.status.category = "reporting"; }));
  const nameMarks = (r) => [...rowCell(r, "Name").querySelectorAll("button")].map((b) => b.getAttribute("aria-label") || b.textContent);
  check("Simple: the Name row has no Rename mark", !nameMarks(root).length && rowCell(root, "Name").textContent === "Button Randy Night Table", nameMarks(root));
  check("Simple: a switched-off Last Seen says so, with no button", /switched off/.test(rowCell(root, "Last seen sensor").textContent)
    && !buttons(rowCell(root, "Last seen sensor")).length, buttons(rowCell(root, "Last seen sensor")));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.status.category = "reporting"; p.identity.node_status = "off"; }));
  check("Simple: a switched-off Z-Wave status says so, with no button", /switched off/.test(rowCell(root, "Z-Wave status").textContent)
    && !buttons(rowCell(root, "Z-Wave status")).length, buttons(rowCell(root, "Z-Wave status")));
  ({ root } = await open({ __mode: "simple" }, (p) => { p.status.category = "reporting"; p.identity.actions.battery_off = true; }));
  check("Simple: a switched-off Battery sensor says so, with no button", /switched off/.test(rowCell(root, "Battery sensor").textContent)
    && !buttons(rowCell(root, "Battery sensor")).length, buttons(rowCell(root, "Battery sensor")));
  ({ root } = await open({ __mode: "simple" }, (p) => {
    p.status.category = "reporting"; p.identity.actions.signal_off = true; p.signal.railed_days = [0, 0, 3];
  }));
  check("Simple: a switched-off Signal sensor says so, with no button", !!rowCell(root, "Signal sensor")
    && /switched off/.test(rowCell(root, "Signal sensor").textContent) && !buttons(rowCell(root, "Signal sensor")).length,
    rowCell(root, "Signal sensor") && buttons(rowCell(root, "Signal sensor")));
  const frozenLognormal = (p) => {
    p.status.category = "frozen"; p.status.rule = "Log-Normal Percentile";
    p.rhythm.rules = { ...(p.rhythm.rules || {}), in_use: "lognormal" };
  };
  ({ root } = await open({ __mode: "simple" }, frozenLognormal));
  check("Simple: a frozen device's Wait rule offers no Use the 14-Day Trimmed Maximum",
    !!rowCell(root, "Wait rule") && !anyButton(root, "Use the 14-Day Trimmed Maximum") && !text(root).includes("press Use the 14-Day"),
    rowCell(root, "Wait rule") && rowCell(root, "Wait rule").textContent);
  check("Simple: the Mute buttons stay", ["Mute freeze", "Mute everything"].every((w) => buttons(rowCell(root, "Muted")).includes(w)),
    buttons(rowCell(root, "Muted")));
  // Advanced keeps every one of them.
  ({ root } = await open({ __mode: "advanced" }, (p) => { p.status.category = "reporting"; p.identity.node_status = "off"; p.identity.actions.battery_off = true; }));
  check("Advanced keeps Rename and the turn-on buttons", nameMarks(root).includes("Rename")
    && buttons(rowCell(root, "Last seen sensor")).includes("Turn on its Last Seen")
    && buttons(rowCell(root, "Z-Wave status")).includes("Turn it on") && buttons(rowCell(root, "Battery sensor")).includes("Turn it on"));
  ({ root } = await open({ __mode: "advanced" }, frozenLognormal));
  check("Advanced keeps Use the 14-Day Trimmed Maximum", !!anyButton(root, "Use the 14-Day Trimmed Maximum"));

  // Firmware in Advanced only (rule DEV-15).
  const withFirmware = (p) => { p.identity.hw_version = "2"; p.identity.firmware = { current: "9.8.7", history: [{ version: "9.8.7", since: "2025-10-20T22:40:00+00:00" }] }; };
  ({ root } = await open({ __mode: "simple" }, withFirmware));
  check("Simple: no Firmware row", !rowCell(root, "Firmware") && !text(root).includes("9.8.7"), labelsOf(root));
  ({ root } = await open({ __mode: "advanced" }, withFirmware));
  check("Advanced: the Firmware row", !!rowCell(root, "Firmware"), labelsOf(root));

  console.log("Simple's integration page");
  ({ root } = await open({ __mode: "simple", __path: "/integration/test", integration: () => JSON.parse(JSON.stringify(payloads.integration)) }));
  check("no Exclude this integration", !anyButton(root, "Exclude this integration"), text(root).slice(0, 80));
  ({ root } = await open({ __mode: "advanced", __path: "/integration/test", integration: () => JSON.parse(JSON.stringify(payloads.integration)) }));
  check("Advanced keeps it", !!anyButton(root, "Exclude this integration"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
