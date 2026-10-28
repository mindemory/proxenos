// Colours for the network graph's clusters. Only the four biggest get a hue of their own: past
// four, no set of the palette's hues stays distinguishable pair by pair (see --c-cluster-* in
// globals.css), so smaller clusters share one neutral and people in none another. A cluster's
// colour follows its id, so filtering never repaints the ones left.

export const CLUSTER_HUES = 4;

export type ClusterSlot = 1 | 2 | 3 | 4 | "other" | "none";

export function clusterSlot(id: number | null | undefined): ClusterSlot {
  if (!id) return "none";
  return id <= CLUSTER_HUES ? (id as 1 | 2 | 3 | 4) : "other";
}

/** The CSS custom property holding a cluster's colour. */
export function clusterVar(id: number | null | undefined): string {
  return `var(--c-cluster-${clusterSlot(id)})`;
}

/** The same colours as plain hex, for when the CSS can't be read. */
export const CLUSTER_FALLBACK: Record<ClusterSlot, string> = {
  1: "#3987e5",
  2: "#c98500",
  3: "#d55181",
  4: "#008300",
  other: "#8b919c",
  none: "#5f6672",
};
