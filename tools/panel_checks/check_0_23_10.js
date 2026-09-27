// Checks for 0.23.10: the controls in a band of their own above the
// tabs, and tabs that read as tabs (from Tim Plas). Run with
//   node check_0_23_10.js [path/to/panel.js]
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
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      const reply = JSON.parse(JSON.stringify(payloads[kind]));
      return extra && extra[kind] ? extra[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot };
}


// The rule for a selector in the panel's own stylesheet, as written.
const rule = (root, selector) => {
  const text = [...root.querySelectorAll("style")].map((s) => s.textContent).join("\n");
  const at = text.indexOf(`\n  ${selector} {`);
  if (at < 0) return "";
  return text.slice(at, text.indexOf("}", at) + 1).replace(/\s+/g, " ");
};

(async () => {
  console.log("The page opened on the Problem List's own address");
  const page = await open(`${PREFIX}/problem-list`);
  const root = page.root;
  const active = root.querySelector('.tab[aria-selected="true"]');
  check("the Problem List tab is the one selected", active && active.textContent === "Problem List", active && active.textContent);

  console.log("The controls sit in a band of their own");
  const head = root.querySelector(".body > .head");
  check("a header band exists", Boolean(head));
  check("it holds the status tiles", Boolean(head && head.querySelector(".status")));
  check("and the action buttons", Boolean(head && head.querySelector(".actions")));
  check("but not the tabs", Boolean(head) && !head.querySelector(".tabs"));
  const card = root.querySelector(".body > .card");
  check("the tabs and their content follow it, in their own card",
    Boolean(head && card) && head.nextElementSibling === card && Boolean(card.querySelector(".tabs")));
  check("the band has a background and a border",
    /background: var\(--secondary-background-color/.test(rule(root, ".head")) && /border: 1px solid/.test(rule(root, ".head")), rule(root, ".head"));

  console.log("The tabs read as tabs");
  check("the strip is tinted", /background: var\(--secondary-background-color/.test(rule(root, ".tabs")), rule(root, ".tabs"));
  check("labels in the main text colour, not grey", /color: var\(--primary-text-color\)/.test(rule(root, ".tab")), rule(root, ".tab"));
  check("a 3px underline", /border-bottom: 3px solid transparent/.test(rule(root, ".tab")), rule(root, ".tab"));
  const on = rule(root, '.tab[aria-selected="true"]');
  check("the active tab is bold", /font-weight: 600/.test(on), on);
  check("in the theme colour, with its underline", /color: var\(--primary-color\)/.test(on) && /border-bottom-color: var\(--primary-color\)/.test(on), on);
  check("and joined to the content below it", /background: var\(--card-background-color/.test(on), on);
  check("a hover shade", /background: rgba/.test(rule(root, ".tab:hover")), rule(root, ".tab:hover"));

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
