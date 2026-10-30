// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_device_page_text.js, Version: 0.27.15 (2026-10-30)
//
// Panel checks: the device page reads at one size (rule DASH-06).
// Secondary text such as "heard by Device Sentinel 9m ago" and
// "heartbeat: when ZHA last heard it" must not drop to 11 or 12px.
// Headings, column headings, the big figures, buttons, chips and the
// charts' own labels keep their sizes; every other text on the page reads 14px, the heartbeat
// line is plain grey text and a sensor's name is in the page's own font.
// Other tabs are unchanged.
//
// jsdom does not apply a stylesheet inside a shadow root, and it does not
// pass a size down from parent to child: every text read "medium" there.
// So each painted page is copied into the light DOM beside the panel's own
// stylesheet, and a text's size is worked out by walking up its parents.
// Run with: LC_ALL=en_US.UTF-8 node check_device_page_text.js [path/to/panel.js]
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
        // page.rhythm, under the same names as the figures: the real
        // page carries them, and they must blank neither chart.
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

// Controls, headings (a table's column headings among them, the same
// capitals as on every tab), the big figures and the charts' own labels
// keep their sizes; everything else on the page is text.
const KEEPS_ITS_SIZE = [
  "button", "select", "option", "input", "textarea", "svg", "svg *", "h2", "h3", "th",
  ".chip", ".reading .v", ".stat .v", ".ruleline span", ".statusline > div:first-child",
].join(", ");

function lightCopy(window, root) {
  const doc = window.document;
  const style = doc.createElement("style");
  style.textContent = root.querySelector("style").textContent;
  const host = doc.createElement("div");
  host.innerHTML = [...root.childNodes].filter((n) => n.nodeName !== "STYLE").map((n) => n.outerHTML || "").join("");
  doc.body.replaceChildren(style, host);
  return host;
}

function sizeOf(window, node) {
  let scale = 1;
  for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
    const fs = window.getComputedStyle(n).fontSize;
    if (/px$/.test(fs)) return `${Math.round(parseFloat(fs) * scale * 10) / 10}px`;
    if (/em$/.test(fs)) scale *= parseFloat(fs);
  }
  return "Home Assistant's own size";
}

function offenders(window, host, scope) {
  const out = [];
  for (const node of host.querySelectorAll(`${scope} *`)) {
    const own = [...node.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(" ");
    if (!own || node.matches(KEEPS_ITS_SIZE)) continue;
    const size = sizeOf(window, node);
    if (size !== "14px") out.push(`${size}: ${own.slice(0, 48)}`);
  }
  return out;
}

const PAGES = [
  ["the heartbeat is ZHA's own", (p) => { p.identity.clock = "zha"; p.readings = p.readings.filter((r) => r.kind !== "last_seen"); }],
  ["the heartbeat is its Last Seen sensor", (p) => { p.identity.clock = "last_seen"; }],
  ["no Last Seen sensor, heard by Device Sentinel", (p) => { p.identity.clock = "entities"; p.readings = p.readings.filter((r) => r.kind !== "last_seen"); }],
  ["its Last Seen switched off", (p) => { p.identity.actions = JSON.parse(JSON.stringify(ACTIONS)); p.readings = p.readings.filter((r) => r.kind !== "last_seen"); }],
];

(async () => {
  console.log("\nThe device page reads at one size (0.26.1)");
  // The check is only worth its pass if jsdom reports the stylesheet's
  // sizes at all: a table cell reads 14px and a chip 13px.
  {
    const { window, root } = await open({ tweak: PAGES[0][1] });
    const host = lightCopy(window, root);
    const cell = host.querySelector("table.kv td");
    const chip = host.querySelector(".chip");
    check("jsdom reports the stylesheet's sizes (a cell 14px, a chip 13px)",
      cell && chip && sizeOf(window, cell) === "14px" && sizeOf(window, chip) === "13px",
      [cell && sizeOf(window, cell), chip && sizeOf(window, chip)]);
  }
  for (const [label, tweak] of PAGES) {
    const { window, root } = await open({ tweak });
    const host = lightCopy(window, root);
    const wrong = offenders(window, host, ".pane");
    check(`Every text reads 14px when ${label}`, wrong.length === 0, wrong.slice(0, 8));
  }
  {
    const { window, root } = await open({ tweak: PAGES[0][1] });
    const host = lightCopy(window, root);
    const tag = host.querySelector(".hbtag");
    check("The heartbeat line reads \"heartbeat: when ZHA last heard it\"", tag && tag.textContent === "heartbeat: when ZHA last heard it", tag && tag.textContent);
    const cs = tag ? window.getComputedStyle(tag) : null;
    check("The heartbeat line is plain grey text, not a pill",
      cs && (cs.paddingLeft === "0px" || cs.padding === "0px") && /none|transparent|rgba\(0, 0, 0, 0\)/.test(cs.background || cs.backgroundColor || "none"),
      cs && [cs.padding, cs.background]);
    const sensor = host.querySelector(".entitylink");
    const family = sensor ? window.getComputedStyle(sensor).fontFamily : "";
    check("A sensor's name is in the page's own font", sensor && !/mono/i.test(family), family);
    const chip = host.querySelector(".pane .chip");
    check("Buttons and chips keep 13px", chip && sizeOf(window, chip) === "13px", chip && sizeOf(window, chip));
    const word = host.querySelector(".statusline > div:first-child");
    check("The status word keeps its 18px", word && sizeOf(window, word) === "18px", word && sizeOf(window, word));
  }
  {
    const { window, root } = await open({ answers: { device: (m) => {
      const page = JSON.parse(JSON.stringify(REAL));
      page.identity.device_id = m.device_id;
      return page;
    } } });
    const host = lightCopy(window, root);
    const wrong = offenders(window, host, ".pane");
    check("Every text reads 14px on a page built from a real device's data", wrong.length === 0, wrong.slice(0, 8));
  }
  {
    // Other tabs are unchanged: the Integrations tab's small text keeps
    // 12px, reached from a device page the way a person reaches it.
    const { window, root, panel } = await open({ tweak: PAGES[0][1] });
    window.history.pushState(null, "", `${PREFIX}/integrations`);
    window.dispatchEvent(new window.Event("location-changed"));
    await settle();
    await settle();
    check("Leaving the device page leaves its size behind", !root.querySelector(".pane").classList.contains("devpage"));
    const host = lightCopy(window, root);
    const small = host.querySelector(".pane .small");
    check("Other tabs keep their sizes (the Integrations tab's small text reads 12px)",
      small && sizeOf(window, small) === "12px", small && [small.textContent.slice(0, 40), sizeOf(window, small)]);
  }
  // A device judged by its connection alone: one line, no window bar,
  // no "still learning".
  for (const [word, expected] of [["connected", "Judged by its connection: connected."], ["dropped", "Judged by its connection: dropped."]]) {
    const { root } = await open({ tweak: (p) => { p.status.connection = word; p.status.window = null; } });
    const line = root.querySelector(".statusline .muted");
    check(`A connection-only device reads "${expected}"`, line && line.textContent === expected, line && line.textContent);
    check(`A connection-only device ${word} has no window bar`, !root.querySelector(".devstatus .bar"));
  }
  // A Matter device of a type that reports only on use (rule STACK-06):
  // its page says how it is judged, with no window bar or wait rule.
  {
    const { root } = await open({ tweak: (p) => { p.status.available_rule = true; p.status.window = 7200; } });
    const line = root.querySelector(".statusline .muted");
    check("A Matter device judged by being available says so",
      line && line.textContent.endsWith("Not called frozen while Home Assistant shows it available."), line && line.textContent);
    check("It has no window bar", !root.querySelector(".devstatus .bar"));
    check("Nor a wait rule", !root.querySelector(".pane").textContent.includes("Wait rule"));
  }
  {
    const source = fs.readFileSync(PANEL, "utf8");
    const print = (/const PRINT_STYLE = `([\s\S]*?)`;/.exec(source) || [])[1] || "";
    check("A printed device page keeps its 12px", /\.pane\.devpage \{ font-size: 12px; \}/.test(print));
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
