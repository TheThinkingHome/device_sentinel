// Panel checks for 0.25.6: the update banner glows three times and then
// holds still (ruling #623); the device page's Excluded row and its
// button (ruling #625, from Tim Plas); the Recommendations tab's opening
// line says none of them is required (ruling #626).
// Run with: LC_ALL=en_US.UTF-8 node check_v256.js [path/to/panel.js]
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


const excludedPage = (excluded) => (p) => {
  p.identity.watched = !(excluded.here || excluded.integration);
  if (!p.identity.watched) p.identity.set_aside = "excluded";
  p.identity.actions.excluded = excluded;
};
const buttons = (cell) => (cell ? [...cell.querySelectorAll("button")].map((b) => b.textContent) : []);

(async () => {
  console.log("\nThe update banner glows three times, then holds (0.25.6)");
  let { root, panel, calls } = await open();
  const css = [...root.querySelectorAll("style")].map((s) => s.textContent).join("\n");
  check("The banner glows three times when it appears", /\.updated \{ animation: ds-updated-glow 1\.2s ease-in-out 3; \}/.test(css));
  check("The glow is a keyframe on the border, not blinking text", /@keyframes ds-updated-glow/.test(css) && !/\.updated span \{[^}]*animation/.test(css) && !/text-decoration:\s*blink/.test(css));
  check("A viewer who asked for less motion sees it still",
    /@media \(prefers-reduced-motion: reduce\) \{ \.updated \{ animation: none; \} \}/.test(css));
  panel._showUpdated();
  const banner = root.querySelector(".updated");
  check("The banner itself is unchanged: its words and Reload",
    !!banner && /Device Sentinel was updated\. Reload this page/.test(banner.textContent) && buttons(banner).join() === "Reload");

  console.log("\nThe device page's Excluded row (0.25.6)");
  ({ root, calls } = await open({ tweak: excludedPage({ here: false, integration: false }) }));
  const order = labelsOf(root);
  check("Excluded is the last row, after Muted", order.slice(-2).join() === "Muted,Excluded", order.slice(-3));
  const excludedRow = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild.textContent === "Excluded");
  check("It sits outside the Last seen group", !!excludedRow && !excludedRow.classList.contains("kvsub"));
  let cell = rowCell(root, "Excluded");
  check("A watched device offers Exclude this device", /^no/.test(cell.textContent) && buttons(cell).join() === "Exclude this device", cell.textContent);
  cell.querySelector("button").click();
  await settle();
  cell = rowCell(root, "Excluded");
  check("It asks once, naming the device and what happens at midnight",
    /^Exclude .+\? Device Sentinel will stop watching it and delete what it recorded at the next midnight\. Take it back here before then and nothing is lost\. After that, take it back in Device Sentinel's settings\.Exclude/.test(cell.textContent)
    && buttons(cell).join() === "Exclude,Cancel", cell.textContent);
  check("Asking sends nothing", !calls.some((c) => c.type === "device_sentinel/device_exclude"));
  [...cell.querySelectorAll("button")].find((b) => b.textContent === "Cancel").click();
  await settle();
  check("Cancel goes back to the button", buttons(rowCell(root, "Excluded")).join() === "Exclude this device");
  rowCell(root, "Excluded").querySelector("button").click();
  await settle();
  [...rowCell(root, "Excluded").querySelectorAll("button")].find((b) => b.textContent === "Exclude").click();
  await settle();
  const sent = calls.filter((c) => c.type === "device_sentinel/device_exclude");
  check("Exclude sends the device and on: true", sent.length === 1 && sent[0].on === true && sent[0].device_id === DEVICE, sent);

  ({ root, calls } = await open({ tweak: excludedPage({ here: true, integration: false }) }));
  cell = rowCell(root, "Excluded");
  check("An excluded device says so and offers Stop excluding",
    /^Excluded\. Device Sentinel does not watch it, and deletes what it recorded at the next midnight\. After that this page is gone, and it is taken back in Device Sentinel's settings, Exclusions and Muting\.Stop excluding/.test(cell.textContent)
    && buttons(cell).join() === "Stop excluding", cell.textContent);
  check("The head says it is set aside, excluded", /Set aside: excluded\./.test(root.querySelector(".pagehead").textContent));
  cell.querySelector("button").click();
  await settle();
  const back = calls.filter((c) => c.type === "device_sentinel/device_exclude");
  check("Stop excluding sends on: false", back.length === 1 && back[0].on === false, back);

  ({ root, calls } = await open({ tweak: excludedPage({ here: false, integration: true }) }));
  cell = rowCell(root, "Excluded");
  check("An excluded integration is named, with the way to Settings, and no button",
    /^Its integration is excluded\. Change it in Device Sentinel's settings, Configure, Exclusions and Muting\./.test(cell.textContent)
    && buttons(cell).length === 0 && !!cell.querySelector("a"), cell.textContent);

  ({ root } = await open({ tweak: (p) => {
    excludedPage({ here: false, integration: false })(p);
    p.identity.same_hardware = { watched_through: DEVICE, devices: [{ device_id: DEVICE }, { device_id: "other" }] };
  } }));
  rowCell(root, "Excluded").querySelector("button").click();
  await settle();
  check("With another listing of the same box, the question says it may take over",
    /If another listing of the same hardware can be watched, Device Sentinel watches the hardware through it instead\./.test(rowCell(root, "Excluded").textContent),
    rowCell(root, "Excluded").textContent);

  ({ root } = await open({ tweak: (p) => { delete p.identity.actions.excluded; } }));
  check("A page from an older server still draws the row", buttons(rowCell(root, "Excluded")).join() === "Exclude this device");

  console.log("\nThe Recommendations tab's opening line (0.25.6)");
  ({ root } = await open({ path: `${PREFIX}/recommendations` }));
  const first = root.querySelector("p");
  const count = (payloads.recommendations.lines || []).length + (payloads.recommendations.devices || []).length;
  const word = count === 1 ? "recommendation" : "recommendations";
  check("It says they help it run better and none is required",
    !!first && first.textContent === `${count} ${word} to help Device Sentinel run better. None of them is required.`, first && first.textContent);
  check("Nothing says one matters more than another", !/most important/.test(root.textContent));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
