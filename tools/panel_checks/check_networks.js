// File: tools/panel_checks/check_networks.js, Version: 0.28.6 (2026-11-08)
// Panel checks: the Networks tab and a network's page (rule DASH-17).
// Simple shows the tab, each network's state, its devices and anything to
// turn on; Advanced adds the last outage, the coordinator, the outages,
// signal health and pairing. A network's counts open the Devices tab on
// those devices.
// Run with: LC_ALL=en_US.UTF-8 node check_networks.js [path/to/panel.js]
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

const COUNTS = (over) => ({ frozen: 0, unavailable: 0, never_reported: 0, battery: 0, signal: 0, drops: 0, ...over });
const NETWORKS = { rows: [
  { key: "z2m", name: "Zigbee2MQTT", kind: "z2m", status: { state: "ok", words: "Running", since: null }, watched: 2,
    with_problem: 1, counts: COUNTS({ battery: 1 }),
    last_outage: { went_down: "2026-11-03T13:11:00+00:00", what: "Bridge: Zigbee2MQTT", duration: 180, devices: 74, open: false }, outages: 1 },
  { key: "mqtt", name: "MQTT Broker", kind: "mqtt", status: { state: "ok", words: "Running", since: null }, watched: 1,
    with_problem: 0, counts: COUNTS({}), last_outage: null, outages: 0 },
] };
const PAGE = {
  key: "z2m", name: "Zigbee2MQTT", kind: "z2m", status: { state: "ok", words: "Running", since: null },
  watched: 2, with_problem: 1, counts: COUNTS({ battery: 1 }), window_days: 30,
  hardware: [{ label: "Type", value: "EmberZNet", device_id: null }, { label: "Zigbee channel", value: "15", device_id: null }],
  outages: [{ went_down: "2026-11-03T13:11:00+00:00", what: "Bridge: Zigbee2MQTT", duration: 180, devices: 74, open: false }],
  notices: [{ title: "Zigbee2MQTT's Availability is off.", words: "Turn it on in Zigbee2MQTT. Device Sentinel never changes Zigbee2MQTT's settings.", open: "Zigbee2MQTT" }],
  sensors: [
    { kind: "last_seen", label: "Last Seen sensors", have: 2, on: 2, off: [] },
    { kind: "battery", label: "Battery sensors", have: 2, on: 1, off: [{ device_id: "dev-door", name: "Door Laundry", by: "user" }] },
  ],
  signal: { weak_week: 1, drops: 5, drop_devices: 2, railed: 0 },
  pairing: { windows: 1, last: { opened: "2026-10-29T15:05:00+00:00", duration: 240, open: false }, new_devices: 1 },
  wifi: null,
};
const DEVICES = { rows: [
  { device_id: "dev-door", name: "Door Laundry", integration: "mqtt", integration_name: "MQTT", muted: "", status: "reporting",
    problem: "battery 12%", acknowledged: false, last_activity: null, rhythm: null, window: null, networks: ["z2m"], groups: ["battery"], labels: [] },
  { device_id: "dev-lamp", name: "Lamp Hall", integration: "mqtt", integration_name: "MQTT", muted: "", status: "reporting",
    problem: "", acknowledged: false, last_activity: null, rhythm: null, window: null, networks: ["z2m"], groups: [], labels: [] },
  { device_id: "dev-relay", name: "Stove Vent Relays", integration: "tasmota", integration_name: "Tasmota", muted: "", status: "reporting",
    problem: "battery low", acknowledged: false, last_activity: null, rhythm: null, window: null, networks: ["wifi", "mqtt"], groups: ["battery"], labels: [] },
], excluded: [] };

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
  const calls = [];
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind === "networks") return JSON.parse(JSON.stringify(NETWORKS));
      if (kind === "network") {
        if (message.key !== "z2m") { const err = new Error("This house has no such network"); err.code = "not_found"; throw err; }
        return JSON.parse(JSON.stringify(PAGE));
      }
      if (kind === "devices") return JSON.parse(JSON.stringify(DEVICES));
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const tabs = (root) => [...root.querySelectorAll(".tab")].map((t) => t.textContent.replace(/ \(\d+\)$/, ""));
const text = (root) => root.querySelector(".pane").textContent;
const heads = (root) => [...root.querySelectorAll(".pane thead th")].map((th) => th.textContent);
const button = (root, label) => [...root.querySelectorAll(".pane button")].find((b) => b.textContent.startsWith(label));
const click = async (node) => { node.click(); await settle(); };
const noStrays = (root) => !/\b(null|undefined|NaN)\b|\[object/.test(text(root));

(async () => {
  console.log("The Networks tab, Advanced");
  let { root } = await open("/networks");
  const row = tabs(root);
  check("Networks sits after Integrations", row.indexOf("Networks") === row.indexOf("Integrations") + 1, row);
  check("its columns", JSON.stringify(heads(root)) === JSON.stringify(["NETWORK", "STATUS", "DEVICES", "WITH A PROBLEM", "LAST OUTAGE"]), heads(root));
  check("each network by name, linking to its page",
    [...root.querySelectorAll(".pane tbody a")].map((a) => a.getAttribute("href").split("?")[0]).join() === "/device-sentinel/network/z2m,/device-sentinel/network/mqtt");
  check("the problem kinds in brackets", text(root).includes("(1 battery)"), text(root));
  const bracketRoot = (await open("/networks", "advanced", { networks: async () => ({ rows: [{ ...JSON.parse(JSON.stringify(NETWORKS.rows[0])),
    with_problem: 2, counts: COUNTS({ frozen: 1, drops: 1 }) }] }) })).root;
  check("short drop-outs in the brackets read so", text(bracketRoot).includes("(1 frozen, 1 with short drop-outs)"), text(bracketRoot));
  check("the broker's devices read through it", text(root).includes("1 through it"));
  check("a network with no outage says so", text(root).includes("None in 30 days"));
  check("no stray words", noStrays(root), text(root));
    ({ root } = await open("/networks"));
  await click(button(root, "1"));
  const shown = () => [...root.querySelectorAll(".pane tbody tr td:first-child")].map((td) => td.textContent);
  check("WITH A PROBLEM opens the network's devices with a problem only", JSON.stringify(shown()) === JSON.stringify(["Door Laundry"]), shown());
  check("and says so", text(root).includes("Showing the devices on Zigbee2MQTT with a problem only."), text(root));
  await click(button(root, "Show all"));
  check("Show all after it shows every device, the problem filter off too", shown().length === 3, shown());

  console.log("The Networks tab, Simple");
  ({ root } = await open("/networks", "simple"));
  check("Networks is on Simple's tab row", tabs(root).includes("Networks"), tabs(root));
  check("Simple leaves out LAST OUTAGE", !heads(root).includes("LAST OUTAGE"), heads(root));

  console.log("A network's page, Advanced");
  let calls;
  ({ root, calls } = await open("/network/z2m?from=networks"));
  check("it asks for that network", calls.some((c) => c.type === "device_sentinel/network" && c.key === "z2m"));
  check("its name and state", root.querySelector(".pane h2").textContent === "Zigbee2MQTT" && text(root).includes("Running"));
  check("the back link names the tab", root.querySelector(".pane a").textContent.includes("Networks"));
  check("a tile per problem, Battery counting 1", button(root, "Battery") && button(root, "Battery").textContent === "Battery1",
    button(root, "Battery") && button(root, "Battery").textContent);
  check("Never reported and Short drop-outs only when counted", !button(root, "Never reported") && !button(root, "Short drop-outs"));
  check("the setting is told, never changed", text(root).includes("Availability is off") && text(root).includes("never changes"));
  check("all of a sensor on reads so", text(root).includes("All 2 on"));
  check("a sensor partly off reads its count", text(root).includes("1 of 2 on"));
  check("the coordinator", text(root).includes("The Coordinator") && text(root).includes("EmberZNet"));
  check("outages over 30 days", text(root).includes("Outages in the Last 30 Days") && text(root).includes("3m"), text(root));
  check("signal health this week", text(root).includes("Signal Health This Week") && text(root).includes("5, on 2 devices"));
  check("pairing", text(root).includes("Last pairing window"));
  check("no stray words on the page", noStrays(root), text(root));

  console.log("Turning a sensor on from the page");
  const turnOn = button(root, "Turn it on");
  check("a switched-off device has Turn it on", Boolean(turnOn));
  if (turnOn) await click(turnOn);
  const sent = calls.find((c) => c.type === "device_sentinel/device_turn_on");
  check("it is the device page's action, one device, said as from the Networks tab",
    sent && sent.device_id === "dev-door" && sent.kind === "battery" && sent.source === "network_page", sent);

  console.log("A network's page, Simple");
  ({ root } = await open("/network/z2m?from=networks", "simple"));
  check("Simple shows the tiles and the sensors", Boolean(button(root, "Battery")) && text(root).includes("Status Sensors and Settings"));
  check("Simple leaves out the coordinator, outages, signal and pairing",
    !text(root).includes("The Coordinator") && !text(root).includes("Outages in the Last")
    && !text(root).includes("Signal Health") && !text(root).includes("Pairing"), text(root));

  console.log("A count opens the Devices tab on those devices");
  let window;
  ({ root, window } = await open("/network/z2m?from=networks"));
  await click(button(root, "Battery"));
  check("the Devices tab opens", window.location.pathname === "/device-sentinel/devices", window.location.pathname);
  const names = () => [...root.querySelectorAll(".pane tbody tr td:first-child")].map((td) => td.textContent);
  check("only that network's devices with that problem", JSON.stringify(names()) === JSON.stringify(["Door Laundry"]), names());
  check("it says what it shows", text(root).includes("Showing the devices on Zigbee2MQTT with a battery problem only."), text(root));
  await click(button(root, "Show all"));
  check("Show all shows every device", names().length === 3, names());

  console.log("A network with no watched device");
  ({ root } = await open("/network/z2m?from=networks", "advanced", { network: async () => ({ ...JSON.parse(JSON.stringify(PAGE)),
    watched: 0, with_problem: 0, counts: COUNTS({}) }) }));
  check("says so, with nothing to press", text(root).includes("No watched device reports through it.")
    && !button(root, "Frozen") && !text(root).includes("Press a number"), text(root));

  console.log("A pairing window whose length is not known");
  ({ root } = await open("/network/z2m?from=networks", "advanced", { network: async () => ({ ...JSON.parse(JSON.stringify(PAGE)),
    pairing: { windows: 1, last: { opened: "2026-10-29T15:05:00+00:00", duration: null, open: false }, new_devices: 0 } }) }));
  check("reads length not recorded", text(root).includes("length not recorded"), text(root));

  console.log("Previous and Next from a network page");
  let panelNow;
  ({ root, panel: panelNow } = await open("/network/z2m?from=networks"));
  check("step through the devices the page names", JSON.stringify((panelNow._lists || {})["/network/z2m?from=networks"]) === JSON.stringify(["dev-door"]),
    panelNow._lists);

  console.log("A network the house lacks");
  ({ root } = await open("/network/matter?from=networks"));
  check("says so", text(root).includes("This house has no such network."), text(root));

  console.log("The Networks answer failing");
  ({ root } = await open("/devices", "advanced", { networks: async () => { throw new Error("boom"); } }));
  check("every other tab still draws", names().length === 3, text(root));
  ({ root } = await open("/networks", "advanced", { networks: async () => { throw new Error("boom"); } }));
  check("the tab says it could not load, not that the house has none",
    text(root).includes("could not load the networks") && !text(root).includes("No network found"), text(root));

  console.log("A stack that keeps no pairing window");
  ({ root } = await open("/network/z2m?from=networks", "advanced", { network: async () => ({ ...JSON.parse(JSON.stringify(PAGE)),
    pairing: { windows: null, last: null, new_devices: 2 } }) }));
  check("gives the devices added, and claims no window", text(root).includes("Devices added in 30 days")
    && !text(root).includes("Last pairing window"), text(root));

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
