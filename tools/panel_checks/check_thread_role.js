// Copyright (C) 2026 James Lander, The Thinking Home
// Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
// Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
//   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
//   Repository: https://github.com/TheThinkingHome/device_sentinel
// File: tools/panel_checks/check_thread_role.js, Version: 0.30.7 (2026-11-26)
//
// The Thread role from the Matter server's map (rule STACK-18): a Matter
// device's page shows its role, what it carries, its best link and a link
// to Home Assistant's own Matter map, in Advanced; the Networks tab shows
// the Thread network's counts, and in Advanced its routers. A map that is
// missing or damaged leaves the rest of each page drawn.
// Run with: LC_ALL=en_US.UTF-8 node check_thread_role.js [path/to/panel.js]
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
const DEVICE = payloads.devices.rows[1].device_id;
const THREAD = { role: "router", role_words: "Router", carries: 3, link: { strength: "strong", to: "SMHUB Nano" },
  network: "home-thread", map_path: "/config/matter/visualization" };
const VIEW = { networks: ["home-thread"], border_routers: 2, routers: 1, end_devices: 1, sleepy: 4, read_at: 1,
  map_path: "/config/matter/visualization",
  rows: [{ name: "SMHUB Nano", device_id: null, role: "Border router", carries: 2, link: null },
    { name: "Kitchen Plug", device_id: DEVICE, role: "Router", carries: 3, link: "strong" }] };

async function open(path, mode, { thread, view } = {}) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => {
    if (!String(err.message).includes("Not implemented")) console.log("jsdom:", err.message);
  });
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${path}`, virtualConsole,
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
  const hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (kind === "status") return { ...JSON.parse(JSON.stringify(payloads.status)), dashboard: mode };
      if (kind === "networks") {
        const tab = JSON.parse(JSON.stringify(payloads.networks || { rows: [], air: {} }));
        if (!tab.rows || !tab.rows.length) tab.rows = [{ key: "matter", name: "Matter", kind: "matter",
          status: { state: "ok", words: "Running", since: null }, watched: 6, with_problem: 0,
          counts: {}, last_outage: null, outages: 0 }];
        tab.thread = view;
        return tab;
      }
      if (kind === "device") {
        const page = JSON.parse(JSON.stringify(payloads.device));
        page.identity.device_id = message.device_id;
        page.identity.thread = thread;
        return page;
      }
      if (kind.startsWith("device_")) return {};
      if (!(kind in payloads)) throw new Error(`no payload for ${kind}`);
      return JSON.parse(JSON.stringify(payloads[kind]));
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
    themes: { darkMode: false },
  };
  panel.hass = hass;
  await settle(); await settle(); await settle();
  return { window, root: panel.shadowRoot };
}

const text = (root) => (root.querySelector(".pane") || root).textContent;
const noStrays = (root) => !/\b(null|undefined|NaN)\b|\[object/.test(text(root));
const link = (root) => [...root.querySelectorAll(".pane a")].find((a) => a.textContent === "Open Home Assistant's Matter map");

(async () => {
  console.log("A Matter device's page, Advanced");
  let { root, window } = await open(`/device/${DEVICE}`, "advanced", { thread: THREAD });
  check("its role and what it carries", text(root).includes("Router, 3 devices route through it"), text(root).slice(0, 300));
  check("its best link", text(root).includes("Strong to SMHUB Nano"));
  check("the map can lag", text(root).includes("Read from the Matter server's network map, which can lag a few minutes."));
  const a = link(root);
  check("a link to Home Assistant's map", a && a.getAttribute("href") === "/config/matter/visualization");
  check("nothing stray", noStrays(root));

  ({ root } = await open(`/device/${DEVICE}`, "advanced", { thread: { ...THREAD, role_words: "Sleepy end device", carries: null, link: null } }));
  check("an end device carries nothing and shows no link row", text(root).includes("Sleepy end device")
    && !text(root).includes("route through it") && !text(root).includes("Thread Link"));
  ({ root } = await open(`/device/${DEVICE}`, "advanced", { thread: { ...THREAD, carries: 1, link: { strength: "none", to: "x" }, map_path: "javascript:alert(1)" } }));
  check("one device, an unknown strength and a strange path", text(root).includes("1 device routes through it")
    && !text(root).includes("Thread Link") && !link(root));

  console.log("Simple, and a device with no map");
  ({ root } = await open(`/device/${DEVICE}`, "simple", { thread: THREAD }));
  check("Simple leaves the rows out", !text(root).includes("Thread Role") && text(root).length > 50);
  ({ root } = await open(`/device/${DEVICE}`, "advanced", { thread: null }));
  check("no map, no rows, the page still drawn", !text(root).includes("Thread Role") && text(root).includes("Powered by"));

  console.log("The Networks tab");
  ({ root } = await open("/networks", "advanced", { view: VIEW }));
  check("the counts", text(root).includes("Your Thread network (home-thread): 2 border routers, 1 router, 1 end device, 4 sleepy end devices."), text(root));
  const thread = root.querySelector('[data-thread="card"]');
  const rows = thread ? [...thread.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((td) => td.textContent)) : [];
  check("each router with what it carries", JSON.stringify(rows) === JSON.stringify([
    ["SMHUB Nano", "Border router", "2 devices", "Not shown"], ["Kitchen Plug", "Router", "3 devices", "Strong"]]), rows);
  check("a router with a page is a link to it", thread && [...thread.querySelectorAll("tbody a")].some((x) => x.textContent === "Kitchen Plug"));
  check("a link to Home Assistant's map", !!link(root));
  check("the network table is still there", root.querySelector('table[data-shares="networks"]') !== null);
  check("nothing stray", noStrays(root));

  ({ root } = await open("/networks", "simple", { view: VIEW }));
  check("Simple shows the counts without the table", text(root).includes("2 border routers")
    && !(root.querySelector('[data-thread="card"] table')));
  ({ root } = await open("/networks", "advanced", { view: null }));
  check("no map, no card", !root.querySelector('[data-thread="card"]') && root.querySelector('table[data-shares="networks"]') !== null);
  ({ root } = await open("/networks", "advanced", { view: { rows: "x" } }));
  check("a damaged map draws no card and keeps the tab", !root.querySelector('[data-thread="card"]')
    && root.querySelector('table[data-shares="networks"]') !== null);
  ({ root } = await open("/networks", "advanced", { view: { rows: [{}], networks: null } }));
  check("an empty router row still reads", noStrays(root) && text(root).includes("0 border routers"), text(root));

  console.log(`\n${passed} passed, ${failed} failed`);
  window.close();
  process.exit(failed ? 1 : 0);
})();
