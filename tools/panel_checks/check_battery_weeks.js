// File: tools/panel_checks/check_battery_weeks.js, Version: 0.27.0 (2026-10-22)
// Panel checks: battery trends by the week on a device's
// page and on Battery Trends.
// Written for 0.23.6, the knee check moved to 30 days in 0.23.7; named by
// subject since 0.23.19. The knee went in 0.27.0, and a cell above twice
// the threshold is not judged (ruling #725).
// Run with: LC_ALL=en_US.UTF-8 node check_battery_weeks.js [path/to/panel.js]
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

// Tim Plas's S63 of 24 September: steady, then speeding up.
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
    page.ceiling = 45;
    page.falling = [{
      device_id: DEVICE, name: "Garage Door", level: 37.5, since: null, steps: "Smooth",
      weeks: [54.64, 53.71, 51.21, 46.0, 39.64], reading: "accelerating", pace: 5.9,
      left: "about 3 to 4 weeks", until: "reaches 15% in about 3 to 4 weeks", left_soon: true, watch: false,
    }, {
      device_id: page.falling && page.falling[1] ? page.falling[1].device_id : "watch-1", name: "Back Door", level: 30.5,
      since: null, steps: "Smooth", weeks: [36, 35, 34, 32.8, 31.6], reading: "falling", pace: 1.2,
      left: "about 3 to 5 weeks", until: "reaches 15% in about 3 to 5 weeks", left_soon: true, watch: true,
    }];
    return page;
  },
};

(async () => {
  console.log("A cell that sped up, on its page");
  const fast = await open(`${PREFIX}/device/${DEVICE}`, accelerating);
  const page = text(fast.root);
  const heads = [...fast.root.querySelectorAll("table.figures th")].map((th) => th.textContent);
  check("its table shows five weeks, oldest first", heads.join("|") === "LEVEL|28 DAYS AGO|21 DAYS AGO|14 DAYS AGO|7 DAYS AGO|THIS WEEK|READING|LEFT", heads);
  check("each week says what it lost", page.includes("down 6.4") && page.includes("down 5.2"), page.slice(-1500));
  check("the sentence gives its pace today (ruling #725)", page.includes("Falling faster each week, about 5.9 points a week today."), page.slice(-1500));
  [...fast.root.querySelectorAll("button")].find((b) => b.textContent === "30 Days").click();
  await settle();
  check("the chart marks no knee", fast.root.querySelectorAll("svg circle").length === 0);
  check("no rate per day is left on the page", !page.includes("/day"), page.slice(-1500));
  check("no three-slope legend is left", !page.includes("-day rate"), page.slice(-1500));

  console.log("A cell that only wobbles, on its page");
  const calm = await open(`${PREFIX}/device/${DEVICE}`, steady);
  const calmText = text(calm.root);
  check("it reads steady", calmText.includes("Steady: no week has fallen a point below the week before"), calmText.slice(-1200));
  check("no fitted line is drawn", ![...calm.root.querySelectorAll("svg polyline")].some((p) => p.getAttribute("stroke-dasharray") === "7 5"));
  check("and no knee", calm.root.querySelectorAll("svg circle").length === 0);

  console.log("A cell above twice the threshold (ruling #725)");
  const high = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); page.battery.ceiling = 40; return page; },
  });
  const highText = text(high.root);
  check("it says nothing about a fall", !highText.includes("Steady:") && !highText.includes("Not judged") && !highText.includes("Falling"),
    highText.slice(-1200));
  const readingCell = [...high.root.querySelectorAll("table.figures td")].map((td) => td.textContent);
  check("its reading is left empty", !readingCell.includes("steady") && !readingCell.includes("not judged"), readingCell);
  const under = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); page.battery.ceiling = 80; return page; },
  });
  check("under the ceiling a steady cell still reads steady", text(under.root).includes("Steady: no week has fallen"));

  console.log("Battery Trends");
  const tab = await open(`${PREFIX}/battery-trends`, trends);
  const tabText = text(tab.root);
  const tabHeads = [...tab.root.querySelectorAll("th")].map((th) => th.textContent);
  check("the Falling table shows the five weeks", ["28 DAYS AGO", "THIS WEEK", "PACE"].every((h) => tabHeads.some((t) => t.startsWith(h))), tabHeads);
  check("with the pace in points a week", tabText.includes("down 5.9 a week"), tabText.slice(0, 1600));
  check("the Falling list says where judging starts (ruling #725)",
    tabText.includes("A cell is judged falling, and given a time left, at or under 45%, three times your threshold."), tabText.slice(0, 900));
  check("a steady fall inside the warning days is named under Batteries to Watch (#731)",
    tabText.includes("Batteries to Watch") && tabText.includes("Back Door (reaches 15% in about 3 to 5 weeks)."), tabText.slice(0, 1200));
  const leftCells = [...tab.root.querySelectorAll("td")].filter((td) => td.textContent.startsWith("reaches 15% in"));
  check("the time left reaches the threshold (#730)", leftCells.length === 2, leftCells.map((td) => td.textContent));
  check("only the accelerating cell's time left is red (#731)",
    leftCells.filter((td) => (td.getAttribute("style") || "").includes("error-color")).map((td) => td.textContent).join("|")
      === "reaches 15% in about 3 to 4 weeks");
  check("the other cells are not called steady", tabText.includes("Other Cells") && !/\bSteady\b/.test(tabText), tabText.slice(0, 900));
  check("the Steady table counts four weeks in points", tabHeads.some((t) => t.startsWith("4 WEEKS")), tabHeads);
  check("the models are read a week at a time", tabText.includes("points lost a week over the last four weeks"), tabText.slice(0, 600));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
