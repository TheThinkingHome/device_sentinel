// Panel checks: the rhythm chart shows both freeze rules, its marks follow the
// pointer, the device page names the rule in use, and every chart legend
// leads with a swatch (0.24.0).
// Run with: LC_ALL=en_US.UTF-8 node check_rhythm_rules.js [path/to/panel.js]
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
const gaps = Array.from({ length: DAYS }, (_, i) => (i === 12 ? 6 : i === 15 ? 5 : 1 + (i % 3) * 0.05) * H);
const withRules = {
  device: (page) => {
    page.status.rule = "40-Day Log-Normal Percentile";
    page.status.window = 2.6 * H;
    page.rhythm.daily = gaps;
    page.rhythm.windows = gaps.map((_, i) => (i < 7 ? null : (i >= 16 ? 2.6 : 2.3) * H));
    page.rhythm.trimmed = gaps.map((_, i) => (i < 7 ? null : (i >= 16 ? 6.9 : 2.3) * H));
    page.rhythm.lognormal = gaps.map((_, i) => (i < 7 ? null : 2.6 * H));
    page.rhythm.rule = gaps.map((_, i) => (i < 7 ? null : i >= 16 ? "40-Day Log-Normal Percentile" : "14-Day Trimmed Maximum"));
    page.rhythm.deciding = gaps.map((_, i) => (i < 7 ? null : i >= 16 ? 15 : 3));
    page.rhythm.aside = gaps.map((_, i) => (i < 7 ? null : i >= 16 ? [12] : [5]));
    page.rhythm.scale = 7 * H;
    // A battery and a signal history too, so all three legends draw.
    page.battery = {
      daily: Array(DAYS).fill(0).map((_, i) => 76 + ((i % 3) - 1) * 0.5), now: 76, threshold: 20, readable: true,
      weeks: [76.1, 75.9, 76.0], reading: "", fit: null, sentence: "",
      falling: false, left: null, left_soon: false,
    };
    page.signal = Object.assign({}, page.signal, {
      p50: Array(DAYS).fill(0).map((_, i) => 110 + (i % 4)),
      p5: Array(DAYS).fill(0).map((_, i) => 96 + (i % 4)),
      railed_days: Array(DAYS).fill(0),
      judged: Array(DAYS).fill(0).map(() => ({ normal: 108, line: 90, bad: false, low: 96 })),
    });
    return page;
  },
};

(async () => {
  console.log("\nThe device page with both freeze rules");
  const { window, root } = await open(`${PREFIX}/device/${DEVICE}`, withRules);
  const pane = root.querySelector(".pane");
  check("Identity names the rule in use and its wait",
    /Wait rule\s*40-Day Log-Normal Percentile, 2\.6h/.test(pane.textContent.replace(/\s+/g, " ")), pane.textContent.slice(0, 0));
  const charts = [...root.querySelectorAll(".chart")];
  const byTitle = (t) => charts.find((c) => c.querySelector(".statusline strong") && c.querySelector(".statusline strong").textContent === t);
  for (const title of ["Battery", "Signal", "Rhythm"]) {
    const card = byTitle(title);
    if (!card) { console.log(`  (no ${title} chart on this page)`); continue; }
    const first = card.querySelector(".legend > span");
    check(`${title}: the legend's first entry has its swatch`, first && first.querySelector(".swatch"), first ? first.textContent : null);
  }
  const rhythm = byTitle("Rhythm");
  const polylines = [...rhythm.querySelectorAll("polyline, path")];
  check("Rhythm: the Log-Normal Percentile's wait is drawn, dashed, in its own colour",
    polylines.some((p) => p.getAttribute("stroke") === "#2a78d6" && p.getAttribute("stroke-dasharray")));
  check("Rhythm: the Trimmed Maximum's wait is drawn, dashed, in red",
    polylines.some((p) => (p.getAttribute("stroke") || "").includes("error-color") && p.getAttribute("stroke-dasharray")));
  const line = rhythm.querySelector(".rule-line");
  check("Rhythm: the line above the chart names today's rule in use",
    line && /waiting 2\.6h on the 40-Day Log-Normal Percentile/.test(line.textContent), line ? line.textContent : null);
  const ring = rhythm.querySelector("circle[r='8']");
  check("Rhythm: today's ring sits on the day that set the trimmed wait", ring && ring.getAttribute("opacity") === "1");
  const ringXToday = ring.getAttribute("cx");
  // Point at an early day: its trimmed wait was set by day 3, day 5 set aside.
  const rects = [...rhythm.querySelectorAll("rect[fill='transparent']")];
  const target = rects[10];
  target.dispatchEvent(new window.MouseEvent("mouseenter", { bubbles: true }));

  await settle();
  check("Rhythm: the line follows the day pointed at",
    /on the 14-Day Trimmed Maximum/.test(line.textContent), line.textContent);
  check("Rhythm: the ring moves with it", ring.getAttribute("cx") !== ringXToday, [ringXToday, ring.getAttribute("cx")]);
  const cross = [...rhythm.querySelectorAll("text")].find((t) => t.textContent === "\u2715");
  check("Rhythm: the set-aside day is crossed", cross && cross.getAttribute("opacity") === "1");

  const button = [...root.querySelectorAll("button")].find((b) => b.textContent === "Use the 14-Day Trimmed Maximum");
  // No helper text beside it since 0.24.5 (James, 4 October 2026).
  check("Identity: the button sits under the table, with no helper line",
    button && button.parentElement.textContent === "Use the 14-Day Trimmed Maximum", button ? button.parentElement.textContent : null);

  console.log("\nPressing the button");
  const sent = [];
  const pressed = await open(`${PREFIX}/device/${DEVICE}`, withRules);
  const callWS = pressed.hass.callWS;
  pressed.hass.callWS = async (message) => {
    if (message.type === "device_sentinel/use_trimmed_maximum") { sent.push(message); return {}; }
    return callWS(message);
  };
  [...pressed.root.querySelectorAll("button")].find((b) => b.textContent === "Use the 14-Day Trimmed Maximum").click();
  await settle();
  check("it sends the command for this device", sent.length === 1 && sent[0].device_id === payloads.device.identity.device_id, sent);

  console.log("\nA device with no wait rule");
  const young = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => { page.status.rule = null; return page; } });
  check("has no button", ![...young.root.querySelectorAll("button")].some((b) => b.textContent === "Use the 14-Day Trimmed Maximum"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
