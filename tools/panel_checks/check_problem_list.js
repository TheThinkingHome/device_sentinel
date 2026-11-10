// File: tools/panel_checks/check_problem_list.js, Version: 0.28.10 (2026-11-10)
// Panel checks: the Problem List, a section of the Daily Brief tab
// (rule DASH-02). Today it is the list to act on, with its filters,
// sorts, ticks and mutes; a past day's is the problems that stood that
// night, to read; the old address opens the Daily Brief. The
// notification card's link opens today even on a past day, and the same
// address handed back by Home Assistant keeps the day. Its SINCE column. A device that has
// never reported has no moment it stopped: its time is when it was
// discovered, and the tab says so, as the Daily Brief does ("discovered
// 3:47 PM", rule LIST-10). Every other problem
// keeps its bare time.
// Run with: LC_ALL=en_US.UTF-8 node check_problem_list.js [path/to/panel.js]
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

async function open(path, answers = {}) {
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
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (answers[kind]) return answers[kind](message);
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

(async () => {
  console.log("The Problem List tab's SINCE column (rule LIST-10)");
  const at = (minutes) => new Date(Date.now() - minutes * 60e3).toISOString();
  const rows = [
    { uid: "u1", device_id: "n1", name: "Never Sensor", integration: "test", integration_name: "Test",
      problem: "never reported", since: at(90), acknowledged: false, mutes: [], power: null, never_reported: true },
    { uid: "u2", device_id: "f1", name: "Frozen Sensor", integration: "test", integration_name: "Test",
      problem: "frozen", since: at(30), acknowledged: false, mutes: [], power: null, never_reported: false },
  ];
  const { root } = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }) });
  const pane = root.querySelector(".pane");
  const heads = [...pane.querySelectorAll("thead th")].map((th) => th.textContent.trim());
  const sinceAt = heads.indexOf("SINCE");
  const since = (name) => {
    const tr = [...pane.querySelectorAll("tbody tr")].find((r) => r.textContent.includes(name));
    return tr ? tr.cells[sinceAt].textContent : null;
  };
  check("A never-reported device reads discovered, with the time", /^discovered \S.*\d{1,2}:\d\d/.test(since("Never Sensor") || ""), since("Never Sensor"));
  check("Any other problem keeps its bare time", !!since("Frozen Sensor") && !since("Frozen Sensor").startsWith("discovered")
    && /\d{1,2}:\d\d/.test(since("Frozen Sensor")), since("Frozen Sensor"));

  console.log("\nThe Problem List inside the Daily Brief (rule DASH-02)");
  const sections = (r) => [...r.querySelectorAll(".pane h3.section")].map((h) => h.textContent);
  check("one tab: Daily Brief, with no Problem List tab", [...root.querySelectorAll(".tab")].some((t) => t.textContent === "Daily Brief")
    && ![...root.querySelectorAll(".tab")].some((t) => t.textContent === "Problem List"));
  check("its sections read Problem List, Repeat Offenders, What Happened",
    JSON.stringify(sections(root)) === JSON.stringify(["Problem List", "Repeat Offenders", "What Happened"]), sections(root));
  check("today's list has its filters, its ticks and a mute beside each problem",
    [...pane.querySelectorAll(".chip")].some((c) => c.textContent.startsWith("Open "))
    && pane.querySelectorAll('tbody input[type="checkbox"]').length >= 2, pane.textContent.slice(0, 200));
  const muteRows = [{ ...rows[1], mutes: ["freeze"] }];
  const muted = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(muteRows)) }) });
  check("Mute freeze sits beside a frozen device", [...muted.root.querySelectorAll(".pane button.chip")].some((b) => b.textContent === "Mute freeze"));
  const past = await open(PREFIX, {
    problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }),
    brief: () => ({ ...JSON.parse(JSON.stringify(payloads.brief)), is_today: false, day: "2026-09-20", back: null, forward: "2026-09-21",
      now: [{ uid: "u2", device_id: "f1", name: "Old Frozen", problem: "frozen", since: at(3000), seconds: 3600, acknowledged: false }] }),
  });
  const pastPane = past.root.querySelector(".pane");
  check("a past day lists the problems that stood that night", pastPane.textContent.includes("Old Frozen") && !pastPane.textContent.includes("Frozen Sensor"));
  check("to read: no ticks, no mutes, no filters", !pastPane.querySelector('input[type="checkbox"]')
    && ![...pastPane.querySelectorAll("button.chip")].some((b) => /^Mute |^Open |^All /.test(b.textContent)));
  const old = await open(`${PREFIX}/problem-list`);
  check("the Problem List's old address opens the Daily Brief at its own", old.window.location.pathname === PREFIX
    && old.root.querySelector('.tab[aria-selected="true"]').textContent === "Daily Brief", old.window.location.pathname);

  console.log("\nBack to today from another tab (rule DASH-02)");
  {
    const asked = [];
    const back = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }),
      brief: (m) => { asked.push(m.day || "today"); const b = JSON.parse(JSON.stringify(payloads.brief));
        return m.day ? { ...b, is_today: false, day: m.day, back: null, forward: null, now: [] } : { ...b, is_today: true }; } });
    await back.panel._briefGo("2026-09-20");
    await settle();
    const tabNamed = (name) => [...back.root.querySelectorAll(".tab")].find((t) => t.textContent.startsWith(name));
    tabNamed("Devices").click();
    await settle();
    tabNamed("Daily Brief").click();
    await settle(); await settle();
    check("coming back opens today, with the list to act on",
      back.root.querySelectorAll('.pane tbody input[type="checkbox"]').length >= 2 && asked[asked.length - 1] === "today", asked);
  }

  console.log("\nA past day kept through a device page, and today's list kept when the brief fails");
  {
    const asked = [];
    const kept = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }),
      brief: (m) => { asked.push(m.day || "today"); const b = JSON.parse(JSON.stringify(payloads.brief));
        return m.day ? { ...b, is_today: false, day: m.day, back: null, forward: null,
          now: [{ uid: "u9", device_id: payloads.devices.rows[0].device_id, name: "Old Frozen", problem: "frozen", since: at(3000), seconds: 3600, acknowledged: false }] } : { ...b, is_today: true }; } });
    await kept.panel._briefGo("2026-09-20");
    await settle();
    [...kept.root.querySelectorAll(".pane a")].find((a) => a.textContent === "Old Frozen")
      .dispatchEvent(new kept.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await settle(); await settle();
    const backLink = kept.root.querySelector(".pane > p:first-child a");
    backLink.dispatchEvent(new kept.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    await settle(); await settle();
    const stayed = kept.root.querySelector(".pane").textContent.includes("Old Frozen");
    check("back from a device opened on a past day returns to that day", kept.root.querySelector(".pane").textContent.includes("Old Frozen")
      && asked[asked.length - 1] === "2026-09-20", asked);
    // The Daily Brief tab pressed while a past day shows.
    [...kept.root.querySelectorAll(".tab")].find((t) => t.textContent === "Daily Brief").click();
    await settle(); await settle();
    check("the Daily Brief tab pressed on a past day opens today", stayed && asked[asked.length - 1] === "today"
      && kept.root.querySelectorAll('.pane tbody input[type="checkbox"]').length >= 2, asked);
    let failingCalls = 0;
    const failing = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }),
      brief: () => { failingCalls += 1; if (failingCalls > 1) throw new Error("down"); return JSON.parse(JSON.stringify(payloads.brief)); } });
    await failing.panel._briefGo(null);
    await settle();
    const text = failing.root.querySelector(".pane").textContent;
    check("today's brief failing still shows the Problem List, with words that fit", text.includes("Today's brief could not be read")
      && failing.root.querySelectorAll('.pane tbody input[type="checkbox"]').length >= 2, text.slice(0, 160));
  }

  console.log("\nThe notification card's link (rules NOTE-11, DASH-02)");
  {
    const asked = [];
    const brief = (m) => { asked.push(m.day || "today"); const b = JSON.parse(JSON.stringify(payloads.brief));
      return m.day ? { ...b, is_today: false, day: m.day, back: null, forward: null, now: [] } : { ...b, is_today: true }; };
    const card = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }), brief });
    await card.panel._briefGo("2026-09-20");
    await settle();
    // Home Assistant hands the page the address it already has.
    card.panel.route = { prefix: PREFIX, path: "" };
    await settle();
    check("the same address handed back keeps the past day", asked[asked.length - 1] === "2026-09-20", asked);
    // The card's link, followed while the past day shows.
    card.window.history.pushState(null, "", `${PREFIX}?open=today`);
    card.window.dispatchEvent(new card.window.CustomEvent("location-changed"));
    await settle(); await settle();
    check("the card's link opens today, with the list to act on", asked[asked.length - 1] === "today"
      && card.root.querySelectorAll('.pane tbody input[type="checkbox"]').length >= 2, asked);
    check("and the marker leaves the address", card.window.location.search === "" && card.window.location.pathname === PREFIX,
      card.window.location.href);
    const fresh = await open(`${PREFIX}?open=today`, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }) });
    check("opened fresh from the card, the dashboard shows today's Daily Brief", fresh.panel._tab === "Daily Brief"
      && !fresh.panel._briefDay && fresh.window.location.search === "", fresh.window.location.href);
  }

  console.log("\nA late reply is not drawn over another tab");
  {
    let release;
    const slow = await open(PREFIX, { problem_list: () => ({ rows: JSON.parse(JSON.stringify(rows)) }),
      brief: (m) => (m.day ? new Promise((resolve) => { release = () => resolve({ ...JSON.parse(JSON.stringify(payloads.brief)), is_today: false, day: m.day }); })
        : JSON.parse(JSON.stringify(payloads.brief))) });
    const going = slow.panel._briefGo("2026-09-20");
    [...slow.root.querySelectorAll(".tab")].find((t) => t.textContent.startsWith("Devices")).click();
    await settle();
    release();
    await going;
    await settle();
    check("Devices stays drawn", !slow.root.querySelector(".pane h3.section") || ![...slow.root.querySelectorAll(".pane h3.section")].some((h) => h.textContent === "What Happened"),
      [...slow.root.querySelectorAll(".pane h3.section")].map((h) => h.textContent));
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
