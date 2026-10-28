// Shared by the server (lib/memory.ts) and the browser (components/memory/Marked.tsx).

/**
 * Around each matched word in a snippet. The indexer strips both characters from every text it
 * stores, so they can only have come from the search itself.
 */
export const MARK_START = "\u0002";
export const MARK_END = "\u0003";

/** A snippet as plain text, marks removed. */
export function plain(snippet: string): string {
  return snippet.replaceAll(MARK_START, "").replaceAll(MARK_END, "");
}

/** Whether a text is the same as another once marks are gone and case and spacing are ignored. */
export function sameText(a: string, b: string): boolean {
  const norm = (s: string) => plain(s).replace(/[\s…]+/g, " ").trim().toLowerCase();
  return norm(a) === norm(b);
}

/** A time-of-day-less stamp: dates, all-day events and monthly summaries sit at midnight UTC. */
export function hasTime(ts: string): boolean {
  return !ts.endsWith("T00:00:00Z");
}

/** The calendar day a record belongs to: its date as written when it has no time, else local. */
export function dayOf(ts: string): string {
  if (!hasTime(ts)) return ts.slice(0, 10);
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 10);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
