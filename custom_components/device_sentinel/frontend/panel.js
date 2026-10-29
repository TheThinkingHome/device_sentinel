// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: panel.js, Version: 0.27.14 (2026-10-29)
//
// The Device Sentinel dashboard. One plain custom element: no framework,
// no build step. Data comes from the integration's WebSocket commands
// when the page opens and when Refresh is pressed, never on a timer, so
// nothing moves while a person reads. The change marker is the one live
// thing: when it moves past the snapshot on screen, Refresh lights up.
// Colours are Home Assistant's theme variables, so the page follows
// light, dark and custom themes. Every name is set as text, never as
// markup, because names come from a person's own registry.
//
// A tab left open across an update (rule DASH-14). Home Assistant serves this
// file at an address carrying a hash of its contents, so an update gives
// it a new address, and an open tab that reconnects is handed the new
// file while the old one still runs. The element can be registered only
// once in a tab, so the new file registers nothing and tells the running
// page instead; the server sends the hash it serves with every status
// and change marker too. A page that finds it is not the file being
// served says so and offers a reload.

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
// and a bookmark all return to the tab that was on screen. The Daily
// Brief owns the bare address, so opening the dashboard lands on it.
// The tabs Simple leaves off the row (rule DASH-04).
const SIMPLE_HIDDEN_TABS = ["Signal Trends", "Classification"];
const TAB_SLUG = Object.fromEntries(TABS.map((name) => [name, name.toLowerCase().replace(/ /g, "-")]));
const TAB_BY_SLUG = Object.fromEntries(TABS.map((name) => [TAB_SLUG[name], name]));
// A type, an area or a battery nobody has set, the same words on
// every tab, and the Type filters' choice for it (rules DEV-10, DASH-04).
const NOT_SET = "Not Set";
const NOT_KNOWN_TYPE = NOT_SET;
// The device commands that say where they were pressed (rules BRIEF-07,
// DEV-07): "device_page" from the device page, "recommendations" from a
// Recommendations card.
const PAGE_SOURCED = new Set(["device_sentinel/device_turn_on", "device_sentinel/device_power", "device_sentinel/device_type",
  "device_sentinel/device_area", "device_sentinel/device_new_area", "device_sentinel/device_rename"]);
// The hover on a ticked acknowledgment, wherever it sits (rule REC-07).
const ACK_HOVER = "Acknowledged. Press to take it back.";
// Where a "Not Set" was set from, by tab, so the brief says so
// (rule BRIEF-07).
const TAB_SOURCE = { "Battery Trends": "battery_trends", "Devices": "devices_tab", "Classification": "classification",
  "Recommendations": "recommendations", "Problem List": "problem_list" };
// A battery level as reported, the same on every surface: "15.5%",
// "16%", one decimal at most, rounded half up on the number as
// written, as battery_level.py does, so the brief, the device page and
// the phone never disagree (rule NOTE-10).
const levelNumber = (v) => {
  const tenth = Number(`${Math.round(Number(`${Math.abs(v)}e1`))}e-1`) * Math.sign(v);
  return Number.isInteger(tenth) ? String(Math.abs(tenth) === 0 ? 0 : tenth) : tenth.toFixed(1);
};
const levelText = (v) => (typeof v === "number" && Number.isFinite(v) ? `${levelNumber(v)}%` : "");
// A lithium cell's level holds near full until its end (rule BAT-16): said
// whenever the cell is not falling, so a steady reading is not taken
// for a healthy one.
const lithiumWords = (type) => `A lithium cell (${type}) holds its level near full for most of its life and falls quickly at the end, `
  + "so a steady reading says little about how long it has left.";
// The others of its model, as context and never as a time left: the
// slowest and fastest of them, sent only when two or more have a
// weekly fall (rule BAT-16).
const modelPaceRange = (pace) => (pace && typeof pace.pace_low === "number" && typeof pace.pace_high === "number"
  ? (levelNumber(pace.pace_low) === levelNumber(pace.pace_high) ? levelNumber(pace.pace_low)
    : `${levelNumber(pace.pace_low)} to ${levelNumber(pace.pace_high)}`)
  : "");
// "1 point", not "1 points"; a range that rounds to nothing reads
// "almost nothing".
const modelPaceWords = (pace) => {
  const range = modelPaceRange(pace);
  if (!range) return "";
  const high = levelNumber(pace.pace_high);
  if (high === "0") return "Others of this model lose almost nothing a week.";
  const said = levelNumber(pace.pace_low) === "0" && range !== high ? `up to ${high}` : range;
  return `Others of this model lose ${said} ${said === "1" || said === "up to 1" ? "point" : "points"} a week.`;
};
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
// Each mute, the words for it, and the settings section that holds it.
const MUTE_SOURCES = [
  ["everything", "Everything", "Exclusions and Muting"],
  ["freeze", "Freeze", "Freeze and Unavailable Detection"],
  // By label or device, never integration (rule MUTE-06).
  ["unavailable", "Unavailable", "Freeze and Unavailable Detection"],
  ["battery", "Battery", "Low Battery"],
  ["signal", "Signal", "Signal Strength"],
];
const INTEGRATION_FILTERS = [
  ["all", "All"],
  ["recommended", "Recommended"],
  ["trouble", "Trouble"],
  ["excluded", "Excluded"],
  ["muted", "Muted"],
];
// What each standing means, on the words under an integration's name
// when hovered.
const STANDING_MEANING = {
  service: "Its devices report themselves as services, so there is nothing to watch.",
  no_hardware: "An add-on with no hardware of its own. It puts its entities on devices other integrations own, as Battery Notes does, and they never count as the device reporting.",
  helper: "A Home Assistant helper you linked to a device. Its entities never count as the device reporting.",
  notices_only: "Its devices have nothing switched on that can report.",
};
// An integration's trouble, each kind in the Problem List's words, worst first.
const TROUBLE_WORDS = [
  ["flapping", "dropping out"],
  ["unavailable", "unavailable"],
  ["frozen", "frozen"],
  ["unknown", "unknown"],
  ["never_reported", "never reported"],
  ["low_battery", "battery low"],
  ["falling_battery", "battery falling"],
  ["railed_signal", "signal railed"],
];
const DEVICE_FILTERS = [
  ["all", "All"],
  ["problem", "With a problem"],
  ["muted", "Muted"],
];
// The Area filter's choice for a device with no area (rule DASH-12).
const NO_AREA = "\u0000no area";
const RANGES = [["all", "All"], [360, "360 Days"], [180, "180 Days"], [90, "90 Days"], [30, "30 Days"], [14, "14 Days"]];
const STATUS_WORDS = {
  reporting: ["Reporting", "var(--success-color, #43a047)"],
  frozen: ["Frozen", "var(--error-color, #db4437)"],
  unavailable: ["Unavailable", "var(--error-color, #db4437)"],
  // A device that keeps dropping out (rule UNAV-06).
  flapping: ["Flapping", "var(--error-color, #db4437)"],
  unknown: ["Unknown", "var(--warning-color, #ffa600)"],
  never_reported: ["Never reported", "var(--error-color, #db4437)"],
  // Nobody is watching it, so there is no verdict to give (rule WATCH-03).
  set_aside: ["Set aside", "var(--disabled-text-color, #888)"],
};
const LIVE_SECONDS = 60;
const PANEL_ELEMENT = "device-sentinel-panel";
const UPDATED_EVENT = "device-sentinel-updated";
// The hash in the address this copy was loaded from, read from
// where the browser says this code is running. A browser that names no
// such address leaves it to the first reply from the server, which comes
// a moment after the file was served.
const PANEL_FILE = (() => {
  try {
    const found = /\/device_sentinel_panel\/panel\.([0-9a-f]{12})\.js/.exec(String(new Error().stack || ""));
    return found ? found[1] : null;
  } catch (err) {
    return null;
  }
})();
let panelLoadedFrom = PANEL_FILE;
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
  .pane.devpage { font-size: 12px; }
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
  const when = new Date(iso).getTime();
  // A time that cannot be read says so, never "NaN".
  if (!Number.isFinite(when)) return "at an unknown time";
  return `${span((at - when) / 1000)} ago`;
}

const STANDING = {
  watched: "Watched",
  excluded: "Excluded",
  muted: "Muted",
  service: "Service only",
  no_hardware: "No hardware",
  helper: "Helper",
  notices_only: "Nothing switched on to read",
};
// The key under the Integrations table, the same words as
// classification.md's. A test holds the two to one text.
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
// as durations.py (rule GEN-09). A test holds the two to one wording.
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
// capture says which day it shows. The language decides the order, the
// month's name and the 12 or 24 hour clock.
function longMoment(date) {
  const time = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${time}, ${date.toLocaleDateString([], { dateStyle: "long" })}`;
}

// Home Assistant's own cog, mdiCog from Material Design Icons
// (@mdi/js, Apache-2.0), so the gear looks like the one in its
// Settings.
const COG_PATH = "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z";

// Home Assistant's printer, mdiPrinter from the same icon set.
const PRINTER_PATH = "M18,3H6V7H18M19,12A1,1 0 0,1 18,11A1,1 0 0,1 19,10A1,1 0 0,1 20,11A1,1 0 0,1 19,12M16,19H8V14H16M19,8H5A3,3 0 0,0 2,11V17H6V21H18V17H22V11A3,3 0 0,0 19,8Z";

// Where a page was opened from, read out of its address. A
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

// How much room a column needs, by its heading, so the columns never
// move when a filter changes.
// A table's widths depend only on its headings, never on the rows a
// filter or a sort leaves, so its columns stay still, and two tables
// with the same headings line up. Names and free text get more room
// than numbers, and the first column always gets a name's share.
const COLUMN_SHARE = {
  "DEVICE": 3, "MAKER AND MODEL": 3, "WHAT HAPPENED": 3,
  "MUTED": 2.5, "WHICH ONE": 2.5, "WHAT": 2.5,
  "PROBLEM": 2.2, "SET ASIDE": 2.2, "STANDING": 2, "DEVICES THAT WENT DOWN": 2,
  "INTEGRATION": 1.6, "SINCE": 1.4, "TIME": 1.4, "WENT DOWN": 1.4, "GAP STARTED": 1.4,
  // Room for "Door/Window Sensor" and "Judged by its connection" on one
  // line.
  "TYPE": 1.7, "AREA": 1.4, "WINDOW": 1.5, "LAST REPORT": 1.1, "BATTERY": 0.9,
};
// Battery Trends' tables share one scale (their "data-base"), so DEVICE,
// TYPE and LEVEL sit in the same place in each, and a table with fewer
// columns ends short of the edge rather than spreading out (rule DASH-04).
const BATTERY_SHARE = {
  "DEVICE": 3, "MAKER AND MODEL": 3, "TYPE": 1.7, "LEVEL": 0.8, "CELLS": 0.8, "READING": 1,
  "TYPICAL RATE": 1.2, "TYPICAL LEVEL": 0.9, "LOWEST CELL": 0.9, "WHICH ONE": 2.2,
  "SINCE": 1.4, "PACE": 1.2, "LEFT": 1.6, "4 WEEKS": 1, "DAYS RECORDED": 1.35, "STEPS": 1.3,
  "CELL": 1.2, "MODEL, A WEEK": 1.1,
};
const BATTERY_BASE = 13.4;
// The Devices tab's own widths: ten columns in Advanced, each word whole
// (rule DASH-04).
const DEVICES_SHARE = {
  "DEVICE": 2.6, "TYPE": 2.4, "AREA": 1.6, "INTEGRATION": 1.6, "STANDING": 1.6, "PROBLEM": 1.6,
  "BATTERY": 1.15, "LAST REPORT": 1.15, "RHYTHM": 1.1, "WINDOW": 1.5,
};
// The Devices tab's Excluded list: the last column, which has no
// heading, holds "Cancel the exclusion" or "Open its integration page"
// on one line (rule DASH-12).
const EXCLUDED_SHARE = { "DEVICE": 2.6, "INTEGRATION": 1.6, "AREA": 1.4, "EXCLUDED": 1.5, "HISTORY": 1.5, "": 2.2 };
// The Integrations tab: the five buttons get the room they need, so
// none breaks inside a word (rule DASH-16).
const INTEGRATION_SHARE = { "INTEGRATION": 3, "EXCLUDE AND MUTE": 4.6, "SET ASIDE": 0.9, "OUTAGES, 14 DAYS": 1.1, "TROUBLE": 1.6 };
// The history table's own widths, the ones its printout uses.
const HISTORY_WIDTHS = [8, 8, 11, 9, 11, 9, 44];

function pinTable(table) {
  if (table.classList.contains("pinned")) return;
  const heads = table.tHead && table.tHead.rows[0]
    ? [...table.tHead.rows[0].cells].map((cell) => cell.textContent.trim())
    : null;
  const count = heads ? heads.length : (table.rows[0] ? table.rows[0].cells.length : 0);
  if (!count) return;
  let shares;
  const base = Number(table.dataset.base) || 0;
  const own = table.dataset.shares === "battery" ? BATTERY_SHARE
    : table.dataset.shares === "integrations" ? INTEGRATION_SHARE
      : table.dataset.shares === "devices" ? DEVICES_SHARE
        : table.dataset.shares === "excluded" ? EXCLUDED_SHARE : null;
  if (own && heads) shares = heads.map((head) => own[head] ?? 1);
  else if (table.classList.contains("days") && count === HISTORY_WIDTHS.length) shares = HISTORY_WIDTHS;
  else if (!heads) shares = count === 2 ? [1, 2] : Array(count).fill(1);
  else {
    shares = heads.map((head, index) => {
      const share = COLUMN_SHARE[head] || (head === "" ? 0.5 : 1);
      return index === 0 && head !== "" ? Math.max(share, 2.5) : share;
    });
  }
  const total = shares.reduce((sum, share) => sum + share, 0);
  const scale = Math.max(base, total);
  const group = document.createElement("colgroup");
  for (const share of shares) {
    const col = document.createElement("col");
    col.style.width = `${((share / total) * 100).toFixed(3)}%`;
    group.append(col);
  }
  table.prepend(group);
  table.classList.add("pinned");
  // On a shared scale the table is only as wide as its columns.
  if (base) table.style.width = `${((total / scale) * 100).toFixed(3)}%`;
  // Seventy pixels per share: on a phone the table scrolls sideways in
  // its box rather than crushing its columns.
  if (table.parentElement && table.parentElement.classList.contains("scroll")) {
    table.style.minWidth = `${Math.round(total * (table.dataset.shares === "integrations" ? 125 : 70))}px`;
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

// A day in the browser's own time zone, as a date input reads it: the
// UTC day is tomorrow in an evening west of Greenwich.
function localDay(d) {
  const pad = (v) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

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
  /* The browser draws a dropdown's open list on its own white
     background, so on a dark theme white choices vanish. Each choice
     takes the theme's card and text colours (rule DASH-05). */
  select option, select optgroup { background-color: var(--card-background-color, #ffffff);
    color: var(--primary-text-color, #212121); }
  .pill { min-height: 44px; padding: 0 18px; border-radius: 22px; cursor: pointer;
    background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
  .pill:disabled { opacity: 0.6; cursor: default; }
  .pill.new { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .modes { display: inline-flex; gap: 0; }
  .modes .pill.mode { border-radius: 0; }
  .modes .pill.mode:first-child { border-radius: 22px 0 0 22px; }
  .modes .pill.mode:last-child { border-radius: 0 22px 22px 0; }
  .pill.mode[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .pill.active-recs { background: var(--warning-color, #ffa600); color: #1a1a1a; border-color: var(--warning-color, #ffa600); font-weight: 600; }
  .pill[hidden] { display: none; }
  /* An acknowledged row fades, all but its tick and the word beside it,
     so the tick still reads as something to press (rule REC-07). */
  tr.acked td:not(.ackcell):not(.ackhold) { opacity: 0.75; }
  .rec.acked > :not(:has(.ack)) { opacity: 0.75; }
  .rec.acked .actrow:has(> .ack) > :not(.ack) { opacity: 0.75; }
  label.ack { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; cursor: pointer; }
  .maint { display: flex; align-items: center; border: 1px solid var(--divider-color); border-radius: 22px;
    background: var(--card-background-color); }
  .maint .pill { border: 0; background: transparent; }
  .maint select { min-height: 44px; background: transparent; color: var(--primary-text-color); border: 0;
    border-left: 1px solid var(--divider-color); padding: 0 12px; border-radius: 0 22px 22px 0; }
  .asof { margin-left: auto; font-size: 13px; color: var(--secondary-text-color); }
  /* The release running, at the foot of every view (rule DASH-15). */
  .release { margin: 12px 4px 0; font-size: 13px; color: var(--secondary-text-color); text-align: center; }
  .release a { color: inherit; }
  /* A tab older than the dashboard served (rule DASH-14). */
  .updated { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 12px 14px;
    border: 1px solid var(--warning-color, #ffa600); border-left-width: 6px;
    border-radius: var(--ha-card-border-radius, 12px); background: var(--card-background-color, var(--ha-card-background)); }
  .updated span { flex: 1 1 260px; }
  /* It glows three times when it appears, then holds still, so it
     catches the eye without blinking for as long as it is shown; a
     viewer who asked for less motion sees it still (rule DASH-14). */
  .updated { animation: ds-updated-glow 1.2s ease-in-out 3; }
  @keyframes ds-updated-glow {
    0%, 100% { box-shadow: 0 0 0 0 transparent; }
    50% { box-shadow: 0 0 0 4px var(--warning-color, #ffa600), 0 0 18px 6px var(--warning-color, #ffa600); }
  }
  @media (prefers-reduced-motion: reduce) { .updated { animation: none; } }
  /* The controls above sit in a band of their own, and the tabs read
     as tabs: a tinted strip joined to the content, labels in the main
     text colour, the active one bold with a thicker underline, so the
     tab row never reads as one more row of buttons (rule DASH-02). */
  .head { display: flex; flex-direction: column; gap: 12px; padding: 14px;
    background: var(--secondary-background-color, rgba(127,127,127,0.08)); border: 1px solid var(--divider-color);
    border-radius: var(--ha-card-border-radius, 12px); margin-bottom: 8px; }
  .tabs { display: flex; gap: 2px; padding: 0 8px; border-bottom: 1px solid var(--divider-color); overflow-x: auto;
    background: var(--secondary-background-color, rgba(127,127,127,0.08));
    border-radius: var(--ha-card-border-radius, 12px) var(--ha-card-border-radius, 12px) 0 0; }
  .tab { min-height: 48px; padding: 0 18px; background: transparent; border: 0; border-bottom: 3px solid transparent;
    color: var(--primary-text-color); font-size: 15px; font-weight: 500; cursor: pointer; white-space: nowrap; }
  .tab:hover { background: rgba(127,127,127,0.12); }
  .tab[aria-selected="true"] { color: var(--primary-color); font-weight: 600; border-bottom-color: var(--primary-color);
    background: var(--card-background-color, var(--ha-card-background)); }
  .pane { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }
  .muted { color: var(--secondary-text-color); }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { min-height: 28px; padding: 0 11px; border-radius: 14px; cursor: pointer; background: transparent;
    color: var(--primary-text-color); border: 1px solid var(--divider-color); font-size: 13px; }
  /* The device page's actions (rule DASH-09): small marks beside a value,
     and a line saying why a write was refused or asking first. */
  .edit { width: 28px; height: 28px; border: none; border-radius: 14px; background: transparent;
    color: var(--primary-color); display: inline-flex; align-items: center; justify-content: center;
    cursor: pointer; padding: 0; vertical-align: middle; }
  .actrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .linkbtn { background: none; border: 0; padding: 0; font: inherit; color: var(--primary-color); cursor: pointer; text-decoration: underline; text-align: left; }
  .powericon { display: inline-flex; align-items: center; width: 20px; height: 20px; }
  .actcol { display: flex; flex-direction: column; gap: 6px; padding: 2px 0; }
  .labelchip { display: inline-flex; align-items: center; gap: 4px; padding-left: 10px; border-radius: 13px;
    border: 1px solid var(--divider-color); font-size: 13px; }
  .labelchip .meaning { color: var(--warning-color, #b26a00); }
  /* The label that mutes this device, drawn lit (rule MUTE-09). */
  .labelchip.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .labelchip.on .meaning, .labelchip.on button { color: var(--text-primary-color, #fff); }
  .labelchip button { width: 24px; height: 24px; border: none; background: transparent; padding: 0;
    color: var(--secondary-text-color); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
  .actnote { padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  .actnote.refused { background: rgba(219, 68, 55, 0.12); color: var(--error-color, #db4437); }
  .actnote.ask { background: rgba(255, 152, 0, 0.12); color: var(--warning-color, #b26a00); }
  .actinput { min-height: 30px; padding: 0 8px; border: 1px solid var(--divider-color); border-radius: 6px;
    background: transparent; color: var(--primary-text-color); font: inherit; min-width: 240px; }
  .pick { display: flex; align-items: center; gap: 8px; min-height: 30px; }
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
  /* The device page's groups and rule charts. */
  .gaps > div.grey { background: var(--divider-color); }
  .rulechart { position: relative; height: 110px; }
  .rulechart > .ruleline { position: absolute; left: 0; right: 0; height: 0; border-top: 2px solid #E24B4A; border-radius: 0; flex: none; background: none; }
  .ruleline > span { position: absolute; right: 0; top: -18px; font-size: 11px; color: #E24B4A; }
  .rulebox { margin-bottom: 14px; }
  .ruletitle { font-weight: 500; margin-bottom: 2px; }
  .inuse { font-size: 11px; padding: 1px 8px; margin-left: 8px; border-radius: 10px; background: var(--success-color, #43a047); color: #fff; }
  .kv tr.kvgroup td { padding-top: 14px; font-weight: 500; color: var(--primary-text-color); border-bottom: 1px solid var(--divider-color); }
  .kv tr.kvsub td { background: var(--secondary-background-color, rgba(127,127,127,.06)); }
  .kv tr.kvsub td:first-child { padding-left: 10px; }
  .entitylink { font-family: var(--code-font-family, monospace); font-size: 12px; color: var(--primary-color); text-decoration: none; word-break: break-all; }
  .hbtag { font-size: 11px; padding: 1px 8px; border-radius: 10px; background: var(--secondary-background-color, rgba(127,127,127,.12)); color: var(--secondary-text-color); }
  .readingvalue { font-weight: 500; }
  .prevnext { font-size: 14px; }
  .chart { border: 1px solid var(--divider-color); border-radius: 10px; padding: 14px 16px; display: flex;
    flex-direction: column; gap: 8px; }
  .chart svg { width: 100%; height: auto; }
  .chart .axis { fill: var(--secondary-text-color); font-size: 11px; }
  .chip[aria-disabled="true"] { opacity: 0.4; cursor: default; border-style: dashed; }
  /* A mute that is on (rule MUTE-09): filled, with its check mark, and
     still filled when it is set elsewhere and cannot be pressed here. */
  .chip.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .chip.on[aria-disabled="true"] { opacity: 1; border-style: solid; }
  /* The Integrations tab (rule MUTE-03): an excluded row is greyed,
     its mutes rest, and a recommendation reads under the name. */
  tr.excluded td { background: var(--secondary-background-color, rgba(127,127,127,0.08)); }
  tr.excluded .chip:not(.on) { opacity: 0.4; border-style: dashed; }
  .recommended { color: var(--warning-color, #b26a00); font-size: 13px; margin-top: 2px; line-height: 1.4; }
  td.trouble { color: var(--error-color, #db4437); }
  /* The five buttons stay on one line, each word whole. */
  .intbuttons { flex-wrap: nowrap; gap: 6px; }
  .intbuttons .chip { white-space: nowrap; padding: 0 8px; text-align: center; }
  /* Each button keeps one width, lit or not, so they stand in columns. */
  .intbuttons .chip:nth-child(1) { min-width: 92px; }
  .intbuttons .chip:nth-child(2) { min-width: 134px; }
  .intbuttons .chip:nth-child(3) { min-width: 108px; }
  .intbuttons .chip:nth-child(4) { min-width: 114px; }
  .intbuttons .chip:nth-child(5) { min-width: 108px; }
  .figures th, .figures td { padding: 6px 8px; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--secondary-text-color); align-items: center; }
  .legend .swatch { display: inline-block; width: 18px; vertical-align: middle; margin-right: 6px; }
  .readout { background: var(--secondary-background-color, rgba(127,127,127,0.1)); border-radius: 8px; padding: 10px 12px; min-height: 22px; }
  .small { font-size: 12px; color: var(--secondary-text-color); }
  /* The device page reads at one size (rule DASH-06): its secondary
     text, such as "heard by Device Sentinel 9m ago" and the heartbeat
     line, takes the page's size. Headings, the big figures, buttons,
     chips and the charts' own labels keep theirs.
     The heartbeat line is plain grey text and a sensor's name is in the
     page's own font, since a pill or monospace reads as a different
     size even at the same pixels. Other tabs are unchanged. */
  .pane.devpage { font-size: 14px; }
  .devpage .small, .devpage .legend, .devpage .actnote, .devpage .labelchip,
  .devpage .inuse, .devpage .entitylink, .devpage .hbtag { font-size: inherit; }
  .devpage .entitylink { font-family: inherit; }
  .devpage .hbtag { padding: 0; border-radius: 0; background: none; }
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
    // The dashboard's own Simple or Advanced switch (rule DASH-03): held
    // only while this page is open, and nothing is kept in the browser.
    // Leaving the dashboard, closing the window or reloading returns it
    // to the setting the status reply carries. Held on the dashboard
    // itself, never cleared when Home Assistant takes it out of a tab
    // hidden for five minutes and puts the same one back (rule DASH-03):
    // leaving for another page of Home Assistant builds a new dashboard
    // when it is opened again, which starts from the setting.
    this._modeChoice = null;
    // The Recommendations cards a person has open (rule REC-11): kept
    // while this dashboard is open, in memory only, so an answer or a
    // tick redraws the tab with the same cards open and the page where
    // it was. The address's ?open= opens its card once.
    this._openCards = new Set();
    this._openFromAddress = null;
    this._filter = "all";
    this._problemFilter = "all";
    this._problemSort = null;
    this._integrationFilter = "all";
    this._integrationSort = null;
    this._base = "/device-sentinel";
    this._view = null;
    this._page = null;
    this._deviceFilter = "all";
    this._deviceType = "";
    this._deviceSort = null;
    // The Devices tab's search, area and label (rule DASH-12).
    this._deviceSearch = "";
    // The watched devices, or the devices on the exclusion lists.
    this._deviceView = "watched";
    this._deviceArea = "";
    this._deviceLabel = "";
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
    // Whether this tab runs an older dashboard than the one served.
    this._updated = false;
    this._onUpdated = (event) => {
      // Only the word a copy of this file sends: a detail naming its file,
      // or null where its browser could not say. Anything else is not this file's.
      const detail = event && event.detail;
      if (!detail || typeof detail !== "object" || !("file" in detail)) return;
      const file = detail.file;
      if (file !== null && typeof file !== "string") return;
      // Another copy running at all means Home Assistant loaded a file
      // at a new address; only a copy that names this very file is not.
      if (file && panelLoadedFrom && file === panelLoadedFrom) return;
      this._showUpdated();
    };
  }

  set hass(hass) {
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    // Entity states arrive with every hass update, so the readings on
    // a device page redraw the moment one changes.
    if (this._readingCells && this._view && this._view.kind === "device") this._paintReadings();
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
    // The Send to Battery Notes offer belongs to the save that made it:
    // leaving the tab ends it (rule DEV-09).
    if (changed) this._recReport = null;
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
    window.addEventListener(UPDATED_EVENT, this._onUpdated);
    // Back on the page: the Maintenance Mode countdown runs again.
    if (this._maintButton && this._snapshot) this._paintMaintButton();
    if (this._started && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
    window.removeEventListener(UPDATED_EVENT, this._onUpdated);
    if (this._maintTimer) {
      clearInterval(this._maintTimer);
      this._maintTimer = null;
    }
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
          this._noteServed(event.panel);
          this._latestMarker = event.marker;
          this._paintRefresh();
        },
        { type: "device_sentinel/subscribe_changes" },
      );
    } catch (err) {
      this._unsubscribe = null;
    }
  }

  // The dashboard file the server says it serves (rule DASH-14). The first one
  // heard stands for this copy when the browser could not name it.
  _noteServed(file) {
    if (typeof file !== "string" || !file) return;
    if (panelLoadedFrom === null) {
      panelLoadedFrom = file;
      return;
    }
    if (file !== panelLoadedFrom) this._showUpdated();
  }

  _showUpdated() {
    this._updated = true;
    if (!this._body || this._notice) return;
    this._notice = el("div", { class: "updated", role: "status" },
      el("span", {}, "Device Sentinel was updated. Reload this page to use the new version."),
      el("button", { class: "pill", type: "button", onclick: () => window.location.reload() }, "Reload"));
    this._body.prepend(this._notice);
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

  // How a device never judged for freezing is judged: "Judged by its
  // hub, Garage Smart Bridge", the name a link to
  // the hub's page here, or Home Assistant's when the hub is not
  // watched; or "Judged by its connection". Null for any other device.
  _judgedByWords(judged, stop = "") {
    if (!judged) return null;
    if (judged.how === "hub") {
      const path = judged.hub_page ? this._devicePath(judged.hub_id)
        : `/config/devices/device/${encodeURIComponent(judged.hub_id)}`;
      return el("span", {}, "Judged by its hub, ", this._link(judged.hub_name || "its hub", path), stop);
    }
    return el("span", {}, `Judged by its connection${stop}`);
  }

  _build() {
    const root = this.shadowRoot;
    root.append(el("style", {}, STYLE));
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    // The gear goes to the integration's own page, where Configure is
    // one click away. Home Assistant gives a custom panel no supported
    // way to open the options dialog itself.
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
    // the house. The toolbar is not part of a printout.
    const printer = el("button", {
      class: "print", type: "button", title: "Print this page", "aria-label": "Print this page",
      onclick: () => this._print(),
    }, svg("svg", { width: "24", height: "24", viewBox: "0 0 24 24", "aria-hidden": "true" },
      svg("path", { d: PRINTER_PATH, fill: "currentColor" })));
    root.append(el("div", { class: "toolbar" }, this._menu, "Device Sentinel", printer, gear));

    this._statusRow = el("section", { class: "status", "aria-label": "Status" });
    this._refreshButton = el("button", { class: "pill", type: "button", onclick: () => this._refresh() }, "Refresh");
    this._maintButton = el("button", { class: "pill", type: "button", onclick: () => this._maintenance() }, "Start Maintenance Mode");
    this._minutes = el("select", { "aria-label": "Maintenance length" });
    this._asOf = el("span", { class: "asof" });
    // One highlighted button (rule DASH-02): the recommendations not yet
    // acknowledged, hidden at zero, opening the tab.
    this._activeButton = el("button", { class: "pill active-recs", type: "button", hidden: "",
      onclick: () => this._navigate(this._tabPath("Recommendations")) }, "");
    const actions = el(
      "section",
      { class: "actions", "aria-label": "Actions" },
      this._refreshButton,
      el("div", { class: "maint" }, this._maintButton, this._minutes),
      this._activeButton,
      this._modeSwitch = el("div", { class: "modes", role: "group", "aria-label": "Dashboard" }),
      this._asOf,
    );

    this._tabRow = el("div", { class: "tabs", role: "tablist", "aria-label": "Reports" });
    this._pane = el("div", { class: "pane", role: "tabpanel" });
    // A part left out (null) is dropped rather than drawn as the word
    // "null", on every tab and page the pane shows.
    const draw = this._pane.replaceChildren.bind(this._pane);
    this._pane.replaceChildren = (...parts) => draw(...parts.filter((part) => part !== null && part !== undefined && part !== false));
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
    // The release running, linked to its notes (rule DASH-15), so a
    // person sees which one this is without opening Settings or HACS.
    this._release = el("p", { class: "release" });
    this._body = el("div", { class: "body" },
      el("div", { class: "head" }, this._statusRow, actions),
      el("div", { class: "card" }, this._tabRow, this._pane),
      this._release);
    root.append(this._body);
    if (this._updated) this._showUpdated();
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
    this._areaChoices = null;
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
      // An open "Change date" is dropped once its device waits on no
      // detection, answered here or anywhere else.
      if (this._batteryDayOpen) {
        const confirm = (recommendations.devices || []).find((card) => card.kind === "battery_confirm");
        const waiting = new Set(confirm ? confirm.devices.map((row) => row.device_id) : []);
        for (const id of Object.keys(this._batteryDayOpen)) if (!waiting.has(id)) delete this._batteryDayOpen[id];
      }
      this._noteServed(status.panel);
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

  // The button says what pressing it does; open, with the minutes left,
  // counted down each half minute while it is open (rule DASH-02).
  _paintMaintButton() {
    const open = this._maintOpen();
    const maint = open ? this._snapshot.status.maintenance : null;
    const until = open ? new Date(maint.until).getTime() : NaN;
    const left = Number.isFinite(until) ? Math.max(1, Math.ceil((until - Date.now()) / 60000)) : null;
    this._maintButton.textContent = !open ? "Start Maintenance Mode"
      : left === null ? "End Maintenance Mode" : `End Maintenance Mode (${left} min left)`;
    if (open && !this._maintTimer) this._maintTimer = setInterval(() => this._paintMaintButton(), 30000);
    else if (!open && this._maintTimer) {
      clearInterval(this._maintTimer);
      this._maintTimer = null;
      // The window ran out while the page was open: read the house
      // again, so the tile and the length list say so too.
      this._refresh();
    }
  }

  // Open, and not yet past its end: a window that has run out reads as
  // off, so the button never offers to end what has ended.
  _maintOpen() {
    const maint = this._snapshot && this._snapshot.status && this._snapshot.status.maintenance;
    if (!maint || !maint.open) return false;
    const until = new Date(maint.until).getTime();
    return !Number.isFinite(until) || until > Date.now();
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

    this._paintMaintButton();
    this._minutes.disabled = maint.open;
    const chosen = this._minutes.value || String(maint.default_minutes);
    this._minutes.replaceChildren(...[5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60].map((m) =>
      el("option", { value: String(m), ...(String(m) === chosen ? { selected: "" } : {}) }, `${m} min`)));
    this._asOf.textContent = `As of ${longMoment(at)}`;
    this._paintRelease(status.release);
    this._paintModes();
    this._paintActiveRecs();
  }

  // The same words in Simple and Advanced (rule DASH-15). A link only
  // when the server gave one, and only to the release notes page.
  _paintRelease(release) {
    if (!this._release) return;
    const words = release && typeof release.words === "string" ? release.words : "";
    const url = release && typeof release.url === "string"
      && release.url.startsWith("https://github.com/TheThinkingHome/device_sentinel/releases/tag/") ? release.url : null;
    this._release.replaceChildren(...(!words ? [] : url
      ? [el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, words)]
      : [words]));
  }

  // The recommendations this view shows (rule REC-09): Simple shows
  // the cards and lines that stop a missed or false alarm.
  _recsInView() {
    const recs = (this._snapshot && this._snapshot.recommendations) || {};
    const simple = this._isSimple();
    return {
      lines: (recs.lines || []).filter((line) => !simple || line.simple),
      cards: (recs.devices || []).filter((card) => !simple || card.simple),
    };
  }

  // What is not acknowledged in the cards and lines this view shows
  // (rule REC-08).
  _activeRecs() {
    const { lines, cards } = this._recsInView();
    return lines.filter((line) => !line.acknowledged).length
      + cards.reduce((n, card) => n + card.devices.filter((row) => !row.acknowledged).length, 0);
  }

  // Simple or Advanced (rule DASH-03): the switch while it is
  // held, else the setting.
  _mode() {
    if (this._modeChoice) return this._modeChoice;
    const set = this._snapshot && this._snapshot.status && this._snapshot.status.dashboard;
    return set === "simple" ? "simple" : "advanced";
  }

  _isSimple() {
    return this._mode() === "simple";
  }

  _paintModes() {
    if (!this._modeSwitch) return;
    const mode = this._mode();
    this._modeSwitch.replaceChildren(...[["simple", "Simple"], ["advanced", "Advanced"]].map(([key, label]) =>
      el("button", { class: "pill mode", type: "button", "aria-pressed": String(mode === key),
        onclick: () => this._switchMode(key) }, label)));
  }

  // The switch, held while the page is open (rule DASH-03); also what a
  // Simple line that points to Advanced presses.
  _switchMode(key) {
    if (this._mode() === key) return;
    this._modeChoice = key;
    this._devEdit = null;
    this._paintStatus();
    this._paintPane();
  }

  _paintActiveRecs() {
    if (!this._activeButton) return;
    const active = this._snapshot ? this._activeRecs() : 0;
    this._activeButton.hidden = active === 0;
    this._activeButton.textContent = `Active Recommendations (${active})`;
    this._paintTabs();
  }

  _paintTabs() {
    // Simple hides Signal Trends and Classification (rule DASH-04); either
    // still opens from a link, and its tab shows while it is open.
    const hidden = this._snapshot && this._isSimple() ? SIMPLE_HIDDEN_TABS : [];
    const shown = TABS.filter((name) => !hidden.includes(name) || name === this._tab);
    this._tabRow.replaceChildren(...shown.map((name) =>
      el("button", {
        class: "tab", type: "button", role: "tab", "aria-selected": String(name === this._tab),
        onclick: () => {
          // The address moves, and the route that follows paints the
          // tab, the same way a link or the back button does.
          if (!this._view && name === this._tab) return;
          this._navigate(this._tabPath(name));
        },
      }, name === "Recommendations" && this._snapshot && this._activeRecs()
        ? `Recommendations (${this._activeRecs()})` : name)));
  }

  _paintPane() {
    // The device page reads at one size (rule DASH-06); every other view keeps
    // its own.
    this._pane.classList.toggle("devpage", Boolean(this._view && this._view.kind === "device"));
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
        integration: (row) => (row.integration_name || row.integration).toLowerCase(),
        since: (row) => (row.since ? new Date(row.since).getTime() : 0),
      }[sort.key];
      rows = [...rows].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : 0) * sort.dir);
    }
    // The order a device page's Previous and Next follow.
    this._lists = { ...(this._lists || {}), [TAB_SLUG["Problem List"]]: [...new Set(rows.map((row) => row.device_id))] };
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
        el("td", { class: "ackcell" }, el("label", { class: "ackbox", ...(row.acknowledged ? { title: ACK_HOVER } : {}) },
          el("input", {
            type: "checkbox", "aria-label": `Acknowledge ${row.name}`,
            ...(row.acknowledged ? { checked: "" } : {}),
            onchange: (ev) => this._acknowledge(row.uid, ev.target.checked),
          }))),
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, row.integration
          ? this._link(row.integration_name || row.integration, this._integrationPath(row.integration))
          : ""),
        // The mute that matches each problem, beside it (rule MUTE-09).
        el("td", {}, el("div", { class: "actrow" }, el("span", {}, row.power ? `${row.problem}, ${row.power}` : row.problem),
          ...(row.mutes || []).map((kind) => el("button", { class: "chip", type: "button",
            onclick: () => this._muteFromList(row.device_id, kind) }, `Mute ${kind}`)))),
        // A device that never reported has no moment it stopped: the
        // time is when it was discovered, and it says so, as the Daily
        // Brief does (rule LIST-10).
        el("td", {}, row.since ? `${row.never_reported ? "discovered " : ""}${moment(row.since)}` : ""),
        el("td", {}, row.since ? span((at - new Date(row.since).getTime()) / 1000) : "")))));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table),
      el("p", { class: "muted", style: "margin:0;font-size:13px" },
        "Tick a problem to acknowledge it: it stays listed, but nothing reminds you of it again. "
        + "Its recovery is still reported, and the same tick shows on the to-do list."));
  }

  // A mute beside a Problem List item: the item leaves the list
  // silently on the refresh, as a mute always makes it (rule MUTE-07).
  async _muteFromList(device_id, kind) {
    try {
      await this._call({ type: "device_sentinel/device_mute", device_id, kind, on: true, source: "problem_list" });
    } catch (err) {
      // Gone since the snapshot; the refresh below shows the list as it stands.
    }
    await this._refresh();
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
    const { closing } = this._snapshot.recommendations;
    const { lines, cards: devices } = this._recsInView();
    const report = this._recReport ? el("div", { class: "actrow" },
      el("span", { class: "muted" }, `${this._recReport.name} saved. Battery Notes' library does not list this yet.`),
      el("a", { class: "chip", href: this._recReport.url, target: "_blank", rel: "noopener noreferrer",
        style: "display:inline-flex;align-items:center;text-decoration:none",
        onclick: () => { this._recReport = null; } }, "Send to Battery Notes")) : null;
    if (!lines.length && !devices.length) {
      this._pane.replaceChildren(el("p", {}, "Nothing to recommend right now."), ...(report ? [report] : []));
      return;
    }
    const cards = lines.map((line) => {
      const text = line.text;
      const at = text.indexOf(":");
      const title = at > 0 ? text.slice(0, at) : "";
      const rest = (at > 0 ? text.slice(at + 1) : text).trim();
      const body = rest.charAt(0).toUpperCase() + rest.slice(1);
      // An integration recommended for exclusion, one card each (rules
      // MUTE-02, REC-03): its devices, and Exclude beside the tick that
      // keeps it watched.
      if (line.exclude) {
        const devices = line.devices || [];
        return el("article", { class: line.acknowledged ? "rec acked" : "rec" },
          title ? el("h3", {}, title) : null,
          el("p", {}, body),
          devices.length ? el("p", { class: "muted" }, devices.join(", ")) : null,
          el("div", { class: "actrow" },
            el("button", { class: "chip", type: "button", onclick: async (ev) => {
              ev.target.disabled = true;
              try {
                await this._call({ type: "device_sentinel/integration_exclude", domain: line.exclude, on: true, source: "recommendations_tab" });
              } catch (err) {
                ev.target.disabled = false;
                ev.target.after(el("span", { class: "actnote refused" }, err.message || "Home Assistant refused the change."));
                return;
              }
              await this._refresh();
            } }, "Exclude"),
            el("label", { class: "actrow" }, this._ackBox(line.acknowledged, { line: line.key }), "Keep watching it")));
      }
      return el("article", { class: line.acknowledged ? "rec acked" : "rec" },
        title ? el("h3", {}, title) : null,
        el("p", {}, body),
        el("div", { class: "actrow" },
          this._link("Open Device Sentinel settings", SETTINGS_PATH),
          this._ackBox(line.acknowledged, { line: line.key })));
    });
    // Recommendations about single devices, each listing its devices
    // (rule REC-04); a brief's "Open the list" arrives with its card
    // open, and is scrolled to once, not again at each answer (rule REC-11).
    const open = new URLSearchParams(window.location.search).get("open");
    let scrollTo = null;
    if (open && this._openFromAddress !== window.location.href) {
      this._openFromAddress = window.location.href;
      this._openCards.add(open);
      scrollTo = open;
    }
    const deviceCards = devices.map((card) => this._recDeviceCard(card, this._openCards.has(card.kind)));
    // The rows and lines not ticked, as the tab name and the Active
    // Recommendations button count them (rule REC-01).
    const count = this._activeRecs();
    this._keepScroll(() => this._pane.replaceChildren(
      // Every card is a suggestion and none is required (rule REC-01):
      // no card is singled out as more needed than another.
      el("p", { style: "margin:0" }, count
        ? `${count} ${count === 1 ? "recommendation" : "recommendations"} to help Device Sentinel run better. None of them is required.`
        : "Nothing to recommend right now."),
      report, ...cards, ...deviceCards,
      el("p", { class: "muted", style: "margin:0;font-size:13px;line-height:1.5" }, closing)));
    const target = scrollTo ? [...this._pane.querySelectorAll("article.rec")].find((a) => a.dataset.kind === scrollTo) : null;
    // A scroll is a nicety; a browser without one still shows the tab.
    if (target && typeof target.scrollIntoView === "function") target.scrollIntoView({ block: "start" });
  }

  // Redraw without moving the page (rule REC-11): every scrolled
  // element from the pane up through Home Assistant's own, across the
  // shadow roots, is put back where it was.
  _keepScroll(redraw) {
    const kept = [];
    let node = this._pane;
    while (node) {
      if (node.scrollTop) kept.push([node, node.scrollTop]);
      node = node.parentNode || (node.host !== undefined ? node.host : null);
    }
    const page = document.scrollingElement;
    if (page && page.scrollTop && !kept.some(([n]) => n === page)) kept.push([page, page.scrollTop]);
    redraw();
    for (const [n, top] of kept) n.scrollTop = top;
  }

  // The acknowledgment tick (rule REC-07): one device on one card, or
  // one written line, and it can be unticked again.
  _ackBox(on, which) {
    const box = el("input", { type: "checkbox", "aria-label": "Acknowledged", ...(on ? { checked: "" } : {}) });
    box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        await this._call({ type: "device_sentinel/recommendation_ack", on: box.checked, ...which });
        this._snapshot.recommendations = await this._call({ type: "device_sentinel/recommendations" });
      } catch (err) {
        box.checked = !box.checked;
      }
      this._paintActiveRecs();
      if (this._tab === "Recommendations" && !this._view) this._paintRecommendations();
    });
    // Ticked, it says it can be taken back (rule REC-07).
    return el("label", { class: "ack small", ...(on ? { title: ACK_HOVER } : {}) }, box, " Acknowledged");
  }

  _recDeviceCard(card, open) {
    const ids = card.devices.map((row) => row.device_id);
    const unticked = card.devices.filter((row) => !row.acknowledged).length;
    const from = TAB_SLUG.Recommendations;
    const nameLink = (row) => el("a", {
      href: `${this._base}/device/${encodeURIComponent(row.device_id)}?from=${from}`,
      onclick: (ev) => {
        ev.preventDefault();
        // Previous and Next on the device page step through this card.
        this._lists = { ...(this._lists || {}), [from]: ids };
        this._navigate(`${this._base}/device/${encodeURIComponent(row.device_id)}?from=${from}`);
      },
    }, row.name);
    // A save on a card reads everything again, so a new name, area or
    // type shows on the other tabs at once (rule DASH-11).
    const refresh = () => this._refresh();
    const rows = card.devices.map((row) => {
      const note = el("span", { class: "small" }, "");
      const fail = (err) => { note.textContent = (err && err.message) || "That did not save."; };
      let action = null;
      if (card.kind === "power") action = this._recPowerPicker(row.device_id, refresh, fail, row.name);
      if (card.kind === "type") action = this._recTypePicker(row.device_id, refresh, fail);
      // Every card is answered in its own rows, as Power and Type are
      // (rule REC-04): the area, the name, the model's type.
      if (card.kind === "area") action = this._recAreaPicker(row.device_id, refresh, fail);
      if (card.kind === "names") action = this._recRename(row, refresh, fail);
      // A model split between types: which model and what this device
      // is now, then the type for the whole model.
      if (card.kind === "mixed_types") {
        action = el("span", { class: "actcol" }, el("span", { class: "small" }, `${row.model || "Unknown model"}: ${row.type}`),
          this._recTypePicker(row.device_id, refresh, fail));
      }
      // The switched-off cards (rule REC-05): one device, one kind.
      const TURN_ON = {
        last_seen: ["last_seen", "Turn on its Last Seen"],
        // Named for what it reports (rule REC-05).
        battery_off: ["battery", "Turn on its battery percentage sensor"],
        signal_off: ["signal", "Turn on its signal sensor"],
        node_status_off: ["node_status", "Turn on its Z-Wave status"],
        voltage_off: ["voltage", "Turn on its battery voltage sensor"],
      };
      if (card.kind === "battery_confirm") {
        action = this._batteryAnswers(row.device_id, async (error) => {
          if (error) fail({ message: error }); else await refresh();
        }, el("span", { class: "small" }, `detected ${this._dayWords(row.day)}`));
      }
      if (TURN_ON[card.kind]) {
        const [kind, words] = TURN_ON[card.kind];
        action = el("button", { class: "chip", type: "button", onclick: async () => {
          // Where it was pressed, so the log says so (rules BRIEF-07, DEV-07).
          try { await this._call({ type: "device_sentinel/device_turn_on", device_id: row.device_id, kind, source: "recommendations" }); await refresh(); } catch (err) { fail(err); }
        } }, words);
      }
      // A device slow to judge for freeze (rule REC-06): the
      // same mute its device page offers, in the list. The device
      // leaves the card once muted.
      if (card.kind === "slow") {
        action = el("button", { class: "chip", type: "button", onclick: async () => {
          try { await this._call({ type: "device_sentinel/device_mute", device_id: row.device_id, kind: "freeze", on: true, source: "recommendations" }); await refresh(); } catch (err) { fail(err); }
        } }, "Mute freeze");
      }
      return el("tr", row.acknowledged ? { class: "acked" } : {},
        el("td", {}, nameLink(row)),
        // The area, or "Not Set" to set it; on the area card the row's own
        // chooser does that (rule DASH-04).
        el("td", { class: "small" }, card.kind === "area" ? el("span", { class: "muted" }, NOT_SET)
          : this._areaWords(row.area, row.device_id)),
        el("td", {}, el("div", { class: "actrow" }, action, note)),
        // A battery replacement is answered, not ticked (rule REC-07).
        el("td", { class: "ackhold" }, card.kind === "battery_confirm" ? null
          : this._ackBox(row.acknowledged, { kind: card.kind, device_id: row.device_id })));
    });
    return el("article", { class: "rec", "data-kind": card.kind },
      // The rows not yet ticked, as the tab and the button count them
      // (rule REC-08); no number once every row is ticked.
      el("h3", {}, unticked ? `${card.title} (${unticked})` : card.title),
      el("p", {}, card.body),
      this._recDetails(card.kind, open,
        el("summary", {}, `Show the ${card.devices.length} ${card.devices.length === 1 ? "device" : "devices"}`),
        el("div", { class: "scroll" }, el("table", {}, el("tbody", {}, ...rows)))));
  }

  // A card's device list, remembered open or closed as the person
  // leaves it (rule REC-11).
  _recDetails(kind, open, ...children) {
    const details = el("details", open ? { open: "" } : {}, ...children);
    details.addEventListener("toggle", () => {
      if (details.open) this._openCards.add(kind);
      else this._openCards.delete(kind);
    });
    return details;
  }

  // The Power choices in a list row, as the device page's pencil
  // offers them; Save sets the whole model, as there.
  _recPowerPicker(deviceId, refresh, fail, deviceName = "", source = "recommendations") {
    const power = this._snapshot.recommendations.power || {};
    const [qmin, qmax] = power.quantity || [1, 8];
    const wired = power.wired || [];
    const select = el("select", { class: "actinput", "aria-label": "What powers this device" },
      el("option", { value: "" }, "Choose…"), ...(power.choices || []).map((c) => el("option", { value: c }, c)));
    const quantity = el("select", { class: "actinput", "aria-label": "How many" },
      ...Array.from({ length: qmax - qmin + 1 }, (_, i) => qmin + i).map((n) => el("option", { value: String(n) }, `× ${n}`)));
    const other = el("input", { class: "actinput", type: "text", maxlength: "40", placeholder: "Battery or power source",
      "aria-label": "Battery or power source" });
    const repaint = () => {
      quantity.style.display = select.value && !wired.includes(select.value) ? "" : "none";
      other.style.display = select.value === power.other ? "" : "none";
    };
    select.addEventListener("change", repaint);
    repaint();
    const save = el("button", { class: "chip", type: "button", onclick: async () => {
      if (!select.value) return;
      // Where it was set, so the log says so (rules BRIEF-07, DEV-07).
      const message = { type: "device_sentinel/device_power", device_id: deviceId, choice: select.value, source };
      if (!wired.includes(select.value)) message.quantity = Number(quantity.value);
      if (select.value === power.other) message.other = other.value;
      try {
        const reply = await this._call(message);
        // The device leaves the card once saved, so Send to Battery
        // Notes is offered above the cards (rule DEV-09).
        if (source === "recommendations") {
          this._recReport = reply && reply.report_url
            ? { device_id: deviceId, name: deviceName, url: reply.report_url } : null;
        }
        await refresh();
      } catch (err) { fail(err); }
    } }, "Save");
    return el("span", { class: "actrow" }, select, quantity, other, save);
  }


  // The Type choices in a list row, as the device page's
  // pencil offers them; Save sets the whole model, as there.
  _recTypePicker(deviceId, refresh, fail, source = "recommendations") {
    const kinds = this._snapshot.recommendations.types || { choices: [], other: "Other" };
    const select = el("select", { class: "actinput", "aria-label": "What this device is" },
      el("option", { value: "" }, "Choose…"), ...kinds.choices.map((c) => el("option", { value: c }, c)));
    const other = el("input", { class: "actinput", type: "text", maxlength: "40", placeholder: "What it is",
      "aria-label": "Your own words for what this device is" });
    const save = el("button", { class: "chip", type: "button", disabled: "", onclick: async () => {
      if (!select.value) return;
      // Where it was set, so the log says so (rules BRIEF-07, DEV-07).
      const message = { type: "device_sentinel/device_type", device_id: deviceId, choice: select.value, source };
      if (select.value === kinds.other) message.other = other.value;
      try { await this._call(message); await refresh(); } catch (err) { fail(err); }
    } }, "Save");
    const repaint = () => {
      other.style.display = select.value === kinds.other ? "" : "none";
      save.disabled = !select.value;
    };
    select.addEventListener("change", repaint);
    repaint();
    return el("span", { class: "actrow" }, select, other, save);
  }

  // The area chooser in a No Area Assigned row (rule REC-04): the
  // same areas the device page offers; Save moves this one device, in
  // Home Assistant.
  _recAreaPicker(deviceId, refresh, fail) {
    const holder = el("span", { class: "actrow" }, el("span", { class: "muted small" }, "Loading the areas."));
    this._areaPicker(deviceId, refresh, fail, "recommendations").then((picker) => holder.replaceChildren(picker));
    return holder;
  }

  // A new name in a Devices Sharing A Name row (rule REC-04), held for a
  // yes when another device shows it, as on the device page (rule
  // DASH-10). The device leaves the card once no other device shares
  // its name.
  _recRename(row, refresh, fail) {
    const input = el("input", { class: "actinput", type: "text", "aria-label": `A new name for ${row.name}`, value: row.name || "" });
    const ask = el("span", { class: "actrow" });
    const send = async (confirm) => {
      ask.replaceChildren();
      try {
        await this._call({ type: "device_sentinel/device_rename", device_id: row.device_id, name: input.value,
          confirm, source: "recommendations" });
        await refresh();
      } catch (err) {
        if (err && err.code === "name_in_use") {
          ask.replaceChildren(el("span", { class: "small" }, err.message),
            el("button", { class: "chip", type: "button", onclick: () => send(true) }, "Save anyway"));
        } else fail(err);
      }
    };
    const save = el("button", { class: "chip", type: "button", onclick: () => send(false) }, "Save");
    input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") send(false); });
    return el("span", { class: "actcol" }, el("span", { class: "actrow" }, input, save), ask);
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
    const simple = this._isSimple();
    const owns = (row) => Boolean(row.devices);
    const muted = (row) => Boolean(row.mutes && Object.values(row.mutes).some(Boolean));
    const hasTrouble = (row) => Boolean(row.down_since || Object.keys(row.trouble || {}).length);
    // Recommended, with trouble, excluded and muted, each its own chip
    // (rule DASH-16).
    const filters = {
      all: () => true,
      recommended: (row) => Boolean(row.recommended),
      trouble: (row) => !row.excluded && hasTrouble(row),
      excluded: (row) => Boolean(row.excluded),
      muted: (row) => !row.excluded && muted(row),
    };
    const counts = Object.fromEntries(INTEGRATION_FILTERS.map(([key]) => [key, all.filter(filters[key]).length]));
    if (!filters[this._integrationFilter]) this._integrationFilter = "all";
    let rows = all.filter(filters[this._integrationFilter]);
    const sort = this._integrationSort;
    if (sort) {
      rows = [...rows].sort((a, b) => (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1) * sort.dir);
    }
    const direction = sort ? sort.dir : 1;
    const header = el("button", {
      class: "sort", type: "button",
      "aria-sort": !sort ? "none" : direction === 1 ? "ascending" : "descending",
      onclick: () => {
        this._integrationSort = { key: "name", dir: sort && direction === 1 ? -1 : 1 };
        this._paintIntegrations();
      },
    }, "INTEGRATION");
    const devices = all.filter((row) => !row.excluded).reduce((n, row) => n + (row.watched || 0), 0);
    const open = all.filter((row) => row.recommended).length;
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${all.length} ${all.length === 1 ? "integration" : "integrations"}, ${devices} ${devices === 1 ? "device" : "devices"} watched.`
      + (open ? ` ${open} ${open === 1 ? "is" : "are"} recommended for exclusion.` : ""));
    const how = el("p", { class: "muted", style: "margin:0;font-size:13px;line-height:1.5" },
      "Each button works on all the integration's devices at once, and pressing it again undoes it. ",
      el("strong", {}, "Exclude"), " stops the watching; what its devices recorded is deleted at midnight, "
      + "so pressing it again before then loses nothing. ",
      el("strong", {}, "Mute"), " keeps the watching and stops the reports. A single device is muted or "
      + "excluded on its own page.");
    const chips = el("div", { class: "chips" }, ...INTEGRATION_FILTERS.filter(([key]) =>
      key === "all" || counts[key] || this._integrationFilter === key).map(([key, label]) =>
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._integrationFilter),
        onclick: () => {
          this._integrationFilter = key;
          this._paintIntegrations();
        },
      }, `${label} ${counts[key]}`)));
    const table = el("table", { "data-shares": "integrations" },
      el("thead", {}, el("tr", {},
        el("th", {}, header), el("th", {}, "EXCLUDE AND MUTE"),
        // Advanced adds the counts nothing else on the tab shows (rule DASH-16).
        simple ? null : el("th", { class: "num" }, "SET ASIDE"),
        simple ? null : el("th", { class: "num" }, "OUTAGES, 14 DAYS"),
        el("th", {}, "TROUBLE"))),
      el("tbody", {}, ...rows.map((row) => el("tr", { class: row.excluded ? "excluded" : "" },
        el("td", {},
          this._link(row.name, this._integrationPath(row.domain)),
          owns(row) ? ` (${row.devices}) ` : " ",
          el("span", { class: "small" }, row.domain),
          // An integration with no hardware, or one with nothing to
          // watch, says so under its name.
          !owns(row) || !["watched", "excluded", "muted"].includes(row.standing)
            ? el("div", { class: "small", title: STANDING_MEANING[row.standing] || "" }, this._standingText(row)
              + ((row.standing === "no_hardware" || row.standing === "helper") && row.adds_to
                ? `, on ${row.adds_to} ${row.adds_to === 1 ? "device" : "devices"}` : ""))
            : null,
          // What Device Sentinel recommends, under the name (rule MUTE-02).
          row.recommended
            ? el("div", { class: "recommended" }, "Recommended: ", el("strong", {}, "Exclude"), `, ${row.recommended}`)
            : null),
        el("td", {}, owns(row) ? this._integrationButtons(row) : null),
        simple ? null : el("td", { class: "num" }, row.set_aside ? String(row.set_aside) : ""),
        simple ? null : el("td", { class: "num" }, row.outages ? String(row.outages) : ""),
        el("td", { class: "trouble" }, row.excluded ? "" : this._troubleText(row))))));
    const note = this._integrationNote && this._integrationNote.domain === "*"
      ? el("p", { class: "actnote refused" }, this._integrationNote.text) : null;
    this._pane.replaceChildren(...[summary, how, chips, note, el("div", { class: "scroll" }, table)].filter((part) => part));
  }

  // An integration's five buttons: one press each, no confirm, and a
  // second press undoes it (rules MUTE-03, MUTE-09). Mute everything
  // lights the three single mutes and holds them; an excluded
  // integration's mutes rest. Unavailable is never muted by
  // integration (rule MUTE-06).
  _integrationButtons(row) {
    const act = async (message) => {
      this._integrationNote = null;
      try {
        await this._call(message);
      } catch (err) {
        this._integrationNote = { domain: "*", text: `${row.name}: ${err.message || "Home Assistant refused the change."}` };
      }
      await this._refresh();
    };
    const mutes = row.mutes || {};
    const exclude = el("button", {
      class: row.excluded ? "chip on" : "chip", type: "button", "aria-pressed": String(Boolean(row.excluded)),
      title: row.excluded ? "History deleted at midnight. Press again before then to keep it." : "",
      onclick: () => act({ type: "device_sentinel/integration_exclude", domain: row.domain, on: !row.excluded, source: "integrations_tab" }),
    }, row.excluded ? "✓ Excluded" : "Exclude");
    const mute = (kind, words) => {
      const covered = kind !== "everything" && mutes.everything;
      const lit = Boolean(mutes[kind] || covered);
      const resting = Boolean(row.excluded) || covered;
      return el("button", {
        class: lit ? "chip on" : "chip", type: "button", "aria-pressed": String(lit),
        ...(resting ? { "aria-disabled": "true" } : {}),
        onclick: () => {
          if (resting) return;
          act({ type: "device_sentinel/integration_mute", domain: row.domain, kind, on: !mutes[kind] });
        },
      }, lit ? `✓ ${words}` : words);
    };
    return el("div", { class: "actrow intbuttons" }, exclude,
      mute("everything", "Mute everything"), mute("freeze", "Mute freeze"),
      mute("battery", "Mute battery"), mute("signal", "Mute signal"));
  }

  // What is wrong now on an integration's devices, worst first, and
  // whether it is down (rule DASH-16).
  _troubleText(row) {
    const parts = [];
    if (row.down_since) parts.push(`Down since ${moment(row.down_since)}`);
    for (const [kind, words] of TROUBLE_WORDS) {
      const n = (row.trouble || {})[kind];
      if (n) parts.push(`${n} ${words}`);
    }
    return parts.join(", ");
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
  // each entity opening Home Assistant's window.
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
    // Counted as the Integrations tab counts it: muted from
    // everything, not a battery or signal mute alone.
    const muted = page.devices.filter((d) => (d.muted_global === undefined ? d.muted : d.muted_global)).length;
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
    // Exclude the integration, or take it back, here as well as in
    // Settings, in Simple and Advanced alike (rule MUTE-03).
    const exclusion = el("div", { class: "actrow" },
      el("button", { class: "chip", type: "button",
        onclick: async () => {
          this._integrationNote = null;
          try {
            await this._call({ type: "device_sentinel/integration_exclude", domain: page.domain, on: !page.excluded });
          } catch (err) {
            this._integrationNote = { domain: page.domain, text: err.message || "Home Assistant refused the change." };
          }
          await this._refresh();
        } }, page.excluded ? "Cancel the exclusion" : "Exclude this integration"),
      page.excluded
        ? el("span", { class: "muted" }, "Device Sentinel does not watch its devices, and deletes their history at the midnight after it is excluded.")
        : null,
      this._integrationNote && this._integrationNote.domain === page.domain
        ? el("span", { class: "actnote refused" }, this._integrationNote.text) : null);
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
    // Devices another integration owns that reach Home Assistant
    // through the broker, such as Tasmota's, on MQTT's page beneath
    // its own (rule DASH-13).
    const riders = page.behind_broker || [];
    const ridersTable = riders.length
      ? el("div", { class: "scroll" }, el("table", {},
          el("thead", {}, el("tr", {}, ...["DEVICE", "INTEGRATION", "STANDING", "PROBLEM"].map((h) => el("th", {}, h)))),
          el("tbody", {}, ...riders.map((d) => el("tr", {},
            el("td", {}, this._link(d.name, this._devicePath(d.device_id))),
            el("td", {}, d.integration),
            el("td", {}, d.watched ? (d.muted ? `Watched, muted: ${d.muted}` : "Watched") : `Set aside: ${d.set_aside}`),
            el("td", {}, d.problem ? `${d.problem}${d.acknowledged ? ", acknowledged" : ""}` : ""))))))
      : null;
    this._pane.replaceChildren(back, head, ...(exclusion ? [exclusion] : []), stats,
      el("h3", { class: "section" }, "Recommendations"), ...recs,
      // Headings in Title Case, book-title style (rule GEN-06).
      el("h3", { class: "section" }, "Outages, Last 14 Days"), outages,
      el("h3", { class: "section" }, `Devices `, el("span", { class: "small" }, `${page.devices.length}, problems first`)), devices,
      ...(ridersTable ? [
        el("h3", { class: "section" }, "Also on the Broker ", el("span", { class: "small" },
          `${riders.length}, owned by another integration, and down whenever the broker is`)),
        ridersTable] : []));
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
          brief.is_today ? el("td", { class: "ackcell" }, el("label", { class: "ackbox", ...(row.acknowledged ? { title: ACK_HOVER } : {}) },
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

    // The rows themselves, drawn as the table the brief file shows,
    // never as the file's Markdown rows (rule BRIEF-09).
    const repeatRows = brief.repeat.rows || [];
    const repeat = repeatRows.length
      ? [el("div", { class: "scroll" }, el("table", {},
          el("thead", {}, el("tr", {}, ...["DEVICE", "WHAT HAPPENED", "TIMES", "WHEN", "TYPICAL", "WITH"]
            .map((h) => el("th", {}, h)))),
          el("tbody", {}, ...repeatRows.map((row) => el("tr", {},
            el("td", {}, row.device_id ? this._link(row.name, this._devicePath(row.device_id)) : row.name),
            el("td", {}, row.what),
            el("td", {}, String(row.times)),
            el("td", {}, row.when),
            el("td", {}, row.typical),
            el("td", {}, row.with)))))),
        el("p", { style: "margin:8px 0 0;line-height:1.5" }, brief.repeat.paragraph)]
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

    // Empty parts left out: the browser writes a missing one as "null".
    // A line at the top while recommendations are not acknowledged,
    // counting what this view shows, as the emailed Brief does (rule REC-10).
    const active = this._activeRecs();
    const recLine = active ? el("p", { class: "recline", style: "margin:0" },
      `${active} active ${active === 1 ? "recommendation" : "recommendations"} on the `,
      el("a", { href: this._tabPath("Recommendations"), onclick: (ev) => {
        ev.preventDefault();
        this._navigate(this._tabPath("Recommendations"));
      } }, "Recommendations tab"), ".") : null;
    // A detected battery replacement names the device and the day
    // (rule REC-10), as the emailed Brief does.
    const confirm = this._recsInView().cards.find((card) => card.kind === "battery_confirm");
    const confirmLine = confirm && confirm.brief ? el("p", { class: "recline", style: "margin:0" }, confirm.brief) : null;
    this._pane.replaceChildren(...[recLine, confirmLine, nav,
      el("h3", { class: "section" }, "Now"),
      nowLine ? el("p", { style: "margin:0" }, nowLine) : null, nowTable,
      el("h3", { class: "section" }, "Repeat Offenders"), ...repeat,
      el("h3", { class: "section" }, "Last 24 Hours"),
      el("p", { style: "margin:0" }, eventsLine), eventsTable].filter((part) => part));
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

  // Types on a tab (rule DEV-12). Each tab keeps its own choice: "" for
  // every type, NOT_KNOWN_TYPE for devices with none, else the type.
  _typeMatch(chosen, type) {
    if (!chosen) return true;
    return chosen === NOT_KNOWN_TYPE ? !type : type === chosen;
  }

  // A type as a link that narrows the tab to it.
  // A device's type in a list (rules DEV-10, DEV-12): a type that is set
  // is plain words, since the Type filter is what narrows a list; one
  // nobody has set is "Not Set", which opens the way to set it.
  _typeLink(type, deviceId) {
    if (type) return el("span", {}, type);
    return deviceId ? this._notSet("type", deviceId) : el("span", { class: "muted" }, NOT_SET);
  }

  // "Not Set" (rules DEV-10, DASH-04): a type, an area or a battery
  // nobody has set, a link that opens the way to set it in place, with
  // no question first. A type and a battery are set for the whole
  // model; an area for this one device, in Home Assistant. Saved, the
  // dashboard reads everything again, so every tab shows it.
  _notSet(kind, deviceId, opts = {}) {
    const source = opts.source || (this._view ? "device_page" : TAB_SOURCE[this._tab]) || "device_page";
    const holder = el("span", { class: "actrow notset" });
    const note = el("span", { class: "small" }, "");
    const fail = (err) => { note.textContent = (err && err.message) || "That did not save."; };
    const done = async () => {
      await this._refresh();
      // A battery set on a device's page offers Send to Battery Notes
      // below it, as the pencil does (rule DEV-09).
      const fresh = this._page && this._page.identity;
      if (kind === "power" && source === "device_page" && fresh && fresh.device_id === deviceId && fresh.power && fresh.power.report_url) {
        this._devEdit = { device: deviceId, row: "power-saved", saved: true };
        this._paintDevicePage();
      }
    };
    const link = el("button", { class: "linkbtn", type: "button", "aria-label": `${NOT_SET}: set it`, onclick: async () => {
      const picker = kind === "type" ? this._recTypePicker(deviceId, done, fail, source)
        : kind === "power" ? this._recPowerPicker(deviceId, done, fail, opts.name || "", source)
          : await this._areaPicker(deviceId, done, fail, source);
      holder.replaceChildren(picker, el("button", { class: "chip", type: "button",
        onclick: () => { note.textContent = ""; holder.replaceChildren(link, note); } }, "Cancel"), note);
    } }, NOT_SET);
    holder.append(link, note);
    return holder;
  }

  // The areas Home Assistant holds, to choose one in place; Save
  // moves this one device there (rule DASH-09).
  async _areaPicker(deviceId, done, fail, source) {
    let choices;
    try {
      // Asked once for a whole card's rows, again after the next refresh.
      if (!this._areaChoices) this._areaChoices = this._call({ type: "device_sentinel/device_choices" });
      choices = await this._areaChoices;
    } catch (err) {
      this._areaChoices = null;
      fail(err);
      return el("span", {});
    }
    const select = el("select", { class: "actinput", "aria-label": "Which area" },
      el("option", { value: "" }, "Choose…"), ...(choices.areas || []).map((a) => el("option", { value: a.id }, a.name)));
    const save = el("button", { class: "chip", type: "button", disabled: "", onclick: async () => {
      if (!select.value) return;
      try {
        await this._call({ type: "device_sentinel/device_area", device_id: deviceId, area_id: select.value, source });
        await done();
      } catch (err) { fail(err); }
    } }, "Save");
    select.addEventListener("change", () => { save.disabled = !select.value; });
    return el("span", { class: "actrow" }, select, save);
  }

  // A device's area in a list: set, its name; else "Not Set" to set it.
  _areaWords(area, deviceId) {
    if (area) return el("span", {}, area);
    return deviceId ? this._notSet("area", deviceId) : el("span", { class: "muted" }, NOT_SET);
  }

  // The list of types beside a tab's filters, with how many of each.
  _typePicker(types, chosen, pick, label) {
    const counted = [...types.entries()]
      .filter(([type]) => type)
      .sort(([a], [b]) => a.localeCompare(b, undefined, { sensitivity: "base" }) || (a < b ? -1 : a > b ? 1 : 0));
    const total = [...types.values()].reduce((sum, n) => sum + n, 0);
    const unknown = types.get("") || 0;
    return el("select", { class: "actinput", "aria-label": label || "Show one type", onchange: (ev) => pick(ev.target.value) },
      el("option", { value: "", ...(!chosen ? { selected: "" } : {}) }, `All types ${total}`),
      ...counted.map(([type, n]) => el("option", { value: type, ...(chosen === type ? { selected: "" } : {}) }, `${type} ${n}`)),
      ...(unknown ? [el("option", { value: NOT_KNOWN_TYPE, ...(chosen === NOT_KNOWN_TYPE ? { selected: "" } : {}) },
        `${NOT_KNOWN_TYPE} ${unknown}`)] : []));
  }

  _typeShowing(chosen, pick) {
    return chosen ? el("p", { class: "typeshowing", style: "margin:0" }, `Showing ${chosen} only. `,
      el("button", { class: "linkbtn", type: "button", onclick: () => pick("") }, "Show all")) : null;
  }

  _countTypes(rows) {
    const types = new Map();
    for (const row of rows) types.set(row.type || "", (types.get(row.type || "") || 0) + 1);
    return types;
  }

  _paintBatteryTrends() {
    const page = this._snapshot.battery;
    // Simple reads the type and asks for nothing (rule DASH-04).
    const simpleView = this._isSimple();
    // Points a week and points over four weeks, from weekly averages
    // because a rate per day describes a wobble (rule BAT-18).
    const perWeek = (v) => (v === null || v === undefined ? "–"
      : Math.abs(v) < 0.05 ? "level" : v < 0 ? `down ${(-v).toFixed(1)} a week` : `up ${v.toFixed(1)} a week`);
    const moved = (v) => (v === null || v === undefined ? "–"
      : Math.abs(v) < 0.05 ? "level" : v > 0 ? `down ${v.toFixed(1)}` : `up ${(-v).toFixed(1)}`);
    const pct = (v) => (v === null || v === undefined ? "" : `${Math.round(v)}%`);
    this._batterySort = this._batterySort || { key: null, dir: 1 };
    this._modelSort = this._modelSort || { key: null, dir: 1 };
    this._lowSort = this._lowSort || { key: null, dir: 1 };
    this._steadySort = this._steadySort || { key: null, dir: 1 };
    const again = () => this._paintBatteryTrends();
    // One type at a time (rule DEV-12): the whole tab narrows, the bank, the
    // models and every list, and the summary counts what is shown.
    const allCells = page.cell_rows || [];
    const everyone = [...allCells, ...page.unreadable];
    const types = this._countTypes(everyone);
    let chosen = this._batteryType || "";
    if (chosen && !everyone.some((row) => this._typeMatch(chosen, row.type))) chosen = this._batteryType = "";
    const pick = (type) => { this._batteryType = type; again(); };
    const keep = (row) => this._typeMatch(chosen, row.type);
    const cells = allCells.filter(keep);
    const falling = page.falling.filter(keep);
    const watchRows = falling.filter((row) => row.watch);
    const low = page.low.filter(keep);
    const steadyAll = page.steady.filter(keep);
    const unreadableRows = page.unreadable.filter(keep);
    const noBattery = chosen
      ? ((page.no_battery_types || {})[chosen === NOT_KNOWN_TYPE ? "" : chosen] || 0) : page.no_battery;
    const middle = (values) => {
      const s = [...values].sort((a, b) => a - b);
      const n = s.length;
      return !n ? 0 : n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
    };
    let bankCounts = page.bank;
    let modelRows = page.models;
    if (chosen) {
      bankCounts = Array(10).fill(0);
      for (const cell of cells) bankCounts[Math.min(9, Math.floor(cell.level / 10))] += 1;
      // Counted by type, so a model row matches the lists below: a
      // model with one device set apart shows only the cells of the
      // type chosen.
      const byModel = new Map();
      for (const cell of cells) {
        const key = `${cell.maker}\u0000${cell.model}`;
        if (!byModel.has(key)) byModel.set(key, []);
        byModel.get(key).push(cell);
      }
      modelRows = [...byModel.values()].map((group) => {
        const lowest = group.reduce((a, b) => (b.level < a.level ? b : a));
        return { maker: group[0].maker, model: group[0].model, cells: group.length,
          rate: middle(group.map((c) => c.rate)), typical: middle(group.map((c) => c.level)),
          lowest: lowest.level, lowest_name: lowest.name, lowest_id: lowest.device_id,
          types: [[group[0].type || "", group.length]] };
      }).sort((a, b) => a.rate - b.rate || b.cells - a.cells);
    }
    // Three parts that add up to the cells (rule BAT-18): a cell at or under
    // the threshold that is also falling is counted once, as falling.
    const fallingIds = new Set(falling.map((row) => row.device_id));
    const lowOnly = low.filter((row) => !fallingIds.has(row.device_id)).length;
    // The total counted from the same cells as its parts (rule BAT-18):
    // a new cell, or one just replaced, is in both or neither.
    const cellCount = falling.length + lowOnly + steadyAll.length;
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${cellCount} ${cellCount === 1 ? "cell reports" : "cells report"} a level. ${falling.length} falling, `
      + (lowOnly ? `${lowOnly} at or under your threshold of ${page.threshold}% and not falling, ` : "")
      + `${steadyAll.length} not falling or not yet judged. ${noBattery} watched `
      + `${noBattery === 1 ? "device reports" : "devices report"} no battery at all, and ${unreadableRows.length} ${unreadableRows.length === 1 ? "reports" : "report"} a reading that is not a percentage.`);
    // The bank.
    const top = Math.max(...bankCounts, 1);
    const bank = el("div", {},
      el("div", { class: "bank", role: "img", "aria-label": "How many cells sit in each ten percent band" },
        ...bankCounts.map((count, index) => el("div", {
          class: "band",
          title: `${count} cell${count === 1 ? "" : "s"} between ${index * 10}% and ${index * 10 + 10}%`,
        },
        el("div", { class: "count" }, count ? String(count) : ""),
        // An empty band draws nothing: a sliver reads as one cell.
        el("div", { style: `height:${count ? Math.max(3, (count / top) * 100) : 0}%` })))),
      el("div", { class: "statusline small" }, el("span", {}, "0%"),
        el("span", {}, "cells by charge remaining"), el("span", {}, "100%")));
    // Every model, with the types of its cells: one type as a link, a
    // model split between types as each type and its count.
    const typeCell = (row) => {
      const list = row.types || [];
      // Any device of the model sets the model's type (rule DEV-10).
      if (list.length <= 1) return this._typeLink((list[0] || [""])[0], row.lowest_id);
      return el("span", {}, ...list.flatMap(([type, n], i) => [i ? ", " : null, this._typeLink(type, row.lowest_id), ` ${n}`]));
    };
    const modelSort = simpleView && ["typical", "lowest"].includes(this._modelSort.key) ? {} : this._modelSort;
    const models = this._sortRows(modelRows, modelSort, {
      name: (row) => `${row.maker} ${row.model}`.toLowerCase(),
      type: (row) => (((row.types || [])[0] || [""])[0] || "￿").toLowerCase(),
      cells: (row) => row.cells,
      rate: (row) => row.rate,
      typical: (row) => row.typical,
      lowest: (row) => row.lowest,
    });
    // Simple leaves out TYPICAL LEVEL, LOWEST CELL and WHICH ONE (rule DASH-04).
    const fewer = simpleView;
    const modelTable = el("table", { "data-shares": "battery", "data-base": BATTERY_BASE },
      el("thead", {}, el("tr", {},
        this._sortHead(this._modelSort, "MAKER AND MODEL", "name", again),
        this._sortHead(this._modelSort, "TYPE", "type", again),
        this._sortHead(this._modelSort, "CELLS", "cells", again, "num"),
        this._sortHead(this._modelSort, "TYPICAL RATE", "rate", again, "num"),
        ...(fewer ? [] : [
          this._sortHead(this._modelSort, "TYPICAL LEVEL", "typical", again, "num"),
          this._sortHead(this._modelSort, "LOWEST CELL", "lowest", again, "num"),
          el("th", {}, "WHICH ONE")]))),
      el("tbody", {}, ...models.map((row) => el("tr", {},
        el("td", {}, `${row.maker} ${row.model}`),
        el("td", {}, typeCell(row)),
        el("td", { class: "num" }, String(row.cells)),
        el("td", { class: "num", style: row.rate <= -1 ? "color:var(--error-color, #db4437)" : "" }, perWeek(row.rate)),
        ...(fewer ? [] : [
          el("td", { class: "num" }, pct(row.typical)),
          el("td", { class: "num" }, pct(row.lowest)),
          el("td", {}, this._link(row.lowest_name, this._devicePath(row.lowest_id)))])))));
    const byType = (row) => (row.type || "￿").toLowerCase();
    const byName = (row) => (row.name || "").toLowerCase();
    // The report's own groups. A falling cell shows its last five
    // weekly averages and what each week lost (rule BAT-18).
    const weekHeads = ["28 DAYS AGO", "21 DAYS AGO", "14 DAYS AGO", "7 DAYS AGO", "THIS WEEK"];
    const fallingRows = this._sortRows(falling, this._batterySort, {
      name: byName,
      type: byType,
      level: (row) => row.level,
      rate: (row) => -(row.pace || 0),
      reading: (row) => row.reading || "",
    });
    const fallingTable = falling.length
      ? el("div", { class: "scroll" }, el("table", { "data-shares": "battery", "data-base": BATTERY_BASE },
        el("thead", {}, el("tr", {},
          this._sortHead(this._batterySort, "DEVICE", "name", again),
          this._sortHead(this._batterySort, "TYPE", "type", again),
          this._sortHead(this._batterySort, "LEVEL", "level", again, "num"),
          // Simple leaves out the weekly levels (rule DASH-04).
          ...(simpleView ? [] : weekHeads.map((label) => el("th", { class: "num" }, label))),
          this._sortHead(this._batterySort, "PACE", "rate", again, "num"),
          this._sortHead(this._batterySort, "READING", "reading", again),
          el("th", {}, "LEFT"))),
        el("tbody", {}, ...fallingRows.map((row) => {
          const weeks = row.weeks || [];
          const padded = [...Array(Math.max(0, 5 - weeks.length)).fill(null), ...weeks];
          return el("tr", {},
            el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
            el("td", {}, this._typeLink(row.type, row.device_id)),
            el("td", { class: "num" }, levelText(row.level)),
            ...(simpleView ? [] : padded.map((w, i) => el("td", { class: "num" }, w == null ? "–" : `${w.toFixed(1)}%`,
              i > 0 && padded[i - 1] != null ? el("div", { class: "small" }, moved(padded[i - 1] - w)) : ""))),
            el("td", { class: "num" }, perWeek(-(row.pace || 0))),
            el("td", { style: row.reading === "accelerating" ? "color:var(--error-color, #db4437);font-weight:500" : "" }, row.reading || ""),
            // Red for a warning, an accelerating cell inside Days Till Low;
            // a cell to watch is named above the table instead (rule BAT-14).
            el("td", row.left_soon && row.reading === "accelerating" ? { style: "color:var(--error-color, #db4437)" } : {},
              row.until || row.left || ""));
        }))))
      : el("p", { class: "muted", style: "margin:0" }, "No cell is measurably falling.");
    // A sort on a column a view leaves out does not order its rows.
    const lowSort = simpleView && this._lowSort.key === "month" ? {} : this._lowSort;
    const lowRows = this._sortRows(low, lowSort, { name: byName, type: byType, level: (row) => row.level,
      month: (row) => row.month_drop || 0, since: (row) => row.since || "" });
    const lowTable = low.length
      ? el("div", { class: "scroll" }, el("table", { "data-shares": "battery", "data-base": BATTERY_BASE },
        el("thead", {}, el("tr", {},
          this._sortHead(this._lowSort, "DEVICE", "name", again),
          this._sortHead(this._lowSort, "TYPE", "type", again),
          this._sortHead(this._lowSort, "LEVEL", "level", again, "num"),
          // Advanced shows whether a low cell is still falling (rule DASH-04).
          simpleView ? null : this._sortHead(this._lowSort, "4 WEEKS", "month", again, "num"),
          this._sortHead(this._lowSort, "SINCE", "since", again))),
        el("tbody", {}, ...lowRows.map((row) => el("tr", {},
          el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
          el("td", {}, this._typeLink(row.type, row.device_id)),
          el("td", { class: "num" }, levelText(row.level)),
          simpleView ? null : el("td", { class: "num" }, moved(row.month_drop)),
          el("td", {}, row.since ? moment(row.since) : ""))))))
      : el("p", { class: "muted", style: "margin:0" }, "No cell is at or under your threshold.");
    const steadySort = simpleView && ["days", "steps"].includes(this._steadySort.key) ? {} : this._steadySort;
    const steadyRows = this._sortRows(steadyAll, steadySort, { name: byName, type: byType,
      level: (row) => row.level, month: (row) => row.month_drop || 0, days: (row) => row.days || 0,
      steps: (row) => row.steps || "" });
    const steady = el("div", { class: "scroll" }, el("table", { "data-shares": "battery", "data-base": BATTERY_BASE },
      el("thead", {}, el("tr", {},
        this._sortHead(this._steadySort, "DEVICE", "name", again),
        this._sortHead(this._steadySort, "TYPE", "type", again),
        this._sortHead(this._steadySort, "LEVEL", "level", again, "num"),
        this._sortHead(this._steadySort, "4 WEEKS", "month", again, "num"),
        // Simple leaves out how well each cell is measured (rule DASH-04).
        simpleView ? null : this._sortHead(this._steadySort, "DAYS RECORDED", "days", again, "num"),
        simpleView ? null : this._sortHead(this._steadySort, "STEPS", "steps", again),
        el("th", {}, "CELL"),
        simpleView ? null : el("th", { class: "num" }, "MODEL, A WEEK"))),
      el("tbody", {}, ...steadyRows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, this._typeLink(row.type, row.device_id)),
        el("td", { class: "num" }, levelText(row.level)),
        el("td", { class: "num" }, moved(row.month_drop)),
        simpleView ? null : el("td", { class: "num" }, String(row.days)),
        // How the cell reports (rule BAT-09): a coarse cell that is falling
        // sits here with no forecast, and this says why.
        simpleView ? null : el("td", {}, row.steps || ""),
        // The battery it takes, as its Power row says it, lithium named
        // (rule BAT-16); "Not Set" when nobody has said, which opens the
        // way to set it in place, for the whole model (rule DASH-04).
        el("td", {}, row.cell ? (row.lithium ? `${row.cell}, lithium` : row.cell)
          : this._notSet("power", row.device_id, { name: row.name })),
        // How fast the others of its model fall (rule BAT-16).
        simpleView ? null : el("td", { class: "num" }, modelPaceRange(row.model_pace) || "\u2013"))))));
    // A raw sensor value is no level to act on: Advanced only (rule DASH-04).
    const unreadable = unreadableRows.length && !simpleView
      ? el("div", {}, el("div", { class: "scroll" }, el("table", { "data-shares": "battery", "data-base": BATTERY_BASE },
        el("thead", {}, el("tr", {}, el("th", {}, "DEVICE"), el("th", {}, "TYPE"), el("th", { class: "num" }, "READING"))),
        el("tbody", {}, ...unreadableRows.map((row) => el("tr", {},
          el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
          el("td", {}, this._typeLink(row.type, row.device_id)),
          el("td", { class: "num" }, levelText(row.level))))))),
      el("p", { class: "small", style: "margin:6px 0 0" },
        "These report a raw sensor value rather than a battery level, and are never called low. To take them out of these lists, "
        + "mute them for battery in Configure, Low Battery."))
      : null;
    const cellTotal = modelRows.reduce((sum, row) => sum + row.cells, 0);
    // Empty parts are left out before the page is filled: the browser
    // writes a missing one as the word "null", and two read "nullnull".
    this._pane.replaceChildren(...[summary,
      el("div", { class: "actrow" }, this._typePicker(types, chosen, pick)),
      this._typeShowing(chosen, pick),
      el("h3", { class: "section" }, "The Bank"), bank,
      el("h3", { class: "section" }, "By Model ",
        el("span", { class: "small" }, `${modelRows.length} ${modelRows.length === 1 ? "model" : "models"}, ${cellTotal} ${cellTotal === 1 ? "cell" : "cells"}${chosen ? "" : ", all of them"}`)),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "Which of your models eat batteries, and which do not. The rate is the middle of that model's cells: points lost a week over the last four weeks, from weekly averages. Mains-powered devices are absent: they report no battery."),
      el("div", { class: "scroll" }, modelTable),
      el("h3", { class: "section" }, "At or Under the Threshold"), lowTable,
      // Falling at a steady pace inside Days Till Low (rule BAT-14): named, and
      // no warning sent.
      watchRows.length ? el("h3", { class: "section" }, "Batteries to Watch") : null,
      watchRows.length ? el("p", { style: "margin:0;line-height:1.5" }, ...watchRows.flatMap((row, i) => [
        i ? ", " : "", this._link(row.name, this._devicePath(row.device_id)), ` (${row.until || row.left})`]), ".") : null,
      el("h3", { class: "section" }, "Falling"),
      // Judged only near the threshold (rules BAT-10, BAT-13): with no
      // battery yet watched from new to replaced, a date further out is
      // a guess.
      typeof page.ceiling === "number" ? el("p", { class: "small", style: "margin:0;line-height:1.5" },
        `A cell is judged falling, and given a time left, at or under ${page.ceiling}%, three times your threshold. Above it, its last four weeks are shown under Other Cells.`) : null,
      fallingTable,
      el("h3", { class: "section" }, "Other Cells ", el("span", { class: "small" }, `${steadyAll.length} cells`)), steady,
      // One line each, shown when its rows are there, so the MODEL, A
      // WEEK line never hides behind the lithium one.
      steadyAll.some((row) => row.lithium) ? el("p", { class: "small", style: "margin:6px 0 0;line-height:1.5" },
        "A lithium cell holds its level near full until close to its end, so its four weeks say little about how long it has left.") : null,
      !simpleView && steadyAll.some((row) => modelPaceRange(row.model_pace)) ? el("p", { class: "small", style: "margin:6px 0 0;line-height:1.5" },
        "MODEL, A WEEK is how many points the other cells of the same model lose a week, slowest to fastest: context, not this cell's time left.") : null,
      !simpleView && steadyAll.some((row) => !row.cell) ? el("p", { class: "small", style: "margin:6px 0 0;line-height:1.5" },
        "Not Set: no battery type is known for the device. Press Not Set to choose it; one answer covers every device of the same model.") : null,
      unreadable ? el("h3", { class: "section" }, "Not a Percentage") : null, unreadable].filter((part) => part));
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
    // The two middles CHANGE is taken between: this week's and
    // the days before this week, so a row adds up. The second leaves
    // the last seven days out, which is why it is named Before This
    // Week (rule SIG-12).
    const weekOf = (row) => (row.week === undefined ? row.now : row.week);
    const usualOf = (row) => (row.usual === undefined ? row.normal : row.usual);
    // Each sign is taken from the number as shown, so nothing reads
    // "+0" or "-0.0" (rule SIG-12).
    const sign = (v) => {
      if (v === null || v === undefined) return "";
      const shown = Math.round(v) || 0;
      return `${shown > 0 ? "+" : ""}${shown}`;
    };
    const spreads = (v) => {
      if (v === null || v === undefined) return "";
      const shown = Number(v.toFixed(1)) || 0;
      return `${shown > 0 ? "+" : ""}${shown.toFixed(1)}`;
    };
    // The SCALE column belongs to the house, not to the chip: a filter to
    // one scale keeps it, so the columns stay where the All view put them
    // (rule SIG-12).
    const mixed = scales.length > 1;
    const cap = 6;
    const chart = svg("svg", { viewBox: "0 0 1100 170", role: "img",
      "aria-label": "Each device's signal against its own normal, in its own spreads" });
    chart.append(svg("line", { x1: 20, y1: 85, x2: 1080, y2: 85, stroke: "var(--divider-color)" }));
    const width = 1060 / Math.max(1, showing.length);
    showing.forEach((row, index) => {
      const z = Math.max(-cap, Math.min(cap, row.spreads || 0));
      const height = Math.abs(z) / cap * 70;
      // In the columns' own words, so the bar and its row agree (rule SIG-12).
      const words = `${row.name}: ${Math.round(weekOf(row))} this week against ${Math.round(usualOf(row))} before this week, `
        + `${spreads(row.spreads || 0)} of its own spreads`;
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
      el("span", {}, `${showing.length} devices. ${below} sit two spreads or more below their normal, ${above} two spreads or more above. `
        + `The middle device is ${sign(middleChange) || "0"} points.`),
      el("span", {}, "stronger"));
    // The two lists.
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
        now: (row) => weekOf(row) || 0,
        bad: (row) => row.bad_days,
        change: (row) => row.spreads || 0,
      },
    );
    // Both tables carry BAD DAYS, so their columns line up and they read
    // as one table split in two; in the steady one it reads 0, which is
    // why each device is there.
    const table = (rows) => {
      if (!rows.length) return el("p", { class: "muted", style: "margin:0" }, "None.");
      const head = el("tr", {},
        this._sortHead(this._signalSort, "DEVICE", "name", again),
        mixed ? el("th", {}, "SCALE") : null,
        // The column names of rule SIG-12, in capitals as every
        // column head on the dashboard is.
        this._sortHead(this._signalSort, "THIS WEEK", "now", again, "num"),
        el("th", { class: "num" }, "ITS NORMAL"),
        el("th", { class: "num" }, "BAD-DAY LINE"),
        this._sortHead(this._signalSort, "BAD DAYS", "bad", again, "num"),
        el("th", { class: "num" }, "BEFORE THIS WEEK"),
        this._sortHead(this._signalSort, "CHANGE", "change", again, "num"),
        el("th", { class: "num" }, "IN ITS OWN SPREADS"),
        el("th", { class: "num" }, "READINGS A DAY"));
      const body = rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        mixed ? el("td", {}, named[row.scale] || row.scale) : null,
        el("td", { class: "num" }, weekOf(row) === null ? "" : String(Math.round(weekOf(row)))),
        el("td", { class: "num" }, String(Math.round(row.normal))),
        el("td", { class: "num", style: "color:var(--error-color, #db4437)" }, lineWords(row)),
        el("td", { class: "num" }, String(row.bad_days)),
        el("td", { class: "num" }, usualOf(row) === null ? "" : String(Math.round(usualOf(row)))),
        // The change as the two shown numbers give it, so the row adds up.
        el("td", { class: "num", style: colour(row.spreads) },
          weekOf(row) === null || usualOf(row) === null ? sign(row.change) : sign(Math.round(weekOf(row)) - Math.round(usualOf(row)))),
        el("td", { class: "num", style: colour(row.spreads) }, spreads(row.spreads)),
        el("td", { class: "num" }, row.readings_a_day === null ? "" : String(Math.round(row.readings_a_day)))));
      return el("div", { class: "scroll" },
        el("table", {}, el("thead", {}, head), el("tbody", {}, ...body)));
    };
    // Two short columns: on a scale of its own, so DEVICES sits beside
    // DAY instead of across the page.
    const badDays = page.bad_days.length
      ? el("div", { class: "scroll" }, el("table", { "data-base": 12 },
        el("thead", {}, el("tr", {}, el("th", {}, "DAY"), el("th", { class: "num" }, "DEVICES"))),
        el("tbody", {}, ...page.bad_days.map((row) => el("tr", {},
          el("td", {}, moment(`${row.day}T12:00:00`).replace(/,[^,]*$/, "")),
          el("td", { class: "num" }, String(row.devices)))))))
      : el("p", { class: "muted", style: "margin:0" }, "No day had more than one device fall below its line.");
    const unsteady = pick("unsteady");
    const steady = pick("steady");
    // Devices in a flap (rule UNAV-06): worded as something to check,
    // because a flap does not prove a weak link.
    const flapping = page.dropping_out || [];
    const dropping = flapping.length
      ? el("div", { class: "scroll" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "DEVICE"), el("th", { class: "num" }, "DROPS"),
            el("th", {}, "SINCE"), el("th", { class: "num" }, "SIGNAL"))),
          el("tbody", {}, ...flapping.map((row) => el("tr", {},
            el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
            el("td", { class: "num" }, String(row.drops)),
            el("td", {}, row.since ? moment(row.since) : ""),
            el("td", { class: "num" }, row.signal === null || row.signal === undefined ? "" : String(Math.round(row.signal))))))))
      : el("p", { class: "muted", style: "margin:0" }, "No device is dropping out again and again.");
    this._pane.replaceChildren(summary,
      el("h3", { class: "section" }, "Devices That Keep Dropping Out"),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "A device that goes unavailable three times in two hours, and stays listed until it holds on longer than it has between drops. Check its signal and the router it connects through."),
      dropping,
      el("h3", { class: "section" }, "Days Several Devices Had a Bad Day"),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        "One device having a bad day is its own business. Several on the same day usually means something happened to the mesh or the house."),
      badDays,
      el("h3", { class: "section" }, "How Each Link Sits Against Its Own Normal"),
      el("p", { class: "small", style: "margin:0;line-height:1.5" },
        // The second figure leaves this week out, so "its whole
        // history" would not be true (rule SIG-12).
        "Each device's typical signal this week, beside its history. A large drop means its radio link has weakened this week."),
      chips, chart, chartNote,
      el("h3", { class: "section" }, "Devices With Unsteady Signals ", el("span", { class: "small" }, `${unsteady.length} shown`)),
      table(unsteady),
      el("h3", { class: "section" }, "Devices With Steady Signals ", el("span", { class: "small" }, `${steady.length} shown`)),
      table(steady));
  }

  _paintDevices() {
    const all = this._snapshot.devices.rows;
    const excludedAll = this._snapshot.devices.excluded || [];
    const at = this._snapshot.at.getTime();
    const counts = {
      all: all.length,
      problem: all.filter((row) => row.problem).length,
      muted: all.filter((row) => row.muted).length,
    };
    // Search, Area and Label narrow either list (rule DASH-12). A chosen
    // area or label nothing carries any longer goes back to All.
    const excludedView = this._deviceView === "excluded";
    const listed = excludedView ? excludedAll : all;
    const areas = [...new Set(listed.map((row) => row.area).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const labels = [...new Set(listed.flatMap((row) => row.labels || []))].sort((a, b) => a.localeCompare(b));
    if (this._deviceArea && this._deviceArea !== NO_AREA && !areas.includes(this._deviceArea)) this._deviceArea = "";
    if (this._deviceLabel && !labels.includes(this._deviceLabel)) this._deviceLabel = "";
    const wanted = this._deviceSearch.trim().toLocaleLowerCase();
    const narrow = (list) => list.filter((row) =>
      (!wanted || row.name.toLocaleLowerCase().includes(wanted))
      && (!this._deviceArea || (this._deviceArea === NO_AREA ? !row.area : row.area === this._deviceArea))
      && (this._isSimple() || !this._deviceLabel || (row.labels || []).includes(this._deviceLabel)));
    const finders = this._deviceFinders(areas, labels, listed);
    const chipsFor = () => el("div", { class: "chips" }, ...DEVICE_FILTERS.map(([key, label]) =>
      el("button", {
        class: "chip", type: "button", "aria-pressed": String(key === this._deviceFilter),
        onclick: () => {
          this._deviceFilter = key;
          this._paintDevices();
        },
      }, `${label} ${counts[key]}`)));
    // A view of its own rather than a filter chip: its table has other
    // columns, and a filter never moves a table's columns.
    const switchView = (view) => el("button", { class: "linkbtn", type: "button",
      onclick: () => { this._deviceView = view; this._paintDevices(); } },
      view === "excluded"
        ? `Show the ${excludedAll.length} excluded ${excludedAll.length === 1 ? "device" : "devices"}`
        : "Back to the watched devices");
    if (excludedView) {
      this._paintExcludedDevices(narrow(excludedAll), excludedAll.length, switchView("watched"), finders);
      return;
    }
    let rows = narrow(all).filter({
      all: () => true,
      problem: (row) => row.problem,
      muted: (row) => row.muted,
    }[this._deviceFilter]);
    // The Type filter (rule DEV-12), beside the chips, in both views:
    // every type a watched device has, then the ones not set.
    const NOT_KNOWN = NOT_SET;
    // Sorted as people read, so an owner's "lamp" sits with the L's.
    const types = [...new Set(all.map((row) => row.type).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }) || (a < b ? -1 : a > b ? 1 : 0));
    // A chosen type no device has any longer goes back to All types,
    // Not Set included once every device has a type.
    if (this._deviceType && (this._deviceType === NOT_KNOWN ? all.every((row) => row.type) : !types.includes(this._deviceType))) {
      this._deviceType = "";
    }
    if (this._deviceType) {
      rows = rows.filter((row) => (this._deviceType === NOT_KNOWN ? !row.type : row.type === this._deviceType));
    }
    const pickType = (type) => { this._deviceType = type; this._paintDevices(); };
    // A sort on a column Simple leaves out does not order Simple's rows.
    const sort = this._isSimple() && this._deviceSort && ["area", "battery", "last", "rhythm", "window"].includes(this._deviceSort.key)
      ? null : this._deviceSort;
    if (sort) {
      const value = {
        name: (row) => row.name.toLowerCase(),
        type: (row) => (row.type || "\uffff").toLowerCase(),
        integration: (row) => row.integration_name.toLowerCase(),
        area: (row) => (row.area || "\uffff").toLowerCase(),
        battery: (row) => (row.battery == null ? 999 : row.battery),
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
    // Simple leaves out AREA, BATTERY, LAST REPORT, RHYTHM and WINDOW,
    // and the label filter; TYPE and its filter show in both (rule DASH-04).
    const simple = this._isSimple();
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `${all.length} devices are watched. ${counts.problem} ${counts.problem === 1 ? "has" : "have"} a problem, `
      + `${counts.muted} ${counts.muted === 1 ? "is" : "are"} muted.`
      + (simple ? "" : " Each device's window is how long it may stay quiet before it is called frozen, learned from its own rhythm."));
    const chips = chipsFor();
    const table = el("table", { "data-shares": "devices" },
      el("thead", {}, el("tr", {},
        header("DEVICE", "name"), header("TYPE", "type"), simple ? null : header("AREA", "area"),
        header("INTEGRATION", "integration"), el("th", {}, "STANDING"), el("th", {}, "PROBLEM"),
        ...(simple ? [] : [header("BATTERY", "battery", "num"), header("LAST REPORT", "last"),
          header("RHYTHM", "rhythm", "num"), header("WINDOW", "window", "num")]))),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        el("td", {}, this._typeLink(row.type, row.device_id)),
        simple ? null : el("td", {}, this._areaWords(row.area, row.device_id)),
        el("td", {}, this._link(row.integration_name, this._integrationPath(row.integration))),
        el("td", {}, row.muted ? `Muted: ${row.muted}` : "Watched"),
        el("td", {}, row.problem ? `${row.problem}${row.acknowledged ? ", acknowledged" : ""}` : ""),
        ...(simple ? [] : [
          el("td", { class: "num" }, row.battery == null ? "" : `${Math.round(row.battery)}%`),
          el("td", {}, ago(row.last_activity, at)),
          el("td", { class: "num" }, row.rhythm ? span(row.rhythm) : ""),
          el("td", { class: "num" }, row.judged_by ? this._judgedByWords(row.judged_by)
            : row.window ? span(row.window) : row.window_learning ? el("span", { class: "muted" }, "learning") : "")])))));
    // The order a device page's Previous and Next follow.
    this._lists = { ...(this._lists || {}), [TAB_SLUG.Devices]: rows.map((row) => row.device_id) };
    const typeFilter = el("select", { class: "actinput", "aria-label": "Show one type",
      onchange: (ev) => { this._deviceType = ev.target.value; this._paintDevices(); } },
      el("option", { value: "", ...(!this._deviceType ? { selected: "" } : {}) }, "All types"),
      ...[...types, NOT_KNOWN].map((type) => el("option", { value: type, ...(this._deviceType === type ? { selected: "" } : {}) },
        `${type} ${type === NOT_KNOWN ? all.filter((row) => !row.type).length : all.filter((row) => row.type === type).length}`)));
    this._pane.replaceChildren(...[summary, el("div", { class: "actrow" }, chips, typeFilter), finders,
      excludedAll.length ? el("p", { style: "margin:0" }, switchView("excluded")) : null,
      this._typeShowing(this._deviceType, pickType), el("div", { class: "scroll" }, table)].filter((part) => part));
    this._keepSearchFocus();
  }

  // The Devices tab's search box and its Area and Label filters
  // (rule DASH-12), shared by the watched and excluded lists.
  _deviceFinders(areas, labels, listed) {
    const search = el("input", {
      class: "actinput devsearch", type: "search", placeholder: "Search by name", "aria-label": "Search by name",
      value: this._deviceSearch,
      oninput: (ev) => {
        this._deviceSearch = ev.target.value;
        this._searchFocus = { start: ev.target.selectionStart, end: ev.target.selectionEnd };
        this._paintDevices();
      },
    });
    search.value = this._deviceSearch;
    const count = (test) => listed.filter(test).length;
    const area = el("select", { class: "actinput", "aria-label": "Show one area",
      onchange: (ev) => { this._deviceArea = ev.target.value; this._paintDevices(); } },
      el("option", { value: "", ...(!this._deviceArea ? { selected: "" } : {}) }, "All areas"),
      ...areas.map((name) => el("option", { value: name, ...(this._deviceArea === name ? { selected: "" } : {}) },
        `${name} ${count((row) => row.area === name)}`)),
      el("option", { value: NO_AREA, ...(this._deviceArea === NO_AREA ? { selected: "" } : {}) },
        `${NOT_SET} ${count((row) => !row.area)}`));
    const label = el("select", { class: "actinput", "aria-label": "Show one label",
      onchange: (ev) => { this._deviceLabel = ev.target.value; this._paintDevices(); } },
      el("option", { value: "", ...(!this._deviceLabel ? { selected: "" } : {}) }, "All labels"),
      ...labels.map((name) => el("option", { value: name, ...(this._deviceLabel === name ? { selected: "" } : {}) },
        `${name} ${count((row) => (row.labels || []).includes(name))}`)));
    // Labels mute in Advanced only, so Simple has no label filter
    // (rule DASH-04).
    return el("div", { class: "actrow" }, search, area, this._isSimple() ? null : label);
  }

  // Typing repaints the tab, so the search box takes its focus and
  // cursor back each time (rule DASH-12).
  _keepSearchFocus() {
    if (!this._searchFocus) return;
    const box = this._pane.querySelector("input.devsearch");
    const { start, end } = this._searchFocus;
    this._searchFocus = null;
    if (!box) return;
    box.focus();
    try { box.setSelectionRange(start, end); } catch (err) { /* a search box that cannot take a range keeps its focus */ }
  }

  // The Excluded list (rule DASH-12): the devices on the exclusion lists,
  // as Home Assistant has them now, since nothing of them is recorded. A
  // device excluded on its own is taken back here; one excluded with its
  // integration is taken back on that integration's page, because the
  // broader exclusion covers it (rule MUTE-04). A device whose history
  // has gone has no Device Sentinel page, so its name opens Home
  // Assistant's own.
  _paintExcludedDevices(rows, total, back, finders) {
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      total
        ? `${total} ${total === 1 ? "device is" : "devices are"} excluded. Device Sentinel does not watch `
          + `${total === 1 ? "it" : "them"}, and deletes each one's history at the midnight after it is excluded.`
        : "No device is excluded.");
    const takeBack = (row) => el("button", { class: "chip", type: "button",
      onclick: async () => {
        try {
          await this._call({ type: "device_sentinel/device_exclude", device_id: row.device_id, on: false, source: "devices_tab" });
        } catch (err) { /* the refresh shows the list as it stands */ }
        await this._refresh();
      } }, "Cancel the exclusion");
    // Its own widths, so the last column's button and link sit on one
    // line (rule DASH-12).
    const table = el("table", { "data-shares": "excluded" },
      el("thead", {}, el("tr", {}, ...["DEVICE", "INTEGRATION", "AREA", "EXCLUDED", "HISTORY", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        el("td", {}, row.page
          ? this._link(row.name, this._devicePath(row.device_id))
          : this._link(row.name, `/config/devices/device/${encodeURIComponent(row.device_id)}`)),
        el("td", {}, this._link(row.integration_name, this._integrationPath(row.integration))),
        el("td", {}, this._areaWords(row.area, row.device_id)),
        el("td", {}, row.how === "integration" ? "With its integration" : "By you"),
        el("td", {}, row.page ? "Kept until midnight" : "Deleted"),
        el("td", { style: "white-space:nowrap" }, row.how === "integration"
          ? this._link("Open its integration page", this._integrationPath(row.integration))
          : takeBack(row))))));
    this._pane.replaceChildren(summary, el("p", { style: "margin:0" }, back), finders,
      rows.length || !total ? el("div", { class: "scroll" }, table)
        : el("p", { class: "muted", style: "margin:0" }, "No excluded device matches."));
    this._keepSearchFocus();
  }

  _paintReadings() {
    // Each group's current value, with when it changed (rule DASH-08): the
    // first of the device's sensors of that kind that Home Assistant
    // can read. Repainted the moment Home Assistant reports a change.
    const page = this._page;
    const cells = this._readingCells;
    if (!cells || !page || page.error) return;
    for (const [kind, cell] of Object.entries(cells)) {
      let shown = null;
      for (const reading of (page.readings || []).filter((r) => r.kind === kind)) {
        const state = this._hass && this._hass.states ? this._hass.states[reading.entity_id] : null;
        // A reading Home Assistant cannot give is not a reading
        // (rules BAT-02, SIG-04): the second signal entity of a ZHA device often
        // reads unknown.
        if (!state || state.state === "unknown" || state.state === "unavailable") continue;
        let value = state.state;
        if (kind === "battery" && reading.raw_scale && !Number.isNaN(Number(value))) {
          // A sensor on Zigbee's raw 0 to 200 scale (rule BAT-02): its
          // own number, marked raw, then the percentage Device Sentinel
          // reads from it, because "182%" reads as a broken cell.
          const half = Number(value) / 2;
          value = `${value} raw (${levelText(half)})`;
        } else if (state.attributes && state.attributes.unit_of_measurement && !Number.isNaN(Number(value))) {
          value = kind === "battery" && state.attributes.unit_of_measurement === "%"
            ? levelText(Number(value))
            : `${value}${state.attributes.unit_of_measurement === "%" ? "%" : ` ${state.attributes.unit_of_measurement}`}`;
        }
        if (kind === "last_seen" && !Number.isNaN(Date.parse(state.state))) {
          value = new Date(state.state).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        }
        // Home Assistant stamps an entity as changed when a retained
        // message is replayed at a restart (rule WATCH-12), so a value is
        // dated from the device's own last report when that is older.
        const stampedAt = state.last_changed ? new Date(state.last_changed).getTime() : NaN;
        // A time Home Assistant gave that cannot be read: no "changed"
        // at all rather than one that says nothing.
        const stamped = Number.isFinite(stampedAt) ? stampedAt : null;
        const heard = page.status && page.status.last_activity ? new Date(page.status.last_activity).getTime() : null;
        const changed = stamped === null ? ""
          : heard !== null && heard < stamped - 1000
            ? `last heard ${ago(page.status.last_activity, Date.now())}`
            : `changed ${ago(state.last_changed, Date.now())}`;
        shown = [el("span", { class: "readingvalue" }, value), " ", el("span", { class: "small" }, changed)];
        break;
      }
      // A device with no Last seen sensor, or none Home Assistant can
      // read, shows when Device Sentinel last heard it (rule DASH-08):
      // most Matter, Z-Wave and ESPHome devices have no such sensor.
      if (!shown && kind === "last_seen" && page.status && page.status.last_activity
          && Number.isFinite(new Date(page.status.last_activity).getTime())) {
        shown = [el("span", { class: "readingvalue" },
          new Date(page.status.last_activity).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })),
          " ", el("span", { class: "small" }, `heard by Device Sentinel ${ago(page.status.last_activity, Date.now())}`)];
      }
      cell.replaceChildren(...(shown || [el("span", { class: "muted" }, kind === "last_seen" ? "none" : "no reading")]));
    }
  }

  // An entity's own Home Assistant dialog, with its history and settings.
  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  // The list a device page steps through: the one it was opened
  // from, in the order it was shown, or the Devices tab's own order.
  _navList() {
    const rows = this._snapshot && this._snapshot.devices ? this._snapshot.devices.rows : [];
    const known = new Set(rows.map((row) => row.device_id));
    const kept = this._lists && this._lists[this._from || ""];
    // A device removed since the list was drawn is stepped over, never
    // offered; the page itself stays in the list it came from.
    if (kept && this._view && kept.includes(this._view.id)) {
      return kept.filter((id) => id === this._view.id || known.has(id));
    }
    return rows.map((row) => row.device_id);
  }

  _prevNext() {
    if (!this._view || this._view.kind !== "device") return null;
    const ids = this._navList();
    const at = ids.indexOf(this._view.id);
    if (at < 0) return null;
    const names = {};
    for (const row of (this._snapshot && this._snapshot.devices ? this._snapshot.devices.rows : [])) names[row.device_id] = row.name;
    const own = this._from ? `?from=${encodeURIComponent(this._from)}` : "";
    const step = (id, text) => id
      ? el("a", { href: `${this._base}/device/${encodeURIComponent(id)}${own}`, title: names[id] || "",
        onclick: (ev) => { ev.preventDefault(); this._navigate(`${this._base}/device/${encodeURIComponent(id)}${own}`); } }, text)
      : el("span", { class: "muted" }, text);
    return el("span", { class: "prevnext" }, step(ids[at - 1], "\u2039 Previous"), el("span", { class: "muted" }, " \u00b7 "),
      step(ids[at + 1], "Next \u203a"));
  }


  // The device page's actions (rule DASH-09). One edit at a time, tied to its
  // device, so another device's page never shows a half-finished edit.
  _edit(device_id) {
    const e = this._devEdit;
    return e && e.device === device_id ? e : null;
  }

  _editMark(label, onclick) {
    const icon = svg("svg", { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" });
    icon.append(svg("path", { d: "M4 20h4L19 9l-4-4L4 16z" }), svg("path", { d: "M13.5 6.5l4 4" }));
    return el("button", { class: "edit", type: "button", "aria-label": label, onclick }, icon);
  }

  // The Z-Wave status row (rule STACK-05): what Z-Wave says of the node,
  // or that its sensor is switched off, with its own Turn it on.
  // Simple says it is switched off and offers no button: the
  // Recommendations card turns it on (rule DASH-04).
  _nodeStatusCell(who, acts) {
    const WORDS = { alive: "alive", asleep: "asleep", awake: "awake", dead: "dead", unknown: "not known yet" };
    if (who.node_status === "off") {
      return el("div", { class: "actcol" },
        el("span", {}, "switched off"),
        acts && !this._isSimple() ? el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
          onclick: () => this._deviceAct({ type: "device_sentinel/device_turn_on", device_id: who.device_id, kind: "node_status" }, "nodestatus") },
          "Turn it on")) : null,
        this._actNote("nodestatus"));
    }
    // Any other reading, such as "unavailable" after a reload, is not a
    // status of the node (rule STACK-05).
    const word = WORDS[who.node_status] || "not known yet";
    return el("span", who.node_status === "dead" ? { style: "color:var(--error-color, #db4437)" } : {}, word);
  }

  // A Battery or Signal sensor switched off, with the button that
  // switches on this device's own sensor of that kind (rule DASH-09).
  // Simple says it is
  // switched off and offers no button: its Recommendations card turns
  // it on (rule DASH-04).
  _switchedOffCell(who, kind, row) {
    return el("div", { class: "actcol" },
      el("span", {}, "switched off"),
      this._isSimple() ? null : el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
        onclick: () => this._deviceAct({ type: "device_sentinel/device_turn_on", device_id: who.device_id, kind }, row) },
        "Turn it on")),
      this._actNote(row));
  }

  _actNote(row) {
    const e = this._edit(this._page && this._page.identity && this._page.identity.device_id);
    if (!e || e.errorRow !== row || !e.error) return null;
    return el("div", { class: "actnote refused", role: "alert" }, e.error);
  }

  // One action: on success the edit closes and the dashboard is fetched
  // afresh, the page and every tab with it, so a rename, a mute or a new
  // area shows on the Devices tab and the Problem List without pressing
  // Refresh (rule DASH-11); a refusal keeps the row's old value and
  // says why under it.
  async _deviceAct(message, row) {
    const device = message.device_id;
    // A sensor turned on, a power answer or a type set here says it
    // came from the device page; the Recommendations cards send their
    // own source, so the log says where each was done (rules BRIEF-07,
    // DEV-07).
    if (PAGE_SOURCED.has(message.type)) message = { ...message, source: "device_page" };
    try {
      await this._call(message);
      this._devEdit = null;
      await this._refresh();
    } catch (err) {
      const base = this._edit(device) || { device, row };
      if (err && err.code === "name_in_use") {
        this._devEdit = { ...base, row, clash: err.message, error: null };
      } else {
        this._devEdit = { ...base, row, errorRow: row, clash: null,
          error: (err && err.message) || "Home Assistant refused the change." };
      }
    }
    this._paintDevicePage();
  }

  async _openPicker(who, row) {
    try {
      this._choices = await this._call({ type: "device_sentinel/device_choices" });
      this._devEdit = { device: who.device_id, row };
    } catch (err) {
      this._devEdit = { device: who.device_id, row: null, errorRow: row,
        error: (err && err.message) || "Home Assistant's list could not be read." };
    }
    this._paintDevicePage();
  }

  // The Firmware row (rule DEV-15): the version now, and beneath it
  // each version recorded, newest first, with when it was first seen,
  // so a change in how a device reports can be set beside an update.
  _firmwareCell(firmware) {
    const history = Array.isArray(firmware.history) ? firmware.history : [];
    return el("div", { class: "actcol" }, el("span", {}, firmware.current),
      history.length ? el("ul", { class: "small", style: "margin:2px 0 0;padding-left:18px;line-height:1.5" },
        ...[...history].reverse().map((row) => el("li", {},
          row.since ? `${row.version}, first seen ${moment(row.since)}` : row.version))) : null);
  }

  _nameCell(who) {
    const acts = who.actions;
    const e = this._edit(who.device_id);
    if (!e || e.row !== "name") {
      return el("div", { class: "actcol" }, el("div", { class: "actrow" }, el("span", {}, who.name),
        this._editMark("Rename", () => {
          this._devEdit = { device: who.device_id, row: "name", value: acts.name_by_user || who.name };
          this._paintDevicePage();
        })), this._actNote("name"));
    }
    const input = el("input", { class: "actinput", type: "text", "aria-label": "Name", value: e.value || "" });
    input.addEventListener("input", () => { e.value = input.value; });
    const save = (confirm) => this._deviceAct(
      { type: "device_sentinel/device_rename", device_id: who.device_id, name: input.value, confirm }, "name");
    const parts = [el("div", { class: "actrow" }, input,
      el("button", { class: "chip", type: "button", onclick: () => save(false) }, "Save"),
      el("button", { class: "chip", type: "button", onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Cancel"))];
    if (e.clash) {
      parts.push(el("div", { class: "actnote ask", role: "alert" }, e.clash),
        el("div", { class: "actrow" },
          el("button", { class: "chip", type: "button", onclick: () => {
            this._devEdit = { ...e, clash: null };
            this._paintDevicePage();
            const again = this._pane.querySelector("input.actinput");
            if (again) { again.focus(); again.select(); }
          } }, "Change name"),
          el("button", { class: "chip", type: "button", onclick: () => save(true) }, "Save anyway")));
    }
    if (acts.name_by_user) {
      parts.push(el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
        onclick: () => this._deviceAct({ type: "device_sentinel/device_rename", device_id: who.device_id, name: "" }, "name") },
        `Reset to ${acts.integration_name || "the integration's name"}`)));
    }
    parts.push(this._actNote("name"));
    return el("div", { class: "actcol" }, ...parts);
  }

  // What powers the device (rule DEV-07). The library's icon is Battery
  // Notes' own, redrawn small (MIT, credited in the integration's
  // data folder), and opens its repository; the owner's is Device
  // Sentinel's shield. Each has a version for the dark theme.
  _powerIcon(power, deviceId) {
    const dark = !!(this._hass && this._hass.themes && this._hass.themes.darkMode);
    const icon = svg("svg", { width: 20, height: 20, viewBox: "0 0 24 24", "aria-hidden": "true" });
    if (power.source === "library") {
      const c = dark
        ? { body: "#64B5F6", edge: "#90CAF9", note: "#FFF59D", ink: "#1C1C1C" }
        : { body: "#4CA8F2", edge: "#1E88E5", note: "#FFF176", ink: "#212121" };
      const note = svg("g", { transform: "rotate(-11 12 9.5)" });
      note.append(svg("rect", { x: 6.6, y: 5.9, width: 10.8, height: 7.2, rx: 0.6, fill: c.note }),
        svg("path", { d: "M8.6 8.6 H15.4 M8.6 10.6 H14.2", stroke: c.ink, "stroke-width": 1.15, "stroke-linecap": "round" }));
      icon.append(
        svg("rect", { x: 8.5, y: 0.75, width: 7, height: 3, rx: 1, fill: c.body, stroke: c.edge, "stroke-width": 0.75 }),
        svg("rect", { x: 4.75, y: 2.75, width: 14.5, height: 20.5, rx: 2.5, fill: c.body, stroke: c.edge, "stroke-width": 0.75 }),
        note);
      const title = "From the Battery Notes library";
      return el("a", { class: "powericon", href: power.library_home, target: "_blank", rel: "noopener noreferrer",
        title, "aria-label": `${title}, opens its repository` }, icon);
    }
    const c = dark ? { shield: "#B0C4DE", trace: "#1F3A4D" } : { shield: "#224A5E", trace: "#FFFFFF" };
    icon.append(
      svg("path", { d: "M12 2 L20 5 V11 C20 16.5 16.6 20.7 12 22 C7.4 20.7 4 16.5 4 11 V5 Z", fill: c.shield }),
      svg("path", { d: "M6.5 12.5 H9.4 L10.9 9.2 L13.1 15.6 L14.6 12.5 H17.5", fill: "none", stroke: c.trace,
        "stroke-width": 1.6, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    // An answer set on another device of its model names that device,
    // as the line under the row does (rule DEV-07).
    const title = power.set_on && power.set_on !== deviceId
      ? `Entered on ${power.set_on_name || "another device"}` : "Entered on this page";
    return el("span", { class: "powericon", title, role: "img", "aria-label": title }, icon);
  }

  // A day as the dashboard writes one: Oct 18, 2026.
  _dayWords(iso) {
    const day = new Date(`${iso}T12:00:00`);
    return day.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  }

  // The answers to a detected replacement (rule BAT-07): Confirm,
  // Change date and Cancel, on the device page and on its card.
  _batteryAnswers(deviceId, after, row) {
    const send = async (message) => {
      try {
        await this._call({ type: "device_sentinel/device_battery", device_id: deviceId, ...message });
        await after(null);
      } catch (err) {
        await after((err && err.message) || "That did not save.");
      }
    };
    // An open "Change date" and the day picked so far are kept by device,
    // so the page's minute refresh does not close it mid-pick. Kept in
    // memory only, and dropped once an answer is sent.
    this._batteryDayOpen = this._batteryDayOpen || {};
    const held = this._batteryDayOpen[deviceId];
    const day = el("input", { class: "actinput", type: "date", "aria-label": "The day the battery was changed",
      max: localDay(new Date()), value: held ? held.value : "" });
    day.style.display = held ? "" : "none";
    day.addEventListener("input", () => { this._batteryDayOpen[deviceId] = { value: day.value }; });
    const sendAndForget = (message) => { delete this._batteryDayOpen[deviceId]; return send(message); };
    const save = el("button", { class: "chip", type: "button", style: held ? "" : "display:none",
      onclick: () => day.value && sendAndForget({ action: "date", day: day.value }) }, "Save");
    return el("div", { class: "actrow" },
      el("button", { class: "chip", type: "button", onclick: () => sendAndForget({ action: "confirm" }) }, "Confirm"),
      el("button", { class: "chip", type: "button", onclick: () => {
        this._batteryDayOpen[deviceId] = { value: day.value };
        day.style.display = ""; save.style.display = "";
      } }, "Change date"),
      day, save,
      el("button", { class: "chip", type: "button", onclick: () => sendAndForget({ action: "cancel" }) }, "Cancel"),
      row);
  }

  _batteryReplacedCell(who) {
    const view = who.battery_replaced;
    const acts = who.actions;
    const after = async (error) => {
      if (error) {
        this._devEdit = { device: who.device_id, row: null, errorRow: "batteryreplaced", error };
      } else {
        this._devEdit = null;
        await this._refresh();
      }
      this._paintDevicePage();
    };
    if (view.waiting) {
      return el("div", { class: "actcol" },
        el("span", {}, `Detected ${view.words.done} on ${this._dayWords(view.day)}`),
        acts ? this._batteryAnswers(who.device_id, after, null) : null,
        this._actNote("batteryreplaced"));
    }
    const e = this._edit(who.device_id);
    // With no replacement on record, when the device was first seen
    // (rule BAT-07): "Device first detected {day}. No battery
    // replacement yet."
    const firstSeen = view.first_seen
      ? `Device first detected ${new Date(`${view.first_seen}T12:00:00`).toLocaleDateString([], { month: "long", day: "numeric", year: "numeric" })}. ${view.words.none}.`
      : null;
    const words = view.day ? this._dayWords(view.day) : (firstSeen || view.words.none);
    const shown = el("div", { class: "actrow" }, el("span", {}, words),
      view.how === "entered" ? el("span", { class: "muted small" }, "set by you") : null,
      acts ? this._editMark(`Change the day the battery was ${view.words.done}`, () => {
        this._devEdit = { device: who.device_id, row: "batteryreplaced" };
        this._paintDevicePage();
      }) : null);
    if (!acts || !e || e.row !== "batteryreplaced") {
      return el("div", { class: "actcol" }, shown, this._actNote("batteryreplaced"));
    }
    const day = el("input", { class: "actinput", type: "date", "aria-label": "The day the battery was changed",
      max: localDay(new Date()), value: view.day || "" });
    return el("div", { class: "actcol" }, shown,
      el("div", { class: "actrow" }, day,
        el("button", { class: "chip", type: "button", onclick: () => day.value && this._deviceAct(
          { type: "device_sentinel/device_battery", device_id: who.device_id, action: "date", day: day.value }, "batteryreplaced") }, "Save"),
        el("button", { class: "chip", type: "button", onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Cancel")),
      this._actNote("batteryreplaced"));
  }

  _powerCell(who) {
    const power = who.power || { words: NOT_SET, source: null };
    const acts = who.actions;
    const e = this._edit(who.device_id);
    const openPower = () => {
      const entry = power.entry;
      const wired = power.wired || [power.mains, power.usb];
      const pick = entry ? (power.battery_choices.includes(entry.type) || wired.includes(entry.type)
        ? entry.type : power.other) : "";
      this._devEdit = { device: who.device_id, row: "power", choice: pick,
        quantity: (entry && entry.quantity) || 1, other: entry && pick === power.other ? entry.type : "" };
      this._paintDevicePage();
    };
    // Nothing known reads "Not Set", which opens the pencil's choices;
    // the pencil stays beside it (rule DASH-04).
    const words = power.source ? el("span", {}, power.words)
      : acts ? el("button", { class: "linkbtn", type: "button", onclick: openPower }, NOT_SET)
        : el("span", { class: "muted" }, NOT_SET);
    const shown = el("div", { class: "actrow" }, words,
      power.source ? this._powerIcon(power, who.device_id) : null,
      acts ? this._editMark("Change what powers this device", openPower) : null);
  // Where an owner's entry was set, and how many it covers (rule DEV-07).
    const elsewhere = power.source === "owner" && power.set_on && power.set_on !== who.device_id;
    const covers = power.source === "owner" && power.covers > 1;
    const whence = elsewhere || covers ? el("div", { class: "muted small powerwhence" },
      [elsewhere ? `set on ${power.set_on_name || "another device"}` : "set here",
        covers ? `covers ${power.covers} devices of this model` : null].filter(Boolean).join(", ")) : null;
    if (!acts || !e || e.row !== "power") {
      return el("div", { class: "actcol" }, shown, whence, this._powerReport(who, e), this._actNote("power"));
    }
    const [qmin, qmax] = power.quantity || [1, 8];
    const isBattery = (choice) => choice && !(power.wired || [power.mains, power.usb]).includes(choice);
    const select = el("select", { class: "actinput", "aria-label": "What powers this device" },
      el("option", { value: "" }, "Choose…"),
      ...power.choices.map((choice) => el("option", { value: choice, ...(e.choice === choice ? { selected: "" } : {}) }, choice)));
    const quantity = el("select", { class: "actinput", "aria-label": "How many" },
      ...Array.from({ length: qmax - qmin + 1 }, (_, i) => qmin + i).map((n) =>
        el("option", { value: String(n), ...(Number(e.quantity) === n ? { selected: "" } : {}) }, `× ${n}`)));
    const other = el("input", { class: "actinput", type: "text", maxlength: "40", "aria-label": "Battery or power source",
      placeholder: "Battery or power source", value: e.other || "" });
    const repaint = () => {
      quantity.style.display = isBattery(select.value) ? "" : "none";
      other.style.display = select.value === power.other ? "" : "none";
    };
    select.addEventListener("change", () => { e.choice = select.value; repaint(); });
    quantity.addEventListener("change", () => { e.quantity = Number(quantity.value); });
    other.addEventListener("input", () => { e.other = other.value; });
    repaint();
    const save = () => {
      if (!select.value) return;
      const message = { type: "device_sentinel/device_power", device_id: who.device_id, choice: select.value };
      if (isBattery(select.value)) message.quantity = Number(quantity.value);
      if (select.value === power.other) message.other = other.value;
      this._powerAct(message);
    };
    const parts = [el("div", { class: "actrow" }, select, quantity, other,
      el("button", { class: "chip", type: "button", onclick: save }, "Save"),
      el("button", { class: "chip", type: "button", onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Cancel"))];
    if (power.entry) {
      parts.push(el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
        onclick: () => this._powerAct({ type: "device_sentinel/device_power", device_id: who.device_id, choice: null }) },
        power.model_answer ? `Use the model's answer (${power.model_answer})`
          : power.library ? `Use the library (${power.library})` : "Use the library")));
    }
    parts.push(this._actNote("power"));
    return el("div", { class: "actcol" }, ...parts);
  }

  // The other devices Home Assistant shows for this hardware (rule WATCH-06):
  // the one Device Sentinel watches it through first, then the rest,
  // each with its integration and why it is not watched.
  _sameHardwareCell(who) {
    const same = who.same_hardware || { devices: [] };
    // Worded from each row's own state, so a page never says another
    // device is watched when this one is too.
    const mine = same.devices.find((row) => row.device_id === who.device_id);
    const others = same.devices.filter((row) => row.device_id !== who.device_id && row.watched);
    const lead = mine && mine.watched
      ? (others.length ? "Device Sentinel watches this device, and another device for the same hardware too."
        : "Device Sentinel watches this hardware through this device.")
      : others.length ? "Device Sentinel watches this hardware through another device."
        : "Device Sentinel watches none of these devices.";
    const why = (row) => (row.watched ? "watched"
      : row.set_aside === "clone" ? "a clone, not judged on its own"
        : row.set_aside ? `set aside: ${row.set_aside}` : "not watched");
    return el("div", { class: "actcol" },
      el("div", {}, lead),
      ...same.devices.filter((row) => row.device_id !== who.device_id).map((row) => el("div", { class: "muted small" },
        row.has_page === false ? (row.name || row.device_id) : this._link(row.name || row.device_id, this._devicePath(row.device_id)),
        ` (${row.integration || "unknown"}), ${why(row)}`)));
  }

  // What the device is (rule DEV-10): the owner's answer, else Device
  // Sentinel's own (a known model, a network role, its entities), else
  // "Not Set", which opens the pencil's choices; the pencil stays beside
  // it (rule DASH-04). Like the Power row, an answer covers the whole
  // model.
  _typeCell(who) {
    const kind = who.type || { words: null, source: null, choices: [], other: "Other" };
    const acts = who.actions;
    const e = this._edit(who.device_id);
    const open = () => {
      // The type shown now is chosen to start with, whoever gave it.
      const pick = kind.source === "owner"
        ? (kind.choices.includes(kind.words) ? kind.words : kind.other)
        : (kind.choices.includes(kind.words) ? kind.words : "");
      this._devEdit = { device: who.device_id, row: "type", choice: pick,
        other: kind.source === "owner" && pick === kind.other ? kind.words : "" };
      this._paintDevicePage();
    };
    const words = kind.words
      ? el("span", {}, kind.words)
      : acts
        ? el("button", { class: "linkbtn", type: "button", onclick: open }, NOT_SET)
        : el("span", { class: "muted" }, NOT_SET);
    const shown = el("div", { class: "actrow" }, words,
      // The hover names where the answer was entered, as the Power
      // row's does (rule DEV-07).
      kind.source === "owner" ? this._powerIcon({ source: "owner", set_on: kind.set_on, set_on_name: kind.set_on_name }, who.device_id) : null,
      acts ? this._editMark("Change what this device is", open) : null);
    const elsewhere = kind.source === "owner" && kind.set_on && kind.set_on !== who.device_id;
    const covers = kind.source === "owner" && kind.covers > 1;
    const whence = elsewhere || covers ? el("div", { class: "muted small powerwhence" },
      [elsewhere ? `set on ${kind.set_on_name || "another device"}` : "set here",
        covers ? `covers ${kind.covers} devices of this model` : null].filter(Boolean).join(", ")) : null;
    if (!acts || !e || e.row !== "type") {
      return el("div", { class: "actcol" }, shown, whence, this._actNote("type"));
    }
    const select = el("select", { class: "actinput", "aria-label": "What this device is" },
      el("option", { value: "" }, "Choose…"),
      ...kind.choices.map((choice) => el("option", { value: choice, ...(e.choice === choice ? { selected: "" } : {}) }, choice)));
    const other = el("input", { class: "actinput", type: "text", maxlength: "40",
      "aria-label": "Your own words for what this device is", placeholder: "What this device is", value: e.other || "" });
    // Save waits for a choice, so pressing it never does nothing.
    const saveButton = el("button", { class: "chip", type: "button", onclick: () => save() }, "Save");
    const repaint = () => {
      other.style.display = select.value === kind.other ? "" : "none";
      saveButton.disabled = !select.value;
    };
    select.addEventListener("change", () => { e.choice = select.value; repaint(); });
    other.addEventListener("input", () => { e.other = other.value; });
    repaint();
    const save = () => {
      if (!select.value) return;
      const message = { type: "device_sentinel/device_type", device_id: who.device_id, choice: select.value };
      if (select.value === kind.other) message.other = other.value;
      this._deviceAct(message, "type");
    };
    const parts = [el("div", { class: "actrow" }, select, other, saveButton,
      el("button", { class: "chip", type: "button", onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Cancel"))];
    if (kind.source === "owner") {
      parts.push(el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
        onclick: () => this._deviceAct({ type: "device_sentinel/device_type", device_id: who.device_id, choice: null }, "type") },
        kind.model_answer ? `Use the model's answer (${kind.model_answer})`
          : kind.auto && kind.auto_source && kind.auto_source !== "entities"
            ? `Use Device Sentinel's answer (${kind.auto})`
            : kind.auto ? `Use what its entities say (${kind.auto})` : "Use what its entities say")));
    }
    parts.push(this._actNote("type"));
    return el("div", { class: "actcol" }, ...parts);
  }

  // After a save, the page offers to send the entry to Battery Notes'
  // library: its New Device form, filled in, in a new tab. The owner
  // presses Submit there; the library's author reviews every entry.
  _powerReport(who, e) {
    const power = who.power || {};
    if (!power.report_url || !e || !e.saved) return null;
    return el("div", { class: "actrow" },
      el("span", { class: "muted" }, "Saved. Battery Notes' library does not list this yet."),
      el("a", { class: "chip", href: power.report_url, target: "_blank", rel: "noopener noreferrer",
        style: "display:inline-flex;align-items:center;text-decoration:none" }, "Send to Battery Notes"));
  }

  async _powerAct(message) {
    await this._deviceAct(message, "power");
    const fresh = this._page && this._page.identity;
    if (!this._devEdit && fresh && fresh.device_id === message.device_id && fresh.power && fresh.power.report_url) {
      this._devEdit = { device: message.device_id, row: "power-saved", saved: true };
      this._paintDevicePage();
    }
  }

  _areaCell(who) {
    const acts = who.actions;
    const e = this._edit(who.device_id);
    if (!e || e.row !== "area" || !this._choices) {
      const openArea = () => this._openPicker(who, "area");
      return el("div", { class: "actcol" }, el("div", { class: "actrow" },
        who.area ? el("span", {}, who.area) : el("button", { class: "linkbtn", type: "button", onclick: openArea }, NOT_SET),
        this._editMark("Change area", openArea)), this._actNote("area"));
    }
    const choose = (area_id) => this._deviceAct(
      { type: "device_sentinel/device_area", device_id: who.device_id, area_id }, "area");
    const option = (id, name) => el("label", { class: "pick" },
      el("input", { type: "radio", name: "ds-area", ...((acts.area_id || null) === id ? { checked: "" } : {}),
        onchange: () => choose(id) }), name);
    return el("div", { class: "actcol" },
      el("fieldset", { style: "border:none;margin:0;padding:0" },
        el("legend", { class: "muted", style: "padding:0 0 4px" }, "Area"),
        option(null, "No area"), ...this._choices.areas.map((a) => option(a.id, a.name))),
      this._newNameRow("New area", "Create and move here",
        (name) => this._deviceAct({ type: "device_sentinel/device_new_area", device_id: who.device_id, name }, "area")),
      el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
        onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Cancel")),
      this._actNote("area"));
  }

  // A new area or label made from Device Sentinel's own picker, so a
  // person need not leave for Home Assistant's settings and come back
  // (rule DASH-09). A name Home Assistant already holds is used
  // as it is.
  _newNameRow(label, action, save) {
    const input = el("input", { class: "actinput", type: "text", "aria-label": label, placeholder: label });
    const go = () => { if (input.value.trim()) save(input.value); };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") go(); });
    return el("div", { class: "actrow" }, input,
      el("button", { class: "chip", type: "button", onclick: go }, action));
  }

  _labelsCell(who) {
    const acts = who.actions;
    const e = this._edit(who.device_id);
    const cross = () => {
      const icon = svg("svg", { width: 12, height: 12, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
        "stroke-width": 2.4, "stroke-linecap": "round", "aria-hidden": "true" });
      icon.append(svg("path", { d: "M6 6l12 12" }), svg("path", { d: "M18 6L6 18" }));
      return icon;
    };
    // A label that mutes this device is drawn lit; its × takes it off
    // this device and so lifts the mute here (rule MUTE-09).
    const muting = new Set(Object.values(acts.mutes || {}).flatMap((m) =>
      (m && typeof m.source === "string" && m.source.startsWith("label: ") ? m.source.slice(7).split(", ") : [])));
    const chips = acts.labels.map((label) => el("span", { class: muting.has(label.name) ? "labelchip on" : "labelchip" }, label.name,
      label.meaning ? el("span", { class: "meaning" }, label.meaning) : null,
      el("button", { type: "button", "aria-label": `Remove the label ${label.name} from this device`,
        title: "Removes the label from this device in Home Assistant.",
        onclick: () => this._deviceAct({ type: "device_sentinel/device_label", device_id: who.device_id,
          label_id: label.id, add: false }, "labels") }, cross())));
    const parts = [el("div", { class: "actrow" }, ...chips,
      el("button", { class: "chip", type: "button", onclick: () => this._openPicker(who, "labels") }, "Add label"))];
    if (e && e.row === "labels" && this._choices) {
      const have = new Set(acts.labels.map((l) => l.id));
      const offer = this._choices.labels.filter((l) => !have.has(l.id));
      parts.push(el("div", { class: "actcol" },
        ...offer.map((l) => el("div", { class: "actrow" },
          el("button", { class: "chip", type: "button",
            onclick: () => this._deviceAct({ type: "device_sentinel/device_label", device_id: who.device_id,
              label_id: l.id, add: true }, "labels") }, "Add"),
          el("span", {}, l.name), l.meaning ? el("span", { class: "muted" }, l.meaning) : null)),
        this._newNameRow("New label", "Create and add",
          (name) => this._deviceAct({ type: "device_sentinel/device_new_label", device_id: who.device_id, name }, "labels")),
        el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
          onclick: () => { this._devEdit = null; this._paintDevicePage(); } }, "Done"))));
    }
    parts.push(this._actNote("labels"));
    return el("div", { class: "actcol" }, ...parts);
  }

  _mutedCell(who, hub) {
    const mutes = who.actions.mutes;
    // The device's own Mute everything covers its single mutes.
    const everything = Boolean(mutes.everything && mutes.everything.here);
    const toggle = (kind, words) => {
      const m = mutes[kind] || { on: false, here: false };
      // A button shows only the device's own mute, so every lit button
      // lifts its mute when pressed; a mute from a label, an
      // integration or a hub lights none of them and is named below
      // (rule MUTE-09). Mute everything set here lights the single
      // mutes it covers, held. Freeze and unavailable are each their
      // own (rule MUTE-06).
      const covered = kind !== "everything" && everything;
      const own = Boolean(m.here);
      const lit = own || covered;
      return el("button", { class: lit ? "chip on" : "chip", type: "button", "aria-pressed": String(lit),
        ...(covered && !own ? { "aria-disabled": "true", title: "Muted by Mute everything." }
          : own ? { title: "Muted. Press to lift the mute." } : {}),
        onclick: () => {
          if (covered && !own) return;
          // One press, no confirm: a second press undoes it (rule MUTE-09).
          this._deviceAct({ type: "device_sentinel/device_mute", device_id: who.device_id, kind, on: !own }, "muted");
        } }, lit ? `\u2713 ${words}` : words);
    };
    // The buttons say what is muted, with no word for none (rule MUTE-09).
    const parts = [
      el("div", { class: "actrow" }, toggle("freeze", "Mute freeze"), toggle("unavailable", "Mute unavailable"),
        toggle("battery", "Mute battery"), toggle("signal", "Mute signal"), toggle("everything", "Mute everything"))];
    // A mute from a label, an integration or a hub says where it comes
    // from and where it is lifted (rule MUTE-09).
    for (const [kind, words, section] of MUTE_SOURCES) {
      const m = mutes[kind];
      if (!m || !m.on || !m.source || m.source === "device") continue;
      const source = String(m.source);
      if (source === "hub") {
        // A hub's mute covers the devices it controls and is lifted on
        // the hub's page (rule STACK-10).
        parts.push(el("div", { class: "actnote" }, `${words} is muted with its hub. Change it on `,
          hub ? this._link(`${hub.name}'s page`, this._devicePath(hub.device_id)) : "the hub's page", "."));
        continue;
      }
      if (source.startsWith("label: ")) {
        const from = `the label ${source.slice(7)}`;
        // The device's own mute as well: the button lifts that one, and
        // the label's stays until the label goes (rule MUTE-09).
        if (m.here) {
          parts.push(el("div", { class: "actnote" }, `${words} is also muted by ${from}, which stays when you lift your own.`));
          continue;
        }
        // Advanced: take the label off this device in the Labels row, or
        // change what it does in settings. Simple has no Labels row, and
        // says where (rule DASH-04).
        parts.push(this._isSimple()
          ? el("div", { class: "actnote" }, `${words} is muted by ${from}. Switch to `,
            el("button", { class: "linkbtn", type: "button", onclick: () => this._switchMode("advanced") }, "Advanced"),
            " to change it.")
          : el("div", { class: "actnote" }, `${words} is muted by ${from}. Remove the label above to lift it for this device, or change it in `,
            this._link("Device Sentinel's settings", SETTINGS_PATH), `, Configure, ${section}.`));
        continue;
      }
      const from = source.startsWith("integration: ")
        ? `the integration ${source.slice(13) === who.integration && who.integration_title ? who.integration_title : source.slice(13)}`
        : source;
      // An integration's mute is changed on the Integrations tab (rule MUTE-03).
      parts.push(source.startsWith("integration: ")
        ? el("div", { class: "actnote" }, `${words} is muted by ${from}. Change it on the `,
          this._link("Integrations tab", this._tabPath("Integrations")), ".")
        : el("div", { class: "actnote" }, `${words} is muted by ${from}. Change it in `,
          this._link("Device Sentinel's settings", SETTINGS_PATH), `, Configure, ${section}.`));
    }
    parts.push(this._actNote("muted"));
    return el("div", { class: "actcol" }, ...parts);
  }

  // Exclude one device (rule MUTE-03): the integration exclusion's
  // rules for this device alone, one press with no confirm. Only the
  // device's own exclusion is lifted here; an excluded integration is
  // changed on the Integrations tab.
  _excludedCell(who) {
    const ex = who.actions.excluded || { here: false, integration: false };
    const act = (on) => this._deviceAct({ type: "device_sentinel/device_exclude", device_id: who.device_id, on }, "excluded");
    const parts = [];
    // Another listing of the same hardware can take over the watching,
    // as it does when an integration is excluded (rule MUTE-03).
    const copies = who.same_hardware && Array.isArray(who.same_hardware.devices) && who.same_hardware.devices.length > 1;
    const takeover = copies ? " If another listing of the same hardware can be watched, Device Sentinel watches the hardware through it instead." : "";
    if (ex.here) {
      // Watching stops at once; the history goes at midnight, and until
      // then cancelling loses nothing (rule MUTE-03).
      parts.push(el("span", {}, "Excluded. Device Sentinel has stopped watching this device and deletes its history at midnight. "
        + `After that this page is gone, and the device is taken back in Device Sentinel's settings, Exclusions and Muting.${takeover}`),
        el("div", { class: "actrow" }, el("button", { class: "chip", type: "button", onclick: () => act(false) }, "Cancel the exclusion")));
    } else if (ex.integration) {
      parts.push(el("div", { class: "actnote" }, "Its integration is excluded. Change it on the ",
        this._link("Integrations tab", this._tabPath("Integrations")), "."));
    } else {
      // A watched device shows only the button (rule MUTE-03).
      parts.push(
        el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
          onclick: () => act(true) }, "Exclude this device")));
    }
    parts.push(this._actNote("excluded"));
    return el("div", { class: "actcol" }, ...parts);
  }

  _paintDevicePage() {
    const page = this._page;
    this._pane.classList.add("devpage");
    const back = el("p", { style: "margin:0;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap" },
      // Previous and Next beside the way back (rule DASH-07).
      el("span", { class: "actrow" }, this._backLink(), this._prevNext()),
      // Shown once, here at the top, never a second time in the header.
      this._page && this._page.identity
        ? this._link("Open in Home Assistant", `/config/devices/device/${encodeURIComponent(this._page.identity.device_id)}`)
        : null);
    this._readingCells = null;
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
    let [word, colour] = STATUS_WORDS[status.category] || [status.category, "var(--disabled-text-color, #888)"];
    if (status.flap) word = `${word}, ${status.flap}`;
    // Muted: the verdict is true and nobody asked to hear it, so the
    // word stays and the alarm color goes (rule MUTE-07).
    if (page.identity && page.identity.muted && status.category !== "set_aside") {
      word = `${word}, muted`;
      colour = "var(--disabled-text-color, #888)";
    }
    const quiet = status.last_activity ? (now - new Date(status.last_activity).getTime()) / 1000 : null;
    const fill = status.window && quiet !== null ? Math.min(1, quiet / status.window) : 0;
    const standing = who.watched ? (who.muted ? `Watched, muted: ${who.muted}` : "Watched") : `Set aside: ${who.set_aside}`;
    // Judged by its hub (rule STACK-10): a hub reads up
    // or down from its connection, and a device it controls is judged by it.
    const hub = page.hub || null;
    const hubSelf = page.hub_self || null;
    const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "an unknown time");
    // A verdict of its own, or a mute, is shown as on any page: the hub's
    // words take the place of the plain "reporting" only.
    const ownVerdict = ["frozen", "unavailable", "unknown", "never_reported", "flapping"].includes(status.category);
    if (hub && !ownVerdict && !(who && who.muted)) {
      word = hub.up === false ? "Its hub is down" : "Judged by its hub";
      colour = hub.up === false ? "var(--error-color, #db4437)" : "var(--success-color, #43a047)";
    }
    if (hubSelf) {
      word = hubSelf.up ? "Up" : "Down";
      colour = hubSelf.up ? "var(--success-color, #43a047)" : "var(--error-color, #db4437)";
      if (who && who.muted) {
        word = `${word}, muted`;
        colour = "var(--disabled-text-color, #888)";
      }
    }
    const head = el("div", { class: "pagehead" },
      el("div", {},
        el("h2", {}, who.name),
        el("div", { class: "muted" },
          [who.manufacturer, who.model].filter(Boolean).join(" ") || "Device",
          who.integration ? [" on ", this._link(who.integration_name || who.integration, this._integrationPath(who.integration))] : "",
          `. ${standing}.`)),
      el("div", { class: "links" },
        el("span", { class: "small" }, "Live, updates every minute")));
    // Simple shows the freeze window and the rhythm only for a device
    // that is frozen or never reported (rule DASH-04).
    const simple = this._isSimple();
    const rhythmShown = !simple || ["frozen", "never_reported"].includes(status.category);
    // By its hub or by its connection: never judged for freezing.
    const judged = status.judged_by || null;
    const statusBox = el("div", { class: "devstatus" },
      el("div", { class: "statusline" },
        el("div", { style: "font-size:18px;font-weight:500;display:flex;align-items:center;gap:8px" },
          el("span", { class: "dot", style: `background:${colour}` }), word),
        el("div", { class: "muted" }, status.connection
          // Judged by its connection alone (rule STACK-07).
          ? `Judged by its connection: ${status.connection}.`
          // Never judged for freezing: one sentence in place of the
          // window and the learning line.
          : judged
            ? this._judgedByWords(judged, ".")
          // A Matter device of a type that reports only on use (rule STACK-06).
          : status.available_rule
            ? `Last report ${ago(status.last_activity, now)}. Not called frozen while Home Assistant shows it available.`
          : status.window
            ? `Last report ${ago(status.last_activity, now)}. Called frozen after a gap of ${span(status.window)}.`
            : `Last report ${ago(status.last_activity, now)}. Still learning its rhythm, so it is not yet judged for freezing.`)),
      rhythmShown && status.window && !status.connection && !judged && !status.available_rule ? el("div", { class: "bar", role: "img", "aria-label": `${Math.round(fill * 100)} percent of its window used` },
        el("div", { style: `width:${(fill * 100).toFixed(1)}%;background:${colour}` })) : null,
      rhythmShown && status.window && !status.connection && !judged && !status.available_rule ? el("div", { class: "statusline small" },
        el("span", {}, "0"), el("span", {}, `rhythm ${span(status.rhythm)}`), el("span", {}, `window ${span(status.window)}`)) : null);

    // The Identity section (rule DASH-08): who the device is first, then
    // three groups, Power, Signal and Last seen, each holding its current
    // value with when it changed, its sensor as a link that opens Home
    // Assistant's own dialog, and the details that belong with it. The
    // values are repainted the moment Home Assistant reports a change.
    // Its addresses, one row per kind, named by the kind (rule DEV-13).
    const ADDRESS_LABELS = ["MAC Address", "Zigbee Address", "Bluetooth Address", "UPnP ID", "Z-Wave Node", "Serial Number"];
    const addressRows = (Array.isArray(who.addresses) ? who.addresses : [])
      .filter((row) => row && ADDRESS_LABELS.includes(row.label) && typeof row.value === "string" && row.value)
      .map((row) => [row.label, row.value]);
    const acts = who.actions;
    this._readingCells = {};
    const byKind = (kind) => (page.readings || []).filter((r) => r.kind === kind);
    const sensorLinks = (kind) => {
      const list = byKind(kind);
      if (!list.length) return null;
      return el("div", { class: "actcol" }, ...list.map((r) => el("a", {
        class: "entitylink", href: "#", title: "Open in Home Assistant",
        onclick: (ev) => { ev.preventDefault(); this._moreInfo(r.entity_id); },
      }, r.entity_id)));
    };
    const valueCell = (kind) => {
      const cell = el("span", {}, "");
      this._readingCells[kind] = cell;
      return cell;
    };
    const heartbeat = who.clock === "last_seen";
    const lastSeenSensor = sensorLinks("last_seen")
      ? el("div", { class: "actrow" }, sensorLinks("last_seen"), heartbeat ? el("span", { class: "hbtag" }, "heartbeat") : null)
      : acts && acts.last_seen_off ? el("div", { class: "actcol" },
        el("span", {}, "switched off"),
        // No button in Simple: the Recommendations card turns it on
        // (rule DASH-04).
        simple ? null : el("div", { class: "actrow" }, el("button", { class: "chip", type: "button",
          onclick: () => this._deviceAct({ type: "device_sentinel/device_turn_on", device_id: who.device_id, kind: "last_seen" }, "heartbeat") },
          "Turn on its Last Seen")),
        this._actNote("heartbeat"))
        // ZHA keeps its own Last Seen for every device (rule STACK-04).
        : who.clock === "zha" ? el("div", { class: "actrow" }, el("span", {}, "ZHA's own"),
          el("span", { class: "hbtag" }, "heartbeat: when ZHA last heard it"))
        : el("div", { class: "actrow" }, el("span", { class: "muted" }, "none"),
          el("span", { class: "hbtag" }, "heartbeat: updates from its entities"));
    // The button beside the wait rule (rule FRZ-05): starts the Log-Normal
    // Percentile's count again by hand, as a firmware update does, for
    // a change Device Sentinel cannot see.
    // Only while the Log-Normal Percentile is in use, because with the
    // Trimmed Maximum in use it changes nothing to be seen and would hide
    // the 42-day chart for 28 days. Never in Simple, which asks
    // for nothing it does not need (rule DASH-04).
    const lognormalInUse = Boolean(page.rhythm && page.rhythm.rules && page.rhythm.rules.in_use === "lognormal");
    const useTrimmed = status.rule && lognormalInUse && !simple ? el("button", { class: "chip", type: "button", style: "margin-top:6px",
      onclick: async () => {
        try {
          await this._call({ type: "device_sentinel/use_trimmed_maximum", device_id: who.device_id });
          await this._refresh();
        } catch (err) { /* the next refresh shows the rule as it stands */ }
      } }, "Use the 14-Day Trimmed Maximum") : null;
    const group = (title) => ["__group__", title];
    // Simple (rule DASH-04): the value when set, in grey, with nothing to
    // press; "Not Set" when not, which opens the way to set it in place
    // (rules DEV-07, DEV-10).
    const plain = (text, kind) => (text ? el("span", { class: "muted" }, text)
      : acts ? this._notSet(kind, who.device_id, { source: "device_page", name: who.name })
        : el("span", { class: "muted" }, NOT_SET));
    const signalTrouble = (() => {
      const rail = (page.signal && page.signal.railed_days) || [];
      const last = [...rail].reverse().find((v) => v !== null && v !== undefined);
      return Boolean(last);
    })();
    const showSignal = !simple || signalTrouble;
    const nodeTrouble = who.node_status === "dead" || who.node_status === "off";
    const exclusion = (acts && acts.excluded) || {};
    const identity = [
      // No Rename in Simple (rule DASH-04).
      ["Name", acts && !simple ? this._nameCell(who) : who.name],
      // What it is (rule DEV-10).
      ["Type", simple ? plain(who.type && who.type.words, "type") : this._typeCell(who)],
      ["Device ID", who.device_id],
      ["Area", simple ? plain(who.area, "area") : acts ? this._areaCell(who) : (who.area || NOT_SET)],
      // Labels, each with what Device Sentinel does with it, in Advanced
      // only: Simple says when a label mutes the device (rule DASH-04).
      ...(acts && !simple ? [["Labels", this._labelsCell(who)]] : []),
      // A row with nothing to show is left out (rule DASH-08); a row with
      // an action, such as Area or Power, always stays. The server
      // sends nothing for a field that is empty or only zeros.
      ...(who.manufacturer ? [["Manufacturer", who.manufacturer]] : []),
      ...(who.model ? [["Model", who.model]] : []),
      ...(who.model_id ? [["Model ID", who.model_id]] : []),
      ...(who.hw_version ? [["Hardware version", who.hw_version]] : []),
      // What it runs, with what it ran before, in Advanced only (rule
      // DEV-15).
      ...(who.firmware && !simple ? [["Firmware", this._firmwareCell(who.firmware)]] : []),
      ...(who.integration_name || who.integration ? [["Integration", who.integration_name || who.integration]] : []),
      // How it connects, from its integration's declaration, for a
      // device that does not report on the local network as changes
      // happen (rule DEV-13).
      ...(who.connects ? [["Connects", who.connects]] : []),
      // One piece of hardware shown as several devices (rule WATCH-06).
      ...(who.same_hardware ? [["Same hardware", this._sameHardwareCell(who)]] : []),
      ...addressRows,
      group("Power"),
      ...(byKind("battery").length ? [["Battery level", valueCell("battery")]] : []),
      ...(byKind("battery").length ? [["Battery sensor", sensorLinks("battery")]]
        : acts && acts.battery_off ? [["Battery sensor", this._switchedOffCell(who, "battery", "batterysensor")]] : []),
      // What powers it (rule DEV-07): words, where they came from, pencil.
      ["Power", simple ? el("div", { class: "actcol" }, plain(who.power && who.power.source ? who.power.words : null, "power"),
        this._powerReport(who, this._edit(who.device_id))) : this._powerCell(who)],
      // Battery Last Replaced, in both modes (rule BAT-07): the day, or
      // a detected one waiting for an answer, with a pencil.
      ...(who.battery_replaced ? [[who.battery_replaced.words.row, this._batteryReplacedCell(who)]] : []),
      ...(who.battery_steps ? [["Battery steps", who.battery_steps]] : []),
      // Simple shows the signal only when it is the trouble (rule DASH-04).
      ...(showSignal ? [
        group("Signal"),
        ...(byKind("signal").length ? [["Signal", valueCell("signal")]] : []),
        ...(byKind("signal").length ? [["Signal sensor", sensorLinks("signal")]]
          : acts && acts.signal_off ? [["Signal sensor", this._switchedOffCell(who, "signal", "signalsensor")]] : []),
      ] : []),
      // Not on a hub's page (rule DASH-08): a Lutron hub's only entity
      // changes at a restart, so its Last seen would read as a fault
      // while it is up. Its status line and outages say it.
      ...(hubSelf ? [] : [
        group("Last seen"),
        ["Last seen", valueCell("last_seen")],
        // Simple: only when its sensor is switched off (rule DASH-04).
        ...(!simple || (acts && acts.last_seen_off && !byKind("last_seen").length)
          ? [["Last seen sensor", lastSeenSensor]] : []),
        // Z-Wave's own word on the device (rule STACK-05): it is what tells
        // Device Sentinel a Z-Wave device has become unavailable. Simple:
        // only when the node is dead or its sensor is off (rule DASH-04).
        ...(who.node_status && (!simple || nodeTrouble) ? [["Z-Wave status", this._nodeStatusCell(who, acts)]] : []),
        ...(who.first_observed ? [["First seen", moment(who.first_observed)]] : []),
        ["Events seen", who.event_count != null ? Number(who.event_count).toLocaleString() : "0"],
      ]),
      // The freeze rule in use today and its wait (rule FRZ-05): the
      // shorter of the Trimmed Maximum and the Log-Normal Percentile.
      ...(status.rule && rhythmShown && !status.available_rule && !judged ? [["Wait rule", el("div", { class: "actcol" }, `${status.rule}, ${span(status.window)}`, useTrimmed)]] : []),
      // What is muted and why, with the toggles (rule MUTE-09).
      ...(acts ? [["Muted", this._mutedCell(who, hub)]] : []),
      // Excluded, with its button (rule MUTE-03).
      // Simple hides Exclude this device (rule MUTE-03); an exclusion already
      // made still shows, with its way back.
      ...(acts && (!simple || exclusion.here || exclusion.integration) ? [["Excluded", this._excludedCell(who)]] : []),
    ];
    // A group left with no rows under it is not drawn either.
    const ungrouped = new Set(["Muted", "Excluded"]);
    const shownRows = identity.filter(([k], i) =>
      k !== "__group__" || (identity[i + 1] && identity[i + 1][0] !== "__group__" && !ungrouped.has(identity[i + 1][0])));
    let inGroup = false;
    const idTable = el("table", { class: "kv" }, el("tbody", {}, ...shownRows.map(([k, v]) => {
      if (k === "__group__") {
        inGroup = true;
        return el("tr", { class: "kvgroup" }, el("td", { colspan: "2" }, v));
      }
      if (ungrouped.has(k)) inGroup = false;
      return el("tr", inGroup ? { class: "kvsub" } : {}, el("td", {}, k), el("td", {}, v));
    })));

    // Its rhythm (rule FRZ-22): both rules, each with its own chart and its
    // result as a red line, the one in use tagged, and a short word on
    // why there are two.
    // In a block of its own: page.rhythm's "trimmed" and
    // "lognormal" are the History chart's series, not these figures.
    const rhythmBox = (page.rhythm && page.rhythm.rules) || {};
    const ruleChart = (title, inUse, note, gaps, aside, asideClass, rawLine, from) => {
      // Only a real number draws the line; anything else draws none,
      // so a wrong value can never blank the bars.
      const line = typeof rawLine === "number" && Number.isFinite(rawLine) ? rawLine : null;
      gaps = (gaps || []).map((g) => (typeof g === "number" && Number.isFinite(g) ? g : 0));
      if (!gaps.length) return null;
      const top = Math.max(...gaps.filter((g, i) => !aside.includes(i)), line || 0, 1) * 1.15;
      const bars = el("div", { class: "gaps rulechart", role: "img",
        "aria-label": `${title}: longest gap each day${line ? `, line at ${span(line)}` : ""}` },
        ...gaps.map((g, i) => el("div", {
          class: aside.includes(i) ? asideClass : "",
          style: `height:${Math.max(2, Math.min(100, (g / top) * 100)).toFixed(1)}%`,
          title: `${span(g)}${aside.includes(i) ? ", set aside" : ""}`,
        })),
        line ? el("div", { class: "ruleline", style: `bottom:${Math.min(100, (line / top) * 100).toFixed(1)}%` },
          el("span", {}, span(line))) : null);
      return el("div", { class: "rulebox" },
        el("div", { class: "ruletitle" }, title, inUse ? el("span", { class: "inuse" }, "in use") : null),
        el("p", { class: "small", style: "margin:0 0 6px;line-height:1.5" }, note),
        bars,
        el("div", { class: "statusline small" }, el("span", {}, from), el("span", {}, "yesterday")));
    };
    const trimmedDays = rhythmBox.trimmed_days || (page.rhythm.gaps || []).length;
    const charts = [
      ruleChart(`${trimmedDays}-Day Trimmed Maximum`, rhythmBox.in_use === "trimmed",
        "Each bar is one day's longest gap. The hatched day is set aside as a possible fluke; the red line is the longest of the rest.",
        page.rhythm.gaps || [], page.rhythm.set_aside || [], "aside", rhythmBox.trimmed, `${(page.rhythm.gaps || []).length} days ago`),
      rhythmBox.lognormal_days ? ruleChart(`${rhythmBox.lognormal_days}-Day Log-Normal Percentile`, rhythmBox.in_use === "lognormal",
        "Each bar is one day's longest gap. Grey days sit too far from the device's usual to count; the red line is the gap it stays under on nine days out of ten.",
        rhythmBox.lognormal_gaps || [], rhythmBox.lognormal_set_aside || [], "grey", rhythmBox.lognormal, `${rhythmBox.lognormal_days} days ago`) : null,
    ].filter(Boolean);
    // Where the 42-day chart stood while it counts again (rule FRZ-22).
    const again = !rhythmBox.lognormal_days && rhythmBox.counting_again;
    if (again && charts.length && !status.connection && !judged) {
      const since = new Date(`${again.since}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
      charts.push(el("div", { class: "rulebox" },
        el("div", { class: "ruletitle" }, "Log-Normal Percentile"),
        el("p", { class: "small", style: "margin:0;line-height:1.5" },
          `The 42-Day Log-Normal Percentile statistics were restarted on ${since} because of one of the following 5 reasons: `
          + "A battery change, re-pair, firmware update, three days in a row of slower reporting, or you manually restarted it. "
          + "This is done so that this device is not falsely reported frozen while the 42-Day Log-Normal Percentile is re-learned. "
          + "Until then, the 14-Day Trimmed Maximum rule is used to calculate the freeze interval.")));
    }
    // Headings in Title Case, book-title style (rule GEN-06).
    const rhythm = el("div", {}, el("h3", { class: "section" }, "Its Rhythm"),
      // A device judged by its connection reports nothing to learn a
      // rhythm from (rule STACK-07).
      ...(status.connection ? [el("p", { style: "margin:0;line-height:1.5" }, "Judged by its connection: no rhythm to learn.")]
        : judged ? [el("p", { style: "margin:0;line-height:1.5" }, this._judgedByWords(judged, "."))]
        : charts.length ? charts : [el("p", { style: "margin:0;line-height:1.5" }, "Not enough days yet to learn its rhythm.")]),
      charts.length > 1 && !again && !judged ? el("p", { class: "small", style: "margin:8px 0 0;line-height:1.6" },
        `Device Sentinel uses whichever of the two is shorter. The 14-day rule adjusts to a change within days, and the 42-day rule within weeks. A change to the device or the mesh around it, such as a firmware update, a new battery, a re-pair or a new router nearby, can leave the 42-day rule out of date.${
          // The button is not offered in Simple, so nor is the advice
          // to press it (rule DASH-04).
          lognormalInUse && !simple ? " If it does, press Use the 14-Day Trimmed Maximum." : ""}`) : null);

    const silences = page.silences.length
      ? el("div", { class: "scroll" }, el("table", {},
        el("thead", {}, el("tr", {}, ...["GAP STARTED", "GAP", "WINDOW THEN", "ENDED", "LEARNED FROM"].map((h) => el("th", {}, h)))),
        el("tbody", {}, ...page.silences.map((row) => el("tr", {},
          el("td", {}, row.since ? moment(row.since) : ""),
          el("td", {}, row.still_silent && row.silence_total
            ? span(row.silence_total)
            : row.silence ? span(row.silence) : ""),
          el("td", {}, row.window ? span(row.window) : ""),
          el("td", {}, `${row.ended || ""}${row.at ? ` at ${new Date(row.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}`),
          // Truncated by an intervention and still waiting on the
          // device's first word since, which a blank cell would leave
          // unsaid.
          el("td", {}, row.still_silent
            ? `still no report, ${ago(row.at, Date.now())} since the intervention`
            : row.learned || ""))))))
      : el("p", { class: "muted", style: "margin:0" }, "No gap longer than its rhythm in the last 14 days.");

    const mkHubLink = () => (hub ? this._link(hub.name, this._devicePath(hub.device_id)) : null);
    const hubBox = hub || hubSelf ? el("div", { class: "devstatus" },
      el("div", { class: "statusline" },
        el("div", { style: "font-size:18px;font-weight:500;display:flex;align-items:center;gap:8px" },
          el("span", { class: "dot", style: `background:${colour}` }), word),
        el("div", { class: "muted" }, hub
          ? (hub.up === null
            ? el("span", {}, "Device Sentinel cannot read ", mkHubLink(), `'s connection right now. Lutron reports this ${hub.kind} only when someone uses it, so its silence cannot be judged.`)
            : hub.up
            ? el("span", {}, mkHubLink(), ` is up, connected since ${clock(hub.since)}. Lutron reports this ${hub.kind} only when someone uses it, so its silence cannot be judged.`)
            : el("span", {}, mkHubLink(), ` went down at ${clock(hub.since)}. Until it is back, this ${hub.kind} is listed on the hub's page, not on the Problem List.`))
          : (hubSelf.up
            ? `Connected since ${clock(hubSelf.since)}. Home Assistant's Lutron integration checks the hub once a minute.`
            : `Down since ${clock(hubSelf.since)}. ${hubSelf.behind.length === 1 ? "The device it controls is" : `The ${hubSelf.behind.length} devices it controls are`} listed on this page, not on the Problem List, until it is back.`)))) : null;
    const judgedBlock = hub ? el("div", {}, el("h3", { class: "section" }, "How It Is Judged"),
      el("p", { style: "margin:0 0 10px;line-height:1.6" }, "By its hub. Lutron tells Home Assistant whether ", mkHubLink(),
        " is connected, and nothing about a single " + hub.kind + (hub.battery ? ": not when it last spoke, not when it loses power. " : ": not when it last spoke, not its battery, not when it loses power. ")
        + "When the hub goes down, this " + hub.kind + " is listed on the hub's page, not on its own."),
      ...(hub.kind === "remote" ? [el("p", { style: "margin:0 0 10px;line-height:1.6" },
        "Each press of one of its buttons counts as the remote reporting, and shows as Last seen.")] : []),
      el("p", { class: "small", style: "margin:0;line-height:1.6" },
        "A " + hub.kind + " that loses power on its own while its hub stays up cannot be seen. Lutron does not report it."))
      : hubSelf ? el("div", {}, el("h3", { class: "section" }, "How It Is Judged"),
        el("p", { style: "margin:0 0 10px;line-height:1.6" }, "By its connection. Home Assistant's Lutron integration checks the hub once a minute. "
          + "When a check fails, Device Sentinel reports the hub down within about two minutes and lists the devices it controls on this page."),
        el("p", { class: "small", style: "margin:0;line-height:1.6" },
          "Its own switch, Smart Away, changes only when Home Assistant restarts, so its silence cannot be judged.")) : null;
    const behindTable = hubSelf ? el("div", { class: "scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["DEVICE", "TYPE", "STANDING", "LAST SEEN", "PROBLEM"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...hubSelf.behind.map((d) => el("tr", {},
        el("td", {}, this._link(d.name, this._devicePath(d.device_id))),
        el("td", {}, d.type), el("td", {}, d.standing), el("td", {}, d.last_seen ? ago(d.last_seen, now) : "never"),
        el("td", {}, d.problem || "")))))) : null;
    const hubOutages = hubSelf ? el("div", { class: "scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, ...["WENT DOWN", "BACK", "DOWN FOR", "DEVICES IT CONTROLS"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...hubSelf.outages.map((o) => el("tr", {},
        el("td", {}, moment(o.start)), el("td", {}, o.end ? clock(o.end) : "still down"),
        el("td", {}, o.end ? span((new Date(o.end) - new Date(o.start)) / 1000) : ""), el("td", {}, String(hubSelf.behind.length))))))) : null;
    if (hub || hubSelf) {
      this._pane.replaceChildren(back, head, hubBox,
        el("div", { class: "twocol" }, el("div", {}, el("h3", { class: "section" }, "Identity"), idTable), judgedBlock),
        ...(hubSelf ? [el("h3", { class: "section" }, "Devices This Hub Controls ", el("span", { class: "small" }, `${hubSelf.behind.length}`)), behindTable,
          el("h3", { class: "section" }, "Outages, Last 14 Days"), hubOutages] : []));
      this._paintReadings();
      return;
    }
    if (simple) {
      // Simple's page (rule DASH-04): the rhythm and its silences only
      // for a device frozen or never reported, and the battery as one
      // chart with its expected fall (rule BAT-17).
      const b = page.battery || {};
      const batteryChart = (b.daily || []).some((v) => typeof v === "number") && b.readable !== false
        ? el("div", { class: "chart" },
          el("div", { class: "statusline" }, el("strong", {}, "Battery"),
            el("span", { class: "small" }, b.now != null ? `${levelText(b.now)} now` : "")),
          // The time left whenever there is one (rule DASH-04): the chart
          // draws and words the fall ahead only when it is soon.
          b.sentence ? el("p", { class: "small", style: "margin:0;line-height:1.5" }, `${b.sentence}${
            !b.left || b.left_soon ? "" : typeof b.target === "number" && b.target > 0
              ? ` It reaches your ${b.target}% in ${b.left}.` : ` Empty in ${b.left}.`}`) : null,
          b.lithium && !b.reading ? el("p", { class: "small", style: "margin:0;line-height:1.5" }, lithiumWords(b.lithium)) : null,
          this._batteryFutureChart(b, { future: "simple" }))
        : null;
      this._pane.replaceChildren(...[back, head, statusBox,
        rhythmShown
          ? el("div", { class: "twocol" }, el("div", {}, el("h3", { class: "section" }, "Identity"), idTable), rhythm)
          : el("div", {}, el("h3", { class: "section" }, "Identity"), idTable),
        // No gaps for a device never judged for freezing, as Advanced.
        ...(rhythmShown && !judged ? [el("h3", { class: "section" }, "Gaps, Last 14 Days"), silences] : []),
        ...(batteryChart ? [el("h3", { class: "section" }, "Battery"), batteryChart] : [])]);
      this._paintReadings();
      return;
    }
    this._pane.replaceChildren(back, head, statusBox,
      el("div", { class: "twocol" }, el("div", {}, el("h3", { class: "section" }, "Identity"), idTable), rhythm),
      // No silences for a device judged by its connection (rule STACK-07).
      ...(status.connection || judged ? [] : [el("h3", { class: "section" }, "Gaps, Last 14 Days"), silences]),
      this._graphs(page),
      el("p", { class: "muted", style: "margin:0" },
        "The Battery and Signal tabs open this page for any device, so these two graphs are where a battery or signal question ends."));
    this._paintReadings();
  }

  // The battery chart with its future (rule BAT-17): every kept
  // day as a light dot under a smoothed line, the expected fall as a
  // shaded range between two lines from today, and the low battery line
  // only where the history or the range reaches it. Simple draws the
  // future only when the near end is inside Days Till Low; the
  // Advanced "Future" view draws it up to half the days kept or Days
  // Till Low, whichever is longer, and says "empty after N days" past
  // that.
  _batteryFutureChart(battery, { future }) {
    const daily = battery.daily || [];
    const n = daily.length;
    const proj = battery.projection;
    const level = typeof battery.now === "number" ? battery.now : null;
    let ahead = 0;
    let beyond = null;
    if (proj && level !== null) {
      const far = proj.far != null ? proj.far : proj.near * 1.5;
      if (future === "simple") {
        // To the far end, or twice the near end when the far end is a
        // long way off, so the history keeps its room.
        if (battery.left_soon) ahead = Math.ceil(Math.min(far, Math.max(proj.near * 2, battery.days_setting || 0)));
      } else {
        const limit = Math.max(Math.ceil(n / 2), battery.days_setting || 0);
        if (proj.near > limit) beyond = limit;
        else {
          // On to the far end's empty day when it is near enough to
          // show, so both dates can be said under the axis (rule BAT-17).
          ahead = Math.min(Math.ceil(far), 2 * limit);
          if (far > 2 * limit) beyond = 2 * limit;
        }
      }
    }
    ahead = Math.min(ahead, 3 * 365);
    // A little room after the last day drawn, so the far end's empty
    // day is not drawn on the chart's edge.
    const total = Math.max(1, n + ahead + (ahead > 0 ? Math.max(2, Math.round(ahead / 20)) : 0));
    const left = 44;
    const right = 1090;
    const x = (i) => left + (i / Math.max(1, total - 1)) * (right - left);
    const y = (v) => 190 - (Math.max(0, Math.min(100, v)) / 100) * 170;
    const g = svg("svg", { viewBox: "0 0 1100 220", role: "img", "aria-label": "Battery level, with its expected fall" });
    for (const v of [0, 25, 50, 75, 100]) {
      g.append(svg("line", { x1: left, y1: y(v), x2: right, y2: y(v), stroke: "var(--divider-color)" }),
        svg("text", { x: 38, y: y(v) + 4, class: "axis", "text-anchor": "end" }, `${v}%`));
    }
    // Month ticks across history and future, today at slot n.
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const dayAt = (i) => new Date(today.getTime() + (i - n) * 86400000);
    for (let i = 1; i < total - 1; i += 1) {
      const d = dayAt(i);
      if (d.getDate() !== 1) continue;
      g.append(svg("line", { x1: x(i), y1: 20, x2: x(i), y2: 190, stroke: "var(--divider-color)", "stroke-opacity": 0.5 }),
        svg("text", { x: x(i), y: 210, class: "axis", "text-anchor": "middle" },
          d.toLocaleDateString([], { month: "short" })));
    }
    // The kept days, and a local fit through them (each point weighted
    // by its distance, fifteen days either side).
    const points = daily.map((v, i) => [i, v]).filter(([, v]) => typeof v === "number");
    for (const [i, v] of points) {
      g.append(svg("circle", { cx: x(i), cy: y(v), r: 2.2, fill: "var(--primary-color, #03a9f4)", "fill-opacity": 0.28 }));
    }
    const smooth = points.map(([i]) => {
      let sw = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
      for (const [j, v] of points) {
        const d = Math.abs(j - i) / 15;
        if (d >= 1) continue;
        const w = (1 - d * d * d) ** 3;
        sw += w; sx += w * j; sy += w * v; sxx += w * j * j; sxy += w * j * v;
      }
      const den = sw * sxx - sx * sx;
      const b = Math.abs(den) < 1e-9 ? 0 : (sw * sxy - sx * sy) / den;
      const a = (sy - b * sx) / sw;
      return [i, a + b * i];
    });
    // The history runs into today: today's reading is the line's last
    // point, where the expected fall begins (rule BAT-17).
    if (level !== null && n > 0) smooth.push([n, level]);
    if (smooth.length > 1) {
      g.append(svg("polyline", { fill: "none", stroke: "var(--primary-color, #03a9f4)", "stroke-width": 2.4,
        points: smooth.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") }));
    }
    g.append(svg("line", { x1: x(n), y1: 20, x2: x(n), y2: 190, stroke: "var(--secondary-text-color)", "stroke-opacity": 0.6 }),
      svg("text", { x: x(n) + 4, y: 32, class: "axis" }, "today"));
    let lowest = points.length ? Math.min(...points.map(([, v]) => v)) : 100;
    // Each zero falls on its own day, said under the axis (rule BAT-17).
    const zeroes = [];
    // Where the fall is drawn to: the low threshold, the level the time
    // left reaches (rule BAT-13), or empty for a cell already under it.
    const floor = proj && typeof proj.target === "number" && proj.target > 0 ? proj.target : 0;
    if (ahead > 0) {
      const path = (p) => (d) => level + p[0] * d + p[1] * d * d;
      // Each end drawn until it reaches its floor, and no further: the two
      // lines never run together along it (rule BAT-17).
      const run = (fn) => {
        const line = [[n, level]];
        for (let d = 1; d <= ahead; d += 1) {
          const v = fn(d);
          if (v <= floor) {
            const before = fn(d - 1);
            const at = d - 1 + (before <= floor ? 0 : (before - floor) / (before - v));
            line.push([n + at, floor]);
            return { line, zero: n + at };
          }
          line.push([n + d, v]);
        }
        return { line, zero: null };
      };
      const near = run(path(proj.near_path));
      const far = proj.far_path ? run(path(proj.far_path)) : near;
      lowest = Math.min(lowest, ...near.line.map(([, v]) => v));
      // The lighter red between the two lines, closed along empty where
      // one has ended before the other.
      // A far line that never empties in view closes the band along
      // empty below its last point.
      const floorUnderFar = near.zero !== null && far.zero === null ? [[far.line[far.line.length - 1][0], floor]] : [];
      const band = near.line.concat(floorUnderFar, far.line.slice().reverse())
        .map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
      g.append(svg("polygon", { class: "futureband", points: band, fill: "var(--error-color, #db4437)", "fill-opacity": 0.16 }));
      for (const line of far === near ? [near] : [near, far]) {
        g.append(svg("polyline", { class: "futureline", fill: "none", stroke: "var(--error-color, #db4437)", "stroke-width": 2.6,
          "stroke-linecap": "round", points: line.line.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") }));
        if (line.zero !== null) zeroes.push(line.zero);
      }
    }
    const zeroText = (i) => dayAt(Math.round(i)).toLocaleDateString([], { month: "short", day: "numeric" });
    const zeroX = zeroes.map(x);
    for (const zx of zeroX) {
      g.append(svg("line", { class: "zerotick", x1: zx, y1: 190, x2: zx, y2: 196, stroke: "var(--error-color, #db4437)", "stroke-width": 2 }));
    }
    if (zeroX.length) {
      // Two dates too close to read apart are said as one range.
      const apart = zeroX.length === 2 && Math.abs(zeroX[1] - zeroX[0]) >= 70;
      const labels = apart ? zeroes.map((i, k) => [zeroX[k], zeroText(i)])
        : [[(Math.min(...zeroX) + Math.max(...zeroX)) / 2, zeroes.length === 2 && zeroText(zeroes[0]) !== zeroText(zeroes[1])
          ? `${zeroText(zeroes[0])} to ${zeroText(zeroes[1])}` : zeroText(zeroes[0])]];
      for (const [lx, words] of labels) {
        g.append(svg("text", { class: "axis zerodate", x: Math.min(right - 30, Math.max(left + 30, lx)), y: 210,
          "text-anchor": "middle", fill: "var(--error-color, #db4437)" }, words));
      }
      // A month's name that would sit on a date gives way to it.
      for (const label of [...g.querySelectorAll("text.axis")]) {
        if (label.classList.contains("zerodate") || label.getAttribute("y") !== "210") continue;
        const mx = Number(label.getAttribute("x"));
        if (labels.some(([lx]) => Math.abs(lx - mx) < 60)) label.remove();
      }
    }
    // The low battery line, only where something reaches it.
    const threshold = battery.threshold;
    if (typeof threshold === "number" && lowest <= threshold) {
      g.append(svg("line", { x1: left, y1: y(threshold), x2: right, y2: y(threshold),
        stroke: "var(--error-color, #db4437)", "stroke-dasharray": "4 4" }),
        svg("text", { x: left + 6, y: y(threshold) - 4, class: "axis", fill: "var(--error-color, #db4437)" },
          `low battery ${threshold}%`));
    }
    // Simple says why the fall stops at the threshold (rule BAT-13); Advanced
    // says it in the sentence above its table.
    const why = future === "simple" && floor > 0 ? " Many devices stop working before their battery reaches 0%." : "";
    const words = ahead > 0 && battery.left
      ? (floor > 0 ? `Expected to reach ${floor}% in ${battery.left}.${why}` : `Expected empty in ${battery.left}.`)
      : beyond !== null ? (floor > 0 ? `Reaches ${floor}% after ${beyond} days.` : `Empty after ${beyond} days.`) : "";
    return el("div", { class: "futurechart" }, g, words ? el("p", { class: "small", style: "margin:4px 0 0" }, words) : null);
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
    // The Future view (rule BAT-17) shows every kept day in the other
    // graphs and the battery with its expected fall.
    const future = this._range === "future";
    const days = this._range === "all" || future ? recorded : Math.min(this._range, recorded);
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

    // "1 day", never "1 days".
    const dayCount = (n) => `${n} ${n === 1 ? "day" : "days"}`;
    const buttons = el("div", { class: "chips", role: "group", "aria-label": "Time range for the graphs" },
      el("span", { class: "muted", style: "align-self:center" }, "Show"),
      ...RANGES.map(([key, label]) => {
        const disabled = key !== "all" && key > recorded;
        return el("button", {
          class: "chip", type: "button",
          "aria-pressed": String(key === this._range), "aria-disabled": String(disabled),
          title: disabled ? `Only ${dayCount(recorded)} recorded so far` : "",
          onclick: () => {
            if (disabled) return;
            this._range = key;
            this._hover = null;
            this._paintDevicePage();
          },
        }, key === "all" ? `All (${dayCount(recorded)})` : label);
      }),
      // Future (rule BAT-17): only a falling battery has one to draw.
      ...(page.battery.projection ? [el("button", {
        class: "chip", type: "button", "aria-pressed": String(future),
        onclick: () => {
          this._range = "future";
          this._hover = null;
          this._paintDevicePage();
        },
      }, "Future")] : []),
      el("span", { class: "small", style: "align-self:center" },
        `${dayCount(recorded)} recorded; your history setting keeps up to ${page.history_days}.`));
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
      if (this._rhythmMarks) this._rhythmMarks(back);
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
    // The histories are laid out one slot a day (rule STOR-16): a day with no
    // measurement is empty, and a line breaks there rather than joining
    // across it. Each run of measured days is its own stretch of path.
    const runsOf = (arr, y) => {
      const runs = [];
      let run = [];
      arr.forEach((v, i) => {
        const back = arr.length - 1 - i;
        if (back >= days) return;
        if (v === null || v === undefined) {
          if (run.length) runs.push(run);
          run = [];
        } else {
          run.push(`${x(back).toFixed(1)},${y(v).toFixed(1)}`);
        }
      });
      if (run.length) runs.push(run);
      return runs;
    };
    const pathOf = (arr, y) => runsOf(arr, y)
      .map((r) => `M${r[0]}${r.length > 1 ? ` L${r.slice(1).join(" L")}` : ""}`)
      .join(" ");
    const addHover = (g) => {
      const line = svg("line", { x1: 44, y1: 16, x2: 44, y2: 194, stroke: "var(--primary-text-color)", opacity: 0 });
      lines.push(line);
      g.append(line);
      for (let b = days - 1; b >= 0; b -= 1) {
        g.append(svg("rect", { x: x(b) - step / 2, y: 16, width: step, height: 178, fill: "transparent",
          onmouseenter: () => setHover(b), onclick: () => setHover(b) }));
      }
    };
    const LOGNORMAL_COLOUR = "#2a78d6";
    const key = (colour, text, dashed, dot, ring) => el("span", {},
      ring ? el("span", { class: "swatch", style: `width:8px;height:8px;border-radius:5px;border:1px solid ${colour};background:none` })
        : dot ? el("span", { class: "swatch", style: `width:10px;height:10px;border-radius:5px;background:${colour}` })
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
      // Above three times the threshold a cell is not judged, nor with
      // under four weeks of readings in the last six (rule BAT-10).
      const above = (typeof b.ceiling === "number" && typeof b.now === "number" && b.now > b.ceiling)
        || b.short === true;
      const unit = percent ? "%" : "";
      const shown = battery.filter((v, i) => battery.length - 1 - i < days && v != null);
      const lowB = Math.max(0, Math.floor(Math.min(...shown)) - 1);
      const highB = percent ? Math.min(100, Math.ceil(Math.max(...shown)) + 1)
        : Math.ceil(Math.max(...shown)) + 1;
      // The threshold is drawn once the battery comes within ten points of it.
      // Your threshold is a percentage, so it means nothing against a
      // reading that is not one, such as a raw lux of 186.
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
      bat.g.append(svg("path", { d: pathOf(battery, bat.y), fill: "none", stroke: "var(--primary-color)", "stroke-width": 2.2 }));
      // The last five weeks' average levels, in orange over the daily
      // line, and the fitted line on a falling cell, drawn only at 30
      // and 14 days: those are the weeks the table and the falling rule
      // read, and at 90 days and longer they only crowd the history.
      // Counted back from the newest day, as the rules count them; a
      // week partly off the left edge is cut there (rule BAT-11).
      const legend = [key("var(--primary-color)", "Daily level")];
      const WEEK = "#E8A33D";
      if (days <= 30) {
        let drawn = 0;
        for (let k = 0; k < 5; k += 1) {
          const endAgo = 7 * k;
          if (endAgo >= days) break;
          const week = battery.slice(battery.length - 7 * (k + 1), battery.length - 7 * k).filter((v) => v != null);
          if (week.length !== 7) break;
          const avg = week.reduce((a, v) => a + v, 0) / 7;
          const startAgo = Math.min(endAgo + 6, days - 1);
          bat.g.append(svg("line", { x1: x(startAgo), y1: bat.y(avg), x2: x(endAgo), y2: bat.y(avg),
            stroke: WEEK, "stroke-width": 5, "stroke-linecap": "round" }),
          svg("text", { x: (x(startAgo) + x(endAgo)) / 2, y: bat.y(avg) - 9, class: "axis", "text-anchor": "middle",
            fill: "#b86e00", "font-weight": 700, "paint-order": "stroke", stroke: "var(--card-background-color, #fff)", "stroke-width": 4 },
          avg.toFixed(1)));
          drawn += 1;
        }
        if (drawn) legend.push(key(WEEK, "Weekly average (bars).", false));
        // The fitted line of a cell falling at an even pace, cut to the
        // range shown. An accelerating cell has none: its curve is drawn
        // as the time left (rule BAT-12).
        const fit = b.fit;
        if (fit && Array.isArray(fit.line) && fit.line.length >= 2) {
          const colour = "var(--secondary-text-color)";
          const edge = days - 1;
          const points = [];
          for (let i = 0; i < fit.line.length - 1; i += 1) {
            const [a0, v0] = fit.line[i];
            const [a1, v1] = fit.line[i + 1];
            if (a1 > edge) continue;
            if (a0 > edge) points.push([edge, v0 + ((v1 - v0) * (a0 - edge)) / (a0 - a1)]);
            else if (!points.length) points.push([a0, v0]);
            points.push([a1, v1]);
          }
          if (points.length >= 2) {
            bat.g.append(svg("polyline", { points: points.map(([ago, v]) => `${x(ago)},${bat.y(v)}`).join(" "),
              fill: "none", stroke: colour, "stroke-width": 2, "stroke-dasharray": "7 5" }));
            legend.push(key(colour, "Falling at an even pace.", true));
          }
        }
      }
      if (!showThreshold && percent) legend.push(el("span", {}, `Your threshold, ${b.threshold}%, is far below this range, so it is not drawn.`));
      // A reading that is not a percentage is a raw sensor value, and
      // your threshold has nothing to say about it (rule BAT-03).
      if (!percent) legend.push(el("span", {}, "This is a raw reading rather than a percentage, so it is not judged against your threshold."));
      addHover(bat.g);
      // The last five weekly averages, with what each week lost beneath
      // it, in place of a rate per day (rule BAT-18).
      let figures = null;
      const weeks = b.weeks || [];
      if (weeks.length) {
        const agoWords = ["THIS WEEK", "7 DAYS AGO", "14 DAYS AGO", "21 DAYS AGO", "28 DAYS AGO"];
        const heads = weeks.map((_, i) => agoWords[weeks.length - 1 - i]);
        const change = (i) => {
          if (i === 0) return "";
          const d = weeks[i - 1] - weeks[i];
          return Math.abs(d) < 0.05 ? "level" : d > 0 ? `down ${d.toFixed(1)}` : `up ${(-d).toFixed(1)}`;
        };
        const head = ["LEVEL", ...heads, "READING", "LEFT"];
        const cells = [
          el("td", {}, percent ? levelText(b.now) : `${b.now}`),
          ...weeks.map((w, i) => el("td", {}, `${w.toFixed(1)}${unit}`, el("div", { class: "small" }, change(i)))),
          el("td", {}, b.coarse ? "coarse" : (b.reading || (above ? "" : "steady"))),
          el("td", b.left_soon ? { style: "color:var(--error-color, #db4437)" } : {}, b.left || "\u2013"),
        ];
        figures = el("div", { class: "scroll" }, el("table", { class: "figures" },
          el("thead", {}, el("tr", {}, ...head.map((h) => el("th", {}, h)))),
          el("tbody", {}, el("tr", {}, ...cells))));
      }
      // The time left ends at the threshold (rule BAT-13), said once with why.
      const reaches = b.sentence && b.left && typeof b.target === "number" && b.target > 0
        ? ` It reaches your ${b.target}% in ${b.left}. Many devices stop working before their battery reaches 0%.` : "";
      // A coarse cell is judged by the low threshold alone (rule BAT-10).
      const meaning = el("p", { class: "small", style: "margin:0;line-height:1.5" },
        b.coarse ? "Coarse: this battery reports its level in large steps, so only your low threshold is judged and no time left is offered."
        : b.sentence ? `${b.sentence}${reaches}` : (above
          // Judged only near the threshold, and with four weeks of
          // readings (rule BAT-10): nothing is said.
          ? ""
          : weeks.length < 2
          ? "Steady: two whole weeks of history are needed before a fall can be judged."
          : "Steady: no week has fallen a point below the week before, so no time left is offered."));
      // Earlier Forecasts (rule BAT-15): what was said, and what happened.
      const forecasts = Array.isArray(b.forecasts) ? b.forecasts : [];
      const shortDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
      // A forecast to empty (rule BAT-15) closes on a reading of 0, or on the
      // day a device that then went silent was last heard: it ran out.
      const reached = (f) => f.target > 0 ? `Reached ${f.target}%` : "Ran out";
      const outcomeWords = (f) => f.outcome === "inside" ? `${reached(f)} on ${shortDay(f.arrived)}, inside the range.`
        : f.outcome === "earlier" ? `${reached(f)} on ${shortDay(f.arrived)}, earlier than the range.`
        : f.outcome === "later" ? (f.arrived ? `${reached(f)} on ${shortDay(f.arrived)}, later than the range.`
          : f.target > 0 ? `Still above ${f.target}% when the range ended.` : "Still working when the range ended.")
        : f.outcome === "replaced" ? "The battery was replaced first."
        : "Not there yet.";
      const said = (f) => f.target > 0 ? `reaches ${f.target}% in ${f.left}` : `empty in ${f.left}`;
      const earlier = forecasts.length ? el("details", { class: "forecasts" },
        el("summary", {}, `Earlier Forecasts (${forecasts.length})`),
        el("ul", { class: "small", style: "margin:4px 0 0;padding-left:18px;line-height:1.5" }, ...forecasts.map((f) =>
          el("li", {}, `${shortDay(f.day)}, at ${levelText(f.level)}: ${said(f)}. ${outcomeWords(f)}`)))) : null;
      const lithiumNote = b.lithium && !b.reading
        ? el("p", { class: "small", style: "margin:4px 0 0;line-height:1.5" }, lithiumWords(b.lithium)) : null;
      // Kept each day for a later forecast, and read by nothing yet (rule BAT-16).
      const ev = b.evidence;
      const evParts = ev ? [
        typeof ev.volts === "number" ? `${ev.volts} V` : null,
        typeof ev.messages === "number" ? `${ev.messages} ${ev.messages === 1 ? "message" : "messages"}` : null,
        typeof ev.temperature === "number" ? `${ev.temperature} \u00b0C` : null,
      ].filter((part) => part) : [];
      const evidenceNote = evParts.length
        ? el("p", { class: "small muted", style: "margin:4px 0 0;line-height:1.5" },
          `Kept each day for a better forecast later: ${evParts.join(", ")} on ${new Date(`${ev.day}T12:00:00`).toLocaleDateString([], { month: "short", day: "numeric" })}.`)
        : null;
      const modelNote = modelPaceWords(b.model_pace)
        ? el("p", { class: "small", style: "margin:4px 0 0;line-height:1.5" }, modelPaceWords(b.model_pace)) : null;
      batteryCard = card("Battery", b.now != null ? `${percent ? levelText(b.now) : b.now} now` : "", figures, meaning, lithiumNote, modelNote, evidenceNote, earlier,
        future && b.projection ? this._batteryFutureChart(b, { future: "advanced" }) : bat.g,
        future && b.projection ? null : el("div", { class: "legend" }, ...legend));
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
      // The band between median and low end, one shape per run of
      // measured days (rule STOR-16).
      const medRuns = runsOf(p50, sig.y);
      const lowRuns = runsOf(p5, sig.y);
      medRuns.forEach((m, k) => {
        const l = lowRuns[k];
        if (l && l.length === m.length && m.length > 1) {
          sig.g.append(svg("polygon", { points: m.concat(l.slice().reverse()).join(" "), fill: "var(--primary-color)", "fill-opacity": 0.16 }));
        }
      });
      sig.g.append(
        svg("path", { d: pathOf(p50, sig.y), fill: "none", stroke: "var(--primary-color)", "stroke-width": 2.2 }),
        svg("path", { d: pathOf(p5, sig.y), fill: "none", stroke: "var(--primary-color)", "stroke-width": 1.2, "stroke-dasharray": "3 3" }));
      const normal = judged.map((j) => (j ? j.normal : null));
      sig.g.append(svg("path", { d: pathOf(normal, sig.y), fill: "none", stroke: "var(--secondary-text-color)", "stroke-width": 1.4 }));
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
      let railed = 0;
      rail.forEach((n, i) => {
        const back = rail.length - 1 - i;
        if (n > 0 && back < days) {
          railed += 1;
          sig.g.append(svg("circle", { cx: x(back), cy: 30, r: 4, fill: "none", stroke: "var(--error-color, #db4437)" }));
        }
      });
      // Inside the chart, on whichever side of the first day has room,
      // so it never sits over the axis. Above the plot area, which
      // starts at 20, because drawn halfway down it lies across the data
      // lines.
      if (p50.length < days) {
        const first = x(p50.length - 1);
        const roomRight = first < (x(0) + x(days - 1)) / 2;
        sig.g.append(svg("text", { x: roomRight ? first + 8 : first - 8, y: 14, class: "axis", "text-anchor": roomRight ? "start" : "end" },
          roomRight ? `\u2039 recording began ${fmt(dayOf(p50.length - 1))}` : `recording began ${fmt(dayOf(p50.length - 1))} \u203a`));
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
      const scaleWords = { lqi: "link quality", rssi: "RSSI" };
      signalCard = card("Signal", scaleWords[page.signal.scale] || "signal", figures,
        el("p", { class: "small", style: "margin:0;line-height:1.5" }, words), sig.g,
        el("div", { class: "legend" },
          key("var(--primary-color)", "Daily median"), key("var(--primary-color)", "low end of each day", true),
          key("var(--secondary-text-color)", "its normal"), key("var(--error-color, #db4437)", "bad-day line", true),
          key("var(--error-color, #db4437)", "a bad day", false, true),
          // The rings along the top (rule SIG-07): a day with readings stuck
          // at the end of the scale.
          railed ? key("var(--error-color, #db4437)", "railed readings that day", false, false, true) : null));
    }

    // ----------------------------------------------------------------- rhythm
    let rhythmCard;
    // Set only when this page draws a rhythm chart, so the shared
    // pointer never moves a previous page's marks.
    this._rhythmMarks = null;
    if (!gaps.length) {
      rhythmCard = el("p", { class: "muted", style: "margin:0" }, "No reporting history for this device.");
    } else {
      // The axis fits what can be read, not the device's worst ever
      // day: a vibration sensor away for six weeks would get an axis of
      // 1032 hours against a rhythm of 1.6, and every ordinary day would
      // lie flat on the floor. The scale is the
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
      // Both rules' waits (rule FRZ-05): the Trimmed Maximum in red, the
      // Log-Normal Percentile in blue; the shorter is the one in use.
      const trimmedWins = page.rhythm.trimmed || wins;
      const lognormalWins = page.rhythm.lognormal || [];
      rhy.g.append(svg("path", { d: pathOf(trimmedWins.map((w) => (w ? cap(w / 3600) : null)), rhy.y), fill: "none",
        stroke: "var(--error-color, #db4437)", "stroke-width": 1.4, "stroke-dasharray": "5 4" }),
      svg("path", { d: pathOf(lognormalWins.map((w) => (w ? cap(w / 3600) : null)), rhy.y), fill: "none",
        stroke: LOGNORMAL_COLOUR, "stroke-width": 1.4, "stroke-dasharray": "2 3" }),
      svg("path", { d: pathOf(gaps.map((g) => (g == null ? null : cap(g / 3600))), rhy.y), fill: "none", stroke: "var(--primary-color)", "stroke-width": 1.4 }));
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
      // The day that set the Trimmed Maximum's wait (a ring) and the
      // day it set aside (a cross), for the day under the pointer,
      // resting on today; and a line naming that day's rule in use.
      const ring = svg("circle", { r: 8, fill: "none", stroke: "var(--primary-text-color)", "stroke-width": 2, opacity: 0 });
      const cross = svg("text", { class: "axis", "text-anchor": "middle", fill: "var(--primary-text-color)", opacity: 0 }, "\u2715");
      rhy.g.append(ring, cross);
      const ruleLine = el("p", { class: "small rule-line", style: "margin:0;line-height:1.5" }, "");
      const deciding = page.rhythm.deciding || [];
      const asideAt = page.rhythm.aside || [];
      const rules = page.rhythm.rule || [];
      const place = (node, index, dy) => {
        const back = index == null ? null : gaps.length - 1 - index;
        if (back == null || back < 0 || back >= days || gaps[index] == null) { node.setAttribute("opacity", 0); return; }
        node.setAttribute(node.tagName === "circle" ? "cx" : "x", x(back));
        node.setAttribute(node.tagName === "circle" ? "cy" : "y", rhy.y(cap(gaps[index] / 3600)) + dy);
        node.setAttribute("opacity", 1);
      };
      this._rhythmMarks = (back) => {
        const i = gaps.length - 1 - back;
        if (i < 0 || !rules[i]) { place(ring, null, 0); place(cross, null, 0); ruleLine.textContent = `${fmt(dayOf(back))}: too few days for a wait yet.`; return; }
        place(ring, deciding[i], 0);
        place(cross, (asideAt[i] || [])[0], 5);
        const other = lognormalWins[i] && trimmedWins[i]
          ? `; Trimmed Maximum ${hours(trimmedWins[i])}, Log-Normal Percentile ${hours(lognormalWins[i])}` : "";
        const by = deciding[i] != null ? `; the trimmed wait set by ${fmt(dayOf(gaps.length - 1 - deciding[i]))}` : "";
        const off = (asideAt[i] || []).length ? `, ${fmt(dayOf(gaps.length - 1 - asideAt[i][0]))} set aside` : "";
        ruleLine.textContent = `${fmt(dayOf(back))}: waiting ${hours(wins[i])} on the ${rules[i]}${other}${by}${off}.`;
      };
      this._rhythmMarks(0);
      addHover(rhy.g);
      rhythmCard = card("Rhythm", `longest gap between reports each day, in ${inMinutes ? "minutes" : "hours"}`,
        ruleLine,
        el("p", { class: "small", style: "margin:0;line-height:1.5" }, over
          ? `${over} ${over === 1 ? "day" : "days"} in this range had a gap longer than its window.`
          : "No day in this range had a gap longer than its window."),
        rhy.g,
        el("div", { class: "legend" }, key("var(--primary-color)", "Longest gap each day", false, true),
          key("var(--error-color, #db4437)", "Trimmed Maximum wait", true),
          key(LOGNORMAL_COLOUR, "Log-Normal Percentile wait", true),
          el("span", {}, el("span", { class: "swatch", style: "width:10px;height:10px;border-radius:6px;border:2px solid var(--primary-text-color)" }), "the day that set the trimmed wait"),
          el("span", {}, el("span", { class: "swatch", style: "border:none;width:auto" }, "\u2715"), "set aside"),
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
    // One type at a time (rule DEV-12), together with the chips: the counts
    // on the chips follow the type chosen.
    const types = this._countTypes(data.rows);
    let chosen = this._classType || "";
    if (chosen && !data.rows.some((row) => this._typeMatch(chosen, row.type))) chosen = this._classType = "";
    const pick = (type) => { this._classType = type; this._paintClassification(); };
    const ofType = data.rows.filter((row) => this._typeMatch(chosen, row.type));
    const counts = {
      all: ofType.length,
      watched: ofType.filter((row) => row.watched).length,
      muted: ofType.filter((row) => row.muted).length,
      set_aside: ofType.filter((row) => !row.watched).length,
    };
    const keep = {
      all: () => true,
      watched: (row) => row.watched,
      muted: (row) => row.muted,
      set_aside: (row) => !row.watched,
    }[this._filter];
    this._classSort = this._classSort || { key: null, dir: 1 };
    const again = () => this._paintClassification();
    const rows = this._sortRows(ofType.filter(keep), this._classSort, {
      name: (row) => (row.name || "").toLowerCase(),
      // By the name shown, as the Daily Brief names it (rule GEN-07).
      integration: (row) => (row.integration_name || row.integration || "").toLowerCase(),
      type: (row) => (row.type || "\uffff").toLowerCase(),
      watched: (row) => (row.watched ? 0 : 1),
      muted: (row) => (row.muted || "\uffff").toLowerCase(),
      set_aside: (row) => (row.set_aside || "\uffff").toLowerCase(),
      copies: (row) => -(row.copies || 1),
    });
    // All seven reasons, and no count of entities with no device: those
    // are never watched, so "seen only as entities" would mislead (rule GEN-03).
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `Watching ${data.watched} of ${data.rows.length} devices. ${data.set_aside} are set aside: integrations you `
      + "excluded, service devices, disabled devices, duplicate coordinators, hardware already watched through "
      + "another device, devices with nothing switched on that can report, and devices with no entities. MUTED "
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
    const head = (label, key) => this._sortHead(this._classSort, label, key, again);
    const table = el("table", {},
      el("thead", {}, el("tr", {}, head("DEVICE", "name"), head("INTEGRATION", "integration"), head("TYPE", "type"),
        head("WATCHED", "watched"), head("MUTED", "muted"), head("SET ASIDE", "set_aside"),
        showCopies ? head("COPIES", "copies") : null)),
      el("tbody", {}, ...rows.map((row) => el("tr", {},
        el("td", {}, this._link(row.name, this._devicePath(row.device_id))),
        // The integration's name; its id still opens its page (rule GEN-07).
        el("td", {}, this._link(row.integration_name || row.integration, this._integrationPath(row.integration))),
        el("td", {}, this._typeLink(row.type, row.device_id)),
        el("td", {}, row.watched ? (row.judged ? `\u2713 ${row.judged}` : "\u2713") : ""),
        el("td", {}, row.muted),
        el("td", {}, row.set_aside),
        showCopies ? el("td", {}, row.copies > 1 ? String(row.copies) : "") : null))));
    // The key to SET ASIDE, the same words as classification.md's.
    const key = el("div", { class: "muted", style: "font-size:13px;line-height:1.5" },
      el("p", { style: "margin:0 0 4px" }, "Set aside, by reason:"),
      ...(data.set_aside_meanings || []).map(([reason, meaning]) =>
        el("p", { style: "margin:0" }, el("strong", {}, reason), `: ${meaning}`)));
    this._pane.replaceChildren(...[summary,
      el("div", { class: "actrow" }, chips, this._typePicker(types, chosen, pick)),
      this._typeShowing(chosen, pick),
      el("div", { class: "scroll" }, table),
      el("p", { class: "muted", style: "margin:0;font-size:13px" }, `${rows.length} shown.`), key].filter((part) => part));
  }

  async _maintenance() {
    const stale = this._snapshot && this._snapshot.status.maintenance.open && !this._maintOpen();
    // A window that ran out while the page was open: read it again
    // first, so a press never opens what the button said it would end.
    if (stale) {
      await this._refresh();
      return;
    }
    const open = this._maintOpen();
    const message = { type: "device_sentinel/action", action: "maintenance" };
    if (!open) message.minutes = Number(this._minutes.value);
    await this._call(message);
    await this._refresh();
  }
}

// Registered once per tab (rule DASH-14). A second copy, loaded into a tab
// already running one after an update, registers nothing and tells the
// running page, which offers a reload.
if (!customElements.get(PANEL_ELEMENT)) {
  customElements.define(PANEL_ELEMENT, DeviceSentinelPanel);
} else {
  window.dispatchEvent(new CustomEvent(UPDATED_EVENT, { detail: { file: PANEL_FILE } }));
}
