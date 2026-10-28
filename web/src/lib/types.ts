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
  /** Optional sources (twitter, linkedin, ...) with no folder under raw/ yet. */
  missing: string[];
  tracker: TrackerStatus;
}

// ── Tasks clone: clones/tasks/tasks.json ────────────────────────────────────

export type TaskPriority = "high" | "medium" | "low";
export type TaskStatus = "open" | "waiting" | "done";
export type TaskAction = "done" | "not_mine" | "dismiss";

export const TASK_ACTIONS: readonly TaskAction[] = ["done", "not_mine", "dismiss"];

/** One entry of tasks.json "tasks". */
export interface Task {
  id: string;
  title: string;
  detail: string;
  source: string; // "whatsapp" | "slack" | "email"; kept as a string so a new source still renders
  with: string | null;
  asked_at: string | null; // ISO
  due: string | null; // YYYY-MM-DD
  priority: TaskPriority;
  status: TaskStatus;
  evidence: string[];
}

/** A task with the latest line about it from clones/tasks/feedback.jsonl folded in. */
export interface TaskView extends Task {
  action: TaskAction | null;
  acted_at: string | null;
}

export interface TasksResponse {
  now: string;
  vault: VaultInfo;
  exists: boolean; // tasks.json is present and parses
  generated: string | null;
  tasks: TaskView[];
}

// ── Advisor clone: clones/advisor/YYYY-MM-DD.json ───────────────────────────

export type Confidence = "high" | "medium" | "low";
export type AdviceAction = "useful" | "not_me" | "doing";

export const ADVICE_ACTIONS: readonly AdviceAction[] = ["useful", "not_me", "doing"];

export interface Suggestion {
  id: string;
  area: string;
  pattern: string;
  suggestion: string;
  why: string;
  confidence: Confidence;
  evidence: string[];
}

export interface SuggestionView extends Suggestion {
  action: AdviceAction | null;
  acted_at: string | null;
}

export interface AdviceResponse {
  now: string;
  vault: VaultInfo;
  dates: string[]; // every YYYY-MM-DD file, newest first
  date: string | null; // the one shown
  generated: string | null;
  suggestions: SuggestionView[];
}

// ── Network clone: clones/network/people.json and ideas.json ────────────────

export type Relation = "met" | "know_of" | "to_read";
export type NetworkAction = "useful" | "not_me" | "done";

export const RELATIONS: readonly Relation[] = ["met", "know_of", "to_read"];
export const NETWORK_ACTIONS: readonly NetworkAction[] = ["useful", "not_me", "done"];

export interface Person {
  id: string;
  name: string;
  relation: Relation;
  sources: string[];
  interactions: number;
  first_seen: string | null;
  last_seen: string | null;
  context: string;
  topics: string[];
  org: string | null;
}

/** The latest line about an idea from clones/network/feedback.jsonl. */
export interface Acted {
  action: NetworkAction | null;
  acted_at: string | null;
}

export interface Project extends Acted {
  id: string;
  title: string;
  pitch: string;
  why_you: string;
  people: string[]; // person ids
  first_step: string;
}

export interface Outreach extends Acted {
  id: string;
  person_id: string | null;
  name: string;
  why: string;
  ask: string;
  channel: string;
}

export interface ToRead extends Acted {
  id: string;
  name: string;
  why: string;
}

export interface NetworkResponse {
  now: string;
  vault: VaultInfo;
  people: { exists: boolean; generated: string | null; list: Person[] };
  ideas: {
    exists: boolean;
    generated: string | null;
    projects: Project[];
    outreach: Outreach[];
    to_read: ToRead[];
  };
}

// ── Home: one request for the opening brief ─────────────────────────────────

export interface ChangelogSection {
  heading: string;
  date: string; // YYYY-MM-DD
  body: string; // markdown
}

export interface SourceSync {
  kind: string;
  lastSync: string | null;
}

export interface HomeResponse {
  now: string;
  vault: VaultInfo;
  name: string | null; // first name from TWIN_NAME
  since: string | null; // the baseline the counts below use
  feed: {
    newCount: number; // items newer than `since`, or in the latest batch when there is no baseline
    top: FeedItem[]; // up to three picks among those
    latest: BatchInfo | null;
  };
  tasks: {
    exists: boolean;
    generated: string | null;
    actionable: TaskView[]; // open, not acted on
    waiting: number;
  };
  advice: {
    exists: boolean;
    date: string | null;
    generated: string | null;
    total: number;
    unanswered: number;
    pick: SuggestionView | null;
  };
  network: {
    exists: boolean; // people.json is present
    people: number;
    met: number;
    outreach: Outreach | null; // first suggestion not yet acted on
  };
  self: {
    exists: boolean; // self/ has any markdown
    updated: string | null; // newest mtime among self/*.md
    latest: ChangelogSection | null;
  };
  sources: SourceSync[];
}
