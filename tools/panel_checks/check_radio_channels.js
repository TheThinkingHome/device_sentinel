// File: tools/panel_checks/check_radio_channels.js, Version: 0.29.6 (2026-11-17)
// Panel checks: radio channels (rules SIG-19, DASH-19, REC-13).
// The Networks tab's chart sits at the top, Advanced only, red where a
// network overlaps a Zigbee or Thread channel. A device page's Radio
// Channel row is Advanced only and carries its warning. The Wi-Fi page
// lists the networks the server hears; the Matter page its Thread
// channels. A channel card shows on its network's page and on the
// Recommendations tab.
// Run with: LC_ALL=en_US.UTF-8 node check_radio_channels.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const DEVICE = payloads._ids.bravo;

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

const COUNTS = { frozen: 0, unavailable: 0, never_reported: 0, battery: 0, signal: 0, drops: 0 };
const AIR = {
  scanned_at: "2026-11-17T19:40:00+00:00", scan: "ok",
  wifi: [
    { ssid: "Neighbour", mhz: 2412, channel: 1, band: "2.4 GHz", signal: 52, own: false, bad: true },
    { ssid: "", mhz: 2412, channel: 1, band: "2.4 GHz", signal: 50, own: false, bad: true },
    { ssid: "Home", mhz: 2427, channel: 4, band: "2.4 GHz", signal: 84, own: true, bad: false },
    { ssid: "Across", mhz: 2437, channel: 6, band: "2.4 GHz", signal: 34, own: false, bad: false },
    { ssid: "Upstairs", mhz: 2462, channel: 11, band: "2.4 GHz", signal: 99, own: false, bad: false },
    { ssid: "Home", mhz: 5180, channel: 36, band: "5 GHz", signal: 70, own: true, bad: false },
  ],
  zigbee: [{ key: "z2m", name: "Zigbee2MQTT", channel: 11, mhz: 2405, devices: 74 }, { key: "zha", name: "ZHA", channel: 25, mhz: 2475, devices: 3 }],
  thread: [],
  overlaps: [],
};
const NETWORKS = { rows: [
  { key: "z2m", name: "Zigbee2MQTT", kind: "z2m", status: { state: "ok", words: "Running", since: null }, watched: 2,
    with_problem: 0, counts: COUNTS, last_outage: null, outages: 0 },
], air: AIR };
const WIFI_CARD = { kind: "channel", channel: 6,
  sentence: "Your Wi-Fi on channel 4 overlaps a neighbour's network on channel 1, heard at 52%. If your router lets you choose, channel 6 is clearer: it covers none of your Zigbee or Thread channels, and the strongest network heard near it is at 34%.",
  question: "A mesh router that picks its own channel may change it back. Device Sentinel only hears Wi-Fi where your server is." };
const PAGE = (key, extra = {}) => ({
  key, name: key === "wifi" ? "Wi-Fi" : "Matter", kind: key, status: { state: "ok", words: "Running", since: null },
  watched: 1, with_problem: 0, counts: COUNTS, window_days: 30, hardware: [], outages: [], notices: [], sensors: [],
  signal: null, pairing: null, wifi: null, devices: [], makeup: { roles: [], power: [], makers: [], other_makers: 0 },
  up: {}, patterns: [], cards: [], offenders: { repeat: [], drops: [] }, wifi_changes: null,
  firmware: { updates: [], changed: [], mixed: [] }, noise: null, own_page: false, radio: null, ...extra,
});

async function open(path, mode = "advanced", answers = {}) {
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
  const hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind === "networks") return JSON.parse(JSON.stringify(NETWORKS));
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = message.device_id;
        page.identity.radio = { kind: "zigbee", channel: 11, words: "Zigbee channel 11, from Zigbee2MQTT",
          warn: "A neighbour's Wi-Fi on channel 1, heard at 52%, covers this channel." };
        return page;
      }
      if (kind === "device_choices") return { areas: [], labels: [] };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  panel.hass = hass;
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

const text = (root) => root.querySelector(".pane").textContent;
const noStrays = (root) => !/\b(null|undefined|NaN)\b|\[object/.test(text(root));
const chart = (root) => root.querySelector(".pane [data-chart=air]");

(async () => {
  console.log("The Networks tab's chart, Advanced");
  let { root } = await open("/networks");
  const c = chart(root);
  check("the chart is there", Boolean(c));
  check("it is the first thing on the tab", c && root.querySelector(".pane").firstElementChild === c);
  check("its title and caption", c && c.textContent.includes("What the Server Hears") && c.textContent.includes("share one band"));
  const shapes = c ? [...c.querySelectorAll("path")] : [];
  check("one shape per 2.4 GHz network, none for 5 GHz", shapes.length === 5, shapes.length);
  const red = shapes.filter((p) => p.getAttribute("stroke").includes("error-color"));
  check("the two networks over Zigbee channel 11 are red", red.length === 2, red.length);
  check("the house's own network drawn in its own colour",
    shapes.some((p) => p.getAttribute("stroke").includes("primary-color")));
  const bars = c ? [...c.querySelectorAll("rect")] : [];
  check("one bar per Zigbee network", bars.length === 2, bars.length);
  check("the bars are named with their channels", c && c.textContent.includes("Zigbee2MQTT 11") && c.textContent.includes("ZHA 25"));
  check("a hidden network is named so in its tooltip", shapes.some((p) => p.textContent.startsWith("(hidden network)")));
  check("the 50% line is dashed", c && [...c.querySelectorAll("line")].some((l) => l.getAttribute("stroke-dasharray")));
  check("no stray words", noStrays(root), text(root));

  console.log("The chart, Simple");
  ({ root } = await open("/networks", "simple"));
  check("Simple has no chart", !chart(root));

  console.log("No Wi-Fi adapter");
  ({ root } = await open("/networks", "advanced", { networks: async () => ({ ...JSON.parse(JSON.stringify(NETWORKS)),
    air: { ...AIR, scan: "no_adapter", scanned_at: null, wifi: [] } }) }));
  check("the Zigbee bars still show", chart(root) && chart(root).querySelectorAll("rect").length === 2);
  check("with a note saying why there is no Wi-Fi", text(root).includes("no Wi-Fi adapter"), text(root));

  check("no red key when nothing is red", !text(root).includes("Covers a Zigbee or Thread channel"));
  ({ root } = await open("/networks", "advanced", { networks: async () => ({ ...JSON.parse(JSON.stringify(NETWORKS)),
    air: { ...AIR, scan: "adapter_off", scanned_at: null, wifi: [] } }) }));
  check("an adapter turned off says where to turn it on", text(root).includes("turned off in Settings, System, Network"), text(root));

  console.log("Nothing to draw");
  ({ root } = await open("/networks", "advanced", { networks: async () => ({ ...JSON.parse(JSON.stringify(NETWORKS)),
    air: { ...AIR, scan: "no_supervisor", wifi: [], zigbee: [], thread: [] } }) }));
  check("no chart at all", !chart(root));
  ({ root } = await open("/networks", "advanced", { networks: async () => ({ rows: NETWORKS.rows }) }));
  check("a 0.29.5 answer with no chart data still paints the tab", !chart(root) && text(root).includes("Zigbee2MQTT"));

  console.log("A device page's Radio Channel row");
  ({ root } = await open(`/device/${DEVICE}`));
  check("Advanced shows the row", text(root).includes("Radio Channel") && text(root).includes("Zigbee channel 11, from Zigbee2MQTT"), text(root));
  check("with its warning", text(root).includes("heard at 52%, covers this channel"));
  ({ root } = await open(`/device/${DEVICE}`, "simple"));
  check("Simple leaves it out", !text(root).includes("Radio Channel"));

  console.log("The Wi-Fi page");
  ({ root } = await open("/network/wifi?from=networks", "advanced", { network: async () => PAGE("wifi", {
    radio: { scanned_at: AIR.scanned_at, scan: "ok", heard: AIR.wifi }, cards: [WIFI_CARD] }) }));
  check("Networks the Server Hears", text(root).includes("Networks the Server Hears"), text(root));
  const rows = [...root.querySelectorAll(".pane table[data-shares=heard] tbody tr")];
  check("a row per network heard", rows.length === 6, rows.length);
  check("a hidden network reads so", rows[1] && rows[1].textContent.startsWith("Hidden network"));
  check("the house's own marked Yes", rows[2] && rows[2].children[1].textContent === "Yes");
  check("the channel 1 rows are red", rows[0] && /error-color/.test(rows[0].children[3].getAttribute("style") || ""));
  check("the channel card is on the page", text(root).includes("Recommendations for This Network") && text(root).includes("channel 6 is clearer"));
  check("no stray words", noStrays(root), text(root));
  ({ root } = await open("/network/wifi?from=networks", "advanced", { network: async () => PAGE("wifi", {
    radio: { scanned_at: null, scan: "no_adapter", heard: [] } }) }));
  check("no scan says why", text(root).includes("cannot scan for Wi-Fi"), text(root));

  console.log("The Matter page");
  ({ root } = await open("/network/matter?from=networks", "advanced", { network: async () => PAGE("matter", {
    radio: { thread: [{ channel: 15, devices: 4 }] } }) }));
  check("Thread channels", text(root).includes("Thread Channels") && text(root).includes("Channel 15") && text(root).includes("4 devices report it"), text(root));

  console.log("The Recommendations tab");
  ({ root } = await open("/recommendations", "advanced", { recommendations: async () => ({
    ...JSON.parse(JSON.stringify(payloads.recommendations)), networks: [{ key: "wifi", name: "Wi-Fi", cards: [WIFI_CARD] }] }) }));
  const card = root.querySelector(".pane article[data-kind='network-wifi-channel-6']");
  check("the channel card names its network", card && card.textContent.startsWith("Wi-Fi"), card && card.textContent);
  check("with its caveat", card && card.textContent.includes("may change it back"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
