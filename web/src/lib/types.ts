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

/** opened: the draft was opened in its app; sent: the reader says they sent it. Both are logged. */
export type DraftAction = "approve" | "discard" | "edit" | "copy" | "opened" | "sent";

export const DRAFT_ACTIONS: readonly DraftAction[] = ["approve", "discard", "edit", "copy", "opened", "sent"];

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
  status: string; // "draft", "approved", "discarded", "sent"
  body: string; // markdown
  found: string; // for a reply: what the twin's look through memory showed, "" when nothing
  asks: string[]; // for a reply: what only the reader can decide, as questions
}

export interface DraftsResponse {
  now: string;
  vault: VaultInfo;
  exists: boolean; // the drafts folder is present
  drafts: Draft[];
}

/** Where a draft's one-click action goes. "file" is a download. */
export type OpenTarget = "gmail" | "whatsapp" | "slack" | "linkedin" | "instagram" | "messenger" | "x" | "file";

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

/** The rule for one channel: whether it's allowed, and what its record must show first. */
export interface OutboxChannelRule {
  on: boolean;
  min_closeness: number; // 0.5 to 1: the mean of how close its drafts came to what was sent
  min_measured: number; // 1 to 100: how many drafts that mean needs behind it
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
  | { channel: OutboxChannel; on?: boolean; min_closeness?: number; min_measured?: number };

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
  /** Each channel's track record: replies measured, and how close they came on average (0 to 1). */
  closeness: Record<string, { n: number; mean: number }>;
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

export interface MailAccount {
  name: string; // GMAIL_<NAME>, lower case
  address: string;
  signIn: "google" | "app_password";
  lastRead: string | null;
}

export interface ConnectSource {
  id: string;
  how: ConnectHow;
  connected: boolean;
  lastRead: string | null; // newest change to its files under raw/
  /** What stops its button from working: "no_google_client", Beeper's "no_token", or WhatsApp's "missing" or "blocked". */
  problem: string | null;
  /** A handle, where one helps. Apple Mail's is the Python that needs Full Disk Access. */
  detail: string | null;
  accounts: MailAccount[]; // Gmail only
  workspaces: string[]; // Slack only: the workspaces slackdump is signed in to
}

/** What the page can start: a Gmail sign-in, a read of WhatsApp, or a Beeper token. One of each at a time. */
export type ConnectJobKind = "gmail" | "whatsapp" | "beeper";
export const CONNECT_JOB_KINDS: readonly ConnectJobKind[] = ["gmail", "whatsapp", "beeper"];

/** Every background command the server runs for the page, one of each kind at a time: those above, an ask, an errand, and a Send. */
export type JobKind = ConnectJobKind | "ask" | "errand" | "send";

export interface ConnectJob {
  kind: ConnectJobKind;
  state: "running" | "done" | "failed" | "stopped";
  /** The command's last line, with anything that looks like a token blanked. */
  message: string;
  account: string | null; // the address a sign-in is for
  started: string;
  finished: string | null;
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
  /** Why the sources couldn't be read, when they couldn't. */
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
export const ASK_MAX_IMAGES = 4;
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

// ── Errands ─────────────────────────────────────────────────────────────────
//
// From clones/errands/<id>.json, which `proxenos clone errands` writes: something to get done,
// carried as far as it goes without the user, each step on its thread, and the messages it wrote,
// each waiting on the user's Send.

export const ERRAND_MAX_GOAL = 2000;
export const ERRAND_MAX_MESSAGE = 20_000;

export type ErrandStatus = "working" | "ready" | "waiting" | "sent" | "failed" | "dropped";

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
  subject: string;
  body: string;
  /** The CV goes with it. */
  attach: boolean;
  state: "ready" | "waiting" | "sent";
  sentAt: string;
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
