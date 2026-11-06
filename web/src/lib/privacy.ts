// Server side of the Privacy view. Import only from route handlers.
//
// Everything comes from `proxenos privacy`: what stays on this computer (the vault by folder,
// FileVault, the secrets kept, by name), what went to a model in the last 30 days (from the log
// each call leaves, never its words), what's read from elsewhere (the connected sources, by
// name and address, and the search engine people are looked up with, by its host, never a key)
// and whether notices go to the phone (by the server's host, never the topic).
// Its answer is read field by field, so nothing else in it reaches the page.


import { lastLine, NO_COMMAND } from "./connect";
import type {
  CallTotals,
  ConnectHow,
  FetchedSource,
  ModelCall,
  ModelWhere,
  PartSends,
  PrivacyReport,
  PrivacyResponse,
  SettingOrigin,
  StepCalls,
  VaultFolder,
} from "./types";
import { LOOKUP_ENGINES, MODEL_WHERES, VAULT_FOLDERS } from "./types";
import { nowIso, proxenos, vaultInfo, vaultPath } from "./vault";

// Adding up a large vault's folders can take a while on a slow disk.
const PRIVACY_MS = 60_000;
const MAX_OUTPUT = 2 * 1024 * 1024;
const MAX_TEXT = 120;
const ORIGINS: readonly SettingOrigin[] = ["environment", ".env", "settings", "keychain"];
const HOWS: readonly ConnectHow[] = ["live", "download", "folder"];

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function list(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function text(v: unknown): string {
  return typeof v === "string" ? v.slice(0, MAX_TEXT) : "";
}

/** A count: a whole number, at least 0. Anything else is null. */
function count(v: unknown): number | null {
  return typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : null;
}

function where(v: unknown): ModelWhere {
  return v === "this computer" ? "this computer" : "Anthropic";
}

function toTotals(raw: unknown): CallTotals {
  const r = rec(raw);
  return {
    calls: count(r.calls) ?? 0,
    failed: count(r.failed) ?? 0,
    hosted: count(r.hosted) ?? 0,
    sentChars: count(r.sent_chars) ?? 0,
    images: count(r.images) ?? 0,
    redacted: count(r.redacted) ?? 0,
    answerChars: count(r.answer_chars) ?? 0,
    tokensIn: count(r.tokens_in) ?? 0,
    tokensOut: count(r.tokens_out) ?? 0,
  };
}

function toStep(raw: unknown): StepCalls {
  const r = rec(raw);
  return { ...toTotals(r), step: text(r.step) || "proxenos", part: text(r.part) || null };
}

function toCall(raw: unknown): ModelCall {
  const r = rec(raw);
  return {
    at: text(r.at),
    step: text(r.step) || "proxenos",
    model: text(r.model),
    where: where(r.where),
    sentChars: count(r.sent_chars),
    images: count(r.images),
    redacted: count(r.redacted),
    answerChars: count(r.answer_chars),
    tokensIn: count(r.tokens_in),
    tokensOut: count(r.tokens_out),
    seconds: typeof r.seconds === "number" && Number.isFinite(r.seconds) && r.seconds >= 0 ? r.seconds : null,
    ok: r.ok === true,
  };
}

function toSends(raw: unknown): PartSends | null {
  const r = rec(raw);
  const part = text(r.part);
  const sends = typeof r.sends === "string" ? r.sends.slice(0, 400) : "";
  if (!part || !sends) return null;
  return { part, sends, steps: list(r.steps).map(text).filter(Boolean) };
}

function toSource(raw: unknown): FetchedSource | null {
  const r = rec(raw);
  const id = text(r.id);
  const how = HOWS.find((h) => h === r.how);
  if (!id || !how) return null;
  return {
    id,
    how,
    lastRead: text(r.last_read) || null,
    accounts: list(r.accounts).flatMap((a) => {
      const account = rec(a);
      const name = text(account.name);
      const address = text(account.address);
      return name || address ? [{ name, address }] : [];
    }),
    workspaces: list(r.workspaces).map(text).filter(Boolean),
  };
}

function toReport(raw: unknown): PrivacyReport | null {
  const r = rec(raw);
  const here = rec(r.here);
  const vault = rec(here.vault);
  const sent = rec(r.sent);
  const model = rec(sent.model);
  const byWhere = rec(sent.by_where);
  const fetched = rec(r.fetched);
  // An older proxenos doesn't say: it had no notices.
  const notices = rec(r.notices);
  const folders = rec(vault.folders);
  if (!text(vault.path) || !Object.keys(sent).length || !Object.keys(fetched).length) return null;
  return {
    here: {
      vault: {
        path: text(vault.path),
        exists: vault.exists === true,
        bytes: count(vault.bytes) ?? 0,
        folders: Object.fromEntries(VAULT_FOLDERS.map((f) => [f, count(folders[f]) ?? 0])) as Record<VaultFolder, number>,
        cloud: vault.cloud === "icloud" || vault.cloud === "drive" ? vault.cloud : null,
      },
      filevault: typeof here.filevault === "boolean" ? here.filevault : null,
      settingsFile: text(here.settings_file),
      // An older proxenos doesn't say: it only ran on a Mac.
      secretStore: text(here.secret_store).slice(0, 40) || "Keychain",
      secrets: list(here.secrets).flatMap((s) => {
        const secret = rec(s);
        const name = text(secret.name);
        return /^[A-Z][A-Z0-9_]*$/.test(name) ? [{ name, from: ORIGINS.find((o) => o === secret.from) ?? null }] : [];
      }),
    },
    sent: {
      model: {
        name: text(model.name),
        kind: model.kind === "local" || model.kind === "api" ? model.kind : "none",
        voice: text(model.voice) || null,
        fast: text(model.fast) || null,
      },
      days: count(sent.days) ?? 30,
      since: text(sent.since),
      totals: toTotals(sent.totals),
      byWhere: Object.fromEntries(MODEL_WHERES.map((w) => [w, toTotals(byWhere[w])])) as Record<ModelWhere, CallTotals>,
      byStep: list(sent.by_step).map(toStep),
      recent: list(sent.recent).map(toCall),
      sends: list(sent.sends).flatMap((s) => toSends(s) ?? []),
    },
    fetched: {
      sources: list(fetched.sources).flatMap((s) => toSource(s) ?? []),
      links: fetched.links === true,
      // An older proxenos doesn't say: it looked nothing up.
      music: { on: rec(fetched.music).on === true, artists: count(rec(fetched.music).artists) ?? 0 },
      lookup: {
        on: rec(fetched.lookup).on === true,
        engine: LOOKUP_ENGINES.find((e) => e === rec(fetched.lookup).engine) ?? "duckduckgo",
        host: text(rec(fetched.lookup).host),
      },
    },
    notices: {
      on: notices.on === true,
      server: text(notices.server),
      quiet: text(notices.quiet) || null,
      sends: typeof notices.sends === "string" ? notices.sends.slice(0, 400) : "",
    },
  };
}

/** What stays here, what went to a model and what's read from elsewhere, from `proxenos privacy`. */
export async function getPrivacy(): Promise<PrivacyResponse> {
  const base = { now: nowIso(), vault: await vaultInfo(vaultPath()) };
  const cli = await proxenos();
  if (!cli) return { ...base, report: null, error: NO_COMMAND };
  return new Promise((resolve) => {
    cli.exec(["privacy"], { timeout: PRIVACY_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      if (error) {
        const why = lastLine(stderr) || (error.killed ? "it took too long" : "it failed");
        resolve({ ...base, report: null, error: `proxenos privacy didn't answer: ${why}` });
        return;
      }
      let report: PrivacyReport | null = null;
      try {
        report = toReport(JSON.parse(stdout));
      } catch {
        report = null;
      }
      resolve(report ? { ...base, report, error: null } : { ...base, report: null, error: "proxenos privacy gave an answer this page can't read." });
    });
  });
}
