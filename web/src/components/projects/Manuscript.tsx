"use client";

import { useState } from "react";
import {
  CopyPlus,
  Download,
  ExternalLink,
  FileText,
  ListPlus,
  MessageSquareText,
  PencilLine,
  Play,
  RotateCcw,
  Save,
  ScrollText,
  X,
} from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Command } from "@/components/EmptyState";
import { Bone } from "@/components/Skeleton";
import { formatDateTime, shortDate } from "@/lib/format";
import { useManuscript, useManuscriptDoc, useStepChanges } from "@/lib/projectsClient";
import {
  MANUSCRIPT_MAX_TEXT,
  STEP_MAX_TEXT,
  type DiffOp,
  type DocComment,
  type FileChanges,
  type ManuscriptEdit,
  type ManuscriptVersion,
  type StepAsk,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// A stretch that stayed longer than this folds away when only the changes are shown, keeping this
// much of it on either side of a change.
const FOLD_AT = 900;
const CONTEXT = 280;

function words(text: string): number {
  return text.match(/\w+/g)?.length ?? 0;
}

/** A stretch that stayed, folded to the ends that sit next to changes. */
function Folded({ text, first, last }: { text: string; first: boolean; last: boolean }) {
  const [open, setOpen] = useState(false);
  if (open || text.length <= FOLD_AT) return <span>{text}</span>;
  const head = first ? "" : text.slice(0, CONTEXT);
  const tail = last ? "" : text.slice(-CONTEXT);
  const hidden = text.slice(head.length, text.length - tail.length);
  return (
    <>
      {head && <span>{head}</span>}
      <button
        onClick={() => setOpen(true)}
        className="mx-0.5 my-1 inline-block rounded-md border border-line-strong px-2 py-0.5 align-middle font-sans text-xs text-muted transition-colors hover:text-ink"
      >
        ⋯ {words(hidden).toLocaleString("en-US")} words that stayed
      </button>
      {tail && <span>{tail}</span>}
    </>
  );
}

/** Text with its changes: what came in highlighted, what went struck through. */
export function Changes({ ops, kind, onlyChanges }: { ops: DiffOp[]; kind: FileChanges["kind"]; onlyChanges: boolean }) {
  const changed = ops.some((o) => o.op !== "same");
  return (
    <div
      className={cn(
        "whitespace-pre-wrap break-words text-ink",
        kind === "code" ? "font-mono text-xs leading-relaxed" : "font-display text-[1rem] leading-relaxed sm:text-[1.0625rem]",
      )}
    >
      {ops.map((o, i) =>
        o.op === "add" ? (
          <ins key={i} className="rounded-sm bg-ok-bg text-ok-ink no-underline">
            {o.text}
          </ins>
        ) : o.op === "del" ? (
          <del key={i} className="rounded-sm bg-bad-bg text-bad-ink line-through decoration-bad-ink/70">
            {o.text}
          </del>
        ) : onlyChanges && changed ? (
          <Folded key={i} text={o.text} first={i === 0} last={i === ops.length - 1} />
        ) : (
          <span key={i}>{o.text}</span>
        ),
      )}
    </div>
  );
}

function Counts({ changes }: { changes: FileChanges }) {
  if (changes.binary || changes.truncated) return null;
  return (
    <span className="num text-xs">
      <span className="text-ok-ink">+{changes.added.toLocaleString("en-US")}</span>{" "}
      <span className="text-bad-ink">−{changes.removed.toLocaleString("en-US")}</span>{" "}
      <span className="text-muted">{changes.unit}</span>
    </span>
  );
}

/** The changes, or why they aren't shown. */
function ChangesBox({ changes, onlyChanges }: { changes: FileChanges; onlyChanges: boolean }) {
  if (changes.binary) return <p className="text-sm text-muted">Not text, so not shown here.</p>;
  return (
    <div className="space-y-2">
      {changes.truncated && <p className="text-xs text-warn-ink">Too long to compare here: its start is shown as it is.</p>}
      <div className="max-h-[70vh] overflow-y-auto rounded-xl border border-line bg-surface p-3 sm:p-4">
        {changes.ops.length ? <Changes ops={changes.ops} kind={changes.kind} onlyChanges={onlyChanges} /> : <p className="text-sm text-muted">Empty.</p>}
      </div>
    </div>
  );
}

function OnlyChanges({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="inline-flex rounded-full border border-line-strong p-0.5 text-xs" role="group" aria-label="What to show">
      {[
        [true, "Changes"],
        [false, "Whole text"],
      ].map(([v, label]) => (
        <button
          key={String(v)}
          onClick={() => onChange(v as boolean)}
          aria-pressed={value === v}
          className={cn("rounded-full px-2.5 py-1 transition-colors", value === v ? "bg-surface-2 text-ink" : "text-muted hover:text-ink")}
        >
          {label as string}
        </button>
      ))}
    </div>
  );
}

interface AskProps {
  label: string;
  placeholder: string;
  /** A step is being taken, so another can't start now. */
  stepping: boolean;
  /** A decision or a change to a queue is going. */
  deciding: boolean;
  onAsk: (text: string, now: boolean) => Promise<boolean>;
}

/** Ask for a change in your own words: queue it, or have it done now. */
export function AskBox({ label, placeholder, stepping, deciding, onAsk }: AskProps) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const ready = text.trim() !== "" && text.length <= STEP_MAX_TEXT && !sending;
  const send = async (now: boolean) => {
    setSending(true);
    if (await onAsk(text.trim(), now)) setText("");
    setSending(false);
  };
  return (
    <div className="space-y-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        aria-label={label}
        placeholder={placeholder}
        className="w-full resize-y rounded-xl border border-line-strong bg-transparent p-3 text-[0.9375rem] leading-relaxed text-ink placeholder:text-faint focus:border-accent/40 focus:outline-none"
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <ActionButton icon={ListPlus} label="Queue it" tone="neutral" disabled={!ready || deciding} onClick={() => void send(false)} />
        <ActionButton icon={Play} label="Do it now" tone="accent" disabled={!ready || stepping} onClick={() => void send(true)} />
      </div>
    </div>
  );
}

function versionLabel(v: ManuscriptVersion): string {
  const waiting = v.proxenos ? (v.edit ? " · your edit, waiting" : " · a step, waiting") : "";
  const subject = v.subject.length > 60 ? `${v.subject.slice(0, 59)}…` : v.subject;
  return `${shortDate(v.date)} · ${subject} · ${v.short}${waiting}`;
}

function VersionPick({
  label,
  value,
  versions,
  onChange,
}: {
  label: string;
  value: string;
  versions: ManuscriptVersion[];
  onChange: (commit: string) => void;
}) {
  const known = versions.some((v) => v.commit === value);
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-muted sm:min-w-[16rem]">
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full min-w-0 truncate rounded-lg border border-line-strong bg-surface px-2 py-1.5 text-sm text-ink hover:border-accent/40"
      >
        {!known && value && <option value={value}>Where it started · {value.slice(0, 7)}</option>}
        {versions.map((v) => (
          <option key={v.commit} value={v.commit}>
            {versionLabel(v)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A comment in the manuscript's Google Doc: who, what they said, the passage it's on, and its replies. */
function DocNote({ c }: { c: DocComment }) {
  return (
    <li className={cn("space-y-1.5 px-3.5 py-3", c.resolved && "opacity-70")}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="text-sm font-medium text-ink">{c.author}</span>
        <span className="text-xs text-muted">
          {formatDateTime(c.created)}
          {c.resolved && " · resolved"}
        </span>
      </div>
      {c.quoted && (
        <blockquote className="line-clamp-4 border-l-2 border-line-strong pl-2.5 font-display text-sm italic leading-relaxed text-muted">
          {c.quoted}
        </blockquote>
      )}
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink/90">{c.content}</p>
      {c.replies.length > 0 && (
        <ul className="space-y-1.5 border-l border-line pl-3">
          {c.replies.map((r, i) => (
            <li key={i} className="text-sm leading-relaxed">
              <span className="text-xs text-muted">
                {r.author} · {formatDateTime(r.created)}
              </span>
              <p className="whitespace-pre-wrap break-words text-ink/90">{r.content}</p>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * The manuscript as a Google Doc in the user's own Drive, to edit, comment on and share with
 * co-authors there: made the first time it's opened, its changes brought back as a step waiting on
 * the user, and its comments, which are other people's words, shown here and never sent to a model.
 */
function GoogleDoc({ project, again, deciding, onPulled }: { project: string; again: string; deciding: boolean; onPulled: () => void }) {
  const { data, error, busy, actionError, clearActionError, open, fresh, pull, readComments } = useManuscriptDoc(
    project,
    true,
    again,
    onPulled,
  );
  const doc = data?.doc ?? null;
  const unresolved = data ? data.comments.filter((c) => !c.resolved).length : 0;

  return (
    <div className="space-y-3 border-t border-line pt-4">
      <p className="smallcaps inline-flex items-center gap-1.5">
        <FileText size={13} aria-hidden="true" />
        Google Docs
      </p>
      {error && <p className="text-sm text-bad-ink">{error}</p>}
      {actionError && (
        <p className="flex items-start justify-between gap-2 text-sm text-bad-ink" role="alert">
          <span className="min-w-0 break-words">{actionError}</span>
          <button onClick={clearActionError} aria-label="Dismiss" className="flex-shrink-0 rounded p-0.5 text-faint hover:text-ink">
            <X size={14} />
          </button>
        </p>
      )}
      {!data && !error && <Bone className="h-8 w-2/3" />}

      {data && data.accounts.length === 0 && !doc && (
        <p className="text-sm leading-relaxed text-muted">
          To edit it in Google Docs, comment on it and share it with co-authors, sign in to Google Docs once, on the Connect page or
          with <Command>proxenos auth gdocs NAME ADDRESS</Command>. That sign-in sees only the files Proxenos makes.
        </p>
      )}

      {data && data.accounts.length > 0 && !doc && (
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton icon={ExternalLink} label={busy === "open" ? "Making it…" : "Open in Google Docs"} tone="accent" disabled={busy !== null} onClick={open} />
          <p className="text-xs text-muted">
            Makes a Google Doc of it as it stands, in {data.accounts[0].address}&apos;s Drive. It&apos;s yours alone until you share it
            from Docs.
          </p>
        </div>
      )}

      {doc && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={doc.link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-accent/40 bg-accent/10 px-3 py-1.5 text-[0.8125rem] leading-none text-accent transition-colors hover:bg-accent/15"
            >
              <ExternalLink size={14} strokeWidth={2.25} aria-hidden="true" />
              Open in Google Docs
            </a>
            <ActionButton
              icon={Download}
              label={busy === "pull" ? "Bringing it back…" : "Bring back its changes"}
              tone="ok"
              disabled={busy !== null || deciding}
              onClick={pull}
            />
            <ActionButton
              icon={MessageSquareText}
              label={busy === "comments" ? "Reading…" : "Read comments"}
              tone="neutral"
              disabled={busy !== null}
              onClick={readComments}
            />
            <ActionButton
              icon={CopyPlus}
              label={busy === "fresh" ? "Making it…" : "A fresh copy"}
              tone="neutral"
              disabled={busy !== null}
              onClick={fresh}
            />
          </div>
          <p className="break-words text-xs leading-relaxed text-muted">
            Made from <span className="font-mono">{doc.branch}</span> at <span className="font-mono">{doc.commit.slice(0, 7)}</span>,{" "}
            {shortDate(doc.at)}, in {doc.address}&apos;s Drive. {doc.pulled ? `Last brought back ${formatDateTime(doc.pulled)}. ` : ""}
            Bring back its changes and only the paragraphs changed in Docs change, on a branch of their own that waits on you below.
          </p>
          <div className="space-y-2">
            <p className="text-xs text-muted">
              {data?.comments.length
                ? `${data.comments.length} ${data.comments.length === 1 ? "comment" : "comments"}, ${unresolved} open`
                : data?.commentsRead
                  ? "No comments yet"
                  : "Comments show here once they're read"}
              {data?.commentsRead ? `, read ${formatDateTime(data.commentsRead)}` : ""}. Your co-authors&apos; words are shown here
              only, never sent to a model.
            </p>
            {data && data.comments.length > 0 && (
              <ul className="max-h-[50vh] divide-y divide-line overflow-y-auto rounded-xl border border-line">
                {data.comments.map((c, i) => (
                  <DocNote key={c.id || i} c={c} />
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}

interface PanelProps {
  project: string;
  /** Changes when a step or an edit comes or goes, so the versions are read again. */
  again: string;
  stepping: boolean;
  deciding: boolean;
  onAsk: (text: string, now: boolean, ask: StepAsk) => Promise<boolean>;
  onSave: (edit: ManuscriptEdit) => Promise<boolean>;
  /** Changes were brought back from its Google Doc as a step: read the steps again. */
  onDocPulled: () => void;
  onClose: () => void;
}

/**
 * A project's manuscript: the old version, the new one and the changes between them, and two
 * ways to change it, both kept off the user's checkout: ask for a change, which a step does on a
 * branch of its own, or edit the text, which is saved on a branch of its own. Either waits on the
 * user below, to accept or discard, and so do the changes brought back from its Google Doc.
 */
export function ManuscriptPanel({ project, again, stepping, deciding, onAsk, onSave, onDocPulled, onClose }: PanelProps) {
  const [pick, setPick] = useState({ base: "", head: "" });
  const [onlyChanges, setOnlyChanges] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { data, error, loading } = useManuscript(project, true, pick.base, pick.head, again);
  const found = data?.manuscript ?? null;
  const head = data?.versions.find((v) => v.commit === data.head);

  const save = async () => {
    if (!data || !found || editing === null) return;
    setSaving(true);
    const ok = await onSave({ path: found.path, branch: found.branch, from: data.tip, text: editing });
    setSaving(false);
    if (ok) setEditing(null);
  };

  return (
    <section aria-label="Manuscript" className="card space-y-4 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="smallcaps inline-flex items-center gap-1.5">
            <ScrollText size={13} aria-hidden="true" />
            Manuscript
          </p>
          {found && (
            <p className="break-words text-sm text-muted">
              <span className="font-mono text-ink/90">{found.path}</span> on <span className="font-mono text-ink/90">{found.branch}</span>
              {!found.named && " · found in its history"}
            </p>
          )}
        </div>
        <button onClick={onClose} aria-label="Close the manuscript" className="flex-shrink-0 rounded p-1 text-faint transition-colors hover:text-ink">
          <X size={16} />
        </button>
      </div>

      {error && <p className="text-sm text-bad-ink">{error}</p>}
      {!data && loading && (
        <div className="space-y-2" aria-hidden="true">
          <Bone className="h-4 w-1/2" />
          <Bone className="h-24 w-full" />
        </div>
      )}
      {data && !found && <p className="text-sm leading-relaxed text-muted">{data.why}</p>}

      {data && found && editing === null && (
        <>
          <div className={cn("space-y-3 transition-opacity", loading && "opacity-60")} aria-busy={loading}>
            <div className="flex flex-wrap items-end gap-3">
              <VersionPick label="Old" value={data.base} versions={data.versions} onChange={(base) => setPick({ base, head: data.head })} />
              <VersionPick label="New" value={data.head} versions={data.versions} onChange={(h) => setPick({ base: "", head: h })} />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {data.base === data.head ? <span className="text-xs text-muted">The same version on both sides.</span> : <Counts changes={data} />}
                {(pick.base || pick.head) && (
                  <button onClick={() => setPick({ base: "", head: "" })} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
                    <RotateCcw size={12} aria-hidden="true" />
                    The newest
                  </button>
                )}
              </div>
              <OnlyChanges value={onlyChanges} onChange={setOnlyChanges} />
            </div>
            {head?.proxenos && (
              <p className="text-xs text-warn-ink">
                This version is {head.edit ? "your edit" : "a step"} on {head.branch}, waiting on you below: Accept merges it into {found.branch}.
              </p>
            )}
            <ChangesBox changes={data} onlyChanges={onlyChanges} />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ActionButton
              icon={PencilLine}
              label="Edit"
              tone="neutral"
              disabled={!data.editable || deciding}
              onClick={() => setEditing(data.text)}
            />
            <p className="text-xs text-muted">
              {data.editable
                ? `Your edit is saved on a branch of its own from ${found.branch}, never on your checkout, and waits on you as a step.`
                : data.truncated
                  ? "Too long to edit here."
                  : "Pick the newest version on the right to edit it."}
            </p>
          </div>

          <div className="space-y-2">
            <p className="smallcaps">Ask for a change</p>
            <AskBox
              label={`A change to ${found.path}`}
              placeholder="In your words: “Tighten the discussion and cite the 2019 study in the methods.” A step does it on a branch from the manuscript's, for you to see and accept."
              stepping={stepping}
              deciding={deciding}
              onAsk={(text, now) => onAsk(text, now, { base: found.branch, manuscript: { path: found.path, branch: found.branch } })}
            />
          </div>

          <GoogleDoc project={project} again={again} deciding={deciding} onPulled={onDocPulled} />
        </>
      )}

      {data && found && editing !== null && (
        <div className="space-y-3">
          <textarea
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
            aria-label={`Edit ${found.path}`}
            spellCheck
            className="h-[60vh] w-full resize-y rounded-xl border border-line-strong bg-surface p-3 font-mono text-[0.8125rem] leading-relaxed text-ink focus:border-accent/40 focus:outline-none"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted">
              {editing.length > MANUSCRIPT_MAX_TEXT
                ? `Too long: keep it to ${MANUSCRIPT_MAX_TEXT.toLocaleString("en-US")} characters.`
                : `Save commits it on a new branch from ${found.branch} at ${data.tip.slice(0, 7)}. Your checkout isn't touched.`}
            </p>
            <div className="flex flex-wrap gap-2">
              <ActionButton icon={X} label="Cancel" tone="neutral" disabled={saving} onClick={() => setEditing(null)} />
              <ActionButton
                icon={Save}
                label={saving ? "Saving…" : "Save"}
                tone="ok"
                disabled={saving || deciding || editing === data.text || editing.length > MANUSCRIPT_MAX_TEXT}
                onClick={() => void save()}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/** Every file a step changed, from where it started: prose word by word, code line by line. */
export function StepChanges({ project, step }: { project: string; step: string }) {
  const { data, error, loading } = useStepChanges(project, step, true);
  const [onlyChanges, setOnlyChanges] = useState(true);
  if (error) return <p className="text-sm text-bad-ink">{error}</p>;
  if (!data || loading) {
    return (
      <div className="space-y-2" aria-hidden="true">
        <Bone className="h-4 w-1/3" />
        <Bone className="h-20 w-full" />
      </div>
    );
  }
  if (!data.files.length) return <p className="text-sm text-muted">It changed no file.</p>;
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <OnlyChanges value={onlyChanges} onChange={setOnlyChanges} />
      </div>
      {data.files.map((f) => (
        <section key={f.path} className="space-y-1.5">
          <p className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <span className="min-w-0 break-all font-mono text-xs text-ink/90">{f.path}</span>
            <Counts changes={f} />
          </p>
          <ChangesBox changes={f} onlyChanges={onlyChanges} />
        </section>
      ))}
      {data.truncated && <p className="text-xs text-muted">It changed more files than are shown here.</p>}
    </div>
  );
}
