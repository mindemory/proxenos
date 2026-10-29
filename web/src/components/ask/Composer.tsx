"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { ArrowUp, ImagePlus, X } from "lucide-react";

import { ActionButton } from "@/components/ActionButton";
import { Bone } from "@/components/Skeleton";
import { IMAGE_ACCEPT, prepareImage, type Attachment } from "@/lib/askImages";
import { ASK_MAX_IMAGES, ASK_MAX_TEXT } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ComposerProps {
  text: string;
  onText: (text: string) => void;
  shots: Attachment[];
  onShots: Dispatch<SetStateAction<Attachment[]>>;
  sending: boolean;
  onSend: () => void;
  /** Research it and think it through, rather than answer quickly. */
  deep: boolean;
  onDeep: (deep: boolean) => void;
}

/** Show the count of characters from this many on, so the limit isn't a surprise. */
const COUNT_FROM = ASK_MAX_TEXT - 2000;

/**
 * Where a question is written: text, and screenshots pasted into it, dropped on it or picked from
 * a file. Each screenshot is made small as it's added (see askImages.ts), so what shows here is
 * what will be sent.
 */
export function Composer({ text, onText, shots, onShots, sending, onSend, deep, onDeep }: ComposerProps) {
  const [processing, setProcessing] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Ready to type on a computer; on a phone, the keyboard waits until it's asked for.
    if (window.matchMedia("(pointer: fine)").matches) area.current?.focus({ preventScroll: true });
  }, []);

  const over = text.length - ASK_MAX_TEXT;
  const empty = text.trim() === "" && shots.length === 0;
  const canSend = !empty && over <= 0 && processing === 0 && !sending;

  const add = async (files: File[]) => {
    const room = ASK_MAX_IMAGES - shots.length - processing;
    if (files.length === 0) return;
    if (room <= 0) {
      setNotice(`A question takes up to ${ASK_MAX_IMAGES} screenshots.`);
      return;
    }
    const take = files.slice(0, room);
    setNotice(files.length > room ? `A question takes up to ${ASK_MAX_IMAGES} screenshots, so only the first ${room} were added.` : null);
    setProcessing((n) => n + take.length);
    const results = await Promise.allSettled(take.map(prepareImage));
    setProcessing((n) => n - take.length);
    const added = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    if (added.length) onShots((prev) => [...prev, ...added].slice(0, ASK_MAX_IMAGES));
    const failure = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
    if (failure) setNotice(failure.reason instanceof Error ? failure.reason.message : "Couldn't read that picture.");
  };

  const send = () => {
    if (canSend) onSend();
  };

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  return (
    <section
      aria-label="Ask"
      className={cn("card p-3 transition-colors sm:p-4", dragging && "border-accent/60 bg-accent/5")}
      onDragEnter={(e) => {
        if (hasFiles(e)) setDragging(true);
      }}
      onDragOver={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(e) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        setDragging(false);
        const files = Array.from(e.dataTransfer.files);
        const pictures = files.filter((f) => f.type.startsWith("image/"));
        if (pictures.length === 0) setNotice("Only pictures can be added: PNG, JPEG or WebP.");
        else void add(pictures);
      }}
    >
      <label htmlFor="ask-text" className="sr-only">
        Your question
      </label>
      <textarea
        id="ask-text"
        ref={area}
        value={text}
        onChange={(e) => onText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
        onPaste={(e) => {
          const pictures = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
          if (pictures.length === 0) return;
          // A copied picture usually has no text with it; if it does, the text pastes as well.
          if (!e.clipboardData.getData("text/plain")) e.preventDefault();
          void add(pictures);
        }}
        rows={Math.min(14, Math.max(4, text.split("\n").length + 1))}
        spellCheck
        placeholder="Ask anything, or paste a message…"
        className="w-full resize-y rounded-xl border border-line-strong bg-bg p-3 font-sans text-base leading-relaxed text-ink sm:text-[15px]"
      />

      {(shots.length > 0 || processing > 0) && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Screenshots to send">
          {shots.map((s, i) => (
            <li key={s.key} className="relative h-16 w-16 overflow-hidden rounded-lg border border-line-strong bg-surface-2">
              {/* A small JPEG made in this page: next/image has nothing to optimise. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={s.preview} alt={`Screenshot ${i + 1}`} className="h-full w-full object-cover" />
              <button
                type="button"
                onClick={() => onShots((prev) => prev.filter((p) => p.key !== s.key))}
                aria-label={`Remove screenshot ${i + 1}`}
                className="absolute right-0.5 top-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-bg/85 text-ink transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-bg hover:text-bad-ink"
              >
                <X size={12} strokeWidth={2.5} />
              </button>
            </li>
          ))}
          {Array.from({ length: processing }, (_, i) => (
            <li key={`busy-${i}`} aria-hidden="true">
              <Bone className="h-16 w-16 rounded-lg" />
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <ActionButton icon={ImagePlus} label="Add screenshot" tone="neutral" onClick={() => picker.current?.click()} />
        <input
          ref={picker}
          type="file"
          accept={IMAGE_ACCEPT}
          multiple
          hidden
          onChange={(e) => {
            void add(Array.from(e.target.files ?? []));
            // So picking the same file again still counts as a change.
            e.target.value = "";
          }}
        />
        <p className="min-w-0 text-xs text-muted">
          {text.length >= COUNT_FROM ? (
            <span className={cn("num", over > 0 && "text-bad-ink")}>
              {text.length.toLocaleString("en-US")} / {ASK_MAX_TEXT.toLocaleString("en-US")}
              {over > 0 && ` · ${over.toLocaleString("en-US")} too many`}
            </span>
          ) : shots.length === 0 ? (
            "Paste or drop screenshots here."
          ) : (
            <span className="num">
              {shots.length} / {ASK_MAX_IMAGES}
            </span>
          )}
        </p>
        <div className="ml-auto flex items-center gap-3">
          <label
            className="inline-flex cursor-pointer select-none items-center gap-2 text-xs text-muted"
            title="Research your memory over several rounds and think before answering. Takes several minutes."
          >
            <input type="checkbox" checked={deep} onChange={(e) => onDeep(e.target.checked)} className="h-4 w-4 accent-accent" />
            Think it through
          </label>
          <span className="hidden text-xs text-muted sm:inline">⌘↵ asks</span>
          <ActionButton icon={ArrowUp} label={sending ? "Sending" : "Ask"} tone="accent" active={canSend} disabled={!canSend} onClick={send} />
        </div>
      </div>

      {notice && (
        <p className="mt-2 text-xs text-bad-ink" role="alert">
          {notice}
        </p>
      )}
    </section>
  );
}
