// Panel checks: the device page's top half and the Recommendations tab's
// device cards (0.24.9). The Identity section's order and groups, live
// values, sensor links, both rule charts, Previous and Next, and setting
// a device right from a card.
// Run with: LC_ALL=en_US.UTF-8 node check_device_page_layout.js [path/to/panel.js]
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
const ROWS = payloads.devices.rows;
const DEVICE = ROWS[1].device_id;

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


const HOUR = 3600;
const steady = (n, h = 1) => Array.from({ length: n }, (_, i) => (h + (i % 3) * 0.1) * HOUR);
const BOTH = {
  gaps: steady(13).concat([6 * HOUR]), set_aside: [13], scale: null,
  trimmed: 1.2 * HOUR, trimmed_days: 14, lognormal: 1.25 * HOUR, lognormal_days: 40,
  lognormal_gaps: steady(38).concat([6 * HOUR, 5.5 * HOUR]), lognormal_set_aside: [38, 39], in_use: "lognormal",
};
const READINGS = [
  { kind: "battery", entity_id: "sensor.bravo_battery" },
  { kind: "signal", entity_id: "sensor.bravo_linkquality" },
  { kind: "last_seen", entity_id: "sensor.bravo_last_seen" },
];
const NOW = new Date();
const STATES = {
  "sensor.bravo_battery": { state: "19.5", attributes: { unit_of_measurement: "%" }, last_changed: new Date(NOW - 3.2 * 3600e3).toISOString() },
  "sensor.bravo_linkquality": { state: "116", attributes: { unit_of_measurement: "lqi" }, last_changed: new Date(NOW - 4 * 60e3).toISOString() },
  "sensor.bravo_last_seen": { state: new Date(NOW - 4 * 60e3).toISOString(), attributes: {}, last_changed: new Date(NOW - 4 * 60e3).toISOString() },
};

async function open({ tweak = () => {}, states = STATES, path = `${PREFIX}/device/${DEVICE}`, answers = {} } = {}) {
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
  const events = [];
  panel.addEventListener("hass-more-info", (ev) => events.push(ev.detail));
  const hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = message.device_id;
        page.identity.name = (ROWS.find((r) => r.device_id === message.device_id) || {}).name || "Device";
        page.identity.clock = "last_seen";
        page.identity.actions = { area_id: null, name_by_user: null, integration_name: null, labels: [], last_seen_off: false,
          mutes: { everything: { on: false }, freeze: { on: false }, battery: { on: false }, signal: { on: false } } };
        page.readings = JSON.parse(JSON.stringify(READINGS));
        // The History chart's own series sit beside the rule figures in
        // page.rhythm, under the same names the figures once used: the
        // real page carries them, and they blanked both charts (0.24.9).
        const { gaps, set_aside, ...figures } = JSON.parse(JSON.stringify(BOTH));
        page.rhythm = { ...page.rhythm, gaps, set_aside, rules: figures,
          trimmed: Array(87).fill(null), lognormal: Array(87).fill(null), daily: Array(87).fill(3600) };
        page.status.rule = "40-Day Log-Normal Percentile";
        page.status.window = 2 * HOUR;
        tweak(page);
        return page;
      }
      if (kind === "device_choices") return { areas: [], labels: [] };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: JSON.parse(JSON.stringify(states)),
    themes: { darkMode: false },
  };
  panel.hass = hass;
  await settle();
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot, calls, events, hass };
}

const labelsOf = (root) => [...root.querySelectorAll("table.kv tr")].map((tr) =>
  tr.classList.contains("kvgroup") ? `[${tr.textContent}]` : tr.firstChild.textContent);
const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};

(async () => {
  console.log("\nThe device page's Identity section (0.24.9)");
  let { window, root, events, hass, panel } = await open();
  const order = labelsOf(root);
  // Type follows Name since 0.25.1 (Project__Device_Type.md).
  const want = ["Name", "Type", "Device ID", "Area", "Labels", "Manufacturer", "Model", "Model ID", "Hardware version", "Integration",
    "Address", "[Power]", "Battery level", "Battery sensor", "Power", "[Signal]", "Signal", "Signal sensor",
    "[Last seen]", "Last seen", "Last seen sensor", "First seen", "Events seen", "Wait rule", "Muted"];
  const shown = order.filter((l) => l !== "Connects" && l !== "Battery steps");
  check("Rows in the approved order, in three groups", JSON.stringify(shown) === JSON.stringify(want), shown);
  check("No Live readings section, and no Heartbeat row", !/Live readings/.test(root.textContent) && !order.includes("Heartbeat"));
  check("Battery level: the value, then when it changed", /^19\.5% changed 3\.2h ago/.test(rowCell(root, "Battery level").textContent),
    rowCell(root, "Battery level").textContent);
  check("Signal: the value with its unit", /^116 lqi changed 4m ago/.test(rowCell(root, "Signal").textContent), rowCell(root, "Signal").textContent);
  check("Last seen: a time of day", /\d{1,2}:\d\d/.test(rowCell(root, "Last seen").textContent), rowCell(root, "Last seen").textContent);
  const link = rowCell(root, "Battery sensor").querySelector("a.entitylink");
  link.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  check("A sensor link opens its own Home Assistant dialog", events.length === 1 && events[0].entityId === "sensor.bravo_battery", events);
  check("The heartbeat tag sits on the Last seen sensor", /heartbeat$/.test(rowCell(root, "Last seen sensor").textContent),
    rowCell(root, "Last seen sensor").textContent);
  const wait = rowCell(root, "Wait rule");
  check("The Trimmed Maximum button sits in the Wait rule row",
    !!wait && [...wait.querySelectorAll("button")].some((b) => b.textContent === "Use the 14-Day Trimmed Maximum"));
  hass.states["sensor.bravo_battery"] = { ...hass.states["sensor.bravo_battery"], state: "19", last_changed: new Date().toISOString() };
  panel.hass = { ...hass };
  await settle();
  check("A new reading repaints its row", /^19% changed/.test(rowCell(root, "Battery level").textContent), rowCell(root, "Battery level").textContent);

  ({ root } = await open({ tweak: (p) => { p.readings = []; p.identity.clock = "entities"; } }));
  check("No sensors: each row says none", ["Battery level", "Battery sensor", "Signal", "Signal sensor"].every((l) => rowCell(root, l).textContent === "none"));
  check("No Last seen sensor: says how the heartbeat is kept",
    rowCell(root, "Last seen sensor").textContent === "noneheartbeat: updates from its entities", rowCell(root, "Last seen sensor").textContent);

  console.log("\nIts rhythm: both rules");
  ({ root } = await open());
  const titles = [...root.querySelectorAll(".ruletitle")].map((t) => t.textContent);
  check("Both charts, titled with their days, the one in use tagged",
    JSON.stringify(titles) === JSON.stringify(["14-Day Trimmed Maximum", "40-Day Log-Normal Percentilein use"]), titles);
  const charts = [...root.querySelectorAll(".rulechart")];
  check("Fourteen and forty bars", charts.length === 2 && [...charts[0].children].filter((d) => !d.classList.contains("ruleline")).length === 14
    && [...charts[1].children].filter((d) => !d.classList.contains("ruleline")).length === 40);
  check("The set-aside days: hatched, then grey", charts[0].querySelectorAll(".aside").length === 1 && charts[1].querySelectorAll(".grey").length === 2);
  check("The bars are drawn, not blank", [...root.querySelectorAll(".rulechart > div:not(.ruleline)")].some((d) => parseFloat(d.style.height) > 5));
  check("Each chart's red line carries its figure", [...root.querySelectorAll(".ruleline span")].map((s) => s.textContent).join("|") === "72m|75m",
    [...root.querySelectorAll(".ruleline span")].map((s) => s.textContent));
  check("The paragraph on why there are two", /uses whichever of the two is shorter/.test(root.textContent));

  ({ root } = await open({ tweak: (p) => { Object.assign(p.rhythm.rules, { lognormal: null, lognormal_days: null, lognormal_gaps: [], lognormal_set_aside: [], in_use: "trimmed", trimmed_days: 9 }); p.rhythm.gaps = p.rhythm.gaps.slice(-9); p.rhythm.set_aside = []; } }));
  check("A young device: one chart with its own days, no paragraph",
    [...root.querySelectorAll(".ruletitle")].map((t) => t.textContent).join("|") === "9-Day Trimmed Maximumin use" && !/whichever of the two/.test(root.textContent),
    [...root.querySelectorAll(".ruletitle")].map((t) => t.textContent));

  console.log("\nPrevious and Next");
  ({ window, root } = await open({ path: `${PREFIX}/devices` }));
  const second = [...root.querySelectorAll("a")].find((a) => a.textContent === ROWS[1].name);
  second.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await settle();
  const nav = root.querySelector(".prevnext");
  const [prev, next] = nav ? [...nav.querySelectorAll("a")] : [];
  check("From the Devices tab: Previous and Next name their neighbours",
    prev && next && prev.getAttribute("title") === ROWS[0].name && next.getAttribute("title") === ROWS[2].name,
    nav ? nav.innerHTML : null);
  next.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await settle();
  check("Next opens the next device, keeping where it came from",
    window.location.pathname.endsWith(ROWS[2].device_id) && /from=devices/.test(window.location.search), window.location.href);
  ({ root } = await open({ path: `${PREFIX}/device/${ROWS[0].device_id}` }));
  const first = root.querySelector(".prevnext");
  check("At the first device, Previous is greyed", first && first.firstChild.tagName === "SPAN" && first.firstChild.textContent === "\u2039 Previous",
    first ? first.innerHTML : null);

  console.log("\nRecommendations: the device cards");
  const RECS = { lines: [], closing: "Closing.", devices: [
    { kind: "power", title: "Power Not Set", body: "1 device has no battery.", brief: "", devices: [{ device_id: ROWS[1].device_id, name: ROWS[1].name, area: null }] },
    { kind: "last_seen", title: "Last Seen Sensor Switched Off", body: "1 device.", brief: "", devices: [{ device_id: ROWS[2].device_id, name: ROWS[2].name, area: "Kitchen" }] },
    { kind: "area", title: "No Area Assigned", body: "2 devices.", brief: "", devices: [ROWS[0], ROWS[3]].map((r) => ({ device_id: r.device_id, name: r.name, area: null })) },
  ], power: { choices: ["AA", "AAA", "Mains Powered", "USB Powered", "PoE Powered", "Other"], battery_choices: ["AA", "AAA"],
    wired: ["Mains Powered", "USB Powered", "PoE Powered"], other: "Other", quantity: [1, 8] } };
  let calls;
  ({ window, root, calls } = await open({ path: `${PREFIX}/recommendations?open=area`, answers: { recommendations: () => JSON.parse(JSON.stringify(RECS)) } }));
  const arts = [...root.querySelectorAll("article.rec")];
  check("One card per kind, each with its list", arts.map((a) => a.querySelector("h3").textContent).join("|") === "Power Not Set|Last Seen Sensor Switched Off|No Area Assigned");
  check("The brief's link opens its card", arts[2].querySelector("details").hasAttribute("open") && !arts[0].querySelector("details").hasAttribute("open"));
  const sel = arts[0].querySelector('select[aria-label="What powers this device"]');
  sel.value = "AAA"; sel.dispatchEvent(new window.Event("change"));
  const qty = arts[0].querySelector('select[aria-label="How many"]'); qty.value = "2";
  [...arts[0].querySelectorAll("button")].find((b) => b.textContent === "Save").click();
  await settle();
  const sent = calls.find((c) => c.type === "device_sentinel/device_power");
  check("Power is set from the list", sent && sent.device_id === ROWS[1].device_id && sent.choice === "AAA" && sent.quantity === 2, sent);
  ({ root, calls } = await open({ path: `${PREFIX}/recommendations`, answers: { recommendations: () => JSON.parse(JSON.stringify(RECS)) } }));
  [...root.querySelectorAll("article.rec")[1].querySelectorAll("button")].find((b) => b.textContent === "Turn on its Last Seen").click();
  await settle();
  check("Last Seen is switched on from the list", calls.some((c) => c.type === "device_sentinel/device_last_seen" && c.device_id === ROWS[2].device_id));
  ({ window, root } = await open({ path: `${PREFIX}/recommendations`, answers: { recommendations: () => JSON.parse(JSON.stringify(RECS)) } }));
  const areaCard = root.querySelectorAll("article.rec")[2];
  const cardLink = [...areaCard.querySelectorAll("a")].find((a) => a.textContent === ROWS[0].name);
  cardLink.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  await settle();
  const nv = root.querySelector(".prevnext");
  const nexts = nv ? [...nv.querySelectorAll("a")] : [];
  check("From a card, Next walks that card's list", nexts.length === 1 && nexts[0].getAttribute("title") === ROWS[3].name, nv ? nv.innerHTML : null);

  console.log("\nBefore Latest (0.24.9)");
  let r2 = await open({ path: `${PREFIX}/devices` });
  r2.panel._lists = { devices: ["gone-1", ROWS[1].device_id, "gone-2"] };
  r2.window.history.pushState({}, "", `${PREFIX}/device/${ROWS[1].device_id}?from=devices`);
  r2.window.dispatchEvent(new r2.window.Event("location-changed"));
  await settle(); await settle();
  const nav2 = r2.root.querySelector(".prevnext");
  check("A device removed since the list was drawn is stepped over",
    nav2 && [...nav2.querySelectorAll("a")].length === 0 && nav2.textContent === "\u2039 Previous \u00b7 Next \u203a",
    nav2 ? nav2.innerHTML : null);
  ({ root } = await open({ states: { ...STATES, "sensor.bravo_battery": { state: "19.5", attributes: { unit_of_measurement: "%" }, last_changed: "not a date" } } }));
  const level = rowCell(root, "Battery level").textContent;
  check("A time that cannot be read prints no NaN", !/NaN/.test(level) && level.startsWith("19.5%"), level);

  // A cell on Zigbee's raw 0 to 200 scale (ruling #545): LUX Outdoors on
  // the reference house read "182%" on its page while Device Sentinel
  // used 91 (0.25.0).
  const rawStates = { ...STATES, "sensor.bravo_battery": { state: "182", attributes: { unit_of_measurement: "%" }, last_changed: new Date().toISOString() } };
  ({ root } = await open({ states: rawStates, tweak: (p) => { p.readings[0].raw_scale = true; } }));
  const raw = rowCell(root, "Battery level").textContent;
  check("A raw-scale battery reads as raw beside its percentage", raw.startsWith("182 raw (91%)"), raw);
  ({ root } = await open({ states: { ...rawStates, "sensor.bravo_battery": { ...rawStates["sensor.bravo_battery"], state: "181" } },
    tweak: (p) => { p.readings[0].raw_scale = true; } }));
  const odd = rowCell(root, "Battery level").textContent;
  check("An odd raw reading keeps its half point", odd.startsWith("181 raw (90.5%)"), odd);
  ({ root } = await open({ states: rawStates }));
  const plain = rowCell(root, "Battery level").textContent;
  check("A battery not marked raw reads as before", plain.startsWith("182%"), plain);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
