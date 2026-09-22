// Checks for 0.22.24: what a device page says when the device is not
// speaking. Run with
//   node check_0_22_24.js [path/to/panel.js]
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

const DEVICE = payloads._ids ? payloads._ids.alpha : null;
const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000).toISOString();
const quiet = (extra) => ({
  device: (page) => {
    page.status.category = "frozen";
    page.status.last_activity = hoursAgo(18);
    page.readings = [
      { kind: "signal", entity_id: "sensor.watering_linkquality" },
      { kind: "last_seen", entity_id: "sensor.watering_last_seen" },
      { kind: "battery", entity_id: "sensor.watering_battery" },
    ];
    page.silences = [{
      since: hoursAgo(18), silence: 32400, window: 2290,
      ended: "intervention (reboot)", at: hoursAgo(9),
      learned: null, still_silent: true,
    }];
    page.battery = { ...page.battery, now: 186, readable: false, threshold: 15,
      daily: [186, 186, 186, 186, 186, 186, 186, 186], windows: {} };
    return { ...page, ...(extra || {}) };
  },
});
const states = {
  "sensor.watering_linkquality": { state: "180", attributes: { unit_of_measurement: "lqi" }, last_changed: hoursAgo(0.2) },
  "sensor.watering_last_seen": { state: hoursAgo(18), attributes: {}, last_changed: hoursAgo(0.2) },
  "sensor.watering_battery": { state: "unknown", attributes: {}, last_changed: hoursAgo(0.2) },
};

(async () => {
  console.log("A device that went quiet");
  const { root, panel } = await open(`${PREFIX}/device/${DEVICE}`, quiet());
  panel.hass = { ...panel.hass, states };
  await settle();
  const page = text(root);
  check("its pill reads Frozen", page.includes("Frozen"), page.slice(0, 200));
  const tiles = [...root.querySelectorAll(".reading")].map((t) => t.textContent);
  check("a reading it cannot give gets no tile", tiles.every((t) => !t.includes("unknown")), tiles);
  check("its tiles are dated from the device", tiles.every((t) => t.includes("last heard")), tiles);
  check("none says it changed a moment ago", tiles.every((t) => !t.includes("changed 12m")), tiles);
  check("its silence says it is still running", page.includes("still silent"), page.slice(-800));
  check("a reading that is not a percentage loses the percent sign", !page.includes("186%"), page);
  check("and loses your low-battery line", !page.includes("Your threshold, 15%"), page);
  check("and says why", page.includes("raw reading rather than a percentage"), page.slice(-900));

  console.log("A device nobody watches");
  const aside = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (p) => {
      p.status.category = "set_aside";
      p.identity.watched = false;
      p.identity.set_aside = "no entities";
      return p;
    },
  });
  const asidePage = text(aside.root);
  check("its pill reads Set aside", asidePage.includes("Set aside"), asidePage.slice(0, 260));
  check("and not Reporting", !asidePage.includes("Reporting"), asidePage.slice(0, 260));

  console.log("A device that has never spoken");
  const never = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (p) => {
      p.status.category = "never_reported";
      p.status.last_activity = null;
      return p;
    },
  });
  check("its pill says it has never reported", text(never.root).includes("Never reported"), text(never.root).slice(0, 260));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
