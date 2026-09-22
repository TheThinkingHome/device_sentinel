// Checks for 0.22.14: every tab has its own address. Run with
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

const ADDRESSES = [
  ["Daily Brief", PREFIX],
  ["Problem List", `${PREFIX}/problem-list`],
  ["Battery Trends", `${PREFIX}/battery-trends`],
  ["Signal Trends", `${PREFIX}/signal-trends`],
  ["Classification", `${PREFIX}/classification`],
  ["Integrations", `${PREFIX}/integrations`],
  ["Devices", `${PREFIX}/devices`],
  ["Recommendations", `${PREFIX}/recommendations`],
];

(async () => {
  console.log("Opening");
  let { window, root } = await open(PREFIX);
  check("the bare address opens the Daily Brief", selected(root) === "Daily Brief", selected(root));

  console.log("Arriving from the sidebar");
  ({ window, root } = await open(`${PREFIX}/battery-trends`));
  // Leave for another page, then come back by the sidebar link, which
  // is the bare address. Home Assistant keeps the panel alive between.
  window.history.pushState(null, "", "/config/integrations");
  window.dispatchEvent(new window.CustomEvent("location-changed"));
  window.history.pushState(null, "", PREFIX);
  window.dispatchEvent(new window.CustomEvent("location-changed"));
  await settle();
  check("the sidebar link opens the Daily Brief, whatever tab was left open", selected(root) === "Daily Brief", selected(root));

  console.log("Every tab has its own address");
  for (const [name, address] of ADDRESSES) {
    ({ window, root } = await open(address));
    check(`${address} opens ${name}, as a reload would`, selected(root) === name, selected(root));
  }
  ({ window, root } = await open(PREFIX));
  for (const [name, address] of ADDRESSES.slice(1)) {
    clickTab(root, name);
    await settle();
    check(`clicking ${name} moves the address to ${address}`, where(window) === address, where(window));
  }
  clickTab(root, "Daily Brief");
  await settle();
  check("clicking Daily Brief returns to the bare address", where(window) === PREFIX, where(window));

  console.log("Back from a device page");
  ({ window, root } = await open(`${PREFIX}/classification`));
  const link = [...root.querySelectorAll(".pane tbody a")].find((a) => a.textContent === "Bravo Phone");
  link.click();
  await settle();
  check("a device opened from Classification remembers where it came from",
    where(window) === `${PREFIX}/device/${BRAVO}?from=classification`, where(window));
  check("the page's own back link names Classification", backLink(root) && backLink(root).text === "\u2039 Classification", backLink(root));
  check("and leads to Classification's address", backLink(root) && backLink(root).href === `${PREFIX}/classification`, backLink(root));
  check("Classification stays the highlighted tab", selected(root) === "Classification", selected(root));
  window.history.back();
  await settle();
  check("the browser's back button returns to Classification", selected(root) === "Classification" && where(window) === `${PREFIX}/classification`, [selected(root), where(window)]);

  console.log("A device page reloaded, or opened from a link");
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}?from=battery-trends`));
  check("reloaded, it still names where it came from", backLink(root) && backLink(root).text === "\u2039 Battery Trends", backLink(root));
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}`));
  check("with no origin, its back link names Devices", backLink(root) && backLink(root).text === "\u2039 Devices", backLink(root));
  check("and leads to the Devices address", backLink(root) && backLink(root).href === `${PREFIX}/devices`, backLink(root));

  console.log("Back from an integration page");
  ({ window, root } = await open(`${PREFIX}/classification`));
  const integration = [...root.querySelectorAll(".pane tbody a")].find((a) => a.textContent === "test");
  integration.click();
  await settle();
  check("an integration opened from Classification remembers where it came from",
    where(window) === `${PREFIX}/integration/test?from=classification`, where(window));
  check("its back link names Classification", backLink(root) && backLink(root).text === "\u2039 Classification", backLink(root));
  ({ window, root } = await open(`${PREFIX}/integration/test`));
  check("with no origin, its back link names Integrations", backLink(root) && backLink(root).text === "\u2039 Integrations", backLink(root));

  console.log("Addresses that name nothing");
  ({ window, root } = await open(`${PREFIX}/no-such-tab`));
  check("an unknown address falls back to the Daily Brief", selected(root) === "Daily Brief", selected(root));
  ({ window, root } = await open(`${PREFIX}/device/${BRAVO}?from=no-such-tab`));
  check("an unknown origin falls back to Devices", backLink(root) && backLink(root).text === "\u2039 Devices", backLink(root));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
