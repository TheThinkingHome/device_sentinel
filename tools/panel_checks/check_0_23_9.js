// Checks for 0.23.9: the Connects line on a device's page. Run with
//   node check_0_23_9.js [path/to/panel.js]
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
const DEVICE = payloads._ids ? payloads._ids.alpha : null;

// Tim Plas's S63 of 24 September: steady, then speeding up.
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
      fit: { knee: true, knee_ago: 19, before: 0.5, pace: 5.9, line: [[38, 74.6], [19, 73.4], [0, 57.2]] },
      sentence: "Accelerating: steady until about Sep 4, then falling about 5.9 points a week since.",
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
    page.falling = [{
      device_id: DEVICE, name: "Garage Door", level: 57.5, since: null, steps: "Smooth",
      weeks: [74.64, 73.71, 71.21, 66.0, 59.64], reading: "accelerating", pace: 5.9,
      left: "about 3 months", left_soon: false,
    }];
    return page;
  },
};

const withConnects = (words) => ({
  device: (page) => {
    page.identity = { ...page.identity, connects: words };
    return page;
  },
});
const rowFor = (root, label) => [...root.querySelectorAll("table.kv tr")]
  .find((tr) => tr.children[0] && tr.children[0].textContent === label);

(async () => {
  console.log("A cloud device's page");
  const cloud = "Through the maker's cloud. It stops reporting if their servers or your internet go down.";
  const one = await open(`${PREFIX}/device/${DEVICE}`, withConnects(cloud));
  const row = rowFor(one.root, "Connects");
  check("a Connects row is shown", Boolean(row));
  check("with the words for its kind", row && row.children[1].textContent === cloud, row && row.children[1].textContent);
  const integration = rowFor(one.root, "Integration");
  check("right after the Integration row", Boolean(integration) && integration.nextElementSibling === row);

  console.log("A device whose integration declares nothing");
  const two = await open(`${PREFIX}/device/${DEVICE}`, withConnects(null));
  check("no Connects row", !rowFor(two.root, "Connects"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
