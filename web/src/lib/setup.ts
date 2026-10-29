// Server side of the setup page and Settings. Import only from route handlers and server components.
//
// Everything goes through `proxenos setup`, which owns the settings file and the Keychain: it
// prints where things stand, and with --apply makes one change read from its stdin. A key or
// token goes there and nowhere else (not its arguments, its environment, a log, or any answer
// from here), and the command never prints one back. Its answer is read field by field, so
// nothing else in it reaches the page.

import { execFile } from "node:child_process";

import { lastLine, NO_COMMAND } from "./connect";
import type { SecretState, SettingKey, SettingOrigin, SettingValue, SetupChange, SetupResponse, SetupResult, SetupStatus } from "./types";
import { SETTING_KEYS } from "./types";
import { proxenosBin, REPO_ROOT, setting } from "./vault";

// Checking a key is one request to Anthropic; everything else answers at once.
const SETUP_MS = 45_000;
const MAX_OUTPUT = 256 * 1024;
const MAX_VALUE = 4096;
const ORIGINS: readonly SettingOrigin[] = ["environment", ".env", "settings", "keychain"];
/** The secrets `proxenos setup` keeps, as config.SECRET names them. */
const SECRET_NAME =
  /^(ANTHROPIC_API_KEY|BEEPER_ACCESS_TOKEN|GMAIL_[A-Z0-9_]+|SLACK_USER_TOKEN(_\w+)?|STRAVA_(CLIENT_ID|CLIENT_SECRET|REFRESH_TOKEN)|GOOGLE_CLIENT_(ID|SECRET))$/;
const MODEL_NAME = /^[\w.:/-]{1,100}$/;

/** A first run: no name and no vault, from the environment, the repo's .env or the settings file. */
export function setupNeeded(): boolean {
  return !setting("NAME") && !setting("VAULT");
}

// ── The command's answer, field by field ────────────────────────────────────

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function origin(v: unknown): SettingOrigin | null {
  return ORIGINS.find((o) => o === v) ?? null;
}

function toStatus(raw: unknown): SetupStatus | null {
  const r = rec(raw);
  const settings = rec(r.settings);
  const vault = rec(r.vault);
  const model = rec(r.model);
  const ollama = rec(r.ollama);
  if (typeof r.needed !== "boolean" || !str(vault.path) || !str(model.name)) return null;
  return {
    needed: r.needed,
    savesTo: r.saves_to === ".env" ? ".env" : "settings",
    settingsFile: str(r.settings_file) ?? "",
    home: str(r.home) ?? "",
    settings: Object.fromEntries(
      SETTING_KEYS.map((key): [SettingKey, SettingValue] => {
        const s = rec(settings[key]);
        return [key, { value: str(s.value), from: origin(s.from) }];
      }),
    ) as Record<SettingKey, SettingValue>,
    vault: {
      path: str(vault.path) ?? "",
      exists: vault.exists === true,
      cloud: vault.cloud === "icloud" || vault.cloud === "drive" ? vault.cloud : null,
    },
    model: {
      kind: model.kind === "local" || model.kind === "api" ? model.kind : "none",
      name: str(model.name) ?? "",
    },
    ollama: {
      running: ollama.running === true,
      models: Array.isArray(ollama.models) ? ollama.models.filter((m): m is string => typeof m === "string") : [],
    },
    keychain: r.keychain === true,
    secrets: Array.isArray(r.secrets)
      ? r.secrets.flatMap((raw): SecretState[] => {
          const s = rec(raw);
          const name = str(s.name);
          return name && SECRET_NAME.test(name) ? [{ name, set: s.set === true, from: origin(s.from) }] : [];
        })
      : [],
  };
}

// ── Running it ──────────────────────────────────────────────────────────────

/** Run `proxenos setup [args]` with `stdin`, and parse what it prints. A secret in stdin is blanked from any error. */
async function run(args: string[], stdin: string | null, secret: string | null): Promise<{ answer: unknown } | { error: string }> {
  const bin = await proxenosBin();
  if (!bin) return { error: NO_COMMAND };
  const hide = (text: string) => (secret ? text.split(secret).join("[hidden]") : text);
  return new Promise((resolve) => {
    const child = execFile(
      bin,
      ["setup", ...args],
      { cwd: REPO_ROOT, timeout: SETUP_MS, maxBuffer: MAX_OUTPUT },
      (error, stdout, stderr) => {
        if (error) {
          const why = error.killed ? "it took too long" : lastLine(hide(stderr)) || "it failed";
          resolve({ error: `proxenos setup didn't answer: ${why}` });
          return;
        }
        try {
          resolve({ answer: JSON.parse(stdout) });
        } catch {
          resolve({ error: "proxenos setup gave an answer this page can't read." });
        }
      },
    );
    if (stdin !== null) {
      // The command may exit without reading it all; that's reported by how it ends, not here.
      child.stdin?.on("error", () => {});
      child.stdin?.end(stdin);
    }
  });
}

/** The settings, the model and which secrets are set, from `proxenos setup`. */
export async function getSetup(): Promise<SetupResponse> {
  const done = await run([], null, null);
  if ("error" in done) return { status: null, error: done.error };
  const status = toStatus(done.answer);
  return status ? { status, error: null } : { status: null, error: "proxenos setup gave an answer this page can't read." };
}

/** Make one change through `proxenos setup --apply`, the change on its stdin. */
export async function applySetup(change: SetupChange): Promise<SetupResult> {
  const secret = "key" in change ? change.key : "value" in change ? change.value : null;
  const done = await run(["--apply"], JSON.stringify(change), secret);
  if ("error" in done) return { ok: false, message: null, error: done.error, status: null };
  const r = rec(done.answer);
  const hide = (text: string | null) => (text && secret ? text.split(secret).join("[hidden]") : text);
  return {
    ok: r.ok === true,
    message: hide(str(r.message)),
    error: r.ok === true ? null : (hide(str(r.error)) ?? "That didn't work."),
    status: toStatus(r.status),
  };
}

// ── The page's request ──────────────────────────────────────────────────────

function oneLine(v: unknown, max = MAX_VALUE): v is string {
  return typeof v === "string" && v.length <= max && !/[\r\n\0]/.test(v);
}

/** One change from a request's body, or why it isn't one. Only one kind of change per request. */
export function parseChange(body: Record<string, unknown>): SetupChange | { error: string } {
  if ("settings" in body) {
    const raw = rec(body.settings);
    const settings: Partial<Record<SettingKey, string>> = {};
    for (const [key, value] of Object.entries(raw)) {
      const known = SETTING_KEYS.find((k) => k === key);
      if (!known) return { error: `${key} isn't a setting.` };
      if (!oneLine(value)) return { error: `The ${known.replace(/_/g, " ")} has to be one line of text.` };
      settings[known] = value.trim();
    }
    if (!Object.keys(settings).length) return { error: "Nothing to save." };
    return { settings };
  }
  if ("key" in body) {
    return oneLine(body.key, 512) && body.key.trim() ? { key: body.key.trim() } : { error: "Paste the key on one line." };
  }
  if ("ollama" in body) {
    return typeof body.ollama === "string" && MODEL_NAME.test(body.ollama.trim())
      ? { ollama: body.ollama.trim() }
      : { error: "Name a model, e.g. gemma4:26b." };
  }
  if ("secret" in body) {
    if (typeof body.secret !== "string" || !SECRET_NAME.test(body.secret)) return { error: "That isn't one of Proxenos's secrets." };
    if (!oneLine(body.value) || !body.value.trim()) return { error: "Paste the new value on one line." };
    return { secret: body.secret, value: body.value.trim() };
  }
  if ("forget" in body) {
    return typeof body.forget === "string" && SECRET_NAME.test(body.forget)
      ? { forget: body.forget }
      : { error: "That isn't one of Proxenos's secrets." };
  }
  return { error: "Nothing to change." };
}
