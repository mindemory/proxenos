// Finding an email address for a name in the vault's mail. Import only from route handlers.
//
// A draft names who it's for ("Priya Sharma"); an email needs an address. The newest message in
// raw/email/<account>/YYYY-MM.jsonl whose sender's name, or whose To entry, is that name gives
// it. Only the address leaves this file, and only to fill in a compose window: no message text,
// no subject, no path.

import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";
import readline from "node:readline";

import { normName, parseAddress } from "./actions";

const MONTH_FILE = /^\d{4}-\d{2}\.jsonl$/;
const MAX_LINE_CHARS = 16 * 1024 * 1024;
/** How far back to look: the newest this many months of mail. */
const MAX_MONTHS = 60;
/** A name is looked up again after this long, found or not. */
const CACHE_MS = 10 * 60 * 1000;
const CACHE_MAX = 2000;

interface Cached {
  address: string | null;
  at: number;
}

const cache = new Map<string, Cached>();

interface MailFile {
  month: string;
  file: string;
}

/** Every month file in raw/email, directly or under an account, newest month first. */
async function mailFiles(root: string): Promise<MailFile[]> {
  const out: MailFile[] = [];
  const list = async (dir: string, nested: boolean) => {
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      // Dirent says "file" or "directory" only for the thing itself, never for a symlink to one.
      if (e.isFile() && MONTH_FILE.test(e.name)) out.push({ month: e.name.slice(0, 7), file: p });
      else if (e.isDirectory() && nested) await list(p, false);
    }
  };
  await list(root, true);
  return out.sort((a, b) => b.month.localeCompare(a.month) || a.file.localeCompare(b.file));
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

interface Best {
  ts: string;
  address: string;
}

/** Look through one month file for the newest message that names each of `queries`. */
async function scan(file: string, queries: ReadonlySet<string>, prefilter: RegExp, best: Map<string, Best>): Promise<void> {
  const lines = readline.createInterface({ input: createReadStream(file, { encoding: "utf8" }), crlfDelay: Infinity });
  try {
    for await (const line of lines) {
      if (line.length < 2 || line.length > MAX_LINE_CHARS) continue;
      // Names sit before the message text in a record: cheap to rule out without parsing.
      const cut = line.indexOf('"body": ');
      if (!prefilter.test(cut > 0 ? line.slice(0, cut) : line)) continue;
      let rec: unknown;
      try {
        rec = JSON.parse(line);
      } catch {
        continue;
      }
      if (!rec || typeof rec !== "object") continue;
      const r = rec as Record<string, unknown>;
      const ts = typeof r.ts === "string" ? r.ts : "";

      const named: [string, string][] = [];
      // The sender, when it isn't the reader: the reader's own name tells nothing about who they wrote to.
      if (r.from_me !== true && typeof r.from_name === "string" && typeof r.from_address === "string") {
        const parsed = parseAddress(r.from_address);
        if (parsed) named.push([r.from_name, parsed[1]]);
      }
      for (const entry of Array.isArray(r.to) ? r.to : []) {
        const parsed = typeof entry === "string" ? parseAddress(entry) : null;
        if (parsed) named.push(parsed);
      }
      for (const [name, address] of named) {
        const q = normName(name);
        if (!q || !queries.has(q)) continue;
        const prev = best.get(q);
        if (!prev || ts > prev.ts) best.set(q, { ts, address });
      }
    }
  } finally {
    lines.close();
  }
}

/**
 * The address for each name, matched whole and without regard to case, from the newest message
 * that has it. Names (as `normName` writes them) with no match are left out of the answer.
 * Results are kept for a few minutes, so a page that polls doesn't read the mail again.
 */
export async function findAddresses(vault: string, names: readonly string[]): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  const now = Date.now();
  const todo = new Set<string>();
  for (const name of names) {
    const q = normName(name);
    if (!q || todo.has(q) || found.has(q)) continue;
    const hit = cache.get(`${vault}\0${q}`);
    if (hit && now - hit.at < CACHE_MS) {
      if (hit.address) found.set(q, hit.address);
    } else todo.add(q);
  }
  if (todo.size === 0) return found;

  const files = await mailFiles(path.join(vault, "raw", "email"));
  const pending = new Set(todo);
  const months = [...new Set(files.map((f) => f.month))].slice(0, MAX_MONTHS);
  for (const month of months) {
    // The pre-filter is a case-insensitive "does this line mention any of the names".
    const prefilter = new RegExp([...pending].map(escapeRegExp).join("|"), "i");
    const best = new Map<string, Best>();
    for (const f of files.filter((x) => x.month === month)) {
      try {
        await scan(f.file, pending, prefilter, best);
      } catch {
        // Unreadable file: look in the others.
      }
    }
    for (const [q, b] of best) {
      found.set(q, b.address);
      pending.delete(q);
    }
    if (pending.size === 0) break;
  }

  if (cache.size > CACHE_MAX) cache.clear();
  for (const q of todo) cache.set(`${vault}\0${q}`, { address: found.get(q) ?? null, at: now });
  return found;
}
