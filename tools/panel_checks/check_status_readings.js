// File: tools/panel_checks/check_status_readings.js, Version: 0.28.6 (2026-11-08)
// Panel checks: readings a device gives about itself, on its page (rules
// STACK-15, DEV-17). A Z-Wave controller's Status with when it began, in
// Advanced, and in Simple only when it is not Ready; a Tasmota device's
// last restart and its reason, the earlier ones folded under it, in
// Advanced only.
// Run with: LC_ALL=en_US.UTF-8 node check_status_readings.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const DEVICE = payloads._ids ? payloads._ids.alpha : "alpha";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

const ACTIONS = {
  area_id: null, name_by_user: null, integration_name: "Motion Hall", labels: [],
  mutes: {
    everything: { on: false, source: null, here: false },
    freeze: { on: false, source: null, here: false },
    battery: { on: false, source: null, here: false },
    signal: { on: false, source: null, here: false },
  },
};
function page(mode, extra) {
  const p = JSON.parse(JSON.stringify(payloads.device));
  p.identity.device_id = DEVICE;
  p.identity.name = "Z-Stick Gen5+";
  if (mode !== "viewer") p.identity.actions = JSON.parse(JSON.stringify(ACTIONS));
  Object.assign(p.identity, extra);
  return p;
}

async function open(mode, extra) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/device/${DEVICE}`, virtualConsole,
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
  const sent = [];
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode === "simple" ? "simple" : "advanced" };
      if (kind === "device") return page(mode, extra);
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot, sent };
}

const row = (root, label) => {
  const cell = [...root.querySelectorAll("th, td")].find((c) => c.textContent === label);
  return cell ? cell.nextElementSibling : null;
};

const JAMMED = { controller_status: { value: "jammed", since: "2026-11-08T09:00:00+00:00" } };
const READY = { controller_status: { value: "ready", since: "2026-11-08T09:00:00+00:00" } };
const RESTARTS = { restarts: [
  { value: "Exception", at: "2026-11-08T09:00:01+00:00" },
  { value: "Power On", at: "2026-11-07T08:02:00+00:00" },
] };

(async () => {
  console.log("\nAdvanced");
  let { root } = await open("advanced", { ...READY, ...RESTARTS });
  let cell = row(root, "Controller status");
  check("the controller's status, with when it began", cell && /^Ready, since Nov 8/.test(cell.textContent), cell ? cell.textContent : null);
  ({ root } = await open("advanced", { controller_status: { ...READY.controller_status, first: true } }));
  cell = row(root, "Controller status");
  check("its first reading says when it was first read, not since", cell && /^Ready, first read Nov 8/.test(cell.textContent),
    cell ? cell.textContent : null);
  ({ root } = await open("advanced", { ...READY, ...RESTARTS }));
  cell = row(root, "Last restart");
  check("the last restart and its reason", cell && /^Exception, Nov 8/.test(cell.textContent), cell ? cell.textContent : null);
  const folded = cell && cell.querySelector("details");
  check("the earlier restart folded under it", folded && /1 earlier/.test(folded.querySelector("summary").textContent)
    && /Power On, Nov 7/.test(folded.textContent), folded ? folded.textContent : null);
  ({ root } = await open("advanced", { restarts: [RESTARTS.restarts[1]] }));
  cell = row(root, "Last restart");
  check("one restart: no fold", cell && !cell.querySelector("details") && /^Power On, Nov 7/.test(cell.textContent), cell ? cell.innerHTML : null);
  check("no controller row on a device without one", !row(root, "Controller status"));

  console.log("\nSimple");
  ({ root } = await open("simple", { ...READY, ...RESTARTS }));
  check("Ready is not shown", !row(root, "Controller status"));
  check("restarts are not shown", !row(root, "Last restart"));
  ({ root } = await open("simple", { ...JAMMED }));
  cell = row(root, "Controller status");
  check("a jammed controller is shown", cell && /^Jammed, since/.test(cell.textContent), cell ? cell.textContent : null);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
