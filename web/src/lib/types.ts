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
  by: string; // who made it: "proxenos"
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

export interface ProfileResponse {
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

/** One person from people.json. Its first_seen is left out: nothing on the page shows it. */
export interface Person {
  id: string;
  name: string;
  relation: Relation;
  sources: string[];
  interactions: number;
  last_seen: string | null;
  context: string;
  topics: string[];
  org: string | null;
  /** The cluster (community) this person is in, for people the graph connects; null for none. */
  cluster: number | null;
  /** Other names this person was found under, merged into one: what "not the same as" can undo. */
  aka: string[];
}

/** A community of people who share groups, from people.json "clusters". Ids are 1, 2, ... by size. */
export interface Cluster {
  id: number;
  label: string; // the name of the group most of its people are in
  size: number;
}

/** What the page can say about who is who: written to clones/network/aliases.json. */
export type PeopleEdit = "same" | "different" | "hide";
export const PEOPLE_EDITS: readonly PeopleEdit[] = ["same", "different", "hide"];

/** The answer to a people edit or a refresh: whether people.json was rebuilt with it. */
export interface PeopleEditResult {
  ok: boolean;
  saved: boolean;
  rebuilt: boolean;
  message: string;
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

export type GroupKind = "whatsapp_group" | "slack_channel" | "event" | "paper" | "email_thread" | "org";

/** In the order the filter chips list them. */
export const GROUP_KINDS: readonly GroupKind[] = ["whatsapp_group", "slack_channel", "event", "paper", "email_thread", "org"];

/**
 * Two people who share at least one group. Each shared group of n people adds 1/log2(n + 1) to
 * `weight`, so a pair alone adds 0.63 and a channel of thousands next to nothing; `shared` is how
 * many groups.
 */
export interface Edge {
  source: string; // person id
  target: string; // person id
  weight: number;
  shared: number;
  contexts: string[]; // short names of the shared groups, closest first, e.g. "Slack: acme #methods"
}

/** One context people share: a chat, a thread, a paper or an organization. */
export interface Group {
  id: string;
  name: string;
  kind: GroupKind;
  members: string[]; // person ids, among the people the graph connects
  size: number; // everyone in it besides the user, drawn or not
}

export interface NetworkResponse {
  now: string;
  vault: VaultInfo;
  people: {
    exists: boolean;
    generated: string | null;
    list: Person[];
    /** Ids of the people the graph connects, strongest first; empty in an index from before connections. */
    core: string[];
    edges: Edge[];
    groups: Group[];
    clusters: Cluster[];
  };
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

/** What the home thumbnail draws: the busiest people and the strongest ties among them. */
export interface GraphThumb {
  now: string;
  exists: boolean;
  people: number; // everyone in the index
  connected: number; // people the graph connects
  edges: number; // connections between them
  groups: number;
  nodes: { id: string; relation: Relation; interactions: number }[];
  links: { source: string; target: string; weight: number }[];
}

// ── Drafts: clones/drafts/*.md ──────────────────────────────────────────────

export type DraftAction = "approve" | "discard" | "edit" | "copy";

export const DRAFT_ACTIONS: readonly DraftAction[] = ["approve", "discard", "edit", "copy"];

/**
 * One drafts/<id>.md. kind, for, channel and status are strings so a new value still
 * renders; lib/drafts.ts has the known ones (kind: reply, email, doc, plan, checklist,
 * blocked; for: task, outreach, project, reading).
 */
export interface Draft {
  id: string;
  title: string;
  kind: string;
  for: string;
  channel: string;
  to: string; // "" when the draft is not addressed to anyone
  created: string | null;
  status: string; // "draft", "approved", "discarded"
  body: string; // markdown
}

export interface DraftsResponse {
  now: string;
  vault: VaultInfo;
  exists: boolean; // the drafts folder is present
  drafts: Draft[];
}

export interface HomeResponse {
  now: string;
  vault: VaultInfo;
  name: string | null; // first name from PROXENOS_NAME
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
  drafts: {
    exists: boolean;
    awaiting: number; // not approved or discarded
    top: Draft[]; // up to three of them, newest first
  };
  self: {
    exists: boolean; // self/ has any markdown
    updated: string | null; // newest mtime among self/*.md
    latest: ChangelogSection | null;
  };
  sources: SourceSync[];
}

// ── Memory: search over everything in raw/, and recall ────────────────────

/** One search hit. `snippet` has its matched words between U+0002 and U+0003 (see lib/memory.ts). */
export interface MemoryHit {
  id: string; // "<source>/<stream>/<record id>"
  source: string;
  stream: string;
  ts: string;
  who: string;
  where_: string;
  title: string;
  snippet: string;
  score: number; // bm25: lower is a better match
  from_me: boolean | null;
}

export interface MemoryFacet {
  source: string;
  count: number;
}

export interface MemorySearchResponse {
  indexed: boolean; // false until `proxenos index` has run
  query: string;
  hits: MemoryHit[];
  /** Rows per source among everything the query matches, before the source filter. */
  facets: MemoryFacet[];
  /** Rows matched with every filter applied; null when there is no index. */
  total: number | null;
  took_ms: number;
}

/** A record of a conversation, with its whole text (cut to 4,000 characters). */
export interface MemoryRecord {
  id: string;
  source: string;
  stream: string;
  ts: string;
  who: string;
  where_: string;
  title: string;
  text: string;
  from_me: boolean | null;
  target: boolean; // the record that was asked about
}

export interface MemoryContextResponse {
  id: string;
  records: MemoryRecord[];
}

export type RecallKind = "event" | "task" | "feed" | "person";

export interface RecallTrigger {
  kind: RecallKind;
  id: string;
  title: string;
  when: string | null;
  memories: MemoryHit[]; // at least one: a trigger with nothing to recall is left out
}

export interface RecallResponse {
  exists: boolean; // today.json is present
  generated: string | null;
  now: string;
  triggers: RecallTrigger[];
}

// ── Landing: /api/summary ───────────────────────────────────────────────────

export interface SummaryResponse {
  now: string;
  vault: VaultInfo;
  memories: number | null; // records in the memory index; null without an index
  people: number | null; // people in the network index; null without one
  drafts: number | null; // drafts awaiting review; null without a drafts folder
  sources: number; // sources with any synced data
  lastSync: string | null; // newest sync across every source
  /**
   * The network's core as a picture: positions in 0..1 and a size in 0..1 per node, and
   * pairs of node indexes per tie. No names and no ids.
   */
  constellation: { nodes: [number, number, number][]; edges: [number, number][] };
}

// ── Home briefing: /api/briefing ────────────────────────────────────────────

export interface AgendaEvent {
  title: string;
  when: string; // ISO start; for an all-day event, midnight UTC of its day
  all_day: boolean;
}

export interface ActivitySeries {
  source: string;
  counts: number[]; // one per day in `days`, oldest first
  total: number;
}

export interface DraftReviews {
  reviewed: number; // drafts with an approve, edit or discard
  approved: number; // approved as written
  edited: number; // edited, and not discarded since
  discarded: number;
  copied: number; // copy actions, all drafts
  last: string | null; // newest review
}

export interface BriefingResponse {
  now: string;
  agenda: { exists: boolean; generated: string | null; events: AgendaEvent[] };
  activity: { indexed: boolean; days: string[]; series: ActivitySeries[] };
  reviews: DraftReviews;
}
