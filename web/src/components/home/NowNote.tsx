"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";

import { ActionButton } from "@/components/ActionButton";

/**
 * "Right now": a line about how the reader is and what's on their mind. The next two days of
 * drafts take it into account (tone, how much they take on); it never goes into a message.
 */
export function NowNote() {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    fetch("/api/now")
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { text: string } | null) => {
        if (d) {
          setText(d.text);
          setSaved(d.text);
        }
      })
      .catch(() => undefined);
  }, []);

  async function save() {
    setState("saving");
    try {
      const res = await fetch("/api/now", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setSaved(text.trim());
      setState("saved");
    } catch {
      setState("error");
    }
  }

  const changed = saved !== null && text.trim() !== saved;
  return (
    <div className="mt-5 max-w-2xl">
      <label className="text-xs text-muted" htmlFor="now-note">
        Right now: how you are and what&apos;s on your mind. Drafts for the next two days take it into account.
      </label>
      <div className="mt-1.5 flex items-start gap-2">
        <textarea
          id="now-note"
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
          placeholder="e.g. tired today, keep things short; focused on the cookbook this week"
          className="min-w-0 flex-1 resize-y rounded-xl border border-line-strong bg-bg p-2.5 text-sm text-ink leading-relaxed font-sans"
        />
        <ActionButton
          icon={Check}
          label={state === "saving" ? "Saving" : state === "saved" && !changed ? "Saved" : "Save"}
          tone="accent"
          active={changed}
          onClick={() => void save()}
        />
      </div>
      {state === "error" && <p className="mt-1 text-xs text-bad-ink">Couldn&apos;t save it. Try again.</p>}
    </div>
  );
}
