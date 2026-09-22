// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: frontend/panel.js, Version: 0.22.25 (2026-09-22)
//
// The Device Sentinel dashboard. One plain custom element: no framework,
// no build step. Data comes from the integration's WebSocket commands
// when the page opens and when Refresh is pressed, never on a timer, so
// nothing moves while a person reads. The change marker is the one live
// thing: when it moves past the snapshot on screen, Refresh lights up.
// Colours are Home Assistant's theme variables, so the page follows
// light, dark and custom themes. Every name is set as text, never as
// markup, because names come from a person's own registry.

const TABS = [
  "Daily Brief",
  "Problem List",
  "Battery Trends",
  "Signal Trends",
  "Classification",
  "Integrations",
  "Devices",
  "Recommendations",
];
// Each tab's own address under the panel, so the back button, a reload
// and a bookmark all return to the tab that was on screen (0.22.14,
// from the second fleet's review). The Daily Brief owns the bare
// address, so opening the dashboard lands on it.
const TAB_SLUG = Object.fromEntries(TABS.map((name) => [name, name.toLowerCase().replace(/ /g, "-")]));
const TAB_BY_SLUG = Object.fromEntries(TABS.map((name) => [TAB_SLUG[name], name]));
const BUILT = new Set(["Daily Brief", "Problem List", "Battery Trends", "Signal Trends", "Classification", "Integrations", "Devices", "Recommendations"]);
const FILTERS = [
  ["all", "All"],
  ["watched", "Watched"],
  ["muted", "Muted"],
  ["set_aside", "Set aside"],
];
const PROBLEM_FILTERS = [
  ["all", "All"],
  ["open", "Open"],
  ["acknowledged", "Acknowledged"],
];
const SETTINGS_PATH = "/config/integrations/integration/device_sentinel";
const INTEGRATION_FILTERS = [
  ["all", "All"],
  ["watched", "Watched"],
  ["excluded", "Excluded"],
  ["muted", "Muted"],
  ["service", "Service only"],
  ["no_hardware", "No hardware"],
  ["helper", "Helper"],
];
const DEVICE_FILTERS = [
  ["all", "All"],
  ["problem", "With a problem"],
  ["muted", "Muted"],
];
const RANGES = [["all", "All"], [360, "360 Days"], [180, "180 Days"], [90, "90 Days"], [30, "30 Days"], [14, "14 Days"]];
const STATUS_WORDS = {
  reporting: ["Reporting", "var(--success-color, #43a047)"],
  frozen: ["Frozen", "var(--error-color, #db4437)"],
  unavailable: ["Unavailable", "var(--error-color, #db4437)"],
  unknown: ["Unknown", "var(--warning-color, #ffa600)"],
  never_reported: ["Never reported", "var(--error-color, #db4437)"],
  // Nobody is watching it, so there is no verdict to give (0.22.24).
  set_aside: ["Set aside", "var(--disabled-text-color, #888)"],
};
const LIVE_SECONDS = 60;
// The print view: dark text on white whatever the theme, the same
// colour names the page draws with, and nothing that only works on a
// screen. A browser's print dialog offers "Save as PDF" as well as a
// printer, so this is also how a page is saved.
const PRINT_STYLE = `
  :root { --primary-background-color: #ffffff; --card-background-color: #ffffff;
    --secondary-background-color: #f2f2f2; --primary-text-color: #1a1a19; --secondary-text-color: #5f5e5a;
    --divider-color: #d3d1c7; --primary-color: #1e6fb8; --text-primary-color: #ffffff;
    --success-color: #2e7d32; --warning-color: #c77700; --error-color: #c62828; --info-color: #4f7cac;
    --disabled-text-color: #9e9e9e; color-scheme: light; }
  /* Backgrounds are dropped from a printout unless the page asks for
     them, which would lose the rhythm bars, the status bar and the
     chips. */
  * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  html, body { background: #ffffff; color: #1a1a19; margin: 0; }
  body { font-family: Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 12px; padding: 16px; }
  .printhead { border-bottom: 1px solid #d3d1c7; margin-bottom: 12px; padding-bottom: 8px; }
  .printhead h1 { margin: 0; font-size: 18px; font-weight: 500; }
  .printhead p { margin: 4px 0 0; color: #5f5e5a; }
  button.chip[aria-expanded], .sort::after { display: none; }
  button { border: 0; background: none; color: inherit; font: inherit; padding: 0; }
  button.chip { border: 1px solid #d3d1c7; border-radius: 12px; padding: 2px 8px; }
  button.chip[aria-pressed="true"] { border-color: #1e6fb8; color: #1e6fb8; }
  a { color: #1e6fb8; text-decoration: none; }
  /* The day table keeps its columns across a page break: a browser
     sizes each page's columns from the rows on that page, and the
     older days carry no battery or signal reading. */
  table.days { table-layout: fixed; width: 100%; }
  /* A pinned table keeps a minimum width on screen so a phone scrolls
     it; on paper it fits the page instead. */
  table.pinned { min-width: 0 !important; }
  table.days th:nth-child(1), table.days td:nth-child(1) { width: 8%; }
  table.days th:nth-child(2), table.days td:nth-child(2) { width: 8%; }
  table.days th:nth-child(3), table.days td:nth-child(3) { width: 11%; }
  table.days th:nth-child(4), table.days td:nth-child(4) { width: 9%; }
  table.days th:nth-child(5), table.days td:nth-child(5) { width: 11%; }
  table.days th:nth-child(6), table.days td:nth-child(6) { width: 9%; }
  table.days th:nth-child(7), table.days td:nth-child(7) { width: 44%; }
  th, td { overflow-wrap: anywhere; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  .chart, .stat, .devstatus, .rec { break-inside: avoid; }
  .scroll { overflow: visible; }
  @page { margin: 12mm; }
`;

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function ago(iso, at) {
  if (!iso) return "never";
  return `${span((at - new Date(iso).getTime()) / 1000)} ago`;
}

const STANDING = {
  watched: "Watched",
  excluded: "Excluded",
  muted: "Muted",
  service: "Service only",
  no_hardware: "No hardware",
  helper: "Helper",
};
// The key under the Integrations table, the same words as
// classification.md's (0.22.21). A test holds the two to one text.
const STANDING_KEY = [
  ["Watched", "It owns devices Device Sentinel watches."],
  ["Excluded", "It is on your exclusion list, in Exclusions and Muting."],
  ["Muted", "It is muted, in Exclusions and Muting: its devices are watched but never reported."],
  ["Service only", "Its devices report themselves as services, so there is nothing to watch."],
  ["No hardware", "An add-on with no hardware of its own. It puts its entities on devices other integrations own, as Battery Notes does, and they never count as the device reporting."],
  ["Helper", "A Home Assistant helper you linked to a device. Its entities never count as the device reporting."],
];
const SVG_NS = "http://www.w3.org/2000/svg";

function checkIcon(label) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", label);
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M4 12l5 5L20 6");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.5");
  svg.append(path);
  return svg;
}

// Past two days a duration reads in days, and past a week and a half
// in weeks, in halves rounded down, the same rule and the same words
// as durations.py (0.22.25). A test holds the two to one wording.
function halves(value, noun) {
  const count = Math.floor(value * 2);
  const whole = Math.floor(count / 2);
  if (count % 2 === 0) return `${whole} ${noun}${whole === 1 ? "" : "s"}`;
  if (whole === 0) return `half a ${noun}`;
  if (whole === 1) return `a ${noun} and a half`;
  return `${whole} and a half ${noun}s`;
}

function span(seconds) {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 1.5 * 7 * 86400) return halves(seconds / (7 * 86400), "week");
  return halves(seconds / 86400, "day");
}

// The header's and the printout's moment: the time, then the date in
// long form, both in the browser's language, so a printout or a screen
// capture says which day it shows (0.22.13, from the second fleet's
// review). The language decides the order, the month's name and the
// 12 or 24 hour clock.
function longMoment(date) {
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${time}, ${date.toLocaleDateString([], { dateStyle: "long" })}`;
}

// Home Assistant's own cog, mdiCog from Material Design Icons
// (@mdi/js 7.4.47, Apache-2.0), so the gear looks like the one in its
// Settings.
const COG_PATH = "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z";

// Home Assistant's printer, mdiPrinter from the same icon set.
const PRINTER_PATH = "M18,3H6V7H18M19,12A1,1 0 0,1 18,11A1,1 0 0,1 19,10A1,1 0 0,1 20,11A1,1 0 0,1 19,12M16,19H8V14H16M19,8H5A3,3 0 0,0 2,11V17H6V21H18V17H22V11A3,3 0 0,0 19,8Z";

// Where a page was opened from, read out of its address (0.22.15). A
// tab is named by its slug. A device or integration page is named by
// its own address, which may carry an origin of its own, so the chain
// can be walked back to the tab it began on. Anything else names
// nothing, and the page falls back to Devices or Integrations.
function readOrigin(from) {
  if (!from) return null;
  if (TAB_BY_SLUG[from]) return { tab: TAB_BY_SLUG[from] };
  const page = /^\/(device|integration)\/([^/?]+)(?:\?(.*))?$/.exec(from);
  if (!page) return null;
  return {
    kind: page[1], id: decodeURIComponent(page[2]), path: from,
    inner: new URLSearchParams(page[3] || "").get("from"),
  };
}

function rootTab(from) {
  let origin = readOrigin(from);
  // Bounded, so an address built by hand cannot loop.
  for (let depth = 0; origin && depth < 8; depth += 1) {
    if (origin.tab) return origin.tab;
    origin = readOrigin(origin.inner);
  }
  return null;
}

// How much room a column needs, by its heading (0.22.17, from the
// second fleet's review: the columns moved whenever a filter changed).
// A table's widths depend only on its headings, never on the rows a
// filter or a sort leaves, so its columns stay still, and two tables
// with the same headings line up. Names and free text get more room
// than numbers, and the first column always gets a name's share.
const COLUMN_SHARE = {
  "DEVICE": 3, "MAKER AND MODEL": 3, "WHAT HAPPENED": 3,
  "MUTED": 2.5, "WHICH ONE": 2.5, "WHAT": 2.5,
  "PROBLEM": 2.2, "SET ASIDE": 2.2, "STANDING": 2, "DEVICES THAT WENT DOWN": 2,
  "INTEGRATION": 1.6, "SINCE": 1.4, "TIME": 1.4, "WENT DOWN": 1.4, "SILENT SINCE": 1.4,
};
// The history table's own widths, as its printout has always used.
const HISTORY_WIDTHS = [8, 8, 11, 9, 11, 9, 44];

function pinTable(table) {
  if (table.classList.contains("pinned")) return;
  const heads = table.tHead && table.tHead.rows[0]
    ? [...table.tHead.rows[0].cells].map((cell) => cell.textContent.trim())
    : null;
  const count = heads ? heads.length : (table.rows[0] ? table.rows[0].cells.length : 0);
  if (!count) return;
  let shares;
  if (table.classList.contains("days") && count === HISTORY_WIDTHS.length) shares = HISTORY_WIDTHS;
  else if (!heads) shares = count === 2 ? [1, 2] : Array(count).fill(1);
  else {
    shares = heads.map((head, index) => {
      const share = COLUMN_SHARE[head] || (head === "" ? 0.5 : 1);
      return index === 0 && head !== "" ? Math.max(share, 2.5) : share;
    });
  }
  const total = shares.reduce((sum, share) => sum + share, 0);
  const group = document.createElement("colgroup");
  for (const share of shares) {
    const col = document.createElement("col");
    col.style.width = `${((share / total) * 100).toFixed(3)}%`;
    group.append(col);
  }
  table.prepend(group);
  table.classList.add("pinned");
  // Seventy pixels per share: on a phone the table scrolls sideways in
  // its box rather than crushing its columns.
  if (table.parentElement && table.parentElement.classList.contains("scroll")) {
    table.style.minWidth = `${Math.round(total * 70)}px`;
  }
}

function moment(iso) {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const STATE_COLOURS = {
  running: "var(--success-color, #43a047)",
  binding: "var(--warning-color, #ffa600)",
  down: "var(--error-color, #db4437)",
};

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "style") node.style.cssText = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const STYLE = `
  :host { display: block; min-height: 100%; background: var(--primary-background-color);
    color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display: flex; align-items: center; gap: 12px; height: 56px; padding: 0 16px;
    border-bottom: 1px solid var(--divider-color); font-size: 20px; }
  .gear, .print { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px;
    border: 0; border-radius: 22px; padding: 0; background: transparent; color: var(--primary-text-color); cursor: pointer; }
  .print { margin-left: auto; }
  .gear:hover, .print:hover { background: var(--secondary-background-color, rgba(127,127,127,0.1)); text-decoration: none; }
  .body { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
  .status { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
  .card { background: var(--card-background-color, var(--ha-card-background)); border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, none); }
  .part { padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
  .part .label { font-size: 13px; color: var(--secondary-text-color); }
  .part .state { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 500; }
  .dot { width: 10px; height: 10px; border-radius: 5px; background: var(--disabled-text-color, #888); }
  .actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  button, select { font: inherit; font-size: 14px; font-weight: 500; }
  .pill { min-height: 44px; padding: 0 18px; border-radius: 22px; cursor: pointer;
    background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .pill:disabled { opacity: 0.6; cursor: default; }
  .pill.new { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .maint { display: flex; align-items: center; border: 1px solid var(--divider-color); border-radius: 22px;
    background: var(--card-background-color); }
  .maint .pill { border: 0; background: transparent; }
  .maint select { min-height: 44px; background: transparent; color: var(--primary-text-color); border: 0;
    border-left: 1px solid var(--divider-color); padding: 0 12px; border-radius: 0 22px 22px 0; }
  .asof { margin-left: auto; font-size: 13px; color: var(--secondary-text-color); }
  .tabs { display: flex; gap: 4px; padding: 0 12px; border-bottom: 1px solid var(--divider-color); overflow-x: auto; }
  .tab { min-height: 48px; padding: 0 16px; background: transparent; border: 0; border-bottom: 2px solid transparent;
    color: var(--secondary-text-color); cursor: pointer; white-space: nowrap; }
  .tab[aria-selected="true"] { color: var(--primary-color); border-bottom-color: var(--primary-color); }
  .pane { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
  .muted { color: var(--secondary-text-color); }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { min-height: 36px; padding: 0 14px; border-radius: 18px; cursor: pointer; background: transparent;
    color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .chip[aria-pressed="true"] { color: var(--primary-color); border-color: var(--primary-color); }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.pinned { table-layout: fixed; }
  table.pinned th, table.pinned td { overflow-wrap: anywhere; }
  th { text-align: left; font-size: 12px; font-weight: 500; letter-spacing: 0.04em; color: var(--secondary-text-color);
    padding: 8px 10px; border-bottom: 1px solid var(--divider-color); }
  td { padding: 9px 10px; border-bottom: 1px solid var(--divider-color); }
  a { color: var(--primary-color); text-decoration: none; }
  button.entity { background: none; border: 0; padding: 0; margin: 0; cursor: pointer; text-align: left;
    font: inherit; font-family: var(--code-font-family, monospace); font-size: 13px; color: var(--primary-color); }
  button.entity:hover { text-decoration: underline; }
  a:hover { text-decoration: underline; }
  .error { color: var(--error-color, #db4437); }
  .sort { background: transparent; border: 0; padding: 0; color: inherit; font: inherit; letter-spacing: inherit;
    cursor: pointer; display: inline-flex; align-items: center; gap: 4px; min-height: 32px; }
  .sort[aria-sort="ascending"]::after { content: "\\25B2"; font-size: 9px; }
  .sort[aria-sort="descending"]::after { content: "\\25BC"; font-size: 9px; }
  .ackcell { width: 56px; }
  .ackbox { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; cursor: pointer; }
  .ackbox input { width: 20px; height: 20px; accent-color: var(--primary-color); cursor: pointer; }
  tr.acked td { opacity: 0.55; }
  .rec { border: 1px solid var(--divider-color); border-radius: 10px; padding: 14px 16px; display: flex;
    flex-direction: column; gap: 6px; }
  .rec h3 { margin: 0; font-size: 15px; font-weight: 500; color: var(--primary-color); }
  .rec p { margin: 0; line-height: 1.5; }
  .devstatus { border: 1px solid var(--divider-color); border-radius: 10px; padding: 14px 16px; display: flex;
    flex-direction: column; gap: 8px; }
  .statusline { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
  .bar { height: 10px; border-radius: 5px; background: var(--divider-color); overflow: hidden; }
  .bar > div { height: 100%; }
  .readings { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
  .reading .v { font-size: 22px; font-weight: 500; }
  .twocol { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; }
  .kv td { padding: 7px 0; border-bottom: 1px solid var(--divider-color); }
  .kv td:first-child { color: var(--secondary-text-color); width: 42%; }
  .gaps { display: flex; align-items: flex-end; gap: 4px; height: 140px; border-bottom: 1px solid var(--divider-color); }
  .gaps > div { flex: 1; border-radius: 3px 3px 0 0; background: var(--primary-color); }
  .bank { display: flex; align-items: flex-end; gap: 6px; height: 150px; border-bottom: 1px solid var(--divider-color); }
  .bank .band { flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; }
  .bank .band > div:last-child { background: var(--primary-color); border-radius: 3px 3px 0 0; }
  .bank .count { text-align: center; font-size: 11px; color: var(--secondary-text-color); padding-bottom: 2px; }
  .gaps > div.aside { background: repeating-linear-gradient(45deg, var(--divider-color), var(--divider-color) 3px, transparent 3px, transparent 6px); }
  .chart { border: 1px solid var(--divider-color); border-radius: 10px; padding: 14px 16px; display: flex;
    flex-direction: column; gap: 8px; }
  .chart svg { width: 100%; height: auto; }
  .chart .axis { fill: var(--secondary-text-color); font-size: 11px; }
  .chip[aria-disabled="true"] { opacity: 0.4; cursor: default; border-style: dashed; }
  .figures th, .figures td { padding: 6px 8px; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--secondary-text-color); align-items: center; }
  .legend .swatch { display: inline-block; width: 18px; vertical-align: middle; margin-right: 6px; }
  .readout { background: var(--secondary-background-color, rgba(127,127,127,0.1)); border-radius: 8px; padding: 10px 12px; min-height: 22px; }
  .small { font-size: 12px; color: var(--secondary-text-color); }
  .num { text-align: right; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
  .stat { border: 1px solid var(--divider-color); border-radius: 10px; padding: 12px 14px; }
  .stat .v { font-size: 22px; font-weight: 500; }
  .pagehead { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; }
  .pagehead h2 { margin: 0; font-size: 22px; font-weight: 500; }
  .links { display: flex; gap: 16px; flex-wrap: wrap; }
  h3.section { margin: 8px 0 0; font-size: 16px; font-weight: 500; }
`;

class DeviceSentinelPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "Daily Brief";
    this._filter = "all";
    this._problemFilter = "all";
    this._problemSort = null;
    this._integrationFilter = "watched";
    this._integrationSort = null;
    this._base = "/device-sentinel";
    this._view = null;
    this._page = null;
    this._deviceFilter = "all";
    this._deviceSort = null;
    // The graphs' range carries from one device page to the next.
    this._range = "all";
    this._hover = null;
    this._tableOpen = false;
    this._briefDay = null;
    this._liveTimer = null;
    this._started = false;
    this._snapshot = null;
    this._shownMarker = null;
    this._latestMarker = null;
    this._unsubscribe = null;
    this._narrow = false;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    // Entity states arrive with every hass update, so the readings on
    // a device page redraw the moment one changes.
    if (this._readingsBox && this._view && this._view.kind === "device") this._paintReadings();
    if (!this._started) {
      this._started = true;
      this._build();
      this._refresh();
      this._subscribe();
    }
  }

  set route(route) {
    if (route && route.prefix) this._base = route.prefix;
    const path = (route && route.path) || "";
    const integration = /^\/integration\/([^/]+)/.exec(path);
    const device = /^\/device\/([^/]+)/.exec(path);
    const next = integration
      ? { kind: "integration", domain: decodeURIComponent(integration[1]) }
      : device ? { kind: "device", id: decodeURIComponent(device[1]) } : null;
    // A device or integration page carries, in its address, the page
    // it was opened from: a tab, or another page with an origin of its
    // own. Its back link leads to that page, and its highlighted tab is
    // the one the chain began on, so a reload keeps both. Opened from
    // anywhere else, it belongs to Devices or Integrations. A plain
    // address names its tab; one that names nothing falls back to the
    // Daily Brief.
    const from = next ? new URLSearchParams(window.location.search).get("from") || "" : "";
    const tab = next
      ? rootTab(from) || (next.kind === "device" ? "Devices" : "Integrations")
      : TAB_BY_SLUG[path.replace(/^\/+|\/+$/g, "")] || "Daily Brief";
    const changed = JSON.stringify(next) !== JSON.stringify(this._view)
      || tab !== this._tab || from !== this._from;
    this._view = next;
    this._tab = tab;
    this._from = from;
    this._origin = readOrigin(from);
    if (this._started && changed) {
      this._paintTabs();
      this._openView();
    }
  }

  _tabPath(name) {
    return name === "Daily Brief" ? this._base : `${this._base}/${TAB_SLUG[name]}`;
  }

  // The address of the page on screen, as an origin for the next one:
  // a tab's slug, or this page's own address with its own origin.
  _here() {
    if (!this._view) return TAB_SLUG[this._tab];
    const id = this._view.kind === "device" ? this._view.id : this._view.domain;
    const own = this._from ? `?from=${encodeURIComponent(this._from)}` : "";
    return `/${this._view.kind}/${encodeURIComponent(id)}${own}`;
  }

  _devicePath(id) {
    return `${this._base}/device/${encodeURIComponent(id)}?from=${encodeURIComponent(this._here())}`;
  }

  _integrationPath(domain) {
    return `${this._base}/integration/${encodeURIComponent(domain)}?from=${encodeURIComponent(this._here())}`;
  }

  // The link at the top of a device or integration page: the page it
  // was opened from, by name, or its tab when it came from a tab or
  // from nowhere the address can name.
  _backLink() {
    const origin = this._origin;
    if (origin && origin.kind) {
      const name = origin.kind === "integration" ? this._integrationName(origin.id) : this._deviceName(origin.id);
      return this._link(`\u2039 ${name}`, `${this._base}${origin.path}`);
    }
    return this._link(`\u2039 ${this._tab}`, this._tabPath(this._tab));
  }

  _integrationName(domain) {
    const rows = (this._snapshot && this._snapshot.integrations && this._snapshot.integrations.rows) || [];
    const row = rows.find((r) => r.domain === domain);
    return row ? row.name : domain;
  }

  _deviceName(id) {
    const rows = (this._snapshot && this._snapshot.classification && this._snapshot.classification.rows) || [];
    const row = rows.find((r) => r.device_id === id);
    return row ? row.name : "Device";
  }

  async _fetchView() {
    const view = this._view;
    if (!view) return null;
    try {
      return view.kind === "device"
        ? await this._call({ type: "device_sentinel/device", device_id: view.id })
        : await this._call({ type: "device_sentinel/integration", domain: view.domain });
    } catch (err) {
      if (err.code !== "not_found") return { error: String(err.message || err) };
      return {
        error: view.kind === "device"
          ? "Device Sentinel has no record of that device."
          : "No device belongs to that integration.",
      };
    }
  }

  _setLive() {
    // A device page is the one live view: it asks again every minute,
    // on the integration's own tick, and stops when left.
    const live = this._view && this._view.kind === "device";
    if (live && !this._liveTimer) {
      this._liveTimer = setInterval(async () => {
        if (!this._view || this._view.kind !== "device") return;
        this._page = await this._fetchView();
        this._paintPane();
      }, LIVE_SECONDS * 1000);
    } else if (!live && this._liveTimer) {
      clearInterval(this._liveTimer);
      this._liveTimer = null;
    }
  }

  async _openView() {
    this._hover = null;
    this._setLive();
    if (!this._view) {
      this._page = null;
      this._paintPane();
      return;
    }
    this._pane.replaceChildren(el("p", { class: "muted" }, "Loading."));
    this._page = await this._fetchView();
    this._paintPane();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
  }

  connectedCallback() {
    if (this._started && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    if (this._liveTimer) {
      clearInterval(this._liveTimer);
      this._liveTimer = null;
    }
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  _call(message) {
    return this._hass.callWS(message);
  }

  async _subscribe() {
    try {
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => {
          this._latestMarker = event.marker;
          this._paintRefresh();
        },
        { type: "device_sentinel/subscribe_changes" },
      );
    } catch (err) {
      this._unsubscribe = null;
    }
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _link(text, path) {
    return el("a", {
      href: path,
      onclick: (ev) => {
        ev.preventDefault();
        this._navigate(path);
      },
    }, text);
  }

  _build() {
    const root = this.shadowRoot;
    root.append(el("style", {}, STYLE));
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    // The gear goes to the integration's own page, where Configure is
    // one click away. Home Assistant gives a custom panel no supported
    // way to open the options dialog itself (0.22.13).
    const settings = "/config/integrations/integration/device_sentinel";
    const gear = el("a", {
      class: "gear", href: settings, title: "Device Sentinel settings",
      "aria-label": "Device Sentinel settings",
      onclick: (ev) => {
        ev.preventDefault();
        this._navigate(settings);
      },
    }, svg("svg", { width: "24", height: "24", viewBox: "0 0 24 24", "aria-hidden": "true" },
      svg("path", { d: COG_PATH, fill: "currentColor" })));
    // Print beside the gear: both act on the dashboard itself, not on
    // the house (0.22.15). The toolbar is not part of a printout.
    const printer = el("button", {
      class: "print", type: "button", title: "Print this page", "aria-label": "Print this page",
      onclick: () => this._print(),
    }, svg("svg", { width: "24", height: "24", viewBox: "0 0 24 24", "aria-hidden": "true" },
      svg("path", { d: PRINTER_PATH, fill: "currentColor" })));
    root.append(el("div", { class: "toolbar" }, this._menu, "Device Sentinel", printer, gear));

    this._statusRow = el("section", { class: "status", "aria-label": "Status" });
    this._refreshButton = el("button", { class: "pill", type: "button", onclick: () => this._refresh() }, "Refresh");
    this._maintButton = el("button", { class: "pill", type: "button", onclick: () => this._maintenance() }, "Maintenance Mode");
    this._minutes = el("select", { "aria-label": "Maintenance length" });
    this._asOf = el("span", { class: "asof" });
    const enable = (label, action) =>
      el("button", { class: "pill", type: "button", onclick: () => this._enable(label, action) }, label);
    const actions = el(
      "section",
      { class: "actions", "aria-label": "Actions" },
      this._refreshButton,
      el("div", { class: "maint" }, this._maintButton, this._minutes),
      enable("Enable Signals", "enable_signals"),
      enable("Enable Last Seen", "enable_last_seen"),
      enable("Enable Battery", "enable_battery"),
      this._asOf,
    );

    this._tabRow = el("div", { class: "tabs", role: "tablist", "aria-label": "Reports" });
    this._pane = el("div", { class: "pane", role: "tabpanel" });
    // Every table the pane gains is pinned as it arrives, whichever tab,
    // page, filter or sort drew it, before the browser lays it out.
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE) continue;
          if (node.tagName === "TABLE") pinTable(node);
          node.querySelectorAll("table").forEach(pinTable);
        }
      }
    }).observe(this._pane, { childList: true, subtree: true });
    root.append(
      el("div", { class: "body" }, this._statusRow, actions,
        el("div", { class: "card" }, this._tabRow, this._pane)),
    );
    this._paintTabs();
  }

  _print() {
    // The current tab or page, copied into a hidden frame and printed
    // from there, so the printout holds only what is on screen and not
    // Home Assistant's sidebar and bars. Built with DOM calls, as the
    // rest of the page is: nothing is written as markup.
    const view = this._view && this._view.kind === "device" && this._page && this._page.identity
      ? this._page.identity.name
      : this._view && this._view.kind === "integration" && this._page && this._page.name
        ? this._page.name
        : this._tab;
    const frame = document.createElement("iframe");
    frame.setAttribute("aria-hidden", "true");
    frame.setAttribute("tabindex", "-1");
    // Off the side of the screen rather than hidden: a browser will
    // not print a frame it treats as not rendered, and prints the
    // whole page instead, sidebar and all.
    frame.style.cssText = "position:fixed;left:-10000px;top:0;width:1100px;height:600px;border:0;opacity:0";
    // On the page's own body, where every browser gives a frame a
    // document of its own; it is hidden, and removed after printing.
    document.body.append(frame);
    const doc = frame.contentDocument;
    doc.title = `Device Sentinel: ${view}`;
    const style = doc.createElement("style");
    style.textContent = STYLE + PRINT_STYLE;
    doc.head.append(style);
    const head = doc.createElement("div");
    head.className = "printhead";
    const title = doc.createElement("h1");
    title.textContent = `Device Sentinel: ${view}`;
    const when = doc.createElement("p");
    // The same long form as the header, so screen and paper agree.
    const taken = this._snapshot ? longMoment(this._snapshot.at) : "";
    when.textContent = `${taken ? `Data as of ${taken}. ` : ""}Printed ${longMoment(new Date())}.`;
    head.append(title, when);
    doc.body.append(head, doc.importNode(this._pane, true));
    // A browser names the PDF after the tab's title, not the print
    // view's, so the tab carries the name for the moment of printing.
    const tabTitle = document.title;
    const stamp = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    document.title = `Device Sentinel - ${view} - ${stamp.getFullYear()}-${pad(stamp.getMonth() + 1)}-${pad(stamp.getDate())} ${pad(stamp.getHours())}${pad(stamp.getMinutes())}`;
    const done = () => {
      document.title = tabTitle;
      frame.remove();
    };
    frame.contentWindow.addEventListener("afterprint", done);
    setTimeout(done, 60000);
    frame.contentWindow.focus();
    frame.contentWindow.print();
    // The name is taken when printing starts, so the tab's own title
    // goes back at once rather than waiting for the dialog to close.
    document.title = tabTitle;
  }

  async _refresh() {
    this._refreshButton.disabled = true;
    try {
      const [status, classification, problems, recommendations, integrations, devices, brief, battery, signal] = await Promise.all([
        this._call({ type: "device_sentinel/status" }),
        this._call({ type: "device_sentinel/classification" }),
        this._call({ type: "device_sentinel/problem_list" }),
        this._call({ type: "device_sentinel/recommendations" }),
        this._call({ type: "device_sentinel/integrations" }),
        this._call({ type: "device_sentinel/devices" }),
        this._call({ type: "device_sentinel/brief", ...(this._briefDay ? { day: this._briefDay } : {}) }),
        this._call({ type: "device_sentinel/battery_trends" }),
        this._call({ type: "device_sentinel/signal_trends" }),
      ]);
      this._snapshot = { status, classification, problems, recommendations, integrations, devices, brief, battery, signal, at: new Date() };
      if (this._view) this._page = await this._fetchView();
      this._shownMarker = status.marker;
      if (this._latestMarker === null || this._latestMarker < status.marker) this._latestMarker = status.marker;
      this._paintStatus();
      this._paintPane();
    } catch (err) {
      this._pane.replaceChildren(el("p", { class: "error" }, `Device Sentinel did not answer: ${err.message || err.code || err}`));
    } finally {
      this._refreshButton.disabled = false;
      this._paintRefresh();
    }
  }

  _paintRefresh() {
    const fresh = this._latestMarker !== null && this._shownMarker !== null && this._latestMarker > this._shownMarker;
    this._refreshButton.classList.toggle("new", fresh);
    this._refreshButton.textContent = fresh ? "Refresh: new data" : "Refresh";
  }

  _paintStatus() {
    const { status, at } = this._snapshot;
    const parts = status.parts.map((part) =>
      el("div", { class: "card part" },
        el("div", { class: "label" }, part.name),
        el("div", { class: "state" },
          el("span", { class: "dot", style: STATE_COLOURS[part.state] ? `background:${STATE_COLOURS[part.state]}` : "" }),
          part.state)));
    const maint = status.maintenance;
    const until = maint.open ? new Date(maint.until).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : null;
    parts.push(el("div", { class: "card part" },
      el("div", { class: "label" }, "Maintenance"),
      el("div", { class: "state" },
        el("span", { class: "dot", style: maint.open ? "background:var(--warning-color, #ffa600)" : "" }),
        maint.open ? `open until ${until}` : "off")));
    this._statusRow.replaceChildren(...parts);

    this._maintButton.textContent = maint.open ? "End Maintenance" : "Maintenance Mode";
    this._minutes.disabled = maint.open;
    const chosen = this._minutes.value || String(maint.default_minutes);
    this._minutes.replaceChildren(...[5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60].map((m) =>
      el("option", { value: String(m), ...(String(m) === chosen ? { selected: "" } : {}) }, `${m} min`)));
    this._asOf.textContent = `As of ${longMoment(at)}`;
  }

  _paintTabs() {
    this._tabRow.replaceChildren(...TABS.map((name) =>
      el("button", {
        class: "tab", type: "button", role: "tab", "aria-selected": String(name === this._tab),
        onclick: () => {
          // The address moves, and the route that follows paints the
          // tab, the same way a link or the back button does.
          if (!this._view && name === this._tab) return;
          this._navigate(this._tabPath(name));
        },
      }, name)));
  }

  _paintPane() {
    if (!BUILT.has(this._tab)) {
      this._pane.replaceChildren(el("p", { class: "muted" }, `${this._tab} arrives in a later release.`));
      return;
    }
    if (!this._snapshot) {
      this._pane.replaceChildren(el("p", { class: "muted" }, "Loading."));
      return;
    }
    if (this._view && this._view.kind === "integration") this._paintIntegrationPage();
    else if (this._view && this._view.kind === "device") this._paintDevicePage();
    else if (this._tab === "Devices") this._paintDevices();
    else if (this._tab === "Daily Brief") this._paintBrief();
    else if (this._tab === "Battery Trends") this._paintBatteryTrends();
    else if (this._tab === "Signal Trends") this._paintSignalTrends();
    else if (this._tab === "Integrations") this._paintIntegrations();
    else if (this._tab === "Problem List") this._paintProblems();
    else if (this._tab === "Recommendations") this._paintRecommendations();
    else this._paintClassification();
  }

  _sortHeader(label, key) {
    const current = this._problemSort;
    const direction = current && current.key === key ? current.dir : null;
    const button = el("button", {
      class: "sort", type: "button",
      "aria-sort": direction === 1 ? "ascending" : direction === -1 ? "descending" : "none",
      onclick: () => {
        this._problemSort = { key, dir: direction === 1 ? -1 : 1 };
        this._paintProblems();
      },
    }, label);
    return button;
  }

  _paintProblems() {
    const all = this._snapshot.problems.rows;
    const at = this._snapshot.at.getTime();
    const acked = all.filter((row) => row.acknowledged).length;
    const keep = {
      all: () => true,
      open: (row) => !row.acknowledged,
      acknowledged: (row) => row.acknowledged,
    }[this._problemFilter];
    let rows = all.filter(keep);
    const sort = this._problemSort;
    if (sort) {
      const value = {
        acknowledged: (row) => (row.acknowledged ? 1 : 0),
        name: (row) => row.name.toLowerCase(),
        integration: (row) => row.integration.toLowerCase(),
        since: (row) => (row.since ? new Date(row.since).getTime() : 0),
      }[sort.key];
      rows = [...rows].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0) * sort.dir);
    }
    if (!all.length) {
      this._pane.replaceChildren(el("p", {}, "Nothing needs attention."));
      return;
    }
    const summary = el("p", { style: "margin:0" },
      `${all.length} ${all.length === 1 ? "problem" : "problems"}, worst first. ${acked} acknowledged.`);
    const chips = el("div", { class: "chips" },
      ...PROBLEM_FILTERS.map(([key, label]) => el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._problemFilter),
        onclick: () => {
          this._problemFilter = key;
          this._paintProblems();
        },
      }, `${label} ${key === "all" ? all.length : key === "open" ? all.length - acked : acked}`)),
      sort ? el("button", {
        class: "chip", type: "button",
        onclick: () => {
          this._problemSort = null;
          this._paintProblems();
        },
      }, "Worst first") : null);
    const ackHead = this._sortHeader("", "acknowledged");
    ackHead.append(checkIcon("Acknowledged"));
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", { class: "ackcell" }, ackHead),
        el("th", {}, this._sortHeader("DEVICE", "name")),
        el("th", {}, this._sortHeader("INTEGRATION", "integration")),
        el("th", {}, "PROBLEM"),
        el("th", {}, this._sortHeader("SINCE", "since")),
        el("th", {}, "FOR"))),
      el("tbody", {}, ...rows.map((row) => el("tr", { class: row.acknowledged ? "acked" : "" },
        el("td", { class: "ackcell" }, el("label", { class: "ackbox" },
          el("input", {
            type: "checkbox", "aria-label": `Acknowledge ${row.name}`,
            ...(row.acknowledged ? { checked: "" } : {}),
            onchange: (ev) => this._acknowledge(row.uid, ev.target.checked),
          }))),
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, row.integration
          ? this._link(row.integration, this._integrationPath(row.integration))
          : ""),
        el("td", {}, row.problem),
        el("td", {}, row.since ? moment(row.since) : ""),
        el("td", {}, row.since ? span((at - new Date(row.since).getTime()) / 1000) : "")))));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table),
      el("p", { class: "muted", style: "margin:0;font-size:13px" },
        "Tick a problem to acknowledge it: it stays listed, but nothing reminds you of it again. "
        + "Its recovery is still reported, and the same tick shows on the to-do list."));
  }

  async _acknowledge(uid, acknowledged) {
    try {
      await this._call({ type: "device_sentinel/acknowledge", uid, acknowledged });
    } catch (err) {
      // Cleared since the snapshot; the refresh below shows it gone.
    }
    await this._refresh();
  }

  _paintRecommendations() {
    const { lines, closing } = this._snapshot.recommendations;
    if (!lines.length) {
      this._pane.replaceChildren(el("p", {}, "Nothing to recommend right now."));
      return;
    }
    const cards = lines.map((line) => {
      const at = line.indexOf(":");
      const title = at > 0 ? line.slice(0, at) : "";
      const rest = (at > 0 ? line.slice(at + 1) : line).trim();
      const body = rest.charAt(0).toUpperCase() + rest.slice(1);
      return el("article", { class: "rec" },
        title ? el("h3", {}, title) : null,
        el("p", {}, body),
        el("p", {}, this._link("Open Device Sentinel settings", SETTINGS_PATH)));
    });
    this._pane.replaceChildren(
      el("p", { style: "margin:0" }, `${lines.length} ${lines.length === 1 ? "change" : "changes"} you could make, the most important first.`),
      ...cards,
      el("p", { class: "muted", style: "margin:0;font-size:13px;line-height:1.5" }, closing));
  }

  _standingText(row) {
    return row.standing === "excluded" && row.first_seen ? "Excluded when first seen" : STANDING[row.standing];
  }

  _outageDevices(outage) {
    if (outage.open) return "still down";
    if (outage.devices === null || outage.devices === undefined) return "";
    if (!outage.worst) return `none of ${outage.devices}`;
    return `${outage.worst} of ${outage.devices}`;
  }

  _paintIntegrations() {
    const all = this._snapshot.integrations.rows;
    const counts = Object.fromEntries(INTEGRATION_FILTERS.map(([key]) =>
      [key, key === "all" ? all.length : all.filter((row) => row.standing === key).length]));
    let rows = all.filter((row) => this._integrationFilter === "all" || row.standing === this._integrationFilter);
    const sort = this._integrationSort;
    if (sort) {
      const value = {
        name: (row) => row.name.toLowerCase(),
        watched: (row) => row.watched,
        problems: (row) => row.problems,
        outages: (row) => row.outages,
      }[sort.key];
      rows = [...rows].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0) * sort.dir);
    }
    const header = (label, key) => {
      const direction = sort && sort.key === key ? sort.dir : null;
      return el("button", {
        class: "sort", type: "button",
        "aria-sort": direction === 1 ? "ascending" : direction === -1 ? "descending" : "none",
        onclick: () => {
          this._integrationSort = { key, dir: direction === 1 ? -1 : 1 };
          this._paintIntegrations();
        },
      }, label);
    };
    const watched = all.filter((row) => row.standing === "watched").length;
    // Each count takes its own verb: "1 is muted", never "1 are muted".
    const be = (n) => `${n} ${n === 1 ? "is" : "are"}`;
    const owns = (n) => `${n} ${n === 1 ? "owns" : "own"}`;
    const owners = all.length - counts.no_hardware - counts.helper;
    const riders = (counts.no_hardware
      ? ` ${counts.no_hardware} more ${counts.no_hardware === 1 ? "has" : "have"} no hardware of `
        + `${counts.no_hardware === 1 ? "its" : "their"} own and only ${counts.no_hardware === 1 ? "adds" : "add"} `
        + "entities to other integrations' devices."
      : "")
      + (counts.helper
        ? ` ${counts.helper} ${counts.helper === 1 ? "is a helper you linked to a device" : "are helpers you linked to devices"}.`
        : "");
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${owners} ${owners === 1 ? "integration owns" : "integrations own"} devices in your house. `
      + `${be(watched)} watched, ${be(counts.excluded)} excluded, ${be(counts.muted)} muted, and `
      + `${owns(counts.service)} only service devices, which have nothing to watch.${riders}`);
    const chips = el("div", { class: "chips" }, ...INTEGRATION_FILTERS.filter(([key]) =>
      key === "all" || counts[key] || this._integrationFilter === key).map(([key, label]) =>
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._integrationFilter),
        onclick: () => {
          this._integrationFilter = key;
          this._paintIntegrations();
        },
      }, `${label} ${counts[key]}`)));
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, header("INTEGRATION", "name")),
        el("th", {}, "STANDING"),
        el("th", { class: "num" }, header("WATCHED", "watched")),
        el("th", { class: "num" }, "MUTED"),
        el("th", { class: "num" }, "SET ASIDE"),
        el("th", { class: "num" }, header("PROBLEMS", "problems")),
        el("th", { class: "num" }, header("OUTAGES, 14 DAYS", "outages")))),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        // An integration with no hardware opens a page of the devices
        // it adds entities to (0.22.22).
        el("td", {}, this._link(row.name, this._integrationPath(row.domain)),
          " ", el("span", { class: "small" }, row.domain),
          (row.standing === "no_hardware" || row.standing === "helper") && row.adds_to
            ? el("span", { class: "small" }, `, on ${row.adds_to} ${row.adds_to === 1 ? "device" : "devices"}`) : null),
        el("td", {}, this._standingText(row)),
        el("td", { class: "num" }, row.watched ? String(row.watched) : ""),
        el("td", { class: "num" }, row.muted ? String(row.muted) : ""),
        el("td", { class: "num" }, row.set_aside ? String(row.set_aside) : ""),
        el("td", { class: "num" }, row.problems ? String(row.problems) : "",
          row.acknowledged ? el("span", { class: "small" }, ` +${row.acknowledged} ack`) : null),
        el("td", { class: "num" }, row.outages ? String(row.outages) : "")))));
    const key = el("div", { class: "muted", style: "font-size:13px;line-height:1.5" },
      el("p", { style: "margin:0 0 4px" }, "Standing, by kind:"),
      ...STANDING_KEY.map(([standing, meaning]) =>
        el("p", { style: "margin:0" }, el("strong", {}, standing), `: ${meaning}`)));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table), key);
  }

  // Home Assistant's own window for an entity, the one a dashboard
  // opens: its value, its history, and a gear to its settings.
  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      detail: { entityId }, bubbles: true, composed: true,
    }));
  }

  // An integration with no hardware of its own, or a helper: the
  // devices it adds entities to, each device opening its page here and
  // each entity opening Home Assistant's window (0.22.22).
  _paintRiderPage(page, back) {
    const count = page.devices.length;
    const what = page.standing === "helper"
      ? `Helper. A Home Assistant helper linked to ${count} ${count === 1 ? "device" : "devices"}.`
      : `No hardware. An add-on that puts its entities on ${count} ${count === 1 ? "device" : "devices"} other integrations own.`;
    const head = el("div", { class: "pagehead" },
      el("div", {},
        el("h2", {}, page.name, " ", el("span", { class: "small" }, page.domain)),
        el("div", { class: "muted" }, `${what} Its entities never count as ${count === 1 ? "that device" : "those devices"} reporting.`)),
      el("div", { class: "links" },
        this._link("Open in Home Assistant", `/config/integrations/integration/${encodeURIComponent(page.domain)}`)));
    const entity = (id) => el("button", {
      class: "entity", type: "button", title: "Open in Home Assistant",
      onclick: () => this._moreInfo(id),
    }, id);
    const table = el("div", { class: "scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["DEVICE", "AREA", "ITS ENTITIES"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...page.devices.map((d) => el("tr", {},
        el("td", {}, this._link(d.name, this._devicePath(d.device_id))),
        el("td", {}, d.area || ""),
        el("td", {}, ...d.entities.flatMap((id, i) => (i ? [el("br"), entity(id)] : [entity(id)]))))))));
    this._pane.replaceChildren(back, head, table);
  }

  _paintIntegrationPage() {
    const page = this._page;
    const back = el("p", { style: "margin:0" }, this._backLink());
    if (!page) {
      this._pane.replaceChildren(back, el("p", { class: "muted" }, "Loading."));
      return;
    }
    if (page.error) {
      this._pane.replaceChildren(back, el("p", {}, page.error));
      return;
    }
    if (page.rider) {
      this._paintRiderPage(page, back);
      return;
    }
    const watched = page.devices.filter((d) => d.watched).length;
    const muted = page.devices.filter((d) => d.muted).length;
    const aside = page.devices.length - watched;
    const open = page.devices.filter((d) => d.problem && !d.acknowledged).length;
    const acked = page.devices.filter((d) => d.acknowledged).length;
    const standingLine = `${this._standingText(page)}. ${watched} watched`
      + `${muted ? `, ${muted} of them muted` : ""}${aside ? `, ${aside} set aside` : ""}.`;
    const head = el("div", { class: "pagehead" },
      el("div", {},
        el("h2", {}, page.name, " ", el("span", { class: "small" }, page.domain)),
        el("div", { class: "muted" }, standingLine)),
      el("div", { class: "links" },
        this._link("Open in Home Assistant", `/config/integrations/integration/${encodeURIComponent(page.domain)}`),
        this._link("Device Sentinel settings", SETTINGS_PATH)));
    const stat = (label, value, note) => el("div", { class: "stat" },
      el("div", { class: "small" }, label), el("div", { class: "v" }, value, note ? el("span", { class: "small" }, ` ${note}`) : null));
    const stats = el("div", { class: "stats" },
      stat("Watched", String(watched)),
      stat("Problems", String(open + acked), acked ? `${acked} acknowledged` : ""),
      stat("Outages, 14 days", String(page.outages.length)),
      stat("Bursts of updates, 7 days", String(page.bursts)));
    const recs = page.recommendations.length
      ? page.recommendations.map((line) => el("p", { style: "margin:0;line-height:1.5" }, line))
      : [el("p", { class: "muted", style: "margin:0" }, "None for this integration.")];
    const outages = page.outages.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["WENT DOWN", "WHAT", "FOR", "DEVICES THAT WENT DOWN"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...page.outages.map((o) => el("tr", {},
          el("td", {}, moment(o.went_down)),
          el("td", {}, o.what),
          el("td", {}, o.open ? "still down" : o.duration === null ? "not recorded" : span(o.duration)),
          el("td", {}, this._outageDevices(o)))))))
      : el("p", { class: "muted", style: "margin:0" }, "None in the last 14 days.");
    const devices = el("div", { class: "scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["DEVICE", "STANDING", "PROBLEM"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...page.devices.map((d) => el("tr", {},
        el("td", {}, this._link(d.name, this._devicePath(d.device_id))),
        el("td", {}, d.watched ? (d.muted ? `Watched, muted: ${d.muted}` : "Watched") : `Set aside: ${d.set_aside}`),
        el("td", {}, d.problem ? `${d.problem}${d.acknowledged ? ", acknowledged" : ""}` : ""))))));
    this._pane.replaceChildren(back, head, stats,
      el("h3", { class: "section" }, "Recommendations"), ...recs,
      el("h3", { class: "section" }, "Outages, last 14 days"), outages,
      el("h3", { class: "section" }, `Devices `, el("span", { class: "small" }, `${page.devices.length}, problems first`)), devices);
  }

  async _briefGo(day) {
    // Stepping to another day asks for that day only; the rest of the
    // snapshot stays as it was.
    this._briefDay = day;
    try {
      const brief = await this._call({ type: "device_sentinel/brief", ...(day ? { day } : {}) });
      this._snapshot.brief = brief;
    } catch (err) {
      this._snapshot.brief = { error: "That day is no longer kept." };
    }
    this._paintBrief();
  }

  _paintBrief() {
    const brief = this._snapshot.brief;
    if (!brief || brief.error) {
      this._pane.replaceChildren(el("p", {}, (brief && brief.error) || "Loading."));
      return;
    }
    const at = this._snapshot.at.getTime();
    const dayDate = new Date(`${brief.day}T12:00:00`);
    const label = brief.is_today
      ? `Today, ${dayDate.toLocaleDateString([], { month: "short", day: "numeric" })}`
      : dayDate.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    const windowWords = brief.is_today
      ? `Midnight to ${new Date(brief.window.end).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}, still running.`
      : "Midnight to midnight.";
    const step = (text, day, ariaLabel) => el("button", {
      class: "chip", type: "button", "aria-disabled": String(!day), "aria-label": ariaLabel,
      onclick: () => {
        if (day) this._briefGo(day);
      },
    }, text);
    const nav = el("div", { class: "chips", style: "align-items:center" },
      step("\u2039 Back", brief.back, "The day before"),
      el("strong", { style: "min-width:190px;text-align:center" }, label),
      step("Forward \u203a", brief.forward, "The day after"),
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(brief.is_today),
        onclick: () => this._briefGo(null),
      }, "Today"),
      el("span", { class: "small" }, windowWords));

    const nowRows = brief.now;
    const open = nowRows.filter((row) => !row.acknowledged).length;
    const nowTable = nowRows.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {},
          brief.is_today ? el("th", { class: "ackcell" }, (() => {
            const head = el("span", {});
            head.append(checkIcon("Acknowledged"));
            return head;
          })()) : null,
          ...["DEVICE", "PROBLEM", "SINCE", "FOR"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...nowRows.map((row) => el("tr", { class: row.acknowledged ? "acked" : "" },
          brief.is_today ? el("td", { class: "ackcell" }, el("label", { class: "ackbox" },
            el("input", {
              type: "checkbox", "aria-label": `Acknowledge ${row.name}`,
              ...(row.acknowledged ? { checked: "" } : {}),
              onchange: (ev) => this._acknowledge(row.uid, ev.target.checked),
            }))) : null,
          el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
          el("td", {}, row.problem),
          el("td", {}, row.since ? moment(row.since) : ""),
          el("td", {}, row.seconds ? span(row.seconds) : ""))))))
      : el("p", { class: "muted", style: "margin:0" }, "Nothing needed attention.");
    const nowLine = nowRows.length
      ? `${open} ${open === 1 ? "device needs" : "devices need"} attention`
        + `${nowRows.length - open ? `, and ${nowRows.length - open} acknowledged` : ""}.`
      : "";

    const repeat = brief.repeat.lines && brief.repeat.lines.length
      ? brief.repeat.lines.map((line) => el("p", { style: "margin:0;line-height:1.5" }, line))
      : [el("p", { class: "muted", style: "margin:0" }, brief.repeat.words)];

    const counts = brief.counts;
    const eventsLine = counts.events
      ? `${counts.events} ${counts.events === 1 ? "event" : "events"}. ${counts.opened} `
        + `${counts.opened === 1 ? "problem" : "problems"} started, ${counts.resolved} ended.`
      : "Nothing happened.";
    const eventsTable = brief.events.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["TIME", "DEVICE", "WHAT HAPPENED"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...brief.events.map((row) => el("tr", {},
          el("td", {}, new Date(row.when).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })),
          el("td", {}, row.device_id ? this._link(row.who, this._devicePath(row.device_id)) : row.who),
          el("td", {}, row.what))))))
      : null;

    this._pane.replaceChildren(nav,
      el("h3", { class: "section" }, "Now"),
      nowLine ? el("p", { style: "margin:0" }, nowLine) : null, nowTable,
      el("h3", { class: "section" }, "Repeat Offenders"), ...repeat,
      el("h3", { class: "section" }, "Last 24 Hours"),
      el("p", { style: "margin:0" }, eventsLine), eventsTable);
  }

  _sorter(state, key, repaint) {
    // One sortable heading: first press sorts, second reverses.
    const direction = state.key === key ? state.dir : null;
    return el("button", {
      class: "sort", type: "button",
      "aria-sort": direction === 1 ? "ascending" : direction === -1 ? "descending" : "none",
      onclick: () => {
        state.key = key;
        state.dir = direction === 1 ? -1 : 1;
        repaint();
      },
    }, "");
  }

  _sortHead(state, label, key, repaint, cls) {
    const button = this._sorter(state, key, repaint);
    button.textContent = label;
    return el("th", cls ? { class: cls } : {}, button);
  }

  _sortRows(rows, state, values) {
    if (!state.key || !values[state.key]) return rows;
    const value = values[state.key];
    return [...rows].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      return (x < y ? -1 : x > y ? 1 : 0) * state.dir;
    });
  }

  _paintBatteryTrends() {
    const page = this._snapshot.battery;
    const rate = (v) => (v === null || v === undefined ? "\u2013" : `${v >= 0 ? "+" : ""}${v.toFixed(3)}/day`);
    const pct = (v) => (v === null || v === undefined ? "" : `${Math.round(v)}%`);
    this._batterySort = this._batterySort || { key: null, dir: 1 };
    this._modelSort = this._modelSort || { key: null, dir: 1 };
    const again = () => this._paintBatteryTrends();
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${page.cells} cells report a level. ${page.falling.length} falling, ${page.steady.length} steady, `
      + `${page.low.length} at or under your threshold of ${page.threshold}%. ${page.no_battery} watched `
      + `devices report no battery at all, and ${page.unreadable.length} ${page.unreadable.length === 1 ? "reports" : "report"} a reading that is not a percentage.`);
    // The bank.
    const top = Math.max(...page.bank, 1);
    const bank = el("div", {},
      el("div", { class: "bank", role: "img", "aria-label": "How many cells sit in each ten percent band" },
        ...page.bank.map((count, index) => el("div", {
          class: "band",
          title: `${count} cell${count === 1 ? "" : "s"} between ${index * 10}% and ${index * 10 + 10}%`,
        },
        el("div", { class: "count" }, count ? String(count) : ""),
        // An empty band draws nothing: a sliver reads as one cell.
        el("div", { style: `height:${count ? Math.max(3, (count / top) * 100) : 0}%` })))),
      el("div", { class: "statusline small" }, el("span", {}, "0%"),
        el("span", {}, "cells by charge remaining"), el("span", {}, "100%")));
    // Every model.
    const models = this._sortRows(page.models, this._modelSort, {
      name: (row) => `${row.maker} ${row.model}`.toLowerCase(),
      cells: (row) => row.cells,
      rate: (row) => row.rate,
      typical: (row) => row.typical,
      lowest: (row) => row.lowest,
    });
    const modelTable = el("table", {},
      el("thead", {}, el("tr", {},
        this._sortHead(this._modelSort, "MAKER AND MODEL", "name", again),
        this._sortHead(this._modelSort, "CELLS", "cells", again, "num"),
        this._sortHead(this._modelSort, "TYPICAL RATE", "rate", again, "num"),
        this._sortHead(this._modelSort, "TYPICAL LEVEL", "typical", again, "num"),
        this._sortHead(this._modelSort, "LOWEST CELL", "lowest", again, "num"),
        el("th", {}, "WHICH ONE"))),
      el("tbody", {}, ...models.map((row) => el("tr", {},
        el("td", {}, `${row.maker} ${row.model}`),
        el("td", { class: "num" }, String(row.cells)),
        el("td", { class: "num", style: row.rate <= -0.05 ? "color:var(--error-color, #db4437)" : "" }, rate(row.rate)),
        el("td", { class: "num" }, pct(row.typical)),
        el("td", { class: "num" }, pct(row.lowest)),
        el("td", {}, this._link(row.lowest_name, this._devicePath(row.lowest_id)))))));
    // The report's own groups.
    const blocks = [];
    for (const row of page.falling) {
      for (const [start, stop] of row.blocks || []) {
        const label = `DAY ${start}\u2013${stop}`;
        if (!blocks.includes(label)) blocks.push(label);
      }
    }
    const fallingRows = this._sortRows(page.falling, this._batterySort, {
      name: (row) => row.name.toLowerCase(),
      level: (row) => row.level,
      rate: (row) => (row.windows ? row.windows["30"] : 0),
      reading: (row) => row.reading || "",
    });
    const falling = page.falling.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {},
          this._sortHead(this._batterySort, "DEVICE", "name", again),
          this._sortHead(this._batterySort, "LEVEL", "level", again, "num"),
          ...blocks.map((label) => el("th", { class: "num" }, label)),
          this._sortHead(this._batterySort, "30 DAY", "rate", again, "num"),
          el("th", { class: "num" }, "14 DAY"), el("th", { class: "num" }, "7 DAY"),
          this._sortHead(this._batterySort, "READING", "reading", again),
          el("th", {}, "LEFT"))),
        el("tbody", {}, ...fallingRows.map((row) => {
          const byPeriod = Object.fromEntries((row.blocks || []).map(([start, stop, value]) => [`DAY ${start}\u2013${stop}`, value]));
          return el("tr", {},
            el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
            el("td", { class: "num" }, pct(row.level)),
            ...blocks.map((label) => el("td", { class: "num" }, label in byPeriod ? rate(byPeriod[label]) : "\u2013")),
            el("td", { class: "num" }, rate(row.windows["30"])),
            el("td", { class: "num" }, rate(row.windows["14"])),
            el("td", { class: "num" }, rate(row.windows["7"])),
            el("td", {}, row.reading || "not falling"),
            el("td", row.left_soon ? { style: "color:var(--error-color, #db4437)" } : {}, row.left || ""));
        }))))
      : el("p", { class: "muted", style: "margin:0" }, "No cell is measurably falling.");
    const plain = (rows, columns) => el("div", { class: "scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ...columns.map(([label, cls]) => el("th", cls ? { class: cls } : {}, label)))),
      el("tbody", {}, ...rows)));
    const low = page.low.length
      ? plain(page.low.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", { class: "num" }, pct(row.level)),
        el("td", {}, row.since ? moment(row.since) : ""))), [["DEVICE"], ["LEVEL", "num"], ["SINCE"]])
      : el("p", { class: "muted", style: "margin:0" }, "No cell is at or under your threshold.");
    const steady = plain(page.steady.map((row) => el("tr", {},
      el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
      el("td", { class: "num" }, pct(row.level)),
      el("td", { class: "num" }, rate(row.rate)),
      el("td", { class: "num" }, String(row.days)))),
    [["DEVICE"], ["LEVEL", "num"], ["30 DAY", "num"], ["DAYS RECORDED", "num"]]);
    const unreadable = page.unreadable.length
      ? el("div", {}, plain(page.unreadable.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", { class: "num" }, pct(row.level)))), [["DEVICE"], ["READING", "num"]]),
      el("p", { class: "small", style: "margin:6px 0 0" },
        "These report a raw sensor value rather than a battery level, and are never called low. To take them out of these lists, "
        + "mute them for battery in Configure, Low Battery."))
      : null;
    this._pane.replaceChildren(summary,
      el("h3", { class: "section" }, "The Bank"), bank,
      el("h3", { class: "section" }, "By Model ",
        el("span", { class: "small" }, `${page.models.length} models, ${page.cells} cells, all of them`)),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "Which of your models eat batteries, and which do not. The rate is the middle of that model's cells over the last 30 days. Mains-powered devices are absent: they report no battery."),
      el("div", { class: "scroll" }, modelTable),
      el("h3", { class: "section" }, "At or Under the Threshold"), low,
      el("h3", { class: "section" }, "Falling"), falling,
      el("h3", { class: "section" }, "Steady ", el("span", { class: "small" }, `${page.steady.length} cells`)), steady,
      unreadable ? el("h3", { class: "section" }, "Not a Percentage") : null, unreadable);
  }

  _paintSignalTrends() {
    const page = this._snapshot.signal;
    this._signalSort = this._signalSort || { key: null, dir: 1 };
    this._signalFilter = this._signalFilter || "all";
    const again = () => this._paintSignalTrends();
    const scales = Object.entries(page.scales);
    const named = { lqi: "link quality", rssi: "RSSI" };
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${page.devices.length} devices report a signal`
      + `${scales.length ? `: ${scales.map(([scale, count]) => `${count} as ${named[scale] || scale}`).join(", ")}` : ""}. `
      + `Over the last 14 days, ${page.counts.unsteady} had at least one bad day and ${page.counts.steady} `
      + "stayed within their own normal."
      + (scales.length > 1 ? " The scales are listed apart: a link quality of 180 and an RSSI of -60 cannot share an axis." : ""));
    // Where each link sits against its own normal.
    const filters = [["all", "All"], ...scales.map(([scale]) => [scale, named[scale] || scale])];
    const chips = el("div", { class: "chips" }, ...filters.map(([key, label]) => el("button", {
      class: "chip", type: "button", "aria-pressed": String(key === this._signalFilter),
      onclick: () => {
        this._signalFilter = key;
        again();
      },
    }, `${label} ${key === "all" ? page.devices.length : page.scales[key]}`)));
    const showing = page.devices.filter((row) => this._signalFilter === "all" || row.scale === this._signalFilter);
    // The SCALE column belongs to the house, not to the chip: a filter to
    // one scale keeps it, so the columns stay where the All view put them
    // (0.22.17).
    const mixed = scales.length > 1;
    const cap = 6;
    const chart = svg("svg", { viewBox: "0 0 1100 170", role: "img",
      "aria-label": "Each device's signal against its own normal, in its own spreads" });
    chart.append(svg("line", { x1: 20, y1: 85, x2: 1080, y2: 85, stroke: "var(--divider-color)" }));
    const width = 1060 / Math.max(1, showing.length);
    showing.forEach((row, index) => {
      const z = Math.max(-cap, Math.min(cap, row.spreads || 0));
      const height = Math.abs(z) / cap * 70;
      const words = `${row.name}: ${Math.round(row.now)} against a normal of ${Math.round(row.normal)}, `
        + `${(row.spreads || 0) >= 0 ? "+" : ""}${(row.spreads || 0).toFixed(1)} of its own spreads`;
      const open = () => this._navigate(this._devicePath(row.device_id));
      // A thin bar is a small target, so the whole column is clickable
      // and the drawn bar sits on top of it.
      const column = svg("rect", {
        x: 20 + index * width, y: 15, width: Math.max(1, width), height: 140,
        fill: "transparent", role: "link", tabindex: 0, "aria-label": `${words}. Open its page.`,
        style: "cursor:pointer", onclick: open,
        onkeydown: (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            open();
          }
        },
      }, svg("title", {}, words));
      chart.append(svg("rect", {
        x: 20 + index * width, y: z >= 0 ? 85 - height : 85,
        width: Math.max(1, width - 1), height: Math.max(1, height),
        style: "pointer-events:none",
        fill: (row.spreads || 0) <= -2 ? "var(--error-color, #db4437)"
          : (row.spreads || 0) >= 2 ? "var(--success-color, #43a047)" : "var(--secondary-text-color)",
      }), column);
    });
    const below = showing.filter((row) => (row.spreads || 0) <= -2).length;
    const above = showing.filter((row) => (row.spreads || 0) >= 2).length;
    const middleChange = showing.length
      ? [...showing].map((row) => row.change).sort((a, b) => a - b)[Math.floor(showing.length / 2)]
      : 0;
    const chartNote = el("div", { class: "statusline small" },
      el("span", {}, "weaker than its normal"),
      el("span", {}, `${showing.length} devices. ${below} sit two spreads or more below their normal, ${above} the same above. `
        + `The middle device is ${middleChange >= 0 ? "+" : ""}${Math.round(middleChange)} points.`),
      el("span", {}, "stronger"));
    // The two lists.
    const sign = (v) => (v === null || v === undefined ? "" : `${v > 0 ? "+" : ""}${Math.round(v)}`);
    const spreads = (v) => (v === null || v === undefined ? "" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}`);
    // Link quality runs from 0 up, so a line below zero is off the
    // bottom of the scale: that device cannot have a bad day at its
    // present spread. RSSI is negative by nature and keeps its number.
    const lineWords = (row) => {
      if (row.line === null || row.line === undefined) return "";
      if (row.scale !== "rssi" && row.line < 0) return "below the scale";
      return String(Math.round(row.line));
    };
    const colour = (v) => ((v || 0) <= -2 ? "color:var(--error-color, #db4437)" : (v || 0) >= 2 ? "color:var(--success-color, #43a047)" : "");
    const pick = (wanted) => this._sortRows(
      showing.filter((row) => (wanted === "unsteady" ? row.bad_days : !row.bad_days)),
      this._signalSort,
      {
        name: (row) => row.name.toLowerCase(),
        now: (row) => row.now || 0,
        bad: (row) => row.bad_days,
        change: (row) => row.spreads || 0,
      },
    );
    // Both tables carry BAD DAYS, so their columns line up and they read
    // as one table split in two; in the steady one it reads 0, which is
    // why each device is there (0.22.17, the owner's choice A).
    const table = (rows) => {
      if (!rows.length) return el("p", { class: "muted", style: "margin:0" }, "None.");
      const head = el("tr", {},
        this._sortHead(this._signalSort, "DEVICE", "name", again),
        mixed ? el("th", {}, "SCALE") : null,
        this._sortHead(this._signalSort, "NOW", "now", again, "num"),
        el("th", { class: "num" }, "ITS NORMAL"),
        el("th", { class: "num" }, "BAD-DAY LINE"),
        this._sortHead(this._signalSort, "BAD DAYS", "bad", again, "num"),
        this._sortHead(this._signalSort, "CHANGE", "change", again, "num"),
        el("th", { class: "num" }, "IN ITS OWN SPREADS"),
        el("th", { class: "num" }, "READINGS A DAY"));
      const body = rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        mixed ? el("td", {}, named[row.scale] || row.scale) : null,
        el("td", { class: "num" }, row.now === null ? "" : String(Math.round(row.now))),
        el("td", { class: "num" }, String(Math.round(row.normal))),
        el("td", { class: "num", style: "color:var(--error-color, #db4437)" }, lineWords(row)),
        el("td", { class: "num" }, String(row.bad_days)),
        el("td", { class: "num", style: colour(row.spreads) }, sign(row.change)),
        el("td", { class: "num", style: colour(row.spreads) }, spreads(row.spreads)),
        el("td", { class: "num" }, row.readings_a_day === null ? "" : String(Math.round(row.readings_a_day)))));
      return el("div", { class: "scroll" },
        el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
    };
    const badDays = page.bad_days.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "DAY"), el("th", { class: "num" }, "DEVICES"))),
        el("tbody", {}, ...page.bad_days.map((row) => el("tr", {},
          el("td", {}, moment(`${row.day}T12:00:00`).replace(/,[^,]*$/, "")),
          el("td", { class: "num" }, String(row.devices)))))))
      : el("p", { class: "muted", style: "margin:0" }, "No day had more than one device fall below its line.");
    const unsteady = pick("unsteady");
    const steady = pick("steady");
    this._pane.replaceChildren(summary,
      el("h3", { class: "section" }, "Days Several Devices Had a Bad Day"),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "One device having a bad day is its own business. Several on the same day usually means something happened to the mesh or the house."),
      badDays,
      el("h3", { class: "section" }, "How Each Link Sits Against Its Own Normal"),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "Each device's last seven days against the middle of its whole history, in its own points and in its own spreads, so a steady link and a jumpy one are judged by their own standards. One bar per device, worst on the left."),
      chips, chart, chartNote,
      el("h3", { class: "section" }, "Devices With Unsteady Signals ", el("span", { class: "small" }, `${unsteady.length} shown`)),
      table(unsteady),
      el("h3", { class: "section" }, "Devices With Steady Signals ", el("span", { class: "small" }, `${steady.length} shown`)),
      table(steady));
  }

  _paintDevices() {
    const all = this._snapshot.devices.rows;
    const at = this._snapshot.at.getTime();
    const counts = {
      all: all.length,
      problem: all.filter((row) => row.problem).length,
      muted: all.filter((row) => row.muted).length,
    };
    let rows = all.filter({
      all: () => true,
      problem: (row) => row.problem,
      muted: (row) => row.muted,
    }[this._deviceFilter]);
    const sort = this._deviceSort;
    if (sort) {
      const value = {
        name: (row) => row.name.toLowerCase(),
        integration: (row) => row.integration_name.toLowerCase(),
        last: (row) => (row.last_activity ? new Date(row.last_activity).getTime() : 0),
        rhythm: (row) => row.rhythm || 0,
        window: (row) => row.window || 0,
      }[sort.key];
      rows = [...rows].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0) * sort.dir);
    }
    const header = (label, key, cls) => {
      const direction = sort && sort.key === key ? sort.dir : null;
      return el("th", cls ? { class: cls } : {}, el("button", {
        class: "sort", type: "button",
        "aria-sort": direction === 1 ? "ascending" : direction === -1 ? "descending" : "none",
        onclick: () => {
          this._deviceSort = { key, dir: direction === 1 ? -1 : 1 };
          this._paintDevices();
        },
      }, label));
    };
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${all.length} devices are watched. ${counts.problem} ${counts.problem === 1 ? "has" : "have"} a problem, `
      + `${counts.muted} ${counts.muted === 1 ? "is" : "are"} muted. Each device's window is how long it may stay `
      + "quiet before it is called frozen, learned from its own rhythm.");
    const chips = el("div", { class: "chips" }, ...DEVICE_FILTERS.map(([key, label]) =>
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._deviceFilter),
        onclick: () => {
          this._deviceFilter = key;
          this._paintDevices();
        },
      }, `${label} ${counts[key]}`)));
    const table = el("table", {},
      el("thead", {}, el("tr", {},
        header("DEVICE", "name"), header("INTEGRATION", "integration"), el("th", {}, "STANDING"),
        el("th", {}, "PROBLEM"), header("LAST REPORT", "last"),
        header("RHYTHM", "rhythm", "num"), header("WINDOW", "window", "num"))),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, this._link(row.integration_name, this._integrationPath(row.integration))),
        el("td", {}, row.muted ? `Muted: ${row.muted}` : "Watched"),
        el("td", {}, row.problem ? `${row.problem}${row.acknowledged ? ", acknowledged" : ""}` : ""),
        el("td", {}, ago(row.last_activity, at)),
        el("td", { class: "num" }, row.rhythm ? span(row.rhythm) : ""),
        el("td", { class: "num" }, row.window ? span(row.window) : "")))));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table));
  }

  _paintReadings() {
    const page = this._page;
    if (!this._readingsBox || !page || page.error) return;
    const labels = { battery: "Battery", signal: "Signal", last_seen: "Last seen" };
    const cards = page.readings.map((reading) => {
      const state = this._hass && this._hass.states ? this._hass.states[reading.entity_id] : null;
      // A reading Home Assistant cannot give is not a reading
      // (0.22.24): the second signal entity of a ZHA device often
      // reads unknown, and a tile saying so is noise.
      if (!state || state.state === "unknown" || state.state === "unavailable") return null;
      let value = state.state;
      if (state && state.attributes && state.attributes.unit_of_measurement && !Number.isNaN(Number(value))) {
        value = `${value}${state.attributes.unit_of_measurement === "%" ? "%" : ` ${state.attributes.unit_of_measurement}`}`;
      }
      if (state && reading.kind === "last_seen" && !Number.isNaN(Date.parse(state.state))) {
        value = new Date(state.state).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      }
      // Home Assistant stamps an entity as changed when a retained
      // message is replayed at a restart, so a device silent since
      // yesterday read "changed 11m ago" on every tile (0.22.24).
      // A tile is dated from the device's own last report when that
      // is older than Home Assistant's stamp.
      const stamped = state.last_changed ? new Date(state.last_changed).getTime() : null;
      const heard = page.status && page.status.last_activity
        ? new Date(page.status.last_activity).getTime() : null;
      const changed = stamped === null ? ""
        : heard !== null && heard < stamped - 1000
          ? `last heard ${ago(page.status.last_activity, Date.now())}`
          : `changed ${ago(state.last_changed, Date.now())}`;
      return el("div", { class: "stat reading" },
        el("div", { class: "small" }, labels[reading.kind]),
        el("div", { class: "v" }, value),
        el("div", { class: "small" }, reading.entity_id),
        el("div", { class: "small" }, changed));
    });
    const shown = cards.filter(Boolean);
    this._readingsBox.replaceChildren(...(shown.length ? shown
      : [el("p", { class: "muted", style: "margin:0" }, "This device has no battery, signal or last seen entity.")]));
  }

  _paintDevicePage() {
    const page = this._page;
    const back = el("p", { style: "margin:0" }, this._backLink());
    this._readingsBox = null;
    if (!page) {
      this._pane.replaceChildren(back, el("p", { class: "muted" }, "Loading."));
      return;
    }
    if (page.error) {
      this._pane.replaceChildren(back, el("p", {}, page.error));
      return;
    }
    const who = page.identity;
    const now = Date.now();
    const status = page.status;
    const [word, colour] = STATUS_WORDS[status.category] || [status.category, "var(--disabled-text-color, #888)"];
    const quiet = status.last_activity ? (now - new Date(status.last_activity).getTime()) / 1000 : null;
    const fill = status.window && quiet !== null ? Math.min(1, quiet / status.window) : 0;
    const standing = who.watched ? (who.muted ? `Watched, muted: ${who.muted}` : "Watched") : `Set aside: ${who.set_aside}`;
    const head = el("div", { class: "pagehead" },
      el("div", {},
        el("h2", {}, who.name),
        el("div", { class: "muted" },
          [who.manufacturer, who.model].filter(Boolean).join(" ") || "Device",
          who.integration ? [" on ", this._link(who.integration_name || who.integration, this._integrationPath(who.integration))] : "",
          `. ${standing}.`)),
      el("div", { class: "links" },
        el("span", { class: "small" }, "Live, updates every minute"),
        this._link("Open in Home Assistant", `/config/devices/device/${encodeURIComponent(who.device_id)}`)));
    const statusBox = el("div", { class: "devstatus" },
      el("div", { class: "statusline" },
        el("div", { style: "font-size:18px;font-weight:500;display:flex;align-items:center;gap:8px" },
          el("span", { class: "dot", style: `background:${colour}` }), word),
        el("div", { class: "muted" }, status.window
          ? `Last report ${ago(status.last_activity, now)}. Called frozen after ${span(status.window)} of silence.`
          : `Last report ${ago(status.last_activity, now)}. Still learning its rhythm, so it is not yet judged for freezing.`)),
      status.window ? el("div", { class: "bar", role: "img", "aria-label": `${Math.round(fill * 100)} percent of its window used` },
        el("div", { style: `width:${(fill * 100).toFixed(1)}%;background:${colour}` })) : null,
      status.window ? el("div", { class: "statusline small" },
        el("span", {}, "0"), el("span", {}, `rhythm ${span(status.rhythm)}`), el("span", {}, `window ${span(status.window)}`)) : null);

    this._readingsBox = el("div", { class: "readings" });
    const address = (who.connections || []).map(([kind, value]) => `${value} (${kind})`).join(", ");
    const identity = [
      ["Name", who.name],
      ["Manufacturer", who.manufacturer || "not reported"],
      ["Model", who.model || "not reported"],
      ["Model ID", who.model_id || "not reported"],
      ["Hardware version", who.hw_version || "none reported"],
      ["Battery type", who.battery_type || "coming soon"],
      ["Integration", who.integration_name || who.integration || ""],
      ["Area", who.area || "none assigned"],
      ["Address", address || "none reported"],
      ["Device ID", who.device_id],
      ["First seen", who.first_observed ? moment(who.first_observed) : "unknown"],
      ["Reports counted", who.event_count != null ? Number(who.event_count).toLocaleString() : "0"],
      // What Device Sentinel counts as this device speaking.
      ["Heartbeat", who.clock === "last_seen" ? "its Last Seen entity" : "updates from its entities"],
    ];
    const idTable = el("table", { class: "kv" }, el("tbody", {}, ...identity.map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v)))));
    const gaps = page.rhythm.gaps;
    const top = Math.max(...gaps, status.window || 0, 1);
    const gapBars = el("div", { class: "gaps", role: "img", "aria-label": "Longest gap each day, last 14 days" },
      ...gaps.map((g, i) => el("div", {
        class: page.rhythm.set_aside.includes(i) ? "aside" : "",
        style: `height:${Math.max(2, (g / top) * 100).toFixed(1)}%`,
        title: `${span(g)}${page.rhythm.set_aside.includes(i) ? ", set aside" : ""}`,
      })));
    const rhythmText = status.rhythm
      ? `Its longest usual gap is ${span(status.rhythm)}, and it is called frozen after ${span(status.window)} of silence. `
        + "Each bar is one day's longest gap; the hatched day is set aside as a possible fluke."
      : "Not enough days yet to learn its rhythm.";
    const rhythm = el("div", {}, el("h3", { class: "section" }, "Its rhythm"),
      el("p", { style: "margin:0 0 8px;line-height:1.5" }, rhythmText), gapBars,
      el("div", { class: "statusline small" }, el("span", {}, "14 days ago"), el("span", {}, "yesterday")));

    const silences = page.silences.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["SILENT SINCE", "SILENT FOR", "WINDOW THEN", "ENDED", "LEARNED FROM"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...page.silences.map((row) => el("tr", {},
          el("td", {}, row.since ? moment(row.since) : ""),
          el("td", {}, row.still_silent && row.silence_total
            ? span(row.silence_total)
            : row.silence ? span(row.silence) : ""),
          el("td", {}, row.window ? span(row.window) : ""),
          el("td", {}, `${row.ended || ""}${row.at ? ` at ${new Date(row.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}`),
          // Truncated by an intervention and still waiting on the
          // device's first word since (0.22.24), which the blank cell
          // used to leave unsaid.
          el("td", {}, row.still_silent
            ? `still silent, ${ago(row.at, Date.now())} since the intervention`
            : row.learned || ""))))))
      : el("p", { class: "muted", style: "margin:0" }, "No silence longer than its rhythm in the last 14 days.");

    this._pane.replaceChildren(back, head, statusBox,
      el("h3", { class: "section" }, "Live readings ", el("span", { class: "small" }, "update the moment they change")),
      this._readingsBox,
      el("div", { class: "twocol" }, el("div", {}, el("h3", { class: "section" }, "Identity"), idTable), rhythm),
      el("h3", { class: "section" }, "Silences, last 14 days"), silences,
      this._graphs(page),
      el("p", { class: "muted", style: "margin:0;font-size:13px" },
        "The Battery and Signal tabs open this page for any device, so these two graphs are where a battery or signal question ends."));
    this._paintReadings();
  }

  _graphs(page) {
    const battery = page.battery.daily;
    const p5 = page.signal.p5;
    const p50 = page.signal.p50;
    const rail = page.signal.railed_days;
    const judged = page.signal.judged || [];
    const gaps = page.rhythm.daily || [];
    const wins = page.rhythm.windows || [];
    const outages = page.outages || [];
    const recorded = Math.max(battery.length, p50.length, gaps.length, 1);
    const days = this._range === "all" ? recorded : Math.min(this._range, recorded);
    const end = new Date(`${page.series_end}T12:00:00`);
    const dayOf = (back) => new Date(end.getFullYear(), end.getMonth(), end.getDate() - back);
    const fmt = (d) => d.toLocaleDateString([], { month: "short", day: "numeric" });
    const x = (back) => 44 + (days <= 1 ? 0 : ((days - 1 - back) * 1046) / (days - 1));
    const step = days <= 1 ? 1046 : 1046 / (days - 1);
    const at = (arr, back) => {
      const i = arr.length - 1 - back;
      return i >= 0 && i < arr.length ? arr[i] : null;
    };
    // Minutes while a span is short: a camera reporting every four
    // minutes reads "4m", not "0.1h".
    const gapText = (s) => (s == null ? "" : s < 5400 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`);
    const hours = gapText;
    // Ticks: the first reads from the left edge and the last from the
    // right, so neither is cut off.
    const ticks = [[days - 1, dayOf(days - 1), "start"]];
    for (let b = days - 2; b > 0; b -= 1) {
      const d = dayOf(b);
      if (d.getDate() === 1 && b > 3 && b < days - 4) ticks.push([b, d, "middle"]);
    }
    ticks.push([0, end, "end"]);
    // Outages on this device's path, placed at their hour of the day.
    const bands = outages.map((o) => {
      const start = new Date(o.start);
      const noon = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 12, 0);
      const back = Math.round((end - noon) / 86400000);
      if (back < 0 || back >= days) return null;
      const centre = x(back) + ((start.getHours() + start.getMinutes() / 60) / 24 - 0.5) * step;
      return { back, o, x: centre, w: Math.max(3, (o.minutes / 1440) * step) };
    }).filter(Boolean);
    const outagesOn = (back) => bands.filter((b) => b.back === back).map((b) =>
      `${b.o.what} down ${b.o.minutes < 90 ? `${b.o.minutes}m` : span(b.o.minutes * 60)}${b.o.worst != null ? `, ${b.o.worst} of ${b.o.devices} devices went down` : ""}${b.o.maintenance ? " (during maintenance)" : ""}`);

    const buttons = el("div", { class: "chips", role: "group", "aria-label": "Time range for the graphs" },
      el("span", { class: "muted", style: "align-self:center" }, "Show"),
      ...RANGES.map(([key, label]) => {
        const disabled = key !== "all" && key > recorded;
        return el("button", {
          class: "chip", type: "button",
          "aria-pressed": String(key === this._range), "aria-disabled": String(disabled),
          title: disabled ? `Only ${recorded} days recorded so far` : "",
          onclick: () => {
            if (disabled) return;
            this._range = key;
            this._hover = null;
            this._paintDevicePage();
          },
        }, key === "all" ? `All (${recorded} days)` : label);
      }),
      el("span", { class: "small", style: "align-self:center" },
        `${recorded} days recorded; your history setting keeps up to ${page.history_days}.`));
    const readout = el("div", { class: "readout", "aria-live": "polite" }, "Point at a day for its values.");
    const lines = [];
    const setHover = (back) => {
      this._hover = back;
      for (const line of lines) {
        line.setAttribute("x1", x(back));
        line.setAttribute("x2", x(back));
        line.setAttribute("opacity", "0.8");
      }
      const parts = [];
      const bat = at(battery, back);
      parts.push(bat != null ? `battery ${bat}%` : "battery not recorded");
      const med = at(p50, back);
      parts.push(med != null ? `signal median ${Math.round(med)}, low ${Math.round(at(p5, back))}` : "signal not recorded");
      const day = at(judged, back);
      if (day && day.bad) parts.push("a bad day");
      if ((at(rail, back) || 0) > 0) parts.push("railed readings");
      const gap = at(gaps, back);
      if (gap != null) parts.push(`longest gap ${hours(gap)}${at(wins, back) ? `, window ${hours(at(wins, back))}` : ""}`);
      readout.textContent = `${fmt(dayOf(back))}: ${parts.concat(outagesOn(back)).join("; ")}`;
    };
    const frame = (low, high, labels, label) => {
      const y = (v) => 190 - ((v - low) / (high - low)) * 170;
      const g = svg("svg", { viewBox: "0 0 1100 220", role: "img", "aria-label": label });
      for (const b of bands) {
        g.append(svg("rect", { x: b.x, y: 20, width: b.w, height: 170,
          fill: "var(--info-color, #4f7cac)", "fill-opacity": b.o.maintenance ? 0.2 : 0.45 }));
      }
      for (const [v, text] of labels) {
        g.append(svg("line", { x1: 44, y1: y(v), x2: 1090, y2: y(v), stroke: "var(--divider-color)" }),
          svg("text", { x: 38, y: y(v) + 4, class: "axis", "text-anchor": "end" }, text));
      }
      for (const [b, d, anchor] of ticks) {
        g.append(svg("line", { x1: x(b), y1: 20, x2: x(b), y2: 190, stroke: "var(--divider-color)", "stroke-opacity": 0.5 }),
          svg("text", { x: x(b), y: 210, class: "axis", "text-anchor": anchor }, fmt(d)));
      }
      return { g, y };
    };
    const pts = (arr, y) => arr
      .map((v, i) => ({ v, back: arr.length - 1 - i }))
      .filter((p) => p.back < days && p.v !== null && p.v !== undefined)
      .map((p) => `${x(p.back).toFixed(1)},${y(p.v).toFixed(1)}`);
    const addHover = (g) => {
      const line = svg("line", { x1: 44, y1: 16, x2: 44, y2: 194, stroke: "var(--primary-text-color)", opacity: 0 });
      lines.push(line);
      g.append(line);
      for (let b = days - 1; b >= 0; b -= 1) {
        g.append(svg("rect", { x: x(b) - step / 2, y: 16, width: step, height: 178, fill: "transparent",
          onmouseenter: () => setHover(b), onclick: () => setHover(b) }));
      }
    };
    const key = (colour, text, dashed, dot) => el("span", {},
      dot ? el("span", { class: "swatch", style: `width:10px;height:10px;border-radius:5px;background:${colour}` })
        : el("span", { class: "swatch", style: `border-top:2px ${dashed ? "dashed" : "solid"} ${colour}` }), text);
    const card = (title, note, ...body) => el("div", { class: "chart" },
      el("div", { class: "statusline" }, el("strong", {}, title), el("span", { class: "small" }, note)), ...body);

    // ---------------------------------------------------------------- battery
    const b = page.battery;
    let batteryCard;
    if (!battery.length) {
      batteryCard = el("p", { class: "muted", style: "margin:0" }, "No battery history for this device.");
    } else {
      const percent = b.readable !== false;
      const unit = percent ? "%" : "";
      const shown = battery.filter((v, i) => battery.length - 1 - i < days && v != null);
      const lowB = Math.max(0, Math.floor(Math.min(...shown)) - 1);
      const highB = percent ? Math.min(100, Math.ceil(Math.max(...shown)) + 1)
        : Math.ceil(Math.max(...shown)) + 1;
      // The threshold is drawn once the battery comes within ten points of it.
      // Your threshold is a percentage, so it means nothing against a
      // reading that is not one (0.22.24): LUX Outdoors reports 186.
      const showThreshold = percent && lowB <= b.threshold + 10;
      const lowAxis = showThreshold ? Math.max(0, Math.min(lowB, Math.floor(b.threshold) - 1)) : lowB;
      const mid = Math.round((lowAxis + highB) / 2);
      const bat = frame(lowAxis, highB, [[highB, `${highB}${unit}`], [mid, `${mid}${unit}`], [lowAxis, `${lowAxis}${unit}`]],
        `Battery level for ${days} days, between ${lowAxis} and ${highB}${percent ? " percent" : ""}`);
      if (showThreshold) {
        bat.g.append(svg("line", { x1: 44, y1: bat.y(b.threshold), x2: 1090, y2: bat.y(b.threshold),
          stroke: "var(--error-color, #db4437)", "stroke-dasharray": "4 4" }),
        svg("text", { x: 1086, y: bat.y(b.threshold) - 5, class: "axis", "text-anchor": "end", fill: "var(--error-color, #db4437)" },
          `your threshold, ${b.threshold}%`));
      }
      bat.g.append(svg("polyline", { points: pts(battery, bat.y).join(" "), fill: "none", stroke: "var(--primary-color)", "stroke-width": 2.2 }));
      // The report's trend lines, ending at the latest reading.
      const trendSet = this._range === 30 ? [[30, "#8E7CC3"], [14, "#E8A33D"], [7, "#D03B3B"]]
        : this._range === 14 ? [[14, "#E8A33D"], [7, "#D03B3B"]] : [];
      const last = battery[battery.length - 1];
      const legend = [el("span", {}, "Daily level (solid).")];
      for (const [window, colour] of trendSet) {
        const slope = b.windows ? b.windows[String(window)] : null;
        if (slope == null || last == null || window > days) continue;
        bat.g.append(svg("line", { x1: x(window - 1), y1: bat.y(last - slope * (window - 1)), x2: x(0), y2: bat.y(last),
          stroke: colour, "stroke-width": 2, "stroke-dasharray": "6 4" }));
        legend.push(key(colour, `${window}-day rate, ${slope >= 0 ? "+" : ""}${slope.toFixed(3)}/day`, true));
      }
      if (!showThreshold && percent) legend.push(el("span", {}, `Your threshold, ${b.threshold}%, is far below this range, so it is not drawn.`));
      // A reading that is not a percentage is a raw sensor value, and
      // your threshold has nothing to say about it (0.22.24).
      if (!percent) legend.push(el("span", {}, "This is a raw reading rather than a percentage, so it is not judged against your threshold."));
      addHover(bat.g);
      const rate = (v) => (v == null ? "\u2013" : `${v >= 0 ? "+" : ""}${v.toFixed(3)}/day`);
      let figures = null;
      if (b.windows) {
        const blocks = (b.blocks || []).slice().sort((p, q) => q[0] - p[0]);
        const head = ["LEVEL", ...blocks.map(([start, stop]) => `DAY ${start}\u2013${stop}`), "30 DAY", "14 DAY", "7 DAY", "READING", "LEFT"];
        const cells = [`${Math.round(b.now)}${unit}`, ...blocks.map((block) => rate(block[2])),
          rate(b.windows["30"]), rate(b.windows["14"]), rate(b.windows["7"]),
          b.reading || "not falling", b.left || "\u2013"];
        figures = el("div", { class: "scroll" }, el("table", { class: "figures" },
          el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))),
          el("tbody", {}, el("tr", {}, ...cells.map((c, i) => el("td",
            i === cells.length - 1 && b.left_soon ? { style: "color:var(--error-color, #db4437)" } : {}, c))))));
      }
      const meaning = b.reading && b.reading_meaning
        ? el("p", { class: "small", style: "margin:0;line-height:1.5" },
          `${b.reading[0].toUpperCase()}${b.reading.slice(1)}: ${b.reading_meaning}`)
        : el("p", { class: "small", style: "margin:0;line-height:1.5" },
          "Not falling: no window of this cell is dropping faster than the rounding of its own readings, so no time left is offered.");
      batteryCard = card("Battery", b.now != null ? `${b.now}${unit} now` : "", figures, meaning, bat.g, el("div", { class: "legend" }, ...legend));
    }

    // ----------------------------------------------------------------- signal
    let signalCard;
    if (!p50.length) {
      signalCard = el("p", { class: "muted", style: "margin:0" }, "No signal history for this device.");
    } else {
      const values = [];
      p5.forEach((v, i) => { if (p5.length - 1 - i < days) values.push(v, p50[i]); });
      const clean = values.filter((v) => v != null);
      let lowS = Math.min(...clean);
      let highS = Math.max(...clean);
      const pad = Math.max(4, (highS - lowS) * 0.15);
      lowS = Math.floor(lowS - pad);
      highS = Math.ceil(highS + pad);
      const midS = Math.round((lowS + highS) / 2);
      const sig = frame(lowS, highS, [[highS, String(highS)], [midS, String(midS)], [lowS, String(lowS)]],
        `Daily ${page.signal.scale || "signal"} for ${days} days: median, low end, its normal and its bad-day line`);
      const med = pts(p50, sig.y);
      const low = pts(p5, sig.y);
      sig.g.append(svg("polygon", { points: med.concat(low.slice().reverse()).join(" "), fill: "var(--primary-color)", "fill-opacity": 0.16 }),
        svg("polyline", { points: med.join(" "), fill: "none", stroke: "var(--primary-color)", "stroke-width": 2.2 }),
        svg("polyline", { points: low.join(" "), fill: "none", stroke: "var(--primary-color)", "stroke-width": 1.2, "stroke-dasharray": "3 3" }));
      const normal = judged.map((j) => (j ? j.normal : null));
      sig.g.append(svg("polyline", { points: pts(normal, sig.y).join(" "), fill: "none", stroke: "var(--secondary-text-color)", "stroke-width": 1.4 }));
      // The bad-day line only where it falls inside the chart.
      let run = [];
      const flush = () => {
        if (run.length > 1) sig.g.append(svg("polyline", { points: run.join(" "), fill: "none", stroke: "var(--error-color, #db4437)", "stroke-width": 1.4, "stroke-dasharray": "5 4" }));
        run = [];
      };
      judged.forEach((j, i) => {
        const back = judged.length - 1 - i;
        if (j && back < days && j.line >= lowS) run.push(`${x(back).toFixed(1)},${sig.y(j.line).toFixed(1)}`);
        else flush();
      });
      flush();
      const badDays = [];
      judged.forEach((j, i) => {
        const back = judged.length - 1 - i;
        if (j && j.bad && back < days) {
          badDays.push({ back, low: p5[i], line: j.line });
          sig.g.append(svg("circle", { cx: x(back), cy: sig.y(p5[i]), r: 5, fill: "var(--error-color, #db4437)" }));
        }
      });
      rail.forEach((n, i) => {
        const back = rail.length - 1 - i;
        if (n > 0 && back < days) sig.g.append(svg("circle", { cx: x(back), cy: 30, r: 4, fill: "none", stroke: "var(--error-color, #db4437)" }));
      });
      if (p50.length < days) {
        sig.g.append(svg("text", { x: x(p50.length - 1) - 8, y: 105, class: "axis", "text-anchor": "end" }, `recording began ${fmt(dayOf(p50.length - 1))} \u203a`));
      }
      addHover(sig.g);
      const lastJudged = [...judged].reverse().find(Boolean);
      const inRange = p5.map((v, i) => ({ v, back: p5.length - 1 - i })).filter((o) => o.back < days && o.v != null);
      const lowest = inRange.reduce((a, o) => (a === null || o.v < a.v ? o : a), null);
      const figures = el("div", { class: "scroll" }, el("table", { class: "figures" },
        el("thead", {}, el("tr", {}, ...["NOW", "ITS NORMAL", "BAD-DAY LINE", "BAD DAYS", "LOWEST DAY", "READINGS A DAY"].map((h) => el("th", {}, h)))),
        el("tbody", {}, el("tr", {},
          el("td", {}, page.signal.now != null ? String(Math.round(page.signal.now)) : "\u2013"),
          el("td", {}, lastJudged ? String(Math.round(lastJudged.normal)) : "\u2013"),
          el("td", { style: "color:var(--error-color, #db4437)" }, lastJudged ? String(Math.round(lastJudged.line)) : "\u2013"),
          el("td", {}, badDays.length ? `${badDays.length} in this range` : "none in this range"),
          el("td", {}, lowest ? `${Math.round(lowest.v)}, ${fmt(dayOf(lowest.back))}` : "\u2013"),
          el("td", {}, page.signal.readings_a_day != null ? `about ${page.signal.readings_a_day}` : "\u2013")))));
      const words = badDays.length
        ? `Bad days in this range: ${badDays.slice().reverse().map((d) => `${fmt(dayOf(d.back))}, when its low end fell to ${Math.round(d.low)}, below that day's line of ${Math.round(d.line)}`).join("; ")}.`
        : "No bad day in this range: its low end stayed above its bad-day line.";
      signalCard = card("Signal", page.signal.scale === "lqi" ? "link quality" : "signal", figures,
        el("p", { class: "small", style: "margin:0;line-height:1.5" }, words), sig.g,
        el("div", { class: "legend" },
          el("span", {}, "Daily median (solid), low end of each day (dashed)."),
          key("var(--secondary-text-color)", "its normal"), key("var(--error-color, #db4437)", "bad-day line", true),
          key("var(--error-color, #db4437)", "a bad day", false, true)));
    }

    // ----------------------------------------------------------------- rhythm
    let rhythmCard;
    if (!gaps.length) {
      rhythmCard = el("p", { class: "muted", style: "margin:0" }, "No reporting history for this device.");
    } else {
      // The axis fits what can be read, not the device's worst ever
      // day (0.22.25): a vibration sensor that left the house for six
      // weeks had an axis of 1032 hours, against a rhythm of 1.6, and
      // every ordinary day lay flat on the floor. The scale is the
      // larger of the device's window and its largest day the trim
      // did not set aside; a day above it is drawn at the top, marked
      // as being off the scale.
      const inHours = [];
      gaps.forEach((g, i) => { if (gaps.length - 1 - i < days) { inHours.push(g / 3600); if (wins[i]) inHours.push(wins[i] / 3600); } });
      const scale = page.rhythm.scale ? page.rhythm.scale / 3600 : null;
      const top = scale && scale > 0 ? scale : Math.max(...inHours);
      const clipped = Math.max(...inHours) > top;
      const inMinutes = top < 1.5;
      // A little headroom, so the window line is never drawn on the
      // chart's own top edge.
      const highG = inMinutes ? Math.ceil((top * 60 + 5) / 5) * 5 / 60 : Math.ceil(top + 1);
      const mark = (h) => (inMinutes ? `${Math.round(h * 60)}m` : `${Number(h.toFixed(1))}h`);
      const rhy = frame(0, highG, [[highG, mark(highG)], [highG / 2, mark(highG / 2)], [0, inMinutes ? "0m" : "0h"]],
        `Longest gap between reports each day for ${days} days, with its window`);
      const cap = (hours) => (hours == null ? null : Math.min(hours, highG));
      rhy.g.append(svg("polyline", { points: pts(wins.map((w) => (w ? cap(w / 3600) : null)), rhy.y).join(" "), fill: "none",
        stroke: "var(--error-color, #db4437)", "stroke-width": 1.4, "stroke-dasharray": "5 4" }),
      svg("polyline", { points: pts(gaps.map((g) => cap(g / 3600)), rhy.y).join(" "), fill: "none", stroke: "var(--primary-color)", "stroke-width": 1.4 }));
      let over = 0;
      gaps.forEach((g, i) => {
        const back = gaps.length - 1 - i;
        if (back >= days) return;
        const late = wins[i] && g > wins[i];
        if (late) over += 1;
        const beyond = g / 3600 > highG;
        rhy.g.append(svg("circle", { cx: x(back), cy: rhy.y(cap(g / 3600)), r: 3,
          fill: late ? "var(--error-color, #db4437)" : "var(--primary-color)" }));
        // Off the scale: drawn at the top with a caret, and named in
        // the legend, so an absence is visible without flattening the
        // days around it.
        if (beyond) {
          rhy.g.append(svg("text", { x: x(back), y: rhy.y(highG) - 6, class: "axis",
            "text-anchor": "middle", fill: "var(--error-color, #db4437)" }, "\u25B2"));
        }
      });
      addHover(rhy.g);
      rhythmCard = card("Rhythm", `longest gap between reports each day, in ${inMinutes ? "minutes" : "hours"}`,
        el("p", { class: "small", style: "margin:0;line-height:1.5" }, over
          ? `${over} ${over === 1 ? "day" : "days"} in this range had a gap longer than its window.`
          : "No day in this range had a gap longer than its window."),
        rhy.g,
        el("div", { class: "legend" }, el("span", {}, "Longest gap each day (dots)."),
          key("var(--error-color, #db4437)", "its window that day", true),
          key("var(--error-color, #db4437)", "a gap longer than its window", false, true),
          clipped ? el("span", {}, "\u25B2 a day beyond the scale, drawn at the top.") : null));
    }

    // ------------------------------------------------------------------ table
    const tableOpen = Boolean(this._tableOpen);
    const toggle = el("button", { class: "chip", type: "button", "aria-expanded": String(tableOpen), style: "align-self:flex-start",
      onclick: () => {
        this._tableOpen = !tableOpen;
        this._paintDevicePage();
      } }, tableOpen ? "Hide table" : "Show as table");
    let table = null;
    if (tableOpen) {
      const rows = [];
      for (let back = 0; back < days; back += 1) {
        const day = at(judged, back);
        rows.push(el("tr", {},
          el("td", {}, fmt(dayOf(back))),
          el("td", { class: "num" }, at(battery, back) != null ? `${at(battery, back)}%` : ""),
          el("td", { class: "num" }, at(p50, back) != null ? String(Math.round(at(p50, back))) : ""),
          el("td", { class: "num", style: day && day.bad ? "color:var(--error-color, #db4437)" : "" },
            at(p5, back) != null ? String(Math.round(at(p5, back))) : ""),
          el("td", { class: "num" }, hours(at(gaps, back))),
          el("td", { class: "num" }, hours(at(wins, back))),
          el("td", {}, outagesOn(back).join("; "))));
      }
      table = el("div", { class: "scroll" }, el("table", { class: "days" },
        el("thead", {}, el("tr", {}, ...["DATE", "BATTERY", "SIGNAL MEDIAN", "LOW END", "LONGEST GAP", "WINDOW", "OUTAGES"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...rows)));
    }
    if (this._hover !== null && this._hover < days) setHover(this._hover);
    return el("div", { style: "display:flex;flex-direction:column;gap:16px" },
      el("h3", { class: "section" }, "History"), buttons, readout, batteryCard, signalCard, rhythmCard,
      el("div", { class: "legend" },
        el("span", {}, el("span", { class: "swatch", style: "height:12px;background:var(--info-color, #4f7cac);opacity:0.45" }),
          "an outage on this device's path (its bridge, broker or integration), not caused by a restart"),
        el("span", {}, el("span", { class: "swatch", style: "height:12px;background:var(--info-color, #4f7cac);opacity:0.2" }),
          "the same, during maintenance")),
      toggle, table);
  }

  _paintClassification() {
    const data = this._snapshot.classification;
    const counts = {
      all: data.rows.length,
      watched: data.watched,
      muted: data.rows.filter((row) => row.muted).length,
      set_aside: data.set_aside,
    };
    const keep = {
      all: () => true,
      watched: (row) => row.watched,
      muted: (row) => row.muted,
      set_aside: (row) => !row.watched,
    }[this._filter];
    const rows = data.rows.filter(keep);
    // All five reasons, and no count of entities with no device: those
    // are never watched, and "seen only as entities" said they were
    // (0.22.13, from the second fleet's review).
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `Watching ${data.watched} of ${data.rows.length} devices. ${data.set_aside} are set aside: integrations you `
      + "excluded, service devices, disabled devices, duplicate coordinators, and devices with no entities. MUTED "
      + "names every mute on a device and its source.");
    const chips = el("div", { class: "chips" }, ...FILTERS.map(([key, label]) =>
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._filter),
        onclick: () => {
          this._filter = key;
          this._paintClassification();
        },
      }, `${label} ${counts[key]}`)));
    const showCopies = data.rows.some((row) => row.copies > 1);
    const head = ["DEVICE", "INTEGRATION", "WATCHED", "MUTED", "SET ASIDE", ...(showCopies ? ["COPIES"] : [])];
    const table = el("table", {},
      el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, this._link(row.integration, this._integrationPath(row.integration))),
        el("td", {}, row.watched ? "\u2713" : ""),
        el("td", {}, row.muted),
        el("td", {}, row.set_aside),
        showCopies ? el("td", {}, row.copies > 1 ? String(row.copies) : "") : null))));
    // The key to SET ASIDE, the same words as classification.md's.
    const key = el("div", { class: "muted", style: "font-size:13px;line-height:1.5" },
      el("p", { style: "margin:0 0 4px" }, "Set aside, by reason:"),
      ...(data.set_aside_meanings || []).map(([reason, meaning]) =>
        el("p", { style: "margin:0" }, el("strong", {}, reason), `: ${meaning}`)));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table),
      el("p", { class: "muted", style: "margin:0;font-size:13px" }, `${rows.length} shown.`), key);
  }

  async _maintenance() {
    const open = this._snapshot && this._snapshot.status.maintenance.open;
    const message = { type: "device_sentinel/action", action: "maintenance" };
    if (!open) message.minutes = Number(this._minutes.value);
    await this._call(message);
    await this._refresh();
  }

  async _enable(label, action) {
    // Enabling entities changes the person's registry, so it is asked first.
    if (!window.confirm(`${label}: turn on every disabled entity of this kind that Device Sentinel reads?`)) return;
    await this._call({ type: "device_sentinel/action", action });
    await this._refresh();
  }
}

customElements.define("device-sentinel-panel", DeviceSentinelPanel);
