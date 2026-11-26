// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_recommendation_order.js, Version: 0.30.7 (2026-11-26)
//
// The Recommendations tab: most severe first (rule REC-01),
// each card drawn on its own and a missing day read as unknown (rule
// REC-14), cards counted rather than rows (rule REC-08), rows selected
// and answered together (rule REC-04), and Turn All On on a switched-off
// card (rule REC-05).
// Run with: LC_ALL=en_US.UTF-8 node check_recommendation_order.js [path/to/panel.js]
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
const STATES = {};

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
        // page.rhythm, under the same names as the figures: the
        // real page carries them, and they must blank neither chart.
        const { gaps, set_aside, ...figures } = JSON.parse(JSON.stringify(BOTH));
        page.rhythm = { ...page.rhythm, gaps, set_aside, rules: figures,
          trimmed: Array(87).fill(null), lognormal: Array(87).fill(null), daily: Array(87).fill(3600) };
        page.status.rule = "40-Day Log-Normal Percentile";
        page.status.window = 2 * HOUR;
        tweak(page);
        return page;
      }
      if (kind === "device_choices") return { areas: [{ id: "porch", name: "Porch" }, { id: "hall", name: "Hall" }], labels: [] };
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


const KEY = JSON.stringify(["IKEA", "TRADFRI", ""]);
const row = (id, name, extra = {}) => ({ device_id: id, name, area: null, acknowledged: false, ...extra });
const CARDS = () => [
  { kind: "power", title: "Power Not Set", grouped: true, rank: 24, active: 2, body: "3 devices have no battery or power source set.",
    devices: [row("p1", "Bulb 1", { model_key: KEY, model: "IKEA TRADFRI" }), row("p2", "Bulb 2", { model_key: KEY, model: "IKEA TRADFRI" }), row("p3", "Lone")] },
  { kind: "battery_off", title: "Battery Sensor Switched Off", rank: 5, active: 3, body: "3 devices have a battery sensor that is switched off.",
    devices: [row("b1", "Door"), row("b2", "Window", { by_user: true, acknowledged: true }), row("b3", "Leak")] },
  { kind: "battery_confirm", title: "Confirm Battery Replacement", rank: 12, active: 2, body: "",
    devices: [row("c1", "Remote", { day: null, words: { done: "replaced" } }), row("c2", "Remote 2", { day: "not a day", words: { done: "replaced" } })] },
  { kind: "area", title: "No Area Assigned", rank: 21, active: 2, body: "2 devices have no area.", devices: [row("a1", "Plug A"), row("a2", "Plug B")] },
  { kind: "slow", title: "Slow Reporting Devices", rank: 17, active: 1, body: "", devices: "not a list" },
];
const LINES = () => [
  { key: "router:unifi", text: "Eliminate noise: watching unifi.", rank: 19, acknowledged: false, simple: false },
  { key: "no_target", text: "Notifications Recipient Not Set: no target.", rank: 1, acknowledged: false, simple: true },
];

(async () => {
  let ticked = {};
  const recs = () => {
    const devices = CARDS();
    for (const card of devices) if (Array.isArray(card.devices)) for (const r of card.devices) if (ticked[r.device_id]) r.acknowledged = true;
    return { lines: LINES(), devices, closing: "", network_rank: 16,
      networks: [{ key: "zigbee", name: "Zigbee", cards: [{ key: "z1", title: "Zigbee Channel Crowded", acknowledged: false, body: "x" }] }],
      power: { choices: ["AA", "Mains Powered", "Other"], wired: ["Mains Powered"], quantity: [1, 4], other: "Other" },
      types: { choices: ["Plug"], other: "Other" } };
  };
  const page = await open({ path: `${PREFIX}/recommendations`, answers: { recommendations: recs,
    network_card: () => ({}), device_area: () => ({}), device_turn_on: () => ({}), device_power: () => ({}) } });
  const titles = () => [...page.root.querySelectorAll(".pane article.rec")].map((a) => (a.querySelector("h3") || {}).textContent || "");
  console.log("Most severe first (rule REC-01)");
  const order = titles();
  const at = (start) => order.findIndex((t) => t.startsWith(start));
  check("A missing notification target comes first", at("Notifications Recipient Not Set") === 0, order);
  check("Then the switched-off battery sensor, then the battery question",
    at("Battery Sensor Switched Off") === 1 && at("Confirm Battery Replacement") === 2, order);
  check("The network's card sits after the alarms and before the noise",
    at("Zigbee") > at("Confirm Battery Replacement") && at("Zigbee") < at("Eliminate noise"), order);
  check("The inventory comes last", at("Power Not Set") === order.length - 1, order);

  console.log("\nEach card drawn on its own (rule REC-14)");
  check("A card that cannot be drawn says so under its own title",
    order.includes("Slow Reporting Devices") && page.root.textContent.includes("Device Sentinel could not draw this card."), order);
  check("The rest of the tab still draws", order.length === 8, order.length);
  const confirm = page.root.querySelector('article.rec[data-kind="battery_confirm"]');
  check("A battery question with no day reads as an unknown day", confirm && confirm.textContent.includes("detected an unknown day"),
    confirm && confirm.textContent.slice(0, 300));

  console.log("\nCards, not rows (rule REC-08)");
  const tab = [...page.root.querySelectorAll(".tab")].map((t) => t.textContent).find((t) => t.startsWith("Recommendations"));
  // The card that could not be drawn is not counted: what it holds is not known.
  check("The tab counts the seven cards it could read", tab === "Recommendations (7)", tab);
  check("The grouped card counts its answers: one model, one lone device", at("Power Not Set (2)") >= 0, order);

  console.log("\nSelect rows and answer once (rule REC-04)");
  const power = page.root.querySelector('article.rec[data-kind="power"]');
  power.querySelector("details").open = true;
  const boxes = [...power.querySelectorAll("td.selhold input")];
  check("Each row has a box to select it", boxes.length >= 2, boxes.length);
  const bar = power.querySelector(".recselect");
  check("The answer at the top waits for a selection", bar && bar.hidden);
  const all = power.querySelector('input[aria-label="Select all"]');
  all.checked = true; all.dispatchEvent(new page.window.Event("change"));
  check("Select all says what is selected", !bar.hidden && bar.textContent.startsWith("1 model and 1 device selected, 3 devices"), bar.textContent);
  const choose = bar.querySelector('select[aria-label="What powers the selected devices"]');
  choose.value = "Mains Powered"; choose.dispatchEvent(new page.window.Event("change"));
  [...bar.querySelectorAll("button")].find((b) => b.textContent === "Set selected").click();
  await settle(); await settle(); await settle();
  const powered = page.calls.filter((c) => c.type === "device_sentinel/device_power");
  check("One answer for the model, one for the lone device, each from the tab",
    JSON.stringify(powered.map((c) => [c.device_id, c.choice, c.source])) === JSON.stringify([["p1", "Mains Powered", "recommendations"], ["p3", "Mains Powered", "recommendations"]]), powered);
  check("A wired answer sends no count", powered.every((c) => c.quantity === undefined), powered);

  const area = page.root.querySelector('article.rec[data-kind="area"]');
  area.querySelector("details").open = true;
  await settle(); await settle();
  const one = area.querySelector("td.selhold input");
  one.checked = true; one.dispatchEvent(new page.window.Event("change"));
  const areaBar = area.querySelector(".recselect");
  check("One device selected says so", areaBar.textContent.startsWith("1 device selected") && !areaBar.textContent.includes(", 1 device"), areaBar.textContent);
  const where = areaBar.querySelector('select[aria-label="Which area for the selected devices"]');
  check("The selected rows' area chooser is there", Boolean(where), areaBar.innerHTML.slice(0, 200));
  where.value = "porch"; where.dispatchEvent(new page.window.Event("change"));
  [...areaBar.querySelectorAll("button")].find((b) => b.textContent === "Set selected").click();
  await settle(); await settle();
  const moved = page.calls.filter((c) => c.type === "device_sentinel/device_area");
  check("Only the selected device moves", moved.length === 1 && moved[0].device_id === "a1" && moved[0].area_id === "porch", moved);

  console.log("\nTurn All On (rule REC-05)");
  const off = page.root.querySelector('article.rec[data-kind="battery_off"]');
  const button = [...off.querySelectorAll("button")].find((b) => b.textContent === "Turn All On");
  check("The switched-off card offers Turn All On", Boolean(button));
  button.click();
  await settle(); await settle();
  const turned = page.calls.filter((c) => c.type === "device_sentinel/device_turn_on");
  check("Only what Home Assistant switched off is turned on, never what the person did",
    JSON.stringify(turned.map((c) => [c.device_id, c.kind])) === JSON.stringify([["b1", "battery"], ["b3", "battery"]]), turned);
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
