// Panel checks: names, Last seen and mutes on the device page and the
// Problem List (0.24.11), from Tim Plas's review of 6 October. The Last
// seen fallback is checked on real_device.json, a real mains plug's page
// built by the server, which has no Last seen sensor.
// Run with: LC_ALL=en_US.UTF-8 node check_names_and_mutes.js [path/to/panel.js]
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
    battery: { on: true, source: "label: Quiet", here: false },
    signal: { on: true, source: "label: Quiet", here: false },
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
        // real page carries them, and they blanked both charts (0.24.9).
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


const REAL = JSON.parse(fs.readFileSync(__dirname + "/real_device.json", "utf8")).device;

const SETTINGS = "/config/integrations/integration/device_sentinel";
const realPage = (tweak = () => {}) => (m) => {
  const page = JSON.parse(JSON.stringify(REAL));
  page.identity.device_id = m.device_id;
  tweak(page);
  return page;
};

(async () => {
  console.log("\nLast seen without a sensor (real data)");
  {
    const { root } = await open({ answers: { device: realPage() } });
    const cell = rowCell(root, "Last seen");
    check("A device with no Last seen sensor shows when Device Sentinel last heard it",
      cell && /heard by Device Sentinel .+ ago/.test(cell.textContent), cell && cell.textContent);
    check("It is not read as \"none\"", cell && !/^none$/.test(cell.textContent.trim()), cell && cell.textContent);
    const sensor = rowCell(root, "Last seen sensor");
    check("The Last seen sensor row still says there is none", sensor && sensor.textContent.trim().startsWith("none"),
      sensor && sensor.textContent);
    check("Nothing on the page reads NaN", !/NaN/.test(root.textContent));
  }
  {
    const { root } = await open({ answers: { device: realPage((p) => { p.status.last_activity = "not a time"; }) } });
    const cell = rowCell(root, "Last seen");
    check("A last report that cannot be read leaves \"none\", never NaN",
      cell && cell.textContent.trim() === "none" && !/NaN/.test(root.textContent), cell && cell.textContent);
  }

  console.log("\nLast seen with a sensor");
  {
    const { root } = await open();
    const cell = rowCell(root, "Last seen");
    check("A readable Last seen sensor is shown, not the fallback",
      cell && !/heard by Device Sentinel/.test(cell.textContent) && /\d/.test(cell.textContent), cell && cell.textContent);
  }
  {
    const states = JSON.parse(JSON.stringify(STATES));
    states["sensor.bravo_last_seen"].state = "unavailable";
    const { root } = await open({ states, tweak: (p) => { p.status.last_activity = new Date(Date.now() - 7 * 60e3).toISOString(); } });
    const cell = rowCell(root, "Last seen");
    check("A Last seen sensor Home Assistant cannot read falls back to Device Sentinel",
      cell && /heard by Device Sentinel/.test(cell.textContent), cell && cell.textContent);
  }

  console.log("\nMuted: where a mute set elsewhere is changed");
  {
    const { root } = await open({ answers: { device: realPage((p) => {
      p.identity.integration = "mqtt";
      p.identity.integration_name = "Zigbee2MQTT";
      p.identity.integration_title = "MQTT";
      p.identity.actions.mutes = {
        everything: { on: false, source: null, here: false },
        freeze: { on: true, source: "integration: mqtt", here: false },
        battery: { on: true, source: "label: Quiet", here: false },
        signal: { on: true, source: "device", here: true },
      };
      p.identity.muted = "freeze (integration: mqtt), battery (label: Quiet), signal (device)";
    }) } });
    const cell = rowCell(root, "Muted");
    const notes = cell ? [...cell.querySelectorAll(".actnote")].map((n) => n.textContent) : [];
    check("A label's mute says so and names its section",
      notes.includes("Battery is muted by the label Quiet. Change it in Device Sentinel's settings, Configure, Low Battery."), notes);
    check("An integration's mute names the integration, MQTT, not the device's Zigbee2MQTT",
      notes.includes("Freeze is muted by the integration MQTT. Change it in Device Sentinel's settings, Configure, Freeze Detection."), notes);
    check("A mute set on the device itself, which the page can lift, adds no note",
      !notes.some((n) => n.startsWith("Signal is muted")), notes);
    const links = cell ? [...cell.querySelectorAll(".actnote a")] : [];
    check("Each note links to Device Sentinel's settings", links.length === 2 && links.every((a) => a.getAttribute("href") === SETTINGS),
      links.map((a) => a.getAttribute("href")));
  }
  {
    const { root } = await open({ answers: { device: realPage() } });
    const cell = rowCell(root, "Muted");
    check("Nothing muted adds no note", cell && cell.querySelectorAll(".actnote:not(:empty)").length === 0,
      cell && cell.textContent);
  }

  console.log("\nZigbee2MQTT named on the device page and the Problem List");
  {
    const { root } = await open({ answers: { device: realPage((p) => {
      p.identity.integration = "mqtt"; p.identity.integration_name = "Zigbee2MQTT"; p.identity.integration_title = "MQTT";
    }) } });
    const head = root.querySelector(".pagehead");
    const link = head ? [...head.querySelectorAll("a")].find((a) => a.textContent === "Zigbee2MQTT") : null;
    check("The page header names the device's integration Zigbee2MQTT", Boolean(link), head && head.textContent);
    check("The name still opens MQTT's integration page", link && /\/integration\/mqtt(\?|$)/.test(link.getAttribute("href")),
      link && link.getAttribute("href"));
  }
  {
    const problems = { rows: [
      { uid: "z", device_id: DEVICE, name: "S73 Door Tilt", integration: "mqtt", integration_name: "Zigbee2MQTT",
        problem: "unavailable", since: new Date(Date.now() - 3600e3).toISOString(), acknowledged: false, mutes: ["freeze"], power: null },
      { uid: "p", device_id: ROWS[0].device_id, name: "Kitchen Panel", integration: "mqtt", integration_name: "MQTT",
        problem: "unavailable", since: new Date(Date.now() - 3600e3).toISOString(), acknowledged: false, mutes: ["freeze"], power: null },
    ] };
    const { root } = await open({ path: `${PREFIX}/problem-list`, answers: { problem_list: () => problems } });
    const cells = [...root.querySelectorAll("tbody tr")].map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent));
    const z = cells.find((c) => c.includes("S73 Door Tilt"));
    const p = cells.find((c) => c.includes("Kitchen Panel"));
    check("The Problem List names a Zigbee2MQTT device's integration Zigbee2MQTT", z && z.includes("Zigbee2MQTT"), z);
    check("Another MQTT device keeps MQTT", p && p.includes("MQTT"), p);
    const links = [...root.querySelectorAll("tbody a")].filter((a) => a.textContent === "Zigbee2MQTT");
    check("Its link opens MQTT's page", links.length === 1 && /\/integration\/mqtt(\?|$)/.test(links[0].getAttribute("href")),
      links.map((a) => a.getAttribute("href")));
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
