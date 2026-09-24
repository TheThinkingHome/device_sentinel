// Checks for 0.23.0: the Repeat Offenders table on the Daily Brief tab,
// and the devices on MQTT's page that ride the broker. Run with
//   node check_0_23_0.js [path/to/panel.js]
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
  console.log("Repeat Offenders on the Daily Brief tab");
  const { root } = await open(`${PREFIX}/daily-brief`, {
    brief: (b) => ({ ...b, repeat: {
      available: true,
      rows: [{ device_id: DEVICE, name: "Closet Switch", what: "went unavailable",
        times: 2, when: "Sep 22, 3:07 PM; Sep 23, 4:12 AM", typical: "12m", with: "alone" }],
      paragraph: "This table lists repeat offenders.", words: "" } }),
  });
  const pane = root.querySelector(".pane");
  const tables = [...pane.querySelectorAll("table")];
  const repeatTable = tables.find((t) => t.textContent.includes("TYPICAL"));
  check("it is drawn as a table", Boolean(repeatTable), tables.map((t) => t.textContent.slice(0, 60)));
  const heads = repeatTable ? [...repeatTable.querySelectorAll("th")].map((h) => h.textContent) : [];
  check("with the brief's six columns", JSON.stringify(heads) === JSON.stringify(["DEVICE", "WHAT HAPPENED", "TIMES", "WHEN", "TYPICAL", "WITH"]), heads);
  const cells = repeatTable ? [...repeatTable.querySelectorAll("tbody td")].map((c) => c.textContent) : [];
  check("one row, its cells in order", cells[0] === "Closet Switch" && cells[2] === "2" && cells[5] === "alone", cells);
  check("the name opens the device", Boolean(repeatTable && repeatTable.querySelector("tbody a")), null);
  check("no pipes anywhere in the section", !pane.textContent.includes("| DEVICE") && !pane.textContent.includes("| Closet"), pane.textContent.slice(0, 400));
  check("the paragraph follows it", pane.textContent.includes("This table lists repeat offenders."), null);

  console.log("A day with no repeat offenders");
  const quiet = await open(`${PREFIX}/daily-brief`);
  check("still reads its sentence", quiet.root.querySelector(".pane").textContent.includes("No device failed more than once"), null);

  console.log("MQTT's page");
  const mqtt = await open(`${PREFIX}/integration/mqtt`, {
    integration: (p) => ({ ...p, domain: "mqtt", name: "MQTT", behind_broker: [
      { device_id: DEVICE, name: "Stove Vent Relays", integration: "Tasmota", watched: true,
        muted: "", set_aside: "", problem: "", acknowledged: false }] }),
  });
  const mqttText = mqtt.root.querySelector(".pane").textContent;
  check("lists the devices on the broker", mqttText.includes("Also on the broker") && mqttText.includes("Stove Vent Relays"), mqttText.slice(-300));
  check("naming the integration that owns each", mqttText.includes("Tasmota"), null);

  console.log("Any other integration's page");
  const other = await open(`${PREFIX}/integration/zha`, {
    integration: (p) => ({ ...p, domain: "zha", name: "ZHA", behind_broker: [] }),
  });
  check("has no such section", !other.root.querySelector(".pane").textContent.includes("Also on the broker"), null);

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
