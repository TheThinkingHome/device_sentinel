// File: tools/panel_checks/check_acknowledged_rows.js, Version: 0.27.14 (2026-10-29)
// Panel checks: an acknowledged row (rule REC-07). On the Problem List,
// the Daily Brief tab and the Recommendations cards the row fades to
// 75%, all but its tick and the word beside it, so the tick still reads
// as something to press; a ticked box says it can be taken back. Also
// the Maintenance Mode button's words (rule DASH-02).
// Run with: LC_ALL=en_US.UTF-8 node check_acknowledged_rows.js [path/to/panel.js]
const fs = require("fs");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || require("path").join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const HOVER = "Acknowledged. Press to take it back.";

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
    runScripts: "outside-only", url: `http://ha.local${PREFIX}${path}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  window.eval(fs.readFileSync(PANEL, "utf8"));
  const panel = window.document.createElement("device-sentinel-panel");
  window.document.body.append(panel);
  panel.route = { prefix: PREFIX, path };
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      const reply = JSON.parse(JSON.stringify(payloads[kind] || {}));
      return answers[kind] ? answers[kind](reply) : reply;
    },
    connection: { subscribeMessage: async () => () => {} },
    states: {},
  };
  await settle();
  return { window, panel, root: panel.shadowRoot };
}

const PROBLEM = (uid, name, acknowledged) => ({ uid, device_id: uid, name, integration: "test", integration_name: "Test",
  problem: "frozen", since: new Date(Date.now() - 3600e3).toISOString(), acknowledged, mutes: ["freeze"] });

(async () => {
  console.log("\nThe look");
  const { root } = await open("/problem-list");
  const css = [...root.querySelectorAll("style")].map((s) => s.textContent).join("\n");
  check("an acknowledged row's cells fade to 75%, all but the tick's",
    /tr\.acked td:not\(\.ackcell\):not\(\.ackhold\) \{ opacity: 0\.75; \}/.test(css), css.match(/[^\n]*acked[^\n]*/g));
  check("a card fades to 75%, all but the part that holds its tick",
    /\.rec\.acked > :not\(:has\(\.ack\)\) \{ opacity: 0\.75; \}/.test(css), css.match(/[^\n]*acked[^\n]*/g));
  check("nothing fades a whole row, tick and all", !/(^|[\s,])tr\.acked \{/.test(css) && !/\.rec\.acked, tr\.acked/.test(css)
    && !/tr\.acked td \{/.test(css), css.match(/[^\n]*acked[^\n]*/g));

  console.log("\nThe Problem List");
  const list = await open("/problem-list", { problem_list: () => ({ rows: [PROBLEM("u1", "Frozen Door", true), PROBLEM("u2", "Frozen Window", false)] }) });
  const rows = [...list.root.querySelectorAll(".pane tbody tr")];
  check("the acknowledged row is marked acked, the other not",
    rows[0].classList.contains("acked") && !rows[1].classList.contains("acked"), rows.map((r) => r.className));
  check("its tick sits in the cell that does not fade", rows[0].children[0].classList.contains("ackcell"));
  check("a ticked box says it can be taken back; an open one says nothing",
    rows[0].querySelector("label.ackbox").getAttribute("title") === HOVER && !rows[1].querySelector("label.ackbox").hasAttribute("title"));

  console.log("\nThe Daily Brief tab");
  const brief = await open("", { brief: (reply) => ({ ...reply, is_today: true,
    now: [{ uid: "u1", device_id: "u1", name: "Frozen Door", problem: "frozen", since: new Date().toISOString(), seconds: 3600, acknowledged: true }] }) });
  const now = brief.root.querySelector(".pane tbody tr.acked");
  check("an acknowledged row keeps its tick in the cell that does not fade, with the hover",
    Boolean(now) && now.children[0].classList.contains("ackcell") && now.querySelector("label.ackbox").getAttribute("title") === HOVER);

  console.log("\nThe Recommendations cards");
  const card = { kind: "slow", title: "Slow Reporting Devices", body: "These devices go quiet.",
    devices: [{ device_id: "s1", name: "Guest Lamp", area: "Hall", acknowledged: true }, { device_id: "s2", name: "Porch", area: "Hall", acknowledged: false }] };
  const recs = await open("/recommendations", { recommendations: (reply) => ({ ...reply, devices: [card] }) });
  const recRows = [...recs.root.querySelectorAll('article[data-kind="slow"] tbody tr')];
  const tickCell = recRows[0] && recRows[0].lastChild;
  check("a ticked device row keeps its tick and the word Acknowledged in the cell that does not fade",
    recRows[0].classList.contains("acked") && tickCell.classList.contains("ackhold") && /Acknowledged/.test(tickCell.textContent));
  check("its tick says it can be taken back", tickCell.querySelector("label.ack").getAttribute("title") === HOVER);
  check("an open row's tick has no hover", !recRows[1].lastChild.querySelector("label.ack").hasAttribute("title"));

  console.log("\nMaintenance Mode says what pressing it does");
  const off = await open("/problem-list");
  const pill = (r) => [...r.querySelectorAll("button.pill")].find((b) => /Maintenance/.test(b.textContent));
  check("off: Start Maintenance Mode", pill(off.root) && pill(off.root).textContent === "Start Maintenance Mode", pill(off.root) && pill(off.root).textContent);
  const on = await open("/problem-list", { status: (reply) => ({ ...reply,
    maintenance: { open: true, until: new Date(Date.now() + 14.5 * 60e3).toISOString(), default_minutes: 10 } }) });
  check("open: End Maintenance Mode, with the minutes left",
    pill(on.root) && pill(on.root).textContent === "End Maintenance Mode (15 min left)", pill(on.root) && pill(on.root).textContent);
  on.panel.remove();
  // A window that ran out while the page was open reads as off, so the
  // button never offers to end what has ended.
  const ended = await open("/problem-list", { status: (reply) => ({ ...reply,
    maintenance: { open: true, until: new Date(Date.now() - 60e3).toISOString(), default_minutes: 10 } }) });
  check("a window already past its end: Start Maintenance Mode", pill(ended.root) && pill(ended.root).textContent === "Start Maintenance Mode",
    pill(ended.root) && pill(ended.root).textContent);
  ended.panel.remove();

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
