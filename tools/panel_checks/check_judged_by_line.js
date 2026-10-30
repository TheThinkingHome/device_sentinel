// File: tools/panel_checks/check_judged_by_line.js, Version: 0.27.15 (2026-10-30)
// Panel checks: a device never judged for freezing. One rule for the
// whole page: no freeze window, no wait rule
// and no learning line, and in their place one sentence, "Judged by its
// hub, Garage Smart Bridge" with the hub's name a link to its page here,
// or Home Assistant's when the hub is not watched, or "Judged by its
// connection". The Devices tab's WINDOW column says the same. A device
// judged by being available (Matter) keeps its own words.
// Run with: LC_ALL=en_US.UTF-8 node check_judged_by_line.js [path/to/panel.js]
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
const ROWS = payloads.devices.rows;
const DEVICE = ROWS[1].device_id;

const ACTIONS = {
  area_id: "bedroom", name_by_user: "Button Randy Night Table", integration_name: "0x00158d0001",
  labels: [{ id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }, { id: "bedside", name: "Bedside", meaning: "" }],
  last_seen_off: true,
  mutes: {
    everything: { on: false, source: null, here: false },
    freeze: { on: false, source: null, here: false },
    battery: { on: true, source: "label: Quiet", here: false, labels: ["quiet"] },
    signal: { on: true, source: "label: Quiet", here: false, labels: ["quiet"] },
  },
};
const CHOICES = { areas: [{ id: "bedroom", name: "Master Bedroom" }, { id: "laundry", name: "Laundry" }],
  labels: [{ id: "garage", name: "Garage", meaning: "mutes freeze" }, { id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }] };


const HOUR = 3600;
const steady = (n, h = 1) => Array.from({ length: n }, (_, i) => (h + (i % 3) * 0.1) * HOUR);
const BOTH = {
  gaps: steady(13).concat([6 * HOUR]), set_aside: [13], scale: null,
  trimmed: 1.2 * HOUR, trimmed_days: 14, lognormal: 1.25 * HOUR, lognormal_days: 40,
  lognormal_gaps: steady(38).concat([6 * HOUR, 5.5 * HOUR]), lognormal_set_aside: [38, 39], in_use: "lognormal",
};
const READINGS = [
  { kind: "battery", entity_id: "sensor.bravo_battery" },
  { kind: "signal", entity_id: "sensor.bravo_linkquality" },
  { kind: "last_seen", entity_id: "sensor.bravo_last_seen" },
];
const NOW = new Date();
const STATES = {
  "sensor.bravo_battery": { state: "19.5", attributes: { unit_of_measurement: "%" }, last_changed: new Date(NOW - 3.2 * 3600e3).toISOString() },
  "sensor.bravo_linkquality": { state: "116", attributes: { unit_of_measurement: "lqi" }, last_changed: new Date(NOW - 4 * 60e3).toISOString() },
  "sensor.bravo_last_seen": { state: new Date(NOW - 4 * 60e3).toISOString(), attributes: {}, last_changed: new Date(NOW - 4 * 60e3).toISOString() },
};

async function open({ tweak = () => {}, states = STATES, path = `${PREFIX}/device/${DEVICE}`, answers = {} } = {}) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${path}`, virtualConsole,
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
  const events = [];
  panel.addEventListener("hass-more-info", (ev) => events.push(ev.detail));
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = message.device_id;
        page.identity.name = (ROWS.find((r) => r.device_id === message.device_id) || {}).name || "Device";
        page.identity.clock = "last_seen";
        page.identity.actions = { area_id: null, name_by_user: null, integration_name: null, labels: [], last_seen_off: false,
          mutes: { everything: { on: false }, freeze: { on: false }, battery: { on: false }, signal: { on: false } } };
        page.readings = JSON.parse(JSON.stringify(READINGS));
        // The History chart's own series sit beside the rule figures in
        // page.rhythm, under the same names the figures once used: the
        // real page carries them, and they must blank neither chart.
        const { gaps, set_aside, ...figures } = JSON.parse(JSON.stringify(BOTH));
        page.rhythm = { ...page.rhythm, gaps, set_aside, rules: figures,
          trimmed: Array(87).fill(null), lognormal: Array(87).fill(null), daily: Array(87).fill(3600) };
        page.status.rule = "40-Day Log-Normal Percentile";
        page.status.window = 2 * HOUR;
        tweak(page);
        return page;
      }
      if (kind === "device_choices") return { areas: [], labels: [] };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: JSON.parse(JSON.stringify(states)),
    themes: { darkMode: false },
  };
  panel.hass = hass;
  await settle();
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot, calls, events, hass };
}

const labelsOf = (root) => [...root.querySelectorAll("table.kv tr")].map((tr) =>
  tr.classList.contains("kvgroup") ? `[${tr.textContent}]` : tr.firstChild.textContent);
const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const HUB = "hub0garage";
const BY_HUB = (page) => ({ how: "hub", hub_id: HUB, hub_name: "Garage Smart Bridge", hub_page: page });
const statusLine = (root) => {
  const box = root.querySelector(".devstatus .statusline .muted");
  return box ? box.textContent : null;
};
const noWindow = (root, label) => {
  const text = root.textContent;
  check(`${label}: no freeze window, no wait rule, no learning line`,
    !root.querySelector(".devstatus .bar") && rowCell(root, "Wait rule") === null
    && !/Called frozen after a gap|Still learning its rhythm|not yet judged for freezing|Not enough days yet to learn/.test(text)
    && !/window \d/.test(text), { labels: labelsOf(root), line: statusLine(root) });
};

(async () => {
  console.log("\nA Lutron device whose hub is not watched, with a learned window");
  let view = await open({ tweak: (p) => {
    p.status.judged_by = BY_HUB(false);
    p.status.last_activity = new Date(NOW - 3600e3).toISOString();
  } });
  check("The status line is the one sentence", statusLine(view.root) === "Judged by its hub, Garage Smart Bridge.", statusLine(view.root));
  let link = view.root.querySelector(".devstatus .statusline .muted a");
  check("The hub's name opens Home Assistant's page for it, since it has none here",
    !!link && link.textContent === "Garage Smart Bridge" && link.getAttribute("href") === `/config/devices/device/${HUB}`,
    link && link.getAttribute("href"));
  noWindow(view.root, "Hub not watched");
  check("No gaps table either", !/Gaps, Last 14 Days/.test(view.root.textContent));
  check("Its Rhythm says the same sentence", [...view.root.querySelectorAll("p")].some((p) => p.textContent === "Judged by its hub, Garage Smart Bridge."));

  console.log("\nThe same device with no learned day yet");
  view = await open({ tweak: (p) => {
    p.status.judged_by = BY_HUB(false);
    p.status.window = null;
    p.status.last_activity = new Date(NOW - 3600e3).toISOString();
  } });
  check("It does not say it is still learning", statusLine(view.root) === "Judged by its hub, Garage Smart Bridge.", statusLine(view.root));
  noWindow(view.root, "Not yet learned");

  console.log("\nA device whose hub has a page here");
  view = await open({ tweak: (p) => { p.status.judged_by = BY_HUB(true); } });
  link = view.root.querySelector(".devstatus .statusline .muted a");
  check("The hub's name opens Device Sentinel's page for the hub",
    !!link && link.getAttribute("href").split("?")[0] === `${PREFIX}/device/${HUB}`, link && link.getAttribute("href"));

  console.log("\nA Lutron device on its hub's page layout (hub watched)");
  view = await open({ tweak: (p) => {
    p.status.judged_by = BY_HUB(true);
    p.hub = { name: "Garage Smart Bridge", device_id: HUB, up: true, since: new Date(NOW - 86400e3).toISOString(), kind: "switch", battery: false };
  } });
  check("Its Identity carries no Wait rule", rowCell(view.root, "Wait rule") === null, labelsOf(view.root));
  check("and no Called frozen", !/Called frozen after a gap/.test(view.root.textContent));

  console.log("\nAn ESPHome device judged by its connection, with learned days");
  view = await open({ tweak: (p) => {
    p.status.judged_by = { how: "connection" };
    p.status.connection = "connected";
    p.status.window = null;
  } });
  check("The status line keeps its connection words", statusLine(view.root) === "Judged by its connection: connected.", statusLine(view.root));
  check("No Wait rule reading 0s", rowCell(view.root, "Wait rule") === null && !/, 0s/.test(view.root.textContent), labelsOf(view.root));
  noWindow(view.root, "Connection");

  console.log("\nA hub, not watched, judged by its connection");
  view = await open({ tweak: (p) => { p.status.judged_by = { how: "connection" }; } });
  check("The status line reads Judged by its connection.", statusLine(view.root) === "Judged by its connection.", statusLine(view.root));
  noWindow(view.root, "Hub itself");

  console.log("\nA Matter device judged by being available keeps its words");
  view = await open({ tweak: (p) => {
    p.status.available_rule = true;
    p.status.judged_by = null;
    p.status.last_activity = new Date(NOW - 3600e3).toISOString();
  } });
  check("Not called frozen while available", /Not called frozen while Home Assistant shows it available\./.test(statusLine(view.root) || ""), statusLine(view.root));

  console.log("\nAn ordinary device keeps its window");
  view = await open({ tweak: (p) => { p.status.last_activity = new Date(NOW - 3600e3).toISOString(); } });
  check("Called frozen after a gap, and the Wait rule", /Called frozen after a gap of 2.0h/.test(statusLine(view.root) || "")
    && rowCell(view.root, "Wait rule") !== null, [statusLine(view.root), labelsOf(view.root)]);

  console.log("\nThe Devices tab's WINDOW column");
  const devices = () => {
    const reply = JSON.parse(JSON.stringify(payloads.devices));
    reply.rows[0].judged_by = BY_HUB(true);
    reply.rows[0].window = null;
    reply.rows[1].judged_by = BY_HUB(false);
    reply.rows[2].judged_by = { how: "connection" };
    reply.rows[3].judged_by = null;
    reply.rows[3].window = 7200;
    return reply;
  };
  view = await open({ path: `${PREFIX}/devices`, answers: { devices } });
  const windowCell = (name) => {
    const tr = [...view.root.querySelectorAll("tbody tr")].find((row) => row.children[0].textContent === name);
    return tr ? tr.lastChild : null;
  };
  const rows = payloads.devices.rows;
  let cell = windowCell(rows[0].name);
  check("A hub with a page: Judged by its hub, its name a link here", cell && cell.textContent === "Judged by its hub, Garage Smart Bridge"
    && cell.querySelector("a").getAttribute("href").split("?")[0] === `${PREFIX}/device/${HUB}`, cell && cell.innerHTML);
  cell = windowCell(rows[1].name);
  check("A hub without one: the link opens Home Assistant's page", cell && cell.textContent === "Judged by its hub, Garage Smart Bridge"
    && cell.querySelector("a").getAttribute("href") === `/config/devices/device/${HUB}`, cell && cell.innerHTML);
  cell = windowCell(rows[2].name);
  check("By its connection", cell && cell.textContent === "Judged by its connection", cell && cell.textContent);
  cell = windowCell(rows[3].name);
  check("Any other device keeps its window", cell && cell.textContent === "2.0h", cell && cell.textContent);
  check("No cell reads null or undefined", !/null|undefined|NaN/.test(view.root.querySelector("tbody").textContent));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
