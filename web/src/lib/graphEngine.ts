// Draws a GraphModel on a canvas and handles the pointer: hover, click, drag a node,
// pan, wheel and pinch zoom. It owns everything that changes every frame (positions,
// the view, the animation loop), so React only sees the few things that matter to the
// page: which node was clicked and which one is under the cursor.

import {
  applyFilters,
  clampZoom,
  fitView,
  Simulation,
  type Filters,
  type GEdge,
  type GNode,
  type GraphModel,
  type View,
  type Visibility,
} from "./graph";
import { CLUSTER_FALLBACK, clusterSlot, type ClusterSlot } from "./clusters";
import type { Relation } from "./types";

export type ColourBy = "cluster" | "relation";

export interface HoverInfo {
  idx: number;
  x: number; // CSS pixels from the canvas's top left
  y: number;
}

export interface EngineOptions {
  /** Pointer input, labels and rings. Off for the thumbnail, which only draws. */
  interactive: boolean;
  /** Ticks to run before the first frame; the rest of the settling plays out on screen. */
  warm?: number;
  /** What fills a node: its cluster (with its relation as a ring) or its relation. */
  colourBy?: ColourBy;
  onSelect?: (idx: number | null) => void;
  onHover?: (hover: HoverInfo | null) => void;
}

interface Theme {
  relation: Record<Relation, string>;
  cluster: Record<ClusterSlot, string>;
  edge: string;
  edgeStrong: string;
  accent: string;
  ink: string;
  muted: string;
  bg: string;
  font: string;
}

const FALLBACK: Theme = {
  relation: { met: "#a3b1ff", know_of: "#6fd0cf", to_read: "#dba6f2" },
  cluster: CLUSTER_FALLBACK,
  edge: "#363b46",
  edgeStrong: "#4a5160",
  accent: "#a3b1ff",
  ink: "#ebe8e2",
  muted: "#9ca2ad",
  bg: "#0e1013",
  font: "system-ui, sans-serif",
};

function readTheme(): Theme {
  const style = getComputedStyle(document.documentElement);
  const get = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    relation: {
      met: get("--c-rel-met", FALLBACK.relation.met),
      know_of: get("--c-rel-know", FALLBACK.relation.know_of),
      to_read: get("--c-rel-read", FALLBACK.relation.to_read),
    },
    cluster: Object.fromEntries(
      (Object.keys(CLUSTER_FALLBACK) as (keyof typeof CLUSTER_FALLBACK)[]).map((slot) => [
        slot,
        get(`--c-cluster-${slot}`, CLUSTER_FALLBACK[slot]),
      ]),
    ) as Record<ClusterSlot, string>,
    edge: get("--c-line-strong", FALLBACK.edge),
    edgeStrong: get("--c-muted", FALLBACK.edgeStrong),
    accent: get("--c-accent", FALLBACK.accent),
    ink: get("--c-ink", FALLBACK.ink),
    muted: get("--c-muted", FALLBACK.muted),
    bg: get("--c-bg", FALLBACK.bg),
    font: getComputedStyle(document.body).fontFamily || FALLBACK.font,
  };
}

/** "#rrggbb" and an opacity as an rgba() string; anything else is returned as it came. */
function alpha(hex: string, a: number): string {
  const m = hex.match(/^#([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

const ALL: Filters = { relations: new Set(), kinds: new Set(), clusters: new Set(), hideUnconnected: false };

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export class GraphEngine {
  private ctx: CanvasRenderingContext2D;
  private sim: Simulation;
  private theme: Theme = readTheme();
  private view: View = { k: 1, x: 0, y: 0 };
  private width = 0;
  private height = 0;
  private dpr = 1;
  private raf: number | null = null;
  private userMoved = false;
  private anim: { from: View; to: View; t0: number; ms: number } | null = null;
  private dragging: number | null = null;

  private visibility: Visibility;
  private selected: number | null = null;
  private highlight: ReadonlySet<number> | null = null;
  private hovered: number | null = null;
  private colourBy: ColourBy;
  private inset = { left: 0, right: 0, bottom: 0 };

  private pointers = new Map<number, { x: number; y: number }>();
  private gesture: {
    mode: "node" | "pan" | "pinch";
    node: number | null;
    startX: number;
    startY: number;
    moved: boolean;
    dist: number;
  } | null = null;
  private resize: ResizeObserver;
  private cleanups: (() => void)[] = [];

  constructor(
    private canvas: HTMLCanvasElement,
    private model: GraphModel,
    private opts: EngineOptions,
  ) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas is not available");
    this.ctx = ctx;
    this.colourBy = opts.colourBy ?? "relation";
    this.visibility = applyFilters(model, ALL);
    this.sim = new Simulation(model.nodes, model.edges);

    // Most of the movement is done before the first frame; the rest plays out on screen.
    const settleNow = reducedMotion();
    const warm = settleNow ? 360 : (opts.warm ?? Math.min(120, Math.round(24000 / Math.max(model.nodes.length, 1)) + 30));
    for (let i = 0; i < warm && !(settleNow && this.sim.settled); i++) this.sim.tick();

    this.resize = new ResizeObserver(() => this.measure());
    this.resize.observe(canvas.parentElement ?? canvas);
    this.measure();
    if (opts.interactive) this.listen();
    this.view = this.fit();
    this.frame();
  }

  // ── What the page can change ──────────────────────────────────────────────

  setFilters(filters: Filters) {
    this.visibility = applyFilters(this.model, filters);
    this.frame();
  }

  setSelection(idx: number | null) {
    this.selected = idx;
    this.frame();
  }

  setHighlight(set: ReadonlySet<number> | null) {
    this.highlight = set;
    this.frame();
  }

  setColourBy(colourBy: ColourBy) {
    this.colourBy = colourBy;
    this.frame();
  }

  /** Space covered by panels on top of the canvas, so fit and focus centre in what's left. */
  setInset(inset: { left?: number; right?: number; bottom?: number }) {
    const next = { left: inset.left ?? 0, right: inset.right ?? 0, bottom: inset.bottom ?? 0 };
    const changed = next.left !== this.inset.left || next.right !== this.inset.right || next.bottom !== this.inset.bottom;
    this.inset = next;
    if (changed && !this.userMoved) this.moveTo(this.fit());
  }

  /** Bring a node to the middle of the free area, zoomed in at least a little. */
  focus(idx: number, inset?: { right?: number; bottom?: number }) {
    const n = this.model.nodes[idx];
    if (!n) return;
    // A panel about to open isn't in `this.inset` yet, so the caller can say what it will cover.
    const right = inset?.right ?? this.inset.right;
    const bottom = inset?.bottom ?? this.inset.bottom;
    const k = clampZoom(Math.min(Math.max(this.view.k, 1.3), 2.4));
    const cx = this.inset.left + (this.width - this.inset.left - right) / 2;
    const cy = (this.height - bottom) / 2;
    this.userMoved = true;
    this.moveTo({ k, x: cx - n.x * k, y: cy - n.y * k });
  }

  /** Show everything that's on screen. */
  fitAll() {
    this.userMoved = false;
    this.moveTo(this.fit(true));
  }

  zoomBy(factor: number) {
    this.userMoved = true;
    const cx = this.inset.left + (this.width - this.inset.left - this.inset.right) / 2;
    const cy = (this.height - this.inset.bottom) / 2;
    const k = clampZoom(this.view.k * factor);
    const to = {
      k,
      x: cx - ((cx - this.view.x) / this.view.k) * k,
      y: cy - ((cy - this.view.y) / this.view.k) * k,
    };
    this.moveTo(to);
  }

  dispose() {
    if (this.raf !== null) cancelAnimationFrame(this.raf);
    this.raf = null;
    this.resize.disconnect();
    for (const off of this.cleanups) off();
    this.cleanups = [];
  }

  // ── Geometry ──────────────────────────────────────────────────────────────

  private measure() {
    const box = (this.canvas.parentElement ?? this.canvas).getBoundingClientRect();
    this.width = Math.max(1, Math.floor(box.width));
    this.height = Math.max(1, Math.floor(box.height));
    this.dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    if (!this.userMoved) this.view = this.fit();
    this.frame();
  }

  private fit(onlyVisible = false): View {
    const nodes = onlyVisible ? this.model.nodes.filter((n) => this.visibility.node[n.idx]) : this.model.nodes;
    const pad = this.opts.interactive ? 40 : 10;
    return fitView(nodes, this.width, this.height, { pad, inset: this.inset });
  }

  private toWorld(sx: number, sy: number): { x: number; y: number } {
    return { x: (sx - this.view.x) / this.view.k, y: (sy - this.view.y) / this.view.k };
  }

  private moveTo(to: View) {
    if (reducedMotion()) {
      this.view = to;
      this.anim = null;
    } else {
      this.anim = { from: { ...this.view }, to, t0: performance.now(), ms: 420 };
    }
    this.frame();
  }

  private hit(sx: number, sy: number): number | null {
    const { x, y } = this.toWorld(sx, sy);
    let best: number | null = null;
    let bestD = Infinity;
    for (const n of this.model.nodes) {
      if (!this.visibility.node[n.idx]) continue;
      const reach = Math.max(n.r, 8 / this.view.k) + 2 / this.view.k;
      const d = (n.x - x) ** 2 + (n.y - y) ** 2;
      if (d <= reach * reach && d < bestD) {
        best = n.idx;
        bestD = d;
      }
    }
    return best;
  }

  // ── Loop ──────────────────────────────────────────────────────────────────

  /** Ask for a frame. Frames repeat only while something is still moving. */
  private frame() {
    if (this.raf === null) this.raf = requestAnimationFrame(() => this.step());
  }

  private step() {
    this.raf = null;
    let again = false;
    if (!this.sim.settled || this.dragging !== null) {
      this.sim.tick();
      again = true;
      if (!this.userMoved && this.anim === null) this.chase(this.fit());
    }
    if (this.anim) {
      const t = Math.min(1, (performance.now() - this.anim.t0) / this.anim.ms);
      const e = 1 - Math.pow(1 - t, 3);
      const { from, to } = this.anim;
      this.view = { k: from.k + (to.k - from.k) * e, x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e };
      if (t >= 1) this.anim = null;
      else again = true;
    }
    this.draw();
    if (again) this.frame();
  }

  /** Ease toward a target view; used to keep a settling layout in frame. */
  private chase(to: View) {
    const f = 0.12;
    this.view = {
      k: this.view.k + (to.k - this.view.k) * f,
      x: this.view.x + (to.x - this.view.x) * f,
      y: this.view.y + (to.y - this.view.y) * f,
    };
  }

  // ── Drawing ───────────────────────────────────────────────────────────────

  private draw() {
    const { ctx, model, theme, view, visibility } = this;
    const interactive = this.opts.interactive;
    const focusSet = this.focusSet();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.setTransform(this.dpr * view.k, 0, 0, this.dpr * view.k, this.dpr * view.x, this.dpr * view.y);
    ctx.lineCap = "round";

    // Edges, by thickness so each thickness is a single stroke.
    const buckets = new Map<string, GEdge[]>();
    const pxFor = (w: number) => Math.min(4.5, 0.7 + 0.8 * Math.sqrt(w));
    const zoomScale = Math.min(1.5, Math.max(0.8, Math.pow(view.k, 0.4)));
    for (let i = 0; i < model.edges.length; i++) {
      if (!visibility.edge[i]) continue;
      const e = model.edges[i];
      const incident = this.selected !== null && (e.a === this.selected || e.b === this.selected);
      const inFocus = focusSet === null ? true : focusSet.has(e.a) && focusSet.has(e.b);
      const style = incident ? "hot" : inFocus ? (focusSet === null ? "base" : "lit") : "dim";
      const key = `${style}:${Math.min(4, Math.round(pxFor(e.weight)))}`;
      const list = buckets.get(key);
      if (list) list.push(e);
      else buckets.set(key, [e]);
    }
    const order = ["dim", "base", "lit", "hot"];
    const sorted = [...buckets].sort((a, b) => order.indexOf(a[0].split(":")[0]) - order.indexOf(b[0].split(":")[0]));
    for (const [key, edges] of sorted) {
      const [style, px] = key.split(":");
      const colour =
        style === "hot"
          ? alpha(theme.accent, 0.9)
          : style === "lit"
            ? alpha(theme.edgeStrong, 0.7)
            : style === "dim"
              ? alpha(theme.edge, 0.18)
              : alpha(theme.edge, interactive ? 0.75 : 0.9);
      ctx.strokeStyle = colour;
      ctx.lineWidth = ((Number(px) || 1) * (style === "hot" ? 1.2 : 1) * zoomScale) / view.k;
      ctx.beginPath();
      for (const e of edges) {
        const a = model.nodes[e.a];
        const b = model.nodes[e.b];
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
      }
      ctx.stroke();
    }

    // Nodes: the least active first, so the busiest sit on top.
    const labels: GNode[] = [];
    for (let i = model.nodes.length - 1; i >= 0; i--) {
      const n = model.nodes[i];
      if (!visibility.node[i]) continue;
      const lit = focusSet === null ? visibility.active[i] : focusSet.has(i);
      const a = lit ? 1 : 0.16;
      const byCluster = this.colourBy === "cluster";
      ctx.globalAlpha = a;
      ctx.fillStyle = byCluster ? theme.cluster[clusterSlot(n.cluster)] : theme.relation[n.person.relation];
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
      if (interactive) {
        // By cluster, the relation still shows: as a ring, once a node is big enough to carry one.
        const ring = byCluster && n.r * view.k >= 3.5;
        ctx.lineWidth = (ring ? 1.6 : 1.2) / view.k;
        ctx.strokeStyle = ring ? theme.relation[n.person.relation] : alpha(theme.bg, 0.9);
        ctx.stroke();
        const isSel = i === this.selected;
        if (isSel || i === this.hovered) {
          ctx.globalAlpha = 1;
          ctx.lineWidth = (isSel ? 2.4 : 1.6) / view.k;
          ctx.strokeStyle = isSel ? theme.ink : alpha(theme.ink, 0.8);
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r + 3 / view.k, 0, Math.PI * 2);
          ctx.stroke();
        }
        if (lit && this.wantsLabel(n, focusSet)) labels.push(n);
      }
    }
    ctx.globalAlpha = 1;

    if (interactive && labels.length) this.drawLabels(labels);
  }

  private focusSet(): ReadonlySet<number> | null {
    if (this.highlight) return this.highlight;
    if (this.selected === null) return null;
    const set = new Set<number>([this.selected]);
    for (const { other } of this.model.adj[this.selected]) set.add(other);
    return set;
  }

  private wantsLabel(n: GNode, focus: ReadonlySet<number> | null): boolean {
    if (n.idx === this.selected || n.idx === this.hovered) return true;
    if (focus !== null) return focus.size <= 40 || n.r * this.view.k >= 7;
    return n.r * this.view.k >= 8.5 || (this.view.k >= 2.4 && n.r * this.view.k >= 4.2);
  }

  private drawLabels(nodes: GNode[]) {
    const { ctx, theme, view } = this;
    // Labels in screen pixels, whatever the zoom: the busiest first, skipping any that would overlap.
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.font = `500 11.5px ${theme.font}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const priority = (n: GNode) => (n.idx === this.selected ? 2 : n.idx === this.hovered ? 1 : 0);
    const ordered = [...nodes].sort((a, b) => priority(b) - priority(a) || b.r - a.r);
    for (const n of ordered) {
      const sx = n.x * view.k + view.x;
      const sy = n.y * view.k + view.y;
      if (sx < -80 || sy < -20 || sx > this.width + 80 || sy > this.height + 20) continue;
      const text = n.person.name;
      const w = ctx.measureText(text).width;
      const x0 = sx + n.r * view.k + 5;
      const box = { x0, y0: sy - 8, x1: x0 + w, y1: sy + 8 };
      const must = priority(n) > 0;
      if (!must && placed.some((p) => box.x0 < p.x1 + 4 && box.x1 > p.x0 - 4 && box.y0 < p.y1 && box.y1 > p.y0)) continue;
      placed.push(box);
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = alpha(theme.bg, 0.92);
      ctx.lineJoin = "round";
      ctx.strokeText(text, x0, sy);
      ctx.fillStyle = priority(n) > 0 ? theme.ink : alpha(theme.ink, 0.88);
      ctx.fillText(text, x0, sy);
    }
  }

  // ── Pointer ───────────────────────────────────────────────────────────────

  private listen() {
    const c = this.canvas;
    const on = <K extends keyof HTMLElementEventMap>(type: K, fn: (e: HTMLElementEventMap[K]) => void, opts?: AddEventListenerOptions) => {
      c.addEventListener(type, fn as EventListener, opts);
      this.cleanups.push(() => c.removeEventListener(type, fn as EventListener, opts));
    };
    on("pointerdown", (e) => this.down(e));
    on("pointermove", (e) => this.move(e));
    on("pointerup", (e) => this.up(e));
    on("pointercancel", (e) => this.up(e, true));
    on("pointerleave", () => this.hoverOver(null, 0, 0));
    on("wheel", (e) => this.wheel(e), { passive: false });
  }

  private local(e: PointerEvent | WheelEvent): { x: number; y: number } {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  private down(e: PointerEvent) {
    const p = this.local(e);
    try {
      this.canvas.setPointerCapture(e.pointerId);
    } catch {
      // A pointer that has already gone (or a synthetic one): the gesture still works.
    }
    this.pointers.set(e.pointerId, p);
    this.anim = null;
    if (this.pointers.size === 2) {
      this.release();
      this.gesture = { mode: "pinch", node: null, startX: p.x, startY: p.y, moved: true, dist: this.pinchDistance() };
      this.hoverOver(null, 0, 0);
      return;
    }
    const node = this.hit(p.x, p.y);
    this.gesture = { mode: node === null ? "pan" : "node", node, startX: p.x, startY: p.y, moved: false, dist: 0 };
  }

  private move(e: PointerEvent) {
    const p = this.local(e);
    const prev = this.pointers.get(e.pointerId);
    if (!this.gesture || !prev) {
      if (e.pointerType === "mouse") this.hoverOver(this.hit(p.x, p.y), p.x, p.y);
      return;
    }
    this.pointers.set(e.pointerId, p);
    const g = this.gesture;
    if (g.mode === "pinch" && this.pointers.size >= 2) {
      const d = this.pinchDistance();
      const [a, b] = [...this.pointers.values()];
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      if (g.dist > 0 && d > 0) this.zoomAt(mid.x, mid.y, d / g.dist);
      g.dist = d;
      this.userMoved = true;
      this.frame();
      return;
    }
    if (!g.moved && Math.hypot(p.x - g.startX, p.y - g.startY) < 4) return;
    g.moved = true;
    if (g.mode === "node" && g.node !== null) {
      const w = this.toWorld(p.x, p.y);
      if (this.dragging === null) {
        this.dragging = g.node;
        this.hoverOver(null, 0, 0);
      }
      this.sim.pin(g.node, w.x, w.y);
      this.sim.reheat(0.3);
    } else if (g.mode === "pan") {
      this.userMoved = true;
      this.view = { ...this.view, x: this.view.x + (p.x - prev.x), y: this.view.y + (p.y - prev.y) };
    }
    this.frame();
  }

  private up(e: PointerEvent, cancelled = false) {
    const g = this.gesture;
    this.pointers.delete(e.pointerId);
    if (this.canvas.hasPointerCapture?.(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
    if (!g) return;
    if (this.pointers.size > 0 && g.mode === "pinch") {
      // One finger stays down after a pinch: it pans from here.
      const [only] = [...this.pointers.values()];
      this.gesture = { mode: "pan", node: null, startX: only.x, startY: only.y, moved: true, dist: 0 };
      return;
    }
    this.release();
    this.gesture = null;
    if (!cancelled && !g.moved && g.mode !== "pinch") this.opts.onSelect?.(g.node);
  }

  private release() {
    if (this.dragging !== null) {
      this.sim.unpin(this.dragging);
      this.dragging = null;
      this.sim.reheat(0.2);
      this.frame();
    }
  }

  private pinchDistance(): number {
    const [a, b] = [...this.pointers.values()];
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
  }

  private wheel(e: WheelEvent) {
    e.preventDefault();
    const p = this.local(e);
    // A trackpad pinch arrives as ctrl+wheel with small deltas, a mouse wheel as big ones.
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 100 : 1;
    const speed = e.ctrlKey ? 0.01 : 0.0015;
    this.userMoved = true;
    this.anim = null;
    this.zoomAt(p.x, p.y, Math.exp(-e.deltaY * unit * speed));
    this.frame();
  }

  private zoomAt(sx: number, sy: number, factor: number) {
    const k = clampZoom(this.view.k * factor);
    const f = k / this.view.k;
    this.view = { k, x: sx - (sx - this.view.x) * f, y: sy - (sy - this.view.y) * f };
  }

  private hoverOver(idx: number | null, x: number, y: number) {
    if (idx === this.hovered) {
      if (idx !== null) this.opts.onHover?.({ idx, x, y });
      return;
    }
    this.hovered = idx;
    this.canvas.style.cursor = idx === null ? "" : "pointer";
    this.opts.onHover?.(idx === null ? null : { idx, x, y });
    this.frame();
  }
}
