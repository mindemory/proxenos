// Finding the WhatsApp number for a chat name in the vault. Import only from route handlers.
//
// A reply draft names the chat it answers ("Asha"); opening that chat needs its number. A direct
// chat in raw/whatsapp/messages/YYYY-MM.jsonl keyed by a phone number ("15551234567@s.whatsapp.net")
// with that chat name gives it. Chats WhatsApp keys by a private id ("...@lid") have no number,
// so those drafts fall back to the chat picker. Only the digits leave this file.

import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";
import readline from "node:readline";

import { normName } from "./actions";

const MONTH_FILE = /^\d{4}-\d{2}\.jsonl$/;
const PHONE_CHAT = /^(\d{7,15})@s\.whatsapp\.net$/;
/** How far back to look: the newest this many months of chats. */
const MAX_MONTHS = 12;
/** A name found is looked up again after this long; one with no number (a group, a private id), after MISS_MS. */
const CACHE_MS = 10 * 60 * 1000;
const MISS_MS = 6 * 60 * 60 * 1000;
const CACHE_MAX = 2000;
/** The most a reader's click waits on names never looked up before. The look-up goes on behind it. */
const WAIT_MS = 1500;

interface Cached {
  phone: string | null;
  at: number;
}

const cache = new Map<string, Cached>();
const stale = (hit: Cached, now: number) => now - hit.at >= (hit.phone ? CACHE_MS : MISS_MS);

/**
 * The number for each chat name, matched whole and without regard to case. As with addresses
 * (recipients.ts), names already looked up are answered at once from the last look-up, redone
 * behind the answer when it's old, and names never looked up are waited on for at most WAIT_MS.
 */
export async function findPhones(vault: string, names: readonly string[]): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  const now = Date.now();
  let unknown = false;
  let old = false;
  for (const name of names) {
    const q = normName(name);
    const hit = q ? cache.get(`${vault}\0${q}`) : undefined;
    if (!q) continue;
    if (!hit) unknown = true;
    else {
      if (hit.phone) found.set(q, hit.phone);
      old ||= stale(hit, now);
    }
  }
  if (!unknown && !old) return found;
  const work = lookUp(vault, names);
  if (!unknown) {
    work.catch(() => undefined);
    return found;
  }
  return (await Promise.race([work, new Promise<null>((done) => setTimeout(() => done(null), WAIT_MS))])) ?? found;
}

// A look-up already under way, by vault and names: a second request for the same names (the page's
// first Drafts read, made at startup, and a reader's click during it) joins it instead of scanning
// the vault again alongside it.
const inflight = new Map<string, Promise<Map<string, string>>>();

function lookUp(vault: string, names: readonly string[]): Promise<Map<string, string>> {
  const key = [vault, ...[...new Set(names)].sort()].join("\0");
  const running = inflight.get(key);
  if (running) return running;
  const work = lookUpPhones(vault, names).finally(() => inflight.delete(key));
  inflight.set(key, work);
  return work;
}

async function lookUpPhones(vault: string, names: readonly string[]): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  const todo = new Set<string>();
  const now = Date.now();
  for (const name of names) {
    const q = normName(name);
    if (!q) continue;
    const hit = cache.get(`${vault}\0${q}`);
    if (hit && !stale(hit, now)) {
      if (hit.phone) found.set(q, hit.phone);
    } else todo.add(q);
  }
  if (todo.size === 0) return found;

  const dir = path.join(vault, "raw", "whatsapp", "messages");
  const months = (await fs.readdir(dir).catch(() => [] as string[]))
    .filter((f) => MONTH_FILE.test(f))
    .sort()
    .reverse()
    .slice(0, MAX_MONTHS);
  const pending = new Set(todo);
  for (const month of months) {
    if (pending.size === 0) break;
    const lines = readline.createInterface({ input: createReadStream(path.join(dir, month), { encoding: "utf8" }), crlfDelay: Infinity });
    try {
      for await (const line of lines) {
        if (!line.includes("@s.whatsapp.net") || !line.includes('"direct"')) continue;
        let r: Record<string, unknown>;
        try {
          r = JSON.parse(line);
        } catch {
          continue;
        }
        const chat = typeof r.chat_id === "string" ? r.chat_id.match(PHONE_CHAT) : null;
        const q = typeof r.chat_name === "string" ? normName(r.chat_name) : "";
        if (chat && r.chat_type === "direct" && pending.has(q)) {
          found.set(q, chat[1]);
          pending.delete(q);
        }
      }
    } catch {
      // Unreadable file: look in the others.
    } finally {
      lines.close();
    }
  }

  if (cache.size > CACHE_MAX) cache.clear();
  for (const q of todo) cache.set(`${vault}\0${q}`, { phone: found.get(q) ?? null, at: now });
  return found;
}
