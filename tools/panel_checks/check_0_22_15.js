// Checks for 0.22.15: each page leads back to the page it came from, and
// Print sits beside the gear. Run with
//   LC_ALL=en_US.UTF-8 node check_0_22_14.js [path/to/panel.js]
// The harness behaves like Home Assistant's router: whenever the
// address changes, by a link, a pushState or the back button, it hands
// the panel its new route, which is how the panel learns where it is.
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const BRAVO = payloads._ids.bravo;
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

async function open(address) {
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
      return JSON.parse(JSON.stringify(payloads[kind]));
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

const toolbarPrint = (root) => root.querySelector(".toolbar .print");
const rowPrint = (root) => [...root.querySelectorAll(".actions button")].find((b) => b.textContent === "Print");
const clickName = async (root, name) => {
  [...root.querySelectorAll(".pane tbody a")].find((a) => a.textContent === name).click();
  await settle();
};

(async () => {
  console.log("The chain: Classification, then an integration, then a device");
  let { window, root } = await open(`${PREFIX}/classification`);
  await clickName(root, "test");
  check("the integration page leads back to Classification",
    JSON.stringify(backLink(root)) === JSON.stringify({ text: "\u2039 Classification", href: `${PREFIX}/classification` }), backLink(root));
  await clickName(root, "Bravo Phone");
  check("the device page leads back to the integration page, named for it",
    backLink(root) && backLink(root).text === "\u2039 test", backLink(root));
  check("and its link goes to that exact page, origin and all",
    backLink(root) && backLink(root).href === `${PREFIX}/integration/test?from=classification`, backLink(root));
  check("Classification stays the highlighted tab", selected(root) === "Classification", selected(root));
  const deviceAddress = where(window);
  root.querySelector(".pane > p:first-child a").click();
  await settle();
  check("following the link lands on the integration page", where(window) === `${PREFIX}/integration/test?from=classification`, where(window));
  check("which still leads back to Classification", backLink(root) && backLink(root).text === "\u2039 Classification", backLink(root));

  console.log("The chain survives a reload");
  ({ window, root } = await open(deviceAddress));
  check("reloaded, the device page still leads back to the integration page",
    backLink(root) && backLink(root).text === "\u2039 test" && backLink(root).href === `${PREFIX}/integration/test?from=classification`, backLink(root));
  check("and Classification is still the highlighted tab", selected(root) === "Classification", selected(root));

  console.log("The browser agrees with the page");
  ({ window, root } = await open(`${PREFIX}/classification`));
  await clickName(root, "test");
  await clickName(root, "Bravo Phone");
  window.history.back();
  await settle();
  check("back from the device returns to the integration page", where(window) === `${PREFIX}/integration/test?from=classification`, where(window));
  window.history.back();
  await settle();
  check("and back again returns to Classification", where(window) === `${PREFIX}/classification` && selected(root) === "Classification", [where(window), selected(root)]);

  console.log("An integration opened from a device page");
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}?from=devices`));
  const onLink = [...root.querySelectorAll(".pane a")].find((a) => a.textContent === "test");
  onLink.click();
  await settle();
  check("the integration page leads back to the device, named for it", backLink(root) && backLink(root).text === "\u2039 Bravo Phone", backLink(root));
  check("Devices, where the chain began, is the highlighted tab", selected(root) === "Devices", selected(root));

  console.log("One step from a tab still names the tab");
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}?from=battery-trends`));
  check("a device opened from Battery Trends leads back to it", backLink(root) && backLink(root).text === "\u2039 Battery Trends" && backLink(root).href === `${PREFIX}/battery-trends`, backLink(root));

  console.log("Origins that name nothing");
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}?from=${encodeURIComponent("/nowhere/at/all")}`));
  check("an origin that is no page falls back to Devices", backLink(root) && backLink(root).text === "\u2039 Devices", backLink(root));

  console.log("Print beside the gear");
  ({ window, root } = await open(PREFIX));
  const icon = toolbarPrint(root);
  check("a print icon is in the toolbar", icon !== null);
  check("it is labelled Print this page", icon && icon.getAttribute("aria-label") === "Print this page" && icon.getAttribute("title") === "Print this page");
  check("it sits just before the gear", icon && icon.nextElementSibling === root.querySelector(".toolbar .gear"));
  check("the button row no longer has a Print button", rowPrint(root) === undefined);
  if (icon) icon.click();
  const frame = window.document.querySelector("iframe");
  check("pressing it prints the page, with its heading", frame !== null && /^Device Sentinel: Daily Brief$/.test(frame.contentDocument.querySelector(".printhead h1").textContent),
    frame && frame.contentDocument.querySelector(".printhead h1").textContent);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
