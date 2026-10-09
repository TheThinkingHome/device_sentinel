// Panel checks: the Same hardware row and the Type row's clear label (0.25.2).
// Run with: LC_ALL=en_US.UTF-8 node check_same_hardware.js [path/to/panel.js]
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
const DEVICE = payloads._ids ? payloads._ids.alpha : "alpha";
const CHOICES = ["Button", "CO Alarm", "Camera", "Cover", "Door/Window Sensor", "Leak Sensor", "Motion Sensor", "Plug",
  "Presence Sensor", "Smoke Alarm", "Soil Sensor", "Switch", "Temperature Sensor", "Vibration Sensor",
  "Voice Assistant", "Other"];
const ACTIONS = {
  area_id: null, name_by_user: null, integration_name: "0x00158d0001", labels: [], last_seen_off: false,
  mutes: { everything: { on: false }, freeze: { on: false }, battery: { on: false }, signal: { on: false } },
};
const block = (over) => Object.assign({ words: null, source: null, auto: null, choices: CHOICES, other: "Other" }, over);

let current = {};
async function open(path, type, rows, admin = true, same = undefined) {
  current = { type, rows, same };
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
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = DEVICE;
        page.identity.name = "Plug Master Router";
        page.identity.actions = admin ? JSON.parse(JSON.stringify(ACTIONS)) : null;
        page.identity.type = JSON.parse(JSON.stringify(current.type));
        if (current.same !== undefined) page.identity.same_hardware = JSON.parse(JSON.stringify(current.same));
        return page;
      }
      if (kind === "devices" && current.rows) return { rows: JSON.parse(JSON.stringify(current.rows)) };
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
  return { window, panel, root: panel.shadowRoot, calls };
}

const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild && tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const labels = (root) => [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].map((tr) => tr.firstChild && tr.firstChild.textContent);
const buttonIn = (node, text) => node && [...node.querySelectorAll("button")].find((b) => b.textContent === text);
const click = async (node) => { node.click(); await settle(); };
const DEVICE_PATH = `${PREFIX}/device/${DEVICE}`;

(async () => {
  console.log("\nThe Same hardware row (0.25.2)");
  let { root } = await open(DEVICE_PATH, block({ words: "Bluetooth Proxy", source: "role", auto: "Bluetooth Proxy", auto_source: "role" }));
  check("No group, no row", !labels(root).includes("Same hardware"), labels(root));

  const group = {
    watched_through: DEVICE,
    devices: [
      { device_id: DEVICE, name: "Office proxy", integration: "ESPHome", watched: true, set_aside: null },
      { device_id: "bs", name: "Sight copy", integration: "BlueSight", watched: false, set_aside: "copy" },
      { device_id: "uf", name: "office-proxy", integration: "UniFi Network", watched: false, set_aside: "excluded" },
      { device_id: "bt", name: "<b>Office adapter</b>", integration: null, watched: false, set_aside: null },
      { device_id: "np", name: "Office never watched", integration: "Bluetooth", watched: false, set_aside: "no entities", has_page: false },
    ],
  };
  ({ root } = await open(DEVICE_PATH, block({ words: "Bluetooth Proxy", source: "role", auto: "Bluetooth Proxy", auto_source: "role" }),
    null, true, group));
  let order = labels(root);
  check("The row sits right after Connects, or before Address", order.includes("Same hardware")
    && (order.indexOf("Same hardware") === order.indexOf("Connects") + 1 || order.indexOf("Address") === order.indexOf("Same hardware") + 1), order);
  let cell = rowCell(root, "Same hardware");
  const text = cell ? cell.textContent : "";
  check("Watched here: says so", text.startsWith("Device Sentinel watches this hardware through this device."), text);
  check("Lists the others, not this device", !text.includes("Office proxy") && text.includes("Sight copy (BlueSight), a copy, not judged on its own"), text);
  check("An exclusion keeps its own reason", text.includes("office-proxy (UniFi Network), set aside: excluded"), text);
  check("No integration reads unknown, and a name is text, never markup",
    text.includes("<b>Office adapter</b> (unknown), not watched") && !cell.querySelector("b"), text);
  const links = cell ? [...cell.querySelectorAll("a")].map((a) => a.getAttribute("href")) : [];
  check("Each other device with a page links to it", links.length === 3 && links.every((h) => h && h.includes("/device/")), links);
  check("A device with no page is named without a link", text.includes("Office never watched (Bluetooth), set aside: no entities")
    && ![...cell.querySelectorAll("a")].some((a) => a.textContent === "Office never watched"), text);

  const fromCopy = JSON.parse(JSON.stringify(group));
  fromCopy.watched_through = "bs";
  fromCopy.devices[0].watched = false; fromCopy.devices[0].set_aside = "copy";
  fromCopy.devices[1].watched = true; fromCopy.devices[1].set_aside = null;
  ({ root } = await open(DEVICE_PATH, block({}), null, true, fromCopy));
  cell = rowCell(root, "Same hardware");
  check("Watched elsewhere: says so", cell && cell.textContent.startsWith("Device Sentinel watches this hardware through another device."),
    cell && cell.textContent);

  const both = JSON.parse(JSON.stringify(group));
  both.watched_through = null;
  both.devices[1].watched = true; both.devices[1].set_aside = null;
  ({ root } = await open(DEVICE_PATH, block({}), null, true, both));
  cell = rowCell(root, "Same hardware");
  check("Two watched for now: never says this one is watched elsewhere",
    cell && cell.textContent.startsWith("Device Sentinel watches this device, and another device for the same hardware too."),
    cell && cell.textContent);

  const none = JSON.parse(JSON.stringify(group));
  none.watched_through = null;
  none.devices[0].watched = false; none.devices[0].set_aside = "excluded";
  ({ root } = await open(DEVICE_PATH, block({}), null, true, none));
  cell = rowCell(root, "Same hardware");
  check("None watched: says so", cell && cell.textContent.startsWith("Device Sentinel watches none of these devices."),
    cell && cell.textContent);

  ({ root } = await open(DEVICE_PATH, block({}), null, false, group));
  check("A non-admin still sees the row", !!rowCell(root, "Same hardware"));

  console.log("\nThe clear label names who answered (0.25.2)");
  ({ root } = await open(DEVICE_PATH, block({ words: "Lamp", source: "owner", auto: "Zigbee Router", auto_source: "role" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  check("A role or known model: Use Device Sentinel's answer",
    !!buttonIn(rowCell(root, "Type"), "Use Device Sentinel's answer (Zigbee Router)"));
  ({ root } = await open(DEVICE_PATH, block({ words: "Lamp", source: "owner", auto: "Plug", auto_source: "known model" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  check("A known model: Use Device Sentinel's answer", !!buttonIn(rowCell(root, "Type"), "Use Device Sentinel's answer (Plug)"));
  ({ root } = await open(DEVICE_PATH, block({ words: "Lamp", source: "owner", auto: "Switch", auto_source: "entities" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  check("Entities: Use what its entities say", !!buttonIn(rowCell(root, "Type"), "Use what its entities say (Switch)"));
  ({ root } = await open(DEVICE_PATH, block({ words: "Lamp", source: "owner", auto: "Plug", auto_source: "known model", model_answer: "Fan" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  check("The model's answer still comes first", !!buttonIn(rowCell(root, "Type"), "Use the model's answer (Fan)"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
