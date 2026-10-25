// File: check_hub_pages.js, Version: 0.27.4 (2026-10-25)
// Panel checks: judged by its hub (0.26.3, rulings #663 to #665). A hub's
// page and the pages of the devices it controls, in the words James approved
// on 14 October 2026, and the Classification tick.
// Run with: LC_ALL=en_US.UTF-8 node check_hub_pages.js [path/to/panel.js]
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
    battery: { on: true, source: "label: Quiet", here: false },
    signal: { on: true, source: "label: Quiet", here: false },
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


const ago = (min) => new Date(Date.now() - min * 60e3).toISOString();
const HUB = { name: "Basement Lutron Caseta", device_id: "hub1", up: true, since: ago(240), kind: "light" };
const BEHIND = [
  { device_id: "d1", name: "Backyard Flood Lights", type: "Switch", standing: "Watched, waiting for its hub", last_seen: ago(600), problem: "" },
  { device_id: "d2", name: "Garage Main Lights", type: "Switch", standing: "Watched, waiting for its hub", last_seen: ago(420), problem: "" },
];
const hubPage = (tweak) => (m) => {
  const page = JSON.parse(JSON.stringify(payloads.device));
  page.identity.device_id = m.device_id;
  page.identity.name = "Garage Lutron Caseta";
  page.identity.actions = null;
  page.readings = [];
  page.silences = [];
  // A watched, unmuted device with no verdict of its own, as most are.
  page.identity.muted = "";
  page.status.category = "reporting";
  tweak(page);
  return page;
};

(async () => {
  console.log("\nJudged by its hub (0.26.3)");
  let r = await open({ answers: { device: hubPage((p) => {
    p.hub_self = { up: false, since: ago(12), behind: BEHIND, outages: [{ start: ago(12), end: null }] };
  }) } });
  let text = r.root.textContent;
  check("A downed hub reads Down", /Down\s*Down since/.test(text) || text.includes("Down since"), text.slice(0, 300));
  check("Its status says the devices it controls are listed on this page",
    /The 2 devices it controls are listed on this page, not on the Problem List, until it is back\./.test(text));
  check("How It Is Judged, by its connection",
    text.includes("By its connection. Home Assistant's Lutron integration checks the hub once a minute. When a check fails, Device Sentinel reports the hub down within about two minutes and lists the devices it controls on this page."));
  check("Its own switch cannot be judged",
    text.includes("Its own switch, Smart Away, changes only when Home Assistant restarts, so its silence cannot be judged."));
  check("The heading is Devices This Hub Controls", text.includes("Devices This Hub Controls"));
  check("Each device it controls is waiting for its hub", (text.match(/Watched, waiting for its hub/g) || []).length === 2);
  check("The outage column is DEVICES IT CONTROLS", text.includes("DEVICES IT CONTROLS"));
  check("An open outage reads still down", text.includes("still down"));
  check("No rhythm charts on a hub", r.root.querySelectorAll(".rulechart").length === 0);
  check("No Last seen on a hub's page", !text.includes("Last seen sensor") && !text.includes("Events seen"));
  check("Nothing says held under", !/held under/i.test(text));

  r = await open({ answers: { device: hubPage((p) => {
    p.hub_self = { up: true, since: ago(30), behind: BEHIND.map((d) => ({ ...d, standing: "Watched" })), outages: [] };
  }) } });
  text = r.root.textContent;
  check("A hub that is up says when it connected and how it is checked",
    /Connected since .*\. Home Assistant's Lutron integration checks the hub once a minute\./.test(text));

  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB }; }) } });
  text = r.root.textContent;
  check("A light is judged by its hub", text.includes("Judged by its hub"));
  check("Its status names the hub and why its silence cannot be judged",
    /Basement Lutron Caseta is up, connected since .*\. Lutron reports this light only when someone uses it, so its silence cannot be judged\./.test(text));
  check("The hub's name links to the hub's page",
    [...r.root.querySelectorAll("a")].some((a) => a.textContent === "Basement Lutron Caseta" && a.getAttribute("href").includes("/device/hub1")));
  check("How It Is Judged, by its hub",
    text.includes("By its hub. Lutron tells Home Assistant whether Basement Lutron Caseta is connected, and nothing about a single light: not when it last spoke, not its battery, not when it loses power. When the hub goes down, this light is listed on the hub's page, not on its own."));
  check("A light that loses power alone cannot be seen",
    text.includes("A light that loses power on its own while its hub stays up cannot be seen. Lutron does not report it."));
  check("No rhythm charts on a light", r.root.querySelectorAll(".rulechart").length === 0);
  check("A light keeps its Last seen", text.includes("Last seen sensor"));
  check("No Pico line on a light", !text.includes("Each press of one of its buttons"));

  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB, up: false, since: ago(12) }; }) } });
  text = r.root.textContent;
  check("Its hub is down", text.includes("Its hub is down"));
  check("Until it is back, the light is listed on the hub's page",
    /Basement Lutron Caseta went down at .*\. Until it is back, this light is listed on the hub's page, not on the Problem List\./.test(text));

  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Upstairs Hallway Pico 1"; p.hub = { ...HUB, kind: "remote" }; }) } });
  text = r.root.textContent;
  check("A Pico says a press counts as it reporting",
    text.includes("Each press of one of its buttons counts as the remote reporting, and shows as Last seen."));

  r = await open({ answers: { device: hubPage(() => {}) } });
  check("Any other device keeps its rhythm section", r.root.textContent.includes("Its Rhythm"));

  // Found by the adversarial round of 14 October 2026.
  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB }; p.status.category = "frozen"; }) } });
  text = r.root.textContent;
  check("A light with a verdict of its own still shows it", !text.includes("Judged by its hub") && /frozen/i.test(r.root.querySelector(".devstatus").textContent));
  // A hub's mute covers its devices (James, 14 October 2026).
  r = await open({ answers: { device: hubPage((p) => {
    p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB };
    p.identity.actions = { area_id: null, name_by_user: null, integration_name: null, labels: [], last_seen_off: false,
      mutes: { everything: { on: false }, freeze: { on: true, here: false, source: "hub" }, battery: { on: false }, signal: { on: false } } };
  }) } });
  text = r.root.textContent;
  check("A device muted with its hub says so and links the hub", text.includes("Freeze is muted with its hub. Change it on Basement Lutron Caseta's page."), text.slice(0, 400));
  check("It does not send the person to the settings for it", !text.includes("Freeze is muted by hub"));
  r = await open({ answers: { device: hubPage((p) => {
    p.identity.muted = "freeze (device)";
    p.hub_self = { up: false, since: ago(5), behind: BEHIND.slice(0, 1), outages: [] };
  }) } });
  text = r.root.textContent;
  check("A muted hub that is down reads Down, muted", text.includes("Down, muted"));
  check("One device it controls reads in the singular", text.includes("The device it controls is listed on this page"));
  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB, up: null }; }) } });
  text = r.root.textContent;
  check("A hub whose connection cannot be read is not called up", text.includes("Device Sentinel cannot read Basement Lutron Caseta's connection right now.") && !text.includes("is up, connected since"));
  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Living Room Shade"; p.hub = { ...HUB, kind: "shade", battery: true }; }) } });
  text = r.root.textContent;
  check("A shade with a battery sensor is not told it has no battery",
    text.includes("nothing about a single shade: not when it last spoke, not when it loses power.") && !text.includes("not its battery"));
  r = await open({ answers: { device: hubPage((p) => { p.identity.name = "Kitchen Main Lights"; p.hub = { ...HUB, since: null }; }) } });
  check("A missing time never prints 1969", !/1969|Invalid Date/.test(r.root.textContent));

  r = await open({ path: `${PREFIX}/classification`, answers: { classification: () => {
    const data = JSON.parse(JSON.stringify(payloads.classification));
    data.rows = data.rows.slice(0, 2);
    data.rows[0].judged = "judged by its hub";
    data.rows[1].judged = "hub";
    return data;
  } } });
  text = r.root.textContent;
  check("Classification says judged by its hub", text.includes("✓ judged by its hub"));
  check("Classification marks the hub", text.includes("✓ hub"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
