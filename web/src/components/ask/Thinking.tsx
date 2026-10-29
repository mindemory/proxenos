"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";

import { QuestionText, ShotCount } from "./parts";

/** How long it's been going, ticking every second: "48s", "3m 05s". */
function Elapsed({ since }: { since: number | null }) {
  const [now, setNow] = useState(() => Date.now());
  const [began] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const s = Math.max(0, Math.floor((now - (since ?? began)) / 1000));
  return <span className="num">{s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`}</span>;
}

interface ThinkingProps {
  /** When the ask began, in ms since 1970; null when that isn't known yet. */
  since: number | null;
  question: string;
  images: number;
  stopping: boolean;
  onStop: (() => void) | null;
}

/** What the page shows while an ask is being thought through: the model is slow, so say so. */
export function Thinking({ since, question, images, stopping, onStop }: ThinkingProps) {
  return (
    <section className="card flex flex-col gap-4 p-4 sm:p-5" role="status" aria-live="polite" aria-label="Thinking it through">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <LoaderCircle size={17} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="flex flex-wrap items-baseline gap-x-2.5">
            <span className="title-2">Thinking it through</span>
            {/* Ticking every second: kept out of the live region, or a screen reader would read it out each time. */}
            <span className="text-sm text-muted" aria-hidden="true">
              <Elapsed since={since} />
            </span>
          </p>
          <p className="leading-relaxed text-muted">
            This can take a few minutes on your Mac&apos;s model. You can leave this page: the answer will be here when
            you come back.
          </p>
        </div>
      </div>
      {(question || images > 0) && (
        <div className="min-w-0 space-y-2 border-l-2 border-line-strong pl-3">
          {question && <QuestionText text={question} />}
          <ShotCount n={images} />
        </div>
      )}
      {onStop && (
        <div>
          <ActionButton icon={X} label={stopping ? "Stopping" : "Stop"} tone="bad" disabled={stopping} onClick={onStop} />
        </div>
      )}
    </section>
  );
}
