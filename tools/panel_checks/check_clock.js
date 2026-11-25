// File: tools/panel_checks/check_clock.js, Version: 0.30.6 (2026-11-24)
// Panel checks: times and dates follow the viewer's Home Assistant
// profile as Home Assistant stores it, never the browser. 12 or 24 hours
// and the order of day and month as chosen, or as the language has it; a
// choice that points to the browser follows the language; the time zone
// is always Home Assistant's own; no choice saved follows Home
// Assistant's language (rule GEN-11).
// Run with: node check_clock.js [path/to/panel.js]
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

// locale: the viewer's choices as Home Assistant stores them (null for
// none saved); browser: what the browser's own hass.locale says, which
// the page must not follow; house: Home Assistant's own language.
async function open(address, locale, extra, { browser, house = "en", asked } = {}) {
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
  window.document.body.append(panel);
  panel.route = { prefix: PREFIX, path: window.location.pathname.slice(PREFIX.length) };
  panel.hass = {
    callWS: async (message) => {
      if (message.type === "frontend/get_user_data") {
        if (asked) asked.push(message.key);
        return { value: locale };
      }
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    language: (browser && browser.language) || "en",
    locale: browser || locale || {},
    config: { time_zone: "America/Guayaquil", language: house },
  };
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

// 22:34 UTC is 17:34 in Guayaquil.
const MOMENT = "2026-11-23T22:34:07Z";
const server = (more) => Object.assign({ language: "en", time_zone: "server" }, more);

(async () => {
  console.log("The clock");
  let { window } = await open(`${PREFIX}/`, server({ time_format: "24", date_format: "DMY" }));
  const run = (code) => window.eval(code);
  check("24 hours chosen: 17:34", run(`fmtTime(new Date("${MOMENT}"))`) === "17:34", run(`fmtTime(new Date("${MOMENT}"))`));
  check("24 hours, with seconds: 17:34:07", run(`fmtTime(new Date("${MOMENT}"), true)`) === "17:34:07", run(`fmtTime(new Date("${MOMENT}"), true)`));
  check("Day before month chosen: 23 Nov", run(`fmtDay(new Date("${MOMENT}"))`) === "23 Nov", run(`fmtDay(new Date("${MOMENT}"))`));
  check("With the year: 23 Nov 2026", run(`fmtDay(new Date("${MOMENT}"), { year: true })`) === "23 Nov 2026");
  check("A day and a time: 23 Nov, 17:34", run(`fmtDayTime(new Date("${MOMENT}"))`) === "23 Nov, 17:34", run(`fmtDayTime(new Date("${MOMENT}"))`));
  check("Send Brief's clock follows it", run("document.querySelector('device-sentinel-panel')._hour12()") === false);

  ({ window } = await open(`${PREFIX}/`, server({ time_format: "12", date_format: "MDY" })));
  check("12 hours chosen: 5:34 PM", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "5:34 PM", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  check("Month before day chosen: Nov 23, 2026", window.eval(`fmtDay(new Date("${MOMENT}"), { year: true })`) === "Nov 23, 2026");

  ({ window } = await open(`${PREFIX}/`, server({ time_format: "24", date_format: "YMD" })));
  check("Year first chosen: 2026 Nov 23", window.eval(`fmtDay(new Date("${MOMENT}"), { year: true })`) === "2026 Nov 23");

  ({ window } = await open(`${PREFIX}/`, server({ language: "de", time_format: "language", date_format: "language" })));
  check("As the language has it, German: 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  check("As the language has it, German: 23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`) === "23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`));
  check("The words stay English", window.eval(`fmtDay(new Date("${MOMENT}"), { month: "long" })`) === "23 November");

  ({ window } = await open(`${PREFIX}/`, server({ language: "en", time_format: "language", date_format: "language" })));
  check("As the language has it, English: 5:34 PM", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "5:34 PM");
  check("As the language has it, English: Nov 23", window.eval(`fmtDay(new Date("${MOMENT}"))`) === "Nov 23");

  ({ window } = await open(`${PREFIX}/`, { language: "en", time_zone: "server", time_format: "24" }));
  check("The server's zone: 22:34 UTC reads 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34");

  console.log("Never the browser");
  ({ window } = await open(`${PREFIX}/`, { language: "en", time_zone: "local", time_format: "24" }));
  check("Local time chosen: still Home Assistant's zone, 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  check("A day is Home Assistant's day: 2026-11-23", window.eval(`typeof houseDay === "function" && houseDay(new Date("2026-11-24T03:00:00Z"))`) === "2026-11-23", window.eval(`typeof houseDay === "function" && houseDay(new Date("2026-11-24T03:00:00Z"))`));
  ({ window } = await open(`${PREFIX}/`, { language: "de", time_zone: "server", time_format: "system", date_format: "system" }));
  check("Use system locale for the time: German's 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  check("Use system locale for the date: German's 23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`) === "23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`));
  ({ window } = await open(`${PREFIX}/`, null, undefined, { house: "de", browser: { language: "en", time_format: "12", date_format: "MDY", time_zone: "local" } }));
  check("No choice saved: Home Assistant's German, 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  check("No choice saved: Home Assistant's German, 23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`) === "23 Nov", window.eval(`fmtDay(new Date("${MOMENT}"))`));
  ({ window } = await open(`${PREFIX}/`, server({ time_format: "24" }), undefined, { browser: { language: "en", time_format: "12", time_zone: "local" } }));
  check("The browser's own choices are not followed: 17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "17:34", window.eval(`fmtTime(new Date("${MOMENT}"))`));
  ({ window } = await open(`${PREFIX}/`, null, undefined, { house: "en" }));
  check("Nothing saved, English house: 5:34 PM", window.eval(`fmtTime(new Date("${MOMENT}"))`) === "5:34 PM", window.eval(`fmtTime(new Date("${MOMENT}"))`));

  console.log("A change to the profile");
  const asked = [];
  let opened;
  opened = await open(`${PREFIX}/`, server({ time_format: "12" }), undefined, { asked, browser: { language: "en", time_format: "12" } });
  const first = asked.length;
  opened.panel.hass = Object.assign({}, opened.panel._hass, { locale: { language: "en", time_format: "12" } });
  await settle();
  check("The same profile: not read again", asked.length === first, asked);
  opened.panel.hass = Object.assign({}, opened.panel._hass, { locale: { language: "en", time_format: "24" } });
  await settle();
  check("A changed profile: read again", asked.length === first + 1, asked);

  console.log("On a page");
  const DEVICE = payloads._ids.bravo;
  const went = new Date(Date.now() - 38 * 60000).toISOString();
  const { root } = await open(`${PREFIX}/device/${DEVICE}`, server({ time_format: "24" }), { device: (page) => {
    Object.assign(page.status, { category: "unavailable", since: went, last_activity: went, rhythm: 300, window: 1560 });
    page.identity.muted = "";
    return page;
  } });
  const status = root.querySelector(".devstatus .statusline .muted").textContent;
  check("A device page on 24 hours: no AM or PM", /\b\d\d:\d\d\b/.test(status) && !/\b(AM|PM)\b/.test(status), status);

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
