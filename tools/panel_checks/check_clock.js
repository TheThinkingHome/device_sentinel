// File: tools/panel_checks/check_clock.js, Version: 0.30.4 (2026-11-23)
// Panel checks: times and dates follow the viewer's Home Assistant
// profile. 12 or 24 hours as chosen, or as the language has it; the
// order of day and month as chosen, or as the language has it; the
// server's time zone when the profile asks for it (rule GEN-11).
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

async function open(address, locale, extra) {
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
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    language: "en",
    locale,
    config: { time_zone: "America/Guayaquil" },
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
