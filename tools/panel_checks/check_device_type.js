// Panel checks: the Type row and the Devices tab's Type column and filter (0.25.1).
// Run with: LC_ALL=en_US.UTF-8 node check_device_type.js [path/to/panel.js]
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
async function open(path, type, rows, admin = true) {
  current = { type, rows };
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
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = DEVICE;
        page.identity.name = "Plug Master Router";
        page.identity.actions = admin ? JSON.parse(JSON.stringify(ACTIONS)) : null;
        page.identity.type = JSON.parse(JSON.stringify(current.type));
        return page;
      }
      if (kind === "devices" && current.rows) return { rows: JSON.parse(JSON.stringify(current.rows)) };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild && tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const labels = (root) => [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].map((tr) => tr.firstChild && tr.firstChild.textContent);
const buttonIn = (node, text) => node && [...node.querySelectorAll("button")].find((b) => b.textContent === text);
const click = async (node) => { node.click(); await settle(); };
const DEVICE_PATH = `${PREFIX}/device/${DEVICE}`;

(async () => {
  console.log("\nThe Type row (0.25.1)");
  let { root, calls, window } = await open(DEVICE_PATH, block({ words: "Switch", source: "entities", auto: "Switch" }));
  const order = labels(root);
  check("Type sits right after Name", order.indexOf("Type") === order.indexOf("Name") + 1, order.slice(0, 4));
  let cell = rowCell(root, "Type");
  check("Entities' answer: the words, no icon, a pencil", cell && cell.textContent.startsWith("Switch") && !cell.querySelector(".powericon")
    && cell.querySelector('button[aria-label="Change what this device is"]'), cell && cell.innerHTML);

  ({ root } = await open(DEVICE_PATH, block({ words: "Plug", source: "owner", auto: "Switch", set_on: "other",
    set_on_name: "Plug Laundry Router", covers: 8 })));
  cell = rowCell(root, "Type");
  const shield = cell.querySelector("span.powericon");
  check("Owner's answer: the words, then the shield titled Entered on this page",
    cell.textContent.startsWith("Plug") && shield && shield.getAttribute("title") === "Entered on this page");
  const whence = cell.querySelector(".powerwhence");
  check("Owner's answer set on another device: names it and how many it covers",
    whence && whence.textContent === "set on Plug Laundry Router, covers 8 devices of this model", whence && whence.textContent);

  ({ root, calls, window } = await open(DEVICE_PATH, block({})));
  cell = rowCell(root, "Type");
  const link = buttonIn(cell, "Not known, click to set");
  check("Nothing known: Not known, click to set, and no separate pencil", link && !cell.querySelector("button.edit"), cell && cell.innerHTML);
  await click(link);
  cell = rowCell(root, "Type");
  const select = cell.querySelector('select[aria-label="What this device is"]');
  const options = select ? [...select.options].map((o) => o.textContent) : [];
  check("Click to set opens the choices: the types, then Other", options.join("|") === ["Choose…", ...CHOICES].join("|"), options);
  const other = cell.querySelector('input[aria-label="Your own words for what this device is"]');
  check("The text box has its own label, apart from the list's", !!other && !cell.querySelector('input[aria-label="What this device is"]'));
  const saveBtn = buttonIn(cell, "Save");
  check("Save waits for a choice", saveBtn && saveBtn.disabled === true);
  check("The text box hides until Other is chosen", other && other.style.display === "none");
  select.value = "Other"; select.dispatchEvent(new window.Event("change")); await settle();
  check("Other shows the text box", other.style.display === "");
  check("A choice makes Save pressable", buttonIn(cell, "Save").disabled === false);
  other.value = "Zigbee router"; other.dispatchEvent(new window.Event("input"));
  current.type = block({ words: "Zigbee router", source: "owner" });
  await click(buttonIn(cell, "Save"));
  const sent = calls.find((c) => c.type === "device_sentinel/device_type");
  check("Save sends the choice and the words", sent && sent.choice === "Other" && sent.other === "Zigbee router", sent);
  check("After the save the row reads the owner's words", rowCell(root, "Type").textContent.startsWith("Zigbee router"));

  ({ root, calls } = await open(DEVICE_PATH, block({ words: "Plug", source: "owner", auto: "Switch" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  const back = buttonIn(rowCell(root, "Type"), "Use what its entities say (Switch)");
  check("The owner's answer offers going back, naming what the entities say", !!back);
  current.type = block({ words: "Switch", source: "entities", auto: "Switch" });
  await click(back);
  const cleared = calls.filter((c) => c.type === "device_sentinel/device_type").pop();
  check("Going back clears the answer", cleared && cleared.choice === null, cleared);

  ({ root } = await open(DEVICE_PATH, block({ words: "Switch", source: "entities", auto: "Switch" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  const picked = rowCell(root, "Type").querySelector('select[aria-label="What this device is"]');
  check("The pencil starts on the type shown, even one its entities gave", picked && picked.value === "Switch", picked && picked.value);

  ({ root } = await open(DEVICE_PATH, block({ words: "Lamp", source: "owner", auto: "Switch", model_answer: "Plug" })));
  await click(rowCell(root, "Type").querySelector('button[aria-label="Change what this device is"]'));
  check("Clearing its own answer names the model's answer it goes back to",
    !!buttonIn(rowCell(root, "Type"), "Use the model's answer (Plug)") && !buttonIn(rowCell(root, "Type"), "Use what its entities say (Switch)"));

  ({ root } = await open(DEVICE_PATH, block({ words: "<img src=x onerror=1>", source: "owner" })));
  cell = rowCell(root, "Type");
  check("Words are shown as text, never markup", cell.textContent.startsWith("<img src=x onerror=1>") && !cell.querySelector("img"));

  ({ root } = await open(DEVICE_PATH, block({}), null, false));
  cell = rowCell(root, "Type");
  check("Without the right to change it: plain Not known, nothing to click",
    cell && cell.textContent === "Not known" && !cell.querySelector("button"), cell && cell.innerHTML);

  console.log("\nThe Devices tab's Type column and filter (0.25.1)");
  const base = JSON.parse(JSON.stringify(payloads.devices.rows[0]));
  const row = (id, name, type) => Object.assign({}, base, { device_id: id, name, type, problem: "", muted: "" });
  const rows = [row("a", "Leak Kitchen Sink", "Leak Sensor"), row("b", "Plug Master Router", "Switch"),
    row("c", "Router Aotec Zi", null), row("d", "Leak Washing Machine", "Leak Sensor")];
  ({ root, window } = await open(`${PREFIX}/devices`, block({}), rows));
  const heads = [...root.querySelectorAll("thead th")].map((th) => th.textContent);
  check("TYPE is the second column", heads[1] === "TYPE", heads);
  const typeCells = () => [...root.querySelectorAll("tbody tr")].map((tr) => tr.children[1].textContent);
  check("Each row shows its type, Not known where there is none",
    typeCells().join("|") === "Leak Sensor|Switch|Not known|Leak Sensor", typeCells());
  const filter = root.querySelector('select[aria-label="Show one type"]');
  const offered = filter ? [...filter.options].map((o) => o.textContent) : [];
  check("The filter offers each type present with its count, then Not known",
    offered.join("|") === "All types|Leak Sensor 2|Switch 1|Not known 1", offered);
  filter.value = "Leak Sensor"; filter.dispatchEvent(new window.Event("change")); await settle();
  check("Choosing a type shows only those devices", typeCells().join("|") === "Leak Sensor|Leak Sensor", typeCells());
  const again = root.querySelector('select[aria-label="Show one type"]');
  check("The filter keeps its choice after repainting", again && again.value === "Leak Sensor");
  again.value = "Not known"; again.dispatchEvent(new window.Event("change")); await settle();
  check("Not known shows the devices nothing could name", [...root.querySelectorAll("tbody tr")].map((tr) => tr.children[0].textContent).join("|") === "Router Aotec Zi");
  const sortType = [...root.querySelectorAll("thead button.sort")].find((b) => b.textContent === "TYPE");
  const all = root.querySelector('select[aria-label="Show one type"]');
  all.value = ""; all.dispatchEvent(new window.Event("change")); await settle();
  await click([...root.querySelectorAll("thead button.sort")].find((b) => b.textContent === "TYPE"));
  check("TYPE sorts, Not known last", typeCells().join("|") === "Leak Sensor|Leak Sensor|Switch|Not known", typeCells());
  check("The sort button exists", !!sortType);

  const named = [row("a", "Lamp Office", "lamp"), row("b", "Plug Master Router", "Switch"), row("c", "Hub", "Button"),
    row("d", "Leak Washing Machine", "Leak Sensor")];
  ({ root, window } = await open(`${PREFIX}/devices`, block({}), named));
  const listed = [...root.querySelector('select[aria-label="Show one type"]').options].map((o) => o.textContent);
  check("Types list as people read them, an owner's lower case among the rest",
    listed.join("|") === "All types|Button 1|lamp 1|Leak Sensor 1|Switch 1|Not known 0", listed);
  let panel;
  ({ root, window, panel } = await open(`${PREFIX}/devices`, block({}), rows));
  const pick = root.querySelector('select[aria-label="Show one type"]');
  pick.value = "Not known"; pick.dispatchEvent(new window.Event("change")); await settle();
  check("Not known shows the one device with no type", root.querySelectorAll("tbody tr").length === 1);
  panel._snapshot.devices.rows = JSON.parse(JSON.stringify(named));
  panel._paintDevices();
  const after = root.querySelector('select[aria-label="Show one type"]');
  check("Once every device has a type, Not known goes back to All types",
    after.value === "" && root.querySelectorAll("tbody tr").length === 4, [after.value, root.querySelectorAll("tbody tr").length]);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
