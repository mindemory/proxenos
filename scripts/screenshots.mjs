// The README's pictures: each main view of the page at desktop and phone width, from headless
// Chrome over its DevTools protocol. scripts/screenshots.sh starts the page on a made-up vault
// and Chrome on a throwaway profile; this only drives them.
//
//   node scripts/screenshots.mjs PAGE_URL DEBUG_PORT OUT_DIR
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const [page, debugPort, out] = process.argv.slice(2);
const VIEWS = ["home", "care", "errands", "drafts", "tasks", "journal", "projects", "life", "rhythms", "jobs"];
const SIZES = {
  desktop: { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false },
  // Drawn at twice the size, then scaled by half: smoother text than drawing it small.
  phone: { width: 412, height: 892, deviceScaleFactor: 2, mobile: true, scale: 0.5 },
};
// Views that open on a list, or on a preamble a phone has no room for, made ready first: `press`
// presses the first button whose text starts with it (a month, to read it), then `top`, by size,
// scrolls the first element matching [selector, the text it starts with] to just under the top bar.
const MONTHS = "section[aria-labelledby='rhythms-months-title']";
const BEFORE = {
  drafts: { top: { phone: ["p", "To send"] } },
  life: { press: "Read the month", top: { phone: ["h2.title-1", ""] } },
  rhythms: { top: { desktop: [MONTHS, ""], phone: [MONTHS, ""] } },
};
const LOADED_FOR_MS = 1000; // nothing loading for this long, and the view is done
const TIMEOUT_MS = 90_000; // the dev server compiles each route the first time it's asked

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const target = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve) => socket.addEventListener("open", resolve, { once: true }));
let lastId = 0;
const waiting = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const call = waiting.get(message.id);
  if (!call) return;
  waiting.delete(message.id);
  if (message.error) call.reject(new Error(`${call.method}: ${message.error.message}`));
  else call.resolve(message.result);
});

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++lastId;
    waiting.set(id, { method, resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  return (await send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
}

/** Wait until nothing on the page has been loading (a skeleton, or aria-busy) for LOADED_FOR_MS. */
async function settled(view) {
  const start = Date.now();
  let quietSince = null;
  while (Date.now() - start < TIMEOUT_MS) {
    const busy = await evaluate(
      `document.readyState !== "complete" || !!document.querySelector(".skeleton, [aria-busy='true']")`,
    );
    if (busy) quietSince = null;
    else if (quietSince === null) quietSince = Date.now();
    else if (Date.now() - quietSince >= LOADED_FOR_MS) return;
    await sleep(250);
  }
  throw new Error(`${view} was still loading after ${TIMEOUT_MS / 1000} seconds`);
}

mkdirSync(out, { recursive: true });
await send("Page.enable");
await send("Runtime.enable");
// A first visit every time: nothing kept from an earlier run, such as when the reader last came.
await send("Storage.clearDataForOrigin", { origin: new URL(page).origin, storageTypes: "all" });
for (const [size, { scale = 1, ...metrics }] of Object.entries(SIZES)) {
  await send("Emulation.setDeviceMetricsOverride", metrics);
  await send("Emulation.setTouchEmulationEnabled", { enabled: metrics.mobile });
  for (const view of VIEWS) {
    await send("Page.navigate", { url: view === "home" ? `${page}/app` : `${page}/app?view=${view}` });
    await sleep(500);
    await settled(view);
    const { press, top } = BEFORE[view] ?? {};
    if (press) {
      const pressed = await evaluate(`(() => {
        const button = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith(${JSON.stringify(press)}));
        button?.click();
        return !!button;
      })()`);
      if (!pressed) throw new Error(`${view} has no button "${press}"`);
      await sleep(500);
      await settled(view);
    }
    if (top?.[size]) {
      const [selector, text] = top[size];
      const found = await evaluate(`(() => {
        const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.textContent.trim().startsWith(${JSON.stringify(text)}));
        if (el) window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 76);
        return !!el;
      })()`);
      if (!found) throw new Error(`${view} has no ${selector} starting "${text}"`);
      await sleep(500);
    }
    const shot = await send("Page.captureScreenshot", {
      format: "png",
      clip: { x: 0, y: await evaluate("window.scrollY"), width: metrics.width, height: metrics.height, scale },
    });
    const file = path.join(out, `${view}-${size}.png`);
    writeFileSync(file, Buffer.from(shot.data, "base64"));
    console.log(file);
  }
}
socket.close();
