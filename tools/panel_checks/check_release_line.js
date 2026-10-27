// File: tools/panel_checks/check_release_line.js, Version: 0.27.10 (2026-10-27)
// Panel checks: the release line at the foot of the dashboard (rule
// DASH-15). It reads "Device Sentinel"
// and the version running, in Simple and Advanced alike, on every tab
// and page, and links to that release's notes in a new tab. A link the
// server did not give, or one to anywhere but the notes, is not drawn.
// Run with: LC_ALL=en_US.UTF-8 node check_release_line.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const NOTES = "https://github.com/TheThinkingHome/device_sentinel/releases/tag/0.27.0";
const RELEASE = { words: "Device Sentinel 0.27.0", url: NOTES };

let passed = 0;
let failed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok    ${label}`); return; }
  failed += 1;
  console.log(`  FAIL  ${label}${detail !== undefined ? `\n        got: ${JSON.stringify(detail)}` : ""}`);
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 60));

async function open({ path = PREFIX, mode = "advanced", release = RELEASE } = {}) {
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
      if (kind === "status") {
        const status = { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
        if (release !== "none") status.release = release;
        return status;
      }
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = message.device_id;
        return page;
      }
      if (kind === "device_choices") return { areas: [], labels: [] };
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  await settle();
  await settle();
  await settle();
  return { window, root: panel.shadowRoot };
}

const line = (root) => root.querySelector("p.release");

(async () => {
  console.log("The release line (ruling #723)");
  let { root } = await open();
  let foot = line(root);
  check("It reads Device Sentinel and the version", !!foot && foot.textContent === "Device Sentinel 0.27.0", foot && foot.textContent);
  const link = foot && foot.querySelector("a");
  check("It links to that release's notes", !!link && link.getAttribute("href") === NOTES, link && link.getAttribute("href"));
  check("In a new tab, telling the page nothing", !!link && link.getAttribute("target") === "_blank"
    && /noopener/.test(link.getAttribute("rel")) && /noreferrer/.test(link.getAttribute("rel")), link && link.outerHTML);
  check("It sits below the tabs' card, at the foot", !!foot && foot.previousElementSibling
    && foot.previousElementSibling.classList.contains("card") && foot.nextElementSibling === null);

  ({ root } = await open({ mode: "simple" }));
  foot = line(root);
  check("Simple shows the same line", !!foot && foot.textContent === "Device Sentinel 0.27.0" && !!foot.querySelector("a"),
    foot && foot.outerHTML);

  for (const path of ["/recommendations", "/battery-trends", `/device/${payloads.devices.rows[0].device_id}`]) {
    ({ root } = await open({ path: PREFIX + path }));
    foot = line(root);
    check(`It shows on ${path}`, !!foot && foot.textContent === "Device Sentinel 0.27.0", foot && foot.textContent);
  }

  console.log("\nWhat it will not draw");
  ({ root } = await open({ release: { words: "Device Sentinel 0.27.0", url: "https://evil.example/releases/tag/0.27.0" } }));
  foot = line(root);
  check("A link anywhere but the notes is left off; the words stay", !!foot && !foot.querySelector("a")
    && foot.textContent === "Device Sentinel 0.27.0", foot && foot.outerHTML);
  ({ root } = await open({ release: { words: "Device Sentinel <b>x</b>", url: null } }));
  foot = line(root);
  check("Words are only text", !!foot && !foot.querySelector("b") && foot.textContent === "Device Sentinel <b>x</b>", foot && foot.innerHTML);
  ({ root } = await open({ release: "none" }));
  foot = line(root);
  check("A server that sends no release leaves the line empty", !!foot && foot.textContent === "" && !foot.querySelector("a"),
    foot && foot.outerHTML);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
