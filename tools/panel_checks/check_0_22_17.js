// Checks for 0.22.17: every table keeps its columns still, whatever is
// filtered or sorted, on the reference fleet's real contents. Run with
//   LC_ALL=en_US.UTF-8 node check_0_22_14.js [path/to/panel.js]
// The harness behaves like Home Assistant's router: whenever the
// address changes, by a link, a pushState or the back button, it hands
// the panel its new route, which is how the panel learns where it is.
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads_fleet.json", "utf8"));
const BRAVO = payloads._ids.bravo;
const PREFIX = "/device-sentinel";

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) {
    passed += 1;
    console.log(`  ok    ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
  }
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

async function open(address) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${address}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  const route = () => ({ prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) });
  // Home Assistant's router: a new route on every change of address.
  window.addEventListener("location-changed", () => {
    if (window.location.pathname.startsWith(PREFIX)) panel.route = route();
  });
  window.addEventListener("popstate", () => { panel.route = route(); });
  window.document.body.append(panel);
  panel.route = route();
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

const selected = (root) => {
  const tab = root.querySelector('.tab[aria-selected="true"]');
  return tab ? tab.textContent : null;
};
const clickTab = (root, name) => [...root.querySelectorAll(".tab")].find((b) => b.textContent === name).click();
const where = (window) => window.location.pathname + window.location.search;
const backLink = (root) => {
  const link = root.querySelector(".pane > p:first-child a");
  return link ? { text: link.textContent, href: link.getAttribute("href") } : null;
};

const TABS = ["daily-brief", "problem-list", "battery-trends", "signal-trends", "classification", "integrations", "devices", "recommendations"];
const headings = (table) => [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
const widths = (table) => [...table.querySelectorAll("colgroup col")].map((col) => col.style.width);
const tables = (root) => [...root.querySelectorAll(".pane table")];

function checkPinned(label, root) {
  const found = tables(root);
  for (const [i, table] of found.entries()) {
    const heads = table.querySelector("thead") ? headings(table).length : table.rows[0] ? table.rows[0].cells.length : 0;
    const w = widths(table);
    const sum = w.reduce((a, b) => a + parseFloat(b), 0);
    const ok = table.classList.contains("pinned") && w.length === heads && Math.abs(sum - 100) < 0.2;
    if (!ok) { check(`${label}: table ${i + 1} is pinned, one width per column, summing to 100%`, false, { pinned: table.classList.contains("pinned"), cols: w.length, heads, sum }); return false; }
  }
  return true;
}

const settleLong = () => new Promise((resolve) => setTimeout(resolve, 80));

(async () => {
  for (const slug of TABS) {
    let { window, root } = await open(slug === "daily-brief" ? PREFIX : `${PREFIX}/${slug}`);
    await settleLong();
    const count = tables(root).length;
    const all = checkPinned(`${slug}`, root);
    const before = tables(root).map(widths).map((w) => w.join(","));
    // Every filter chip and every sortable heading, one at a time.
    let steady = true;
    const controls = [...root.querySelectorAll(".pane .chip, .pane .sort")].length;
    for (let n = 0; n < controls; n += 1) {
      const control = [...root.querySelectorAll(".pane .chip, .pane .sort")][n];
      if (!control) break;
      const name = control.textContent;
      control.click();
      await settleLong();
      if (!checkPinned(`${slug} after ${name}`, root)) { steady = false; break; }
      const after = tables(root).map(widths).map((w) => w.join(","));
      // A filter can empty a table away; each table still shown keeps its widths.
      const heads = tables(root).map((t) => headings(t).join("|"));
      for (const [i, w] of after.entries()) {
        const j = before.findIndex((b, k) => b === w);
        if (j === -1 && before.length) { steady = false; check(`${slug}: "${name}" left table ${i + 1}'s widths alone`, false, { heads: heads[i], w }); break; }
      }
      if (!steady) break;
    }
    if (all && steady) check(`${slug}: ${count} table(s) pinned, steady through ${controls} filter and sort control(s)`, true);
  }

  console.log("Tables with the same columns line up");
  let { root } = await open(`${PREFIX}/signal-trends`);
  await settleLong();
  const groups = {};
  for (const t of tables(root)) (groups[headings(t).join("|")] ||= []).push(widths(t).join(","));
  const pairs = Object.entries(groups).filter(([, list]) => list.length > 1);
  check("Signal Trends holds two tables with the same columns", pairs.length >= 1, Object.keys(groups));
  check("and they share their widths", pairs.every(([, list]) => list.every((w) => w === list[0])), pairs);

  console.log("A device's page and an integration's page");
  ({ root } = await open(`${PREFIX}/device/${BRAVO}?from=devices`));
  await settleLong();
  checkPinned("device page", root) && check("the device page's tables are pinned", true);
  const days = root.querySelector(".pane table.days");
  check("the history table is pinned on screen with its printout's widths", days === null || JSON.stringify(widths(days).map((w) => Math.round(parseFloat(w)))) === JSON.stringify([8, 8, 11, 9, 11, 9, 44]), days && widths(days));
  const beforeRange = tables(root).map(widths).map((w) => w.join(","));
  const range = [...root.querySelectorAll(".pane .chip")].find((c) => c.textContent.startsWith("30"));
  if (range) { range.click(); await settleLong(); }
  const afterRange = tables(root).map(widths).map((w) => w.join(","));
  check("choosing another range leaves their widths alone", JSON.stringify(afterRange) === JSON.stringify(beforeRange), { beforeRange, afterRange });
  ({ root } = await open(`${PREFIX}/integration/test?from=integrations`));
  await settleLong();
  checkPinned("integration page", root) && check("the integration page's tables are pinned", true);

  console.log("On a narrow screen");
  ({ root } = await open(`${PREFIX}/classification`));
  await settleLong();
  const t = tables(root)[0];
  check("a table in a scrolling box keeps a minimum width, so it scrolls instead of crushing", t && t.parentElement.classList.contains("scroll") && parseInt(t.style.minWidth, 10) > 0, t && t.style.minWidth);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
