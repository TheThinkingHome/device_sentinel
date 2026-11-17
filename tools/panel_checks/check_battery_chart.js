// File: tools/panel_checks/check_battery_chart.js, Version: 0.29.5 (2026-11-17)
// Panel checks: the weekly bars in orange and the fitted line, drawn only
// at 30 and 14 days.
// The fitted line is drawn for a cell falling at an even pace only: an
// accelerating cell is judged on a curve (rules BAT-12, BAT-17).
// At 90 days and longer, the smoothed line over the daily level with the
// usual bounce shaded around it, and thinner lines throughout (BAT-17).
// Run with: LC_ALL=en_US.UTF-8 node check_battery_chart.js [path/to/panel.js]
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

const selected = (root) => {
  const tab = root.querySelector('.tab[aria-selected="true"]');
  return tab ? tab.textContent : null;
};
const clickTab = (root, name) => [...root.querySelectorAll(".tab")].find((b) => b.textContent === name).click();
const where = (window) => window.location.pathname + window.location.search;
const backLink = (root) => {
  const link = root.querySelector(".pane > p:first-child a");
  return link ? { text: link.textContent, href: link.getAttribute("href") } : null;
};

const text = (root) => root.querySelector(".pane").textContent;
const DEVICE = payloads._ids ? payloads._ids.alpha : null;

// A recorded cell: steady, then speeding up.
const S63 = [73.5, 74.0, 74.0, 74.0, 74.5, 74.5, 75.0, 74.5, 74.5, 74.5, 74.5, 74.5,
  74.0, 74.0, 74.0, 74.0, 72.5, 73.0, 72.5, 72.5, 72.5, 72.0, 70.5, 70.0,
  68.5, 67.0, 67.5, 67.5, 65.0, 65.5, 65.0, 64.5, 63.0, 61.5, 60.5, 59.5,
  58.0, 57.5, 57.5];
const accelerating = {
  device: (page) => {
    page.battery = {
      daily: S63, now: 57.5, threshold: 20, readable: true,
      weeks: [74.64, 73.71, 71.21, 66.0, 59.64],
      reading: "accelerating",
      fit: null,
      sentence: "Falling faster each week, about 5.9 points a week today.",
      falling: true, left: "about 3 months", left_soon: false,
    };
    return page;
  },
};
const steady = {
  device: (page) => {
    page.battery = {
      daily: Array(42).fill(0).map((_, i) => 76 + ((i % 3) - 1) * 0.5), now: 76, threshold: 20, readable: true,
      weeks: [76.1, 75.9, 76.0, 76.1, 75.9], reading: "", fit: null, sentence: "",
      falling: false, left: null, left_soon: false,
    };
    return page;
  },
};
const trends = {
  battery_trends: (page) => {
    page.falling = [{
      device_id: DEVICE, name: "Garage Door", level: 57.5, since: null, steps: "Smooth",
      weeks: [74.64, 73.71, 71.21, 66.0, 59.64], reading: "accelerating", pace: 5.9,
      left: "about 3 months", left_soon: false,
    }];
    return page;
  },
};

const range = async (root, label) => {
  [...root.querySelectorAll("button")].find((b) => b.textContent === label).click();
  await settle();
};
const bars = (root) => [...root.querySelectorAll("svg line")].filter((l) => l.getAttribute("stroke") === "#E8A33D");
const fitted = (root) => [...root.querySelectorAll("svg polyline")].filter((p) => p.getAttribute("stroke-dasharray") === "6 5");
const even = {
  device: (page) => {
    page.battery = {
      daily: S63, now: 57.5, threshold: 20, readable: true,
      weeks: [74.64, 73.71, 71.21, 66.0, 59.64],
      reading: "falling",
      fit: { pace: 3.2, line: [[38, 75.0], [0, 57.6]] },
      sentence: "Falling about 3.2 points a week, at a steady pace.",
      falling: true, left: "about 4 months", left_soon: false,
    };
    return page;
  },
};

// A recorded door sensor's 128 days, falling from 32% to 10%.
const DOOR = [32,32.5,31.5,32.5,32.5,31.5,31,32,32.5,31.5,21.5,30,28,23.5,22,21,12,23.5,24,23.5,24.5,24.5,25,25,24.5,23,24.5,25,24.5,25,25,25,25,25,25,25,25,24.5,24,24.5,24.5,24,24.5,24.5,24.5,24,24,24,24.5,24,23.5,23,23,23,22.5,23,23.5,23,23,23,22,23,22,23.5,22.5,23.5,23,22,22.5,23,21,21.5,22.5,21.5,21,21,20.5,20.5,20,19.5,19,19,17,19.5,19,17,17.5,15,15,18,18,17.5,16.5,17,15,14.5,15.5,14.5,18,16.5,16,11,15,14,13,14,13.5,15,16.5,14.5,14,12,12.5,13,12.5,10.5,13,11,13,12,11];
const door = {
  device: (page) => {
    page.battery = {
      daily: DOOR, now: 10, threshold: 15, readable: true,
      weeks: [16.79, 15.86, 13.79, 13.93, 11.86], reading: "falling",
      fit: { pace: 1.25, line: [[41, 18.79], [0, 11.47]] },
      sentence: "Falling about 1.3 points a week, at a steady pace.",
      falling: true, left: "about 7 to 9 weeks", left_soon: false,
    };
    return page;
  },
};
const smoothLine = (root) => root.querySelectorAll("svg polyline.smoothline").length;
const bounce = (root) => root.querySelectorAll("svg polygon.bounceband").length;
const daily = (root) => [...root.querySelectorAll("svg path")].find((p) => p.getAttribute("stroke") === "var(--primary-color)");

(async () => {
  console.log("A cell that sped up, at each range");
  const fast = await open(`${PREFIX}/device/${DEVICE}`, accelerating);
  check("at all 39 days: no weekly bars", bars(fast.root).length === 0, bars(fast.root).length);
  check("and no fitted line", fitted(fast.root).length === 0);
  await range(fast.root, "90 Days");
  check("at 90 days: no weekly bars", bars(fast.root).length === 0, bars(fast.root).length);
  check("and no fitted line", fitted(fast.root).length === 0);
  await range(fast.root, "30 Days");
  check("at 30 days: five weekly bars, the oldest cut at the edge", bars(fast.root).length === 5, bars(fast.root).length);
  check("in orange, labelled with their averages", text(fast.root).includes("59.6") && text(fast.root).includes("66.0"));
  check("no straight line beside a curve, and no knee marker", fitted(fast.root).length === 0
    && fast.root.querySelectorAll("svg circle").length === 0 && !text(fast.root).includes("knee"));
  await range(fast.root, "14 Days");
  check("at 14 days: the last two weekly bars", bars(fast.root).length === 2, bars(fast.root).length);
  check("and still no straight line", fitted(fast.root).length === 0);

  console.log("A cell falling at an even pace");
  const flat = await open(`${PREFIX}/device/${DEVICE}`, even);
  check("at all 39 days: no fitted line", fitted(flat.root).length === 0);
  await range(flat.root, "30 Days");
  check("at 30 days: the fitted line, dashed", fitted(flat.root).length === 1);
  check("said as an even pace", text(flat.root).includes("Falling at an even pace."));
  await range(flat.root, "14 Days");
  check("at 14 days: the line cut to the range", fitted(flat.root).length === 1);
  check("the five-week table stays at every range", text(fast.root).includes("28 DAYS AGO"));

  console.log("A steady cell at 30 days");
  const calm = await open(`${PREFIX}/device/${DEVICE}`, steady);
  await range(calm.root, "30 Days");
  check("weekly bars, and no fitted line", bars(calm.root).length >= 4 && fitted(calm.root).length === 0
    && ![...calm.root.querySelectorAll("svg polyline")].some((p) => p.getAttribute("stroke-dasharray") === "7 5"), bars(calm.root).length);


  console.log("A long history: the smoothed line and the usual bounce (rule BAT-17)");
  const d = await open(`${PREFIX}/device/${DEVICE}`, door);
  check("at all 128 days: the smoothed line and the band", smoothLine(d.root) === 1 && bounce(d.root) === 1);
  check("named in the legend", text(d.root).includes("Smoothed") && text(d.root).includes("Usual bounce"));
  check("the band sits under the daily line, the smoothed line over it", (() => {
    const svgEl = d.root.querySelector("svg polygon.bounceband").ownerSVGElement;
    const kids = [...svgEl.children];
    return kids.indexOf(d.root.querySelector("svg polygon.bounceband")) < kids.indexOf(daily(d.root))
      && kids.indexOf(daily(d.root)) < kids.indexOf(d.root.querySelector("svg polyline.smoothline"));
  })());
  check("the smoothed line is thinner than the daily line", Number(d.root.querySelector("svg polyline.smoothline").getAttribute("stroke-width"))
    < Number(daily(d.root).getAttribute("stroke-width")));
  check("the daily line is 1.5 wide", daily(d.root).getAttribute("stroke-width") === "1.5");
  check("the band stays inside the chart", (() => {
    const ys = d.root.querySelector("svg polygon.bounceband").getAttribute("points").split(" ").map((p) => Number(p.split(",")[1]));
    return Math.min(...ys) >= 20 - 0.01 && Math.max(...ys) <= 190 + 0.01;
  })());
  await range(d.root, "90 Days");
  check("at 90 days: both", smoothLine(d.root) === 1 && bounce(d.root) === 1);
  await range(d.root, "30 Days");
  check("at 30 days: neither", smoothLine(d.root) === 0 && bounce(d.root) === 0 && !text(d.root).includes("Usual bounce"));
  check("the weekly bars 3 wide and squared", bars(d.root).length > 0
    && bars(d.root).every((b) => b.getAttribute("stroke-width") === "3" && b.getAttribute("stroke-linecap") === "butt"));
  await range(d.root, "14 Days");
  check("at 14 days: neither", smoothLine(d.root) === 0 && bounce(d.root) === 0);

  console.log("A rise not counted as a new battery stays one line; a gap breaks it (rule BAT-17)");
  // The history drawn is the battery in the device: Device Sentinel
  // starts it again at each replacement (rules BAT-06, BAT-07), so a rise
  // left in it, such as a replacement a person cancelled, is the same
  // battery. 100 days falling 40% to 25%, a rise to 45% kept as the same
  // battery, and three weeks with a five-day gap in them.
  const kept = Array.from({ length: 100 }, (_, i) => 40 - (15 * i) / 99)
    .concat(Array.from({ length: 21 }, (_, i) => (i >= 8 && i < 13 ? null : 45 - i * 0.2)));
  const r = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    page.battery = { ...door.device(JSON.parse(JSON.stringify(page))).battery, daily: kept, now: 41 };
    return page;
  } });
  check("two stretches: up to the gap and past it", smoothLine(r.root) === 2 && bounce(r.root) === 2,
    [smoothLine(r.root), bounce(r.root)]);
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
