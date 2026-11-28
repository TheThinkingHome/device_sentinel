// File: tools/panel_checks/check_battery_weeks.js, Version: 0.30.12 (2026-11-28)
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
    config: extra && extra.__config ? extra.__config : undefined,
  };
  await settle();
  // Other Cells opens shut on Battery Trends (rule BAT-18): opened here,
  // so its table can be read.
  const show = panel.shadowRoot && [...panel.shadowRoot.querySelectorAll(".otherbox button")].find((b) => b.textContent === "Show");
  if (show) { show.click(); await settle(); }
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
      sentence: "Battery decay is accelerating, about 5.9 points a week today.",
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
    page.thresholds = { alkaline: 10, lithium: 15, rechargeable: 20 };
    page.falling = [{
      device_id: DEVICE, name: "Garage Door", level: 37.5, since: null, steps: "Smooth",
      weeks: [54.64, 53.71, 51.21, 46.0, 39.64], reading: "accelerating", pace: 5.9,
      left: "about 3 to 4 weeks", until: "reaches 15% in about 3 to 4 weeks", left_soon: true, watch: false,
    }, {
      device_id: page.falling && page.falling[1] ? page.falling[1].device_id : "watch-1", name: "Back Door", level: 30.5,
      since: null, steps: "Smooth", weeks: [36, 35, 34, 32.8, 31.6], reading: "falling", pace: 1.2,
      left: "about 3 to 5 weeks", until: "reaches 15% in about 3 to 5 weeks", left_soon: true, watch: true,
    }];
    // As the server groups them (rule BAT-18): the accelerating cell is a
    // problem, the steady one an other cell with its time left.
    page.problems = [{ ...page.falling[0], state: "accelerating", left: page.falling[0].until, month_drop: 15 }];
    page.others = [{ ...page.falling[1], state: "steady", left: page.falling[1].until, month_drop: 4.4 }];
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
  check("the sentence gives its pace today", page.includes("Battery decay is accelerating, about 5.9 points a week today."), page.slice(-1500));
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
  // Advanced, in plain words.
  check("its day's evidence is shown, for later", coinText.includes("Saved for future battery forecasts: 2.95 V, 182 messages and 21.5 \u00b0C on"),
    (coinText.match(/Saved for future.{0,80}/) || [""])[0]);
  const falling = await open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); Object.assign(page.battery, { lithium: "CR2032", reading: "falling" }); return page; },
  });
  check("a falling lithium cell is not given the note", !text(falling.root).includes("A lithium cell"));

  console.log("A cold battery's voltage, as read and corrected to 20 \u00b0C (BAT-03)");
  const resting = (rest, config) => open(`${PREFIX}/device/${DEVICE}`, {
    device: (page) => { steady.device(page); Object.assign(page.battery, { lithium: "CR2032", resting: rest }); return page; },
    __config: config,
  });
  const frozen = await resting({ volts: 2.844, corrected: 2.965, celsius: -2, judged: true });
  check("a cold coin cell shows the reading, then the corrected value",
    text(frozen.root).includes("Resting voltage 2.844 V (2.965 V corrected for \u22122 \u00b0C)."), (text(frozen.root).match(/Resting voltage.{0,60}/) || [""])[0]);
  const fahrenheit = await resting({ volts: 2.844, corrected: 2.965, celsius: -2, judged: true },
    { unit_system: { temperature: "\u00b0F" } });
  check("in \u00b0F where the house uses it", text(fahrenheit.root).includes("corrected for 28 \u00b0F)"),
    (text(fahrenheit.root).match(/Resting voltage.{0,60}/) || [""])[0]);
  const warm = await resting({ volts: 3.01, corrected: 3.01, celsius: null, judged: true });
  check("a warm coin cell shows its reading alone", text(warm.root).includes("Resting voltage 3.01 V.")
    && !text(warm.root).includes("corrected for"));
  const pack = await resting({ volts: 4.2, corrected: 4.47, celsius: -10, judged: false });
  check("a cold AAA pack shows both too", text(pack.root).includes("Resting voltage 4.20 V (4.47 V corrected for \u221210 \u00b0C)."));
  const warmPack = await resting({ volts: 3.0, corrected: 3.0, celsius: null, judged: false });
  check("a warm AAA pack shows no voltage line", !text(warmPack.root).includes("Resting voltage"));
  const nothing = await resting(null);
  check("no resting voltage sent, no line", !text(nothing.root).includes("Resting voltage"));

  console.log("Battery Trends");
  const tab = await open(`${PREFIX}/battery-trends`, trends);
  const lithiumTab = await open(`${PREFIX}/battery-trends`, {
    battery_trends: (page) => {
      page.others = [{ device_id: DEVICE, name: "Door Bath Main", type: null, level: 100, steps: "Smooth", days: 60, month_drop: 0,
        cell: "CR1632", lithium: "CR1632", model_pace: { model: "Aqara Door and window sensor", others: 7, pace_low: 0.8, pace_high: 1.6 } }];
      return page;
    },
  });
  // Each known battery named, and one nobody has set says so, because
  // one blank would mean two things.
  const mixed = (page) => {
    page.others = [
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
  // The summary's parts add up to the cells, each counted once in its
  // worst state (rule BAT-18).
  const counted = await open(`${PREFIX}/battery-trends`, {
    battery_trends: (page) => {
      trends.battery_trends(page);
      const soil = { device_id: "soil", name: "Soil Irrigation", type: null, level: 0, steps: "Smooth", days: 60, month_drop: 0, cell: null, lithium: null, model_pace: null };
      page.problems = [{ ...page.falling[0], level: 12, state: "low" }, { ...soil, state: "low" },
        { device_id: "coin", name: "Thermometer", type: null, level: 59, volts: "2.6", coin: true, state: "volts" }];
      page.others = [{ device_id: "s1", name: "Door Hall", type: null, level: 90, steps: "Smooth", days: 60, month_drop: 0, cell: null, lithium: null, model_pace: null, state: "holding" }];
      return page;
    },
  });
  const countedLine = (counted.root.querySelector(".pane > p") || {}).textContent || "";
  check("the summary counts each cell once, in its worst state",
    countedLine.startsWith("4 cells report a level. 2 below the threshold, 1 voltage falling, 0 accelerating, 0 charge falling at a steady pace, 1 not judged or steady."),
    countedLine);
  const chipText = [...counted.root.querySelectorAll(".chips .chip")].map((b) => b.textContent);
  check("the chips count each state", chipText.join("|") === "All 3|Below the Threshold 2|Accelerating 0|Voltage Falling 1", chipText);
  const coinCells = rowCells(counted.root, "Thermometer").map((td) => td.textContent);
  check("a falling voltage shows the coin cell scale and no time left yet",
    coinCells.includes("voltage falling") && coinCells.includes("2.6 Vnew 3.0, spent 2.0") && coinCells.includes("not yet predicted"), coinCells);
  const order = [...counted.root.querySelectorAll("tr")].map((tr) => tr.children[2] && tr.children[2].textContent)
    .filter((t) => ["below the threshold", "decay accelerating", "voltage falling"].includes(t));
  check("worst first: below the threshold, then voltage falling", order.join("|") === "below the threshold|below the threshold|voltage falling", order);
  [...counted.root.querySelectorAll(".chips .chip")].find((b) => b.textContent.startsWith("Voltage Falling")).click();
  await settle();
  const filtered = [...counted.root.querySelectorAll("tr")].map((tr) => tr.children[0] && tr.children[0].textContent);
  check("a chip shows only its state", filtered.includes("Thermometer") && !filtered.includes("Soil Irrigation"), filtered);
  const tabText = text(tab.root);
  check("a level reads as reported there too, 37.5%", tabText.includes("37.5%") && !tabText.includes("38%"), tabText.slice(0, 1600));
  const tabHeads = [...tab.root.querySelectorAll("th")].map((th) => th.textContent);
  check("Batteries With Problems has a state, a voltage and a time left",
    ["STATE", "VOLTAGE", "TIME LEFT"].every((h) => tabHeads.some((t) => t.startsWith(h))), tabHeads);
  check("the order is the chart, the problems, how to read them, By Model, then Other Cells",
    /The Bank.*Batteries With Problems.*How to read this table.*By Model.*Other Cells/s.test(tabText), tabText.slice(0, 600));
  check("How to read this table says where judging starts",
    tabText.includes("A cell's charge is judged, and given a time left, only at or under three times its type's threshold."), tabText.slice(0, 1600));
  check("a steady fall is an other cell with its time left, and no Batteries to Watch section",
    !tabText.includes("Batteries to Watch") && rowCells(tab.root, "Back Door").some((td) => td.textContent === "charge falling at a steady pace"),
    rowCells(tab.root, "Back Door").map((td) => td.textContent));
  const leftCells = [...tab.root.querySelectorAll("td")].filter((td) => td.textContent.startsWith("reaches 15% in"));
  check("the time left reaches the threshold", leftCells.length === 2, leftCells.map((td) => td.textContent));
  check("the accelerating cell's state is red",
    [...tab.root.querySelectorAll("td")].some((td) => td.textContent === "decay accelerating" && (td.getAttribute("style") || "").includes("error-color")));
  const shut = await open(`${PREFIX}/battery-trends`, trends);
  check("Other Cells can be shut again", (() => {
    const button = [...shut.root.querySelectorAll(".otherbox button")].find((b) => b.textContent === "Hide");
    if (!button) return false;
    button.click();
    return true;
  })());
  await settle();
  check("and then shows no table", !shut.root.querySelector(".otherbox table")
    && [...shut.root.querySelectorAll(".otherbox button")].some((b) => b.textContent === "Show"));
  check("the other cells are not called steady", tabText.includes("Other Cells") && !/\bSteady\b/.test(tabText), tabText.slice(0, 900));
  check("the Steady table counts four weeks in points", tabHeads.some((t) => t.startsWith("4 WEEKS")), tabHeads);
  check("the models are read a week at a time", tabText.includes("points lost a week over the last four weeks"), tabText.slice(0, 600));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
