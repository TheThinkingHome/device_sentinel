// File: tools/panel_checks/check_after_a_restart.js, Version: 0.29.2 (2026-11-15)
// Panel checks: how a device's model is read after a restart (rule
// WATCH-12). The After a restart row with its three choices, the two
// notes with their counts and buttons, and the two Recommendations
// cards, in Simple and Advanced.
// Run with: LC_ALL=en_US.UTF-8 node check_after_a_restart.js [path/to/panel.js]
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
    battery: { on: true, source: "label: Quiet", here: false, labels: ["quiet"] },
    signal: { on: true, source: "label: Quiet", here: false, labels: ["quiet"] },
  },
};
const CHOICES = { areas: [{ id: "bedroom", name: "Master Bedroom" }, { id: "laundry", name: "Laundry" }],
  labels: [{ id: "garage", name: "Garage", meaning: "mutes freeze" }, { id: "quiet", name: "Quiet", meaning: "mutes battery and signal" }] };

async function open(answers, tweak = () => {}, simple = false) {
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
        page.status.rule = "14-Day Trimmed Maximum";
        page.status.window = 43200;
        tweak(page);
        return page;
      }
      if (kind === "status" && simple) {
        const status = JSON.parse(JSON.stringify(payloads.status));
        status.dashboard = "simple";
        return status;
      }
      if (kind === "device_choices") return CHOICES;
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
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


const labelsOf = (root) => [...root.querySelectorAll("table.kv tr")].map((tr) =>
  tr.classList.contains("kvgroup") ? `[${tr.textContent}]` : tr.firstChild.textContent);
const buttons = (cell) => (cell ? [...cell.querySelectorAll("button")].map((b) => b.textContent) : []);

const ROW = {
  name: "After a restart", integration: "Shelly", listed: true, can_set: true, mode: null,
  words: "Shelly devices can report cached values after a restart, so this device is reported back only when one of its values changes.",
  note: null,
};
const BACK = {
  kind: "back", name: "Back after a restart?",
  text: "Home Assistant restarted while this device was down. Its values are back, but Device Sentinel can't tell whether the device sent them or its integration restored its cached values.",
  count: "This has happened to this device 3 times since Nov 2, and to other Shelly H&T devices 5 times.",
  buttons: [
    { action: "back", label: "It's Back", under: "Removes this device from the Problem List. If it happens again after a restart, you'll see this note again." },
    { action: "back_live", label: "It's Back, This Model Reports Live", under: "All Shelly H&T devices will be reported back as their values return after a restart." },
  ],
};
const FROZEN = {
  kind: "frozen", name: "Frozen since a restart?",
  text: "This device was down when Home Assistant restarted. It was reported back when its values returned, but none of its values has changed since, and it is now listed frozen.",
  count: "This is the first time this has happened to this device.",
  buttons: [{ action: "cached", label: "This Model Reports Cached Values After a Restart", under: "All Sonos One devices will be reported back only when one of their values changes after a restart." }],
};
const withRow = (change = {}) => (p) => { p.identity.actions.restart = { ...ROW, ...change }; };
const sent = (calls, type) => calls.filter((m) => m.type === `device_sentinel/${type}`);
const pressed = (cell) => (cell ? [...cell.querySelectorAll('button[aria-pressed="true"]')].map((b) => b.textContent) : []);

(async () => {
  console.log("The After a restart row");
  let { root, calls } = await open({}, withRow());
  let cell = rowCell(root, "After a restart");
  check("the row is under Actions with three choices", JSON.stringify(buttons(cell)) === JSON.stringify(["Same as Shelly", "Reports live", "Reports cached values"]), buttons(cell));
  check("the choice in use is highlighted", JSON.stringify(pressed(cell)) === JSON.stringify(["Same as Shelly"]), pressed(cell));
  check("the sentence for it is under the choices", cell.textContent.includes("Shelly devices can report cached values after a restart"), cell.textContent);
  check("no note while nothing is wrong", !rowCell(root, "Back after a restart?") && !rowCell(root, "Frozen since a restart?"));
  await click(buttonIn(cell, "Reports live"));
  let acts = sent(calls, "device_restart");
  check("a choice sets the model", acts.length === 1 && acts[0].mode === "live" && acts[0].device_id === DEVICE, acts);
  ({ root, calls } = await open({}, withRow({ mode: "live", words: "All Shelly Plus Plug devices will be reported back as their values return after a restart." })));
  cell = rowCell(root, "After a restart");
  check("a model's own setting is the one highlighted", JSON.stringify(pressed(cell)) === JSON.stringify(["Reports live"]), pressed(cell));
  await click(buttonIn(cell, "Reports live"));
  check("the choice in use sends nothing", sent(calls, "device_restart").length === 0);
  await click(buttonIn(cell, "Same as Shelly"));
  acts = sent(calls, "device_restart");
  check("Same as goes back to the integration's setting", acts.length === 1 && acts[0].mode === "same", acts);
  // A model on Device Sentinel's own list: its first choice goes back
  // to Device Sentinel's setting, not the integration's (rule WATCH-12).
  ({ root, calls } = await open({}, withRow({ listed: false, same_label: "Device Sentinel's Setting",
    words: "Device Sentinel lists Shelly H&T devices as reporting cached values after a restart, so this device is reported back only when one of its values changes." })));
  cell = rowCell(root, "After a restart");
  check("a listed model's first choice is Device Sentinel's Setting", JSON.stringify(buttons(cell)) === JSON.stringify(["Device Sentinel's Setting", "Reports live", "Reports cached values"]), buttons(cell));
  check("it is the one highlighted", JSON.stringify(pressed(cell)) === JSON.stringify(["Device Sentinel's Setting"]), pressed(cell));
  check("its sentence names Device Sentinel's list", cell.textContent.includes("Device Sentinel lists Shelly H&T devices as reporting cached values"), cell.textContent);
  ({ root, calls } = await open({}, withRow({ can_set: false })));
  cell = rowCell(root, "After a restart");
  await click(buttonIn(cell, "Reports cached values"));
  check("a device that names no model cannot be set", sent(calls, "device_restart").length === 0 && buttonIn(cell, "Reports live").disabled);
  ({ root } = await open({}, (p) => { p.identity.actions.restart = null; }));
  check("no row for a device judged by last seen", !rowCell(root, "After a restart"));
  ({ root } = await open({ device_restart: () => { throw { code: "refused", message: "Choose from the three choices." }; } }, withRow()));
  await click(buttonIn(rowCell(root, "After a restart"), "Reports live"));
  check("a refusal is said under the row", rowCell(root, "After a restart").textContent.includes("Choose from the three choices."), rowCell(root, "After a restart").textContent);

  console.log("\nBack after a restart?");
  ({ root, calls } = await open({}, withRow({ note: BACK })));
  cell = rowCell(root, "Back after a restart?");
  check("the note has its own row, above the choices", Boolean(cell) && labelsOf(root).indexOf("Back after a restart?") < labelsOf(root).indexOf("After a restart"), labelsOf(root));
  check("it says what happened and how often", cell.textContent.includes("Home Assistant restarted while this device was down.") && cell.textContent.includes("3 times since Nov 2, and to other Shelly H&T devices 5 times."), cell.textContent);
  check("it offers the safe choice and the lasting one", JSON.stringify(buttons(cell)) === JSON.stringify(["It's Back", "It's Back, This Model Reports Live"]), buttons(cell));
  check("each button says what it does", cell.textContent.includes("Removes this device from the Problem List.") && cell.textContent.includes("All Shelly H&T devices will be reported back"), cell.textContent);
  await click(buttonIn(cell, "It's Back"));
  acts = sent(calls, "device_confirm_back");
  check("It's Back confirms the device alone", acts.length === 1 && acts[0].live === false && acts[0].device_id === DEVICE, acts);
  ({ root, calls } = await open({}, withRow({ note: BACK })));
  await click(buttonIn(rowCell(root, "Back after a restart?"), "It's Back, This Model Reports Live"));
  acts = sent(calls, "device_confirm_back");
  check("the second button also sets the model", acts.length === 1 && acts[0].live === true, acts);

  console.log("\nFrozen since a restart?");
  ({ root, calls } = await open({}, withRow({ integration: "Sonos", listed: false, note: FROZEN })));
  cell = rowCell(root, "Frozen since a restart?");
  check("the second note has its own row", Boolean(cell) && cell.textContent.includes("it is now listed frozen") && cell.textContent.includes("This is the first time this has happened to this device."), cell && cell.textContent);
  check("its one button", JSON.stringify(buttons(cell)) === JSON.stringify(["This Model Reports Cached Values After a Restart"]), buttons(cell));
  await click(buttonIn(cell, "This Model Reports Cached Values After a Restart"));
  acts = sent(calls, "device_restart");
  check("it sets the model to report cached values", acts.length === 1 && acts[0].mode === "cached", acts);

  console.log("\nIn Simple");
  ({ root } = await open({}, withRow({ note: BACK }), true));
  check("this is Simple: no Exclude this device", !rowCell(root, "Excluded"), labelsOf(root));
  check("the row and the note show in Simple too", Boolean(rowCell(root, "After a restart")) && Boolean(rowCell(root, "Back after a restart?")), labelsOf(root));

  console.log("\nThe Recommendations cards");
  const cards = () => ({
    recommendations: () => ({
      lines: [], closing: "", power: {}, types: { choices: [], other: "Other" }, networks: [],
      devices: [
        { kind: "restart_live", title: "Models That May Report Live", body: "", active: 1, simple: true,
          devices: [{ device_id: DEVICE, name: "Shelly H&T", area: null, acknowledged: false, mode: "live",
            text: "Shelly H&T, 4 devices. 3 times since Nov 2, a Shelly H&T was listed as down after a restart with its values back, and was marked back each time.",
            button: "Set to Reports Live", under: "All Shelly H&T devices will be reported back as their values return after a restart." }] },
        { kind: "restart_cached", title: "Models That May Report Cached Values", body: "", active: 1, simple: true,
          devices: [{ device_id: DEVICE, name: "Sonos One", area: null, acknowledged: false, mode: "cached",
            text: "Sonos One, 2 devices. 3 times since Nov 2, a Sonos One was reported back after a restart, then later listed frozen with none of its values changed.",
            button: "Set to Reports Cached Values", under: "All Sonos One devices will be reported back only when one of their values changes after a restart." }] },
      ],
    }),
  });
  for (const simple of [false, true]) {
    const where = simple ? "Simple" : "Advanced";
    const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", { runScripts: "outside-only", url: `http://ha.local${PREFIX}/recommendations`, virtualConsole: new VirtualConsole() });
    const { window } = dom;
    window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
    window.eval(fs.readFileSync(PANEL, "utf8"));
    const panel = window.document.createElement("device-sentinel-panel");
    const route = () => ({ prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) });
    window.document.body.append(panel);
    panel.route = route();
    const seen = [];
    const answers = cards();
    panel.hass = {
      callWS: async (message) => {
        seen.push(message);
        const kind = message.type.replace("device_sentinel/", "");
        if (answers[kind]) return answers[kind](message);
        if (kind === "status") {
          const status = JSON.parse(JSON.stringify(payloads.status));
          if (simple) status.dashboard = "simple";
          return status;
        }
        if (kind.startsWith("device_")) return {};
        if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
        return JSON.parse(JSON.stringify(payloads[kind]));
      },
      connection: { subscribeMessage: async () => () => {} },
      states: {},
    };
    await settle();
    const pane = panel.shadowRoot;
    const live = pane.querySelector('article.rec[data-kind="restart_live"]');
    const cached = pane.querySelector('article.rec[data-kind="restart_cached"]');
    check(`${where}: both cards are drawn, each with its count`, Boolean(live) && Boolean(cached)
      && live.querySelector("h3").textContent === "Models That May Report Live (1)"
      && cached.querySelector("h3").textContent === "Models That May Report Cached Values (1)",
      [live && live.querySelector("h3").textContent, cached && cached.querySelector("h3").textContent]);
    check(`${where}: a card with no opening words draws no empty paragraph`, live && !live.querySelector(":scope > p"));
    check(`${where}: a row is a model, with what was seen`, live && live.textContent.includes("Show the 1 model") && live.textContent.includes("was marked back each time."), live && live.textContent);
    await click(buttonIn(cached, "Set to Reports Cached Values"));
    const set = seen.filter((m) => m.type === "device_sentinel/device_restart");
    check(`${where}: the button sets the model, and says where it was pressed`, set.length === 1 && set[0].mode === "cached" && set[0].source === "recommendations", set);
    check(`${where}: what the setting does is under the button`, cached.textContent.includes("All Sonos One devices will be reported back only when one of their values changes after a restart."));
    check(`${where}: each row has its tick`, Boolean(live.querySelector("label.ack")));
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
