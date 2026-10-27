// File: tools/panel_checks/check_integration_names.js, Version: 0.27.10 (2026-10-27)
// Panel checks: an integration is named as Home Assistant shows it, the
// way the Daily Brief names it (rule GEN-07).
// The Classification tab's INTEGRATION column drew and sorted the id
// ("zwave_js"), though the server sends integration_name ("Z-Wave").
// The column now shows and sorts by the name; the link keeps the id.
// Run with: LC_ALL=en_US.UTF-8 node check_integration_names.js [path/to/panel.js]
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

async function open(path, answers = {}) {
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
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

(async () => {
  console.log("The Classification tab's INTEGRATION column (rule GEN-07)");
  // Ids and names that sort differently: by id, mqtt comes before
  // zwave_js; by name, "Z-Wave" comes after "MQTT", and "Alarm Hub"
  // (id zzz_alarm) first.
  const classification = () => {
    const c = JSON.parse(JSON.stringify(payloads.classification));
    const names = {
      "Alpha Panel": ["zwave_js", "Z-Wave"], "Bravo Phone": ["mqtt", "MQTT"], "Charlie Plug": ["zzz_alarm", "Alarm Hub"],
    };
    for (const row of c.rows) {
      const [id, name] = names[row.name] || [row.integration, row.integration === "device_sentinel" ? "Device Sentinel" : "Test"];
      row.integration = id;
      row.integration_name = name;
    }
    return c;
  };
  const { root } = await open(`${PREFIX}/classification`, { classification });
  const pane = root.querySelector(".pane");
  const heads = () => [...pane.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  const col = heads().findIndex((h) => h.startsWith("INTEGRATION"));
  const cells = () => [...pane.querySelectorAll("tbody tr")].map((tr) => [tr.cells[0].textContent, tr.cells[col].textContent, tr.cells[col].querySelector("a")]);
  const cell = (n) => cells().find((c) => c[0] === n) || [];
  check("Alpha Panel (zwave_js) reads Z-Wave", cell("Alpha Panel")[1] === "Z-Wave", cell("Alpha Panel")[1]);
  check("Bravo Phone (mqtt) reads MQTT", cell("Bravo Phone")[1] === "MQTT", cell("Bravo Phone")[1]);
  const link = cell("Alpha Panel")[2];
  check("The link still opens the integration by its id", !!link && /\/integration\/zwave_js\?/.test(link.getAttribute("href")), link && link.getAttribute("href"));
  const sortButton = [...pane.querySelectorAll("thead th button")].find((b) => b.textContent.startsWith("INTEGRATION"));
  sortButton.click();
  await settle();
  const order = cells().map((c) => c[1]);
  const sorted = [...order].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  check("Sorting INTEGRATION sorts by the name shown", JSON.stringify(order) === JSON.stringify(sorted) && order[0] === "Alarm Hub", order);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
