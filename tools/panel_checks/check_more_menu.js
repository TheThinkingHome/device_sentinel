// File: tools/panel_checks/check_more_menu.js, Version: 0.30.5 (2026-11-23)
// Panel checks: the header's ⋮ menu holds Send Brief and Regenerate
// Reports, Send Brief is greyed out with no target, and a note beside the
// menu says what happened (rule DASH-20).
// Run with: LC_ALL=en_US.UTF-8 node check_more_menu.js [path/to/panel.js]
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

async function open(status = {}, actionAnswer = null, locale = undefined) {
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
  const calls = [];
  panel.hass = {
    callWS: async (message) => {
      calls.push(message);
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), ...status };
      if (kind === "action") {
        if (actionAnswer instanceof Error) throw actionAnswer;
        return actionAnswer || {};
      }
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    locale,
  };
  await settle();
  return { window, root: panel.shadowRoot, calls };
}

const menu = (root) => root.querySelector(".more .menu");
const item = (root, words) => [...root.querySelectorAll(".more .menu button")].find((b) => b.textContent === words);
const note = (root) => root.querySelector(".toolbar > .note").textContent;

(async () => {
  console.log("The menu");
  let { window, root, calls } = await open({ brief_targets: 2 }, { sent: 2, targets: 2 });
  const more = root.querySelector(".toolbar .more > .dots");
  check("a ⋮ button at the top right, labelled for a screen reader", more && more.querySelector("svg path") !== null
    && more.getAttribute("aria-label") === "More actions" && more.parentElement.parentElement.lastElementChild === more.parentElement);
  check("no gear beside it", root.querySelector(".toolbar .gear") === null);
  check("the button row has no ⋮", root.querySelector(".actions .more") === null);
  check("closed at first", menu(root).hidden === true);
  more.click();
  check("open on a press", menu(root).hidden === false && more.getAttribute("aria-expanded") === "true");
  check("it holds Send Brief, Regenerate Reports and Settings, in that order",
    [...root.querySelectorAll(".more .menu button")].map((b) => b.textContent).join(", ") === "Send Brief, Regenerate Reports, Settings",
    [...root.querySelectorAll(".more .menu button")].map((b) => b.textContent));
  check("Send Brief offered with a target", item(root, "Send Brief").disabled === false);
  root.querySelector(".pane").click();
  check("a press elsewhere closes it", menu(root).hidden === true);
  more.click();
  more.dispatchEvent(new root.ownerDocument.defaultView.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  check("Escape closes it", menu(root).hidden === true && more.getAttribute("aria-expanded") === "false");

  console.log("Settings");
  more.click();
  item(root, "Settings").click();
  check("Settings goes to the integration page and closes the menu",
    window.location.pathname === "/config/integrations/integration/device_sentinel" && menu(root).hidden === true, window.location.pathname);

  console.log("Send Brief");
  more.click();
  item(root, "Send Brief").click();
  await settle();
  check("it asks the server to send", calls.some((c) => c.type === "device_sentinel/action" && c.action === "send_brief"));
  check("with the clock this browser's language uses", calls.some((c) => c.action === "send_brief" && typeof c.hour12 === "boolean"));
  check("the note says where it went", note(root) === "Sent to 2 targets.", note(root));
  check("the menu closes", menu(root).hidden === true);

  ({ root, calls } = await open({ brief_targets: 2 }, { sent: 1, targets: 2 }));
  root.querySelector(".more > .dots").click();
  item(root, "Send Brief").click();
  await settle();
  check("one of two", note(root) === "Sent to 1 of 2 targets.", note(root));

  ({ root, calls } = await open({ brief_targets: 1 }, { sent: 0, targets: 1 }));
  root.querySelector(".more > .dots").click();
  item(root, "Send Brief").click();
  await settle();
  check("none took it", note(root).startsWith("Not sent: no target took it."), note(root));

  console.log("No target");
  ({ root, calls } = await open({ brief_targets: 0 }));
  root.querySelector(".more > .dots").click();
  check("Send Brief greyed out", item(root, "Send Brief").disabled === true);
  check("and says why", !root.querySelector(".more .why").hidden
    && root.querySelector(".more .why").textContent.includes("Notifications and Daily Brief"));

  console.log("An older server");
  ({ root } = await open({}));
  root.querySelector(".more > .dots").click();
  check("no count means offered", item(root, "Send Brief").disabled === false);

  console.log("The person's clock");
  for (const [locale, want, words] of [
    [{ time_format: "24", language: "en" }, false, "24-hour in the profile"],
    [{ time_format: "12", language: "de" }, true, "12-hour in the profile"],
    [{ time_format: "language", language: "de" }, false, "German's clock"],
    [{ time_format: "language", language: "en-US" }, true, "US English's clock"],
  ]) {
    ({ root, calls } = await open({ brief_targets: 1 }, { sent: 1, targets: 1 }, locale));
    root.querySelector(".more > .dots").click();
    item(root, "Send Brief").click();
    await settle();
    const call = calls.find((c) => c.action === "send_brief");
    check(words, call && call.hour12 === want, JSON.stringify(call));
  }

  console.log("Regenerate Reports");
  ({ root, calls } = await open({ brief_targets: 1 }, { regenerated: 2 }));
  root.querySelector(".more > .dots").click();
  item(root, "Regenerate Reports").click();
  await settle();
  check("it asks the server to regenerate", calls.some((c) => c.type === "device_sentinel/action" && c.action === "regenerate_reports"));
  check("the note says done", note(root) === "Reports regenerated.", note(root));

  console.log("A refusal");
  ({ root } = await open({ brief_targets: 1 }, Object.assign(new Error("Unauthorized"), { code: "unauthorized" })));
  root.querySelector(".more > .dots").click();
  item(root, "Send Brief").click();
  await settle();
  check("the note says it did not work", note(root).startsWith("That did not work"), note(root));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
