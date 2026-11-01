// Proxenos as an app: the page in a window of its own, a menu-bar icon (the tray on Windows), and
// the scheduler, with a Python and the page's server inside the app, so nothing needs installing.
//
// At launch it starts the page's server (a Next.js standalone build, run by Electron's own Node in
// a utility process) on a free loopback port and opens a window on it once it answers. The page
// runs the `proxenos` command with the bundled Python (PROXENOS_PYTHON) from the app's resources
// (PROXENOS_HOME). `proxenos schedule` runs beside it while the app is open, once a vault is set
// up, and is stopped cleanly on quit. Links to other sites open in the browser, and mailto:,
// whatsapp: and slack: links in their apps, as mac/Proxenos.swift does. Nothing is sent anywhere:
// no telemetry, and no updates yet.
//
// Built by desktop/build.sh. `npm start` here runs it from desktop/resources once that's built.

"use strict";

const { app, BrowserWindow, Menu, Tray, nativeImage, session, shell, utilityProcess } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const MAC = process.platform === "darwin";
const WINDOWS = process.platform === "win32";
const RESOURCES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "resources");
const WEB = path.join(RESOURCES, "web"); // server.js, .next and public
const PYTHON = WINDOWS ? path.join(RESOURCES, "python", "python.exe") : path.join(RESOURCES, "python", "bin", "python3");
const BUSY = 75; // `proxenos schedule`'s exit when another scheduler already keeps the vault
const STOP_GRACE = 30_000; // ms: the scheduler gives a running job 20 s to wind down, then ends it
const RETRY = 5 * 60_000; // ms between tries at starting a scheduler that stopped by itself
const TICK = 30_000; // ms between looks at the vault, the schedule and the menu
// What leaves the window, and where it goes: the browser, the mail and chat apps, and on a Mac the
// Full Disk Access pane the Connect page links to. Anything else is dropped.
const OUTSIDE = new Set(["http:", "https:", "mailto:", "whatsapp:", "slack:", "x-apple.systempreferences:"]);

// The folder Proxenos keeps its settings in, found as config.settings_file() finds it. The app's
// own (Chromium's storage, its logs, the port) goes in a folder inside it, private like the rest.
const SETTINGS_DIR = MAC
  ? path.join(os.homedir(), "Library", "Application Support", "Proxenos")
  : WINDOWS
    ? path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "Proxenos")
    : path.join(path.isAbsolute(process.env.XDG_CONFIG_HOME ?? "") ? process.env.XDG_CONFIG_HOME : path.join(os.homedir(), ".config"), "proxenos");
const OWN = path.join(SETTINGS_DIR, "desktop");
fs.mkdirSync(OWN, { recursive: true, mode: 0o700 });
app.setPath("userData", OWN);
app.setAppLogsPath(path.join(OWN, "logs"));

let origin = ""; // http://127.0.0.1:<port>, once the page's server is up
let port = 0;
let server = null; // the page's utility process
let window = null;
let tray = null;
let quitting = false;
let restarts = 0; // of the page's server, this run
const schedule = { child: null, vault: null, paused: false, note: "", started: 0, stopping: null };
let syncing = null; // a Sync now run
let ticking = false;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", openWindow);
  app.on("activate", openWindow);
  app.on("window-all-closed", () => {}); // it stays in the menu bar
  app.on("before-quit", beforeQuit);
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => app.quit());
  app.whenReady().then(start);
}

async function start() {
  session.defaultSession.on("will-download", (_event, item) => {
    item.setSavePath(freeName(app.getPath("downloads"), item.getFilename()));
  });
  tray = new Tray(trayIcon());
  tray.setToolTip("Proxenos");
  if (!MAC) tray.on("click", openWindow); // on a Mac a click opens the menu
  refreshMenu();
  setInterval(tick, TICK).unref();

  port = await choosePort();
  origin = `http://127.0.0.1:${port}`;
  writeState({ port });
  startPage();
  startSchedule();
  if (await answering(origin, 120_000)) openWindow();
  refreshMenu();
}

// ── The page ────────────────────────────────────────────────────────────────

/** The environment the page and every command run with: the app's own Python and resources, and
 * a Python that reads only what's inside the app and never writes inside it. */
function environment() {
  const env = {
    ...process.env,
    PROXENOS_HOME: RESOURCES,
    PROXENOS_PYTHON: PYTHON,
    PROXENOS_PORT: String(port),
    PYTHONUTF8: "1",
    PYTHONNOUSERSITE: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  };
  delete env.PYTHONHOME;
  delete env.PYTHONPATH;
  // An app opened from the Finder gets a bare PATH; add Homebrew's, as the launchd jobs do.
  if (MAC) env.PATH = [...new Set(["/opt/homebrew/bin", "/usr/local/bin", ...(env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin").split(":")])].join(":");
  return env;
}

function startPage() {
  server = utilityProcess.fork(path.join(WEB, "server.js"), [], {
    cwd: WEB,
    env: { ...environment(), HOSTNAME: "127.0.0.1", PORT: String(port), NEXT_TELEMETRY_DISABLED: "1" },
    serviceName: "Proxenos page",
    stdio: "pipe",
  });
  const log = openLog(path.join(OWN, "logs", "page.log"));
  server.stdout?.pipe(log, { end: false });
  server.stderr?.pipe(log, { end: false });
  server.on("exit", (code) => {
    server = null;
    // It stopped by itself: start it again, a few times, and the window's next load finds it.
    if (!quitting && restarts++ < 5) {
      log.write(`desktop: the page's server stopped (exit ${code}); starting it again\n`);
      setTimeout(() => quitting || startPage(), 2000);
    }
    log.end();
  });
}

/** The page's port: PROXENOS_PORT when set; else last launch's, when it's free, so the page keeps
 * its address (and what it saved in the browser); else one the system picks. */
async function choosePort() {
  const set = Number(process.env.PROXENOS_PORT);
  if (Number.isInteger(set) && set > 0 && set < 65536) return set;
  const last = readJson(path.join(OWN, "state.json")).port;
  if (Number.isInteger(last) && (await free(last))) return last;
  return free(0);
}

function free(wanted) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => resolve(null));
    probe.listen(wanted, "127.0.0.1", () => {
      const { port: got } = probe.address();
      probe.close(() => resolve(got));
    });
  });
}

/** Whether `url` answers at all within `ms`, trying every quarter second. */
async function answering(url, ms) {
  const until = Date.now() + ms;
  while (Date.now() < until && !quitting) {
    const up = await new Promise((resolve) => {
      const request = http.get(url, (response) => {
        response.resume();
        resolve(true);
      });
      request.on("error", () => resolve(false));
      request.setTimeout(2000, () => request.destroy());
    });
    if (up) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

// ── The window ──────────────────────────────────────────────────────────────

function openWindow() {
  if (!origin) return; // still starting; it opens once the page answers
  if (MAC) app.dock?.show();
  if (window) {
    window.show();
    window.focus();
    return;
  }
  window = new BrowserWindow({
    width: 1280,
    height: 860,
    title: "Proxenos",
    backgroundColor: "#111111",
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  const contents = window.webContents;
  // Only the page itself stays in the window; anything else opens where it belongs.
  contents.on("will-navigate", (event, url) => {
    if (sameOrigin(url)) return;
    event.preventDefault();
    openOutside(url);
  });
  contents.setWindowOpenHandler(({ url }) => {
    openOutside(url);
    return { action: "deny" };
  });
  // The server is restarting: try again in a moment, as the Swift app does.
  contents.on("did-fail-load", (_event, code, _description, url, mainFrame) => {
    if (mainFrame && code !== -3 && sameOrigin(url)) setTimeout(() => window?.loadURL(url).catch(() => {}), 2000);
  });
  window.on("closed", () => {
    window = null;
    if (MAC) app.dock?.hide();
  });
  window.loadURL(`${origin}/app`).catch(() => {}); // a failed load is retried above
}

function sameOrigin(url) {
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
}

function openOutside(url) {
  let scheme = "";
  try {
    scheme = new URL(url).protocol;
  } catch {
    return;
  }
  if (OUTSIDE.has(scheme)) shell.openExternal(url).catch(() => {});
}

/** `name` in `folder`, or name-1, name-2, ... when it's taken, as the Swift app saves downloads. */
function freeName(folder, name) {
  const { name: stem, ext } = path.parse(name);
  let target = path.join(folder, name);
  for (let n = 1; fs.existsSync(target); n++) target = path.join(folder, `${stem}-${n}${ext}`);
  return target;
}

// ── The schedule ────────────────────────────────────────────────────────────

/** The vault, found as `proxenos` finds it in the app: PROXENOS_VAULT (or the older TWIN_VAULT),
 * else the settings file's, else ~/proxenos_vault when that exists. Null before setup picks one,
 * so nothing makes a vault the person hasn't chosen. */
function vaultPath() {
  const chosen = process.env.PROXENOS_VAULT?.trim() || process.env.TWIN_VAULT?.trim() || readJson(path.join(SETTINGS_DIR, "settings.json")).vault;
  const set = typeof chosen === "string" && chosen.trim() ? chosen.trim() : "";
  const vault = path.resolve(RESOURCES, expandHome(set || "~/proxenos_vault"));
  return set || fs.existsSync(vault) ? vault : null;
}

function expandHome(p) {
  return p === "~" || p.startsWith("~/") || p.startsWith("~\\") ? path.join(os.homedir(), p.slice(1)) : p;
}

/** Start `proxenos schedule` on the vault, unless it's paused, going or stopping, or there's no
 * vault. */
function startSchedule() {
  const vault = vaultPath();
  if (schedule.child || schedule.stopping || schedule.paused || !vault || quitting) return;
  schedule.started = Date.now();
  schedule.note = "";
  const log = openLog(path.join(OWN, "logs", "schedule.log"));
  const child = spawn(PYTHON, ["-m", "proxenos", "schedule"], {
    cwd: RESOURCES,
    env: { ...environment(), PROXENOS_VAULT: vault },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  child.stdout.pipe(log, { end: false });
  child.stderr.pipe(log, { end: false });
  child.on("close", () => log.end());
  child.on("error", (error) => log.write(`desktop: couldn't start the schedule: ${error.message}\n`));
  child.on("exit", (code) => {
    if (schedule.child !== child) return;
    schedule.child = null;
    if (code === BUSY) schedule.note = "Another scheduler keeps this vault";
    else if (code && !quitting && !schedule.paused) schedule.note = `The schedule stopped (exit ${code})`;
    refreshMenu();
  });
  Object.assign(schedule, { child, vault });
  refreshMenu();
}

async function stopSchedule() {
  const child = schedule.child;
  if (!child) return schedule.stopping;
  schedule.child = null;
  schedule.stopping = stop(child, STOP_GRACE);
  await schedule.stopping;
  schedule.stopping = null;
}

/** Stop a command: SIGTERM, then SIGKILL after `grace` ms. Windows has no SIGTERM, so there it ends
 * the command and anything it started at once, which every run is safe to (docs/apps.md). */
function stop(child, grace) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve();
    const timer = setTimeout(() => child.kill("SIGKILL"), grace);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    if (WINDOWS) spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { windowsHide: true });
    else child.kill("SIGTERM");
  });
}

/** Sync now: `proxenos sync` in the background, its output in the vault's sync log, as the
 * schedule's are. One that finds a sync going says so there and stops. */
function syncNow() {
  const vault = vaultPath();
  if (syncing || !vault) return;
  const logs = path.join(vault, "logs");
  fs.mkdirSync(logs, { recursive: true, mode: 0o700 });
  const log = openLog(path.join(logs, "sync.log"));
  syncing = spawn(PYTHON, ["-m", "proxenos", "sync"], {
    cwd: RESOURCES,
    env: { ...environment(), PROXENOS_VAULT: vault, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  syncing.stdout.pipe(log, { end: false });
  syncing.stderr.pipe(log, { end: false });
  syncing.on("close", () => log.end());
  const done = () => {
    syncing = null;
    refreshMenu();
  };
  syncing.on("exit", done);
  syncing.on("error", done);
  refreshMenu();
}

/** Every TICK: start the schedule once there's a vault, again after it stopped by itself, and
 * afresh when setup moved the vault; then bring the menu up to date. */
async function tick() {
  if (quitting || ticking) return;
  ticking = true;
  try {
    if (schedule.child && schedule.vault !== vaultPath()) {
      await stopSchedule();
      startSchedule();
    } else if (!schedule.child && Date.now() - schedule.started >= RETRY) {
      startSchedule();
    }
    refreshMenu();
  } finally {
    ticking = false;
  }
}

// ── The menu ────────────────────────────────────────────────────────────────

function refreshMenu() {
  if (!tray || tray.isDestroyed()) return;
  const vault = vaultPath();
  const items = [
    { label: "Open Proxenos", click: openWindow, enabled: Boolean(origin) },
    { type: "separator" },
    { label: syncing ? "Syncing…" : "Sync now", click: syncNow, enabled: Boolean(vault) && !syncing },
    { label: vault ? lastSynced(vault) : "Set up Proxenos to start syncing", enabled: false },
  ];
  if (schedule.note) items.push({ label: schedule.note, enabled: false });
  if (vault) {
    items.push(
      schedule.paused
        ? { label: "Resume syncing", click: resume }
        : { label: "Pause syncing", click: pause },
    );
  }
  items.push({ type: "separator" }, { label: "Quit Proxenos", role: "quit" });
  tray.setContextMenu(Menu.buildFromTemplate(items));
}

/** The menu's line on the schedule, from <vault>/state/schedule.json. */
function lastSynced(vault) {
  const status = readJson(path.join(vault, "state", "schedule.json"));
  if (status.running?.job) return `${status.running.job === "night" ? "Night run" : "Sync"} running`;
  const last = status.sync?.last;
  const ended = last?.ended ? new Date(last.ended) : null;
  if (!ended || Number.isNaN(ended.getTime())) return "Not synced yet";
  const today = ended.toDateString() === new Date().toDateString();
  const when = today
    ? ended.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : ended.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  return last.result === "ok" ? `Last synced ${when}` : `Last sync ${last.result}, ${when}`;
}

async function pause() {
  schedule.paused = true;
  schedule.note = "";
  await stopSchedule();
  refreshMenu();
}

function resume() {
  schedule.paused = false;
  startSchedule();
  refreshMenu();
}

/** The menu-bar icon. On a Mac, the mark's two circles (web/src/app/icon.svg) drawn here as a
 * template image, which macOS tints for a light or dark menu bar; elsewhere, the page's icon. */
function trayIcon() {
  if (!MAC) return nativeImage.createFromPath(path.join(WEB, "public", "icon-192.png")).resize({ width: 16, height: 16 });
  const size = 36; // 18 points at 2x
  const pixels = Buffer.alloc(size * size * 4); // BGRA; only alpha matters in a template
  const samples = 4; // a side, for smooth edges
  const unit = 44 / size; // the icon's 64-unit square, cropped to the circles (10 to 54)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let alpha = 0;
      for (let i = 0; i < samples; i++) {
        for (let j = 0; j < samples; j++) {
          const u = 10 + (x + (i + 0.5) / samples) * unit;
          const v = 10 + (y + (j + 0.5) / samples) * unit;
          if (Math.hypot(u - 27, v - 27) <= 14) alpha += 1; // the disc
          else if (Math.abs(Math.hypot(u - 37, v - 37) - 14) <= 1.5) alpha += 0.65; // the ring
        }
      }
      pixels[(y * size + x) * 4 + 3] = Math.round((255 * alpha) / samples ** 2);
    }
  }
  const image = nativeImage.createFromBitmap(pixels, { width: size, height: size, scaleFactor: 2 });
  image.setTemplateImage(true);
  return image;
}

// ── Quitting ────────────────────────────────────────────────────────────────

/** Stop the schedule and a Sync now cleanly before the app goes, then the page. */
function beforeQuit(event) {
  if (quitting) return;
  event.preventDefault();
  quitting = true;
  tray?.destroy();
  Promise.all([stopSchedule(), syncing ? stop(syncing, 10_000) : null]).finally(() => {
    server?.kill();
    app.quit();
  });
}

// TODO(updates): electron-updater from signed GitHub Releases, once the app is signed
// (docs/apps.md). Until then a new version is a new download.

// ── Files ───────────────────────────────────────────────────────────────────

function readJson(file) {
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8"));
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function writeState(fields) {
  const file = path.join(OWN, "state.json");
  fs.writeFileSync(file, JSON.stringify({ ...readJson(file), ...fields }) + "\n", { mode: 0o600 });
}

/** A log to append to, private, started afresh (the last kept as .old) once it passes 5 MB. */
function openLog(file) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  try {
    if (fs.statSync(file).size > 5 * 1024 * 1024) fs.renameSync(file, `${file}.old`);
  } catch {
    // Not there yet.
  }
  return fs.createWriteStream(file, { flags: "a", mode: 0o600 });
}
