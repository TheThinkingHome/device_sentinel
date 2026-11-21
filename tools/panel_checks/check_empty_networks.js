// File: tools/panel_checks/check_empty_networks.js, Version: 0.30.0 (2026-11-21)
// Panel checks: an empty Networks tab says why it is empty, from the
// server's Wi-Fi scan, and how to let Device Sentinel hear Wi-Fi, with
// the step pictures (rule DASH-17).
// Run with: LC_ALL=en_US.UTF-8 node check_empty_networks.js [path/to/panel.js]
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

let AIR = {};
const NETWORKS = { rows: [] };
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
      if (kind === "networks") return { rows: [], air: AIR };
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

const text = (root) => root.querySelector(".pane").textContent;
const pics = (root) => [...root.querySelectorAll(".pane img")].map((img) => decodeURIComponent(img.getAttribute("src").split("/").pop()));
const noStrays = (root) => !/\b(null|undefined|NaN)\b|\[object/.test(text(root));
const STEPS = ["HA Network - Step 1 Choose the Wi-Fi Interface.png", "HA Network - Step 2 Open Wi-Fi.png",
  "HA Network - Step 3 Search Networks.png", "HA Network - Step 4 Set a Static Address.png", "HA Network - Step 5 Choose the Network in Device Sentinel.png"];

(async () => {
  for (const mode of ["simple", "advanced"]) {
    console.log(`No Supervisor, ${mode}`);
    AIR = { scan: "no_supervisor", connected: null, wifi: [], zigbee: [], thread: [], overlaps: [] };
    let { root } = await open("/networks", mode);
    check("it says nothing is found yet", text(root).includes("No Wi-Fi or other networks found."), text(root));
    check("it names a Container or Core install and the router instead", text(root).includes("Container or Core install")
      && text(root).includes("UniFi, TP-Link Router or FRITZ!Box"), text(root));
    check("no pictures", pics(root).length === 0, pics(root));

    console.log(`No adapter, ${mode}`);
    AIR = { scan: "no_adapter", connected: null, wifi: [], zigbee: [], thread: [], overlaps: [] };
    ({ root } = await open("/networks", mode));
    check("it suggests a USB adapter and names the chips", text(root).includes("inexpensive USB Wi-Fi adapter")
      && text(root).includes("MT7612U") && text(root).includes("RTL8822CU"), text(root));
    check("the adapter photo, then the step pictures", JSON.stringify(pics(root)) === JSON.stringify(["usb_wifi_adapter.png", ...STEPS]), pics(root));
    check("the pictures come from the repository", [...root.querySelectorAll(".pane img")].every((img) =>
      img.getAttribute("src").startsWith("https://raw.githubusercontent.com/TheThinkingHome/device_sentinel/main/docs/images/")));
    check("each picture says what it shows", [...root.querySelectorAll(".pane img")].every((img) => img.getAttribute("alt")));
    check("no stray words", noStrays(root), text(root));

    console.log(`Adapter turned off, ${mode}`);
    AIR = { scan: "adapter_off", connected: false, wifi: [], zigbee: [], thread: [], overlaps: [] };
    ({ root } = await open("/networks", mode));
    check("it says turned off or not connected, and the step pictures", text(root).includes("turned off or not connected")
      && JSON.stringify(pics(root)) === JSON.stringify(STEPS), pics(root));
    check("the five steps in order, each with its picture", [...root.querySelectorAll(".pane ol li")].length === 5
      && text(root).includes("often named wlo1 or wlan0") && text(root).includes("wired network also uses Static."), text(root));
    check("then where to choose the network", text(root).includes("under Wi-Fi."), text(root));

    console.log(`Adapter on, not connected, ${mode}`);
    AIR = { scan: "ok", connected: false, wifi: [], zigbee: [], thread: [], overlaps: [] };
    ({ root } = await open("/networks", mode));
    check("the same steps", JSON.stringify(pics(root)) === JSON.stringify(STEPS), pics(root));

    console.log(`Adapter connected, ${mode}`);
    AIR = { scan: "ok", connected: true, wifi: [], zigbee: [], thread: [], overlaps: [] };
    ({ root } = await open("/networks", mode));
    check("it says to choose the network", text(root).includes("adapter is connected. Choose your network"), text(root));
    check("no pictures", pics(root).length === 0, pics(root));

    console.log(`An older server with no reason, ${mode}`);
    AIR = undefined;
    ({ root } = await open("/networks", mode, { networks: async () => ({ rows: [] }) }));
    check("only the first line, nothing stray", text(root).includes("No Wi-Fi or other networks found.") && noStrays(root), text(root));
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
