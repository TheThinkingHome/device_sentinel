// Panel checks: the device page's actions (0.24.5). Rename with its
// duplicate-name warning, the area and label pickers, the Heartbeat chip,
// the mute toggles and their confirmation, a refused write shown under
// its row, Open in Home Assistant, and no helper text.
// Run with: LC_ALL=en_US.UTF-8 node check_device_actions.js [path/to/panel.js]
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

async function open(answers) {
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
        return page;
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

(async () => {
  console.log("\nThe device page with its actions");
  let { root, calls } = await open({});
  check("No helper text beside the wait rule's button", !/Until this device has 28 new days/.test(root.textContent));
  const link = [...root.querySelectorAll("a")].find((a) => a.textContent === "Open in Home Assistant");
  check("Open in Home Assistant links to the device's own page", link && link.getAttribute("href") === `/config/devices/device/${DEVICE}`,
    link ? link.getAttribute("href") : null);

  const labels = rowCell(root, "Labels");
  check("Labels: each shows what it means", labels && /Quietmutes battery and signal/.test(labels.textContent), labels ? labels.textContent : null);
  const remove = labels && labels.querySelector('button[aria-label="Remove the label Bedside from this device"]');
  await click(remove);
  const removal = calls.find((c) => c.type === "device_sentinel/device_label");
  check("Labels: the remove mark takes the label off the device", removal && removal.label_id === "bedside" && removal.add === false, removal);

  ({ root, calls } = await open({}));
  // In the Last seen group since 0.24.9, where the Heartbeat row was.
  await click(buttonIn(rowCell(root, "Last seen sensor"), "Turn on its Last Seen"));
  check("Last seen sensor: the chip switches on this device's Last Seen", calls.some((c) => c.type === "device_sentinel/device_last_seen" && c.device_id === DEVICE));

  ({ root, calls } = await open({}));
  const muted = rowCell(root, "Muted");
  const battery = buttonIn(muted, "Mute battery");
  check("Muted: a mute from a label shows lit and fixed",
    battery && battery.getAttribute("aria-pressed") === "true" && battery.getAttribute("aria-disabled") === "true");
  await click(battery);
  check("Muted: a fixed chip sends nothing", !calls.some((c) => c.type === "device_sentinel/device_mute"));
  await click(buttonIn(rowCell(root, "Muted"), "Mute everything"));
  check("Muted: Mute everything asks first", /Mute everything for Button Randy Night Table\?/.test(rowCell(root, "Muted").textContent)
    && !calls.some((c) => c.type === "device_sentinel/device_mute"));
  const confirmButton = [...rowCell(root, "Muted").querySelectorAll("button")].filter((b) => b.textContent === "Mute everything").pop();
  await click(confirmButton);
  check("Muted: confirming sends the mute", calls.some((c) => c.type === "device_sentinel/device_mute" && c.kind === "everything" && c.on === true));

  console.log("\nRenaming");
  ({ root, calls } = await open({
    device_rename: (m) => {
      if (!m.confirm) { const e = new Error("Another device is already named Button Randy Night Table (in the Living Room)."); e.code = "name_in_use"; throw e; }
      return {};
    },
  }));
  await click(rowCell(root, "Name").querySelector('button[aria-label="Rename"]'));
  const input = rowCell(root, "Name").querySelector("input.actinput");
  check("Rename: the edit mark opens the field with the name", input && input.value === "Button Randy Night Table", input ? input.value : null);
  await click(buttonIn(rowCell(root, "Name"), "Save"));
  check("Rename: a name in use is warned, not saved", /Another device is already named/.test(rowCell(root, "Name").textContent)
    && buttonIn(rowCell(root, "Name"), "Save anyway") && buttonIn(rowCell(root, "Name"), "Change name"));
  await click(buttonIn(rowCell(root, "Name"), "Save anyway"));
  const last = calls.filter((c) => c.type === "device_sentinel/device_rename").pop();
  check("Rename: Save anyway sends the confirmation", last && last.confirm === true, last);
  await click(rowCell(root, "Name").querySelector('button[aria-label="Rename"]'));
  const reset = buttonIn(rowCell(root, "Name"), "Reset to 0x00158d0001");
  check("Rename: Reset offers the integration's name", Boolean(reset), rowCell(root, "Name").textContent);
  await click(reset);
  const cleared = calls.filter((c) => c.type === "device_sentinel/device_rename").pop();
  check("Rename: Reset sends an empty name", cleared && cleared.name === "", cleared);

  console.log("\nThe area picker, and a refusal");
  ({ root, calls } = await open({
    device_area: () => { const e = new Error("Home Assistant has no such area"); e.code = "refused"; throw e; },
  }));
  await click(rowCell(root, "Area").querySelector('button[aria-label="Change area"]'));
  check("Area: the picker fetches the choices", calls.some((c) => c.type === "device_sentinel/device_choices"));
  const options = [...rowCell(root, "Area").querySelectorAll("label.pick")].map((l) => l.textContent);
  check("Area: the picker offers No area and every area", options.join("|") === "No area|Master Bedroom|Laundry", options);
  const laundry = [...rowCell(root, "Area").querySelectorAll("label.pick")].find((l) => l.textContent === "Laundry").querySelector("input");
  laundry.checked = true;
  laundry.dispatchEvent(new (laundry.ownerDocument.defaultView.Event)("change"));
  await settle();
  const note = rowCell(root, "Area").querySelector(".actnote.refused");
  check("Refusal: Home Assistant's reason shows under the row", note && note.textContent === "Home Assistant has no such area", note ? note.textContent : null);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
