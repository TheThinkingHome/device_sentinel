// File: tools/panel_checks/check_status_bar.js, Version: 0.27.17 (2026-11-01)
// Panel checks: the status bar at the top of a device's page. Green
// within the device's rhythm, yellow past it until it is called
// frozen, red when frozen. An unavailable device reads gray, says
// since when, and its bar stops where it stood when the device went.
// And the Its Rhythm section: a line under the wait rule, the button at
// its own width, chart titles at 16px and room between the charts
// (rule DASH-08).
// Run with: LC_ALL=en_US.UTF-8 node check_status_bar.js [path/to/panel.js]
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
  const hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, hass };
}

const DEVICE = payloads._ids.bravo;
const M = 60;
const minutesAgo = (n) => new Date(Date.now() - n * M * 1000).toISOString();
const reporting = (minutes, extra = {}) => ({ device: (page) => {
  Object.assign(page.status, { category: "reporting", last_activity: minutesAgo(minutes), rhythm: 5 * M, window: 26 * M, rule: "14-Day Trimmed Maximum" }, extra);
  page.rhythm.gaps = Array.from({ length: 14 }, () => 300);
  page.rhythm.set_aside = [];
  page.identity.muted = "";
  return page;
} });
const bar = (root) => root.querySelector(".devstatus .bar > div");
const line = (root) => root.querySelector(".devstatus .statusline .muted").textContent;
const word = (root) => root.querySelector(".devstatus .statusline > div").textContent;
const width = (root) => parseFloat(bar(root).style.width);

(async () => {
  console.log("The bar's colours");
  let { root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(3));
  check("Within its rhythm: green", /success-color/.test(bar(root).style.background), bar(root).style.background);
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(14)));
  check("Past its rhythm, not yet frozen: yellow", /warning-color/.test(bar(root).style.background), bar(root).style.background);
  check("and still reads Reporting, with the freeze line", word(root).includes("Reporting") && /Called frozen after 26m of silence\./.test(line(root)), [word(root), line(root)]);
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(30, { category: "frozen" })));
  check("Frozen: red, full", /error-color/.test(bar(root).style.background) && width(root) === 100, [bar(root).style.background, width(root)]);
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    Object.assign(page.status, { category: "reporting", last_activity: minutesAgo(14), rhythm: 5 * M, window: 26 * M });
    page.identity.muted = "Global (device)";
    return page;
  } }));
  check("A muted device keeps its gray, not yellow", !/warning-color/.test(bar(root).style.background), bar(root).style.background);

  console.log("An unavailable device");
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(52, { category: "unavailable", since: minutesAgo(38) })));
  check("Gray, and its dot too", /#8a8a8a|138, 138, 138/.test(bar(root).style.background)
    && /#8a8a8a|138, 138, 138/.test(root.querySelector(".devstatus .dot").style.background), bar(root).style.background);
  // Before 00:38 the moment it went was yesterday and carries its date.
  check("Says since when, not the freeze window", /^Unavailable since (?:[A-Z][a-z]{2} \d{1,2}, )?\d{1,2}:\d\d.*, 38m ago\.$/.test(line(root)) && !/Called frozen/.test(line(root)), line(root));
  check("The bar stops where it stood when it went (14 of 26 minutes)", Math.abs(width(root) - (14 / 26) * 100) < 1, width(root));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(52, { category: "unknown", since: minutesAgo(40) })));
  check("Unknown says since when too", /^Unknown since /.test(line(root)), line(root));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(52, { category: "unavailable", since: null })));
  check("With no time it went, the freeze line stays and nothing breaks", /Called frozen after/.test(line(root)), line(root));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(4400, { category: "unavailable", since: minutesAgo(4320) })));
  check("Gone on an earlier day: the line gives the date", /^Unavailable since [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d\d.*, 3 days ago\.$/.test(line(root)), line(root));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, reporting(52, { category: "unavailable", since: "not a time" })));
  check("A time it went that cannot be read: no NaN, no Invalid Date", !/NaN|Invalid/.test(line(root) + bar(root).style.width) && /Called frozen after/.test(line(root)), [line(root), bar(root).style.width]);

  console.log("The Its Rhythm section");
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    Object.assign(page.status, { category: "frozen", last_activity: minutesAgo(200), rhythm: 72 * M, window: 2 * 3600, rule: "40-Day Log-Normal Percentile" });
    page.rhythm.gaps = Array.from({ length: 14 }, () => 3000);
    page.rhythm.set_aside = [];
    page.rhythm.rules = { trimmed: 4320, trimmed_days: 14, lognormal: 4500, lognormal_days: 40,
      lognormal_gaps: Array.from({ length: 40 }, () => 3000), lognormal_set_aside: [], in_use: "lognormal", counting_again: null };
    return page;
  } }));
  const css = [...root.querySelectorAll("style")].map((s) => s.textContent).join("");
  check("Chart titles at 16px", /\.ruletitle \{[^}]*font-size: 16px/.test(css));
  check("Room between the two charts", /\.rulebox \{ margin-bottom: 28px; \}/.test(css));
  const span = [...root.querySelectorAll(".actcol > span")].find((s) => s.textContent.startsWith("Wait rule:"));
  const wait = span && span.parentNode;
  check("A line under the wait rule", !!wait && /border-bottom/.test(wait.getAttribute("style") || ""), wait && wait.getAttribute("style"));
  const button = wait && [...wait.querySelectorAll("button")].find((b) => b.textContent === "Use the 14-Day Trimmed Maximum");
  check("The button at its own width", !!button && /align-self:\s*flex-start/.test(button.getAttribute("style") || ""), button && button.getAttribute("style"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
