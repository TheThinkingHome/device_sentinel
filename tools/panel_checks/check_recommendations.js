// File: tools/panel_checks/check_recommendations.js, Version: 0.27.0 (2026-10-22)
// Panel checks: the Recommendations tab. Its opening line counts the
// recommendations, says they help Device Sentinel run better, and says
// none of them is required; no card is singled out (#626, 0.25.6).
// Since 0.26.0 it also draws the Slow Reporting Devices card (#637).
// Since 0.26.7: the switched-off cards' Turn on chips (#696, #698), a
// tick on each row and each written line (#699), and the count on the
// tab, the highlighted top-band button and the Daily Brief tab (#700).
// Since 0.26.8: a card stays open, and the page stays put, after a
// tick or an answer (#714).
// Since 0.27.0: each card's title counts its rows not ticked, with no
// number at zero or on a written line (#724).
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

(async () => {
  console.log("\nThe Recommendations tab's opening line (ruling #626)");
  const { root } = await open({ path: `${PREFIX}/recommendations` });
  const first = root.querySelector("p");
  const count = (payloads.recommendations.lines || []).length + (payloads.recommendations.devices || []).length;
  const word = count === 1 ? "recommendation" : "recommendations";
  check("It says they help it run better and none is required",
    !!first && first.textContent === `${count} ${word} to help Device Sentinel run better. None of them is required.`, first && first.textContent);
  check("Nothing says one matters more than another", !/most important/.test(root.textContent));

  // Slow Reporting Devices (ruling #637, 0.26.0): the card in James's
  // words, each device with a Mute freeze chip that calls the same
  // mute the device page does, and the list refreshed afterwards.
  console.log("\nThe Slow Reporting Devices card (ruling #637)");
  const SLOW = {
    kind: "slow", title: "Slow Reporting Devices",
    body: "These devices go quiet for long periods. They are often devices that sleep until a person triggers or interacts with them. Because these devices do not report on a rhythm, Device Sentinel has trouble accurately reporting a frozen verdict. Often a freeze verdict for this device is noise and the best practice is to mute it. Device Sentinel will still report when it becomes unavailable or its battery runs low.",
    devices: [{ device_id: ROWS[0].device_id, name: "Guest Lamp", area: "Guest Bedroom" }, { device_id: ROWS[1].device_id, name: "Porch Button", area: null }],
  };
  let muted = [];
  let served = 0;
  const slow = await open({ path: `${PREFIX}/recommendations?open=slow`, answers: {
    recommendations: () => {
      served += 1;
      const base = JSON.parse(JSON.stringify(payloads.recommendations));
      const card = JSON.parse(JSON.stringify(SLOW));
      card.devices = card.devices.filter((row) => !muted.includes(row.device_id));
      base.devices = (base.devices || []).concat(card.devices.length ? [card] : []);
      return base;
    },
    device_mute: (message) => { muted.push(message.device_id); return {}; },
  } });
  const card = [...slow.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "slow");
  check("The card is drawn with James's title", !!card && card.querySelector("h3").textContent === "Slow Reporting Devices (2)",
    card && card.querySelector("h3").textContent);
  check("Its body is James's text, word for word", !!card && card.querySelector("p").textContent === SLOW.body);
  check("It opens on its list when the address asks for it", !!card && card.querySelector("details").hasAttribute("open"));
  const rows = card ? [...card.querySelectorAll("tbody tr")] : [];
  check("Each device has a row with its area or 'no area'", rows.length === 2
    && rows[0].children[1].textContent === "Guest Bedroom" && rows[1].children[1].textContent === "no area", rows.map((r) => r.textContent));
  const chip = rows[0] && rows[0].querySelector("button.chip");
  check("Each row offers Mute freeze", !!chip && chip.textContent === "Mute freeze", chip && chip.textContent);
  chip.click();
  await settle(); await settle(); await settle();
  const muteCall = slow.calls.find((c) => c.type === "device_sentinel/device_mute");
  check("The chip mutes freeze for that device, and nothing else",
    !!muteCall && muteCall.device_id === ROWS[0].device_id && muteCall.kind === "freeze" && muteCall.on === true, muteCall);
  check("The brief will say it came from the Recommendations tab (ruling #643)", !!muteCall && muteCall.source === "recommendations", muteCall);
  const after = [...slow.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "slow");
  check("The list is fetched again and the muted device leaves the card",
    served >= 2 && !!after && after.querySelectorAll("tbody tr").length === 1
    && after.querySelector("tbody tr").textContent.includes("Porch Button"), after && after.textContent);
  const count2 = (payloads.recommendations.lines || []).length + (payloads.recommendations.devices || []).length + 1;
  check("The opening line counts the new card", slow.root.querySelector("p").textContent.startsWith(`${count2} recommendations`),
    slow.root.querySelector("p").textContent);

  // Acknowledgement and the count (rulings #696 to #700).
  console.log("\nTicks, the count and the Active Recommendations button (rulings #696 to #700)");
  let ticks = { line: false, [ROWS[0].device_id]: false };
  const OFF = {
    kind: "battery_off", title: "Battery Sensor Switched Off", simple: true, active: 1,
    body: "2 devices have a battery sensor that is switched off.",
    devices: [
      { device_id: ROWS[0].device_id, name: "Hall Motion", area: "Hall", acknowledged: false },
      { device_id: ROWS[1].device_id, name: "Shed Leak", area: null, acknowledged: true, by_user: true },
    ],
  };
  const LINE = { key: "no_target", text: "Notifications Recipient Not Set: no target is set.", simple: true, acknowledged: false };
  const recs = () => {
    const card = JSON.parse(JSON.stringify(OFF));
    card.devices[0].acknowledged = ticks[ROWS[0].device_id];
    return { lines: [{ ...LINE, acknowledged: ticks.line }], devices: [card], closing: "", power: {}, types: { choices: [], other: "Other" } };
  };
  const acks = await open({ path: `${PREFIX}/recommendations`, answers: {
    recommendations: recs,
    recommendation_ack: (message) => {
      if (message.line) ticks.line = message.on; else ticks[message.device_id] = message.on;
      return {};
    },
  } });
  const tabLabel = () => [...acks.root.querySelectorAll(".tab")].map((t) => t.textContent).find((t) => t.startsWith("Recommendations"));
  const band = () => acks.root.querySelector("button.active-recs");
  check("The tab counts what is not acknowledged: one device and one line", tabLabel() === "Recommendations (2)", tabLabel());
  check("The top band carries Active Recommendations (2), shown", !!band() && !band().hidden && band().textContent === "Active Recommendations (2)",
    band() && band().textContent);
  const titleOf = (kind) => {
    const art = [...acks.root.querySelectorAll("article.rec")].find((a) => (kind ? a.dataset.kind === kind : !a.dataset.kind));
    return art && art.querySelector("h3") ? art.querySelector("h3").textContent : null;
  };
  check("A card's title counts its rows not ticked (ruling #724)", titleOf("battery_off") === "Battery Sensor Switched Off (1)", titleOf("battery_off"));
  check("A written line's title carries no number (ruling #724)", titleOf(null) === "Notifications Recipient Not Set", titleOf(null));
  check("No Enable button is left in the top band (ruling #696)", !/Enable (Signals|Last Seen|Battery)/.test(acks.root.querySelector(".actions").textContent));
  const offCard = [...acks.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "battery_off");
  const offRows = offCard ? [...offCard.querySelectorAll("tbody tr")] : [];
  check("A sensor its person switched off is shown ticked and faded", offRows[1] && offRows[1].classList.contains("acked")
    && offRows[1].querySelector('input[type="checkbox"]').checked);
  const turnOn = offRows[0] && offRows[0].querySelector("button.chip");
  check("Each row offers Turn on its battery sensor", !!turnOn && turnOn.textContent === "Turn on its battery sensor", turnOn && turnOn.textContent);
  turnOn.click();
  await settle(); await settle();
  const turnCall = acks.calls.find((c) => c.type === "device_sentinel/device_turn_on");
  check("Turn on asks for this device's battery sensor alone", !!turnCall && turnCall.kind === "battery" && turnCall.device_id === ROWS[0].device_id, turnCall);
  const box = [...acks.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "battery_off")
    .querySelector("tbody tr").querySelector('input[type="checkbox"]');
  box.checked = true;
  box.dispatchEvent(new acks.window.Event("change"));
  await settle(); await settle();
  const ackCall = acks.calls.find((c) => c.type === "device_sentinel/recommendation_ack");
  check("A tick names the card and the device", !!ackCall && ackCall.kind === "battery_off" && ackCall.device_id === ROWS[0].device_id && ackCall.on === true, ackCall);
  check("The tab then counts one", tabLabel() === "Recommendations (1)", tabLabel());
  check("With every row ticked the card's title has no number", titleOf("battery_off") === "Battery Sensor Switched Off", titleOf("battery_off"));
  const lineBox = acks.root.querySelector("article.rec:not([data-kind]) input[type=checkbox]");
  lineBox.checked = true;
  lineBox.dispatchEvent(new acks.window.Event("change"));
  await settle(); await settle();
  const lineCall = acks.calls.filter((c) => c.type === "device_sentinel/recommendation_ack").pop();
  check("A written line is ticked by its key", !!lineCall && lineCall.line === "no_target" && lineCall.on === true, lineCall);
  check("With everything ticked the tab reads plain", tabLabel() === "Recommendations", tabLabel());
  check("And the button hides", !!band() && band().hidden);
  const undo = [...acks.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "battery_off")
    .querySelector("tbody tr").querySelector('input[type="checkbox"]');
  undo.checked = false;
  undo.dispatchEvent(new acks.window.Event("change"));
  await settle(); await settle();
  check("A tick can be taken back, and counts again", tabLabel() === "Recommendations (1)", tabLabel());
  check("And the card's title counts it again", titleOf("battery_off") === "Battery Sensor Switched Off (1)", titleOf("battery_off"));

  console.log("\nA card stays open after an answer (ruling #714)");
  ticks = { line: false, [ROWS[0].device_id]: false };
  const SLOW_CARD = { kind: "slow", title: "Slow Reporting Devices", simple: true, active: 1, body: "One device.",
    devices: [{ device_id: ROWS[2].device_id, name: "Garage Door", area: "Garage", acknowledged: false }] };
  const stay = await open({ path: `${PREFIX}/recommendations?open=battery_off`, answers: {
    recommendations: () => { const r = recs(); r.devices.push(JSON.parse(JSON.stringify(SLOW_CARD))); return r; },
    recommendation_ack: (message) => { if (message.line) ticks.line = message.on; else ticks[message.device_id] = message.on; return {}; },
  } });
  const cardOf = (kind) => [...stay.root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === kind);
  const isOpen = (kind) => cardOf(kind).querySelector("details").hasAttribute("open");
  // The page's scroll, kept by the host here; a redraw that moved it
  // is what the browser does when the tab is rebuilt.
  let top = 0;
  Object.defineProperty(stay.panel, "scrollTop", { configurable: true, get: () => top, set: (v) => { top = v; } });
  const pane = stay.root.querySelector(".pane");
  const replace = pane.replaceChildren.bind(pane);
  pane.replaceChildren = (...nodes) => { top = 0; replace(...nodes); };
  let scrolled = 0;
  stay.window.Element.prototype.scrollIntoView = function () { scrolled += 1; };
  await stay.panel._refresh(); await settle();
  check("The address opens its card", isOpen("battery_off") && !isOpen("slow"));
  const scrolledFirst = scrolled;
  top = 640;
  const tick = cardOf("battery_off").querySelector("tbody tr input[type=checkbox]");
  tick.checked = true;
  tick.dispatchEvent(new stay.window.Event("change"));
  await settle(); await settle();
  check("A tick leaves the card open", isOpen("battery_off"));
  check("And the page where it was", top === 640, top);
  check("The address's card is scrolled to once, not at each answer", scrolled === scrolledFirst, [scrolledFirst, scrolled]);
  cardOf("battery_off").querySelector("button.chip").click();
  await settle(); await settle();
  check("An action leaves the card open", isOpen("battery_off"));
  const slowDetails = cardOf("slow").querySelector("details");
  slowDetails.open = true;
  slowDetails.dispatchEvent(new stay.window.Event("toggle"));
  cardOf("slow").querySelector("button.chip").click();
  await settle(); await settle();
  check("A card the person opened stays open after its own action", isOpen("slow") && isOpen("battery_off"));
  const offDetails = cardOf("battery_off").querySelector("details");
  offDetails.open = false;
  offDetails.dispatchEvent(new stay.window.Event("toggle"));
  const again = cardOf("battery_off").querySelector("tbody tr input[type=checkbox]");
  again.checked = false;
  again.dispatchEvent(new stay.window.Event("change"));
  await settle(); await settle();
  check("A card the person closed stays closed", !isOpen("battery_off") && isOpen("slow"));
  check("Nothing is kept in the browser", stay.window.localStorage.length === 0 && stay.window.sessionStorage.length === 0);

  console.log("\nThe Daily Brief tab's line (ruling #700)");
  ticks = { line: false, [ROWS[0].device_id]: false };
  const brief = await open({ path: PREFIX, answers: { recommendations: recs } });
  const recLine = brief.root.querySelector("p.recline");
  check("It opens with the count and a link to the tab", !!recLine && recLine.textContent === "2 active recommendations on the Recommendations tab."
    && !!recLine.querySelector("a"), recLine && recLine.textContent);
  ticks = { line: true, [ROWS[0].device_id]: true };
  const quiet = await open({ path: PREFIX, answers: { recommendations: recs } });
  check("With nothing active it says nothing", quiet.root.querySelector("p.recline") === null);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
