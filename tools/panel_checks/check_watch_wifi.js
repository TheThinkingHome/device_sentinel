// File: tools/panel_checks/check_watch_wifi.js, Version: 0.30.3 (2026-11-23)
// Panel checks: under the networks a house has, a closed "Watch your
// Wi-Fi" section for a server that could hear its Wi-Fi and does not yet;
// none on a Container or Core install, or once Wi-Fi is watched (rule DASH-17).
// Run with: LC_ALL=en_US.UTF-8 node check_watch_wifi.js [path/to/panel.js]
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
const ROWS = [{ key: "lutron:hub", name: "Lutron Smart Bridge", status: "up", watched: 4, with_problem: 0, counts: {}, last_outage: null, window_days: 14 }];
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
      if (kind === "networks") return { rows: ROWS, air: AIR };
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
  const section = (root) => root.querySelector(".pane details.watchwifi");
  const air = (extra) => ({ connected: null, wifi: [], zigbee: [], thread: [], overlaps: [], watching: false, ...extra });
  for (const mode of ["simple", "advanced"]) {
    console.log(`Adapter found, not used, ${mode}`);
    AIR = air({ scan: "ok", connected: false });
    let { root } = await open("/networks", mode);
    const s = section(root);
    check("the networks are listed", text(root).includes("Lutron Smart Bridge"), text(root));
    check("a closed section titled Watch your Wi-Fi", !!s && s.open === false
      && s.querySelector("summary").textContent.startsWith("Watch your Wi-Fi") && !s.querySelector("summary").textContent.includes("too"));
    check("its line says the adapter is unused", s.textContent.includes("Your server has a Wi-Fi adapter it isn't using"));
    check("it holds the five steps with their pictures", pics(root).filter((f) => STEPS.includes(f)).length === 5, pics(root));
    check("step 3 says any network will do", s.textContent.includes("It doesn't have to be the one your devices use"));
    check("no stray words", noStrays(root), text(root));

    console.log(`No adapter, ${mode}`);
    AIR = air({ scan: "no_adapter" });
    ({ root } = await open("/networks", mode));
    check("closed, saying an adapter would let it hear", !!section(root) && section(root).open === false
      && section(root).textContent.includes("A USB Wi-Fi adapter would let Device Sentinel hear it"));
    check("the adapter picture and the steps inside", pics(root).includes("usb_wifi_adapter.png")
      && pics(root).filter((f) => STEPS.includes(f)).length === 5, pics(root));

    console.log(`Adapter connected, no network chosen, ${mode}`);
    AIR = air({ scan: "ok", connected: true });
    ({ root } = await open("/networks", mode));
    check("closed, pointing to the settings, no steps", !!section(root)
      && section(root).textContent.includes("Choose your network in Device Sentinel's settings")
      && pics(root).filter((f) => STEPS.includes(f)).length === 0);

    console.log(`Container or Core, ${mode}`);
    AIR = air({ scan: "no_supervisor" });
    ({ root } = await open("/networks", mode));
    check("no section", !section(root), text(root));

    console.log(`Wi-Fi already watched, ${mode}`);
    AIR = air({ scan: "ok", connected: true, watching: true });
    ({ root } = await open("/networks", mode));
    check("no section", !section(root), text(root));

    console.log(`First scan not run yet, ${mode}`);
    AIR = air({ scan: "not_yet" });
    ({ root } = await open("/networks", mode));
    check("no section", !section(root), text(root));
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
