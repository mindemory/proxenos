// Server side of the Offers page. Import only from route handlers.
//
// A comparison is started by handing its goal to `proxenos clone offers -` as one JSON line on its
// stdin (never its arguments: it says what the user is choosing between), and the page follows it
// by reading clones/offers/<slug>.json, which the command writes when it begins and when it's done.
// Each file is read field by field, so nothing else in it reaches the page. Each row's reply is
// read from its errand, as the Errands page reads it, so what's sent there shows here too.

import { constants as fsConstants, promises as fs } from "node:fs";
import path from "node:path";

import { OFFERS_MS, latestJob, startJob, type Job } from "./connect";
import { getErrand } from "./errands";
import {
  OFFERS_MAX_GOAL,
  OFFERS_MONTHS,
  type ErrandJob,
  type OfferPerson,
  type OfferPrice,
  type OfferReply,
  type OfferRow,
  type Offers,
  type OffersRequest,
  type OffersResponse,
  type OffersStatus,
} from "./types";
import { nowIso, readJsonFile, vaultInfo, vaultPath } from "./vault";

const MAX_COMPARISONS = 20;
const MAX_ROWS = 12;
const MAX_BYTES = 2 * 1024 * 1024;
// A comparison's file name, as the command makes it from the goal's words.
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const PROJECT_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const STATUSES: readonly OffersStatus[] = ["working", "done", "failed"];

// ── Requests ────────────────────────────────────────────────────────────────

/** A comparison asked for in a request's body, or why it can't be started. */
export function parseOffers(body: Record<string, unknown>): OffersRequest | { error: string } {
  const goal = typeof body.goal === "string" ? body.goal.trim() : "";
  if (!goal) return { error: "Say what the offers are for." };
  if (goal.length > OFFERS_MAX_GOAL) return { error: `Keep it to ${OFFERS_MAX_GOAL} characters.` };
  const months = body.months ?? 12;
  if (typeof months !== "number" || !(OFFERS_MONTHS as readonly number[]).includes(months)) {
    return { error: `months must be one of ${OFFERS_MONTHS.join(", ")}.` };
  }
  const project = body.project ?? null;
  if (project !== null && (typeof project !== "string" || !PROJECT_ID.test(project))) {
    return { error: "project must be a project's id." };
  }
  return { goal, months, project };
}

/** Compare the offers for a goal. Null when a comparison is already being made. */
export function startOffers(request: OffersRequest): Promise<Job | null> {
  const line = JSON.stringify({ goal: request.goal, months: request.months, project: request.project, draft: true });
  return startJob("offers", ["clone", "offers", "-"], null, line + "\n");
}

// ── The comparisons ─────────────────────────────────────────────────────────

function str(v: unknown, limit = 2000): string {
  return typeof v === "string" ? v.slice(0, limit) : "";
}

function strings(v: unknown, limit: number): string[] {
  return Array.isArray(v) ? v.filter((s): s is string => typeof s === "string" && s.trim() !== "").slice(0, limit) : [];
}

function toPrice(raw: unknown): OfferPrice {
  const r = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return { what: str(r.what, 300), price: str(r.price, 300) };
}

function toPerson(raw: unknown): OfferPerson | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const name = str(r.name, 120).trim();
  return name ? { name, role: str(r.role, 300) } : null;
}

/** A row's reply, as its errand stands now: null when it has none, or the errand is gone. */
async function toReply(id: unknown): Promise<OfferReply | null> {
  if (typeof id !== "string") return null;
  const errand = await getErrand(id);
  const message = errand?.messages[0];
  if (!errand || !message || errand.status === "dropped") return null;
  return {
    errand: errand.id,
    status: errand.status,
    to: message.to,
    channel: message.channel,
    address: message.address,
    subject: message.subject,
    body: message.body,
    state: message.state,
  };
}

async function toRow(raw: unknown): Promise<OfferRow | null> {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const key = str(r.key, 400);
  const name = str(r.name, 300).trim();
  if (!key || !name) return null;
  return {
    key,
    kind: r.kind === "org" ? "org" : "person",
    name,
    channel: str(r.channel, 40) || "email",
    people: Array.isArray(r.people) ? r.people.map(toPerson).filter((p): p is OfferPerson => p !== null).slice(0, 4) : [],
    address: str(r.address, 320),
    first: toPrice(r.first),
    whole: toPrice(r.whole),
    prices: Array.isArray(r.prices) ? r.prices.map(toPrice).filter((p) => p.price).slice(0, 6) : [],
    credited: str(r.credited, 300),
    terms: strings(r.terms, 6),
    missing: strings(r.missing, 6),
    last: str(r.last, 40),
    owes: r.owes === "them" ? "them" : "you",
    heard: typeof r.heard === "number" && Number.isInteger(r.heard) ? r.heard : 0,
    unconfirmed: strings(r.unconfirmed, 20),
    reply: await toReply(r.errand),
    error: str(r.error, 300) || null,
  };
}

async function toOffers(raw: unknown): Promise<Offers | null> {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const status = STATUSES.find((s) => s === r.status);
  const slug = str(r.slug, 80);
  if (!SLUG.test(slug) || !status) return null;
  const rows = Array.isArray(r.rows) ? await Promise.all(r.rows.slice(0, MAX_ROWS).map(toRow)) : [];
  return {
    slug,
    goal: str(r.goal, 600),
    created: str(r.created, 40),
    updated: str(r.updated, 40),
    months: typeof r.months === "number" ? r.months : 12,
    since: str(r.since, 40),
    project: str(r.project, 40),
    status,
    error: str(r.error, 300) || null,
    note: str(r.note, 4000),
    rows: rows.filter((row): row is OfferRow => row !== null),
  };
}

async function readPlainJson(file: string): Promise<unknown> {
  try {
    // O_NOFOLLOW: a file swapped for a symlink since the listing isn't followed either.
    const fh = await fs.open(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    try {
      const st = await fh.stat();
      if (!st.isFile() || st.size > MAX_BYTES) return null;
      return JSON.parse(await fh.readFile("utf8"));
    } finally {
      await fh.close();
    }
  } catch {
    return null;
  }
}

/** The projects a comparison can be added to the brief of, by id and name. */
async function projectsListed(vault: string): Promise<{ id: string; name: string }[]> {
  const raw = await readJsonFile(path.join(vault, "clones", "projects", "projects.json"));
  const listed = raw && typeof raw === "object" ? (raw as Record<string, unknown>).projects : null;
  if (!Array.isArray(listed)) return [];
  return listed.flatMap((p) => {
    if (!p || typeof p !== "object") return [];
    const { id, name } = p as Record<string, unknown>;
    return typeof id === "string" && PROJECT_ID.test(id) && typeof name === "string" && name.trim()
      ? [{ id, name: name.trim().slice(0, 120) }]
      : [];
  });
}

function toJob(job: Job | null): ErrandJob | null {
  return job && { state: job.state, message: job.message, started: job.started, finished: job.finished };
}

/** The comparisons, the newest first, and how the one being made stands. */
export async function getOffers(): Promise<OffersResponse> {
  const vault = vaultPath();
  const dir = path.join(vault, "clones", "offers");
  let names: string[] = [];
  try {
    names = (await fs.readdir(dir)).filter((n) => n.endsWith(".json") && SLUG.test(n.slice(0, -5)));
  } catch {
    // No comparisons yet.
  }
  const job = latestJob("offers");
  const comparisons: Offers[] = [];
  for (const name of names) {
    const offers = await toOffers(await readPlainJson(path.join(dir, name)));
    if (!offers) continue;
    // Still "working" with nothing making it: the page's command for it ended without saying so,
    // or (one started from the command line) it's been longer than a comparison may take.
    const updated = Date.parse(offers.updated);
    const ended =
      job !== null && job.state !== "running" && Date.parse(job.started) <= updated + 5000 && updated <= Date.parse(job.finished ?? "");
    const stale = Date.now() - updated > OFFERS_MS;
    if (offers.status === "working" && (ended || stale)) {
      offers.status = "failed";
      offers.error = (ended && job.state === "failed" && job.message) || "It didn't finish.";
    }
    comparisons.push(offers);
  }
  comparisons.sort((a, b) => b.updated.localeCompare(a.updated));
  return {
    now: nowIso(),
    vault: await vaultInfo(vault),
    comparisons: comparisons.slice(0, MAX_COMPARISONS),
    projects: await projectsListed(vault),
    job: toJob(job),
  };
}
