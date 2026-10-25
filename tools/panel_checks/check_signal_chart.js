// File: tools/panel_checks/check_signal_chart.js, Version: 0.27.4 (2026-10-25)
// Panel checks: the Signal chart on a device's page (0.27.3). Its card
// names RSSI as RSSI, its legend explains the rings drawn on days with
// railed readings, and "recording began" sits inside the chart's width.
// Since 0.27.4 it sits above the plot area, clear of every data line
// (it lay across the lines on James's FJ40 sensor).
// Run with: LC_ALL=en_US.UTF-8 node check_signal_chart.js [path/to/panel.js]
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
const DAYS = 20;
const withSignal = (scale, railedOn, reports = 2 * DAYS) => ({
  device: (page) => {
    // Its reports go back further than its signal: the signal chart
    // starts where recording began.
    page.rhythm.daily = Array.from({ length: reports }, () => 3600);
    page.signal = Object.assign({}, page.signal, {
      scale, now: -60, readings_a_day: 30,
      p50: Array.from({ length: DAYS }, () => -60),
      p5: Array.from({ length: DAYS }, () => -70),
      railed_days: Array.from({ length: DAYS }, (_, i) => (railedOn.includes(i) ? 3 : 0)),
      judged: Array.from({ length: DAYS }, () => ({ normal: -62, line: -80, bad: false, low: -70 })),
    });
    return page;
  },
});

(async () => {
  console.log("The Signal chart on a device's page (0.27.3)");
  let { root } = await open(`${PREFIX}/device/${DEVICE}`, withSignal("rssi", [4, 9, 15]));
  const signalCard = (r) => [...r.querySelectorAll(".chart")].find((c) => c.querySelector(".statusline strong") && c.querySelector(".statusline strong").textContent === "Signal");
  let card = signalCard(root);
  check("An RSSI device's card says RSSI", !!card && card.querySelector(".statusline .small").textContent === "RSSI", card && card.querySelector(".statusline .small").textContent);
  const rings = card ? card.querySelectorAll('circle[fill="none"]').length : 0;
  const legend = card && card.querySelector(".legend");
  check("Three railed days draw three rings", rings === 3, rings);
  check("The legend explains the rings", !!legend && /railed readings that day/.test(legend.textContent), legend && legend.textContent);
  const began = card && [...card.querySelectorAll("text")].find((t) => /recording began/.test(t.textContent));
  check("Recording began is drawn", !!began, card && [...card.querySelectorAll("text")].map((t) => t.textContent));
  // Inside the chart: from the axis at 44 to the right edge at 1090,
  // about 6.5 px a character at the axis size.
  const inside = (t) => {
    const x = Number(t.getAttribute("x"));
    const width = t.textContent.length * 6.5;
    const from = t.getAttribute("text-anchor") === "end" ? x - width : x;
    return from > 44 && from + width < 1090;
  };
  check("It sits inside the chart", !!began && inside(began), began && { x: began.getAttribute("x"), anchor: began.getAttribute("text-anchor") });
  // The plot area runs from y 20 down to the axis at 190. The label's
  // baseline sits above it, with room for its height inside the
  // drawing, and every line, band and ring the chart draws lies at or
  // below 20, so nothing it shows can pass under the words.
  const svgOf = began && began.closest("svg");
  const ys = (node) => {
    const out = [];
    for (const attr of ["points", "d"]) {
      const v = node.getAttribute(attr);
      if (v) for (const m of v.matchAll(/-?\d+(?:\.\d+)?,(-?\d+(?:\.\d+)?)/g)) out.push(Number(m[1]));
    }
    if (node.tagName === "circle") out.push(Number(node.getAttribute("cy")) - Number(node.getAttribute("r")));
    if (node.tagName === "rect" && node.getAttribute("fill") !== "transparent") out.push(Number(node.getAttribute("y")));
    return out;
  };
  const marks = svgOf ? [...svgOf.querySelectorAll("path, polyline, polygon, circle, rect")].flatMap(ys).filter((v) => !Number.isNaN(v)) : [];
  const baseline = began ? Number(began.getAttribute("y")) : NaN;
  check("It sits above the plot area, inside the drawing", baseline > 10 && baseline <= 16, began && began.getAttribute("y"));
  check("Every data line, ring and band lies below it", marks.length > 0 && Math.min(...marks) >= 20, { lowest: Math.min(...marks), count: marks.length });
  // Master Park Shades on 24 October 2026: its signal began a few days
  // after its reports, so the first day sits by the axis.
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, withSignal("lqi", [], 22)));
  card = signalCard(root);
  const nearAxis = card && [...card.querySelectorAll("text")].find((t) => /recording began/.test(t.textContent));
  check("Near the axis it is drawn to the right of the first day, clear of the axis", !!nearAxis && inside(nearAxis)
    && nearAxis.getAttribute("text-anchor") === "start", nearAxis && { x: nearAxis.getAttribute("x"), anchor: nearAxis.getAttribute("text-anchor") });
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, withSignal("lqi", [])));
  card = signalCard(root);
  check("A link quality device's card still says link quality", !!card && card.querySelector(".statusline .small").textContent === "link quality");
  check("No rings, no legend entry for them", !!card && !/railed readings/.test(card.querySelector(".legend").textContent));
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
