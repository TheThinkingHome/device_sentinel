// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_recommendation_models.js, Version: 0.28.10 (2026-11-10)
//
// Panel checks: the Recommendations tab's cards whose answer covers a
// model, one row per model (rules DEV-06, REC-04). Power Not Set, Type
// Not Set and Model With More Than One Type: a row for each model with
// the maker and model, how many devices, one chooser and one tick for
// them all, and its devices listed when the row is opened. A device with
// no model keeps its own row. The title counts the models and the
// devices.
// Run with: LC_ALL=en_US.UTF-8 node check_recommendation_models.js [path/to/panel.js]
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

const L42 = JSON.stringify(["LightwaveRF", "L42MK3", ""]);
const L40 = JSON.stringify(["LightwaveRF", "L40MK2", ""]);
const row = (id, name, key, model, extra = {}) => ({ device_id: id, name, area: "Kitchen", acknowledged: false, model_key: key, model, ...extra });
const POWER = {
  kind: "power", title: "Power Not Set", grouped: true, body: "5 devices have no battery or power source set, in 2 models.",
  devices: [
    row("a1", "Socket 1", L42, "LightwaveRF L42MK3"), row("a2", "Socket 2", L42, "LightwaveRF L42MK3"),
    row("a3", "Socket 3", L42, "LightwaveRF L42MK3"), row("b1", "Dimmer", L40, "LightwaveRF L40MK2"),
    row("c1", "Accessory", null, ""),
  ],
};
const MIXED = {
  kind: "mixed_types", title: "Model With More Than One Type", grouped: true, body: "1 model has devices of more than one type.",
  devices: [
    row("m1", "Unit A", L42, "LightwaveRF L42MK3", { type: "Plug" }), row("m2", "Unit B", L42, "LightwaveRF L42MK3", { type: "Plug" }),
    row("m3", "Unit C", L42, "LightwaveRF L42MK3", { type: "Light" }),
  ],
};

(async () => {
  const ticks = {};
  const recs = () => {
    const card = JSON.parse(JSON.stringify(POWER));
    for (const r of card.devices) r.acknowledged = Boolean(ticks[r.device_id]);
    return { lines: [], devices: [card, JSON.parse(JSON.stringify(MIXED))], closing: "",
      power: { choices: ["AA", "Mains"], wired: ["Mains"], quantity: [1, 4], other: "Other" }, types: { choices: ["Plug", "Light"], other: "Other" } };
  };
  const page = await open({ path: `${PREFIX}/recommendations`, answers: {
    recommendations: recs,
    recommendation_ack: (message) => { ticks[message.device_id] = message.on; return {}; },
    device_power: () => ({}),
  } });
  const card = (kind) => [...page.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === kind);
  console.log("One row per model (rules DEV-06, REC-04)");
  const power = card("power");
  check("The title counts the models and the devices", power.querySelector("h3").textContent === "Power Not Set (2 models, 5 devices)",
    power.querySelector("h3").textContent);
  const rows = [...power.querySelectorAll("table > tbody > tr")];
  check("Three rows: the model of three, the model of one, and the device with no model", rows.length === 3, rows.length);
  const grouped = rows.find((tr) => tr.querySelector("details summary"));
  check("The model's row names it and counts its devices", grouped && grouped.querySelector("summary").textContent === "LightwaveRF L42MK3, 3 devices",
    grouped && grouped.querySelector("summary").textContent);
  const links = grouped ? [...grouped.querySelectorAll("details li a")].map((a) => a.textContent) : [];
  check("Opened, it lists each of its devices, each opening its page", JSON.stringify(links) === JSON.stringify(["Socket 1", "Socket 2", "Socket 3"])
    && grouped.querySelector("details li a").getAttribute("href").startsWith(`${PREFIX}/device/a1`), links);
  check("A device with no model keeps its own row", rows.some((tr) => tr.textContent.includes("Accessory") && !tr.querySelector("details")));
  const outer = [...power.children].find((child) => child.tagName === "DETAILS");
  const outerSummary = outer ? outer.querySelector("summary").textContent : null;
  check("The summary counts both", outerSummary === "Show the 2 models and 5 devices", outerSummary);
  // One answer for the model.
  const select = grouped.querySelector("select");
  select.value = "AA";
  select.dispatchEvent(new page.window.Event("change"));
  [...grouped.querySelectorAll("button.chip")].find((b) => b.textContent === "Save").click();
  await settle(); await settle();
  const saved = page.calls.filter((c) => c.type === "device_sentinel/device_power");
  check("One save, on one of the model's devices, sets the model", saved.length === 1 && saved[0].device_id === "a1" && saved[0].choice === "AA", saved);
  // One tick for the model.
  const fresh = [...card("power").querySelectorAll("table > tbody > tr")].find((tr) => tr.querySelector("details summary"));
  const box = fresh.querySelector('td.ackhold input[type="checkbox"]');
  box.checked = true;
  box.dispatchEvent(new page.window.Event("change"));
  await settle(); await settle(); await settle();
  const acks = page.calls.filter((c) => c.type === "device_sentinel/recommendation_ack").map((c) => c.device_id);
  check("One tick acknowledges each of the model's devices", JSON.stringify(acks) === JSON.stringify(["a1", "a2", "a3"]), acks);
  check("The title then counts what is left", card("power").querySelector("h3").textContent === "Power Not Set (1 model, 2 devices)",
    card("power").querySelector("h3").textContent);
  console.log("\nModel With More Than One Type");
  const mixed = card("mixed_types");
  const mixedRows = [...mixed.querySelectorAll("table > tbody > tr")];
  check("One row for the model, with how its devices split", mixedRows.length === 1 && mixedRows[0].textContent.includes("1 Light, 2 Plug"),
    mixedRows.map((tr) => tr.textContent));
  check("Each device in its list says its type", [...mixedRows[0].querySelectorAll("details li")].map((li) => li.textContent).join("|") === "Unit A, Plug, Kitchen|Unit B, Plug, Kitchen|Unit C, Light, Kitchen",
    [...mixedRows[0].querySelectorAll("details li")].map((li) => li.textContent));
  // Its answer is for the whole model, the devices' own answers with it.
  const mixedSelect = mixedRows[0].querySelector("select");
  mixedSelect.value = mixedSelect.options[1].value;
  mixedSelect.dispatchEvent(new page.window.Event("change"));
  [...mixedRows[0].querySelectorAll("button.chip")].find((b) => b.textContent === "Save").click();
  await settle(); await settle();
  const typed = page.calls.filter((c) => c.type === "device_sentinel/device_type");
  check("The model's row saves for the whole model", typed.length === 1 && typed[0].whole_model === true, typed);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
