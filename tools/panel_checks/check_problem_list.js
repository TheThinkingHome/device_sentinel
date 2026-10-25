// File: tools/panel_checks/check_problem_list.js, Version: 0.27.4 (2026-10-25)
// Panel checks: the Problem List tab's SINCE column. A device that has
// never reported has no moment it stopped: its time is when it was
// discovered, and the tab says so, as the Daily Brief does ("discovered
// 3:47 PM", rule LIST-10, James, 25 October 2026). Every other problem
// keeps its bare time.
// Run with: LC_ALL=en_US.UTF-8 node check_problem_list.js [path/to/panel.js]
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
  console.log("The Problem List tab's SINCE column (rule LIST-10)");
  const at = (minutes) => new Date(Date.now() - minutes * 60e3).toISOString();
  const rows = [
    { uid: "u1", device_id: "n1", name: "Never Sensor", integration: "test", integration_name: "Test",
      problem: "never reported", since: at(90), acknowledged: false, mutes: [], power: null, never_reported: true },
    { uid: "u2", device_id: "f1", name: "Frozen Sensor", integration: "test", integration_name: "Test",
      problem: "frozen", since: at(30), acknowledged: false, mutes: [], power: null, never_reported: false },
  ];
  const { root } = await open(`${PREFIX}/problem-list`, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }) });
  const pane = root.querySelector(".pane");
  const heads = [...pane.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  const sinceAt = heads.indexOf("SINCE");
  const since = (name) => {
    const tr = [...pane.querySelectorAll("tbody tr")].find((r) => r.textContent.includes(name));
    return tr ? tr.cells[sinceAt].textContent : null;
  };
  check("A never-reported device reads discovered, with the time", /^discovered \S.*\d{1,2}:\d\d/.test(since("Never Sensor") || ""), since("Never Sensor"));
  check("Any other problem keeps its bare time", !!since("Frozen Sensor") && !since("Frozen Sensor").startsWith("discovered")
    && /\d{1,2}:\d\d/.test(since("Frozen Sensor")), since("Frozen Sensor"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
