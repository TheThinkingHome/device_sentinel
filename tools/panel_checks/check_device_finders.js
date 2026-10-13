// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_device_finders.js, Version: 0.26.1 (2026-10-13)
//
// Panel checks: finding a device, and taking an exclusion back from the
// dashboard (0.26.1, rulings #658 and #659). The Devices tab's name
// search, Area and Label filters; its Excluded list, read live, with
// Cancel the exclusion for a device excluded on its own, a link to the
// integration for one excluded with it, and Home Assistant's own page
// for one whose history has gone; and an integration's page excluding
// it or taking it back. Run on the reference house's 103 device rows
// (payloads_fleet.json, anonymized), with areas, labels and exclusions
// laid over them, since the house as committed carries none.
// Run with: LC_ALL=en_US.UTF-8 node check_device_finders.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const fleet = JSON.parse(fs.readFileSync(__dirname + "/payloads_fleet.json", "utf8"));
const PREFIX = "/device-sentinel";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

// The house's rows, every third in the Kitchen, every fifth labelled
// Spare, a few in the Garage, and three exclusions of each kind.
function devicesReply() {
  const rows = JSON.parse(JSON.stringify(fleet.devices.rows)).map((row, i) => ({
    ...row,
    area: i % 3 === 0 ? "Kitchen" : i % 7 === 0 ? "Garage" : null,
    labels: i % 5 === 0 ? ["Spare"] : i % 11 === 0 ? ["Outdoor", "Spare"] : [],
  }));
  const excluded = [
    { device_id: "ex-own-kept", name: "Old Plug", integration: "test", integration_name: "Test", how: "device", page: true, area: "Garage", labels: ["Spare"] },
    { device_id: "ex-own-gone", name: "Old Lamp", integration: "test", integration_name: "Test", how: "device", page: false, area: null, labels: [] },
    { device_id: "ex-int", name: "Phone Randy", integration: "mobile_app", integration_name: "Mobile App", how: "integration", page: false, area: "Kitchen", labels: [] },
  ];
  return { rows, excluded };
}

async function open(path, overrides = {}) {
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
      if (kind in overrides) {
        const answer = overrides[kind];
        return typeof answer === "function" ? answer(message) : JSON.parse(JSON.stringify(answer));
      }
      if (kind === "devices") return devicesReply();
      if (kind.startsWith("device_") || kind === "integration_exclude") return {};
      if (!(kind in fleet)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(fleet[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot, calls };
}

const bodyRows = (root) => [...root.querySelectorAll(".pane table tbody tr")];
const names = (root) => bodyRows(root).map((tr) => tr.firstChild.textContent);
const select = (root, label) => root.querySelector(`select[aria-label="${label}"]`);
async function choose(root, label, value) {
  const box = select(root, label);
  box.value = value;
  box.dispatchEvent(new box.ownerDocument.defaultView.Event("change"));
  await settle();
}
async function type(root, words) {
  const box = root.querySelector("input.devsearch");
  box.focus();
  box.value = words;
  box.setSelectionRange(words.length, words.length);
  box.dispatchEvent(new box.ownerDocument.defaultView.Event("input"));
  await settle();
}
const linkButton = (root, start) => [...root.querySelectorAll(".pane button.linkbtn")].find((b) => b.textContent.startsWith(start));

(async () => {
  const reply = devicesReply();
  console.log("\nFinding a device on the Devices tab (ruling #658)");
  let { root, calls, window } = await open(`${PREFIX}/devices`);
  check("All 103 of the house's devices are listed", bodyRows(root).length === 103, bodyRows(root).length);

  await type(root, "device 01");
  const searched = names(root);
  check("The search narrows by name, ignoring case",
    searched.length === 10 && searched.every((n) => n.toLowerCase().includes("device 01")), searched);
  const box = root.querySelector("input.devsearch");
  check("The search box keeps its focus and cursor while typing",
    root.activeElement === box && box.selectionStart === "device 01".length, [root.activeElement && root.activeElement.className, box.selectionStart]);
  await type(root, "");
  check("Clearing the search lists every device again", bodyRows(root).length === 103);

  const areaOptions = [...select(root, "Show one area").options].map((o) => o.textContent);
  const kitchen = reply.rows.filter((r) => r.area === "Kitchen").length;
  const garage = reply.rows.filter((r) => r.area === "Garage").length;
  const none = reply.rows.filter((r) => !r.area).length;
  check("The Area filter offers each area with its count, then No area",
    JSON.stringify(areaOptions) === JSON.stringify(["All areas", `Garage ${garage}`, `Kitchen ${kitchen}`, `No area ${none}`]), areaOptions);
  await choose(root, "Show one area", "Kitchen");
  check("Choosing an area lists its devices only", bodyRows(root).length === kitchen, bodyRows(root).length);
  await choose(root, "Show one area", select(root, "Show one area").options[3].value);
  check("No area lists the devices without one", bodyRows(root).length === none, bodyRows(root).length);
  await choose(root, "Show one area", "");

  const spare = reply.rows.filter((r) => r.labels.includes("Spare")).length;
  const outdoor = reply.rows.filter((r) => r.labels.includes("Outdoor")).length;
  const labelOptions = [...select(root, "Show one label").options].map((o) => o.textContent);
  check("The Label filter offers each label with its count",
    JSON.stringify(labelOptions) === JSON.stringify(["All labels", `Outdoor ${outdoor}`, `Spare ${spare}`]), labelOptions);
  await choose(root, "Show one label", "Spare");
  check("Choosing a label lists the devices carrying it", bodyRows(root).length === spare, bodyRows(root).length);
  await choose(root, "Show one area", "Kitchen");
  const both = reply.rows.filter((r) => r.labels.includes("Spare") && r.area === "Kitchen").length;
  check("Area and Label narrow together", bodyRows(root).length === both, [bodyRows(root).length, both]);
  await choose(root, "Show one area", "");
  await choose(root, "Show one label", "");

  console.log("\nThe Excluded list (ruling #658)");
  const show = linkButton(root, "Show the 3 excluded devices");
  check("A link offers the excluded devices, with their count", Boolean(show), [...root.querySelectorAll(".pane button.linkbtn")].map((b) => b.textContent));
  show.click();
  await settle();
  const heads = [...root.querySelectorAll(".pane table thead th")].map((th) => th.textContent);
  check("The Excluded list has its own columns",
    JSON.stringify(heads) === JSON.stringify(["DEVICE", "INTEGRATION", "AREA", "EXCLUDED", "HISTORY", ""]), heads);
  check("It lists the three excluded devices by name", JSON.stringify(names(root)) === JSON.stringify(["Old Plug", "Old Lamp", "Phone Randy"]), names(root));
  const row = (name) => bodyRows(root).find((tr) => tr.firstChild.textContent === name);
  const link = (tr) => tr.firstChild.querySelector("a").getAttribute("href");
  check("A device whose history is kept opens its Device Sentinel page", link(row("Old Plug")).split("?")[0] === `${PREFIX}/device/ex-own-kept`, link(row("Old Plug")));
  check("A device whose history has gone opens Home Assistant's own page", link(row("Old Lamp")) === "/config/devices/device/ex-own-gone", link(row("Old Lamp")));
  check("Each says how it was excluded and what became of its history",
    [...row("Old Plug").children].slice(3, 5).map((td) => td.textContent).join("|") === "By you|Kept until midnight"
    && [...row("Phone Randy").children].slice(3, 5).map((td) => td.textContent).join("|") === "With its integration|Deleted",
    [...row("Phone Randy").children].map((td) => td.textContent));
  const last = (tr) => tr.lastChild;
  check("One excluded with its integration is taken back on the integration's page",
    last(row("Phone Randy")).querySelector("a") && last(row("Phone Randy")).querySelector("a").getAttribute("href").split("?")[0] === `${PREFIX}/integration/mobile_app`
    && !last(row("Phone Randy")).querySelector("button"), last(row("Phone Randy")).innerHTML);
  await type(root, "lamp");
  check("The search narrows the Excluded list too", JSON.stringify(names(root)) === JSON.stringify(["Old Lamp"]), names(root));
  await type(root, "");
  await choose(root, "Show one area", "Garage");
  check("So does the Area filter", JSON.stringify(names(root)) === JSON.stringify(["Old Plug"]), names(root));
  await choose(root, "Show one area", "");
  const before = calls.length;
  last(row("Old Plug")).querySelector("button").click();
  await settle();
  await settle();
  const sent = calls.slice(before).find((c) => c.type === "device_sentinel/device_exclude");
  check("Cancel the exclusion takes the device back, saying it was pressed on the Devices tab",
    sent && sent.device_id === "ex-own-kept" && sent.on === false && sent.source === "devices_tab", sent);
  check("and the tab is fetched again", calls.slice(before).some((c) => c.type === "device_sentinel/devices"));
  const back = linkButton(root, "Back to the watched devices");
  back.click();
  await settle();
  check("A link leads back to the watched devices", bodyRows(root).length === 103, bodyRows(root).length);

  ({ root } = await open(`${PREFIX}/devices`, { devices: { rows: reply.rows, excluded: [] } }));
  check("With nothing excluded, no link is offered", !linkButton(root, "Show the"));

  console.log("\nAn integration's page excludes it or takes it back (ruling #659)");
  const watchedPage = { ...fleet.integration, excluded: false };
  ({ root, calls } = await open(`${PREFIX}/integration/${fleet.integration.domain}`, { integration: watchedPage }));
  const chip = (start) => [...root.querySelectorAll(".pane button.chip")].find((b) => b.textContent.startsWith(start));
  check("A watched integration's page offers Exclude this integration", Boolean(chip("Exclude this integration")) && !chip("Cancel the exclusion"));
  let mark = calls.length;
  chip("Exclude this integration").click();
  await settle();
  let act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_exclude");
  check("It sends the exclusion for that integration", act && act.domain === fleet.integration.domain && act.on === true, act);
  const excludedPage = { ...fleet.integration, standing: "excluded", excluded: true };
  ({ root, calls } = await open(`${PREFIX}/integration/${fleet.integration.domain}`, { integration: excludedPage }));
  check("An excluded integration's page offers Cancel the exclusion", Boolean(chip("Cancel the exclusion")) && !chip("Exclude this integration"));
  mark = calls.length;
  chip("Cancel the exclusion").click();
  await settle();
  act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_exclude");
  check("It sends the exclusion's cancelling", act && act.on === false, act);
  ({ root } = await open(`${PREFIX}/integration/${fleet.integration.domain}`, {
    integration: watchedPage,
    integration_exclude: () => { throw Object.assign(new Error("Home Assistant refused it."), { code: "refused" }); },
  }));
  chip("Exclude this integration").click();
  await settle();
  await settle();
  const note = root.querySelector(".pane .actnote.refused");
  check("A refusal is shown on the page with Home Assistant's reason", note && note.textContent === "Home Assistant refused it.", note && note.textContent);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
