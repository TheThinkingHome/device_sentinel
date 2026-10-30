// File: tools/panel_checks/check_not_set.js, Version: 0.27.15 (2026-10-30)
// Panel checks: "Not Set" (rules DASH-04, DEV-10, DASH-12). A type, an
// area or a battery nobody has set reads "Not Set" on every tab and on
// the device page, a link that opens the way to set it in place, saved
// with where it was pressed (rule BRIEF-07); the Excluded list keeps
// its last column on one line.
// Run with: LC_ALL=en_US.UTF-8 node check_not_set.js [path/to/panel.js]
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
const AREAS = { areas: [{ id: "hall", name: "Hall" }, { id: "porch", name: "Porch" }], labels: [] };

async function open(path, answers = {}, mode = "advanced") {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${path}`, virtualConsole,
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
      if (answers[kind]) return answers[kind](JSON.parse(JSON.stringify(payloads[kind] || {})), message);
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind === "device_choices") return AREAS;
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const tableRows = (root) => [...root.querySelectorAll(".pane table tbody tr")];
const heads = (root) => [...root.querySelectorAll(".pane table thead th")].map((th) => th.textContent);
const buttonsIn = (node) => (node ? [...node.querySelectorAll("button")].map((b) => b.textContent) : []);
const click = async (node) => { node.click(); await settle(); };

(async () => {
  console.log("\nDevices tab, Advanced: AREA");
  const devices = (reply) => {
    reply.rows.forEach((row, i) => { row.area = i % 2 ? null : "Hall"; row.type = "Switch"; });
    return reply;
  };
  let { root, calls, window } = await open("/devices", { devices });
  const areaAt = heads(root).indexOf("AREA");
  const rows = tableRows(root);
  const unset = rows.find((tr) => tr.children[areaAt].textContent === "Not Set");
  const set = rows.find((tr) => tr.children[areaAt].textContent === "Hall");
  check("an area that is set is its name, a link that narrows the list to it",
    Boolean(set) && buttonsIn(set.children[areaAt]).join() === "Hall");
  check("one nobody has set reads Not Set, a link", Boolean(unset) && buttonsIn(unset.children[areaAt]).join() === "Not Set");
  await click(unset.children[areaAt].querySelector("button.linkbtn"));
  await settle();
  const select = unset.children[areaAt].querySelector('select[aria-label="Which area"]');
  check("pressing it opens Home Assistant's areas there, with Save and Cancel, and asks nothing first",
    Boolean(select) && [...select.options].map((o) => o.textContent).join("|") === "Choose…|Hall|Porch"
    && buttonsIn(unset.children[areaAt]).join() === "Save,Cancel", unset.children[areaAt].innerHTML.slice(0, 300));
  select.value = "porch";
  select.dispatchEvent(new window.Event("change"));
  await click([...unset.children[areaAt].querySelectorAll("button")].find((b) => b.textContent === "Save"));
  const moved = calls.find((c) => c.type === "device_sentinel/device_area");
  check("Save moves that device, from the Devices tab", moved && moved.area_id === "porch" && moved.source === "devices_tab", moved);
  check("and the dashboard reads everything again", calls.filter((c) => c.type === "device_sentinel/devices").length >= 2);

  console.log("\nThe Excluded list");
  const excluded = (reply) => {
    reply.excluded = [
      { device_id: "x1", name: "Old Plug", integration: "zha", integration_name: "Zigbee Home Automation", area: null, how: "device", page: true },
      { device_id: "x2", name: "Speaker", integration: "cast", integration_name: "Google Cast", area: "Hall", how: "integration", page: false },
    ];
    return reply;
  };
  ({ root, calls } = await open("/devices", { devices: excluded }));
  await click([...root.querySelectorAll(".pane button.linkbtn")].find((b) => /^Show the 2 excluded/.test(b.textContent)));
  const table = root.querySelector(".pane table");
  check("it has its own widths", table && table.dataset.shares === "excluded" && table.classList.contains("pinned"));
  const cols = table ? [...table.querySelectorAll("colgroup col")].map((c) => parseFloat(c.style.width)) : [];
  check("the last column gets the room for its button or link", cols.length === 6 && cols[5] > cols[2], cols);
  const last = tableRows(root).map((tr) => tr.children[5]);
  check("and holds it on one line", last.every((td) => td.style.whiteSpace === "nowrap"), last.map((td) => td.getAttribute("style")));
  const exAreas = tableRows(root).map((tr) => tr.children[2]);
  check("AREA reads Not Set, a link, or the area's name",
    exAreas[0].textContent === "Not Set" && buttonsIn(exAreas[0]).join() === "Not Set" && exAreas[1].textContent === "Hall", exAreas.map((td) => td.textContent));

  console.log("\nBattery Trends: TYPE from the Battery Trends tab");
  const battery = (reply) => {
    reply.steady = [{ device_id: "b1", name: "Mystery Tag", type: null, level: 80, steps: "Smooth", days: 30, month_drop: 0, cell: "CR2032", lithium: null, model_pace: null }];
    return reply;
  };
  const recommendations = (reply) => ({ ...reply, types: { choices: ["Leak Sensor", "Tag"], other: "Other" } });
  ({ root, calls, window } = await open("/battery-trends", { battery_trends: battery, recommendations }));
  const tagRow = [...root.querySelectorAll(".pane tr")].find((tr) => tr.children[0] && tr.children[0].textContent === "Mystery Tag");
  const typeCell = tagRow && tagRow.children[1];
  check("a type nobody has set reads Not Set, a link", typeCell && buttonsIn(typeCell).join() === "Not Set", typeCell && typeCell.innerHTML);
  await click(typeCell.querySelector("button.linkbtn"));
  const kinds = typeCell.querySelector('select[aria-label="What this device is"]');
  kinds.value = "Tag";
  kinds.dispatchEvent(new window.Event("change"));
  await click([...typeCell.querySelectorAll("button")].find((b) => b.textContent === "Save"));
  const typed = calls.find((c) => c.type === "device_sentinel/device_type");
  check("Save sets it for the model, from the Battery Trends tab",
    typed && typed.device_id === "b1" && typed.choice === "Tag" && typed.source === "battery_trends", typed);

  console.log("\nClassification: a device not watched");
  const classification = (reply) => {
    reply.rows.forEach((row, i) => { row.type = null; row.watched = i % 2 === 0; });
    reply.rows[1].type = "Router";
    return reply;
  };
  ({ root } = await open("/classification", { classification }));
  const typeAt = heads(root).indexOf("TYPE");
  const classRows = tableRows(root);
  const watchedRow = classRows.find((tr, i) => i % 2 === 0);
  const unwatched = classRows.filter((tr) => tr.children[typeAt].textContent === "Not Watched");
  check("a watched device with no type reads Not Set, a link", watchedRow && buttonsIn(watchedRow.children[typeAt]).join() === "Not Set");
  check("one not watched reads Not Watched, grey, with nothing to press",
    unwatched.length > 0 && unwatched.every((tr) => !tr.children[typeAt].querySelector("button") && tr.children[typeAt].querySelector("span.muted")),
    classRows.map((tr) => tr.children[typeAt].textContent));
  check("one not watched with a type known shows the type",
    classRows.some((tr) => tr.children[typeAt].textContent === "Router"), classRows.map((tr) => tr.children[typeAt].textContent));
  // The Type filter counts each under the words its row shows: "Not
  // Set" only the watched devices with no type, "Not Watched" the rest
  // (rule DEV-12).
  const typeSelect = root.querySelector('select[aria-label="Show one type"]');
  const optionText = typeSelect ? [...typeSelect.options].map((o) => o.textContent) : [];
  const notSetCount = classRows.filter((tr) => tr.children[typeAt].textContent === "Not Set").length;
  check("the Type filter's Not Set counts only the rows that read Not Set",
    optionText.includes(`Not Set ${notSetCount}`), [optionText, notSetCount]);
  check("and offers Not Watched with the rows that read it",
    optionText.includes(`Not Watched ${unwatched.length}`), optionText);
  typeSelect.value = "Not Watched";
  typeSelect.dispatchEvent(new window.Event("change"));
  await settle();
  const shownTypes = tableRows(root).map((tr) => tr.children[heads(root).indexOf("TYPE")].textContent);
  check("choosing Not Watched lists those rows only",
    shownTypes.length === unwatched.length && shownTypes.every((t) => t === "Not Watched"), shownTypes);

  console.log("\nThe device page, Advanced: Area");
  const page = (reply) => {
    reply.identity.actions = { area_id: null, name_by_user: null, integration_name: null, labels: [], last_seen_off: false,
      mutes: { everything: { on: false }, freeze: { on: false }, unavailable: { on: false }, battery: { on: false }, signal: { on: false } } };
    reply.identity.area = null;
    return reply;
  };
  const id = payloads._ids ? payloads._ids.alpha : "alpha";
  ({ root } = await open(`/device/${id}`, { device: page }));
  const areaRow = [...root.querySelectorAll("table.kv tr")].find((tr) => tr.firstChild && tr.firstChild.textContent === "Area");
  const areaCell = areaRow && areaRow.lastChild;
  check("an area nobody set reads Not Set, a link, with the pencil beside it",
    areaCell && areaCell.querySelector("button.linkbtn") && areaCell.querySelector("button.linkbtn").textContent === "Not Set"
    && areaCell.querySelector("button.edit"), areaCell && areaCell.innerHTML.slice(0, 300));
  await click(areaCell.querySelector("button.linkbtn"));
  const areaNow = [...root.querySelectorAll("table.kv tr")].find((tr) => tr.firstChild && tr.firstChild.textContent === "Area").lastChild;
  check("pressing it opens the area choices, as the pencil does", /Master|Hall/.test(areaNow.textContent) && Boolean(areaNow.querySelector('input[name="ds-area"]')),
    areaNow.textContent.slice(0, 200));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
