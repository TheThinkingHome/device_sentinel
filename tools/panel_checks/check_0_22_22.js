// Checks for 0.22.22: each integration with no hardware of its own, and
// each helper linked to a device, opens a page naming the devices it adds
// entities to, and each entity opens Home Assistant's own window. Run with
//   node check_0_22_22.js [path/to/panel.js]
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
  const opened = [];
  window.addEventListener("hass-more-info", (ev) => opened.push(ev.detail.entityId));
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
  return { window, panel, root: panel.shadowRoot, opened };
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

const rider = (domain, name, standing, devices) => ({
  domain, name, standing, first_seen: false, watched: 0, muted: 0, set_aside: 0,
  problems: 0, acknowledged: 0, outages: 0, adds_to: devices.length,
});
const NOTES = [
  { device_id: "d1", name: "Door Entry", area: "Hall", entities: ["sensor.door_entry_battery_plus"] },
  { device_id: "d2", name: "Window Kitchen", area: null, entities: ["sensor.window_kitchen_battery_plus", "sensor.window_kitchen_battery_type"] },
];
const RATE = [{ device_id: "d3", name: "Power Monitor", area: "Kitchen", entities: ["sensor.kitchen_power_rate"] }];
const extra = {
  integrations: (reply) => {
    reply.rows.push(rider("battery_notes", "Battery Notes", "no_hardware", NOTES));
    reply.rows.push(rider("derivative", "Derivative", "helper", RATE));
    return reply;
  },
  integration: () => null,
};
const pageFor = (domain) => ({
  ...extra,
  integration: () => (domain === "derivative"
    ? { domain, name: "Derivative", standing: "helper", rider: true, devices: RATE }
    : { domain, name: "Battery Notes", standing: "no_hardware", rider: true, devices: NOTES }),
});
const rowOf = (root, name) => [...root.querySelectorAll(".pane tbody tr")]
  .find((tr) => tr.cells[0].textContent.startsWith(name));

(async () => {
  console.log("The Integrations tab");
  let { root, window, opened } = await open(`${PREFIX}/integrations`, extra);
  [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("All")).click();
  await settle();
  const notes = rowOf(root, "Battery Notes");
  const rate = rowOf(root, "Derivative");
  check("Battery Notes reads No hardware", notes && notes.cells[1].textContent === "No hardware");
  check("Derivative reads Helper", rate && rate.cells[1].textContent === "Helper", rate && rate.cells[1].textContent);
  check("each opens a page", notes && notes.cells[0].querySelector("a") && rate && rate.cells[0].querySelector("a"));
  const chip = [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("Helper"));
  check("a Helper filter counts it", chip && chip.textContent === "Helper 1", chip && chip.textContent);
  const summary = root.querySelector(".pane > p").textContent;
  check("the count of owners leaves both out", summary.startsWith("2 integrations own devices"), summary);
  // 0.22.24 made the singular read "to a device".
  check("the summary names the helper", summary.includes("1 is a helper you linked to a device."), summary);
  check("the key says what a helper is",
    text(root).includes("Helper: A Home Assistant helper you linked to a device."), text(root).slice(-500));
  check("the key says what no hardware is",
    text(root).includes("No hardware: An add-on with no hardware of its own."), text(root).slice(-500));

  console.log("A helper's page");
  ({ root, window, opened } = await open(`${PREFIX}/integration/derivative?from=integrations`, pageFor("derivative")));
  check("it says it is a helper linked to 1 device",
    text(root).includes("Helper. A Home Assistant helper linked to 1 device."), text(root).slice(0, 300));
  const head = [...root.querySelectorAll(".pane thead th")].map((th) => th.textContent);
  check("its table names device, area and entities", JSON.stringify(head) === JSON.stringify(["DEVICE", "AREA", "ITS ENTITIES"]), head);
  const row = root.querySelector(".pane tbody tr");
  check("the device opens Device Sentinel's page for it",
    row && row.cells[0].querySelector("a") && row.cells[0].querySelector("a").getAttribute("href").startsWith(`${PREFIX}/device/d3`),
    row && row.cells[0].innerHTML);
  check("the area is named", row && row.cells[1].textContent === "Kitchen");
  const button = row && row.cells[2].querySelector("button.entity");
  check("the entity is a control, named by its id", button && button.textContent === "sensor.kitchen_power_rate");
  if (button) button.click();
  await settle();
  check("clicking it asks Home Assistant for the entity's window", JSON.stringify(opened) === JSON.stringify(["sensor.kitchen_power_rate"]), opened);
  check("and the address does not change", where(window) === `${PREFIX}/integration/derivative?from=integrations`, where(window));

  console.log("An add-on's page");
  ({ root } = await open(`${PREFIX}/integration/battery_notes?from=integrations`, pageFor("battery_notes")));
  check("it says it has no hardware, on 2 devices",
    text(root).includes("No hardware. An add-on that puts its entities on 2 devices other integrations own."), text(root).slice(0, 300));
  const rows = [...root.querySelectorAll(".pane tbody tr")];
  check("one row per device", rows.length === 2, rows.length);
  check("every entity of a device is listed", rows[1] && rows[1].querySelectorAll("button.entity").length === 2);
  check("a device with no area leaves the cell empty", rows[1] && rows[1].cells[1].textContent === "");
  const back = backLink(root);
  check("the back link returns to Integrations", back && back.href.startsWith(`${PREFIX}/integrations`), back);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
