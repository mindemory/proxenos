"use client";

import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionButton } from "@/components/ActionButton";
import { shortDate } from "@/lib/format";
import type { ToldNote } from "@/lib/types";

/**
 * What the reader tells Proxenos that no message shows: a fact for now ("I'm not going to
 * Tuesday's visit"), which the task list and calendar follow, or a rule for everything it drafts
 * ("keep replies to my manager short"). Each can be removed again.
 */
export function ToldNotes({ now }: { now: string }) {
  const [notes, setNotes] = useState<ToldNote[]>([]);
  const [text, setText] = useState("");
  const [always, setAlways] = useState(false);
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");

  useEffect(() => {
    fetch("/api/told")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { notes: ToldNote[] } | null) => d && setNotes(d.notes))
      .catch(() => undefined);
  }, []);

  async function send(body: Record<string, unknown>) {
    setState("saving");
    try {
      const res = await fetch("/api/told", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(String(res.status));
      setNotes(((await res.json()) as { notes: ToldNote[] }).notes);
      setState("idle");
      return true;
    } catch {
      setState("error");
      return false;
    }
  }

  async function save() {
    if (!text.trim() || state === "saving") return;
    if (await send({ text, always })) {
      setText("");
      setAlways(false);
    }
  }

  return (
    <div className="mt-5 max-w-2xl">
      <label className="text-xs text-muted" htmlFor="told-note">
        Tell Proxenos: what your messages don&apos;t show (it updates your tasks and calendar), or a rule for everything it
        writes for you.
      </label>
      <div className="mt-1.5 flex items-start gap-2">
        <textarea
          id="told-note"
          rows={2}
          maxLength={1000}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setState("idle");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void save();
          }}
          placeholder="e.g. I'm not going to Tuesday's appointment; keep replies to my manager short"
          className="min-w-0 flex-1 resize-y rounded-xl border border-line-strong bg-bg p-2.5 text-sm text-ink leading-relaxed font-sans"
        />
        <ActionButton
          icon={Check}
          label={state === "saving" ? "Saving" : "Tell"}
          tone="accent"
          active={!!text.trim()}
          onClick={() => void save()}
        />
      </div>
      <label className="mt-1.5 inline-flex items-center gap-2 text-xs text-muted">
        <input type="checkbox" checked={always} onChange={(e) => setAlways(e.target.checked)} />
        Always: a rule for every draft, kept until you remove it
      </label>
      {state === "error" && <p className="mt-1 text-xs text-bad-ink">Couldn&apos;t save it. Try again.</p>}
      {notes.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {notes.map((n) => (
            <li key={n.at} className="flex items-start gap-2 text-sm text-ink/90">
              <span className="mt-0.5 shrink-0 rounded-md border border-line-strong px-1.5 text-[0.65625rem] uppercase tracking-wider text-muted">
                {n.always ? "Rule" : shortDate(n.at, now)}
              </span>
              <span className="min-w-0 flex-1 break-words">{n.text}</span>
              <button
                onClick={() => void send({ forget: n.at })}
                className="shrink-0 text-muted hover:text-ink"
                aria-label={`Remove: ${n.text}`}
                title="Remove"
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
