// File: tools/panel_checks/check_rhythm_words.js, Version: 0.27.3 (2026-10-24)
// Panel checks: how a device's rhythm and gaps are worded (0.27.3). A
// window still being learned reads "learning" on the Devices tab; a
// device judged by its connection says it has no rhythm to learn and
// shows no gaps; the device page says "gap", not "silence"; one day
// is "1 day"; and while the Log-Normal Percentile counts again, a line
// stands where its chart was.
// Run with: LC_ALL=en_US.UTF-8 node check_rhythm_words.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
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

async function open(address, extra) {
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
  const hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  panel.hass = hass;
  await settle();
  return { window, panel, root: panel.shadowRoot, hass };
}

const DEVICE = payloads._ids ? payloads._ids.alpha : null;
const H = 3600;
const pane = (root) => root.querySelector(".pane").textContent;

(async () => {
  console.log("The Devices tab");
  let { root } = await open(`${PREFIX}/devices`, { devices: (reply) => {
    reply.rows = reply.rows.map((row, i) => (i === 0 ? { ...row, rhythm: 20.4 * H, window: null, window_learning: true } : row));
    return reply;
  } });
  const first = root.querySelector(".pane tbody tr");
  const cells = first ? [...first.cells].map((td) => td.textContent) : [];
  check("A window still learned reads learning, not blank", cells[cells.length - 1] === "learning", cells);

  console.log("A device judged by its connection");
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    page.status.connection = "connected";
    page.rhythm.daily = [3600];
    page.silences = [];
    return page;
  } }));
  let text = pane(root);
  check("It says there is no rhythm to learn", text.includes("Judged by its connection: no rhythm to learn.")
    && !text.includes("Not enough days yet to learn its rhythm."), text.match(/Its rhythm.{0,80}/));
  check("It shows no gaps section", !/Gaps, last 14 days|Silences, last 14 days/.test(text));
  check("One day recorded is 1 day", text.includes("All (1 day)") && text.includes("1 day recorded") && !text.includes("1 days"),
    text.match(/.{0,20}1 days?.{0,20}/g));

  console.log("Gaps, not silences");
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    page.status.category = "frozen";
    page.status.window = 64 * 60;
    page.status.last_activity = new Date(Date.now() - 3 * H * 1000).toISOString();
    page.silences = [];
    return page;
  } }));
  text = pane(root);
  check("Called frozen after a gap of 64m", text.includes("Called frozen after a gap of 64m."), text.match(/Called frozen.{0,40}/));
  check("Its section is Gaps, last 14 days", text.includes("Gaps, last 14 days") && !/silence/i.test(text.replace(/its silence cannot be judged/g, "")),
    text.match(/.{0,30}[Ss]ilen.{0,30}/g));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    page.status.category = "frozen";
    page.status.window = 8 * H;
    page.status.last_activity = new Date(Date.now() - 9 * H * 1000).toISOString();
    return page;
  } }));
  check("A gap of 8h reads as one", /Called frozen after a gap of 8(\.0)?h\./.test(pane(root)), pane(root).match(/Called frozen.{0,40}/));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, { device: (page) => {
    page.status.category = "frozen";
    page.status.window = 11 * 86400;
    page.status.last_activity = new Date(Date.now() - 12 * 86400 * 1000).toISOString();
    return page;
  } }));
  check("A gap of days reads as words, with no doubled article (adversarial round)",
    /Called frozen after a gap of [a-z0-9]/.test(pane(root)) && !/after a a |after an? \d+ days gap/.test(pane(root)), pane(root).match(/Called frozen.{0,50}/));

  console.log("The Log-Normal Percentile counting again");
  const withAgain = (rules) => ({ device: (page) => {
    page.rhythm.gaps = Array.from({ length: 14 }, () => 300);
    page.rhythm.set_aside = [];
    page.rhythm.rules = { trimmed: 330, trimmed_days: 14, lognormal: null, lognormal_days: null,
      lognormal_gaps: [], lognormal_set_aside: [], in_use: "trimmed", ...rules };
    return page;
  } });
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, withAgain({ counting_again: { since: "2026-10-16", to_go: 20 } })));
  text = pane(root);
  check("A line stands where the chart was, in James's words",
    text.includes("The 42-Day Log-Normal Percentile statistics were restarted on Oct 16 because of one of the following 5 reasons:")
    && text.includes("the 14-Day Trimmed Maximum rule is used to calculate the freeze interval."),
    text.match(/Log-Normal Percentile.{0,300}/));
  check("And the two-rules paragraph is not shown", !text.includes("uses whichever of the two is shorter"));
  ({ root } = await open(`${PREFIX}/device/${DEVICE}`, withAgain({})));
  check("No line when it is not counting again", !pane(root).includes("statistics were restarted"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
