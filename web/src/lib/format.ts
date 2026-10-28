// Small display helpers. Relative times take the server's "now" from the API
// response, so rendering stays pure.

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // A bare date is a calendar day, not an instant: read it as local midnight so
  // "2026-10-25" shows as Oct 25 in every time zone.
  const day = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const d = day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(iso: string | null | undefined, now: string): string {
  const d = parse(iso);
  const n = parse(now);
  if (!d || !n) return "never";
  const s = Math.max(0, (n.getTime() - d.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 60) return `${Math.floor(s / 86400)}d ago`;
  return `${Math.floor(s / (86400 * 30))} mo ago`;
}

export function hoursSince(iso: string | null | undefined, now: string): number {
  const d = parse(iso);
  const n = parse(now);
  if (!d || !n) return Infinity;
  return (n.getTime() - d.getTime()) / 3_600_000;
}

export function formatDate(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** "Oct 27", with the year only when it differs from `now`'s. */
export function shortDate(iso: string | null | undefined, now?: string): string {
  const d = parse(iso);
  if (!d) return "";
  const n = parse(now);
  const sameYear = !n || n.getFullYear() === d.getFullYear();
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) });
}

/** "Tuesday, October 27" in the reader's time zone. */
export function longDay(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "";
  return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}

/** "Good morning" / "Good afternoon" / "Good evening" by the reader's clock at `now`. */
export function greeting(now: string): string {
  const d = parse(now);
  const h = d ? d.getHours() : 12;
  if (h >= 5 && h < 12) return "Good morning";
  if (h >= 12 && h < 17) return "Good afternoon";
  return "Good evening";
}

/** Calendar date (YYYY-MM-DD) of an instant in the reader's time zone. */
export function localDay(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Whole calendar days from `today` to `day`, both YYYY-MM-DD. */
export function daysBetween(today: string, day: string): number {
  return Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

export function formatDateTime(iso: string | null | undefined): string {
  const d = parse(iso);
  if (!d) return "";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const SOURCE_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  openalex: "OpenAlex",
  biorxiv: "bioRxiv",
  hn: "Hacker News",
  whatsapp: "WhatsApp",
  slack: "Slack",
  email: "Email",
  spotify: "Spotify",
  strava: "Strava",
  twitter: "Twitter",
  linkedin: "LinkedIn",
  instagram: "Instagram",
  bluesky: "Bluesky",
  website: "Website",
  mentions: "Mentions",
  calendar: "Calendar",
};

export function sourceLabel(source: string): string {
  if (source.startsWith("rss:")) return source.slice(4).replace(/^www\./, "");
  return SOURCE_LABELS[source] ?? source;
}

/** "a", "a and b", "a, b and c". */
export function joinAnd(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? "";
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/**
 * One line about how fresh the raw sources are, grouped by calendar day:
 * "WhatsApp and Email synced today, Spotify yesterday, Strava 70 days ago."
 */
export function freshnessLine(sources: { kind: string; lastSync: string | null }[], now: string): string {
  const today = localDay(now);
  const groups = new Map<number, string[]>();
  const never: string[] = [];
  for (const s of sources) {
    const label = sourceLabel(s.kind);
    if (!s.lastSync) {
      never.push(label);
      continue;
    }
    const ago = Math.max(0, -daysBetween(today, localDay(s.lastSync)));
    groups.set(ago, [...(groups.get(ago) ?? []), label]);
  }
  const when = (d: number) => (d === 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`);
  const parts = [...groups]
    .sort((a, b) => a[0] - b[0])
    .map(([d, names], i) => `${joinAnd(names)} ${i === 0 ? "synced " : ""}${when(d)}`);
  if (never.length) parts.push(`${joinAnd(never)} not synced yet`);
  return parts.length ? `${parts.join(", ")}.` : "";
}

/** How fresh a source's last sync is: a label, and Tailwind classes for its dot and text. */
export function freshness(lastSync: string | null, now: string): { label: string; dot: string; text: string } {
  const h = hoursSince(lastSync, now);
  if (h < 6) return { label: "Fresh", dot: "bg-ok-ink", text: "text-ok-ink" };
  if (h < 72) return { label: "Behind", dot: "bg-warn-ink", text: "text-warn-ink" };
  if (h < Infinity) return { label: "Stale", dot: "bg-bad-ink", text: "text-bad-ink" };
  return { label: "Never", dot: "bg-muted/60", text: "text-muted" };
}

export function percent(score: number): number {
  return Math.round(score * 100);
}

export function authorLine(authors: string[] | null, max = 4): string {
  if (!authors || authors.length === 0) return "";
  const shown = authors.slice(0, max).join(", ");
  return authors.length > max ? `${shown} et al.` : shown;
}

/** "open_questions.md" -> "Open questions", "CHANGELOG.md" -> "Changelog". */
export function fileTitle(name: string): string {
  const base = name.replace(/\.md$/i, "").replace(/[_-]+/g, " ").toLowerCase();
  return base.charAt(0).toUpperCase() + base.slice(1);
}
