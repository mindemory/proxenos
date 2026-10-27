// Shapes shared by the API routes (server) and the components (client).

export type Kind = "paper" | "news" | "post";
export type Action = "useful" | "not_me" | "save" | "open";
/** The actions that express a judgment. "open" is logged but never changes a card's state. */
export type Reaction = Exclude<Action, "open">;

export const ACTIONS: readonly Action[] = ["useful", "not_me", "save", "open"];

/** One line of tracker/items/YYYY-MM.jsonl. */
export interface Item {
  id: string;
  ts: string; // batch time, ISO Z
  batch: string;
  url: string; // "" when the source URL was not http(s)
  title: string;
  source: string; // "arxiv", "openalex", "hn", "rss:<host>", ...
  kind: Kind;
  published: string | null;
  authors: string[] | null;
  summary: string;
  score: number; // 0..1
  why: string;
  interest: string;
  explore: boolean;
  by: string; // "twin"
}

/** One line of tracker/feedback.jsonl. */
export interface FeedbackEntry {
  item_id: string;
  action: Action;
  ts: string; // ISO Z
}

export interface FeedItem extends Item {
  reaction: Reaction | null;
  reacted_at: string | null;
  opened: boolean;
}

export interface VaultInfo {
  path: string; // with the home directory shown as ~
  exists: boolean;
}

export interface BatchInfo {
  batch: string;
  ts: string;
  count: number;
}

export interface ItemsResponse {
  now: string;
  vault: VaultInfo;
  view: "feed" | "saved";
  items: FeedItem[];
  batches: BatchInfo[];
  latest: BatchInfo | null;
}

export interface SelfFile {
  name: string;
  mtime: string;
  content: string;
}

export interface TwinResponse {
  now: string;
  vault: VaultInfo;
  files: SelfFile[];
}

export interface SourceStatus {
  id: string; // "whatsapp", "email/<account>", "slack/<team>/messages", ...
  kind: string; // top-level folder under raw/
  command: string;
  lastSync: string | null; // newest mtime of any month file
  newestMonth: string | null; // "YYYY-MM"
  newestMonthLines: number;
  newestMonthFiles: number;
}

export interface TrackerStatus {
  lastBatch: string | null;
  lastBatchCount: number;
  items: number;
  feedback: number;
}

export interface StatusResponse {
  now: string;
  vault: VaultInfo;
  sources: SourceStatus[];
  tracker: TrackerStatus;
}
