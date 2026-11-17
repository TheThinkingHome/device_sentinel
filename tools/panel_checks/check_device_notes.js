// File: tools/panel_checks/check_device_notes.js, Version: 0.29.5 (2026-11-17)
// Panel checks: the Notes row on a device's page (rule DEV-19). Last in
// the first group, before Power, in Simple and Advanced alike; empty with
// only its pencil until written; the pencil opens one line that sends the
// note, Clear sends it empty, and a refusal shows under the row.
// Run with: LC_ALL=en_US.UTF-8 node check_device_notes.js [path/to/panel.js]
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
const NOTE = "Previously the terrace door sensor in the guest room";

const ACTIONS = {
  area_id: "bedroom", name_by_user: null, integration_name: "Door Terrace", labels: [], last_seen_off: false,
  mutes: {
    everything: { on: false, source: null, here: false }, freeze: { on: false, source: null, here: false },
    battery: { on: false, source: null, here: false }, signal: { on: false, source: null, here: false },
  },
};

async function open({ mode = "advanced", note = null, refuse = false }) {
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
  panel.hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = DEVICE;
        page.identity.name = "Door Terrace";
        page.identity.area = "Master Bedroom";
        page.identity.note = note;
        page.identity.actions = JSON.parse(JSON.stringify(ACTIONS));
        return page;
      }
      if (kind === "device_note") {
        if (refuse) throw { code: "refused", message: "A note holds up to 500 characters." };
        return {};
      }
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { root: panel.shadowRoot, calls };
}

const labelsOf = (root) => [...root.querySelectorAll("table.kv tr")].map((tr) =>
  tr.classList.contains("kvgroup") ? `[${tr.textContent}]` : tr.firstChild.textContent);
const rowCell = (root, label) => {
  const row = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild && tr.firstChild.textContent === label);
  return row ? row.lastChild : null;
};
const buttonIn = (node, text) => node && [...node.querySelectorAll("button")].find((b) => b.textContent === text || b.getAttribute("aria-label") === text);
const click = async (node) => { node.click(); await settle(); };

(async () => {
  for (const mode of ["advanced", "simple"]) {
    console.log(`\nThe Notes row, ${mode}`);
    let { root, calls } = await open({ mode });
    const rows = labelsOf(root);
    const at = rows.indexOf("Notes");
    check("a Notes row", at >= 0, rows);
    check(`the ${mode} page`, rows.includes("Labels") === (mode === "advanced"), rows);
    check("last in the first group, just before Power", at >= 0 && rows[at + 1] === "[Power]", rows.slice(at - 1, at + 2));
    let cell = rowCell(root, "Notes");
    check("empty: only its pencil, no words", cell && cell.textContent.trim() === "" && !!buttonIn(cell, "Write a note"),
      cell && cell.textContent);
    await click(buttonIn(cell, "Write a note"));
    cell = rowCell(root, "Notes");
    const input = cell && cell.querySelector("input.noteinput");
    check("the pencil opens one line, up to 500 characters", !!input && input.getAttribute("maxlength") === "500");
    input.value = NOTE;
    input.dispatchEvent(new root.host.ownerDocument.defaultView.Event("input"));
    await click(buttonIn(cell, "Save"));
    const sent = calls.find((c) => c.type === "device_sentinel/device_note");
    check("Save sends the note for this device", sent && sent.device_id === DEVICE && sent.note === NOTE, sent);

    ({ root, calls } = await open({ mode, note: NOTE }));
    cell = rowCell(root, "Notes");
    check("a written note shows on the page", cell && cell.textContent.includes(NOTE), cell && cell.textContent);
    await click(buttonIn(cell, "Edit the note"));
    cell = rowCell(root, "Notes");
    check("the editor starts from the note", cell.querySelector("input.noteinput").value === NOTE);
    await click(buttonIn(cell, "Clear"));
    const cleared = calls.find((c) => c.type === "device_sentinel/device_note");
    check("Clear sends it empty", cleared && cleared.note === "", cleared);
  }

  console.log("\nA refused note");
  const { root } = await open({ refuse: true });
  let cell = rowCell(root, "Notes");
  await click(buttonIn(cell, "Write a note"));
  cell = rowCell(root, "Notes");
  await click(buttonIn(cell, "Save"));
  cell = rowCell(root, "Notes");
  check("the reason shows under the row", cell && cell.textContent.includes("A note holds up to 500 characters."), cell && cell.textContent);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
