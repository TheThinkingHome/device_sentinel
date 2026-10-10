// Panel checks: a dashboard tab left open across an update (0.25.4).
// Home Assistant hands an open tab the new dashboard file after an
// update, while the old one still runs. The new copy must register
// nothing and raise no error, and the running page must say it is out
// of date and offer a reload, whether it learns it from the new copy or
// from the server. Found in James's log of 9 October 2026: "the name
// device-sentinel-panel has already been used with this registry".
// Run with: LC_ALL=en_US.UTF-8 node check_stale_tab.js [path/to/panel.js]
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const PANEL = process.argv[2] || path.join(__dirname, "..", "..", "custom_components", "device_sentinel", "frontend", "panel.js");
const SOURCE = fs.readFileSync(PANEL, "utf8");
const payloads = JSON.parse(fs.readFileSync(__dirname + "/payloads.json", "utf8"));
const PREFIX = "/device-sentinel";
const OLD = "aaaaaaaaaaaa";
const NEW = "bbbbbbbbbbbb";
const LINE = "Device Sentinel was updated. Reload this page to use the new version.";

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

// The file as a browser runs it from its hashed address, or with no
// address the code can read when file is null.
const copy = (file) => (file ? `${SOURCE}\n//# sourceURL=http://ha.local:8123/device_sentinel_panel/panel.${file}.js\n` : SOURCE);

function tab() {
  const errors = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (err) => errors.push(String(err.message)));
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    runScripts: "outside-only", url: `http://ha.local${PREFIX}`, virtualConsole,
  });
  const { window } = dom;
  window.customElements.define("ha-menu-button", class extends window.HTMLElement {});
  return { window, errors };
}

// Load one copy of the file into the tab, as Home Assistant's import
// does: a throw here is the error the browser reports to the log.
function load(t, file) {
  try {
    t.window.eval(copy(file));
    return null;
  } catch (err) {
    return `${err.name}: ${err.message}`;
  }
}

async function open(t, served, events) {
  const { window } = t;
  const panel = window.document.createElement("device-sentinel-panel");
  window.document.body.append(panel);
  panel.route = { prefix: PREFIX, path: "" };
  const reply = { ...payloads };
  panel.hass = {
    callWS: async (message) => {
      const kind = message.type.replace("device_sentinel/", "");
      if (!(kind in reply)) throw new Error(`no payload for ${kind}`);
      const out = JSON.parse(JSON.stringify(reply[kind]));
      if (kind === "status" && served.file !== undefined) out.panel = served.file;
      return out;
    },
    connection: {
      subscribeMessage: async (callback) => {
        if (events) events.push(callback);
        return () => {};
      },
    },
    states: {},
  };
  await settle();
  return panel;
}

const notice = (panel) => panel.shadowRoot.querySelector(".updated");
const notices = (panel) => panel.shadowRoot.querySelectorAll(".updated").length;

(async () => {
  console.log("The fault: two copies of the file in one tab");
  {
    const t = tab();
    check("the first copy loads", load(t, OLD) === null);
    const second = load(t, NEW);
    check("the second copy raises no error", second === null, second);
    const t2 = tab();
    load(t2, OLD);
    const same = load(t2, OLD);
    check("nor does a copy of the same file", same === null, same);
  }

  console.log("The running page hears the new copy arrive");
  {
    const t = tab();
    load(t, OLD);
    const served = { file: OLD };
    const panel = await open(t, served);
    check("no line while the page is the file served", notice(panel) === null);
    load(t, NEW);
    await settle();
    const line = notice(panel);
    check("a new copy arriving shows the line", Boolean(line));
    check("in the owner's words", line && line.querySelector("span").textContent === LINE, line && line.textContent);
    const button = line && line.querySelector("button");
    check("with a Reload button", button && button.textContent === "Reload");
    check("above the status band", line && line.nextElementSibling && line.nextElementSibling.classList.contains("head"));
    check("announced to a screen reader", line && line.getAttribute("role") === "status");
    const before = t.errors.length;
    if (button) button.click();
    check("Reload reloads the page", t.errors.slice(before).some((m) => /navigation|reload/i.test(m)), t.errors.slice(before));
    load(t, NEW);
    await settle();
    check("a third copy adds no second line", notices(panel) === 1, notices(panel));
    check("the page still answers", panel.shadowRoot.querySelectorAll(".tab").length === 8);
  }

  console.log("The running page hears it from the server");
  {
    const t = tab();
    load(t, OLD);
    const served = { file: OLD };
    const events = [];
    const panel = await open(t, served, events);
    check("the status reply naming this file shows nothing", notice(panel) === null);
    events.forEach((cb) => cb({ marker: 1, panel: OLD }));
    await settle();
    check("a change marker naming this file shows nothing", notice(panel) === null);
    events.forEach((cb) => cb({ marker: 2, panel: NEW }));
    await settle();
    check("a change marker naming another file shows the line", Boolean(notice(panel)));
  }
  {
    const t = tab();
    load(t, OLD);
    const served = { file: OLD };
    const panel = await open(t, served);
    served.file = NEW;
    panel.shadowRoot.querySelector(".actions .pill").click();
    await settle();
    check("Refresh after an update shows the line", Boolean(notice(panel)));
    const tabs = [...panel.shadowRoot.querySelectorAll(".tab")];
    tabs[6].click();
    await settle();
    check("it stays when the tab changes", Boolean(notice(panel)));
  }

  console.log("The page knows its own file from its address");
  {
    const t = tab();
    load(t, OLD);
    const panel = await open(t, {});
    t.window.dispatchEvent(new t.window.CustomEvent("device-sentinel-updated", { detail: { file: OLD } }));
    await settle();
    check("read from its address, with no reply to go by", notice(panel) === null);
    t.window.dispatchEvent(new t.window.CustomEvent("device-sentinel-updated", { detail: { file: NEW } }));
    await settle();
    check("and another file is told apart from it", Boolean(notice(panel)));
  }

  console.log("Home Assistant draws the page again after the new copy arrives");
  {
    const t = tab();
    load(t, OLD);
    const first = await open(t, { file: OLD });
    load(t, NEW);
    first.remove();
    // The element name still belongs to the copy running first, so the
    // page Home Assistant draws next is that copy's, and it missed the
    // new copy's word: it learns from the server's first reply.
    const again = await open(t, { file: NEW });
    check("the page drawn again learns from the server and shows the line", Boolean(notice(again)));
  }

  console.log("A browser that names no address");
  {
    const t = tab();
    load(t, null);
    const served = { file: OLD };
    const events = [];
    const panel = await open(t, served, events);
    check("the first reply stands for this copy", notice(panel) === null);
    events.forEach((cb) => cb({ marker: 1, panel: OLD }));
    await settle();
    check("the same file again shows nothing", notice(panel) === null);
    events.forEach((cb) => cb({ marker: 2, panel: NEW }));
    await settle();
    check("another file shows the line", Boolean(notice(panel)));
  }
  {
    const t = tab();
    load(t, null);
    const panel = await open(t, { file: OLD });
    load(t, null);
    await settle();
    check("a second copy arriving shows the line", Boolean(notice(panel)));
  }

  console.log("Nothing said without cause");
  {
    const t = tab();
    load(t, OLD);
    const events = [];
    const panel = await open(t, {}, events);
    check("a server that names no file shows nothing", notice(panel) === null);
    events.forEach((cb) => cb({ marker: 1 }));
    events.forEach((cb) => cb({ marker: 2, panel: null }));
    events.forEach((cb) => cb({ marker: 3, panel: 7 }));
    await settle();
    check("nor a marker without one, or with a value that is not a name", notice(panel) === null);
  }
  {
    const t = tab();
    load(t, OLD);
    const panel = await open(t, { file: OLD });
    t.window.dispatchEvent(new t.window.CustomEvent("device-sentinel-updated", { detail: { file: OLD } }));
    await settle();
    check("a copy naming this very file shows nothing", notice(panel) === null);
    for (const detail of [undefined, null, 7, "x", {}, { file: 7 }, { file: {} }, { other: NEW }]) {
      t.window.dispatchEvent(new t.window.CustomEvent("device-sentinel-updated", detail === undefined ? {} : { detail }));
    }
    await settle();
    check("nor word that no copy of the file sends", notice(panel) === null);
  }

  console.log("Timing");
  {
    const t = tab();
    load(t, OLD);
    const panel = t.window.document.createElement("device-sentinel-panel");
    t.window.document.body.append(panel);
    load(t, NEW);
    panel.route = { prefix: PREFIX, path: "" };
    panel.hass = {
      callWS: async (message) => JSON.parse(JSON.stringify(payloads[message.type.replace("device_sentinel/", "")])),
      connection: { subscribeMessage: async () => () => {} },
      states: {},
    };
    await settle();
    check("a copy arriving before the page is drawn shows the line once drawn", notices(panel) === 1, notices(panel));
  }
  {
    const t = tab();
    load(t, OLD);
    const panel = await open(t, { file: OLD });
    panel.remove();
    load(t, NEW);
    await settle();
    check("a page taken off screen stops listening", notice(panel) === null);
    t.window.document.body.append(panel);
    load(t, NEW);
    await settle();
    check("and listens again when put back", Boolean(notice(panel)));
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
