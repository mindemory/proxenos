"use client";

import { useCallback, useEffect, useState } from "react";

import { AskCard } from "@/components/ask/AskCard";
import { Composer } from "@/components/ask/Composer";
import { Thinking } from "@/components/ask/Thinking";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import type { View } from "@/components/layout/nav";
import { Bone } from "@/components/Skeleton";
import type { Attachment } from "@/lib/askImages";
import { useAsk } from "@/lib/askClient";
import { errandFromAsk } from "@/lib/errandsClient";

// What was being written when the view was left, so coming back to it doesn't lose it; and what
// was last sent, to give back if that ask ends without an answer (a model that fell over, or a
// Stop), so it doesn't have to be written and pasted again.
interface Draft {
  text: string;
  shots: Attachment[];
}
let kept: Draft = { text: "", shots: [] };
let lastSent: Draft = { text: "", shots: [] };

/** Ask the twin anything, or paste a message it should reply to: it answers from your memory, the way you'd think it through. */
export function Ask({ onNavigate }: { onNavigate: (view: View) => void }) {
  const [text, setText] = useState(kept.text);
  const [shots, setShots] = useState<Attachment[]>(kept.shots);
  const [sending, setSending] = useState(false);
  const [deep, setDeep] = useState(false);

  const ended = useCallback((answered: boolean) => {
    if (answered) lastSent = { text: "", shots: [] };
    else {
      // Give the question back, unless something new is already being written.
      setText((t) => (t === "" ? lastSent.text : t));
      setShots((s) => (s.length === 0 ? lastSent.shots : s));
    }
  }, []);
  const { data, error, clearError, pending, stopping, flashId, send, again, stop } = useAsk(ended);
  const [handOffError, setHandOffError] = useState<string | null>(null);

  /** Carry out what an answer says to do, as an errand, and go to Errands to follow it. */
  const handOff = (question: string, answer: string) => {
    errandFromAsk(question, answer).then(
      () => onNavigate("errands"),
      (e: unknown) => setHandOffError(e instanceof Error ? e.message : String(e)),
    );
  };

  useEffect(() => {
    kept = { text, shots };
  }, [text, shots]);

  // A new answer comes into view: the question is above it, the thinking was in this spot.
  useEffect(() => {
    if (!flashId) return;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(`ask-${flashId}`)?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  }, [flashId]);

  const submit = async () => {
    setSending(true);
    const sent = { text: text.trim(), shots };
    const ok = await send(sent.text, sent.shots.map((s) => s.image), deep);
    setSending(false);
    if (ok) {
      lastSent = sent;
      setText("");
      setShots([]);
      setDeep(false);
    }
  };

  if (data && !data.vault.exists) return <NoVault path={data.vault.path} />;

  const working = data?.asks.find((a) => a.status === "working") ?? null;
  const thinking = pending !== null || working !== null;
  const since = pending?.since ?? (working ? Date.parse(working.at) || null : null);
  const earlier = (data?.asks ?? []).filter((a) => a !== working);
  const canStop = pending !== null || data?.job?.state === "running";

  return (
    <div className="space-y-6 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={data ? clearError : undefined} />}
      {handOffError && <ErrorBanner message={handOffError} onDismiss={() => setHandOffError(null)} />}

      {thinking ? (
        <Thinking
          since={since}
          question={pending?.question || working?.question || ""}
          images={pending?.images || working?.images || 0}
          deep={pending?.deep ?? working?.deep ?? false}
          stopping={stopping}
          onStop={canStop ? stop : null}
        />
      ) : (
        <Composer
          text={text}
          onText={setText}
          shots={shots}
          onShots={setShots}
          sending={sending}
          onSend={() => void submit()}
          deep={deep}
          onDeep={setDeep}
        />
      )}

      {data === null ? (
        error ? null : (
          <div className="card space-y-3 p-5" aria-hidden="true">
            <Bone className="h-4 w-1/4" />
            <Bone className="h-4 w-full" />
            <Bone className="h-4 w-4/5" />
          </div>
        )
      ) : earlier.length === 0 ? (
        !thinking && (
          <p className="max-w-2xl text-sm leading-relaxed text-muted">
            Ask what you&apos;d ask yourself, or paste a message with a screenshot of the chat. It answers quickly, from
            who you are and what&apos;s nearest in your memory; tick Think it through, or press it on an answer, for a
            deeper look that takes several minutes. When it&apos;s a message to you, a draft reply in your voice lands
            here and in Drafts. Nothing is ever sent for you.
          </p>
        )
      ) : (
        <section aria-label="Earlier questions" className="space-y-4">
          <p className="smallcaps">Recent</p>
          {earlier.map((a) => (
            <AskCard
              key={a.id}
              ask={a}
              now={data.now}
              flash={flashId === a.id}
              onDrafts={() => onNavigate("drafts")}
              onAgain={thinking ? null : () => void again(a)}
              onErrand={() => handOff(a.question, a.answer)}
            />
          ))}
        </section>
      )}
    </div>
  );
}
