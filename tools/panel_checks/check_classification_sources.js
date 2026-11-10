// File: tools/panel_checks/check_classification_sources.js, Version: 0.28.8 (2026-11-09)
// Panel checks: the gear, the date beside "As of", and the devices set
// aside and excluded on the Devices tab (rule DASH-12), driven
// with real WebSocket replies captured from the integration.
// Run with: LC_ALL=en_US.UTF-8 node check_classification_sources.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const args = process.argv.slice(2);
const locale = args.includes("--locale") ? args[args.indexOf("--locale") + 1] : null;
const PANEL = args.find((a) => a.endsWith(".js")) || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));

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

async function open(lang, path = "") {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local/device-sentinel${path}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.navigated = [];
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  // Home Assistant's router: a new route whenever the address changes.
  const route = () => ({ prefix: "/device-sentinel", path: window.location.pathname.slice("/device-sentinel".length) });
  window.addEventListener("location-changed", () => {
    window.navigated.push(window.location.pathname);
    if (window.location.pathname.startsWith("/device-sentinel")) panel.route = route();
  });
  window.addEventListener("popstate", () => { panel.route = route(); });
  window.document.body.append(panel);
  panel.route = route();
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await new Promise((resolve) => setTimeout(resolve, 50));
  return { window, panel, root: panel.shadowRoot };
}

async function tab(root, name) {
  const button = [...root.querySelectorAll(".tab")].find((b) => b.textContent === name);
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 60));
}

(async () => {
  // The date follows the JavaScript engine's language, which in Node is
  // the process's own (LC_ALL), not the page's navigator.language. So
  // each language runs in its own process, started in that language.
  if (locale) {
    const { root } = await open(locale);
    const text = root.querySelector(".asof").textContent;
    const expect = {
      "en-GB": /^As of \d{2}:\d{2}, \d{1,2} [A-Z][a-z]+ \d{4}$/,
      "de-DE": /^As of \d{2}:\d{2}, \d{1,2}\. [A-Z][a-zä]+ \d{4}$/,
    }[locale];
    check(`${locale} writes the time and date its own way`, expect.test(text), text);
    console.log(`\n${passed} passed, ${failed} failed`);
    process.exit(failed ? 1 : 0);
  }
  console.log("Header, in American English");
  let { window, root } = await open("en-US");
  const asOf = root.querySelector(".asof").textContent;
  check("As of carries the time then the long date", /^As of \d{1,2}:\d{2}\s?[AP]M, [A-Z][a-z]+ \d{1,2}, \d{4}$/.test(asOf), asOf);

  const gear = root.querySelector(".toolbar a.gear");
  check("a gear is in the toolbar", gear !== null);
  check("the gear links to the integration's page", gear && gear.getAttribute("href") === "/config/integrations/integration/device_sentinel", gear && gear.getAttribute("href"));
  check("the gear is labelled for a screen reader", gear && gear.getAttribute("aria-label") === "Device Sentinel settings");
  check("the gear draws Home Assistant's cog", gear && gear.querySelector("svg path") !== null && gear.querySelector("svg path").getAttribute("d").startsWith("M12,15.5A3.5,3.5"));
  if (gear) gear.click();
  check("clicking the gear navigates inside Home Assistant", window.navigated.includes("/config/integrations/integration/device_sentinel"), window.navigated);

  console.log("The printout's heading");
  ({ window, root } = await open("en-US"));
  // The printer icon beside the gear, or a Print button.
  const print = root.querySelector(".toolbar .print") || [...root.querySelectorAll("button")].find((b) => b.textContent === "Print");
  print.click();
  const frame = window.document.querySelector("iframe");
  const heading = frame ? frame.contentDocument.querySelector(".printhead p").textContent : "";
  check("the printout says Data as of in the long form", /Data as of \d{1,2}:\d{2}\s?[AP]M, [A-Z][a-z]+ \d{1,2}, \d{4}\./.test(heading), heading);
  check("the printout says Printed in the long form", /Printed \d{1,2}:\d{2}\s?[AP]M, [A-Z][a-z]+ \d{1,2}, \d{4}\.$/.test(heading), heading);

  console.log("Classification's devices on the Devices tab (rule DASH-12)");
  ({ window, root } = await open("en-US"));
  check("there is no Classification tab", ![...root.querySelectorAll(".tab")].some((b) => b.textContent === "Classification"));
  await tab(root, "Devices");
  let pane = root.querySelector(".pane");
  const summary = pane.querySelector("p").textContent;
  check("the summary counts the watched, excluded and set-aside devices", /^Watching 4 of 5 devices\..* 0 are excluded and 1 is set aside\./.test(summary), summary);
  const chipTexts = [...pane.querySelectorAll(".chip")].map((c) => c.textContent);
  check("it opens on Watched, with Excluded and Set aside chips", chipTexts.includes("Watched 4") && chipTexts.includes("Excluded 0") && chipTexts.includes("Set aside 1")
    && pane.querySelector('.chip[aria-pressed="true"]').textContent === "Watched 4", chipTexts);
  check("a set-aside device is filtered out by default", ![...pane.querySelectorAll("tbody tr")].some((tr) => tr.cells[0].textContent === "Device Sentinel"));
  const heads = [...pane.querySelectorAll("thead th")].map((th) => th.textContent);
  check("RHYTHM and BATTERY are gone", JSON.stringify(heads) === JSON.stringify(["DEVICE", "TYPE", "AREA", "INTEGRATION", "STANDING", "PROBLEM", "LAST REPORT", "WINDOW"]), heads);
  const cell = (name, column) => {
    const hs = [...pane.querySelectorAll("thead th")].map((th) => th.textContent);
    const row = [...pane.querySelectorAll("tbody tr")].find((tr) => tr.cells[0].textContent === name);
    return row ? row.cells[hs.indexOf(column)].textContent : null;
  };
  check("STANDING names every mute with its source", cell("Alpha Panel", "STANDING").startsWith("Muted: "), cell("Alpha Panel", "STANDING"));
  [...pane.querySelectorAll(".chip")].find((c) => c.textContent.startsWith("Set aside")).click();
  await new Promise((resolve) => setTimeout(resolve, 30));
  pane = root.querySelector(".pane");
  check("Set aside shows the device with its reason", cell("Device Sentinel", "STANDING") === "Set aside: service", cell("Device Sentinel", "STANDING"));
  check("its type reads Not Watched, with nothing to set", cell("Device Sentinel", "TYPE") === "Not Watched");
  const keyText = pane.lastElementChild.textContent;
  check("the key sits under the table", keyText.startsWith("Set aside, by reason:"), keyText.slice(0, 40));
  check("the key has the four reasons other than an exclusion", ["service:", "disabled:", "duplicate coordinator:", "no entities:"].every((part) => keyText.includes(part)) && !keyText.includes("excluded:"), keyText);

  console.log("Classification's old address");
  const old = await open("en-US", "/classification");
  const oldPane = old.root.querySelector(".pane");
  check("it opens the Devices tab on Set aside", old.window.location.pathname.endsWith("/devices")
    && oldPane.querySelector('.chip[aria-pressed="true"]') && oldPane.querySelector('.chip[aria-pressed="true"]').textContent.startsWith("Set aside"),
    [old.window.location.pathname, oldPane.textContent.slice(0, 120)]);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
