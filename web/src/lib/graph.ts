// The network as a graph: the people to draw, the ties between them, and a small
// force simulation that lays them out. Pure data and arithmetic, no DOM, so the
// canvas components stay about drawing and pointers.
//
// Limits: only the top GRAPH_MAX_NODES people are drawn, and only the strongest
// GRAPH_MAX_EDGES ties among them. The Python side already picks both (people.json's
// "core" and "edges"); this keeps an older or hand-edited file from drawing more.

import type { GraphThumb, Group, GroupKind, NetworkResponse, Person, Relation } from "./types";

// The same as GRAPH_PEOPLE and GRAPH_EDGES in src/twin/clones/network.py.
export const GRAPH_MAX_NODES = 600;
export const GRAPH_MAX_EDGES = 4000;

export interface GNode {
  idx: number;
  id: string;
  person: Person;
  r: number; // radius in world units, from interactions
  degree: number; // ties among the drawn edges
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx: number | null; // set while the node is dragged
  fy: number | null;
}

export interface GEdge {
  a: number;
  b: number;
  weight: number;
  contexts: string[];
  kinds: GroupKind[]; // kinds of the groups both people are in
}

export interface GGroup {
  group: Group;
  members: number[]; // node indexes
}

export interface GraphModel {
  nodes: GNode[];
  edges: GEdge[];
  groups: GGroup[];
  /** Per node: who it's tied to, with the edge. Strongest first. */
  adj: { other: number; edge: number }[][];
  /** Per node: the groups it's in (indexes into groups). */
  nodeGroups: number[][];
  byId: Map<string, number>;
}

/** Interactions and recency, as the Python side ranks them. Only used when "core" is missing. */
function score(p: Person, now: number): number {
  const last = p.last_seen ? Date.parse(p.last_seen) : NaN;
  const ageDays = Number.isNaN(last) ? 3650 : Math.max(0, (now - last) / 86_400_000);
  return Math.log2(2 + p.interactions) * Math.pow(0.5, ageDays / 365);
}

export const nodeRadius = (interactions: number) => 2.6 + Math.min(10, 1.15 * Math.log2(1 + interactions));

export function buildGraph(people: NetworkResponse["people"], now: string): GraphModel {
  const list = new Map(people.list.map((p) => [p.id, p]));
  let ids = [...new Set(people.core)].filter((id) => list.has(id));
  if (ids.length === 0 && list.size > 0) {
    const t = Date.parse(now) || Date.now();
    ids = [...list.values()]
      .sort((a, b) => score(b, t) - score(a, t))
      .slice(0, GRAPH_MAX_NODES)
      .map((p) => p.id);
  }
  ids = ids.slice(0, GRAPH_MAX_NODES);

  // Start on a sunflower spiral, strongest in the middle, so a layout is the same every time.
  const nodes: GNode[] = ids.map((id, idx) => {
    const person = list.get(id)!;
    const radius = 14 * Math.sqrt(0.5 + idx);
    const angle = idx * Math.PI * (3 - Math.sqrt(5));
    return {
      idx,
      id,
      person,
      r: nodeRadius(person.interactions),
      degree: 0,
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
      vx: 0,
      vy: 0,
      fx: null,
      fy: null,
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n.idx]));

  const groups: GGroup[] = [];
  const nodeGroups: number[][] = nodes.map(() => []);
  for (const group of people.groups) {
    const members = [...new Set(group.members)].map((id) => byId.get(id)).filter((i): i is number => i !== undefined);
    if (members.length < 2) continue;
    const gi = groups.push({ group, members }) - 1;
    for (const m of members) nodeGroups[m].push(gi);
  }

  const edges: GEdge[] = [];
  const adj: { other: number; edge: number }[][] = nodes.map(() => []);
  const seen = new Set<string>();
  for (const e of people.edges) {
    if (edges.length >= GRAPH_MAX_EDGES) break;
    const a = byId.get(e.source);
    const b = byId.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const shared = nodeGroups[a].filter((g) => nodeGroups[b].includes(g));
    const kinds = [...new Set(shared.map((g) => groups[g].group.kind))];
    const ei = edges.push({ a, b, weight: e.weight, contexts: e.contexts, kinds }) - 1;
    adj[a].push({ other: b, edge: ei });
    adj[b].push({ other: a, edge: ei });
    nodes[a].degree++;
    nodes[b].degree++;
  }
  for (const list of adj) list.sort((x, y) => edges[y.edge].weight - edges[x.edge].weight);

  return { nodes, edges, groups, adj, nodeGroups, byId };
}

/** The home thumbnail's graph: the same model, from names-free data, with no groups. */
export function buildThumbGraph(thumb: GraphThumb): GraphModel {
  const nodes: GNode[] = thumb.nodes.map((n, idx) => {
    const radius = 10 * Math.sqrt(0.5 + idx);
    const angle = idx * Math.PI * (3 - Math.sqrt(5));
    const person: Person = {
      id: n.id,
      name: "",
      relation: n.relation,
      sources: [],
      interactions: n.interactions,
      last_seen: null,
      context: "",
      topics: [],
      org: null,
    };
    return {
      idx,
      id: n.id,
      person,
      r: 2 + Math.min(5, 0.9 * Math.log2(1 + n.interactions)),
      degree: 0,
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
      vx: 0,
      vy: 0,
      fx: null,
      fy: null,
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n.idx]));
  const edges: GEdge[] = [];
  const adj: { other: number; edge: number }[][] = nodes.map(() => []);
  for (const l of thumb.links) {
    const a = byId.get(l.source);
    const b = byId.get(l.target);
    if (a === undefined || b === undefined || a === b) continue;
    const ei = edges.push({ a, b, weight: l.weight, contexts: [], kinds: [] }) - 1;
    adj[a].push({ other: b, edge: ei });
    adj[b].push({ other: a, edge: ei });
    nodes[a].degree++;
    nodes[b].degree++;
  }
  return { nodes, edges, groups: [], adj, nodeGroups: nodes.map(() => []), byId };
}

// ── Filters ─────────────────────────────────────────────────────────────────

export interface Filters {
  relations: ReadonlySet<Relation>; // none: every relation
  kinds: ReadonlySet<GroupKind>; // none: every kind of tie
  hideUnconnected: boolean;
}

export interface Visibility {
  node: boolean[];
  edge: boolean[];
  /** With a kind filter on: whether the node has a tie of that kind. Without: always true. */
  active: boolean[];
}

export function applyFilters(g: GraphModel, f: Filters): Visibility {
  const relationOk = (n: GNode) => f.relations.size === 0 || f.relations.has(n.person.relation);
  const edge = g.edges.map(
    (e) =>
      relationOk(g.nodes[e.a]) &&
      relationOk(g.nodes[e.b]) &&
      (f.kinds.size === 0 || e.kinds.some((k) => f.kinds.has(k))),
  );
  const tied = g.nodes.map(() => false);
  g.edges.forEach((e, i) => {
    if (edge[i]) tied[e.a] = tied[e.b] = true;
  });
  const node = g.nodes.map((n, i) => relationOk(n) && (!f.hideUnconnected || tied[i]));
  // An edge needs both ends on screen.
  g.edges.forEach((e, i) => {
    if (!node[e.a] || !node[e.b]) edge[i] = false;
  });
  const active = g.nodes.map((_, i) => f.kinds.size === 0 || tied[i]);
  return { node, edge, active };
}

// ── Search ──────────────────────────────────────────────────────────────────

/** Text as search compares it: no accents, no case. */
export const fold = (s: string) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();

/** Nodes matching a search, name starts first, then names containing it, then org and context. */
export function searchNodes(g: GraphModel, query: string, limit = 8): number[] {
  const q = fold(query.trim());
  if (!q) return [];
  const ranked: { idx: number; rank: number }[] = [];
  for (const n of g.nodes) {
    const name = fold(n.person.name);
    let rank = -1;
    if (name.startsWith(q) || name.split(" ").some((w) => w.startsWith(q))) rank = 0;
    else if (name.includes(q)) rank = 1;
    else if (fold(`${n.person.org ?? ""} ${n.person.context}`).includes(q)) rank = 2;
    if (rank >= 0) ranked.push({ idx: n.idx, rank });
  }
  ranked.sort((a, b) => a.rank - b.rank || g.nodes[b.idx].person.interactions - g.nodes[a.idx].person.interactions);
  return ranked.slice(0, limit).map((r) => r.idx);
}

// ── Layout ──────────────────────────────────────────────────────────────────

interface Link {
  a: number;
  b: number;
  dist: number;
  strength: number;
  bias: number;
}

/**
 * A small force simulation: ties are springs (shorter and firmer the more
 * contexts two people share), every pair repels, overlapping nodes push apart,
 * and a weak pull toward the middle keeps strangers from drifting off.
 * Same ideas as d3-force, with the repulsion done pair by pair: for the 600
 * nodes drawn that is 180k pairs a tick, about a millisecond.
 */
export class Simulation {
  alpha = 1;
  private links: Link[];
  private loose: number[]; // people with no tie
  private tied: number[];
  private ring = 0; // radius of the ring the untied people sit on
  private static readonly DECAY = 1 - Math.pow(0.001, 1 / 300);
  private static readonly MIN_ALPHA = 0.002;
  private static readonly PULL = 0.035; // toward the middle

  constructor(
    private nodes: GNode[],
    edges: GEdge[],
  ) {
    this.links = edges.map((e) => {
      const da = nodes[e.a].degree;
      const db = nodes[e.b].degree;
      return {
        a: e.a,
        b: e.b,
        dist: 34 + 60 / Math.sqrt(e.weight),
        strength: 1 / Math.min(da, db),
        bias: da / (da + db),
      };
    });
    this.loose = nodes.filter((n) => n.degree === 0).map((n) => n.idx);
    this.tied = nodes.filter((n) => n.degree > 0).map((n) => n.idx);
  }

  get settled(): boolean {
    return this.alpha < Simulation.MIN_ALPHA;
  }

  reheat(alpha = 0.35) {
    this.alpha = Math.max(this.alpha, alpha);
  }

  /** Hold a node at a point, as while it is dragged. */
  pin(idx: number, x: number, y: number) {
    const n = this.nodes[idx];
    n.fx = x;
    n.fy = y;
  }

  unpin(idx: number) {
    const n = this.nodes[idx];
    n.fx = n.fy = null;
  }

  tick() {
    const { nodes, links } = this;
    this.alpha -= this.alpha * Simulation.DECAY;
    const alpha = this.alpha;

    for (const l of links) {
      const s = nodes[l.a];
      const t = nodes[l.b];
      let x = t.x + t.vx - s.x - s.vx || 1e-6;
      let y = t.y + t.vy - s.y - s.vy || 1e-6;
      const d = Math.sqrt(x * x + y * y);
      const k = ((d - l.dist) / d) * alpha * l.strength;
      x *= k;
      y *= k;
      t.vx -= x * l.bias;
      t.vy -= y * l.bias;
      s.vx += x * (1 - l.bias);
      s.vy += y * (1 - l.bias);
    }

    const n = nodes.length;
    const MAX2 = 420 * 420;
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 > MAX2) continue;
        if (d2 === 0) {
          dx = 1e-3 * (i - j);
          dy = 1e-3;
          d2 = dx * dx + dy * dy;
        }
        const d = Math.sqrt(d2);
        // Repulsion falls off as 1/d, as in d3's many-body force.
        const w = (-62 * alpha) / Math.max(d2, 100);
        a.vx += dx * w;
        a.vy += dy * w;
        b.vx -= dx * w;
        b.vy -= dy * w;
        const gap = a.r + b.r + 3;
        if (d < gap) {
          const push = ((gap - d) / d) * 0.5;
          a.vx -= dx * push;
          a.vy -= dy * push;
          b.vx += dx * push;
          b.vy += dy * push;
        }
      }
    }

    // People with no tie sit on a ring around the ones who have them, so the ties stay readable.
    if (this.tied.length > 0 && this.loose.length > 0) {
      const radii = this.tied.map((i) => Math.hypot(nodes[i].x, nodes[i].y)).sort((a, b) => a - b);
      const target = radii[Math.floor(radii.length * 0.92)] + 60;
      this.ring = this.ring === 0 ? target : this.ring + (target - this.ring) * 0.06;
      for (const i of this.loose) {
        const p = nodes[i];
        const d = Math.hypot(p.x, p.y) || 1;
        const k = ((d - this.ring) / d) * 0.12 * alpha;
        p.vx -= p.x * k;
        p.vy -= p.y * k;
      }
    }

    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      if (this.tied.length === 0 || p.degree > 0) {
        p.vx -= p.x * Simulation.PULL * alpha;
        p.vy -= p.y * Simulation.PULL * alpha;
      }
      if (p.fx !== null && p.fy !== null) {
        p.x = p.fx;
        p.y = p.fy;
        p.vx = p.vy = 0;
      } else {
        p.vx *= 0.6;
        p.vy *= 0.6;
        p.x += p.vx;
        p.y += p.vy;
      }
    }
  }
}

// ── View ────────────────────────────────────────────────────────────────────

/** Screen position = world position * k + (x, y). */
export interface View {
  k: number;
  x: number;
  y: number;
}

export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 6;

export function clampZoom(k: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));
}

/** The view that shows the given nodes with some margin, centred in the free part of a w by h box. */
export function fitView(
  nodes: GNode[],
  w: number,
  h: number,
  options: { pad?: number; inset?: { left?: number; right?: number; bottom?: number } } = {},
): View {
  const pad = options.pad ?? 36;
  const left = options.inset?.left ?? 0;
  const right = options.inset?.right ?? 0;
  const bottom = options.inset?.bottom ?? 0;
  if (nodes.length === 0) return { k: 1, x: w / 2, y: h / 2 };
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const n of nodes) {
    x0 = Math.min(x0, n.x - n.r);
    y0 = Math.min(y0, n.y - n.r);
    x1 = Math.max(x1, n.x + n.r);
    y1 = Math.max(y1, n.y + n.r);
  }
  const availW = Math.max(80, w - left - right - pad * 2);
  const availH = Math.max(80, h - bottom - pad * 2);
  const k = clampZoom(Math.min(availW / Math.max(x1 - x0, 1), availH / Math.max(y1 - y0, 1), 2.5));
  return {
    k,
    x: left + (w - left - right) / 2 - ((x0 + x1) / 2) * k,
    y: (h - bottom) / 2 - ((y0 + y1) / 2) * k,
  };
}
