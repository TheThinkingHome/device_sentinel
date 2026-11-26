// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_other_power.js, Version: 0.30.7 (2026-11-26)
//
// Words typed under Other are a battery or a wired source (rule DEV-08):
// the card's chooser asks which, a wired answer sends no quantity, and
// Check Power Typed Under Other answers each device saved as a battery
// before Other asked, each answer saying what it does.
// Run with: LC_ALL=en_US.UTF-8 node check_other_power.js [path/to/panel.js]
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



const POWER = { kind: "power", title: "Power Not Set", rank: 24, active: 1, body: "1 device has no battery or power source set.",
  devices: [{ device_id: "p1", name: "Rack", area: null, acknowledged: false }] };
const OTHER = { kind: "other_power", title: "Check Power Typed Under Other", rank: 13, active: 2, simple: true,
  body: "2 devices have power typed under Other.",
  devices: [{ device_id: "u1", name: "Router", area: null, acknowledged: false, detail: "UPS", quantity: 1 },
    { device_id: "u2", name: "Remote", area: null, acknowledged: false, detail: "Coin thing", quantity: 3 }] };

(async () => {
  const page = await open({ path: `${PREFIX}/recommendations`, answers: {
    recommendations: () => ({ lines: [], devices: [JSON.parse(JSON.stringify(OTHER)), JSON.parse(JSON.stringify(POWER))], closing: "",
      power: { choices: ["AA", "Mains Powered", "Other"], wired: ["Mains Powered"], quantity: [1, 4], other: "Other" },
      types: { choices: [], other: "Other" } }),
    device_power: () => ({}),
  } });
  const card = (kind) => page.root.querySelector(`article.rec[data-kind="${kind}"]`);
  console.log("The chooser asks battery or wired (rule DEV-08)");
  const power = card("power");
  power.querySelector("details").open = true;
  const row = power.querySelector("tbody tr");
  const select = row.querySelector('select[aria-label="What powers this device"]');
  select.value = "Other"; select.dispatchEvent(new page.window.Event("change"));
  const how = row.querySelector('select[aria-label="Battery or wired"]');
  const qty = row.querySelector('select[aria-label="How many"]');
  check("Other asks battery or wired, with no quantity until battery", how && how.style.display === "" && qty.style.display === "none");
  row.querySelector('input[aria-label="Battery or power source"]').value = "UPS";
  [...row.querySelectorAll("button")].find((b) => b.textContent === "Save").click();
  await settle();
  check("Save waits for the answer", !page.calls.some((c) => c.type === "device_sentinel/device_power")
    && row.textContent.includes("Choose battery or wired."), row.textContent);
  how.value = "wired"; how.dispatchEvent(new page.window.Event("change"));
  check("Wired shows no quantity", qty.style.display === "none");
  [...row.querySelectorAll("button")].find((b) => b.textContent === "Save").click();
  await settle(); await settle();
  const sent = page.calls.filter((c) => c.type === "device_sentinel/device_power").pop();
  check("Wired sends the words, wired and no quantity",
    sent && sent.choice === "Other" && sent.other === "UPS" && sent.wired === true && sent.quantity === undefined, sent);

  console.log("\nCheck Power Typed Under Other");
  const other = card("other_power");
  other.querySelector("details").open = true;
  const rows = [...other.querySelectorAll("tbody tr")];
  check("Each row shows what was typed", rows[0].textContent.includes("Typed: UPS") && rows[1].textContent.includes("Typed: Coin thing"));
  check("Each answer says what it does",
    rows[0].textContent.includes("Device Sentinel tracks its battery and warns you when it runs low.")
    && rows[0].textContent.includes("Device Sentinel stops watching a battery and judges it as a mains device."));
  check("Never says it keeps it as it is", !other.textContent.toLowerCase().includes("as it is"));
  [...rows[0].querySelectorAll("button")].find((b) => b.textContent === "Wired").click();
  await settle(); await settle();
  let last = page.calls.filter((c) => c.type === "device_sentinel/device_power").pop();
  check("Wired answers for that device, from the tab",
    last && last.device_id === "u1" && last.other === "UPS" && last.wired === true && last.quantity === undefined && last.source === "recommendations", last);
  const again = card("other_power");
  again.querySelector("details").open = true;
  const second = [...again.querySelectorAll("tbody tr")][1];
  [...second.querySelectorAll("button")].find((b) => b.textContent === "Battery").click();
  await settle(); await settle();
  last = page.calls.filter((c) => c.type === "device_sentinel/device_power").pop();
  check("Battery keeps the count it had", last && last.device_id === "u2" && last.wired === false && last.quantity === 3, last);
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
