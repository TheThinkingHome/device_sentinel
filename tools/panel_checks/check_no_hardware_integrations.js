// File: tools/panel_checks/check_no_hardware_integrations.js, Version: 0.27.11 (2026-10-28)
// Panel checks: an integration with no hardware of its own, as Battery
// Notes is, on the Integrations tab.
// Run with: LC_ALL=en_US.UTF-8 node check_no_hardware_integrations.js [path/to/panel.js]
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

const withNotes = {
  integrations: (reply) => {
    reply.rows.push({
      domain: "battery_notes", name: "Battery Notes", standing: "no_hardware",
      first_seen: false, watched: 0, muted: 0, set_aside: 0,
      problems: 0, acknowledged: 0, outages: 0, adds_to: 3,
    });
    return reply;
  },
};
const rowOf = (root, name) => [...root.querySelectorAll(".pane tbody tr")]
  .find((tr) => tr.cells[0].textContent.startsWith(name));

(async () => {
  console.log("The Integrations tab, with Battery Notes");
  let { root } = await open(`${PREFIX}/integrations`, withNotes);
  check("the tab is open", selected(root) === "Integrations", selected(root));
  const notes = rowOf(root, "Battery Notes");
  const cells = notes ? [...notes.cells].map((td) => td.textContent) : [];
  // Under its name, what it is; it owns no device, so it has no buttons
  // and no trouble (rule DASH-16).
  check("under its name it reads No hardware, on 3 devices", cells[0] && cells[0].includes("No hardware, on 3 devices"), cells);
  check("its row has no buttons", notes && notes.cells[1].querySelectorAll("button").length === 0, notes && notes.cells[1].innerHTML);
  check("the words say what no hardware means when hovered",
    notes && /An add-on with no hardware of its own/.test(notes.cells[0].querySelector(".small[title]")?.getAttribute("title") || ""));
  // Its name opens a page of the devices it adds to.
  check("its name opens its page", notes && !!notes.cells[0].querySelector("a"), notes && notes.cells[0].innerHTML);
  const owner = rowOf(root, "test");
  check("an owning integration still links to its page", owner && !!owner.cells[0].querySelector("a"));
  check("an owning integration has its five buttons", owner && owner.cells[1].querySelectorAll("button").length === 5);
  const summary = root.querySelector(".pane > p").textContent;
  const allChip = [...root.querySelectorAll(".chips .chip")].find((c) => c.textContent.startsWith("All "));
  check("the summary opens with the All chip's total", !!allChip && summary.startsWith(`${allChip.textContent.slice(4)} integrations,`), [allChip && allChip.textContent, summary]);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
