// File: tools/panel_checks/check_no_stray_words.js, Version: 0.27.13 (2026-10-28)
// Panel checks: no tab, in Simple or Advanced, draws a part left out as
// the word "null", "undefined" or "NaN" (rule DASH-04).
// Run with: LC_ALL=en_US.UTF-8 node check_no_stray_words.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const PREFIX = "/device-sentinel";
const TABS = ["daily-brief", "problem-list", "battery-trends", "signal-trends", "classification", "integrations", "devices", "recommendations"];

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 80));

async function open(payloads, path, mode) {
  const virtualConsole = new VirtualConsole();
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/${path}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  window.document.body.append(panel);
  panel.route = { prefix: PREFIX, path: `/${path}` };
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind in payloads) return JSON.parse(JSON.stringify(payloads[kind]));
      return {};
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle(); await settle();
  return panel.shadowRoot;
}

(async () => {
  for (const file of ["payloads.json", "payloads_fleet.json"]) {
    const payloads = JSON.parse(fs.readFileSync(`${__dirname}/${file}`, "utf8"));
    // The Recommendations tab with nothing active and no report link:
    // the case that drew "null" on a house.
    const quiet = JSON.parse(JSON.stringify(payloads));
    quiet.recommendations = { ...quiet.recommendations, lines: [], report: null };
    for (const [label, set] of [[file, payloads], [`${file}, nothing active`, quiet]]) {
      console.log(label);
      for (const mode of ["simple", "advanced"]) {
        for (const tab of TABS) {
          const root = await open(set, tab, mode);
          const text = root.querySelector(".pane").textContent;
          // Text from one element runs into the next, so the letters on
          // each side mark the word, not spaces.
          const stray = text.match(/.{0,30}(?<![a-z])(null|undefined|NaN)(?![a-z]).{0,30}/);
          check(`${mode} ${tab}: no stray word`, !stray, stray && stray[0]);
        }
      }
    }
  }
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
