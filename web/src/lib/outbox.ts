// The outbox's rules: their defaults and limits, how one edit is checked and applied, and how
// the files the sync writes (state.json, log.jsonl) are read when they can't be trusted to be
// well formed. No file access, so the server and the page share it.

import { channelLabel } from "./drafts";
import {
  OUTBOX_CHANNELS,
  type OutboxChannel,
  type OutboxChannelRule,
  type OutboxLogEntry,
  type OutboxQueued,
  type OutboxRuleEdit,
  type OutboxRules,
  type OutboxState,
} from "./types";

export const OUTBOX_LIMITS = {
  dailyLimit: { min: 1, max: 50 },
  closeness: { min: 0.5, max: 1 },
  measured: { min: 1, max: 100 },
} as const;

/** How many log lines the page is given. */
export const OUTBOX_LOG_SHOWN = 50;

const MAX_QUEUE = 200;

const DEFAULT_CHANNEL: OutboxChannelRule = { on: false, min_closeness: 0.9, min_measured: 5 };

/** Everything off, and a channel must have been sent as drafted nearly always, five times over. */
export function defaultOutboxRules(): OutboxRules {
  const channels = Object.fromEntries(OUTBOX_CHANNELS.map((c) => [c, { ...DEFAULT_CHANNEL }]));
  return { enabled: false, daily_limit: 10, channels: channels as Record<OutboxChannel, OutboxChannelRule> };
}

const record = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
const text = (v: unknown): string | null => (typeof v === "string" ? v : null);
const isInt = (v: unknown, min: number, max: number): v is number =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max;
const isNum = (v: unknown, min: number, max: number): v is number =>
  typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;

/**
 * rules.json as the page shows it: a switch counts as on only when it is exactly true, and a
 * number that is missing, malformed or outside what the page itself would save falls back to its
 * default, which is the stricter choice. Channels the page doesn't know are dropped.
 */
export function outboxRules(raw: unknown): OutboxRules {
  const rules = defaultOutboxRules();
  const r = record(raw);
  if (!r) return rules;
  rules.enabled = r.enabled === true;
  if (isInt(r.daily_limit, OUTBOX_LIMITS.dailyLimit.min, OUTBOX_LIMITS.dailyLimit.max)) rules.daily_limit = r.daily_limit;
  const channels = record(r.channels);
  for (const ch of OUTBOX_CHANNELS) {
    const c = record(channels?.[ch]);
    if (!c) continue;
    const rule = rules.channels[ch];
    rule.on = c.on === true;
    if (isNum(c.min_closeness, OUTBOX_LIMITS.closeness.min, OUTBOX_LIMITS.closeness.max)) rule.min_closeness = c.min_closeness;
    if (isInt(c.min_measured, OUTBOX_LIMITS.measured.min, OUTBOX_LIMITS.measured.max)) rule.min_measured = c.min_measured;
  }
  return rules;
}

/**
 * One edit to the rules, checked strictly: exactly one of "enabled", "daily_limit" or "channel",
 * no other field, and every value of the right type and inside its limits.
 */
export function parseOutboxEdit(body: Record<string, unknown>): { edit: OutboxRuleEdit } | { error: string } {
  const keys = Object.keys(body);
  const main = ["enabled", "daily_limit", "channel"].filter((k) => keys.includes(k));
  if (main.length !== 1) return { error: 'send one change: "enabled", "daily_limit" or "channel"' };
  const extra = keys.filter((k) => !["enabled", "daily_limit", "channel", "on", "min_closeness", "min_measured"].includes(k));
  if (extra.length > 0) return { error: "unknown field" };

  if (main[0] === "enabled") {
    if (keys.length !== 1 || typeof body.enabled !== "boolean") return { error: "enabled must be true or false, on its own" };
    return { edit: { enabled: body.enabled } };
  }
  if (main[0] === "daily_limit") {
    const { min, max } = OUTBOX_LIMITS.dailyLimit;
    if (keys.length !== 1 || !isInt(body.daily_limit, min, max)) {
      return { error: `daily_limit must be a whole number from ${min} to ${max}, on its own` };
    }
    return { edit: { daily_limit: body.daily_limit } };
  }

  const channel = body.channel;
  if (typeof channel !== "string" || !OUTBOX_CHANNELS.includes(channel as OutboxChannel)) {
    return { error: `channel must be one of ${OUTBOX_CHANNELS.join(", ")}` };
  }
  const edit: { channel: OutboxChannel; on?: boolean; min_closeness?: number; min_measured?: number } = {
    channel: channel as OutboxChannel,
  };
  if ("on" in body) {
    if (typeof body.on !== "boolean") return { error: "on must be true or false" };
    edit.on = body.on;
  }
  if ("min_closeness" in body) {
    const { min, max } = OUTBOX_LIMITS.closeness;
    if (!isNum(body.min_closeness, min, max)) return { error: `min_closeness must be a number from ${min} to ${max}` };
    edit.min_closeness = body.min_closeness;
  }
  if ("min_measured" in body) {
    const { min, max } = OUTBOX_LIMITS.measured;
    if (!isInt(body.min_measured, min, max)) return { error: `min_measured must be a whole number from ${min} to ${max}` };
    edit.min_measured = body.min_measured;
  }
  if (Object.keys(edit).length === 1) return { error: "say what to change: on, min_closeness or min_measured" };
  return { edit };
}

/** The rules with one checked edit applied. */
export function applyOutboxEdit(rules: OutboxRules, edit: OutboxRuleEdit): OutboxRules {
  if ("enabled" in edit) return { ...rules, enabled: edit.enabled };
  if ("daily_limit" in edit) return { ...rules, daily_limit: edit.daily_limit };
  const { channel, ...change } = edit;
  return { ...rules, channels: { ...rules.channels, [channel]: { ...rules.channels[channel], ...change } } };
}

/** state.json, keeping only what is well formed; null when it isn't an object at all. */
export function outboxState(raw: unknown): OutboxState | null {
  const r = record(raw);
  if (!r) return null;

  // Only the channels the page can set rules for. A route that isn't a name counts as none: no
  // way to send is the safe reading.
  const routes: OutboxState["routes"] = {};
  const closeness: OutboxState["closeness"] = {};
  const earned: OutboxState["earned"] = {};
  const rawRoutes = record(r.routes);
  const rawCloseness = record(r.closeness);
  const rawEarned = record(r.earned);
  for (const ch of OUTBOX_CHANNELS) {
    if (rawRoutes && ch in rawRoutes) {
      const v = rawRoutes[ch];
      routes[ch] = typeof v === "string" && v.trim() ? v.trim().slice(0, 40) : null;
    }
    const s = record(rawCloseness?.[ch]);
    if (s && isInt(s.n, 0, Number.MAX_SAFE_INTEGER) && isNum(s.mean, 0, 1)) closeness[ch] = { n: s.n, mean: s.mean };
    if (rawEarned && ch in rawEarned) earned[ch] = rawEarned[ch] === true;
  }

  const queue: OutboxQueued[] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(r.queue) ? r.queue : []) {
    const q = record(raw);
    const id = text(q?.draft_id);
    if (!q || !id || id.length > 256 || seen.has(id)) continue;
    seen.add(id);
    queue.push({
      draft_id: id,
      channel: text(q.channel) ?? "",
      to: (text(q.to) ?? "").slice(0, 200),
      queued_at: text(q.queued_at) ?? "",
      sends_at: text(q.sends_at) ?? "",
    });
    if (queue.length >= MAX_QUEUE) break;
  }

  return {
    generated: text(r.generated),
    routes,
    closeness,
    earned,
    queue,
    sent_today: isInt(r.sent_today, 0, Number.MAX_SAFE_INTEGER) ? r.sent_today : 0,
  };
}

/** The newest `limit` attempts from log.jsonl's lines, newest first. */
export function outboxLog(rows: readonly unknown[], limit = OUTBOX_LOG_SHOWN): OutboxLogEntry[] {
  const out: OutboxLogEntry[] = [];
  for (let i = rows.length - 1; i >= 0 && out.length < limit; i--) {
    const r = record(rows[i]);
    const id = text(r?.draft_id);
    if (!r || !id) continue;
    const ok = r.ok === true;
    out.push({
      draft_id: id,
      channel: text(r.channel) ?? "",
      to: (text(r.to) ?? "").slice(0, 200),
      at: text(r.at) ?? "",
      via: text(r.via),
      ok,
      error: ok ? null : (text(r.error)?.slice(0, 300) ?? null),
    });
  }
  return out;
}

/** Every draft id cancelled so far, from cancelled.jsonl's lines. */
export function cancelledIds(rows: readonly unknown[]): string[] {
  const ids = new Set<string>();
  for (const raw of rows) {
    const id = text(record(raw)?.draft_id);
    if (id) ids.add(id);
  }
  return [...ids];
}

// ── Words for the panel ─────────────────────────────────────────────────────

const CHANNEL_LABELS: Record<OutboxChannel, string> = {
  email: "Email",
  whatsapp: "WhatsApp",
  slack: "Slack",
  instagram: "Instagram",
  messenger: "Messenger",
  x: "X",
  linkedin: "LinkedIn",
};

export function outboxChannelLabel(channel: string): string {
  return CHANNEL_LABELS[channel as OutboxChannel] ?? channelLabel(channel);
}

/** The chats Beeper reaches, so a channel with no way to send yet is told to add it there. */
const VIA_BEEPER: readonly string[] = ["whatsapp", "instagram", "messenger", "x", "linkedin"];

/** What to do about a channel that has no way to send yet, or "" when there is nothing to suggest. */
export function outboxRouteHint(channel: string): string {
  return VIA_BEEPER.includes(channel) ? `Add ${outboxChannelLabel(channel)} in Beeper to send from here` : "";
}

const ROUTE_LABELS: Record<string, string> = { apple_mail: "Apple Mail", beeper: "Beeper" };

/** How a route is named in the panel: "apple_mail" is "Apple Mail". */
export function outboxRouteLabel(route: string): string {
  if (ROUTE_LABELS[route]) return ROUTE_LABELS[route];
  const words = route.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : route;
}
