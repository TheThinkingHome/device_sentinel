// File: tools/panel_checks/check_signal_trends.js, Version: 0.27.4 (2026-10-25)
// Panel checks: the Signal Trends tab. Each row adds up: THIS WEEK
// less BEFORE THIS WEEK is CHANGE, and no sign reads "+0" or "-0.0"
// (0.27.3). Since 0.27.4 the columns and the caption are in James's
// words (rule SIG-12).
// Run with: LC_ALL=en_US.UTF-8 node check_signal_trends.js [path/to/panel.js]
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

const row = (over) => ({
  device_id: "x", name: "Device", scale: "lqi", now: 100, normal: 100, line: 60,
  week: 100, usual: 100, change: 0, spreads: 0, bad_days: 0, readings_a_day: 24, days: 60, ...over,
});
// The rig's Temperature Living Room on 24 October 2026: the last seven
// days' middle 174, the days before them 218, its normal 138.
const ROWS = [
  row({ device_id: "t", name: "Temperature Living Room", now: 188, normal: 138, line: 98,
    week: 174.4, usual: 218.4, change: -44.0, spreads: -2.5, bad_days: 1 }),
  row({ device_id: "s", name: "Steady Plug", week: 120.6, usual: 120.9, change: -0.3, spreads: -0.04 }),
  row({ device_id: "u", name: "Up Plug", week: 120.4, usual: 120.1, change: 0.3, spreads: 0.04 }),
];
const TRENDS = (reply) => ({ ...reply, devices: ROWS, scales: { lqi: 3 }, counts: { unsteady: 1, steady: 2 } });

(async () => {
  console.log("Signal Trends: each row adds up (0.27.3)");
  const { root } = await open(`${PREFIX}/signal-trends`, { signal_trends: TRENDS });
  const tables = [...root.querySelectorAll(".pane table")].filter((t) => /CHANGE/.test(t.textContent));
  const heads = tables.length ? [...tables[0].querySelectorAll("thead th")].map((th) => th.textContent.replace(/[▲▼↑↓\s]+$/u, "").trim()) : [];
  check("The first column of figures is THIS WEEK, not NOW or LAST 7 DAYS", heads.some((h) => h === "THIS WEEK")
    && !heads.some((h) => h.startsWith("NOW") || h.startsWith("LAST 7 DAYS")), heads);
  const usualAt = heads.findIndex((h) => h === "BEFORE THIS WEEK");
  const changeAt = heads.findIndex((h) => h === "CHANGE");
  check("BEFORE THIS WEEK stands just before CHANGE, and no column reads USUAL", usualAt >= 0 && changeAt === usualAt + 1
    && !heads.includes("USUAL"), heads);
  const caption = [...root.querySelectorAll(".pane p.small")].map((p) => p.textContent)
    .find((t) => t.startsWith("Each device's"));
  check("The caption is James's words exactly", caption === "Each device's typical signal this week, beside its history. "
    + "A large drop means its radio link has weakened this week.", caption);
  const bar = root.querySelector(".pane svg rect[role=link] title");
  check("A bar's words name the same two figures", !!bar && /this week against 218 before this week/.test(bar.textContent)
    && !/usual|last 7 days/.test(bar.textContent), bar && bar.textContent);
  const cells = (name) => {
    for (const t of tables) {
      const tr = [...t.querySelectorAll("tbody tr")].find((r) => r.textContent.startsWith(name));
      if (tr) return [...tr.querySelectorAll("td")].map((td) => td.textContent);
    }
    return null;
  };
  const weekAt = heads.findIndex((h) => h === "THIS WEEK");
  const temp = cells("Temperature Living Room");
  check("Temperature Living Room reads 174, usual 218, change -44", !!temp && temp[weekAt] === "174" && temp[usualAt] === "218" && temp[changeAt] === "-44", temp);
  const steady = cells("Steady Plug");
  const up = cells("Up Plug");
  const spreadsAt = heads.findIndex((h) => h.startsWith("IN ITS OWN SPREADS"));
  check("A change that rounds to nothing reads 0, not -0 or +0", !!steady && !!up && steady[changeAt] === "0" && up[changeAt] === "0", [steady && steady[changeAt], up && up[changeAt]]);
  check("Spreads that round to nothing read 0.0, not -0.0 or +0.0", !!steady && !!up && steady[spreadsAt] === "0.0" && up[spreadsAt] === "0.0", [steady && steady[spreadsAt], up && up[spreadsAt]]);
  const note = root.querySelector(".pane .statusline");
  check("The chart's note says what the number above means", !!note && /0 two spreads or more above/.test(note.textContent) && !/the same above/.test(note.textContent), note && note.textContent);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
