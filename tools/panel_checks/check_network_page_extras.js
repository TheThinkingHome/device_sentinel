// File: tools/panel_checks/check_network_page_extras.js, Version: 0.28.7 (2026-11-09)
// Panel checks: more on a network's page (rules DASH-17, DASH-18). The
// Open buttons for the network's own page and its app, its devices and
// makeup, outage patterns with their one sentence used twice, Yes it is
// expected and Stop expecting this, the logbook button, firmware,
// Wi-Fi address changes and Z-Wave radio noise; the same cards on the
// Recommendations tab, and the expected outages on the Integrations tab.
// Run with: LC_ALL=en_US.UTF-8 node check_network_page_extras.js [path/to/panel.js]
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

const COUNTS = { frozen: 0, unavailable: 0, never_reported: 0, battery: 0, signal: 0, drops: 0 };
const CARD = { kind: "pattern", minute: 220, time: "3:40 AM", sentence: "Down 6 nights in a row at 3:40 AM, Oct 29 to Nov 3.",
  question: "Is this expected? A nightly backup or scheduled restart on the device that runs Zigbee2MQTT often does this.",
  logbook: { start: "2026-11-03T08:30:00+00:00", end: "2026-11-03T08:54:00+00:00", day: "Nov 3", words: "Nov 3, 3:30 AM to 3:54 AM" },
  usual_words: "4 minutes", key: "network:z2m:pattern:220:", acknowledged: false };
const OUTAGE = (day, len, expected = false) => ({ went_down: `2026-11-0${day}T08:40:00+00:00`, what: "Bridge: Zigbee2MQTT",
  duration: len, devices: 74, open: false, expected });
const PAGE = {
  key: "z2m", name: "Zigbee2MQTT", kind: "z2m", status: { state: "ok", words: "Running", since: null },
  watched: 2, with_problem: 0, counts: COUNTS, window_days: 30, hardware: [],
  outages: [OUTAGE(7, 120), OUTAGE(3, 240), OUTAGE(2, 240), OUTAGE(1, 240)],
  patterns: [{ ...CARD, times: 3, usual: 240, outages: [1, 2, 3], expected: false, last_went: "2026-11-03T08:40:00+00:00" }],
  cards: [CARD],
  notices: [{ title: "Zigbee2MQTT's Availability is off.", words: "Turn it on in Zigbee2MQTT.", open: "Zigbee2MQTT" }],
  sensors: [{ kind: "firmware", label: "Firmware update checks", have: 2, on: 1, off: [{ device_id: "dev-lamp", name: "Lamp Hall", by: "integration" }] }],
  signal: { weak_week: 0, drops: 0, drop_devices: 0, railed: 0 }, pairing: null, wifi: null,
  devices: [
    { device_id: "dev-door", name: "Door Laundry", maker: "Aqara", model: "MCCGQ11LM", firmware: "3.0", role: "End device", power: "Battery", problem: "battery" },
    { device_id: "dev-lamp", name: "Lamp Hall", maker: "Philips", model: "LCT015", firmware: "1.50.2", role: "Router", power: "Mains", problem: null },
  ],
  makeup: { roles: [{ name: "End device", devices: 1 }, { name: "Router", devices: 1 }],
    power: [{ name: "Battery", devices: 1 }, { name: "Mains", devices: 1 }],
    makers: [{ name: "Aqara", devices: 1 }, { name: "Philips", devices: 1 }], other_makers: 3 },
  up: { back_since: "2026-11-07T08:42:00+00:00", since: null, outages: 4, expected: 0 },
  offenders: { repeat: [{ device_id: "dev-door", name: "Door Laundry", what: "went unavailable", times: 3, typical: "4m" }],
    drops: [{ device_id: "dev-lamp", name: "Lamp Hall", drops: 5 }] },
  wifi_changes: null,
  firmware: { updates: [{ device_id: "dev-lamp", name: "Lamp Hall", entity_id: "update.lamp", installed: "1.50.2", latest: "1.122.2" }],
    changed: [{ device_id: "dev-door", name: "Door Laundry", from: "2.0", to: "3.0", when: "2026-11-05T12:00:00+00:00" }],
    mixed: [{ maker: "Philips", model: "LCT015", versions: [{ version: "1.50.2", devices: 3 }, { version: "1.88.1", devices: 1 }] }] },
  noise: null, own_page: false,
};
const ZWAVE = { ...clone(PAGE), key: "zwave_js", name: "Z-Wave", kind: "zwave_js", notices: [], patterns: [], cards: [], outages: [],
  noise: { channels: [{ channel: 0, now: -90, average: -101.5, typical: -104, days: 23, raised: true, floor: false },
    { channel: 1, now: -105, average: null, typical: null, days: 5, raised: false, floor: false }],
  cards: [{ kind: "noise", channel: 0, sentence: "Radio noise on channel 0 has stayed at least 10 dB above its usual -104 dBm for 3 days." }] } };
const WIFI = { ...clone(PAGE), key: "wifi", name: "Wi-Fi", kind: "wifi", notices: [], patterns: [], cards: [],
  wifi: { watched_networks: [], scan: false, access_points: [], shared: [] },
  wifi_changes: [{ device_id: "dev-door", name: "Door Laundry", addresses: 2, moves: 1, last: "2026-11-08T12:00:00+00:00" }] };
const PANELS = {
  config: { url_path: "config", component_name: "config", config: null },
  "45df7312_zigbee2mqtt": { url_path: "45df7312_zigbee2mqtt", component_name: "app", title: "Zigbee2MQTT", config: { addon: "45df7312_zigbee2mqtt" } },
  "device-sentinel": { url_path: "device-sentinel", component_name: "custom", config: { _panel_custom: {} } },
};

async function open(path, { mode = "advanced", answers = {}, panels = PANELS } = {}) {
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
  const calls = [];
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "status") return { ...clone(payloads.status), dashboard: mode };
      if (kind === "networks") return { rows: [] };
      if (kind === "network") return clone({ z2m: PAGE, zwave_js: ZWAVE, wifi: WIFI }[message.key]);
      if (kind === "network_expected") return {};
      if (kind === "devices") return { rows: [], excluded: [] };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return clone(payloads[kind]);
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    panels,
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}
const text = (root) => root.querySelector(".pane").textContent;
const links = (root) => [...root.querySelectorAll(".pane a")];
const link = (root, words) => links(root).find((a) => a.textContent.startsWith(words));
const button = (root, words) => [...root.querySelectorAll(".pane button")].find((b) => b.textContent.startsWith(words));
const noStrays = (root) => !/\b(null|undefined|NaN)\b|\[object/.test(text(root));

(async () => {
  console.log("The Open buttons");
  let { root, calls, window } = await open("/network/z2m?from=networks");
  check("Zigbee2MQTT's app opens its sidebar panel", link(root, "Open Zigbee2MQTT") && link(root, "Open Zigbee2MQTT").getAttribute("href") === "/45df7312_zigbee2mqtt",
    links(root).map((a) => [a.textContent, a.getAttribute("href")]));
  const notice = root.querySelector(".pane .notice");
  check("the Availability notice carries the same button", notice && [...notice.querySelectorAll("a")].some((a) => a.getAttribute("href") === "/45df7312_zigbee2mqtt"),
    notice && notice.innerHTML);
  ({ root } = await open("/network/z2m?from=networks", { panels: { config: PANELS.config } }));
  check("with no Zigbee2MQTT panel, no button and no broken link", !link(root, "Open Zigbee2MQTT")
    && !root.querySelector(".pane .notice a"), links(root).map((a) => a.textContent));
  ({ root } = await open("/network/z2m?from=networks", { panels: { z: { url_path: "hassio_zigbee2mqtt_edge", component_name: "custom", config: { ingress: "45df7312_zigbee2mqtt_edge" } } } }));
  check("an older panel shape, or the edge app, is found too", link(root, "Open Zigbee2MQTT") && link(root, "Open Zigbee2MQTT").getAttribute("href") === "/hassio_zigbee2mqtt_edge");
  ({ root } = await open("/network/z2m?from=networks", { panels: undefined }));
  check("no panels at all still draws the page", root.querySelector(".pane h2") && root.querySelector(".pane h2").textContent === "Zigbee2MQTT");
  ({ root } = await open("/network/zwave_js?from=networks", { panels: { ...PANELS, zui: { url_path: "a0d7b954_zwavejs2mqtt", component_name: "app", config: { addon: "a0d7b954_zwavejs2mqtt" } } } }));
  check("Z-Wave: its own page and Z-Wave JS UI", link(root, "Open Z-Wave JS UI") && link(root, "Open Z-Wave JS UI").getAttribute("href") === "/a0d7b954_zwavejs2mqtt"
    && link(root, "Open Z-Wave JS").getAttribute("href") === "/config/zwave_js/dashboard", links(root).map((a) => [a.textContent, a.getAttribute("href")]));
  for (const [key, words, href] of [["zha", "Open ZHA", "/config/zha/dashboard"], ["matter", "Open Matter", "/config/matter/dashboard"]]) {
    ({ root } = await open(`/network/${key}?from=networks`, { answers: { network: () => ({ ...clone(PAGE), key, name: key, kind: key, notices: [], cards: [], patterns: [] }) } }));
    check(`${words} opens ${href}`, link(root, words) && link(root, words).getAttribute("href") === href);
  }

  console.log("One sentence, used twice");
  ({ root, calls } = await open("/network/z2m?from=networks"));
  const heads = [...root.querySelectorAll(".pane h3")].map((h) => h.textContent);
  check("its recommendations come first", heads[0] === "Recommendations for This Network", heads);
  const sentences = [...root.querySelectorAll(".pane strong")].filter((s) => s.textContent === CARD.sentence);
  check("the sentence is shown twice: the card and over its outages", sentences.length === 2, sentences.length);
  const card = root.querySelector(".pane article.rec");
  check("the card asks if it is expected", card && card.textContent.includes("Is this expected?"), card && card.textContent);
  const book = [...card.querySelectorAll("a")].find((a) => a.textContent.startsWith("Open the logbook"));
  check("the logbook button opens that night, ten minutes either side",
    book && book.getAttribute("href") === `/logbook?start_date=${encodeURIComponent(CARD.logbook.start)}&end_date=${encodeURIComponent(CARD.logbook.end)}`
    && book.textContent === "Open the logbook, Nov 3, 3:30 AM to 3:54 AM", book && [book.textContent, book.getAttribute("href")]);
  const outageTable = [...root.querySelectorAll(".pane table")].find((tb) => tb.textContent.includes("WENT DOWN"));
  const rows = outageTable ? [...outageTable.querySelectorAll("tbody tr")].map((tr) => tr.className) : [];
  check("the pattern's three outages under its sentence, the other after", JSON.stringify(rows.slice(0, 5)) === JSON.stringify(["patternrow", "inpattern", "inpattern", "inpattern", ""]), rows);
  button(root, "Yes, it is expected").click();
  await settle();
  const sent = calls.find((c) => c.type === "device_sentinel/network_expected");
  check("Yes, it is expected sends the network and time", sent && sent.key === "z2m" && sent.minute === 220 && sent.on === true, sent);
  const expectedPage = clone(PAGE);
  expectedPage.cards = [];
  expectedPage.patterns[0].expected = true;
  expectedPage.outages.forEach((o, i) => { o.expected = i > 0; });
  ({ root, calls } = await open("/network/z2m?from=networks", { answers: { network: () => clone(expectedPage) } }));
  check("marked expected: no card, its outages say expected", !root.querySelector(".pane article.rec") && text(root).includes("(expected)")
    && text(root).includes("Expected."), text(root));
  button(root, "Stop expecting this").click();
  await settle();
  const stop = calls.find((c) => c.type === "device_sentinel/network_expected");
  check("Stop expecting this takes it back", stop && stop.on === false && stop.minute === 220, stop);
  const failing = await open("/network/z2m?from=networks", { answers: { network_expected: async () => { throw new Error("No outage pattern at that time"); } } });
  const yes = button(failing.root, "Yes, it is expected");
  yes.click();
  await settle(); await settle();
  check("a refusal is said beside the button", text(failing.root).includes("No outage pattern at that time"), failing.calls.map((c) => c.type));

  // A refusal is said: once the click was handled, the shadow root used
  // to name no button, and the reason was lost (rule DASH-10).
  const refusedOn = await open("/network/z2m?from=networks", { answers: { device_turn_on: async () => { throw new Error("Home Assistant said no"); } } });
  button(refusedOn.root, "Turn it on").click();
  await settle(); await settle();
  check("a sensor turn-on refused is said", text(refusedOn.root).includes("Home Assistant said no"));

  console.log("Its devices, makeup and the rest");
  ({ root } = await open("/network/z2m?from=networks"));
  const details = root.querySelector(".pane details.devlist");
  check("its devices, folded", details && details.querySelector("summary").textContent === "Its 2 devices" && !details.hasAttribute("open"));
  const th = details ? [...details.querySelectorAll("th")].map((h) => h.textContent) : [];
  check("with model, maker, part in the mesh, power and firmware", JSON.stringify(th) === JSON.stringify(["DEVICE", "MODEL", "MAKER", "IN THE MESH", "POWER", "FIRMWARE", "PROBLEM"]), th);
  check("a problem reads in the tile's words", details && details.textContent.includes("Battery"));
  check("what it is made of", text(root).includes("What It Is Made Of") && text(root).includes("1 End device, 1 Router")
    && text(root).includes("1 Aqara, 1 Philips, and 3 more"), text(root));
  check("running since its last outage ended", text(root).includes("Running since its last outage ended"));
  check("devices that keep failing", text(root).includes("Devices That Keep Failing This Week") && text(root).includes("went unavailable, 3 times")
    && text(root).includes("Lamp Hall: 5"));
  check("firmware changes look back 30 days on any page", text(root).includes("Changed in the last 30 days:"));
  check("firmware: updates, changes and mixed versions", text(root).includes("Home Assistant offers an update for 1 device")
    && text(root).includes("1.50.2 to 1.122.2") && text(root).includes("2.0 to 3.0") && text(root).includes("Philips LCT015: 1.50.2 on 3, 1.88.1 on 1"), text(root));
  check("a switched-off update check is offered to turn on", text(root).includes("Firmware update checks") && button(root, "Turn it on"));
  check("no stray words", noStrays(root), text(root));

  console.log("Simple");
  ({ root } = await open("/network/z2m?from=networks", { mode: "simple" }));
  const sth = [...root.querySelectorAll(".pane details.devlist th")].map((h) => h.textContent);
  check("the card and the device list, with fewer columns", root.querySelector(".pane article.rec")
    && JSON.stringify(sth) === JSON.stringify(["DEVICE", "MODEL", "PROBLEM"]), sth);
  check("no makeup, outages or firmware", !text(root).includes("What It Is Made Of") && !text(root).includes("Outages in the Last")
    && !text(root).includes("Home Assistant offers"));

  console.log("Wi-Fi and Z-Wave");
  ({ root } = await open("/network/wifi?from=networks"));
  check("Wi-Fi address changes", text(root).includes("Address Changes in the Last 30 Days") && text(root).includes("Door Laundry21"), text(root));
  ({ root } = await open("/network/zwave_js?from=networks"));
  check("radio noise per channel", text(root).includes("Radio Noise") && text(root).includes("-90 dBm") && text(root).includes("-101 dBm")
    && text(root).includes("-104 dBm") && text(root).includes("learning, 5 of 14 days"), text(root));
  check("raised noise is a recommendation", root.querySelector(".pane article.rec") && root.querySelector(".pane article.rec").textContent.includes("channel 0"));
  check("no stray words", noStrays(root), text(root));

  console.log("Previous and Next walk the device list");
  let panelNow;
  ({ root, panel: panelNow, window } = await open("/network/z2m?from=networks"));
  const lampLink = [...root.querySelectorAll(".pane details.devlist a")].find((a) => a.textContent === "Lamp Hall");
  lampLink.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await settle();
  check("its devices in name order", JSON.stringify(panelNow._lists["/network/z2m?from=networks"]) === JSON.stringify(["dev-door", "dev-lamp"]), panelNow._lists);

  console.log("The Recommendations tab");
  const RECS = { ...clone(payloads.recommendations), networks: [{ key: "z2m", name: "Zigbee2MQTT", cards: [CARD] }] };
  ({ root, calls } = await open("/recommendations", { answers: { recommendations: () => clone(RECS) } }));
  const recCard = [...root.querySelectorAll(".pane article.rec")].find((a) => a.textContent.includes(CARD.sentence));
  check("the same card, naming its network", recCard && recCard.querySelector("h3").textContent === "Zigbee2MQTT", recCard && recCard.innerHTML);
  check("with its question and buttons", recCard && recCard.textContent.includes("Is this expected?") && [...recCard.querySelectorAll("button")].some((b) => b.textContent === "Yes, it is expected"));
  const tabText = [...root.querySelectorAll(".tab")].map((t) => t.textContent).find((t) => t.startsWith("Recommendations"));
  const base = await open("/recommendations", { answers: { recommendations: () => clone(payloads.recommendations) } });
  const baseText = [...base.root.querySelectorAll(".tab")].map((t) => t.textContent).find((t) => t.startsWith("Recommendations"));
  const n = (s) => Number((/\((\d+)\)/.exec(s || "") || [0, 0])[1]);
  check("it counts in the tab's number", n(tabText) === n(baseText) + 1, [tabText, baseText]);
  ({ root } = await open("/recommendations", { mode: "simple", answers: { recommendations: () => clone(RECS) } }));
  check("and shows in Simple", [...root.querySelectorAll(".pane article.rec")].some((a) => a.textContent.includes(CARD.sentence)));
  ({ root } = await open("/recommendations", { answers: { recommendations: () => ({ lines: [], devices: [], closing: "", networks: [{ key: "z2m", name: "Zigbee2MQTT", cards: [CARD] }] }) } }));
  check("a network card alone is not 'nothing to recommend'", !text(root).startsWith("Nothing to recommend") && root.querySelector(".pane article.rec"), text(root));

  console.log("Network cards have no Acknowledged box (rule DASH-18)");
  ({ root } = await open("/recommendations", { answers: { recommendations: () => clone(RECS) } }));
  const netCard = [...root.querySelectorAll(".pane article.rec")].find((a) => a.textContent.includes(CARD.sentence));
  check("no checkbox on a network card", netCard && !netCard.querySelector("input[type=checkbox]"));
  const NOLEN = clone(PAGE);
  NOLEN.cards[0].usual_words = null;
  ({ root } = await open("/network/z2m?from=networks", { answers: { network: () => clone(NOLEN) } }));
  check("a pattern with no recorded length offers no Yes", !button(root, "Yes, it is expected") && root.querySelector(".pane article.rec"));

  console.log("Next stays in the list it was pressed in");
  let pn;
  ({ root, panel: pn, window } = await open("/network/z2m?from=networks"));
  const offenderLink = [...root.querySelectorAll(".pane ul.offlist a")].find((a) => a.textContent === "Lamp Hall");
  offenderLink.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await settle();
  check("opened from Most short drop-outs, its list is that list", JSON.stringify(pn._lists["/network/z2m?from=networks"]) === JSON.stringify(["dev-lamp"]), pn._lists);

  console.log("The Networks tab marks an expected last outage");
  ({ root } = await open("/networks", { answers: { networks: () => ({ rows: [{ key: "z2m", name: "Zigbee2MQTT", kind: "z2m",
    status: { state: "ok", words: "Running", since: null }, watched: 2, with_problem: 0, counts: COUNTS, outages: 0, expected: 1,
    last_outage: { ...OUTAGE(3, 240, true) }, window_days: 30 }] }) } }));
  check("its last outage reads (expected)", text(root).includes("(expected)"), text(root));

  console.log("The Integrations tab");
  const INTS = { ...clone(payloads.integrations), expected: [{ network: "z2m", name: "Zigbee2MQTT", minute: 220, time: "3:40 AM", usual: "4 minutes", since: "2026-11-09T14:00:00+00:00" }] };
  ({ root, calls } = await open("/integrations", { answers: { integrations: () => clone(INTS) } }));
  check("the expected outages, with the mutes", text(root).includes("Expected Outages") && text(root).includes("3:40 AM") && text(root).includes("4 minutes")
    && !text(root).includes("not counted"), text(root));
  button(root, "Stop expecting this").click();
  await settle();
  const off = calls.find((c) => c.type === "device_sentinel/network_expected");
  check("each can be taken back", off && off.key === "z2m" && off.minute === 220 && off.on === false, off);
  ({ root } = await open("/integrations"));
  check("none expected, no section", !text(root).includes("Expected Outages"));

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
