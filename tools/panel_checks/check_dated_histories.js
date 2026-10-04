// Dated daily histories (0.24.4, issue #18): a skipped day breaks a line.
// pointer, the device page names the rule in use, and every chart legend
// leads with a swatch (0.24.0).
// Dated daily histories (0.24.4, issue #18): a skipped day breaks a line.
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
const DEVICE = payloads._ids ? payloads._ids.alpha : null;
const H = 3600;
const DAYS = 20;
// Days 8 to 10 measured nothing: the histories are laid out one slot a
// day, so those slots are empty.
const empty = (i) => i >= 8 && i <= 10;
const withGaps = {
  device: (page) => {
    page.rhythm.daily = Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : (1 + (i % 3) * 0.05) * H));
    page.rhythm.windows = Array.from({ length: DAYS }, (_, i) => (i < 4 || empty(i) ? null : 2.3 * H));
    page.rhythm.trimmed = page.rhythm.windows.slice();
    page.rhythm.lognormal = page.rhythm.windows.slice();
    page.rhythm.rule = page.rhythm.windows.map((w) => (w ? "14-Day Trimmed Maximum" : null));
    page.rhythm.deciding = page.rhythm.windows.map(() => null);
    page.rhythm.aside = page.rhythm.windows.map(() => []);
    page.rhythm.scale = 3 * H;
    page.battery = {
      daily: Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : 84 - i * 0.2)),
      now: 80, threshold: 20, readable: true, weeks: [83.5, 82.2], reading: "", fit: null, sentence: "",
      falling: false, left: null, left_soon: false,
    };
    page.signal = Object.assign({}, page.signal, {
      p50: Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : 110)),
      p5: Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : 96)),
      railed_days: Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : 0)),
      judged: Array.from({ length: DAYS }, (_, i) => (empty(i) ? null : { normal: 108, line: 90, bad: false, low: 96 })),
    });
    return page;
  },
};

const runs = (el) => {
  if (!el) return 0;
  if (el.tagName.toLowerCase() === "path") return ((el.getAttribute("d") || "").match(/M/g) || []).length;
  return 1;
};

(async () => {
  console.log("\nThe device page with three days that measured nothing");
  const { root } = await open(`${PREFIX}/device/${DEVICE}`, withGaps);
  const charts = [...root.querySelectorAll(".chart")];
  const byTitle = (t) => charts.find((c) => c.querySelector(".statusline strong") && c.querySelector(".statusline strong").textContent === t);
  const mainLine = (card, width) => [...card.querySelectorAll("polyline, path")].find(
    (p) => p.getAttribute("stroke") === "var(--primary-color)" && p.getAttribute("stroke-width") === width);
  const battery = byTitle("Battery");
  const bLine = battery && mainLine(battery, "2.2");
  check("Battery: the daily line breaks at the days with no reading", runs(bLine) === 2, bLine && (bLine.getAttribute("d") || bLine.getAttribute("points")));
  const signal = byTitle("Signal");
  const sLine = signal && mainLine(signal, "2.2");
  check("Signal: the median breaks at the days with no reading", runs(sLine) === 2, sLine && (sLine.getAttribute("d") || sLine.getAttribute("points")));
  check("Signal: the band is two shapes, not one across the gap", signal && signal.querySelectorAll("polygon").length === 2, signal && signal.querySelectorAll("polygon").length);
  const rhythm = byTitle("Rhythm");
  const gLine = rhythm && mainLine(rhythm, "1.4");
  check("Rhythm: the daily gap line breaks at the days with no learned gap", runs(gLine) === 2, gLine && (gLine.getAttribute("d") || gLine.getAttribute("points")));
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
