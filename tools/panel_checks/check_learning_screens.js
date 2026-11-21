// File: tools/panel_checks/check_learning_screens.js, Version: 0.30.0 (2026-11-21)
// Panel checks: Battery Trends and Signal Trends on a new install
// (rules BAT-19, SIG-18). While no device has enough days, each tab
// opens with a box saying when its trends start, why there is a wait,
// what works already and how far along the house is. Signal Trends
// lists the devices still learning, and keeps the list under the
// regular page once one device has its days.
// Run with: LC_ALL=en_US.UTF-8 node check_learning_screens.js [path/to/panel.js]
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


const learner = (over) => ({ device_id: "d", name: "Door 2nd Bedroom", scale: "lqi", now: 112, days: 7, from: "2026-11-27", ...over });
const LEARNING = [
  learner({}),
  learner({ device_id: "p", name: "Living Room Plug", scale: "rssi", now: -58, days: 5, from: "2026-11-29" }),
];
const row = (over) => ({
  device_id: "x", name: "Device", scale: "lqi", now: 100, normal: 100, line: 60,
  week: 100, usual: 100, change: 0, spreads: 0, bad_days: 0, readings_a_day: 24, days: 60, ...over,
});
const text = (root) => root.querySelector(".pane").textContent.replace(/\s+/g, " ");

(async () => {
  console.log("Signal Trends while learning (rule SIG-18)");
  let { root } = await open(`${PREFIX}/signal-trends`, {
    signal_trends: (reply) => ({ ...reply, devices: [], learning: LEARNING, need: 21, scales: {}, counts: { unsteady: 0, steady: 0 } }),
  });
  let shown = text(root);
  const box = root.querySelector(".pane .learnbox");
  check("The box opens the tab", !!box && root.querySelector(".pane").firstElementChild === box);
  check("It names the day trends start", /Signal trends start on November 27/.test(shown), shown.slice(0, 120));
  check("It counts the devices and says why there is a wait",
    /2 devices report a signal\. Device Sentinel needs 21 days of readings from each device to learn its own normal/.test(shown));
  check("It says what works from the first day", /short drop-outs are reported from the first day/.test(shown));
  check("Day 7 of 21, 14 days to go", /Day 7 of 21/.test(shown) && /14 days to go/.test(shown));
  check("The bar is a third full", /width: ?33%/.test(box.querySelector(".learntrack div").getAttribute("style")));
  check("Short drop-outs are still there", /Devices With Short Drop-Outs/.test(shown));
  check("No chart or unsteady list while learning", !/How Each Link Sits/.test(shown) && !/Devices With Unsteady Signals/.test(shown));
  const rows = [...root.querySelectorAll(".pane table tbody tr")].map((tr) => [...tr.cells].map((td) => td.textContent.trim()));
  check("Still Learning lists each device with its signal, days and start", rows.some((r) => r.join("|") === "Door 2nd Bedroom|LQI 112|7|Nov 27")
    && rows.some((r) => r.join("|") === "Living Room Plug|RSSI \u221258|5|Nov 29"), rows);
  check("No null, undefined or NaN", !/null|undefined|NaN/.test(shown));

  console.log("Signal Trends with trends and some still learning");
  ({ root } = await open(`${PREFIX}/signal-trends`, {
    signal_trends: (reply) => ({ ...reply, devices: [row({ device_id: "t", name: "Old Plug" })], learning: LEARNING.slice(1), need: 21, scales: { lqi: 1 }, counts: { unsteady: 0, steady: 1 } }),
  }));
  shown = text(root);
  check("The regular page shows, with no box", !root.querySelector(".pane .learnbox") && /How Each Link Sits/.test(shown));
  check("Still Learning comes under it", /Still Learning 1 device/.test(shown) && /Living Room Plug/.test(shown));

  console.log("Signal Trends with nothing learning");
  ({ root } = await open(`${PREFIX}/signal-trends`, {
    signal_trends: (reply) => ({ ...reply, devices: [row({ device_id: "t", name: "Old Plug" })], learning: [], scales: { lqi: 1 }, counts: { unsteady: 0, steady: 1 } }),
  }));
  check("No Still Learning section", !/Still Learning/.test(text(root)));

  console.log("Battery Trends while learning (rule BAT-19)");
  const cell = (over) => ({ device_id: "c", name: "Door 2nd Bedroom", level: 12, rate: 0, type: "Door/Window Sensor", maker: "Aqara", model: "Door", alone: false, learning: true, ...over });
  ({ root } = await open(`${PREFIX}/battery-trends`, {
    battery_trends: (reply) => ({ ...reply, thresholds: { alkaline: 10, lithium: 20, rechargeable: 20 },
      cell_rows: [cell({}), cell({ device_id: "k", name: "Kitchen Motion", level: 80, model: "Motion" })],
      models: [{ maker: "Aqara", model: "Door", cells: 1, rate: 0, typical: 12, lowest: 12, lowest_name: "Door 2nd Bedroom", lowest_id: "c", learning: true, types: [["Door/Window Sensor", 1]] },
        { maker: "Aqara", model: "Motion", cells: 1, rate: 0, typical: 80, lowest: 80, lowest_name: "Kitchen Motion", lowest_id: "k", learning: true, types: [["Motion Sensor", 1]] }],
      bank: [0, 1, 0, 0, 0, 0, 0, 0, 1, 0], cells: 2,
      falling: [], low: [{ device_id: "c", name: "Door 2nd Bedroom", type: "Door/Window Sensor", level: 12, days: 7 }],
      steady: [{ device_id: "k", name: "Kitchen Motion", type: "Motion Sensor", level: 80, days: 7 }],
      unreadable: [], no_battery: 51,
      learning: { day: 7, need: 28, start: "2026-12-04", low_now: 1 } }),
  }));
  shown = text(root);
  check("The box opens the tab", root.querySelector(".pane").firstElementChild === root.querySelector(".pane .learnbox"));
  check("It names the day forecasts start", /Battery forecasts start on December 4/.test(shown), shown.slice(0, 120));
  check("It says why and what works now, with the count at or under the threshold",
    /needs four weeks of readings to tell a battery that is falling from one that only wobbles/.test(shown)
    && /at or under its type's threshold \(10% for alkaline, 20% for lithium and other, 20% for rechargeable\) is reported from the first day: 1 is now\./.test(shown));
  check("Day 7 of 28, 21 days to go", /Day 7 of 28/.test(shown) && /21 days to go/.test(shown));
  check("The headline says only what is known",
    /2 batteries report a level: 1 at or under its type's threshold \(10% for alkaline, 20% for lithium and other, 20% for rechargeable\), 1 above it\. 51 watched devices report no battery at all\./.test(shown), shown.slice(0, 600));
  const rates = [...root.querySelectorAll(".pane td")].map((td) => td.textContent.trim());
  check("The rate column reads learning", rates.filter((t) => t === "learning").length === 2 && !rates.includes("level"), rates.slice(0, 20));
  check("No null, undefined or NaN", !/null|undefined|NaN/.test(shown));

  console.log("Battery Trends once a battery has its four weeks");
  ({ root } = await open(`${PREFIX}/battery-trends`, { battery_trends: (reply) => ({ ...reply, learning: null }) }));
  check("No box", !root.querySelector(".pane .learnbox"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
