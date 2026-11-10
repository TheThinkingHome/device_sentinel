// File: tools/panel_checks/check_device_links.js, Version: 0.28.9 (2026-11-10)
// Panel checks: a device's name opens a page that is there (rule DASH-12).
// A device Device Sentinel watches, or once watched and keeps a record
// for, opens its page here; any other device still in Home Assistant
// opens Home Assistant's own device page; one removed from Home
// Assistant is plain words. Checked where such a device can be named:
// the Daily Brief's tables, MQTT's Also on the Broker, and a network
// page's hardware Device row.
// Run with: LC_ALL=en_US.UTF-8 node check_device_links.js [path/to/panel.js]
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
const clone = (x) => JSON.parse(JSON.stringify(x));

// The house: one watched device, one set aside that was never watched,
// one set aside that was (its record kept), one excluded with its history
// gone, and "gone-1", removed from Home Assistant, in no list at all.
const WATCHED = payloads.devices.rows[0];
const CLASSIFICATION = (() => {
  const c = clone(payloads.classification);
  const row = (id, name, extra) => ({ device_id: id, name, integration: "tasmota", integration_name: "Tasmota", watched: false,
    muted: "", muted_global: "", copies: 1, type: null, area: null, labels: [], ...extra });
  c.rows.push(
    row("aside-never", "Spare Plug", { set_aside: "disabled", page: false }),
    row("aside-kept", "Old Plug", { set_aside: "disabled", page: true }),
    row("ex-gone", "Shed Plug", { set_aside: "excluded (device)", page: false }));
  return c;
})();
const DEVICES = (() => {
  const d = clone(payloads.devices);
  d.excluded = [{ device_id: "ex-gone", name: "Shed Plug", integration: "tasmota", integration_name: "Tasmota", how: "device", page: false, area: null, labels: [] }];
  return d;
})();
const NAMES = [[WATCHED.device_id, WATCHED.name], ["aside-never", "Spare Plug"], ["aside-kept", "Old Plug"], ["ex-gone", "Shed Plug"], ["gone-1", "Hall Plug"]];

const COUNTS = { frozen: 0, unavailable: 0, never_reported: 0, battery: 0, signal: 0, drops: 0 };
const NETWORK = {
  key: "z2m", name: "Zigbee2MQTT", kind: "z2m", status: { state: "ok", words: "Running", since: null },
  watched: 1, with_problem: 0, counts: COUNTS, window_days: 30, outages: [], notices: [], sensors: [], patterns: [], cards: [],
  hardware: NAMES.map(([id, name]) => ({ label: "Device", value: name, device_id: id })),
};

async function open(path, answers = {}) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${path}`, virtualConsole,
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
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "status") return { ...clone(payloads.status), dashboard: "advanced" };
      if (kind === "classification") return clone(CLASSIFICATION);
      if (kind === "devices") return clone(DEVICES);
      if (kind === "networks") return { rows: [] };
      if (kind === "network") return clone(NETWORK);
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return clone(payloads[kind]);
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    panels: {},
  };
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

// What each name became: "here", "ha" or "words".
function kinds(root) {
  const out = {};
  const pane = root.querySelector(".pane");
  for (const [id, name] of NAMES) {
    const link = [...pane.querySelectorAll("a")].find((a) => a.textContent === name);
    if (link) {
      const href = link.getAttribute("href");
      out[id] = href.startsWith(`${PREFIX}/device/`) ? "here" : href === `/config/devices/device/${id}` ? "ha" : href;
    } else if (pane.textContent.includes(name)) {
      out[id] = "words";
    }
  }
  return out;
}
const EXPECTED = { [WATCHED.device_id]: "here", "aside-never": "ha", "aside-kept": "here", "ex-gone": "ha", "gone-1": "words" };

(async () => {
  console.log("The Daily Brief's tables");
  const brief = () => {
    const b = clone(payloads.brief);
    b.events = NAMES.map(([id, name], i) => ({ when: `2026-09-25T2${i}:00:00+00:00`, who: name, device_id: id, what: "went unavailable" }));
    return b;
  };
  let { root } = await open("/daily-brief", { brief });
  check("each name in Last 24 Hours opens a page that is there", JSON.stringify(kinds(root)) === JSON.stringify(EXPECTED), kinds(root));
  // A past day's problems: today's are the Problem List, which lists
  // only devices still in Home Assistant.
  const briefNow = () => {
    const b = clone(payloads.brief);
    b.is_today = false;
    b.now = NAMES.map(([id, name], i) => ({ uid: `u${i}`, device_id: id, name, problem: "Unavailable", since: "2026-09-25T20:00:00+00:00", seconds: 60, acknowledged: false }));
    return b;
  };
  ({ root } = await open("/daily-brief", { brief: briefNow }));
  check("and each name in a past day's Problem List", JSON.stringify(kinds(root)) === JSON.stringify(EXPECTED), kinds(root));
  const briefRepeat = () => {
    const b = clone(payloads.brief);
    b.repeat = { available: true, paragraph: "", words: "",
      rows: NAMES.map(([id, name]) => ({ device_id: id, name, what: "unavailable", times: 3, when: "nights", typical: "", with: "" })) };
    return b;
  };
  ({ root } = await open("/daily-brief", { brief: briefRepeat }));
  check("and each name in Repeat Offenders", JSON.stringify(kinds(root)) === JSON.stringify(EXPECTED), kinds(root));

  console.log("MQTT's Also on the Broker");
  const integration = () => {
    const page = clone(payloads.integration);
    page.domain = "mqtt";
    page.name = "MQTT";
    page.devices = [];
    page.behind_broker = NAMES.map(([id, name]) => ({ device_id: id, name, integration: "tasmota", integration_name: "Tasmota",
      watched: id === WATCHED.device_id, muted: "", set_aside: id === WATCHED.device_id ? "" : "disabled", problem: "", acknowledged: false }));
    return page;
  };
  ({ root } = await open("/integration/mqtt", { integration }));
  check("each name opens a page that is there", JSON.stringify(kinds(root)) === JSON.stringify(EXPECTED), kinds(root));

  console.log("A network page's hardware Device row");
  ({ root } = await open("/network/z2m"));
  check("each name opens a page that is there", JSON.stringify(kinds(root)) === JSON.stringify(EXPECTED), kinds(root));

  console.log("Before the tab's lists arrive");
  const late = await open("/daily-brief", { brief, classification: () => new Promise(() => {}) });
  const early = kinds(late.root);
  check("a name keeps its page here", Object.values(early).length === 0 || Object.values(early).every((k) => k === "here"), early);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
