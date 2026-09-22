// Checks for 0.22.16: every mute named where a device is, and the
// Battery Trends advice pointing at a control that exists. Run with
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

const text = (root) => root.querySelector(".pane").textContent;

(async () => {
  console.log("A device's own page");
  let { window, root } = await open(`${PREFIX}/device/${BRAVO}?from=devices`);
  check("its standing names every mute, freeze before battery",
    text(root).includes("Watched, muted: freeze (device); battery (device)"), text(root).slice(0, 300));

  console.log("The Devices tab");
  ({ window, root } = await open(`${PREFIX}/devices`));
  const row = [...root.querySelectorAll(".pane tbody tr")].find((tr) => tr.cells[0].textContent === "Bravo Phone");
  const cells = row ? [...row.cells].map((td) => td.textContent) : [];
  check("the STANDING column names every mute", cells.includes("Muted: freeze (device); battery (device)"), cells);
  const chip = [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("Muted"));
  check("its Muted filter counts the device muted for freeze and battery only", chip && chip.textContent === "Muted 3", chip && chip.textContent);

  console.log("An integration's page");
  ({ window, root } = await open(`${PREFIX}/integration/test?from=integrations`));
  check("its device list names every mute", text(root).includes("Watched, muted: freeze (device); battery (device)")
    && text(root).includes("Watched, muted: Global (device); battery (device)"), text(root).slice(0, 400));

  console.log("Battery Trends");
  ({ window, root } = await open(`${PREFIX}/battery-trends`));
  check("the Not a Percentage note points to Configure, Low Battery",
    text(root).includes("To take them out of these lists, mute them for battery in Configure, Low Battery."), text(root).slice(-300));
  check("and no longer to a Battery switch that does not exist", !text(root).includes("Turn Battery off"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
