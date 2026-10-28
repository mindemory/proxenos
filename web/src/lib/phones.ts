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
const CACHE_MS = 10 * 60 * 1000;
const CACHE_MAX = 2000;

const cache = new Map<string, { phone: string | null; at: number }>();

/** The number for each chat name, matched whole and without regard to case. */
export async function findPhones(vault: string, names: readonly string[]): Promise<Map<string, string>> {
  const found = new Map<string, string>();
  const todo = new Set<string>();
  const now = Date.now();
  for (const name of names) {
    const q = normName(name);
    if (!q) continue;
    const hit = cache.get(`${vault}\0${q}`);
    if (hit && now - hit.at < CACHE_MS) {
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
