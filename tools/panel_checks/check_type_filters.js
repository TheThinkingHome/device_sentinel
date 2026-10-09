// Panel checks: types on Battery Trends, Classification, Devices and Recommendations, and the "null" fix (0.25.3).
// Run with: LC_ALL=en_US.UTF-8 node check_type_filters.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));
const DEVICE = payloads._ids ? payloads._ids.alpha : "alpha";
const CHOICES = ["Button", "CO Alarm", "Camera", "Cover", "Door/Window Sensor", "Leak Sensor", "Motion Sensor", "Plug",
  "Presence Sensor", "Smoke Alarm", "Soil Sensor", "Switch", "Temperature Sensor", "Vibration Sensor",
  "Voice Assistant", "Other"];
const ACTIONS = {
  area_id: null, name_by_user: null, integration_name: "0x00158d0001", labels: [], last_seen_off: false,
  mutes: { everything: { on: false }, freeze: { on: false }, battery: { on: false }, signal: { on: false } },
};
const block = (over) => Object.assign({ words: null, source: null, auto: null, choices: CHOICES, other: "Other" }, over);

let current = {};

async function open(path, overrides) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${path}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  const route = () => ({ prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) });
  window.addEventListener("location-changed", () => {
    if (window.location.pathname.startsWith(PREFIX)) panel.route = route();
  });
  window.document.body.append(panel);
  panel.route = route();
  const calls = [];
  panel.hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (overrides && kind in overrides) return JSON.parse(JSON.stringify(overrides[kind]));
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const text = (node) => (node ? node.textContent.replace(/\s+/g, " ").trim() : "");
const section = (root, title) => {
  const heads = [...root.querySelectorAll("h3.section")];
  const at = heads.find((h) => h.textContent.startsWith(title));
  if (!at) return null;
  let node = at.nextElementSibling;
  while (node && !node.querySelector("table") && node.tagName !== "TABLE"
    && !(node.tagName === "P" && !node.classList.contains("small"))) node = node.nextElementSibling;
  return node;
};
const tableRows = (node) => (node ? [...node.querySelectorAll("tbody tr")] : []);
const headers = (node) => (node ? [...node.querySelectorAll("thead th")].map((th) => th.textContent) : []);
const linkNamed = (root, label) => [...root.querySelectorAll("button.linkbtn")].find((b) => b.textContent === label);
const click = async (node) => { node.click(); await settle(); };
const choose = async (window, select, value) => { select.value = value; select.dispatchEvent(new window.Event("change")); await settle(); };

const cell = (id, name, maker, model, type, level, rate) => ({ device_id: id, name, maker, model, type, level, rate });
const CELLS = [
  cell("m1", "Motion Laundry", "Third Reality", "Wireless motion sensor", "Motion Sensor", 46, -0.3),
  cell("m2", "Motion Closet", "Third Reality", "Wireless motion sensor", "Motion Sensor", 52, -0.3),
  cell("m3", "Motion Hall", "Third Reality", "Wireless motion sensor", "Presence Sensor", 96, -0.1),
  cell("l1", "Leak Sink", "Third Reality", "Water sensor", "Leak Sensor", 75, -0.5),
  cell("d1", "Door Bedroom", "Third Reality", "Door sensor", "Door/Window Sensor", 19, -0.9),
  cell("x1", "Mystery Tag", "Acme", "Tag", null, 88, 0),
];
const row = (c, extra) => Object.assign({ device_id: c.device_id, name: c.name, type: c.type, level: c.level }, extra);
const BATTERY = {
  cells: CELLS.length,
  bank: [0, 1, 0, 0, 1, 1, 0, 1, 1, 1],
  models: [
    { maker: "Third Reality", model: "Door sensor", cells: 1, rate: -0.9, typical: 19, lowest: 19, lowest_name: "Door Bedroom", lowest_id: "d1", types: [["Door/Window Sensor", 1]] },
    { maker: "Third Reality", model: "Water sensor", cells: 1, rate: -0.5, typical: 75, lowest: 75, lowest_name: "Leak Sink", lowest_id: "l1", types: [["Leak Sensor", 1]] },
    { maker: "Third Reality", model: "Wireless motion sensor", cells: 3, rate: -0.3, typical: 52, lowest: 46, lowest_name: "Motion Laundry", lowest_id: "m1", types: [["Motion Sensor", 2], ["Presence Sensor", 1]] },
    { maker: "Acme", model: "Tag", cells: 1, rate: 0, typical: 88, lowest: 88, lowest_name: "Mystery Tag", lowest_id: "x1", types: [["", 1]] },
  ],
  falling: [row(CELLS[4], { weeks: [23.4, 22.9, 22.7, 21.6, 19.4], reading: "falling", pace: 0.9, left: "about 6 months", left_soon: false })],
  low: [],
  steady: [CELLS[0], CELLS[1], CELLS[2], CELLS[3], CELLS[5]].map((c) => row(c, { days: 83, month_drop: 0.5, steps: "Smooth" })),
  unreadable: [],
  no_battery: 44,
  no_battery_types: { "Plug": 10, "Motion Sensor": 1 },
  cell_rows: CELLS,
  threshold: 15,
};

(async () => {
  console.log("\nThe word null never shows (0.25.3)");
  let { root, window } = await open(`${PREFIX}/battery-trends`, { battery_trends: BATTERY });
  check("Battery Trends with nothing that is not a percentage writes no \"null\"", !/null/.test(text(root)), text(root).match(/.{0,40}null.{0,40}/));
  ({ root } = await open(`${PREFIX}/daily-brief`));
  check("A Daily Brief with nothing needing attention writes no \"null\"", !/null/.test(text(root)), text(root).match(/.{0,40}null.{0,40}/));

  console.log("\nBattery Trends by type (0.25.3)");
  ({ root, window } = await open(`${PREFIX}/battery-trends`, { battery_trends: BATTERY }));
  let models = section(root, "By Model");
  check("By Model has a TYPE column after the model", headers(models).slice(0, 3).join("|") === "MAKER AND MODELTYPECELLS".replace(/(MODEL)(TYPE)(CELLS)/, "$1|$2|$3"), headers(models));
  const motion = tableRows(models).find((tr) => tr.firstChild.textContent === "Third Reality Wireless motion sensor");
  check("A model split between types lists each with its count, and keeps all its cells",
    motion && text(motion.children[1]) === "Motion Sensor 2, Presence Sensor 1" && text(motion.children[2]) === "3", motion && text(motion));
  check("A model with no type reads Not known", tableRows(models).some((tr) => text(tr.children[1]) === "Not known"));
  for (const title of ["Falling", "Steady"]) {
    check(`${title} has a TYPE column`, headers(section(root, title)).includes("TYPE"), headers(section(root, title)));
  }
  const picker = root.querySelector('select[aria-label="Show one type"]');
  const options = picker ? [...picker.options].map((o) => o.textContent) : [];
  check("The type list counts each type and the unknown ones", options[0] === "All types 6" && options.includes("Motion Sensor 2")
    && options.includes("Not known 1"), options);

  await click(linkNamed(root, "Motion Sensor"));
  models = section(root, "By Model");
  const steady = section(root, "Steady");
  check("Clicking a type says what is shown, with Show all", text(root.querySelector(".typeshowing")) === "Showing Motion Sensor only. Show all");
  check("By Model counts the model by the type chosen", tableRows(models).length === 1 && text(tableRows(models)[0].children[2]) === "2", tableRows(models).map(text));
  check("The lists show only that type", tableRows(steady).map((tr) => tr.firstChild.textContent).join("|") === "Motion Laundry|Motion Closet", tableRows(steady).map(text));
  const summary = text(root.querySelector("p"));
  check("The summary counts what is shown", summary.startsWith("2 cells report a level. 0 falling, 2 steady, 0 at or under")
    && summary.includes("1 watched device reports no battery"), summary);
  const bands = [...root.querySelectorAll(".band .count")].map((n) => n.textContent);
  check("The bank counts only that type", bands.join(",") === ",,,,1,1,,,,", bands);
  check("Falling says nothing of that type is falling", text(section(root, "Falling")) === "No cell is measurably falling.");

  await click(linkNamed(root, "Show all"));
  await choose(window, root.querySelector('select[aria-label="Show one type"]'), "Presence Sensor");
  models = section(root, "By Model");
  check("Picking from the list narrows the same way; the split model shows its one presence cell",
    tableRows(models).length === 1 && text(tableRows(models)[0].children[2]) === "1" && text(tableRows(section(root, "Steady"))[0].firstChild) === "Motion Hall",
    tableRows(models).map(text));
  await choose(window, root.querySelector('select[aria-label="Show one type"]'), "Not known");
  check("Not known shows the devices with no type", tableRows(section(root, "Steady")).map((tr) => tr.firstChild.textContent).join("|") === "Mystery Tag");

  await click(linkNamed(root, "Show all"));
  await click([...section(root, "Steady").querySelectorAll("thead button")].find((b) => b.textContent === "TYPE"));
  check("Steady sorts by type", tableRows(section(root, "Steady")).map((tr) => text(tr.children[1])).join("|")
    === "Leak Sensor|Motion Sensor|Motion Sensor|Presence Sensor|Not known", tableRows(section(root, "Steady")).map((tr) => text(tr.children[1])));
  check("Every device name and type is text, never markup", !root.querySelector("tbody img"));

  console.log("\nClassification by type (0.25.3)");
  const classification = JSON.parse(JSON.stringify(payloads.classification));
  classification.rows.forEach((r, i) => { r.type = ["Plug", "Plug", "Switch", null][i % 4]; });
  ({ root, window } = await open(`${PREFIX}/classification`, { classification }));
  let table = root.querySelector("table");
  check("TYPE sits after INTEGRATION", headers(table).slice(0, 3).join("|") === "DEVICE|INTEGRATION|TYPE", headers(table));
  check("Every column sorts", headers(table).every((h) => h) && table.querySelectorAll("thead button.sort").length === headers(table).length);
  const plugs = classification.rows.filter((r) => r.type === "Plug");
  await click(linkNamed(root, "Plug"));
  table = root.querySelector("table");
  check("Clicking a type narrows the table", tableRows(table).length === plugs.length, tableRows(table).length);
  const chipText = [...root.querySelectorAll(".chips .chip")].map((b) => b.textContent);
  check("The chips count only that type", chipText[0] === `All ${plugs.length}`
    && chipText[1] === `Watched ${plugs.filter((r) => r.watched).length}`, chipText);
  await click([...root.querySelectorAll("thead button")].find((b) => b.textContent === "DEVICE"));
  const names = tableRows(root.querySelector("table")).map((tr) => tr.firstChild.textContent);
  check("Sorting keeps the type chosen", names.length === plugs.length && names.join("|") === [...names].sort((a, b) => a.toLowerCase() < b.toLowerCase() ? -1 : 1).join("|"), names);

  console.log("\nDevices tab type links (0.25.3)");
  const devices = JSON.parse(JSON.stringify(payloads.devices));
  devices.rows.forEach((r, i) => { r.type = ["Plug", "Switch", null][i % 3]; });
  ({ root } = await open(`${PREFIX}/devices`, { devices }));
  await click(linkNamed(root, "Switch"));
  const shown = tableRows(root.querySelector("table")).map((tr) => text(tr.children[1]));
  check("Clicking a type in a row sets the type filter", shown.length && shown.every((t) => t === "Switch")
    && root.querySelector('select[aria-label="Show one type"]').value === "Switch", shown);
  check("The tab says what is shown", text(root.querySelector(".typeshowing")) === "Showing Switch only. Show all");
  await click(linkNamed(root, "Show all"));
  await click(linkNamed(root, "Not known"));
  check("Not known in a row shows the devices with no type", tableRows(root.querySelector("table")).every((tr) => text(tr.children[1]) === "Not known"));

  console.log("\nRecommendations for types (0.25.3)");
  const recommendations = JSON.parse(JSON.stringify(payloads.recommendations));
  recommendations.types = { choices: ["Plug", "Switch", "Other"], other: "Other" };
  recommendations.devices = [
    { kind: "type", title: "Type Not Set", body: "1 device has no type.", devices: [{ device_id: "x1", name: "Mystery Tag", area: null }] },
    { kind: "mixed_types", title: "Model With More Than One Type", body: "1 model has devices of more than one type.",
      devices: [{ device_id: "m1", name: "Motion Laundry", area: "Laundry", model: "Third Reality Wireless motion sensor", type: "Motion Sensor" },
        { device_id: "m3", name: "Motion Hall", area: "Hall", model: "Third Reality Wireless motion sensor", type: "Presence Sensor" }] },
  ];
  let calls;
  ({ root, window, calls } = await open(`${PREFIX}/recommendations`, { recommendations }));
  const typeCard = root.querySelector('article[data-kind="type"]');
  const select = typeCard && typeCard.querySelector('select[aria-label="What this device is"]');
  const save = typeCard && [...typeCard.querySelectorAll("button")].find((b) => b.textContent === "Save");
  check("Type Not Set lists the device with the type choices", select && [...select.options].map((o) => o.textContent).join("|") === "Choose…|Plug|Switch|Other");
  check("Save waits for a choice", save && save.disabled);
  await choose(window, select, "Other");
  const other = typeCard.querySelector('input[aria-label="Your own words for what this device is"]');
  other.value = "Key Finder";
  await click(save);
  const sent = calls.find((c) => c.type === "device_sentinel/device_type");
  check("Save sends the choice and the words", sent && sent.device_id === "x1" && sent.choice === "Other" && sent.other === "Key Finder", sent);
  const mixed = root.querySelector('article[data-kind="mixed_types"]');
  check("A split model's card names the model and each device's type", text(mixed).includes("Third Reality Wireless motion sensor: Presence Sensor")
    && text(mixed).includes("Motion Laundry"), text(mixed));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
