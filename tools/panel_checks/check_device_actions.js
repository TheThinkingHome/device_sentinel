// File: tools/panel_checks/check_device_actions.js, Version: 0.27.11 (2026-10-28)
// Panel checks: the device page's actions. Rename with its
// duplicate-name warning, the area and label pickers, the Heartbeat chip,
// the mute toggles and their confirmation, a refused write shown under
// its row, Open in Home Assistant, and no helper text. The Excluded row
// excludes one device from its page and shows only its button until
// pressed (rule MUTE-03), and the Muted row draws each mute that is on
// filled with a check mark (rule MUTE-09).
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

async function open(answers, tweak = () => {}) {
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
const excludedPage = (excluded) => (p) => {
  p.identity.watched = !(excluded.here || excluded.integration);
  if (!p.identity.watched) p.identity.set_aside = "excluded";
  p.identity.actions.excluded = excluded;
};

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
  // The chip sits in the Last seen group.
  await click(buttonIn(rowCell(root, "Last seen sensor"), "Turn on its Last Seen"));
  // Each turn-on says where it was pressed (rule BRIEF-07).
  check("Last seen sensor: the chip switches on this device's Last Seen, from the device page", calls.some((c) => c.type === "device_sentinel/device_turn_on"
    && c.kind === "last_seen" && c.device_id === DEVICE && c.source === "device_page"), calls.filter((c) => c.type === "device_sentinel/device_turn_on"));

  // A Battery or Signal sensor switched off: the row says so
  // and Turn it on asks for this device's own sensor of that kind
  // (rules REC-05, DASH-09).
  for (const [label, kind] of [["Battery sensor", "battery"], ["Signal sensor", "signal"]]) {
    ({ root, calls } = await open({}, (page) => {
      page.readings = (page.readings || []).filter((r) => r.kind !== kind);
      page.identity.actions[`${kind}_off`] = true;
    }));
    const cell = rowCell(root, label);
    check(`${label}: switched off reads so`, !!cell && /switched off/.test(cell.textContent), cell && cell.textContent);
    await click(buttonIn(cell, "Turn it on"));
    check(`${label}: Turn it on switches on this device's ${kind} sensor`,
      calls.some((c) => c.type === "device_sentinel/device_turn_on" && c.kind === kind && c.device_id === DEVICE && c.source === "device_page"));
  }

  ({ root, calls } = await open({}));
  const muted = rowCell(root, "Muted");
  const battery = buttonIn(muted, "\u2713 Mute battery");
  check("Muted: a mute from a label shows lit and fixed",
    battery && battery.getAttribute("aria-pressed") === "true" && battery.getAttribute("aria-disabled") === "true");
  // The row says nothing in words; each mute that is on is filled
  // with a check mark, and one that is off is plain (rule MUTE-09).
  check("Muted: no word before the buttons, not even 'nothing'",
    !!muted && muted.querySelector(".actcol").firstChild.classList.contains("actrow")
    && !/nothing/.test(muted.textContent), muted && muted.innerHTML.slice(0, 80));
  check("Muted: a mute that is on is filled and checked, one that is off is plain",
    battery.classList.contains("on") && /^\u2713 /.test(battery.textContent)
    && !buttonIn(muted, "Mute freeze").classList.contains("on"));
  await click(battery);
  check("Muted: a fixed chip sends nothing", !calls.some((c) => c.type === "device_sentinel/device_mute"));
  await click(buttonIn(rowCell(root, "Muted"), "Mute everything"));
  check("Muted: Mute everything sends at once, with no question",
    calls.some((c) => c.type === "device_sentinel/device_mute" && c.kind === "everything" && c.on === true)
    && !/\?/.test(rowCell(root, "Muted").textContent), rowCell(root, "Muted").textContent);

  // Mute everything on: the other four show on too, filled, and cannot
  // be pressed (rule MUTE-09).
  ({ root, calls } = await open({}, (p) => {
    p.identity.actions.mutes = {
      everything: { on: true, source: null, here: true },
      freeze: { on: false, source: null, here: false },
      battery: { on: false, source: null, here: false },
      signal: { on: false, source: null, here: false },
    };
  }));
  const all = rowCell(root, "Muted");
  const lit = [...all.querySelectorAll("button")].filter((b) => b.classList.contains("on")).map((b) => b.textContent);
  // The row holds Mute unavailable as well (rule MUTE-09).
  check("Muted: with Mute everything on, all five are filled and checked",
    lit.join() === "\u2713 Mute freeze,\u2713 Mute unavailable,\u2713 Mute battery,\u2713 Mute signal,\u2713 Mute everything", lit);
  check("Muted: the four it covers cannot be pressed",
    ["\u2713 Mute freeze", "\u2713 Mute unavailable", "\u2713 Mute battery", "\u2713 Mute signal"].every((t) => buttonIn(all, t) && buttonIn(all, t).getAttribute("aria-disabled") === "true"));
  const allButton = buttonIn(all, "\u2713 Mute everything");
  if (allButton) await click(allButton);
  const lift = calls.filter((c) => c.type === "device_sentinel/device_mute");
  check("Muted: pressing Mute everything again lifts it", lift.length === 1 && lift[0].kind === "everything" && lift[0].on === false, lift);

  // Each mute is its own kind (rule MUTE-06): Mute unavailable
  // on leaves Mute freeze plain and pressable, and a label's unavailable
  // mute names its section.
  ({ root, calls } = await open({}, (p) => {
    p.identity.actions.mutes = {
      everything: { on: false, source: null, here: false },
      freeze: { on: false, source: null, here: false },
      unavailable: { on: true, source: "device", here: true },
      battery: { on: false, source: null, here: false },
      signal: { on: false, source: null, here: false },
    };
  }));
  const una = rowCell(root, "Muted");
  const unaLit = [...una.querySelectorAll("button")].filter((b) => b.classList.contains("on")).map((b) => b.textContent);
  check("Muted: with Mute unavailable on, only it is lit", unaLit.join() === "\u2713 Mute unavailable", unaLit);
  check("Muted: no note ties freeze to unavailable", !/muted with unavailable/.test(una.textContent), una.textContent);
  await click(buttonIn(una, "Mute freeze"));
  const fz = calls.filter((c) => c.type === "device_sentinel/device_mute");
  check("Muted: Mute freeze can still be set", fz.length === 1 && fz[0].kind === "freeze" && fz[0].on === true, fz);
  ({ root, calls } = await open({}, (p) => {
    p.identity.actions.mutes = {
      everything: { on: false, source: null, here: false },
      freeze: { on: false, source: null, here: false },
      unavailable: { on: true, source: "label: Wall switched", here: false },
      battery: { on: false, source: null, here: false },
      signal: { on: false, source: null, here: false },
    };
  }));
  const unl = rowCell(root, "Muted");
  check("Muted: a label's unavailable mute names its section",
    /Unavailable is muted by the label Wall switched\. Change it in Device Sentinel's settings, Configure, Freeze and Unavailable Detection\./.test(unl.textContent), unl.textContent);
  check("Muted: a label's unavailable mute cannot be pressed here",
    buttonIn(unl, "\u2713 Mute unavailable").getAttribute("aria-disabled") === "true");

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

  console.log("\nAfter a change, every tab is fetched again (0.25.0)");
  ({ root, calls } = await open({}));
  const before = calls.filter((c) => c.type === "device_sentinel/devices").length;
  await click(rowCell(root, "Name").querySelector('button[aria-label="Rename"]'));
  const field = rowCell(root, "Name").querySelector("input.actinput");
  field.value = "Randy's Button";
  field.dispatchEvent(new (field.ownerDocument.defaultView.Event)("input"));
  await click(buttonIn(rowCell(root, "Name"), "Save"));
  await settle();
  const after = calls.filter((c) => c.type === "device_sentinel/devices").length;
  check("A rename fetches the Devices tab again", after > before, { before, after });
  check("A rename fetches the Problem List again", calls.filter((c) => c.type === "device_sentinel/problem_list").length > 1);

  console.log("\nA new area or label from the picker (0.25.0)");
  ({ root, calls } = await open({}));
  await click(rowCell(root, "Area").querySelector('button[aria-label="Change area"]'));
  const areaInput = rowCell(root, "Area").querySelector('input[aria-label="New area"]');
  check("Area: the picker offers a new area", Boolean(areaInput) && Boolean(buttonIn(rowCell(root, "Area"), "Create and move here")));
  await click(buttonIn(rowCell(root, "Area"), "Create and move here"));
  check("Area: an empty name sends nothing", !calls.some((c) => c.type === "device_sentinel/device_new_area"));
  areaInput.value = "Garage";
  await click(buttonIn(rowCell(root, "Area"), "Create and move here"));
  const made = calls.find((c) => c.type === "device_sentinel/device_new_area");
  check("Area: the new area is sent with its name", made && made.name === "Garage" && made.device_id === DEVICE, made);
  ({ root, calls } = await open({}));
  await click(buttonIn(rowCell(root, "Labels"), "Add label"));
  const labelInput = rowCell(root, "Labels").querySelector('input[aria-label="New label"]');
  check("Labels: the picker offers a new label", Boolean(labelInput) && Boolean(buttonIn(rowCell(root, "Labels"), "Create and add")));
  labelInput.value = "Spare";
  labelInput.dispatchEvent(new (labelInput.ownerDocument.defaultView.KeyboardEvent)("keydown", { key: "Enter" }));
  await settle();
  const madeLabel = calls.find((c) => c.type === "device_sentinel/device_new_label");
  check("Labels: Enter sends the new label", madeLabel && madeLabel.name === "Spare", madeLabel);

  console.log("\nThe Excluded row: one device excluded from its page");
  ({ root, calls } = await open({}, excludedPage({ here: false, integration: false })));
  const order = labelsOf(root);
  check("Excluded is the last row, after Muted", order.slice(-2).join() === "Muted,Excluded", order.slice(-3));
  const excludedRow = [...root.querySelectorAll("table.kv tr:not(.kvgroup)")].find((tr) => tr.firstChild.textContent === "Excluded");
  check("It sits outside the Last seen group", !!excludedRow && !excludedRow.classList.contains("kvsub"));
  cell = rowCell(root, "Excluded");
  check("A watched device offers only Exclude this device, with no 'no'",
    cell.textContent === "Exclude this device" && buttons(cell).join() === "Exclude this device", cell.textContent);
  cell.querySelector("button").click();
  await settle();
  const sent = calls.filter((c) => c.type === "device_sentinel/device_exclude");
  check("One press excludes, with no question: it sends the device and on: true",
    sent.length === 1 && sent[0].on === true && sent[0].device_id === DEVICE, sent);

  ({ root, calls } = await open({}, excludedPage({ here: true, integration: false })));
  cell = rowCell(root, "Excluded");
  check("An excluded device says so and offers Cancel the exclusion",
    /^Excluded\. Device Sentinel has stopped watching this device and deletes its history at midnight\. After that this page is gone, and the device is taken back in Device Sentinel's settings, Exclusions and Muting\.Cancel the exclusion/.test(cell.textContent)
    && buttons(cell).join() === "Cancel the exclusion", cell.textContent);
  check("The head says it is set aside, excluded", /Set aside: excluded\./.test(root.querySelector(".pagehead").textContent));
  cell.querySelector("button").click();
  await settle();
  const back = calls.filter((c) => c.type === "device_sentinel/device_exclude");
  check("Cancel the exclusion sends on: false", back.length === 1 && back[0].on === false, back);

  ({ root, calls } = await open({}, excludedPage({ here: false, integration: true })));
  cell = rowCell(root, "Excluded");
  check("An excluded integration is named, with the way to the Integrations tab, and no button",
    /^Its integration is excluded\. Change it on the Integrations tab\./.test(cell.textContent)
    && buttons(cell).length === 0 && !!cell.querySelector("a"), cell.textContent);

  ({ root } = await open({}, (p) => {
    excludedPage({ here: true, integration: false })(p);
    p.identity.same_hardware = { watched_through: DEVICE, devices: [{ device_id: DEVICE }, { device_id: "other" }] };
  }));
  check("With another listing of the same hardware, the excluded row says it may take over",
    /If another listing of the same hardware can be watched, Device Sentinel watches the hardware through it instead\./.test(rowCell(root, "Excluded").textContent),
    rowCell(root, "Excluded").textContent);

  ({ root } = await open({}, (p) => { delete p.identity.actions.excluded; }));
  check("A page from an older server still draws the row", buttons(rowCell(root, "Excluded")).join() === "Exclude this device");

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
