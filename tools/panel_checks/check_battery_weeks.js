// File: tools/panel_checks/check_battery_weeks.js, Version: 0.27.14 (2026-10-29)
// Panel checks: battery trends by the week on a device's
// page and on Battery Trends.
// A model's pace is the slowest to the fastest of the other cells of
// its model (rule BAT-16). A cell above three times the threshold is not
// judged (rule BAT-10).
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

// S63: steady, then speeding up.
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
  check("the sentence gives its pace today", page.includes("Falling faster each week, about 5.9 points a week today."), page.slice(-1500));
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

  console.log("A cell above three times the threshold");
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

  console.log("A cell with under four weeks of readings");
  const short = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); page.battery.ceiling = 80; page.battery.short = true; return page; },
  });
  const shortText = text(short.root);
  check("it says nothing about a fall", !shortText.includes("Steady:") && !shortText.includes("Falling"), shortText.slice(-1200));
  const shortCells = [...short.root.querySelectorAll("table.figures td")].map((td) => td.textContent);
  check("its reading is left empty, its weeks shown", !shortCells.includes("steady") && shortCells.length > 3, shortCells);

  console.log("A level reads as reported (0.27.1)");
  const half = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); page.battery.now = 15.5; page.battery.threshold = 15; return page; },
  });
  const halfCells = [...half.root.querySelectorAll("table.figures td")].map((td) => td.textContent);
  check("the LEVEL column reads 15.5%, not 16%", halfCells[0] === "15.5%", halfCells);
  check("and the card's title the same", text(half.root).includes("15.5% now"));

  console.log("A lithium cell, its model's pace and its day's evidence");
  const coin = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => {
      steady.device(page);
      Object.assign(page.battery, { now: 100, ceiling: 45, lithium: "CR1632",
        model_pace: { model: "Aqara Door and window sensor", others: 7, pace_low: 0.8, pace_high: 1.6 },
        evidence: { day: "2026-10-22", volts: 2.95, temperature: 21.5, messages: 182, days: 12 } });
      return page;
    },
  });
  const coinText = text(coin.root);
  check("a lithium cell is said to be one", coinText.includes("A lithium cell (CR1632) holds its level near full"), coinText.slice(-1500));
  check("its model's pace is a range, as context (BAT-16)", coinText.includes("Others of this model lose 0.8 to 1.6 points a week."), coinText.slice(-1500));
  const same = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => {
      steady.device(page);
      Object.assign(page.battery, { now: 100, ceiling: 45, model_pace: { model: "Aqara", others: 2, pace_low: 0.8, pace_high: 0.8 } });
      return page;
    },
  });
  check("a range whose ends agree reads one number", text(same.root).includes("Others of this model lose 0.8 points a week.")
    && !text(same.root).includes("0.8 to 0.8"), text(same.root).slice(-1500));
  const none = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); Object.assign(page.battery, { now: 100, ceiling: 45, model_pace: null }); return page; },
  });
  check("no pace sent, no line", !text(none.root).includes("Others of this model"));
  for (const [low, high, words] of [[0.96, 1.04, "lose 1 point a week."], [0, 0, "lose almost nothing a week."],
    [0.04, 1.6, "lose up to 1.6 points a week."]]) {
    const one = await open(`${PREFIX}/device/${DEVICE}`, {
      device: (page) => { steady.device(page); Object.assign(page.battery, { now: 100, ceiling: 45, model_pace: { model: "Aqara", others: 2, pace_low: low, pace_high: high } }); return page; },
    });
    check(`a pace of ${low} to ${high} reads "${words}"`, text(one.root).includes(`Others of this model ${words}`), text(one.root).match(/Others of this model[^.]*\./));
  }
  check("its day's evidence is shown, for later", coinText.includes("Kept each day for a better forecast later: 2.95 V, 182 messages, 21.5 \u00b0C on"));
  const falling = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); Object.assign(page.battery, { lithium: "CR2032", reading: "falling" }); return page; },
  });
  check("a falling lithium cell is not given the note", !text(falling.root).includes("A lithium cell"));

  console.log("Battery Trends");
  const tab = await open(`${PREFIX}/battery-trends`, trends);
  const lithiumTab = await open(`${PREFIX}/battery-trends`, {
    battery_trends: (page) => {
      page.steady = [{ device_id: DEVICE, name: "Door Bath Main", type: null, level: 100, steps: "Smooth", days: 60, month_drop: 0,
        cell: "CR1632", lithium: "CR1632", model_pace: { model: "Aqara Door and window sensor", others: 7, pace_low: 0.8, pace_high: 1.6 } }];
      return page;
    },
  });
  // Each known battery named, and one nobody has set says so, because
  // one blank would mean two things.
  const mixed = (page) => {
    page.steady = [
      { device_id: "aaa1", name: "Door Kitchen", type: null, level: 80, steps: "Smooth", days: 60, month_drop: 1,
        cell: "2× AAA", lithium: null, model_pace: { model: "Third Reality Door sensor", others: 3, pace_low: 0.4, pace_high: 0.4 } },
      { device_id: "unk1", name: "Leak Sink", type: null, level: 90, steps: "Smooth", days: 60, month_drop: 0,
        cell: null, lithium: null, model_pace: null }];
    return page;
  };
  const rowCells = (root, name) => {
    const tr = [...root.querySelectorAll("tr")].find((row) => row.children[0] && row.children[0].textContent === name);
    return tr ? [...tr.children] : [];
  };
  const cellTab = await open(`${PREFIX}/battery-trends`, { battery_trends: mixed });
  const cellText = text(cellTab.root);
  check("a battery that is not lithium is named", rowCells(cellTab.root, "Door Kitchen").some((td) => td.textContent === "2× AAA"),
    rowCells(cellTab.root, "Door Kitchen").map((td) => td.textContent));
  // The last "Not Set" in the row is CELL's; TYPE reads it too.
  const notSet = rowCells(cellTab.root, "Leak Sink").filter((td) => td.textContent === "Not Set").pop();
  const notSetButton = notSet && notSet.querySelector("button.linkbtn");
  check("one nobody has set reads Not Set, a link that sets it in place (rule DASH-04)",
    Boolean(notSetButton) && !notSet.querySelector("a"), notSet && notSet.innerHTML);
  if (notSetButton) {
    notSetButton.click();
    await settle();
  }
  check("pressing Not Set opens the battery choices there, with Save and Cancel",
    Boolean(notSet && notSet.querySelector('select[aria-label="What powers this device"]'))
      && [...notSet.querySelectorAll("button")].map((b) => b.textContent).join(",") === "Save,Cancel", notSet && notSet.innerHTML);
  check("a line says how to set it", cellText.includes("Not Set: no battery type is known for the device. Press Not Set to choose it"), cellText.slice(-900));
  check("MODEL, A WEEK is explained with no lithium cell listed",
    cellText.includes("MODEL, A WEEK is how many points") && !cellText.includes("A lithium cell holds"), cellText.slice(-900));
  check("the line on where to set it is absent when every battery is known",
    !text(lithiumTab.root).includes("Not Set: no battery type"));
  const simpleTab = await open(`${PREFIX}/battery-trends`, {
    battery_trends: mixed,
    status: (reply) => ({ ...reply, dashboard: "simple" }),
  });
  const simpleNotSet = rowCells(simpleTab.root, "Leak Sink").filter((td) => td.textContent === "Not Set").pop();
  check("Simple: Not Set is the link too, with no line below the table",
    Boolean(simpleNotSet) && Boolean(simpleNotSet.querySelector("button.linkbtn")) && !text(simpleTab.root).includes("Not Set: no battery type"),
    simpleNotSet && simpleNotSet.innerHTML);
  const coinRow = [...lithiumTab.root.querySelectorAll("tr")].map((tr) => [...tr.children].map((td) => td.textContent))
    .find((cells) => cells[0] === "Door Bath Main");
  check("Other Cells names the lithium cell and its model's pace", coinRow && coinRow.includes("CR1632, lithium") && coinRow.includes("0.8 to 1.6"), coinRow);
  check("and says what the two columns mean", text(lithiumTab.root).includes("MODEL, A WEEK is how many points the other cells of the same model lose a week, slowest to fastest"));
  check("a range whose ends agree reads one number in the column",
    rowCells(cellTab.root, "Door Kitchen").some((td) => td.textContent === "0.4"), rowCells(cellTab.root, "Door Kitchen").map((td) => td.textContent));
  // The summary's three parts add up to the cells, so a cell at 0% and
  // not falling, like Soil Irrigation, is counted in one (rule BAT-18).
  const counted = await open(`${PREFIX}/battery-trends`, {
    battery_trends: (page) => {
      trends.battery_trends(page);
      const soil = { device_id: "soil", name: "Soil Irrigation", type: null, level: 0, steps: "Smooth", days: 60, month_drop: 0, cell: null, lithium: null, model_pace: null };
      page.low = [{ ...page.falling[0], level: 12 }, soil];
      page.steady = [{ device_id: "s1", name: "Door Hall", type: null, level: 90, steps: "Smooth", days: 60, month_drop: 0, cell: null, lithium: null, model_pace: null }];
      page.cells = 4;
      return page;
    },
  });
  const countedLine = (counted.root.querySelector(".pane > p") || {}).textContent || "";
  check("the summary counts a low cell that is not falling on its own, and a falling one once",
    countedLine.startsWith(`4 cells report a level. 2 falling, 1 at or under your threshold of ${payloads.battery_trends.threshold}% and not falling, 1 not falling or not yet judged.`),
    countedLine);
  const tabText = text(tab.root);
  check("a level reads as reported there too, 37.5%", tabText.includes("37.5%") && !tabText.includes("38%"), tabText.slice(0, 1600));
  const tabHeads = [...tab.root.querySelectorAll("th")].map((th) => th.textContent);
  check("the Falling table shows the five weeks", ["28 DAYS AGO", "THIS WEEK", "PACE"].every((h) => tabHeads.some((t) => t.startsWith(h))), tabHeads);
  check("with the pace in points a week", tabText.includes("down 5.9 a week"), tabText.slice(0, 1600));
  check("the Falling list says where judging starts",
    tabText.includes("A cell is judged falling, and given a time left, at or under 45%, three times your threshold."), tabText.slice(0, 900));
  check("a steady fall inside the warning days is named under Batteries to Watch",
    tabText.includes("Batteries to Watch") && tabText.includes("Back Door (reaches 15% in about 3 to 5 weeks)."), tabText.slice(0, 1200));
  const leftCells = [...tab.root.querySelectorAll("td")].filter((td) => td.textContent.startsWith("reaches 15% in"));
  check("the time left reaches the threshold", leftCells.length === 2, leftCells.map((td) => td.textContent));
  check("only the accelerating cell's time left is red",
    leftCells.filter((td) => (td.getAttribute("style") || "").includes("error-color")).map((td) => td.textContent).join("|")
      === "reaches 15% in about 3 to 4 weeks");
  check("the other cells are not called steady", tabText.includes("Other Cells") && !/\bSteady\b/.test(tabText), tabText.slice(0, 900));
  check("the Steady table counts four weeks in points", tabHeads.some((t) => t.startsWith("4 WEEKS")), tabHeads);
  check("the models are read a week at a time", tabText.includes("points lost a week over the last four weeks"), tabText.slice(0, 600));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
