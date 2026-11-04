// File: tools/panel_checks/check_short_drop_outs.js, Version: 0.28.2 (2026-11-04)
// Panel checks: a device with short drop-outs, on its page and on Signal
// Trends (rules SIG-16, SIG-17).
// Run with: LC_ALL=en_US.UTF-8 node check_short_drop_outs.js [path/to/panel.js]
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

(async () => {
  console.log("The device page");
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      device: (d) => ({ ...d, status: { ...d.status, category: "short_drop_outs", flap: "3 in the last 12 hours" } }),
    });
    const said = text(root);
    check("reads Short drop-outs with the count", said.includes("Short drop-outs, 3 in the last 12 hours"), said.slice(0, 200));
  }
  console.log("The Short drop-outs row (rule SIG-16)");
  const drops = { count: 3, longest: 1260, last: "2026-11-01T19:41:00+00:00", hours: 12 };
  const rowText = (root) => {
    const cells = [...root.querySelectorAll(".pane td, .pane th")];
    const at = cells.findIndex((c) => c.textContent === "Short drop-outs");
    return at < 0 ? null : cells[at + 1].textContent;
  };
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      status: (st) => ({ ...st, dashboard: "advanced" }),
      device: (d) => ({ ...d, identity: { ...d.identity, short_drops: drops, dropping_out: false } }),
    });
    const said = rowText(root);
    check("Advanced shows the row", said !== null, said);
    check("with the count, the longest and the last", said && said.startsWith("3 in the last 12 hours, the longest 21m, the last at "), said);
  }
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      status: (st) => ({ ...st, dashboard: "simple" }),
      device: (d) => ({ ...d, identity: { ...d.identity, short_drops: drops, dropping_out: false } }),
    });
    check("Simple leaves it out while the device is not dropping out", rowText(root) === null, rowText(root));
  }
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      status: (st) => ({ ...st, dashboard: "simple" }),
      device: (d) => ({ ...d, identity: { ...d.identity, short_drops: drops, dropping_out: true } }),
    });
    check("Simple shows it while the device keeps dropping out", rowText(root) !== null, rowText(root));
  }
  {
    const { root } = await open(`${PREFIX}/device/${DEVICE}`, {
      status: (st) => ({ ...st, dashboard: "advanced" }),
      device: (d) => ({ ...d, identity: { ...d.identity, short_drops: null, dropping_out: false } }),
    });
    check("no short drops, no row", rowText(root) === null, rowText(root));
  }
  console.log("Signal Trends");
  {
    const { root } = await open(`${PREFIX}/signal-trends`, {
      signal_trends: (s) => ({ ...s, dropping_out: [{ device_id: DEVICE, name: "S73 Door tilt sensor", drops: 5, since: "2026-09-24T12:00:00+00:00", signal: 110 }] }),
    });
    const heads = [...root.querySelectorAll("h3")].map((h) => h.textContent);
    check("has Devices With Short Drop-Outs", heads.some((h) => h.startsWith("Devices With Short Drop-Outs")), heads);
    check("its count column reads LAST 12 HOURS", text(root).includes("LAST 12 HOURS"));
    check("naming the device", text(root).includes("S73 Door tilt sensor"));
    check("with the check to make", text(root).includes("Check its signal and the router it connects through."));
  }
  {
    const { root } = await open(`${PREFIX}/signal-trends`, { signal_trends: (s) => ({ ...s, dropping_out: [] }) });
    check("an empty section says so", text(root).includes("No device has short drop-outs."));
  }
  console.log("The Integrations tab's TROUBLE column");
  for (const [count, words] of [[1, "1 short drop-out"], [2, "2 short drop-outs"]]) {
    const { root } = await open(`${PREFIX}/integrations`, {
      integrations: (r) => ({ ...r, rows: r.rows.map((row) => row.domain === "test" ? { ...row, trouble: { short_drop_outs: count } } : row) }),
    });
    const said = text(root);
    check(`reads "${words}"`, said.includes(words) && (count !== 1 || !said.includes("1 short drop-outs")), said.slice(0, 300));
  }
  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
