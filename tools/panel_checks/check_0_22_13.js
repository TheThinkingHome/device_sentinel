// Checks for 0.22.13's panel changes, driven with real WebSocket
// replies captured from the integration. Run: node check_0_22_13.js
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

async function open(lang) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: "http://ha.local/device-sentinel", virtualConsole,
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
  // The Print button until 0.22.14, the printer icon beside the gear from 0.22.15.
  const print = root.querySelector(".toolbar .print") || [...root.querySelectorAll("button")].find((b) => b.textContent === "Print");
  print.click();
  const frame = window.document.querySelector("iframe");
  const heading = frame ? frame.contentDocument.querySelector(".printhead p").textContent : "";
  check("the printout says Data as of in the long form", /Data as of \d{1,2}:\d{2}\s?[AP]M, [A-Z][a-z]+ \d{1,2}, \d{4}\./.test(heading), heading);
  check("the printout says Printed in the long form", /Printed \d{1,2}:\d{2}\s?[AP]M, [A-Z][a-z]+ \d{1,2}, \d{4}\.$/.test(heading), heading);

  console.log("Classification");
  ({ window, root } = await open("en-US"));
  await tab(root, "Classification");
  const pane = root.querySelector(".pane");
  const summary = pane.querySelector("p").textContent;
  check("the summary names all five reasons", ["integrations you excluded", "service devices", "disabled devices", "duplicate coordinators", "devices with no entities"].every((reason) => summary.includes(reason)), summary);
  check("the summary no longer counts entities with no device", !summary.includes("belong to no device") && !summary.includes("seen only as entities"), summary);
  const cell = (name, column) => {
    const heads = [...pane.querySelectorAll("thead th")].map((th) => th.textContent);
    const row = [...pane.querySelectorAll("tbody tr")].find((tr) => tr.cells[0].textContent === name);
    return row ? row.cells[heads.indexOf(column)].textContent : null;
  };
  check("MUTED lists every mute with its source", cell("Alpha Panel", "MUTED") === "Global (device); battery (device)", cell("Alpha Panel", "MUTED"));
  // Bravo carries a freeze mute as well since the 0.22.16 fixture, in the order ruled then.
  check("the family mutes show, freeze before battery", cell("Bravo Phone", "MUTED") === "freeze (device); battery (device)", cell("Bravo Phone", "MUTED"));
  check("a label is named by its name", cell("Charlie Plug", "MUTED") === "Global (label: Garage spares)", cell("Charlie Plug", "MUTED"));
  const keyText = pane.lastElementChild.textContent;
  check("the key sits under the table", keyText.startsWith("Set aside, by reason:"), keyText.slice(0, 40));
  check("the key has all five reasons", ["excluded:", "service:", "disabled:", "duplicate coordinator:", "no entities:"].every((part) => keyText.includes(part)), keyText);
  const mutedChip = [...pane.querySelectorAll(".chip")].find((c) => c.textContent.startsWith("Muted"));
  check("the Muted filter follows the cell and counts the battery-only mute", mutedChip && mutedChip.textContent === "Muted 3", mutedChip && mutedChip.textContent);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
