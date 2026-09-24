// Checks for 0.23.2: a device that keeps dropping out, on its page
// and on Signal Trends. Run with
//   node check_0_23_2.js [path/to/panel.js]
// The harness behaves like Home Assistant's router: whenever the
// address changes, by a link, a pushState or the back button, it hands
// the panel its new route, which is how the panel learns where it is.
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

async function open(address, extra) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${address}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  const route = () => ({ prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) });
  // Home Assistant's router: a new route on every change of address.
  window.addEventListener("location-changed", () => {
    if (window.location.pathname.startsWith(PREFIX)) panel.route = route();
  });
  window.addEventListener("popstate", () => { panel.route = route(); });
  window.document.body.append(panel);
  panel.route = route();
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

const selected = (root) => {
  const tab = root.querySelector('.tab[aria-selected="true"]');
  return tab ? tab.textContent : null;
};
const clickTab = (root, name) => [...root.querySelectorAll(".tab")].find((b) => b.textContent === name).click();
const where = (window) => window.location.pathname + window.location.search;
const backLink = (root) => {
  const link = root.querySelector(".pane > p:first-child a");
  return link ? { text: link.textContent, href: link.getAttribute("href") } : null;
};

const text = (root) => root.querySelector(".pane").textContent;

const DEVICE = payloads._ids.bravo;

(async () => {
  console.log("The device page");
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      device: (d) => ({ ...d, status: { ...d.status, category: "flapping", flap: "dropped out 5 times since 7:00 AM" } }),
    });
    const said = text(root);
    check("reads Flapping with the drop count", said.includes("Flapping, dropped out 5 times since 7:00 AM"), said.slice(0, 200));
  }
  console.log("Signal Trends");
  {
    const { root } = await open(`${PREFIX}/signal-trends`, {
      signal_trends: (s) => ({ ...s, dropping_out: [{ device_id: DEVICE, name: "S73 Door tilt sensor", drops: 5, since: "2026-09-24T12:00:00+00:00", signal: 110 }] }),
    });
    const heads = [...root.querySelectorAll("h3")].map((h) => h.textContent);
    check("has Devices That Keep Dropping Out", heads.some((h) => h.startsWith("Devices That Keep Dropping Out")), heads);
    check("naming the device", text(root).includes("S73 Door tilt sensor"));
    check("with the check to make", text(root).includes("Check its signal and the router it connects through."));
  }
  {
    const { root } = await open(`${PREFIX}/signal-trends`, { signal_trends: (s) => ({ ...s, dropping_out: [] }) });
    check("an empty section says so", text(root).includes("No device is dropping out again and again."));
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
