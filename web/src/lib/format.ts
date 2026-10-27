// Small display helpers. Relative times take the server's "now" from the API
// response, so rendering stays pure.

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00Z` : iso);
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
};

export function sourceLabel(source: string): string {
  if (source.startsWith("rss:")) return source.slice(4).replace(/^www\./, "");
  return SOURCE_LABELS[source] ?? source;
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
