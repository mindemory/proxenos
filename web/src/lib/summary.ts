// What the landing page shows: a few counts from the vault and the network's shape. Server
// only. Each part is cheap: the memory count comes from the index's per-file totals, and the
// network picture is laid out once per version of people.json and kept in memory.

import { promises as fs } from "node:fs";
import path from "node:path";

import { layoutConstellation, type Constellation } from "./constellation";
import { isToSend } from "./drafts";
import { memoryCount } from "./memory";
import type { SummaryResponse } from "./types";
import { getDrafts, getGraphThumb, nowIso, sourceSyncs, vaultInfo, vaultPath } from "./vault";

/** How many of the busiest connected people the picture draws. */
const CONSTELLATION_NODES = 160;
const CONSTELLATION_EDGES = 420;

let cached: { key: string; people: number | null; constellation: Constellation } | null = null;

async function network(vault: string): Promise<{ people: number | null; constellation: Constellation }> {
  const file = path.join(vault, "clones", "network", "people.json");
  let key = "none";
  try {
    const st = await fs.stat(file);
    key = `${file}:${st.mtimeMs}:${st.size}`;
  } catch {
    // No people index: nothing to draw.
  }
  if (cached?.key === key) return cached;

  const thumb = await getGraphThumb(CONSTELLATION_NODES);
  const index = new Map(thumb.nodes.map((n, i) => [n.id, i]));
  const edges = thumb.links
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, CONSTELLATION_EDGES)
    .map((l) => [index.get(l.source)!, index.get(l.target)!] as [number, number]);
  const constellation = layoutConstellation(
    thumb.nodes.map((n) => n.interactions),
    edges,
  );
  cached = { key, people: thumb.exists ? thumb.people : null, constellation };
  return cached;
}

export async function getSummary(): Promise<SummaryResponse> {
  const vault = vaultPath();
  const [info, net, drafts, syncs] = await Promise.all([
    vaultInfo(vault),
    network(vault),
    getDrafts(),
    sourceSyncs(vault),
  ]);
  let memories: number | null = null;
  try {
    memories = memoryCount();
  } catch {
    // Unreadable index (or an old Node): leave the count out rather than fail the page.
  }
  const synced = syncs.filter((s) => s.lastSync !== null);
  const lastSync = synced.reduce<string | null>(
    (best, s) => (best === null || Date.parse(s.lastSync!) > Date.parse(best) ? s.lastSync : best),
    null,
  );
  return {
    now: nowIso(),
    vault: info,
    memories,
    people: net.people,
    drafts: drafts.exists ? drafts.drafts.filter((d) => isToSend(d, Date.now())).length : null,
    sources: synced.length,
    lastSync,
    constellation: net.constellation,
  };
}
