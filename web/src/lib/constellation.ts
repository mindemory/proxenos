// A still picture of the network for the landing page: the core people as points and the ties
// among them as lines, laid out once on the server with a small force simulation. Only
// positions leave this file; names and ids never do.

export interface Constellation {
  nodes: [number, number, number][]; // x, y in 0..1; size in 0..1
  edges: [number, number][]; // node indexes
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/**
 * Fruchterman-Reingold on `count` nodes, deterministic: nodes start on a sunflower spiral, so
 * the same network always draws the same way. Coordinates come back fitted into the unit
 * square, centred, with the aspect kept.
 */
export function layoutConstellation(
  sizes: number[],
  edges: [number, number][],
  iterations = 260,
): Constellation {
  const n = sizes.length;
  if (n === 0) return { nodes: [], edges: [] };
  const x = new Float64Array(n);
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const r = Math.sqrt((i + 0.5) / n);
    x[i] = r * Math.cos(i * GOLDEN);
    y[i] = r * Math.sin(i * GOLDEN);
  }
  const k = Math.sqrt(1 / n) * 1.1; // ideal distance in a unit area
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  for (let it = 0; it < iterations; it++) {
    dx.fill(0);
    dy.fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const ex = x[i] - x[j];
        const ey = y[i] - y[j];
        const d2 = ex * ex + ey * ey + 1e-6;
        const f = (k * k) / d2; // repulsion k²/d, applied along the unit vector (ex,ey)/d
        dx[i] += ex * f;
        dy[i] += ey * f;
        dx[j] -= ex * f;
        dy[j] -= ey * f;
      }
    }
    for (const [a, b] of edges) {
      const ex = x[a] - x[b];
      const ey = y[a] - y[b];
      const d = Math.sqrt(ex * ex + ey * ey) + 1e-6;
      const f = d / k; // attraction d²/k, along (ex,ey)/d
      dx[a] -= ex * f;
      dy[a] -= ey * f;
      dx[b] += ex * f;
      dy[b] += ey * f;
    }
    const temperature = 0.08 * (1 - it / iterations) + 0.002;
    for (let i = 0; i < n; i++) {
      // A light pull to the centre keeps loose people from drifting off.
      dx[i] -= x[i] * 0.6;
      dy[i] -= y[i] * 0.6;
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) + 1e-9;
      const step = Math.min(d, temperature);
      x[i] += (dx[i] / d) * step;
      y[i] += (dy[i] / d) * step;
    }
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < n; i++) {
    minX = Math.min(minX, x[i]);
    maxX = Math.max(maxX, x[i]);
    minY = Math.min(minY, y[i]);
    maxY = Math.max(maxY, y[i]);
  }
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  const offX = (1 - (maxX - minX) / span) / 2;
  const offY = (1 - (maxY - minY) / span) / 2;
  const round = (v: number) => Math.round(v * 1000) / 1000;
  const biggest = Math.max(...sizes, 1);
  return {
    nodes: sizes.map((s, i) => [
      round(offX + (x[i] - minX) / span),
      round(offY + (y[i] - minY) / span),
      round(Math.log1p(s) / Math.log1p(biggest)),
    ]),
    edges,
  };
}
