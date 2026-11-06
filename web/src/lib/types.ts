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
export type TaskStatus = "open" | "waiting" | "done" | "cancelled";
export type TaskAction = "done" | "not_mine" | "dismiss" | "keep";

export const TASK_ACTIONS: readonly TaskAction[] = ["done", "not_mine", "dismiss", "keep"];
/** What a task's row offers: the three that close it, or for an older one, keep it or close it. */
export const TASK_ROW_ACTIONS: readonly TaskAction[] = ["done", "not_mine", "dismiss"];
export const OLDER_TASK_ACTIONS: readonly TaskAction[] = ["keep", "done"];

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
  at: string | null; // when it happens, local: YYYY-MM-DDTHH:MM, or YYYY-MM-DD for a day
  place: string | null;
  stale: boolean; // open and unchanged for a week: folded under "Older, still needed?"
  changed: string | null; // ISO, when it last changed
  closed_by: "time" | "elsewhere" | null; // set when Proxenos marked it done itself, with no model
  closed_why: string | null;
}

/** A task with the latest line about it from clones/tasks/feedback.jsonl folded in. */
export interface TaskView extends Task {
  action: TaskAction | null;
  acted_at: string | null;
  /** The draft written for it (clones/drafts/<task id>.md), by its status: waiting, or settled. */
  draft: { status: "draft" | "approved" | "sent" | "discarded" | "overtaken" } | null;
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

// ── Choices clone: clones/choices/YYYY-MM-DD.json ───────────────────────────

export type ChoiceAction = "useful" | "not_me" | "doing";

export const CHOICE_ACTIONS: readonly ChoiceAction[] = ["useful", "not_me", "doing"];

export interface ChoiceEvidence {
  label: string;
  /** Its record in the memory index ("email/<account>/<id>"), or "" when it isn't one. */
  id: string;
}

/** Something to write or do: a first step, or a decline. */
export interface ChoiceMessage {
  what: string;
  to: string;
  channel: string;
}

interface ChoiceBase {
  id: string;
  kind: string;
  title: string;
  why: string;
  evidence: ChoiceEvidence[];
  /** The draft the work clone writes for it; status is null until it has written one. */
  draft: { id: string; status: string | null } | null;
  action: ChoiceAction | null;
  acted_at: string | null;
}

export interface TakeOn extends ChoiceBase {
  deadline: string; // YYYY-MM-DD, or ""
  link: string;
  step: ChoiceMessage & { kind: "draft" | "errand" };
}

export interface Skip extends ChoiceBase {
  cost: string;
  decline: ChoiceMessage | null;
}

export interface ChoicesResponse {
  now: string;
  vault: VaultInfo;
  dates: string[]; // every YYYY-MM-DD file, newest first
  date: string | null; // the one shown
  generated: string | null;
  take_on: TakeOn[];
  skip: Skip[];
}

// ── Jobs clone: clones/jobs/jobs.json and status.jsonl ──────────────────────

/** Where a job stands, as the user sets it: the jobs clone's STATUSES, in its order. */
export const JOB_STATUSES = ["new", "interested", "applied", "interviewing", "closed"] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
/** What the page appends to status.jsonl: a status, or "not applied" to set a suggestion aside. */
export const JOB_ACTIONS = [...JOB_STATUSES, "not_applied"] as const;
export type JobAction = (typeof JOB_ACTIONS)[number];

export type JobVerdict = "apply" | "maybe" | "skip";
/** Where a lead came from: LinkedIn, Work at a Startup, a recruiter, a job board or a receipt, a list, Slack, a post shared to Ask. */
export const JOB_SOURCES = ["linkedin", "workatastartup", "recruiter", "boards", "lists", "slack", "ask"] as const;
export type JobSource = (typeof JOB_SOURCES)[number];

export interface JobPerson {
  name: string;
  /** How the user knows them, or who they are to the job. */
  how: string;
  channel: string;
  /** "contact": who posted or wrote; "known": someone the user knows there. */
  role: "contact" | "known";
}

export interface JobSourceRef {
  source: JobSource;
  label: string;
  ts: string;
  /** Its record in the memory index, or "" when it isn't one. */
  id: string;
}

export interface Job {
  id: string;
  company: string;
  role: string;
  place: string;
  mode: string;
  pay: string;
  deadline: string; // YYYY-MM-DD, or ""
  link: string;
  /** Where a founder's or recruiter's message is answered, on Work at a Startup or LinkedIn. */
  reply_link: string;
  verdict: JobVerdict | null;
  why: string;
  rests_on: string[];
  route: { kind: string; why: string } | null;
  cv: { name: string; kind: string; why: string } | null;
  people: JobPerson[];
  step: { kind: string; to: string; channel: string } | null;
  /** The first step's draft; status is null until it's written. */
  draft: { id: string; status: string | null } | null;
  /** An errand that sends the CV too, in the user's words, or "". */
  errand: string;
  sources: JobSourceRef[];
  first_seen: string;
  last_seen: string;
  status: JobStatus;
  status_at: string | null;
  /** Applied, as the records suggest it, for the user to confirm. */
  suggested: { why: string; ts: string } | null;
}

export interface JobsResponse {
  now: string;
  vault: VaultInfo;
  generated: string | null;
  cvs: { name: string; kind: string }[];
  jobs: Job[];
}

// ── Watch clone: clones/watch/YYYY-MM-DD.json and history.json ───────────────

export type WatchAction = "want" | "seen" | "not_me";

export const WATCH_ACTIONS: readonly WatchAction[] = ["want", "seen", "not_me"];

export interface WatchPick {
  id: string;
  kind: "film" | "show";
  title: string;
  year: number | null;
  why: string;
  /** The films they've seen that it follows from, as "Title (Year), 5/5, hearted". */
  because: string[];
  links: { label: string; url: string }[];
  action: WatchAction | null;
  acted_at: string | null;
}

/** The journal's parts, in the order the page shows them. */
export type JournalSection = "done" | "said" | "moved" | "waiting" | "next";
export const JOURNAL_SECTIONS: readonly JournalSection[] = ["done", "said", "moved", "waiting", "next"];

/** One day of clones/journal/<date>.json: the brief, what's next, and the day's lines. */
export interface JournalEntry {
  date: string;
  generated: string | null;
  brief: string; // "" when no model wrote one
  next_up: string[];
  sections: Record<JournalSection, string[]>;
}

export interface JournalResponse {
  now: string;
  vault: VaultInfo;
  dates: string[]; // every YYYY-MM-DD entry, newest first
  date: string | null; // the one shown
  entry: JournalEntry | null;
}

/** Whom the user wrote to on a day, where, how many times, and the opening of their longest message there. */
export interface LifeWrote {
  to: string;
  channel: string;
  count: number;
  said: string;
}

/** One local day of the Life view: what the vault holds from it, by titles, names and counts, and its journal's brief. */
export interface LifeDay {
  date: string; // YYYY-MM-DD
  records: number;
  sources: Record<string, number>; // records by source, as the page names them
  wrote: LifeWrote[];
  events: string[];
  notes: string[];
  activity: string[];
  health: string[];
  other: string[];
  journal: { brief: string; next_up: string[] } | null;
}

/** A day of a month's diary, in the first person. */
export interface LifeEntry {
  day: string; // YYYY-MM-DD, in the month
  text: string;
}

/**
 * clones/life/months/YYYY-MM.json: a month's diary, written by the model from what the user said about the month, its care,
 * the observers' notes and its days; with the user's own abstract and essay in place of the model's while they're newer.
 */
export interface LifeStory {
  month: string;
  generated: string | null;
  summary: string; // the abstract, a few sentences; a story written before there were entries, whole, its paragraphs separated by a blank line
  essay: string; // paragraphs separated by a blank line; "" for a diary written before there was an essay, which the night writes again
  entries: LifeEntry[] | null; // oldest first; null for a story written before there were entries, which the night writes again
  highlights: string[];
  days_with_records: number;
  edited: string | null; // when the user saved the abstract and essay shown, their own (clones/life/edits.jsonl); null when it's the model's
}

/** clones/life/corrections.jsonl: something the user marked not true in a month's diary, the latest line for its item and text. */
export interface LifeCorrection {
  item: string; // "essay" (a paragraph of it), "highlight" or "entry:YYYY-MM-DD"
  text: string; // what it said
  correction: string; // what's true, in the user's words; "" when they didn't say
  at: string;
}

/** A month in the list: how much the vault holds from it, and its abstract when it has a diary. */
export interface LifeMonth {
  month: string; // YYYY-MM
  days: number; // days with records
  records: number;
  written: string | null; // when its diary was written
  opening: string; // the abstract's first paragraph, cut; "" when there's none
  highlights: string[]; // not those marked not true
  edited: boolean; // the abstract is the user's own
}

/** The page's "Write this month": `proxenos clone life --month`, one at a time. */
export interface LifeJob {
  state: "running" | "done" | "failed" | "stopped";
  message: string;
  month: string | null;
  started: string;
  finished: string | null;
}

export interface LifeResponse {
  now: string;
  vault: VaultInfo;
  today: string; // YYYY-MM-DD, on this computer's clock
  months: LifeMonth[]; // newest first: every month with records or a story
  left: number; // past months with no diary (or one from before there was an essay) that the night will write, four a night
  open: { month: string; story: LifeStory | null; days: LifeDay[]; corrections: LifeCorrection[] } | null;
  job: LifeJob | null;
  error: string | null;
}

export interface WatchResponse {
  now: string;
  vault: VaultInfo;
  dates: string[]; // every YYYY-MM-DD file, newest first
  date: string | null; // the one shown
  generated: string | null;
  films: WatchPick[];
  shows: WatchPick[];
  watchlist: WatchPick[];
  /** Picks from any week marked want and not marked since, newest mark first. */
  saved: WatchPick[];
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

/** opened: the draft was opened in its app; sent: the reader says they sent it. Both are logged. */
export type DraftAction = "approve" | "discard" | "edit" | "copy" | "opened" | "sent" | "keep" | "done";

export const DRAFT_ACTIONS: readonly DraftAction[] = ["approve", "discard", "edit", "copy", "opened", "sent", "keep", "done"];

/** One thing the reader told Proxenos (state/told.jsonl): a fact for now, or a rule ("always"). */
export interface ToldNote {
  at: string;
  text: string;
  always: boolean;
}

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
  updated: string | null; // when its file last changed: written again, edited, or its status set
  status: string; // "draft", "approved", "discarded", "sent", "overtaken"
  body: string; // markdown
  found: string; // for a reply: what the twin's look through memory showed, "" when nothing
  asks: string[]; // for a reply: what only the reader can decide, as questions
  overtaken: string; // why the messages made it moot, "" when they haven't
  thread: { source: string; chat: string } | null; // for a reply: the chat it answers (email: Gmail's thread id, else its subject and people)
  fromAccount: string; // for an email: the vault's mail stream the thread is in, "" when not recorded
  fromAddress: string; // the reader's own address it goes from, "" when not recorded
  fromProvider: string; // "gmail", "google-workspace" or "outlook"; "" when it isn't known
}

export interface DraftsResponse {
  now: string;
  vault: VaultInfo;
  exists: boolean; // the drafts folder is present
  drafts: Draft[];
}

/** Where a draft's one-click action goes. "file" is a download. */
export type OpenTarget = "email" | "whatsapp" | "slack" | "linkedin" | "instagram" | "messenger" | "x" | "file";

/** One way to open a draft in its app. The reader still presses send there. */
export interface DraftOpenStep {
  label: string; // the button's text
  hint: string; // what it does, for a tooltip
  url: string | null; // opened after the copy; null for a download
  copy: boolean; // put the text on the clipboard first
  note: string; // what to do next, shown once it has run
}

/** A draft's action: the way into the app it's meant for, and a second way where there is one (mailto). */
export interface DraftOpen extends DraftOpenStep {
  target: OpenTarget;
  alt: DraftOpenStep | null;
}

/** GET /api/drafts: the drafts, what each can open, and how the reader's reviews have gone. */
export interface DraftsViewResponse extends DraftsResponse {
  actions: Record<string, DraftOpen>; // by draft id; drafts already sent or discarded have none
  record: DraftReviews;
  closeness: DraftCloseness | null; // null until a sent reply has been measured
}

/** How close reply drafts came to what was then sent in their chat (clones/drafts/fidelity.json). */
export interface DraftCloseness {
  measured: number;
  sentAsIs: number; // sent with next to no change (closeness 0.95 or more)
  bySource: Record<string, { n: number; mean: number }>; // mean closeness, 0 to 1
}

// ── Outbox: clones/outbox/ ──────────────────────────────────────────────────
//
// Replies that may go out on their own, within rules the page writes (rules.json) and a window to
// cancel (cancelled.jsonl). Proxenos's sync reads both, sends, and writes back what it did
// (state.json, log.jsonl).

/** The chats a reply can be sent to, in the order the panel lists them. */
export const OUTBOX_CHANNELS = ["email", "whatsapp", "slack", "instagram", "messenger", "x", "linkedin"] as const;
export type OutboxChannel = (typeof OUTBOX_CHANNELS)[number];

/**
 * The rule for one channel: whether it's allowed, what its record must show first, and whether
 * what it sends says it came from the reader's assistant. The record is its drafts the reader
 * didn't touch: the share of them that went out nearly unchanged, at 95% confidence.
 */
export interface OutboxChannelRule {
  on: boolean;
  min_share: number; // 0.5 to 0.99: that share's lower bound must reach this
  min_measured: number; // 1 to 100: how many untouched drafts it needs behind it at least
  sign: boolean; // add a line saying the reader's assistant sent it
}

/** clones/outbox/rules.json, with anything missing filled in. */
export interface OutboxRules {
  enabled: boolean;
  daily_limit: number; // 1 to 50
  channels: Record<OutboxChannel, OutboxChannelRule>;
}

/** One edit to the rules, as POST /api/outbox/rules takes it. */
export type OutboxRuleEdit =
  | { enabled: boolean }
  | { daily_limit: number }
  | { channel: OutboxChannel; on?: boolean; min_share?: number; min_measured?: number; sign?: boolean };

/** A reply waiting out its window: it goes at the first sync after `sends_at` unless cancelled. */
export interface OutboxQueued {
  draft_id: string;
  channel: string;
  to: string;
  queued_at: string;
  sends_at: string;
}

/** clones/outbox/state.json: what the last sync worked out. */
export interface OutboxState {
  generated: string | null;
  /** How each channel can send ("apple_mail", "beeper"), or null for no way yet. */
  routes: Record<string, string | null>;
  /** Each channel's replies measured, used or not, and how close they came on average (0 to 1). */
  closeness: Record<string, { n: number; mean: number }>;
  /**
   * Each channel's record that counts: its measured drafts the reader didn't touch and the
   * outbox didn't send, with those whose chat went unanswered (n), how many went out nearly
   * unchanged, and the share that shows at 95% confidence (lower, 0 to 1).
   */
  evidence: Record<string, { n: number; unchanged: number; lower: number }>;
  /** Whether a channel's record meets its rule's thresholds. */
  earned: Record<string, boolean>;
  queue: OutboxQueued[];
  sent_today: number;
}

/** One line of log.jsonl: an attempt to send. */
export interface OutboxLogEntry {
  draft_id: string;
  channel: string;
  to: string;
  at: string;
  via: string | null;
  ok: boolean;
  error: string | null;
  /** Why the outbox left it for the reader to send (a link the chat never had, say), or null. */
  held: string | null;
}

/** GET /api/outbox. `state` is null until the first sync has written one. */
export interface OutboxResponse {
  now: string;
  rules: OutboxRules;
  state: OutboxState | null;
  cancelled: string[]; // draft ids
  log: OutboxLogEntry[]; // newest first
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
    actionable: TaskView[]; // open, not closed on the page; older ones included (see isStale)
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
    awaiting: number; // not sent or discarded, with an errand's messages waiting to be sent; each thing once
    top: Draft[]; // up to five drafts of them, newest first
    fromErrands: number; // of awaiting, how many are an errand's message
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
  sent: number; // marked sent (each also counts as approved, or as edited if it was)
  copied: number; // copy actions, all drafts
  last: string | null; // newest review
  recentReviewed: number; // reviewed whose latest review is in the last 14 days
  recentAccepted: number; // of those, approved or edited
}

export interface BriefingResponse {
  now: string;
  agenda: { exists: boolean; generated: string | null; events: AgendaEvent[] };
  activity: { indexed: boolean; days: string[]; series: ActivitySeries[] };
  reviews: DraftReviews;
}

// ── Care clone: clones/care/care.json ───────────────────────────────────────

export type CareEventKind =
  | "symptom"
  | "visit"
  | "test"
  | "result"
  | "referral"
  | "call"
  | "message"
  | "bill"
  | "claim"
  | "records"
  | "prescription";
export type CareItemKind =
  | "appointment"
  | "referral"
  | "bill"
  | "claim"
  | "records"
  | "prescription"
  | "form"
  | "follow_up"
  | "question";
export type CareWaitingOn = "me" | "provider" | "insurer" | "other";
export type CareStatus = "open" | "waiting" | "done";
export type CareScriptKind = "call" | "email" | "portal_message" | "form";
export type CareAction = "done" | "waiting" | "not_relevant";

export const CARE_ACTIONS: readonly CareAction[] = ["done", "waiting", "not_relevant"];

/** One dated step on the way through care, as the records tell it. */
export interface CareEvent {
  id: string;
  date: string; // YYYY-MM-DD
  kind: CareEventKind;
  title: string;
  detail: string;
  with: string; // a clinic, organization or role, never a person's name; "" when none
  evidence: string[]; // memory-index ids, looked up in `cited`
}

/** Something unresolved: an appointment, referral, bill, claim, records request, form, ... */
export interface CareItem {
  id: string;
  title: string;
  kind: CareItemKind;
  waiting_on: CareWaitingOn;
  next_step: string;
  due: string | null; // YYYY-MM-DD
  status: CareStatus;
  evidence: string[];
}

export interface CareItemView extends CareItem {
  action: CareAction | null; // the reader's latest, from feedback.jsonl
  acted_at: string | null;
}

/** What to say on a call, in an email, a portal message or a form, for one item. */
export interface CareScript {
  id: string;
  item_id: string;
  kind: CareScriptKind;
  title: string;
  body: string;
}

/** Where one piece of evidence came from, without its text. */
export interface CareCited {
  source: string;
  ts: string;
}

export interface CareResponse {
  now: string;
  vault: VaultInfo;
  exists: boolean;
  generated: string | null;
  summary: string;
  timeline: CareEvent[];
  items: CareItemView[];
  scripts: CareScript[];
  visit_brief: string; // markdown
  cited: Record<string, CareCited>;
  records: Record<string, number>; // what the last run read, by source
}

// ── Connect ─────────────────────────────────────────────────────────────────
//
// From `proxenos connect`: names, addresses, handles and dates, never a secret.

/** How a source gets in: signed in or read directly, a download imported, or a folder named. */
export type ConnectHow = "live" | "download" | "folder";

/** A signed-in account: Gmail's, Microsoft's, Google Calendar's or Google Docs'. */
export interface MailAccount {
  name: string; // GMAIL_<NAME>, MICROSOFT_<NAME>, GCALENDAR_<NAME> or GDOCS_<NAME>, lower case
  address: string;
  signIn: "google" | "microsoft" | "app_password";
  lastRead: string | null;
}

export interface ConnectSource {
  id: string;
  how: ConnectHow;
  connected: boolean;
  lastRead: string | null; // newest change to its files under raw/
  /**
   * What stops its button from working: "no_google_client", "no_microsoft_client", Beeper's "no_token", or WhatsApp's
   * "missing" or "blocked".
   */
  problem: string | null;
  /** A handle, where one helps. Apple Mail's is the Python that needs Full Disk Access. */
  detail: string | null;
  accounts: MailAccount[]; // the sign-ins: Gmail, Microsoft 365, Google Calendar and Google Docs only
  workspaces: string[]; // Slack only: the workspaces slackdump is signed in to
}

/** The sign-ins the page starts, each an account's name and address. */
export type SignInKind = "gmail" | "microsoft" | "gcalendar" | "gdocs";
export const SIGN_IN_KINDS: readonly SignInKind[] = ["gmail", "microsoft", "gcalendar", "gdocs"];

/** What the page can start: a sign-in, a read of WhatsApp, or a Beeper token. One of each at a time. */
export type ConnectJobKind = SignInKind | "whatsapp" | "beeper";
export const CONNECT_JOB_KINDS: readonly ConnectJobKind[] = [...SIGN_IN_KINDS, "whatsapp", "beeper"];

/**
 * Every background command the server runs for the page, one of each kind at a time: those above, an ask, an errand, a Send, a
 * project's step, a decision on one (Accept, Discard, or a change to the queue), a month's story, a thought
 * being thought through, a round of drafts comparing two models, a comparison of offers, a model being
 * downloaded, and an empty view being filled ("Make it now"). The last two show their command's last line as it comes.
 */
export type JobKind =
  | ConnectJobKind
  | "ask"
  | "errand"
  | "send"
  | "step"
  | "decide"
  | "life"
  | "think"
  | "compare"
  | "offers"
  | "review"
  | "model"
  | "make";

export interface ConnectJob {
  kind: ConnectJobKind;
  state: "running" | "done" | "failed" | "stopped";
  /** The command's last line, with anything that looks like a token blanked. */
  message: string;
  account: string | null; // the address a sign-in is for
  started: string;
  finished: string | null;
}

/** A background command as the page follows it: a model download, or a view being filled. `command` is the one the latter runs. */
export interface RunJob {
  state: ConnectJob["state"];
  message: string;
  command: string | null;
  started: string;
  finished: string | null;
}

export interface RunJobResponse {
  job: RunJob | null;
}

export interface ConnectJobsResponse {
  now: string;
  jobs: ConnectJob[];
}

/** Where the owner's phone reaches this page: its Tailscale address and the login that may open it. */
export interface PhoneInfo {
  address: string | null; // an https URL, once `proxenos phone` has set it up
  login: string | null;
}

export interface ConnectResponse extends ConnectJobsResponse {
  vault: VaultInfo;
  sources: ConnectSource[];
  phone: PhoneInfo;
  /** Whether this is the desktop app, which has no `proxenos` command or slackdump on the PATH to point a person at. */
  inApp: boolean;
  /** Why the sources couldn't be read, when they couldn't. */
  error: string | null;
}

// ── Setup and Settings ──────────────────────────────────────────────────────
//
// From `proxenos setup`: the settings, the model, and which secrets are set and where each comes
// from. Never a secret's value.

export const SETTING_KEYS = [
  "name",
  "vault",
  "model",
  "review_model",
  "local_url",
  "fast_model",
  "docs_dirs",
  "website_repo",
  "spotify_export",
  "slackdump_dir",
  "cv_dirs",
  "project_folder",
  "ntfy_server",
  "quiet_hours",
  "notice_kinds",
  "searxng_url",
  "lookup",
] as const;
export type SettingKey = (typeof SETTING_KEYS)[number];

/** Where a value comes from, first to last: the shell, the repo's .env, the settings file, the secure store ("keychain" everywhere). */
export type SettingOrigin = "environment" | ".env" | "settings" | "keychain";

export interface SettingValue {
  value: string | null;
  from: SettingOrigin | null;
}

export interface SecretState {
  name: string; // ANTHROPIC_API_KEY, GMAIL_<NAME>, ...
  set: boolean;
  from: SettingOrigin | null;
}

export interface SetupStatus {
  /** A first run: no name and no vault set anywhere. */
  needed: boolean;
  /** Where a change is saved: the repo's .env (from source, with one), or the settings file and the secure store. */
  savesTo: ".env" | "settings";
  settingsFile: string; // in the platform's settings folder: ~/Library/Application Support/Proxenos/settings.json on a Mac
  home: string; // the home folder, to tell which typed paths iCloud syncs
  settings: Record<SettingKey, SettingValue>;
  vault: { path: string; exists: boolean; cloud: "icloud" | "drive" | null };
  /** A model on this computer (through Ollama or another server), Anthropic's with a key, or none yet. */
  model: { kind: "local" | "api" | "none"; name: string; via: "ollama" | "server" | null };
  /** This computer's memory in bytes (null: unknown), which size of model to get, the rule for what fits, the model to pull unless it's too big, the small one to download first (null: too big too), and the bigger one to offer in the background while a small one is in use (null: none to offer). */
  computer: { memory: number | null; advice: string; rule: string; get: string | null; starter: string | null; upgrade: string | null };
  ollama: LocalModels;
  /** The model for light jobs: the one set ("off" is a choice), whether this Mac has mlx-lm and the model to serve, whether its server answers, and the name setup would set. */
  fast: { model: string | null; found: boolean; running: boolean; suggested: string };
  /** An OpenAI-compatible server on this computer (LM Studio, llama-server, ...) at `url`; `error` when that isn't this computer's own. */
  server: LocalModels & { url: string; error: string | null; context: number };
  keychain: boolean; // whether this computer's secure store can keep secrets
  secretStore: string; // that store's name, after "the": "Keychain", "Credential Manager" or "Secret Service"
  secrets: SecretState[];
}

/** A model a local server has: its size where the server says, and whether it fits this computer (null: unknown). */
export interface LocalModel {
  name: string;
  bytes: number | null;
  fits: boolean | null;
}

/** What a local server has: whether it answers, its models, and the largest that fits, to pick first. */
export interface LocalModels {
  running: boolean;
  models: LocalModel[];
  suggested: string | null;
}

export interface SetupResponse {
  status: SetupStatus | null;
  /** Why the settings couldn't be read, when they couldn't. */
  error: string | null;
}

/** One change: settings ("" removes one), an Anthropic key to check and keep, a model in Ollama or on another local server, a secret replaced or removed. */
export type SetupChange =
  | { settings: Partial<Record<SettingKey, string>> }
  | { key: string }
  | { ollama: string }
  | { server: string }
  | { secret: string; value: string }
  | { forget: string };

export interface SetupResult {
  ok: boolean;
  message: string | null; // what was done, when it was
  error: string | null; // why not, when it wasn't
  status: SetupStatus | null;
}

/** What `proxenos notify test` said: whether a test notice reached ntfy, in the page's words. */
export interface NoticeTest {
  ok: boolean;
  message: string;
}

// ── Listening: a natural voice, or the user's own, made on this Mac (state/speech/) ──

/** What Listen reads with: a voice made on this Mac (natural, or the user's own from a clip), or the device's. */
export type SpeechEngine = "natural" | "own";

/** One of the natural voices Settings offers. */
export interface NaturalVoice {
  id: string;
  name: string;
  accent: string;
}

/** The clip of the user's voice kept in the vault, without its sound. */
export interface VoiceClip {
  seconds: number | null;
  at: string | null;
  /** What the clip says, which the voice is made from with it. */
  text: string | null;
}

/** The last model download asked for, and how far it got. */
export interface SpeechDownload {
  engine: SpeechEngine | null;
  state: "running" | "done" | "failed";
  done: number | null;
  total: number | null;
  message: string | null;
  at: string | null;
}

/** What `proxenos speech status` says: whether this Mac can make the voices and what each needs. */
export interface SpeechStatus {
  /** A Mac with Apple silicon. */
  supported: boolean;
  /** The speech extra is installed. */
  installed: boolean;
  missing: string[];
  /** The line that installs it. */
  install: string;
  engines: Record<SpeechEngine, { downloaded: boolean; size: string; model: string }>;
  voices: NaturalVoice[];
  default_voice: string;
  clip: VoiceClip | null;
  /** What to read for the clip. */
  passage: string;
  download: SpeechDownload | null;
  running: boolean;
}

/** GET /api/speech: the status, or why it couldn't be read. */
export interface SpeechStatusResponse {
  status: SpeechStatus | null;
  error: string | null;
}

/** What a change to the clip or a download said. */
export interface SpeechChange {
  ok: boolean;
  message: string;
}

// ── Compare: which of two models writes like you (state/compare/) ──────────

/** What the reader can pick for a reply: one draft, both, or neither. */
export type ComparePick = "A" | "B" | "both" | "neither";
export const COMPARE_PICKS: readonly ComparePick[] = ["A", "B", "both", "neither"];
/** Replies a round drafts unless asked for another number, and the most it may. */
export const COMPARE_ROUND = 10;
export const COMPARE_MAX_ROUND = 50;
/** Picks under which the intervals are too wide to tell much (the command's MIN_PICKS). */
export const COMPARE_MIN_PICKS = 20;

export interface CompareModel {
  name: string; // as a round names it: "ollama:<name>", Anthropic's, or "voice:<setting>"
  label: string; // as the page shows it
  where: ModelWhere;
}

/** One message of a conversation as the drafts saw it. */
export interface CompareMessage {
  ts: string;
  mine: boolean;
  sender: string | null;
  text: string;
}

/**
 * One held-out reply. Blind until picked: its drafts are A and B, and which model wrote each, how close each came and
 * what the reader sent are there only once they've picked.
 */
export interface CompareItem {
  n: number;
  source: string;
  name: string;
  replied: string; // when the reader answered
  recent: CompareMessage[];
  waiting: CompareMessage[];
  /** ready: both drafts are there; failed: one couldn't be written, and it can't be picked. */
  state: "ready" | "drafting" | "failed";
  a: string | null;
  b: string | null;
  pick: ComparePick | null;
  picked: string | null;
  revealed: {
    a: string; // the model that wrote A, by its label
    b: string;
    aCloseness: number | null; // 0 to 1: how much of the draft was in what was sent
    bCloseness: number | null;
    sent: string;
  } | null;
}

export interface CompareFared {
  name: string;
  label: string;
  where: ModelWhere;
  won: number;
  share: number | null;
  /** The Wilson 95% interval of the share. */
  low: number | null;
  high: number | null;
  closeness: number | null; // its drafts' mean
  drafted: number;
  failed: number;
}

export interface CompareResults {
  picks: number;
  both: number;
  neither: number;
  models: CompareFared[];
  note: string;
}

export interface CompareRound {
  id: string;
  started: string;
  updated: string;
  /** drafting; ready; failed; or stopped: still drafting by its file, with nothing drafting it any more. */
  status: "drafting" | "ready" | "failed" | "stopped";
  error: string | null;
  models: CompareModel[];
  n: number; // replies
  drafted: number; // drafts written or failed, of 2n
}

export interface CompareRoundListed {
  id: string;
  started: string;
  status: CompareRound["status"];
  models: string[]; // labels
  n: number;
  picked: number;
}

/** The models set up now, for the page to offer. */
export interface CompareSetUp {
  drafting: string;
  hosted: string; // Anthropic's model, by default
  key: boolean; // whether there's an Anthropic API key
  voice: string | null; // "voice:<setting>", when a voice model is set up
}

export interface CompareJob {
  state: "running" | "done" | "failed" | "stopped";
  message: string;
  started: string;
  finished: string | null;
}

export interface CompareResponse {
  now: string;
  vault: VaultInfo;
  round: CompareRound | null;
  rounds: CompareRoundListed[];
  results: CompareResults | null;
  /** Every round of the same two models together, when there's more than one. */
  pooled: (CompareResults & { rounds: number }) | null;
  items: CompareItem[];
  setUp: CompareSetUp | null;
  job: CompareJob | null;
  error: string | null;
}

// ── Ask ─────────────────────────────────────────────────────────────────────
//
// A question typed or pasted on the Ask page, with screenshots if there are any. The page sends
// it to `proxenos ask`, which writes clones/ask/<id>.json as it works and when it's done.

export const ASK_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export type AskImageType = (typeof ASK_IMAGE_TYPES)[number];

/** What a question may hold: characters of text, screenshots, and each screenshot's decoded size. */
export const ASK_MAX_TEXT = 8000;
export const ASK_MAX_IMAGES = 8;
export const ASK_MAX_IMAGE_BYTES = 6 * 1024 * 1024;

/** One screenshot as it's sent: base64, without a "data:" prefix. */
export interface AskImage {
  type: AskImageType;
  data: string;
}

export type AskStatus = "working" | "done" | "failed";

/** A reply in the reader's voice, when the question was a message to them. */
export interface AskDraft {
  to: string;
  channel: string; // lower case: "whatsapp", "email", ...
  body: string;
}

/** Whether to go for an opening that was shared, in the order they're listed. */
export const OPENING_VERDICTS = ["apply", "maybe", "skip"] as const;
export type OpeningVerdict = (typeof OPENING_VERDICTS)[number];

/** An opening's first step, drafted: a note to whoever posted it, a cover letter's start, or a plan. */
export interface OpeningDraft extends AskDraft {
  id: string; // its draft in Drafts
  step: "message" | "cover_letter" | "plan";
}

/** A job, postdoc, residency, fellowship, scholar program, call for papers or workshop seen in what was shared. */
export interface Opening {
  id: string;
  kind: string; // "job", "postdoc", "residency", "fellowship", "scholar_program", "cfp", "workshop"
  title: string;
  org: string;
  place: string;
  mode: string; // "on-site", "remote", "hybrid" or ""
  pay: string;
  deadline: string; // YYYY-MM-DD, or ""
  link: string;
  verdict: OpeningVerdict;
  why: string;
  draft: OpeningDraft | null;
  /** Kept for the week's choices to weigh (clones/choices/kept.jsonl). */
  kept: boolean;
}

export interface AskEntry {
  id: string;
  at: string;
  status: AskStatus;
  /** Researched over rounds and thought through, rather than a quick answer. */
  deep: boolean;
  question: string;
  images: number; // how many screenshots came with it
  seen: string; // what the screenshots show, transcribed
  answer: string; // markdown
  draft: AskDraft | null;
  /** The openings in what was shared, apply first; empty when there were none. */
  openings: Opening[];
  found: string;
  asks: string[];
  error: string | null;
}

/** The server's one `proxenos ask` at a time. `id` is the ask it finished, once it has. */
export interface AskJob {
  state: "running" | "done" | "failed" | "stopped";
  /** The command's last line, with anything that looks like a token blanked. */
  message: string;
  started: string;
  finished: string | null;
  id: string | null;
}

export interface AskResponse {
  now: string;
  vault: VaultInfo;
  /** The newest asks, newest first. */
  asks: AskEntry[];
  job: AskJob | null;
}

// ── Think ───────────────────────────────────────────────────────────────────
//
// A conversation with Proxenos about anything, from `proxenos think`, which keeps each thread in
// clones/think/<id>.json. A thread can start from something on another view: a draft, a project,
// a day, a person, or a note of the reader's own.

export const THINK_MAX_TEXT = 8000;
export const THINK_KINDS = ["draft", "project", "day", "person", "free"] as const;
export type ThinkKind = (typeof THINK_KINDS)[number];
export type ThinkStatus = "working" | "done" | "failed";

/** One thing the reader's own goals, notes or records say bears on it, and where it says so. */
export interface ThinkMatter {
  text: string;
  /** "self" (a part of the self-model), "told" (a note), "record", "journal" or "context". */
  source: string;
  /** "From your goals and values", "From your email, 2026-10-17". */
  label: string;
  /** A record's memory id, to open it; "" for anything else. */
  record: string;
}

/** An optional next step. `draftTo` names whom, when it's a message to draft. */
export interface ThinkStep {
  text: string;
  draftTo: string;
}

export interface ThinkMessage {
  role: "me" | "proxenos";
  at: string;
  text: string;
  /** Proxenos's turns only. */
  matters: ThinkMatter[];
  questions: string[];
  next: ThinkStep[];
}

/** What a thread started from, as it shows at the thread's top. */
export interface ThinkContext {
  kind: ThinkKind;
  id: string;
  title: string;
  text: string;
}

export interface ThinkThread {
  id: string;
  title: string;
  created: string;
  updated: string;
  status: ThinkStatus;
  error: string | null;
  context: ThinkContext | null;
  messages: ThinkMessage[];
}

/** A thread as the list shows it. */
export interface ThinkSummary {
  id: string;
  title: string;
  updated: string;
  status: ThinkStatus;
  /** What it started from, or "" for nothing. */
  kind: ThinkKind | "";
  turns: number;
  last: string;
}

/** The server's one `proxenos think` at a time. */
export interface ThinkJob {
  state: "running" | "done" | "failed" | "stopped";
  message: string;
  started: string;
  finished: string | null;
  /** The thread it went on with, or, once a new one is done, the thread it started. */
  thread: string | null;
}

export interface ThinkResponse {
  now: string;
  vault: VaultInfo;
  threads: ThinkSummary[];
  /** The thread asked for with ?id=, when there is one. */
  thread: ThinkThread | null;
  job: ThinkJob | null;
  /** Why the threads couldn't be read, when they couldn't. */
  error: string | null;
}

/** GET /api/think?job=1: the job alone, to poll. */
export interface ThinkJobResponse {
  now: string;
  job: ThinkJob | null;
}

/** What another view hands Think to start a new thread from. */
export interface ThinkStart {
  kind: ThinkKind;
  id: string;
  /** Shown above the composer: "Draft: Reply to Ana". */
  label: string;
  /** The first message, written for the reader to change. */
  text: string;
}

// ── Errands ─────────────────────────────────────────────────────────────────
//
// From clones/errands/<id>.json, which `proxenos clone errands` writes: something to get done,
// carried as far as it goes without the user, each step on its thread, and the messages it wrote,
// each waiting on the user's Send.

export const ERRAND_MAX_GOAL = 2000;
export const ERRAND_MAX_MESSAGE = 20_000;

export type ErrandStatus = "working" | "ready" | "waiting" | "sent" | "done" | "failed" | "dropped";

export interface ErrandStep {
  at: string;
  title: string;
  detail: string;
}

export interface ErrandMessage {
  /** The message the errand is for, or a note asking someone for an introduction. */
  role: "main" | "intro";
  to: string;
  channel: string;
  /** An email address the records show, or one the user typed in. */
  address: string;
  /** How Send sends it: Mail, Beeper, or nothing yet. */
  via: "apple_mail" | "beeper" | "";
  /** How the address or chat is known. */
  evidence: string;
  /** "web" when the address came from the person's organization's own pages, not the records. */
  found: "web" | "";
  /** The pages a web address is on, for the user to check. */
  sources: string[];
  subject: string;
  body: string;
  /** The CV goes with it. */
  attach: boolean;
  /** Written to paste into a chat Proxenos can't send in (Slack, WeChat): Copy, or Send to an address typed in. */
  copied: boolean;
  state: "ready" | "waiting" | "sent" | "done";
  sentAt: string;
  /** Who sent it once it was: Proxenos on Send, the user by hand, or "elsewhere" when their own records show it went. */
  sentBy: "proxenos" | "you" | "elsewhere" | "";
  /** For one sent elsewhere: what in their records showed it. */
  sentEvidence: string;
}

export interface ErrandCv {
  name: string;
  made: string;
  where: string;
  /** What in it is no longer true. */
  notes: string[];
}

export interface Errand {
  id: string;
  goal: string;
  created: string;
  updated: string;
  status: ErrandStatus;
  summary: string;
  who: string;
  why: string;
  needs: string[];
  cv: ErrandCv | null;
  steps: ErrandStep[];
  messages: ErrandMessage[];
  error: string | null;
}

export interface ErrandJob {
  state: "running" | "done" | "failed" | "stopped";
  message: string;
  started: string;
  finished: string | null;
}

export interface ErrandsResponse {
  now: string;
  vault: VaultInfo;
  errands: Errand[];
  /** The errand being carried out now, or how the last one ended. */
  job: ErrandJob | null;
  /** The last Send or Drop. */
  sending: ErrandJob | null;
}

/** What a Send changes in the message first: an address typed in, or the subject or body edited. */
export interface ErrandEdits {
  address?: string;
  subject?: string;
  body?: string;
}

// ── Offers ──────────────────────────────────────────────────────────────────
//
// From clones/offers/<slug>.json, which `proxenos clone offers` writes: what several people or firms
// offered for one goal, a row each, every price held to their own messages, and the reply to each,
// kept as an errand waiting on the user's Send.

export const OFFERS_MAX_GOAL = 500;
export const OFFERS_MONTHS = [3, 6, 12, 24] as const;

export type OffersStatus = "working" | "done" | "failed";

/** Something they offer and its price, each as they wrote it, "" when not said. */
export interface OfferPrice {
  what: string;
  price: string;
}

export interface OfferPerson {
  name: string;
  role: string;
}

/** The reply to one counterpart, as its errand stands now. */
export interface OfferReply {
  errand: string;
  status: ErrandStatus;
  to: string;
  channel: string;
  /** The address it goes to, or "" while it waits for one. */
  address: string;
  subject: string;
  body: string;
  state: "ready" | "waiting" | "sent" | "done";
}

export interface OfferRow {
  key: string;
  /** A firm, by its mail's domain, or one person. */
  kind: "org" | "person";
  name: string;
  channel: string;
  people: OfferPerson[];
  address: string;
  first: OfferPrice;
  whole: OfferPrice;
  prices: OfferPrice[];
  credited: string;
  terms: string[];
  /** What's missing for a fair comparison. */
  missing: string[];
  /** When they or the user last wrote. */
  last: string;
  /** Who owes the next reply. */
  owes: "you" | "them";
  heard: number;
  /** What the model gave that their messages don't say, so it was left out. */
  unconfirmed: string[];
  reply: OfferReply | null;
  error: string | null;
}

export interface Offers {
  slug: string;
  goal: string;
  created: string;
  updated: string;
  months: number;
  since: string;
  project: string;
  status: OffersStatus;
  error: string | null;
  /** What to compare them on, from the rows alone. */
  note: string;
  rows: OfferRow[];
}

export interface OffersResponse {
  now: string;
  vault: VaultInfo;
  comparisons: Offers[];
  /** The projects whose brief a comparison can go into. */
  projects: { id: string; name: string }[];
  /** The comparison being made now, or how the last one ended. */
  job: ErrandJob | null;
}

export interface OffersRequest {
  goal: string;
  months: number;
  project: string | null;
}

// ── Projects ────────────────────────────────────────────────────────────────
//
// From clones/projects/: projects.json, the user's list; each project's status.md, the projects
// clone's notes on where it stands; queue.json, the steps the user asked for; and steps/<when>.json,
// the steps clone's work: one step done on a branch of the project's code, waiting on Accept or
// Discard.

export const STEP_MAX_TEXT = 2000;

export type StepStatus = "working" | "ready" | "failed" | "accepted" | "discarded";

export interface StepNote {
  at: string;
  title: string;
  detail: string;
}

/** A file the step changed in the code, with lines added and removed. */
export interface StepFile {
  path: string;
  added: number;
  removed: number;
}

/** A figure or table the step made for its report, kept in the vault and not committed. */
export interface StepMade {
  name: string;
  caption: string;
  image: boolean;
}

export interface ProjectStep {
  /** <project>/<when>. */
  id: string;
  /** A step taken by a runner, or an edit the user made by hand on the page. */
  kind: "step" | "edit";
  created: string;
  updated: string;
  status: StepStatus;
  summary: string;
  /** The step the user queued, or "" when the runner picked it. */
  asked: string;
  /** A step a paper's peer review asked for, rather than the user. */
  byReview: boolean;
  /** What took it: Claude Code, the local model, or "" before one did. */
  runner: "claude" | "local" | "";
  step: string;
  why: string;
  did: string;
  found: string;
  couldnt: string;
  next: string;
  made: StepMade[];
  files: StepFile[];
  branch: string;
  base: string;
  /** The step still waiting on the user it builds on ("revise this step"), or null. */
  buildsOn: string | null;
  /** Where its worktree is, with ~ for home, until it's accepted or discarded. */
  worktree: string;
  thread: StepNote[];
  error: string | null;
  turns: number | null;
}

export interface QueuedStep {
  id: string;
  text: string;
  added: string;
  /** The branch it starts from, when not the checkout's: a manuscript's, or a waiting step's. */
  base: string;
  /**
   * Who asked for it: the reader ("you"), Proxenos from the project's status ("proxenos"), or
   * comments on the manuscript's copy ("comments", by `authors`). "" for one queued before
   * Proxenos kept who asked.
   */
  by: "you" | "proxenos" | "comments" | "";
  authors: string[];
  /** Whether the reader approved it: their own are; the rest wait, and the night skips them. */
  approved: boolean;
}

/** What a step asked for from the page may say beyond its words. */
export interface StepAsk {
  /** The branch it starts from: the manuscript's, or the branch of a step it revises. */
  base?: string;
  manuscript?: { path: string; branch: string };
}

export interface WorkProject {
  id: string;
  name: string;
  about: string;
  /** Which part of the user's work it belongs to ("PhD", "Postdoc"), from projects.json; "" for none. */
  group: string;
  /** What's known around it, the question and first analyses: clones/projects/<id>/brief.md, markdown, or "". */
  brief: string;
  /** Its folder, manuscript and PDF on drive.google.com, as the folders clone found them synced; "" for each it hasn't. */
  drive: { folder: string; manuscript: string; pdf: string };
  paused: boolean;
  /** Whether the night may take a step nobody asked for ("autostep" in projects.json). */
  autostep: boolean;
  /** The folder of its code, with ~ for home; "" when steps aren't taken on it. */
  repo: string;
  /** The paper it names in projects.json ("manuscript"), as a path in its code; "" when it names none. */
  paper: string;
  data: string[];
  /** Where it stands, as the projects clone last wrote it: markdown, without its title. */
  status: string;
  /** The day it was written, YYYY-MM-DD, or "". */
  statusDate: string;
  queue: QueuedStep[];
  /** Newest first. */
  steps: ProjectStep[];
}

export interface ProjectsJob {
  state: "running" | "done" | "failed" | "stopped";
  message: string;
  started: string;
  finished: string | null;
  /** The project a step is being taken on. */
  project: string | null;
}

export interface ProjectsResponse {
  now: string;
  vault: VaultInfo;
  projects: WorkProject[];
  /** The step being taken now, or how the last one ended. */
  job: ProjectsJob | null;
  /** The last Accept, Discard or change to a queue. */
  deciding: ProjectsJob | null;
}

// ── A paper's peer review ───────────────────────────────────────────────────
//
// From clones/projects/<id>/reviews/, as `proxenos review` writes it: each review's rounds, each
// reviewer's report, the author's plan and the response letter, and every concern with what each
// round made of it. The revision itself is the project's steps, shown with the rest.

export const REVIEW_ROUNDS_MAX = 5;
export const REVIEW_ROUNDS_DEFAULT = 3;
export type ReviewStatus = "working" | "done" | "stopped" | "failed";
export type ConcernStatus = "open" | "resolved" | "partly resolved" | "not resolved";

export interface Reviewer {
  n: number;
  lens: string;
  expertise: string;
}

/** One reviewer's report in one round. */
export interface ReviewReport {
  n: number;
  recommendation: string;
  score: number | null;
  confidence: number | null;
  major: number;
  minor: number;
  resolved: number;
  partly: number;
  unresolved: number;
  /** Suggested works no index found, left out; citations taken out of its words. */
  dropped: number;
  takenOut: number;
  /** The report, in markdown. */
  text: string;
}

export interface ReviewRound {
  n: number;
  status: string;
  /** Where the manuscript was read: its branch, or the last round's step's. */
  branch: string;
  commit: string;
  reviews: ReviewReport[];
  openMajor: number;
  openMinor: number;
  plan: { text: number; analysis: number; later: number; decline: number };
  planText: string;
  response: string;
  steps: string[];
  error: string;
}

export interface ReviewConcern {
  id: string;
  reviewer: number;
  kind: "major" | "minor";
  round: number;
  title: string;
  status: ConcernStatus;
  history: { round: number; status: string }[];
}

export interface ReviewRun {
  id: string;
  created: string;
  updated: string;
  status: ReviewStatus;
  summary: string;
  error: string;
  model: string;
  roundsMax: number;
  manuscript: { path: string; branch: string };
  field: string;
  venue: string;
  reviewers: Reviewer[];
  rounds: ReviewRound[];
  concerns: ReviewConcern[];
  /** What it's doing now, or did last. */
  latest: StepNote | null;
}

export interface ReviewsResponse {
  now: string;
  project: string;
  runs: ReviewRun[];
  /** The review being run now, or how the last one ended. */
  job: ProjectsJob | null;
}

// ── A project's manuscript ──────────────────────────────────────────────────
//
// From `proxenos project manuscript`, which reads the project's code with git: the manuscript (a
// paper.md, manuscript.md or main.tex, on whichever branch holds it), its versions, and one version
// with its changes since another; or every file a step changed.

/** The longest manuscript the page shows whole and lets the user edit. */
export const MANUSCRIPT_MAX_TEXT = 400_000;

/** A stretch of text that stayed, came in or went. The same and add texts make the newer version. */
export interface DiffOp {
  op: "same" | "add" | "del";
  text: string;
}

export interface ManuscriptVersion {
  commit: string;
  short: string;
  date: string;
  author: string;
  subject: string;
  /** The branch it's on: the manuscript's, or that of a step still waiting on the user. */
  branch: string;
  /** On a step's branch, waiting on Accept: Proxenos's work, or the user's own edit. */
  proxenos: boolean;
  edit: boolean;
  /** The step's id, when it's on one. */
  step: string | null;
  path: string;
}

/** One file's changes from one version to another: prose word by word, code line by line. */
export interface FileChanges {
  kind: "prose" | "code";
  unit: "words" | "lines";
  /** The newer version's text. */
  text: string;
  ops: DiffOp[];
  added: number;
  removed: number;
  /** Not text, so not compared. */
  binary: boolean;
  /** Too long to compare: the text is cut, and shown without changes. */
  truncated: boolean;
}

export interface ManuscriptResponse extends FileChanges {
  project: string;
  /** Null when no paper was found: `why` says how to name it. */
  manuscript: { path: string; branch: string; named: boolean } | null;
  why: string;
  /** Newest first. */
  versions: ManuscriptVersion[];
  /** The manuscript branch's newest commit, which an edit starts from. */
  tip: string;
  base: string;
  head: string;
  /** The head is the newest version on the manuscript's own branch, whole. */
  editable: boolean;
}

export interface ChangedFile extends FileChanges {
  path: string;
}

export interface StepChangesResponse {
  project: string;
  step: string;
  branch: string;
  /** The branch Accept merges it into. */
  base: string;
  files: ChangedFile[];
  /** More files changed than are shown. */
  truncated: boolean;
}

/** The text the user saved, and where it came from. */
export interface ManuscriptEdit {
  path: string;
  branch: string;
  /** The commit the text was read at. */
  from: string;
  text: string;
}

/** A reply to a comment in the manuscript's Google Doc. Someone else's words: shown, never sent to a model. */
export interface DocReply {
  author: string;
  content: string;
  created: string;
}

/** A comment in the manuscript's Google Doc, with the passage it's on. */
export interface DocComment {
  id: string;
  author: string;
  content: string;
  /** The passage it's on, as Docs quotes it; empty for a comment on the whole doc. */
  quoted: string;
  resolved: boolean;
  created: string;
  replies: DocReply[];
}

/** The manuscript's Google Doc, as `proxenos project gdocs` keeps it. */
export interface ManuscriptDoc {
  link: string;
  title: string;
  /** The GDOCS_<NAME> sign-in whose Drive it's in, and its address. */
  account: string;
  address: string;
  path: string;
  branch: string;
  /** The commit it was made from. */
  commit: string;
  at: string;
  /** When its changes were last brought back. */
  pulled: string | null;
  /** The step the changes last brought back made, which may still wait on the user. */
  step: string | null;
}

export interface ManuscriptDocResponse {
  project: string;
  /** The Google Docs sign-ins: none means the user must sign in first. */
  accounts: { name: string; address: string }[];
  doc: ManuscriptDoc | null;
  comments: DocComment[];
  commentsRead: string | null;
}

/** What bringing back the doc's changes did: a step waiting on the user, or why there was none. */
export interface ManuscriptDocPull extends ManuscriptDocResponse {
  changed: boolean;
  step: string | null;
  said: string;
}

// ── Calls ───────────────────────────────────────────────────────────────────

/** Where a call is: ringing, pressing the menu, on hold, the assistant talking, ringing you, you on the line, over. */
export type CallPhase = "dialing" | "menu" | "waiting" | "talking" | "connecting" | "connected" | "done";

export interface CallLine {
  at: string;
  /** "them": a person; "line": the hold's recordings; "note": what happened. */
  who: "them" | "assistant" | "line" | "note";
  text: string;
}

export interface CallOutcome {
  summary: string;
  asks: { ask: string; result: string }[];
  rep_name: string;
  reference: string;
  offered: string[];
  next: string[];
}

/** One call from a sheet: going (live) or kept after it ended. */
export interface CallRecord {
  started: string;
  ended: string | null;
  /** How Twilio said it ended: completed, busy, no-answer, failed, canceled; "" while it goes. */
  status: string;
  phase: CallPhase;
  mode: "ring" | "talk";
  /** The asks answered, by number from 1. */
  done: number[];
  notes: { rep_name: string; reference: string; offered: string[] };
  transcript: CallLine[];
  outcome: CallOutcome | null;
}

/** A call sheet, clones/calls/<id>.md: whom to call, why, and what the assistant may ask and say. */
export interface CallSheet {
  id: string;
  title: string;
  to: string;
  number: string;
  about: string;
  asks: string[];
  /** The names of the facts it may tell them; their values stay in the vault. */
  facts: string[];
  talk: boolean;
  notes: string;
  /** What's wrong with the sheet, when it can't be called from. */
  error: string | null;
  /**
   * Why its number may not be theirs, as the last check found it (calls.doubt: in just one
   * message to the reader, and in nothing of theirs), or null. Calling it then takes "Call anyway".
   */
  doubt: string | null;
  live: CallRecord | null;
  /** Newest first. */
  past: CallRecord[];
}

export interface CallsResponse {
  now: string;
  vault: VaultInfo;
  /** The settings calls need that aren't set (the Twilio secrets are checked when a call starts). */
  missing: string[];
  sheets: CallSheet[];
}

// ── Privacy ─────────────────────────────────────────────────────────────────
//
// From `proxenos privacy`: paths, names, addresses, counts and dates. Never a message, a prompt,
// a token or a key.

/** Where a model call ran. A line that doesn't say counts as Anthropic. */
export type ModelWhere = "this computer" | "Anthropic";
export const MODEL_WHERES: readonly ModelWhere[] = ["this computer", "Anthropic"];

/** Where a lookup of someone's address searches: the user's own SearXNG, Brave Search, or DuckDuckGo. */
export type LookupEngine = "searxng" | "brave" | "duckduckgo";
export const LOOKUP_ENGINES: readonly LookupEngine[] = ["searxng", "brave", "duckduckgo"];

/** The vault's own folders, in the order the page lists them; the rest is "other". */
export const VAULT_FOLDERS = ["raw", "memory", "clones", "self", "observations", "state", "other"] as const;
export type VaultFolder = (typeof VAULT_FOLDERS)[number];

/** Calls added up: how many, how many failed or went to Anthropic, and how much went in and came back. */
export interface CallTotals {
  calls: number;
  failed: number;
  hosted: number;
  sentChars: number;
  images: number;
  /** Numbers and secrets blanked before a call went to Anthropic. */
  redacted: number;
  answerChars: number;
  /** Where the model counted them; a call it didn't count adds nothing. */
  tokensIn: number;
  tokensOut: number;
}

/** One part of Proxenos's calls: `step` as the log names it, `part` as the page does (null when no part covers it). */
export interface StepCalls extends CallTotals {
  step: string;
  part: string | null;
}

/** One line of the calls log: when, which part asked, the model, where it ran and how much, never the words. */
export interface ModelCall {
  at: string;
  step: string;
  model: string;
  where: ModelWhere;
  sentChars: number | null;
  images: number | null;
  /** Null for a call that didn't leave this computer. */
  redacted: number | null;
  answerChars: number | null;
  tokensIn: number | null;
  tokensOut: number | null;
  seconds: number | null;
  ok: boolean;
}

/** What one part sends a model, in plain words, and the steps of the log it covers. */
export interface PartSends {
  part: string;
  steps: string[];
  sends: string;
}

/** A connected source, by its names and addresses. */
export interface FetchedSource {
  id: string;
  how: ConnectHow;
  lastRead: string | null;
  accounts: { name: string; address: string }[];
  workspaces: string[];
}

export interface PrivacyReport {
  here: {
    vault: { path: string; exists: boolean; bytes: number; folders: Record<VaultFolder, number>; cloud: "icloud" | "drive" | null };
    /** Whether FileVault encrypts the disk; null off a Mac, or when it can't be told. */
    filevault: boolean | null;
    settingsFile: string;
    secretStore: string;
    /** The secrets that are set, by name, and where each is kept. */
    secrets: { name: string; from: SettingOrigin | null }[];
  };
  sent: {
    model: { name: string; kind: "local" | "api" | "none"; voice: string | null; fast: string | null };
    days: number;
    since: string;
    totals: CallTotals;
    byWhere: Record<ModelWhere, CallTotals>;
    /** Most calls first. */
    byStep: StepCalls[];
    /** The newest calls, newest first. */
    recent: ModelCall[];
    sends: PartSends[];
  };
  fetched: {
    sources: FetchedSource[];
    /** Whether links in chats waiting on a reply are read: whenever a model is set up. */
    links: boolean;
    /** Whether artists' names are looked up at MusicBrainz for their genres, and how many have been. */
    music: { on: boolean; artists: number };
    /** Whether people's addresses are looked up on the web, and the search engine's host (never a key). */
    lookup: { on: boolean; engine: LookupEngine; host: string };
  };
  /** Notices on the phone through ntfy: whether they're on, the server's host (never the topic), the quiet hours and what one carries. */
  notices: { on: boolean; server: string; quiet: string | null; sends: string };
}

export interface PrivacyResponse {
  now: string;
  vault: VaultInfo;
  report: PrivacyReport | null;
  /** Why the report couldn't be read, when it couldn't. */
  error: string | null;
}

// ── Rhythms clone: clones/rhythms/weeks.json, through `proxenos clone rhythms --json` ──

/** How far back the Rhythms view looks, and how many weeks each of its periods holds. */
export type RhythmsRange = "3m" | "1y" | "all";
export type RhythmsResolution = "1w" | "2w" | "1m";

export interface RhythmsMove {
  count: number;
  km: number;
  hours: number;
}

/** One ISO week, in local time: what was listened to, how you moved, whom you wrote to. */
export interface RhythmsWeek {
  week: string; // "2026-W10"
  start: string; // its Monday, YYYY-MM-DD
  listening: {
    hours: number; // podcasts and audiobooks too
    spoken_hours: number;
    plays: number;
    artists: number;
    top: { name: string; hours: number }[]; // up to five, most first
    /** Hours of music by genre and by mood, from the artists' labels; "unlabelled" for the rest. */
    genres: Record<string, number>;
    moods: Record<string, number>;
    top_genre: string | null;
    top_mood: string | null;
  };
  movement: {
    rides: RhythmsMove & { climb_m: number };
    runs: RhythmsMove;
    hikes: RhythmsMove;
    walks: RhythmsMove;
    other: { count: number; hours: number };
  };
  messages: {
    sent: Record<string, number>; // by channel, as the page names it
    received: Record<string, number>;
    people: number; // people and chats written to
  };
  calendar: { events: number; hours: number };
}

export interface RhythmsLine {
  kind: "listening" | "riding" | "messages" | "mood";
  text: string;
}

/** One day of a month card: the mood of the user's own writing beside what they listened to. */
export interface RhythmsMonthDay {
  day: string; // YYYY-MM-DD
  /** VADER's mean over the day's sentences with a feeling, -1 to 1; null with too few of them. */
  valence: number | null;
  scored: number;
  emotions: string[]; // up to three, by the model on this computer only
  words: number;
  music_hours: number;
  /** Shares of the day's music with moods that are upbeat or energetic, and melancholic. */
  upbeat: number | null;
  melancholic: number | null;
}

/** A genre, kind or mood of music, by the hours behind it and its share of those labelled. */
export interface RhythmsShare {
  name: string;
  hours: number;
  share: number;
}

export interface RhythmsMoodWeek {
  start: string; // its Monday, or the month's first day
  valence: number;
  days: number;
  emotion: string | null;
}

/** How a month's mood and music moved together: Pearson's r over the days, said in a sentence. */
export interface RhythmsRelation {
  kind: "same day" | "music then mood" | "mood then music" | "with" | "next day with";
  music: string;
  r: number;
  n: number;
  /** How often chance alone would give an r this strong (Fisher's z); null with too few days. */
  p: number | null;
  notable: boolean;
  text: string;
}

/** A month's card: how it felt in the user's own writing, what they listened to and wrote. */
export interface RhythmsMonthCard {
  month: string; // YYYY-MM
  generated: string;
  complete: boolean; // false while the month is still going
  mood: {
    days: number; // days with a valence
    valence: number | null;
    labelled_days: number;
    top: { name: string; days: number; share: number; bright: boolean }[];
    tone: { brighter: number; mixed: number; heavier: number };
    arc: { weeks: RhythmsMoodWeek[]; best: RhythmsMoodWeek | null; hardest: RhythmsMoodWeek | null };
    variability: { sd: number | null; word: string | null };
    usual_sd: number | null;
    by_model: boolean;
  };
  music: {
    hours: number;
    music_hours: number;
    spoken_hours: number;
    plays: number;
    artists: number;
    top_artists: { name: string; hours: number }[];
    genres: RhythmsShare[]; // the model's labels, from the artists' names
    kinds: RhythmsShare[]; // MusicBrainz's genres
    moods: RhythmsShare[];
    labelled: number; // the share of music with a label
  };
  writing: {
    words: number;
    channels: { name: string; words: number; pieces: number }[];
    notes: { count: number; words: number };
    documents: { count: number; words: number }; // changed that month: not added to the words
    usual: number | null; // the median month of the year before
    usual_by_now: number | null; // the same share of it, for a month still going
    beside_usual: number | null; // 0.2: a fifth more
  };
  relations: RhythmsRelation[]; // the notable first
  story: { by: "model" | "numbers"; text: string };
  waits_on_model: boolean;
  days: RhythmsMonthDay[];
}

export interface RhythmsMonths {
  held: string[]; // months with messages, mail or plays, newest first
  cards: RhythmsMonthCard[]; // newest first
  local_model: boolean; // a model on this computer names each day's emotions
  musicbrainz: boolean; // artists' names are looked up there for genres
}

export interface RhythmsResponse {
  now: string;
  vault: VaultInfo;
  today: string;
  weeks: RhythmsWeek[]; // oldest first, from the first week with a record to this one
  months: RhythmsMonths;
  /** People and chats written to in each two weeks and month, by period: weeks can't be added up for it. */
  people: { "2w": Record<string, number>; "1m": Record<string, number> };
  channels: string[]; // the most messages first
  /** The share of music time whose artist has a genre and moods, and how many artists have one. */
  coverage: { share: number; artists: number; labelled: number };
  model: boolean;
  /** Plain lines on each range at each resolution, written with no model. */
  stands_out: Record<RhythmsRange, Record<RhythmsResolution, RhythmsLine[]>>;
  error: string | null;
}
