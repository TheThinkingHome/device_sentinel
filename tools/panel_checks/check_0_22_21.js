// Checks for 0.22.21: an integration with no hardware of its own, as
// Battery Notes is, on the Integrations tab. Run with
//   node check_0_22_21.js [path/to/panel.js]
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
  // The tab opens on Watched; All shows every standing.
  [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("All")).click();
  await settle();
  const notes = rowOf(root, "Battery Notes");
  const cells = notes ? [...notes.cells].map((td) => td.textContent) : [];
  check("its STANDING reads No hardware", cells[1] === "No hardware", cells);
  check("its name opens no page", notes && !notes.cells[0].querySelector("a"), notes && notes.cells[0].innerHTML);
  check("it says how many devices carry its entities", cells[0] && cells[0].includes("on 3 devices"), cells[0]);
  const owner = rowOf(root, "test");
  check("an owning integration still links to its page", owner && !!owner.cells[0].querySelector("a"));
  const chip = [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("No hardware"));
  check("a No hardware filter counts it", chip && chip.textContent === "No hardware 1", chip && chip.textContent);
  const summary = root.querySelector(".pane > p").textContent;
  check("the count of owners leaves it out", summary.startsWith("2 integrations own devices"), summary);
  check("the summary names it as having no hardware",
    summary.includes("1 more has no hardware of its own and only adds entities to other integrations' devices."), summary);
  check("the key names every standing", ["Watched", "Excluded", "Muted", "Service only", "No hardware"]
    .every((s) => text(root).includes(`${s}: `)), text(root).slice(-600));
  check("the key says what no hardware means",
    text(root).includes("No hardware: It has no hardware of its own."), text(root).slice(-400));
  if (chip) chip.click();
  await settle();
  const shown = [...root.querySelectorAll(".pane tbody tr")].map((tr) => tr.cells[0].textContent);
  check("the filter shows it alone", shown.length === 1 && shown[0].startsWith("Battery Notes"), shown);

  console.log("The Integrations tab, with none");
  ({ root } = await open(`${PREFIX}/integrations`));
  const plain = root.querySelector(".pane > p").textContent;
  check("the summary says nothing about no hardware", !plain.includes("no hardware"), plain);
  check("the key is still there", text(root).includes("Standing, by kind:"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
