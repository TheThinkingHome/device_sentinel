// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_device_finders.js, Version: 0.28.9 (2026-11-10)
//
// Panel checks: finding a device, and taking an exclusion back from the
// dashboard (rules DASH-12, MUTE-03). The Devices tab's name
// search, Area and Label filters; its Excluded chip, read live, with
// Cancel the exclusion for a device excluded on its own, a link to the
// integration for one excluded with it, and Home Assistant's own page
// for one whose history has gone; and an integration's page excluding
// it or taking it back. Run on a real house's 103 device rows
// (payloads_fleet.json, anonymized), with areas, labels and exclusions
// laid over them, since the house as committed carries none (rule
// CODE-16).
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
  console.log("\nFinding a device on the Devices tab");
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
  check("The Area filter offers each area with its count, then Not Set (rule DASH-04)",
    JSON.stringify(areaOptions) === JSON.stringify(["All areas", `Garage ${garage}`, `Kitchen ${kitchen}`, `Not Set ${none}`]), areaOptions);
  await choose(root, "Show one area", "Kitchen");
  check("Choosing an area lists its devices only", bodyRows(root).length === kitchen, bodyRows(root).length);
  await choose(root, "Show one area", select(root, "Show one area").options[3].value);
  check("Not Set lists the devices without one", bodyRows(root).length === none, bodyRows(root).length);
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

  // A set area in a row is a link that narrows the list as the Area
  // filter does (rule DASH-12).
  const areaColumn = [...root.querySelectorAll(".pane table thead th")].findIndex((th) => th.textContent === "AREA");
  const kitchenLink = bodyRows(root).map((tr) => tr.children[areaColumn].querySelector("button.linkbtn"))
    .find((b) => b && b.textContent === "Kitchen");
  check("A set area in a row is a link", Boolean(kitchenLink), areaColumn);
  kitchenLink.click();
  await settle();
  check("Pressing an area lists its devices only, and the Area filter shows it",
    bodyRows(root).length === kitchen && select(root, "Show one area").value === "Kitchen", bodyRows(root).length);
  await choose(root, "Show one area", "");

  console.log("\nThe Excluded chip (0.28.8)");
  const chipNamed = (start) => [...root.querySelectorAll(".pane .chips .chip")].find((b) => b.textContent.startsWith(start));
  check("An Excluded chip counts the excluded devices", chipNamed("Excluded") && chipNamed("Excluded").textContent === "Excluded 3",
    [...root.querySelectorAll(".pane .chips .chip")].map((b) => b.textContent));
  check("They are filtered out until it is pressed", !names(root).includes("Old Plug"));
  chipNamed("Excluded").click();
  await settle();
  const heads = [...root.querySelectorAll(".pane table thead th")].map((th) => th.textContent);
  check("The same columns as the watched devices",
    JSON.stringify(heads) === JSON.stringify(["DEVICE", "TYPE", "AREA", "INTEGRATION", "STANDING", "PROBLEM", "LAST REPORT", "WINDOW"]), heads);
  check("It lists the three excluded devices by name", JSON.stringify(names(root)) === JSON.stringify(["Old Plug", "Old Lamp", "Phone Randy"]), names(root));
  const row = (name) => bodyRows(root).find((tr) => tr.firstChild.textContent === name);
  const link = (tr) => tr.firstChild.querySelector("a").getAttribute("href");
  check("A device whose history is kept opens its Device Sentinel page", link(row("Old Plug")).split("?")[0] === `${PREFIX}/device/ex-own-kept`, link(row("Old Plug")));
  check("A device whose history has gone opens Home Assistant's own page", link(row("Old Lamp")) === "/config/devices/device/ex-own-gone", link(row("Old Lamp")));
  const standingOf = (tr) => tr.children[4];
  check("STANDING says how it was excluded and what became of its history",
    standingOf(row("Old Plug")).textContent === "Excluded by you, history kept until midnight."
    && standingOf(row("Old Lamp")).textContent === "Excluded by you, history deleted."
    && standingOf(row("Phone Randy")).textContent === "Excluded by its integration.",
    [...bodyRows(root)].map((tr) => standingOf(tr).textContent));
  check("The word integration opens that integration's page",
    standingOf(row("Phone Randy")).querySelector("a") && standingOf(row("Phone Randy")).querySelector("a").textContent === "integration"
    && standingOf(row("Phone Randy")).querySelector("a").getAttribute("href").split("?")[0] === `${PREFIX}/integration/mobile_app`,
    standingOf(row("Phone Randy")).innerHTML);
  check("The Excluded chip is information only: no button in any row (rule DASH-12)",
    bodyRows(root).every((tr) => !standingOf(tr).querySelector("button")));
  check("The key under the table says what an exclusion does, and the ways back",
    root.querySelector(".pane").lastElementChild.textContent.includes("deletes its history at the midnight")
    && root.querySelector(".pane").lastElementChild.textContent.includes("Exclusions and Muting"));
  await type(root, "lamp");
  check("The search narrows the excluded devices too", JSON.stringify(names(root)) === JSON.stringify(["Old Lamp"]), names(root));
  await type(root, "");
  await choose(root, "Show one area", "Garage");
  check("So does the Area filter", JSON.stringify(names(root)) === JSON.stringify(["Old Plug"]), names(root));
  await choose(root, "Show one area", "");
  const garageLink = row("Old Plug").children[2].querySelector("button.linkbtn");
  check("An excluded device's area is a link too", Boolean(garageLink) && garageLink.textContent === "Garage");
  garageLink.click();
  await settle();
  check("Pressing it narrows the excluded devices to that area", JSON.stringify(names(root)) === JSON.stringify(["Old Plug"]), names(root));
  await choose(root, "Show one area", "");
  chipNamed("Watched").click();
  await settle();
  check("Watched leads back to the watched devices", bodyRows(root).length === 103, bodyRows(root).length);

  ({ root } = await open(`${PREFIX}/devices`, { devices: { rows: reply.rows, excluded: [] } }));
  check("With nothing excluded, the chip reads 0", chipNamed("Excluded") && chipNamed("Excluded").textContent === "Excluded 0");

  console.log("\nAn integration's page has the Integrations tab's five buttons (rule MUTE-03)");
  const domain = fleet.integration.domain;
  const tabRows = (excluded, mutes) => {
    const reply = JSON.parse(JSON.stringify(fleet.integrations));
    reply.rows = reply.rows.map((r) => (r.domain === domain ? { ...r, excluded, mutes: { everything: false, freeze: false, battery: false, signal: false, ...mutes } } : r));
    return reply;
  };
  // The page reads its own exclusion and mutes; the tab's list may be
  // older, so it says the opposite here.
  const watchedPage = { ...fleet.integration, excluded: false, mutes: { everything: false, freeze: false, battery: true, signal: false } };
  ({ root, calls } = await open(`${PREFIX}/integration/${domain}`, { integration: watchedPage, integrations: tabRows(true, {}) }));
  const chip = (start) => [...root.querySelectorAll(".pane button.chip")].find((b) => b.textContent.replace("\u2713 ", "").startsWith(start));
  const labels = [...root.querySelectorAll(".pane .intbuttons button.chip")].map((b) => b.textContent);
  check("Exclude, Mute everything, Mute freeze, Mute battery and Mute signal, as on the tab",
    JSON.stringify(labels) === JSON.stringify(["Exclude", "Mute everything", "Mute freeze", "\u2713 Mute battery", "Mute signal"]), labels);
  check("A mute that is on is lit", chip("Mute battery").classList.contains("on") && chip("Mute battery").getAttribute("aria-pressed") === "true");
  let mark = calls.length;
  chip("Mute battery").click();
  await settle();
  let act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_mute");
  check("Pressing a lit mute lifts it, saying it was pressed on the integration's page",
    act && act.domain === domain && act.kind === "battery" && act.on === false && act.source === "integration_page", act);
  mark = calls.length;
  chip("Mute signal").click();
  await settle();
  act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_mute");
  check("Pressing one that is off sets it", act && act.kind === "signal" && act.on === true, act);
  mark = calls.length;
  chip("Exclude").click();
  await settle();
  act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_exclude");
  check("Exclude sends the exclusion, saying it was pressed on the integration's page",
    act && act.domain === domain && act.on === true && act.source === "integration_page", act);
  const excludedPage = { ...fleet.integration, standing: "excluded", excluded: true, mutes: {} };
  ({ root, calls } = await open(`${PREFIX}/integration/${domain}`, { integration: excludedPage, integrations: tabRows(false, {}) }));
  check("An excluded integration's page shows Excluded lit", chip("Excluded") && chip("Excluded").classList.contains("on"));
  check("with its mutes at rest", ["Mute everything", "Mute freeze", "Mute battery", "Mute signal"].every((w) => chip(w).getAttribute("aria-disabled") === "true"));
  check("and how to keep its history", root.querySelector(".pane").textContent.includes("Press Excluded again before then to keep it."));
  mark = calls.length;
  chip("Excluded").click();
  await settle();
  act = calls.slice(mark).find((c) => c.type === "device_sentinel/integration_exclude");
  check("Pressing Excluded takes the exclusion back", act && act.on === false && act.source === "integration_page", act);
  ({ root } = await open(`${PREFIX}/integration/${domain}`, {
    integration: watchedPage, integrations: tabRows(false, {}),
    integration_exclude: () => { throw Object.assign(new Error("Home Assistant refused it."), { code: "refused" }); },
  }));
  chip("Exclude").click();
  await settle();
  await settle();
  const note = root.querySelector(".pane .actnote.refused");
  check("A refusal is shown on the page with Home Assistant's reason", note && note.textContent === "Home Assistant refused it.", note && note.textContent);

  console.log("\nThe chips of devices not watched (rule DASH-12)");
  {
    // An excluded device the classification knows a type for, a set-aside
    // device Device Sentinel once watched (it has a page), and one it
    // never did, with an area and a label.
    const classification = () => {
      const c = JSON.parse(JSON.stringify(fleet.classification));
      c.rows = c.rows.filter((r) => r.watched);
      c.rows.push(
        { device_id: "ex-own-kept", name: "Old Plug", integration: "test", integration_name: "Test", watched: false, muted: "", muted_global: "",
          set_aside: "excluded (device)", copies: 1, type: "Plug", area: "Garage", labels: ["Spare"], page: true },
        { device_id: "aside-kept", name: "Retired Sensor", integration: "test", integration_name: "Test", watched: false, muted: "", muted_global: "",
          set_aside: "disabled", copies: 1, type: "Motion Sensor", area: "Hall", labels: ["Spare"], page: true },
        { device_id: "aside-never", name: "Spotify", integration: "spotify", integration_name: "Spotify", watched: false, muted: "", muted_global: "",
          set_aside: "service", copies: 1, type: null, area: null, labels: [], page: false });
      return c;
    };
    const opened = await open(`${PREFIX}/devices`, { classification });
    const r = opened.root;
    const chip = (start) => [...r.querySelectorAll(".pane .chips .chip")].find((b) => b.textContent.startsWith(start));
    const heads = () => [...r.querySelectorAll(".pane thead th")].map((th) => th.textContent);
    const cellOf = (name, column) => {
      const tr = bodyRows(r).find((t) => t.firstChild.textContent === name);
      return tr ? tr.children[heads().indexOf(column)] : null;
    };
    chip("Excluded").click();
    await settle();
    check("an excluded device keeps the type Device Sentinel knows", cellOf("Old Plug", "TYPE").textContent === "Plug", cellOf("Old Plug", "TYPE").textContent);
    check("one with no type known reads Not Watched", cellOf("Old Lamp", "TYPE").textContent === "Not Watched");
    check("LAST REPORT and WINDOW do not sort where they are blank",
      ![...r.querySelectorAll(".pane thead th button")].some((b) => ["LAST REPORT", "WINDOW"].includes(b.textContent)));
    chip("Set aside").click();
    await settle();
    check("a set-aside device shows its area", cellOf("Retired Sensor", "AREA").textContent === "Hall", cellOf("Retired Sensor", "AREA").textContent);
    const areaChoices = [...select(r, "Show one area").options].map((o) => o.textContent);
    check("and the Area filter offers it", areaChoices.some((o) => o.startsWith("Hall")), areaChoices);
    await choose(r, "Show one area", "Hall");
    check("choosing it narrows Set aside", names(r).join() === "Retired Sensor", names(r));
    await choose(r, "Show one area", "");
    const link = (name) => bodyRows(r).find((t) => t.firstChild.textContent === name).firstChild.querySelector("a");
    check("one Device Sentinel once watched opens its page here", /\/device-sentinel\/device\/aside-kept/.test(link("Retired Sensor").getAttribute("href")), link("Retired Sensor").getAttribute("href"));
    check("one it never watched opens Home Assistant's own page", link("Spotify").getAttribute("href").startsWith("/config/devices/device/aside-never"), link("Spotify").getAttribute("href"));
    const list = opened.panel._lists && Object.values(opened.panel._lists).find((l) => Array.isArray(l) && l.includes("aside-kept"));
    check("Previous and Next step only through the ones with a page",
      !!list && !list.includes("aside-never"), list);

    // Each chip keeps its own choices.
    await choose(r, "Show one area", "Hall");
    chip("Watched").click();
    await settle();
    chip("Set aside").click();
    await settle();
    check("going back to a chip finds its Area choice as it was", select(r, "Show one area").value === "Hall" && names(r).join() === "Retired Sensor",
      [select(r, "Show one area").value, names(r)]);
    await choose(r, "Show one area", "");

    // A network's filter belongs to the watched devices.
    opened.panel._devicesOnNetwork("z2m");
    await settle();
    chip("Excluded").click();
    await settle();
    check("a network's filter leaves the Excluded chip whole", bodyRows(r).length === 3 && !r.querySelector(".pane").textContent.includes("Showing the devices on"), names(r));
    chip("Watched").click();
    await settle();
    check("and still holds on Watched", r.querySelector(".pane").textContent.includes("Showing the devices on"));
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
