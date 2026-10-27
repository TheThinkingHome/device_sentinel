// File: tools/panel_checks/check_exclusion_card.js, Version: 0.27.10 (2026-10-27)
// Panel checks: the Recommendations tab card that recommends excluding an
// integration seen for the first time on a house that already exists
// (rule MUTE-02), and Send to Battery Notes offered
// after a battery type is saved from the Power Not Set card (rule DEV-09).
// Run with: LC_ALL=en_US.UTF-8 node check_recommendations.js [path/to/panel.js]
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


(async () => {
  console.log("The exclusion card (Ruled Change 70)");
  const OFFER = {
    key: "offer:cast", simple: true, acknowledged: false, exclude: "cast", devices: ["Basement Chromecast", "Kitchen Speaker"],
    text: "Google Cast Is Usually Excluded: Device Sentinel found the Google Cast integration, with 2 devices. It is usually excluded because its devices go unavailable whenever they are switched off. Exclude it here, or tick the box to keep watching it.",
  };
  let excluded = false;
  const recs = () => ({ lines: excluded ? [] : [JSON.parse(JSON.stringify(OFFER))], devices: [], closing: "", power: {},
    types: { choices: [], other: "Other" } });
  for (const mode of ["simple", "advanced"]) {
    excluded = false;
    const page = await open({ path: `${PREFIX}/recommendations`, answers: {
      recommendations: recs,
      status: () => { const s = JSON.parse(JSON.stringify(payloads.status)); s.dashboard = mode; return s; },
      integration_exclude: () => { excluded = true; return {}; },
    } });
    const card = [...page.root.querySelectorAll("article.rec")].find((a) => a.textContent.includes("Google Cast"));
    check(`${mode}: the card is shown`, !!card, page.root.querySelector(".pane") && page.root.querySelector(".pane").textContent.slice(0, 300));
    if (!card) continue;
    check(`${mode}: its title`, card.querySelector("h3").textContent === "Google Cast Is Usually Excluded");
    check(`${mode}: its devices are listed`, card.textContent.includes("Basement Chromecast, Kitchen Speaker"));
    check(`${mode}: a tick keeps watching it`, card.textContent.includes("Keep watching it") && !!card.querySelector('input[type="checkbox"]'));
    const button = [...card.querySelectorAll("button")].find((b) => b.textContent === "Exclude");
    check(`${mode}: it offers Exclude`, !!button);
    button.click();
    await settle(); await settle(); await settle();
    const call = page.calls.find((c) => c.type === "device_sentinel/integration_exclude");
    check(`${mode}: Exclude excludes that integration`, !!call && call.domain === "cast" && call.on === true, call);
  }

  console.log("\nSend to Battery Notes after a save from the Power Not Set card (rule DEV-09)");
  let saved = false;
  const POWER = { kind: "power", title: "Power Not Set", body: "Say what powers these devices.",
    devices: [{ device_id: DEVICE, name: "Porch Button", area: null }] };
  const page = await open({ path: `${PREFIX}/recommendations?open=power`, answers: {
    recommendations: () => ({ lines: [], devices: saved ? [] : [JSON.parse(JSON.stringify(POWER))], closing: "",
      power: { choices: ["CR2032", "Other"], other: "Other", wired: [], quantity: [1, 4] },
      types: { choices: [], other: "Other" } }),
    device_power: () => { saved = true; return { report_url: "https://github.com/andrew-codechimp/HA-Battery-Notes/issues/new?x=1" }; },
  } });
  const card = [...page.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "power");
  const select = card && card.querySelector("select");
  check("The card offers the choices", !!select);
  if (select) {
    select.value = "CR2032";
    select.dispatchEvent(new page.window.Event("change"));
    [...card.querySelectorAll("button")].find((b) => b.textContent === "Save").click();
    await settle(); await settle(); await settle();
    const link = [...page.root.querySelectorAll("a")].find((a) => a.textContent === "Send to Battery Notes");
    check("Send to Battery Notes is offered once the device has left the card", !!link
      && link.getAttribute("href").startsWith("https://github.com/andrew-codechimp/HA-Battery-Notes"), link && link.outerHTML);
    check("It names the device it is about", page.root.textContent.includes("Porch Button saved."));
    [...page.root.querySelectorAll(".tab")].find((b) => b.textContent === "Problem List").click();
    await settle(); await settle();
    [...page.root.querySelectorAll(".tab")].find((b) => b.textContent.startsWith("Recommendations")).click();
    await settle(); await settle();
    check("Leaving the tab ends the offer", ![...page.root.querySelectorAll("a")].some((a) => a.textContent === "Send to Battery Notes"));
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
