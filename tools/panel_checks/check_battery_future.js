// File: tools/panel_checks/check_battery_future.js, Version: 0.27.0 (2026-10-22)
// Panel checks: the device page's Future view (rulings #703 to #705, #713).
// Written for 0.26.7 (2026-10-19); the chart James reviewed on 19 October in 0.26.8.
// Run with: LC_ALL=en_US.UTF-8 node check_battery_future.js [path/to/panel.js]
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

const text = (root) => root.querySelector(".pane").textContent;
const DEVICE = payloads._ids ? payloads._ids.alpha : null;

// Door 2nd Bedroom on the reference rig, 19 October 2026.
const DOOR = [24.5, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 24.5, 24.0, 24.5, 24.5, 24.0, 24.5, 24.5, 24.5, 24.0, 24.0, 24.0, 24.5, 24.0, 23.5, 23.0, 23.0, 23.0, 22.5, 23.0, 23.5, 23.0, 23.0, 23.0, 22.0, 23.0, 22.0, 23.5, 22.5, 23.5, 23.0, 22.0, 22.5, 23.0, 21.0, 21.5, 22.5, 21.5, 21.0, 21.0, 20.5, 20.5, 20.0, 19.5, 19.0, 19.0, 17.0, 19.5, 19.0, 17.0, 17.5, 15.0, 15.0, 18.0, 18.0, 17.5, 16.5];
const DOOR_PROJECTION = { curved: true, level: 16.5, near: 26.9, far: 35.2, centre: 30.2,
  near_path: [-0.44848, -0.0061018], far_path: [-0.34119, -0.003637] };
const withBattery = (battery) => ({ device: (page) => { page.battery = battery; return page; } });
const door = withBattery({
  daily: DOOR, now: 16.5, threshold: 15, readable: true,
  weeks: [23.0, 22.4, 21.2, 19.4, 16.9], reading: "accelerating",
  fit: null, sentence: "Accelerating.", falling: true,
  left: "about 4 to 5 weeks", left_soon: true, projection: DOOR_PROJECTION, days_setting: 30,
});
const STEADY = Array(60).fill(0).map((_, i) => 80 - 0.3 * i);
const slow = withBattery({
  daily: STEADY, now: 62.3, threshold: 15, readable: true, weeks: [64, 62.5, 61, 59.5, 58], reading: "falling",
  fit: null, sentence: "Falling.", falling: true, left: "about 7 months", left_soon: false,
  projection: { curved: false, level: 62.3, near: 206.5, far: 208.1, centre: 207.1,
    near_path: [-0.30172, 0], far_path: [-0.29937, 0] }, days_setting: 30,
});
const flat = withBattery({
  daily: Array(42).fill(76), now: 76, threshold: 15, readable: true, weeks: [76, 76, 76, 76, 76],
  reading: "", fit: null, sentence: "", falling: false, left: null, left_soon: false, projection: null, days_setting: 30,
});
const button = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent === label);
const chart = (root) => root.querySelector(".futurechart");
const band = (root) => root.querySelectorAll(".futurechart polygon").length;
const lowLine = (root) => [...root.querySelectorAll(".futurechart line")].some((l) => l.getAttribute("stroke-dasharray") === "4 4");

(async () => {
  console.log("A cell speeding up near the end");
  const a = await open(`${PREFIX}/device/${DEVICE}`, door);
  check("a Future button beside the ranges", !!button(a.root, "Future"));
  check("the ranges are unchanged until it is pressed", !chart(a.root));
  button(a.root, "Future").click();
  await settle();
  check("the chart with its future", !!chart(a.root));
  check("a shaded range between two lines", band(a.root) === 1
    && a.root.querySelectorAll(".futurechart polyline").length === 3, a.root.querySelectorAll(".futurechart polyline").length);
  check("every kept day as a light dot", a.root.querySelectorAll(".futurechart circle").length === DOOR.length);
  check("the low battery line, since the range reaches it", lowLine(a.root));
  check("the range in words", text(a.root).includes("Expected empty in about 4 to 5 weeks."));
  // James's review of 19 October (#713).
  const today = a.root.querySelector(".futurechart line[stroke='var(--secondary-text-color)']");
  const history = [...a.root.querySelectorAll(".futurechart polyline")].find((l) => !l.classList.contains("futureline"));
  const lastPoint = history.getAttribute("points").split(" ").pop().split(",").map(Number);
  const yOf = (v) => 190 - (v / 100) * 170;
  check("the history runs to today's reading", Math.abs(lastPoint[0] - Number(today.getAttribute("x1"))) < 0.2
    && Math.abs(lastPoint[1] - yOf(16.5)) < 0.2, lastPoint);
  const lines = [...a.root.querySelectorAll(".futurechart polyline.futureline")];
  check("the future is red, nothing orange", lines.length === 2
    && lines.every((l) => l.getAttribute("stroke") === "var(--error-color, #db4437)")
    && a.root.querySelector(".futurechart polygon").getAttribute("fill") === "var(--error-color, #db4437)"
    && !chart(a.root).innerHTML.includes("warning-color"));
  check("both lines bold", lines.every((l) => Number(l.getAttribute("stroke-width")) >= 2.4));
  const floor = (l) => l.getAttribute("points").split(" ").filter((pt) => Math.abs(Number(pt.split(",")[1]) - 190) < 0.05).length;
  check("each line stops where it empties, none runs along the floor", lines.every((l) => floor(l) === 1),
    lines.map(floor));
  const ends = lines.map((l) => Number(l.getAttribute("points").split(" ").pop().split(",")[0]));
  check("the two lines end apart", Math.abs(ends[0] - ends[1]) > 20, ends);
  const dates = [...a.root.querySelectorAll(".futurechart text.zerodate")].map((t) => t.textContent);
  const when = (days) => { const d = new Date(); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + Math.round(days));
    return d.toLocaleDateString([], { month: "short", day: "numeric" }); };
  check("the day each line empties, under the axis", dates.length === 2 && dates[0] === when(26.9) && dates[1] === when(35.2),
    [dates, when(26.9), when(35.2)]);
  check("a tick on the axis at each", a.root.querySelectorAll(".futurechart line.zerotick").length === 2);
  check("the Future button reads pressed", button(a.root, "Future").getAttribute("aria-pressed") === "true");
  button(a.root, "30 Days").click();
  await settle();
  check("another range brings back the history chart", !chart(a.root));

  console.log("The fall drawn to the low threshold (#730)");
  const LOW_DAILY = DOOR.map((v) => v + 20);
  const toLow = withBattery({
    daily: LOW_DAILY, now: 36.5, threshold: 15, readable: true,
    weeks: [43.0, 42.4, 41.2, 39.4, 36.9], reading: "accelerating", fit: null,
    sentence: "Falling faster each week, about 3.1 points a week today.", falling: true,
    left: "about 4 to 5 weeks", left_soon: true, target: 15, days_setting: 45,
    projection: { ...DOOR_PROJECTION, level: 36.5, target: 15, near: 33.1, far: 43.2, centre: 37 },
  });
  const t = await open(`${PREFIX}/device/${DEVICE}`, toLow);
  check("the page says where the time left ends, and why", text(t.root).includes(
    "Falling faster each week, about 3.1 points a week today. It reaches your 15% in about 4 to 5 weeks. Many devices stop working before their battery reaches 0%."),
    text(t.root).slice(-900));
  button(t.root, "Future").click();
  await settle();
  const lowLines = [...t.root.querySelectorAll(".futurechart polyline.futureline")];
  const atLow = (l) => l.getAttribute("points").split(" ").filter((pt) => Math.abs(Number(pt.split(",")[1]) - yOf(15)) < 0.05).length;
  check("each line stops at the threshold, not at empty", lowLines.length === 2 && lowLines.every((l) => atLow(l) === 1)
    && lowLines.every((l) => floor(l) === 0), lowLines.map(atLow));
  check("the words say the threshold", text(t.root).includes("Expected to reach 15% in about 4 to 5 weeks."));
  check("Advanced says the 0% line once, above the table", text(t.root).split("Many devices stop working").length === 2);

  console.log("Earlier Forecasts (#732)");
  const logged = withBattery({ ...JSON.parse(JSON.stringify(toLow.device({}).battery)), forecasts: [
    { day: "2026-11-20", level: 18.5, accelerating: true, target: 15, left: "about 1 to 2 weeks", outcome: null, arrived: null },
    { day: "2026-10-22", level: 31, accelerating: true, target: 15, left: "about 3 to 5 weeks", outcome: "inside", arrived: "2026-11-19" },
    { day: "2026-09-01", level: 44, accelerating: false, target: 15, left: "about 2 to 3 months", outcome: "later", arrived: null },
  ] });
  const lg = await open(`${PREFIX}/device/${DEVICE}`, logged);
  const items = [...lg.root.querySelectorAll("details.forecasts li")].map((li) => li.textContent);
  check("each forecast with what happened, newest first", items.length === 3
    && items[0].endsWith("Not there yet.")
    && items[1].includes("at 31%: reaches 15% in about 3 to 5 weeks. Reached 15% on ") && items[1].endsWith(", inside the range.")
    && items[2].endsWith("Still above 15% when the range ended."), items);
  check("titled with its count", (lg.root.querySelector("details.forecasts summary") || {}).textContent === "Earlier Forecasts (3)");
  const none = await open(`${PREFIX}/device/${DEVICE}`, toLow);
  check("no list when nothing was forecast", !none.root.querySelector("details.forecasts"));

  console.log("A far end that does not empty in view");
  const wide = withBattery({ ...JSON.parse(JSON.stringify(door.device({}).battery)),
    projection: { ...DOOR_PROJECTION, far: 200, far_path: [-0.08, 0] } });
  const w = await open(`${PREFIX}/device/${DEVICE}`, wide);
  button(w.root, "Future").click();
  await settle();
  const pts = w.root.querySelector(".futurechart polygon").getAttribute("points").split(" ").map((p) => p.split(",").map(Number));
  const farLines = [...w.root.querySelectorAll(".futurechart polyline.futureline")];
  const farEnd = farLines[1].getAttribute("points").split(" ").pop().split(",").map(Number);
  check("the band closes along empty under the far line's last point", pts.some(([px, py]) => Math.abs(px - farEnd[0]) < 0.2 && Math.abs(py - 190) < 0.2),
    farEnd);
  check("only the near end's day is written", w.root.querySelectorAll(".futurechart text.zerodate").length === 1);

  console.log("A slow steady fall, far past the limit");
  const b = await open(`${PREFIX}/device/${DEVICE}`, slow);
  button(b.root, "Future").click();
  await settle();
  check("no range drawn past the limit", band(b.root) === 0);
  check("it says empty after the limit", text(b.root).includes("Empty after 30 days."), text(b.root).slice(0, 0));
  check("no low battery line, nothing reaches it", !lowLine(b.root));

  console.log("A cell that is not falling");
  const c = await open(`${PREFIX}/device/${DEVICE}`, flat);
  check("no Future button", !button(c.root, "Future"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
