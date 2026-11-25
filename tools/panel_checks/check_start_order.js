// File: tools/panel_checks/check_start_order.js, Version: 0.30.8 (2026-11-25)
// Panel checks: the page opens whatever order Home Assistant sets it up
// in. Home Assistant gives a panel its hass before its route, and puts it
// on the page only after both, while the page is still reading its words
// from the server. A route, a reconnect or a server message that comes in
// that wait must not reach for a part of the page not yet drawn, and the
// page subscribes to the server once.
// Run with: LC_ALL=en_US.UTF-8 node check_start_order.js [path/to/panel.js]
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || path.join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
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
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// order: the steps in the order Home Assistant takes them.
async function open(order, route = "/") {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) errors.push(String(err.message));
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${route === "/" ? "/" : route}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  let subscriptions = 0;
  const hass = {
    // The server answers after a moment, as a real one does.
    callWS: async (message) => {
      await wait(30);
      if (message.type === "frontend/get_user_data") return { value: {} };
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: {
      subscribeMessage: async (callback) => {
        subscriptions += 1;
        callback({ panel: "panel.js", marker: "x" });
        return () => {};
      },
    },
    states: {}, language: "en", locale: {},
    config: { time_zone: "America/Guayaquil", language: "en" },
  };
  const steps = {
    hass: () => { panel.hass = hass; },
    route: () => { panel.route = { prefix: PREFIX, path: route }; },
    route_again: () => { panel.route = { prefix: PREFIX, path: "/battery-trends" }; },
    append: () => { window.document.body.append(panel); },
    reconnect: () => { panel.remove(); window.document.body.append(panel); },
  };
  for (const step of order) {
    try {
      steps[step]();
    } catch (err) {
      errors.push(`${step}: ${err.message}`);
    }
  }
  await wait(400);
  const root = panel.shadowRoot || panel;
  const tabs = [...root.querySelectorAll("button.tab")].map((b) => b.textContent);
  const chosen = [...root.querySelectorAll("button.tab")].filter((b) => b.getAttribute("aria-selected") === "true").map((b) => b.textContent);
  return { errors, tabs, chosen, subscriptions, attached: panel.isConnected };
}

(async () => {
  console.log("Home Assistant's order: hass, route, then on the page");
  let page = await open(["hass", "route", "append"]);
  check("no error while the words load", page.errors.length === 0, page.errors);
  check("the tabs are drawn", page.tabs[0] === "Daily Brief", page.tabs);
  check("subscribed once", page.subscriptions === 1, page.subscriptions);

  console.log("A second route before the page is drawn");
  page = await open(["hass", "route", "append", "route_again"]);
  check("no error", page.errors.length === 0, page.errors);
  check("the later route's tab is the one shown", page.chosen[0] === "Battery Trends", page.chosen);

  console.log("Taken off the page and put back while the words load");
  page = await open(["hass", "route", "append", "reconnect"]);
  check("no error", page.errors.length === 0, page.errors);
  check("subscribed once", page.subscriptions === 1, page.subscriptions);
  check("the tabs are drawn", page.tabs[0] === "Daily Brief", page.tabs);

  console.log("The order the other checks use: on the page, route, then hass");
  page = await open(["append", "route", "hass"]);
  check("no error", page.errors.length === 0, page.errors);
  check("the tabs are drawn", page.tabs[0] === "Daily Brief", page.tabs);

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
