// File: tools/panel_checks/check_firmware_card.js, Version: 0.29.2 (2026-11-15)
// Panel checks: the Firmware Updates card (rule REC-12). One row a
// model with what is behind, or a device of its own when it names no
// model, its devices linked to their Home Assistant pages, the
// Zigbee2MQTT words with a link to its panel, and a tick a row.
// Run with: LC_ALL=en_US.UTF-8 node check_firmware_card.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) {
    passed += 1;
    console.log(`  ok    ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
  }
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));


async function open(cards, panels = {}) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/recommendations`, virtualConsole,
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
  panel.hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "recommendations") return { lines: [], devices: JSON.parse(JSON.stringify(cards)), closing: "", power: {}, types: { choices: [], other: "Other" } };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    panels,
  };
  await settle(); await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const FIRMWARE = {
  kind: "firmware", title: "Firmware Updates", body: "", simple: true, active: 2,
  devices: [
    { device_id: "s1", name: "LightwaveRF L42MK3", area: null, acknowledged: false, model_key: "k1", zigbee2mqtt: false,
      text: "2 of your LightwaveRF L42MK3 plugs require a firmware update. 1 is on the new firmware: 6.10.0. 2 are on an old firmware: 6.06.0.",
      behind: [{ device_id: "s1", name: "Socket Hall", installed: "6.06.0" }, { device_id: "s2", name: "Socket Desk", installed: "6.06.0" }] },
    { device_id: "d1", name: "Third Reality 3RDS17BZ", area: null, acknowledged: false, model_key: "k2", zigbee2mqtt: true,
      text: "1 of your Third Reality 3RDS17BZ door/window sensors requires a firmware update. The new firmware is 52.",
      behind: [{ device_id: "d1", name: "Door Garage", installed: "47" }] },
  ],
};
const Z2M_PANEL = { "45df7312_zigbee2mqtt": { url_path: "45df7312_zigbee2mqtt", title: "Zigbee2MQTT", config: {} } };

(async () => {
  console.log("The Firmware Updates card (rule REC-12)");
  let { root } = await open([FIRMWARE], Z2M_PANEL);
  const card = [...root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "firmware");
  check("The card is there with its count", !!card && card.querySelector("h3").textContent === "Firmware Updates (2)", card && card.querySelector("h3").textContent);
  const text = card ? card.textContent.replace(/\s+/g, " ") : "";
  check("Each row says what is behind", text.includes("2 of your LightwaveRF L42MK3 plugs require a firmware update. 1 is on the new firmware: 6.10.0.")
    && text.includes("The new firmware is 52."));
  check("The summary counts models", /Show the 2 models/.test(text), text.slice(0, 200));
  const links = card ? [...card.querySelectorAll("li a")].map((a) => [a.textContent, a.getAttribute("href")]) : [];
  check("Each device behind links to its Home Assistant page", JSON.stringify(links) === JSON.stringify([
    ["Socket Hall", "/config/devices/device/s1"], ["Socket Desk", "/config/devices/device/s2"], ["Door Garage", "/config/devices/device/d1"]]), links);
  check("Each device shows the version it is on", /Socket Hall 6\.06\.0/.test(text));
  check("The Zigbee2MQTT row says how to check every device", text.includes("Open the Zigbee2MQTT dashboard, select OTA, tick the box that selects all devices and press Check selected.")
    && text.includes("Each one then offers its update."));
  const z2m = card ? [...card.querySelectorAll("a")].find((a) => a.textContent === "Open the Zigbee2MQTT dashboard") : null;
  check("Its first words link to the Zigbee2MQTT panel", !!z2m && z2m.getAttribute("href") === "/45df7312_zigbee2mqtt", z2m && z2m.getAttribute("href"));
  check("Only the Zigbee2MQTT row says so", (text.match(/select OTA/g) || []).length === 1);
  const boxes = card ? [...card.querySelectorAll('input[type="checkbox"]')] : [];
  check("Each row has its own Acknowledged box", boxes.length === 2);
  check("No null, undefined or NaN", !/null|undefined|NaN/.test(root.textContent));

  ({ root } = await open([FIRMWARE]));
  const plain = [...root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "firmware");
  const words = plain ? plain.textContent.replace(/\s+/g, " ") : "";
  check("With no Zigbee2MQTT panel the words stay, with no link",
    words.includes("Open the Zigbee2MQTT dashboard, select OTA") && ![...plain.querySelectorAll("a")].some((a) => a.textContent === "Open the Zigbee2MQTT dashboard"));

  console.log("A device that names no model (rule REC-12)");
  ({ root } = await open([{ ...FIRMWARE, active: 1, devices: [{ device_id: "p1", name: "Bluetooth Proxy", area: null, acknowledged: false,
    model_key: "device:p1", zigbee2mqtt: false,
    text: "Bluetooth Proxy requires a firmware update. It is on 2026.10.1. The new firmware is 2026.11.0.",
    behind: [{ device_id: "p1", name: "Bluetooth Proxy", installed: "2026.10.1" }] }] }]));
  const alone = [...root.querySelectorAll("article.rec")].find((a) => a.dataset.kind === "firmware");
  const aloneText = alone ? alone.textContent.replace(/\s+/g, " ") : "";
  check("Its own row, named for the device", aloneText.includes("Bluetooth Proxy requires a firmware update. It is on 2026.10.1. The new firmware is 2026.11.0."));
  check("It links to its Home Assistant page", !!alone && [...alone.querySelectorAll("li a")].some((a) => a.getAttribute("href") === "/config/devices/device/p1"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
