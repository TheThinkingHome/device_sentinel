// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: frontend/panel.js, Version: 0.22.2 (2026-09-19)
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
  "Battery",
  "Signal",
  "Classification",
  "Integrations",
  "Devices",
  "Recommendations",
];
const BUILT = new Set(["Problem List", "Classification", "Recommendations"]);
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

function span(seconds) {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
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
  th { text-align: left; font-size: 12px; font-weight: 500; letter-spacing: 0.04em; color: var(--secondary-text-color);
    padding: 8px 10px; border-bottom: 1px solid var(--divider-color); }
  td { padding: 9px 10px; border-bottom: 1px solid var(--divider-color); }
  a { color: var(--primary-color); text-decoration: none; }
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
`;

class DeviceSentinelPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "Classification";
    this._filter = "all";
    this._problemFilter = "all";
    this._problemSort = null;
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
    if (!this._started) {
      this._started = true;
      this._build();
      this._refresh();
      this._subscribe();
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
  }

  connectedCallback() {
    if (this._started && !this._unsubscribe) this._subscribe();
  }

  disconnectedCallback() {
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
    root.append(el("div", { class: "toolbar" }, this._menu, "Device Sentinel"));

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
    root.append(
      el("div", { class: "body" }, this._statusRow, actions,
        el("div", { class: "card" }, this._tabRow, this._pane)),
    );
    this._paintTabs();
  }

  async _refresh() {
    this._refreshButton.disabled = true;
    try {
      const [status, classification, problems, recommendations] = await Promise.all([
        this._call({ type: "device_sentinel/status" }),
        this._call({ type: "device_sentinel/classification" }),
        this._call({ type: "device_sentinel/problem_list" }),
        this._call({ type: "device_sentinel/recommendations" }),
      ]);
      this._snapshot = { status, classification, problems, recommendations, at: new Date() };
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
    this._asOf.textContent = `As of ${at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
  }

  _paintTabs() {
    this._tabRow.replaceChildren(...TABS.map((name) =>
      el("button", {
        class: "tab", type: "button", role: "tab", "aria-selected": String(name === this._tab),
        onclick: () => {
          this._tab = name;
          this._paintTabs();
          this._paintPane();
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
    if (this._tab === "Problem List") this._paintProblems();
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
        el("td", {}, this._link(row.name, `/config/devices/device/${encodeURIComponent(row.device_id)}`)),
        el("td", {}, row.integration
          ? this._link(row.integration, `/config/integrations/integration/${encodeURIComponent(row.integration)}`)
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
    const summary = el("p", { style: "margin:0;line-height:1.5" },
      `Watching ${data.watched} of ${data.rows.length} devices. ${data.set_aside} are set aside: service devices, `
      + `disabled devices, devices with no entities, and integrations you excluded. ${data.deviceless} entities `
      + "belong to no device and are seen only as entities.");
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
        el("td", {}, this._link(row.name, `/config/devices/device/${encodeURIComponent(row.device_id)}`)),
        el("td", {}, this._link(row.integration, `/config/integrations/integration/${encodeURIComponent(row.integration)}`)),
        el("td", {}, row.watched ? "\u2713" : ""),
        el("td", {}, row.muted),
        el("td", {}, row.set_aside),
        showCopies ? el("td", {}, row.copies > 1 ? String(row.copies) : "") : null))));
    this._pane.replaceChildren(summary, chips, el("div", { class: "scroll" }, table),
      el("p", { class: "muted", style: "margin:0;font-size:13px" }, `${rows.length} shown.`));
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
