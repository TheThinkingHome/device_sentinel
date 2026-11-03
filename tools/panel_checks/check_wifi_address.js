// File: tools/panel_checks/check_wifi_address.js, Version: 0.28.0 (2026-11-03)
// Panel checks: a Wi-Fi device's address and access point on its page, and
// devices that share one address on the Recommendations tab (rule UP-19).
// Run with: LC_ALL=en_US.UTF-8 node check_wifi_address.js [path/to/panel.js]
// The harness behaves like Home Assistant's router: whenever the
// address changes, by a link, a pushState or the back button, it hands
// the panel its new route, which is how the panel learns where it is.
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

const DEVICE = payloads._ids.bravo;

const rowOf = (root, label) => {
  const cells = [...root.querySelectorAll(".pane td, .pane th")];
  const at = cells.findIndex((c) => c.textContent === label);
  return at < 0 ? null : cells[at + 1].textContent;
};
const page = (mode, address) => open(`${PREFIX}/device/${DEVICE}`, {
  status: (st) => ({ ...st, dashboard: mode }),
  device: (d) => ({ ...d, identity: { ...d.identity, address } }),
});
const NET = { ip: "192.168.1.40", ip_since: "2026-11-01T19:41:00+00:00", ap: "aa:bb:cc:11:22:33", ap_since: null, shared: false };

(async () => {
  console.log("The device page (rule UP-19)");
  {
    const { root } = await page("advanced", NET);
    const ip = rowOf(root, "IP Address");
    check("Advanced shows the IP Address", ip && ip.startsWith("192.168.1.40"), ip);
    check("with when it last changed", ip && ip.includes("since "), ip);
    check("Advanced shows the Access Point", rowOf(root, "Access Point") === "aa:bb:cc:11:22:33", rowOf(root, "Access Point"));
  }
  {
    const { root } = await page("simple", NET);
    check("Simple leaves both out while nothing is wrong", rowOf(root, "IP Address") === null && rowOf(root, "Access Point") === null);
  }
  {
    const { root } = await page("simple", { ...NET, shared: true });
    const ip = rowOf(root, "IP Address");
    check("Simple shows the address while another device holds it", ip !== null, ip);
    check("with the advice", ip && ip.includes("Reserve an address for each one in your router."), ip);
    check("and still no Access Point", rowOf(root, "Access Point") === null);
  }
  {
    const { root } = await page("advanced", null);
    check("no address, no rows", rowOf(root, "IP Address") === null && rowOf(root, "Access Point") === null);
  }
  console.log("The Recommendations tab");
  {
    const card = { kind: "shared_address", title: "Devices Sharing a Network Address", simple: true, active: 2,
      body: "These devices hold the same network address at the same time.",
      devices: [{ device_id: DEVICE, name: "Porch Plug", area: null, detail: "192.168.1.50", acknowledged: false },
        { device_id: "other", name: "Shed Plug", area: null, detail: "192.168.1.50", acknowledged: false }] };
    const { root } = await open(`${PREFIX}/recommendations?open=shared_address`, {
      recommendations: () => ({ lines: [], devices: [card], closing: "", power: {}, types: { choices: [], other: "Other" } }),
    });
    const art = root.querySelector('article.rec[data-kind="shared_address"]');
    check("has the card", Boolean(art));
    check("each row names the address", art && [...art.querySelectorAll("tr")].every((tr) => tr.textContent.includes("Address 192.168.1.50")), art && art.textContent);
    check("each row can be acknowledged", art && art.querySelectorAll('tr input[type="checkbox"]').length === 2);
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
