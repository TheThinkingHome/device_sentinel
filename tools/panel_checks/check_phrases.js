// File: tools/panel_checks/check_phrases.js, Version: 0.30.8 (2026-11-24)
// Panel checks: the page's words come from the phrase files (rule
// GEN-12). In English the tabs, the ⋮ menu and the dates read as they
// always have. In the test language, the English wrapped in ⟦ ⟧ with
// each value in ⟨ ⟩ and filed as Russian, every word moved shows its
// markers, a number picks its Russian plural form, and what the language
// leaves out reads English. A change of language in the profile draws
// the page again in the new one.
// Run with: LC_ALL=en_US.UTF-8 node check_phrases.js [path/to/panel.js]
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || path.join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const ENGLISH = payloads.phrases.english;
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
const settle = () => new Promise((resolve) => setTimeout(resolve, 80));

// The test language, as tools/translation/make_test_language.py makes it.
const marked = (text) => text.replace(/\{[a-z_]+\}/g, (m) => `⟨${m}⟩`);
function testLanguage(english) {
  const out = {};
  for (const [key, value] of Object.entries(english)) {
    out[key] = value && typeof value === "object"
      ? Object.fromEntries(["one", "few", "many", "other"].map((form) =>
        [form, `⟦${form}: ${marked(form === "one" ? value.one : value.other)}⟧`]))
      : `⟦${marked(value)}⟧`;
  }
  return out;
}
const RUSSIAN = testLanguage(ENGLISH);

// stored: the viewer's choices as Home Assistant stores them; files: the
// phrase files the server has, by language.
async function open(stored, files = { ru: RUSSIAN }, asked = []) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}/`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  window.document.body.append(panel);
  panel.route = { prefix: PREFIX, path: "/" };
  const state = { stored };
  panel.hass = {
    callWS: async (message) => {
      if (message.type === "frontend/get_user_data") return { value: state.stored };
      if (message.type === "device_sentinel/phrases") {
        asked.push(message.language);
        const code = files[message.language] ? message.language : "en";
        return { language: code, phrases: code === "en" ? {} : files[code], english: ENGLISH };
      }
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    language: "en",
    locale: {},
    config: { time_zone: "America/Guayaquil", language: "en" },
  };
  await settle();
  return { window, panel, root: panel.shadowRoot, state };
}

const tabs = (root) => [...root.querySelectorAll(".tabs .tab")].map((b) => b.textContent);
const menu = (root) => [...root.querySelectorAll(".more .menu button")].map((b) => b.textContent);
const run = (window, code) => window.eval(code);
const MOMENT = "2026-11-23T22:34:07Z";

(async () => {
  console.log("English, as it always read");
  let { window, root } = await open({ language: "en", time_format: "12", date_format: "MDY" });
  check("the tabs", JSON.stringify(tabs(root)) === JSON.stringify(["Daily Brief", "Battery Trends", "Signal Trends", "Integrations", "Networks", "Devices", "Recommendations (1)"]), tabs(root));
  check("the menu", JSON.stringify(menu(root)) === JSON.stringify(["Send Brief", "Regenerate Reports", "Settings"]), menu(root));
  check("the ⋮ button's name", root.querySelector(".more > .dots").getAttribute("aria-label") === "More actions");
  check("the print button's name", root.querySelector(".print").getAttribute("title") === "Print this page");
  check("a day: Nov 23", run(window, `fmtDay(new Date("${MOMENT}"))`) === "Nov 23", run(window, `fmtDay(new Date("${MOMENT}"))`));
  check("a long day: Monday's November 23, 2026", run(window, `fmtDay(new Date("${MOMENT}"), { month: "long", year: true, weekday: true })`) === "Mon November 23, 2026",
    run(window, `fmtDay(new Date("${MOMENT}"), { month: "long", year: true, weekday: true })`));
  check("a time: 5:34 PM", run(window, `fmtTime(new Date("${MOMENT}"))`) === "5:34 PM");
  check("one target", run(window, `t("dashboard.menu.sent", { count: 1 })`) === "Sent to 1 target.");
  check("two targets", run(window, `t("dashboard.menu.sent", { count: 2 })`) === "Sent to 2 targets.");
  check("two of three", run(window, `t("dashboard.menu.sent_some", { sent: 2, count: 3 })`) === "Sent to 2 of 3 targets.");
  check("a key nobody knows reads as itself", run(window, `t("dashboard.no_such_phrase")`) === "dashboard.no_such_phrase");

  console.log("The test language, filed as Russian");
  const asked = [];
  ({ window, root } = await open({ language: "ru", time_format: "12", date_format: "MDY" }, { ru: RUSSIAN }, asked));
  check("the page asks for the viewer's language", asked[0] === "ru", asked);
  check("every tab marked", tabs(root).length > 0 && tabs(root).every((name) => /^⟦[^⟦⟧]+⟧$/.test(name)), tabs(root));
  check("every menu item marked", menu(root).every((name) => /^⟦[^⟦⟧]+⟧$/.test(name)), menu(root));
  check("the ⋮ button's name marked", root.querySelector(".more > .dots").getAttribute("aria-label") === "⟦More actions⟧");
  check("a day: ⟦Nov⟧ 23", run(window, `fmtDay(new Date("${MOMENT}"))`) === "⟦Nov⟧ 23", run(window, `fmtDay(new Date("${MOMENT}"))`));
  check("a weekday marked", run(window, `fmtDay(new Date("${MOMENT}"), { weekday: true })`) === "⟦Mon⟧ ⟦Nov⟧ 23");
  check("a time: 5:34 ⟦PM⟧", run(window, `fmtTime(new Date("${MOMENT}"))`) === "5:34 ⟦PM⟧", run(window, `fmtTime(new Date("${MOMENT}"))`));
  for (const [count, form] of [[1, "one"], [3, "few"], [5, "many"], [11, "many"], [21, "one"], [22, "few"]]) {
    const said = run(window, `t("dashboard.menu.sent", { count: ${count} })`);
    check(`${count} targets: the ${form} form`, said === `⟦${form}: Sent to ⟨${count}⟩ ${form === "one" ? "target" : "targets"}.⟧`, said);
  }
  check("a value marked", run(window, `t("dashboard.menu.failed", { error: "boom" })`) === "⟦That did not work: ⟨boom⟩⟧");

  console.log("What a language leaves out reads English");
  const partial = Object.assign({}, RUSSIAN);
  delete partial["dashboard.menu.settings"];
  partial["dashboard.menu.sent"] = { one: "RU {count}" };
  ({ window, root } = await open({ language: "ru" }, { ru: partial }));
  check("a missing phrase in English", menu(root).includes("Settings"), menu(root));
  check("a missing form in English, by English's rules", run(window, `t("dashboard.menu.sent", { count: 21 })`) === "RU 21"
    && run(window, `t("dashboard.menu.sent", { count: 3 })`) === "Sent to 3 targets.", [run(window, `t("dashboard.menu.sent", { count: 21 })`), run(window, `t("dashboard.menu.sent", { count: 3 })`)]);
  ({ window, root } = await open({ language: "de" }));
  check("a language with no file reads English", menu(root)[0] === "Send Brief", menu(root));

  console.log("A change of language");
  let opened = await open({ language: "en" });
  check("starts in English", tabs(opened.root)[0] === "Daily Brief", tabs(opened.root));
  opened.state.stored = { language: "ru" };
  opened.panel.hass = Object.assign({}, opened.panel._hass, { locale: { language: "ru" } });
  await settle();
  await settle();
  check("the tabs drawn again in the new language", tabs(opened.root)[0] === "⟦Daily Brief⟧", tabs(opened.root));
  check("the menu drawn again in the new language", menu(opened.root)[0] === "⟦Send Brief⟧", menu(opened.root));

  console.log(`${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
