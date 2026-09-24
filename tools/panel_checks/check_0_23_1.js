// Checks for 0.23.1: how a battery reports, shown on the device page
// and on Battery Trends. Run with
//   node check_0_23_1.js [path/to/panel.js]
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
const rows = (root) => [...root.querySelectorAll("tr")].map((tr) => [...tr.children].map((c) => c.textContent));

(async () => {
  console.log("The device page");
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      device: (d) => ({ ...d, identity: { ...d.identity, battery_steps: "Coarse" } }),
    });
    const row = rows(root).find((cells) => cells[0] === "Battery steps");
    check("has a Battery steps row", !!row, rows(root).map((r) => r[0]));
    check("reading the word it was given", row && row[1] === "Coarse", row);
    const order = rows(root).map((r) => r[0]);
    check("beneath Battery type", order.indexOf("Battery steps") === order.indexOf("Battery type") + 1, order);
  }
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      device: (d) => ({ ...d, identity: { ...d.identity, battery_steps: "" } }),
    });
    check("a device with no battery has no such row", !rows(root).some((cells) => cells[0] === "Battery steps"));
  }
  console.log("Battery Trends");
  {
    const { root } = await open(`${PREFIX}/battery-trends`, {
      battery_trends: (b) => ({ ...b, steady: [{ device_id: DEVICE, name: "Office Temp/Humid", level: 30, rate: -1.4, days: 14, steps: "Coarse" }] }),
    });
    const heads = [...root.querySelectorAll("th")].map((th) => th.textContent);
    check("the steady table has a STEPS column", heads.includes("STEPS"), heads);
    const row = rows(root).find((cells) => cells[0] === "Office Temp/Humid");
    check("the coarse cell says so", row && row[row.length - 1] === "Coarse", row);
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
