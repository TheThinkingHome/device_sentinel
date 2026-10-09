// Panel checks: the Power row (0.24.7, 0.24.8). Words, the source icon in light
// and dark, the library icon's link, the pencil's choices, Save, the
// report button after a save, and Use the library.
// Run with: LC_ALL=en_US.UTF-8 node check_power_row.js [path/to/panel.js]
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

const ACTIONS = {
  area_id: "bedroom", name_by_user: "Button Randy Night Table", integration_name: "0x00158d0001",
  labels: [{ id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }, { id: "bedside", name: "Bedside", meaning: "" }],
  last_seen_off: true,
  mutes: {
    everything: { on: false, source: null, here: false },
    freeze: { on: false, source: null, here: false },
    battery: { on: true, source: "label: Quiet", here: false },
    signal: { on: true, source: "label: Quiet", here: false },
  },
};
const CHOICES = { areas: [{ id: "bedroom", name: "Master Bedroom" }, { id: "laundry", name: "Laundry" }],
  labels: [{ id: "garage", name: "Garage", meaning: "mutes freeze" }, { id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }] };

let current = {};
async function open(answers, power, dark = false) {
  current = { power };
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/device/${DEVICE}`, virtualConsole,
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
      if (answers[kind]) return answers[kind](message);
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = DEVICE;
        page.identity.name = "Button Randy Night Table";
        page.identity.area = "Master Bedroom";
        page.identity.muted = "battery (label: Quiet); signal (label: Quiet)";
        page.identity.actions = JSON.parse(JSON.stringify(ACTIONS));
        page.identity.power = JSON.parse(JSON.stringify(current.power));
        page.status.rule = "14-Day Trimmed Maximum";
        page.status.window = 43200;
        return page;
      }
      if (kind === "device_choices") return CHOICES;
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: dark },
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild && tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const buttonIn = (node, text) => node && [...node.querySelectorAll("button")].find((b) => b.textContent === text);
const click = async (node) => { node.click(); await settle(); };


const CHOICES_P = ["AA", "AAA", "CR2032", "CR2450", "Rechargeable", "CR123A", "CR2", "CR2477", "CR1632", "CR2430",
  "Mains Powered", "USB Powered", "PoE Powered", "Other"];
const block = (over) => Object.assign({
  words: "Not known", source: null, entry: null, library: null,
  library_home: "https://github.com/andrew-codechimp/HA-Battery-Notes", report_url: null,
  choices: CHOICES_P, battery_choices: CHOICES_P.slice(0, 10), mains: "Mains Powered", usb: "USB Powered", wired: ["Mains Powered", "USB Powered", "PoE Powered"],
  other: "Other", quantity: [1, 8],
}, over);
const LIBRARY = block({ words: "CR1632", source: "library", library: "CR1632" });
const OWNER = block({ words: "2× AAA", source: "owner", library: "CR1632",
  entry: { kind: "battery", type: "AAA", quantity: 2, set: "2026-10-05T12:00:00+00:00" },
  report_url: "https://github.com/andrew-codechimp/HA-Battery-Notes/issues/new?template=new_device_request.yaml&battery_type=AAA" });

(async () => {
  console.log("\nThe Power row (0.24.7)");
  let { root, calls } = await open({}, LIBRARY);
  let cell = rowCell(root, "Power");
  check("The row is called Power and Battery type is gone", cell && !rowCell(root, "Battery type"));
  const link = cell && cell.querySelector("a.powericon");
  check("Library: words, then the icon linking to Battery Notes in a new tab",
    cell && cell.textContent.startsWith("CR1632") && link && link.getAttribute("href") === LIBRARY.library_home
      && link.getAttribute("target") === "_blank" && /noopener/.test(link.getAttribute("rel")), cell && cell.innerHTML);
  check("Library: the icon names its source", link && link.getAttribute("title") === "From the Battery Notes library");
  const fill = (r) => [...r.querySelectorAll("rect")].map((x) => x.getAttribute("fill")).join(",");
  check("Library icon: light colours on the light theme", link && fill(link).includes("#4CA8F2"), link && fill(link));
  ({ root } = await open({}, LIBRARY, true));
  const darkLink = rowCell(root, "Power").querySelector("a.powericon");
  check("Library icon: its dark version on the dark theme", darkLink && fill(darkLink).includes("#64B5F6"), darkLink && fill(darkLink));

  ({ root } = await open({}, OWNER, true));
  cell = rowCell(root, "Power");
  const mine = cell.querySelector("span.powericon");
  check("Owner: words, then the shield titled Entered on this page", cell.textContent.startsWith("2× AAA") && mine
    && mine.getAttribute("title") === "Entered on this page");
  check("Owner: the light slate shield on the dark theme", /#B0C4DE/.test(mine.innerHTML), mine.innerHTML);
  check("Owner: no report button until a save", !cell.querySelector("a.chip"));

  ({ root } = await open({}, block({ words: "<img src=x onerror=1>" })));
  cell = rowCell(root, "Power");
  check("Words are shown as text, never markup", cell.textContent.startsWith("<img src=x onerror=1>") && !cell.querySelector("img"));
  check("Not known has no source icon", !cell.querySelector(".powericon"));

  ({ root, calls } = await open({}, LIBRARY));
  await click(rowCell(root, "Power").querySelector('button[aria-label="Change what powers this device"]'));
  cell = rowCell(root, "Power");
  const select = cell.querySelector('select[aria-label="What powers this device"]');
  const options = select ? [...select.options].map((o) => o.textContent) : [];
  check("Pencil: the dropdown offers the ten types, Mains, USB, PoE and Other", options.join("|") === ["Choose…", ...CHOICES_P].join("|"), options);
  const qty = cell.querySelector('select[aria-label="How many"]');
  const other = cell.querySelector('input[aria-label="Battery or power source"]');
  check("Pencil: quantity 1 to 8", qty && [...qty.options].map((o) => o.value).join(",") === "1,2,3,4,5,6,7,8");
  const choose = async (value) => { select.value = value; select.dispatchEvent(new (select.ownerDocument.defaultView.Event)("change")); await settle(); };
  await choose("Mains Powered");
  check("Pencil: no quantity and no text box for Mains Powered", qty.style.display === "none" && other.style.display === "none");
  await choose("PoE Powered");
  check("Pencil: no quantity and no text box for PoE Powered", qty.style.display === "none" && other.style.display === "none");
  await choose("Other");
  check("Pencil: Other shows its text box and a quantity", other.style.display === "" && qty.style.display === "");
  other.value = "9V"; other.dispatchEvent(new (other.ownerDocument.defaultView.Event)("input"));
  qty.value = "2"; qty.dispatchEvent(new (qty.ownerDocument.defaultView.Event)("change"));
  current.power = OWNER;
  await click(buttonIn(cell, "Save"));
  const sent = calls.find((c) => c.type === "device_sentinel/device_power");
  check("Save sends the choice, the text and the quantity", sent && sent.choice === "Other" && sent.other === "9V" && sent.quantity === 2, sent);
  cell = rowCell(root, "Power");
  const report = [...cell.querySelectorAll("a.chip")].find((a) => a.textContent === "Send to Battery Notes");
  check("After a save: Send to Battery Notes opens the filled form in a new tab",
    report && report.getAttribute("href") === OWNER.report_url && report.getAttribute("target") === "_blank", cell.innerHTML);

  ({ root, calls } = await open({}, OWNER));
  await click(rowCell(root, "Power").querySelector('button[aria-label="Change what powers this device"]'));
  const back = buttonIn(rowCell(root, "Power"), "Use the library (CR1632)");
  check("Use the library names what it goes back to", !!back);
  current.power = LIBRARY;
  await click(back);
  const cleared = calls.filter((c) => c.type === "device_sentinel/device_power").pop();
  check("Use the library clears the entry", cleared && cleared.choice === null, cleared);
  check("No report after going back to the library", !rowCell(root, "Power").querySelector("a.chip"));

  // 0.25.1: a device's own entry, under a model with an answer of its own.
  ({ root } = await open({}, Object.assign({}, OWNER, { model_answer: "2× AAA" })));
  await click(rowCell(root, "Power").querySelector('button[aria-label="Change what powers this device"]'));
  check("Clearing its own entry names the model's answer it goes back to",
    !!buttonIn(rowCell(root, "Power"), "Use the model's answer (2× AAA)") && !buttonIn(rowCell(root, "Power"), "Use the library (CR1632)"));

  console.log("\nThe Power row, 0.24.8");
  ({ root } = await open({}, Object.assign({}, OWNER, { set_on: "other", set_on_name: "Button Master Shower", covers: 4 })));
  let whence = rowCell(root, "Power").querySelector(".powerwhence");
  check("Set on another device: names it and how many it covers",
    whence && whence.textContent === "set on Button Master Shower, covers 4 devices of this model", whence && whence.textContent);
  ({ root } = await open({}, Object.assign({}, OWNER, { set_on: DEVICE, set_on_name: "Button Randy Night Table", covers: 4 })));
  whence = rowCell(root, "Power").querySelector(".powerwhence");
  check("Set here on a model of four: says so", whence && whence.textContent === "set here, covers 4 devices of this model",
    whence && whence.textContent);
  ({ root } = await open({}, Object.assign({}, OWNER, { set_on: DEVICE, covers: 1 })));
  check("Set here on a one-off: no extra line", !rowCell(root, "Power").querySelector(".powerwhence"));
  ({ root } = await open({}, LIBRARY));
  check("Library answers carry no set-on line", !rowCell(root, "Power").querySelector(".powerwhence"));
  const css = [...root.querySelectorAll("style")].map((s) => s.textContent).join("\n");
  check("Dropdown choices take the theme's card and text colours",
    /select option, select optgroup \{ background-color: var\(--card-background-color, #ffffff\);\s*color: var\(--primary-text-color, #212121\); \}/.test(css));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
