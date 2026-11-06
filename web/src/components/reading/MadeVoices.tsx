"use client";

import { Download, FileAudio, Mic, RotateCcw, Save, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { type Said, SaidLine } from "@/components/setup/parts";
import { setReading, useReading } from "@/lib/reading";
import { CLIP_MAX, CLIP_MIN, record, type Recording, toClip, useSpeechStatus } from "@/lib/speechClient";
import type { SpeechEngine, SpeechStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

type Local = ReturnType<typeof useSpeechStatus>;

const PILL =
  "inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3 py-1.5 text-[0.8125rem] leading-none whitespace-nowrap text-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50";

const NAMES: Record<SpeechEngine, string> = { natural: "the natural voice", own: "your voice" };

const note = "text-sm leading-relaxed text-muted";

const mb = (bytes: number) => `${Math.round(bytes / 1e6).toLocaleString()} MB`;

/**
 * What a voice made on this Mac still needs before it can read: a Mac with Apple silicon, the
 * speech extra installed, then its model downloaded once. Until then Listen reads with this
 * device's voice, and this says what to do; once it's all there, `children`.
 */
function Needs({ local, engine, children }: { local: Local; engine: SpeechEngine; children: React.ReactNode }) {
  const s = local.status;
  if (!s) {
    return <p className={note}>{local.error ? `Couldn't check this Mac: ${local.error}` : "Checking this Mac…"}</p>;
  }
  if (!s.supported) {
    return (
      <p className={note}>
        Voices made here need a Mac with Apple silicon, and this isn&apos;t one. Listen reads with this device&apos;s voice instead.
      </p>
    );
  }
  if (!s.installed) {
    return (
      <div className="space-y-2">
        <p className={note}>
          This part of Proxenos isn&apos;t installed on this Mac, so Listen reads with this device&apos;s voice. The desktop app
          doesn&apos;t include it. If you run Proxenos from source, you can add it once: in a terminal, in the Proxenos folder, run this.
        </p>
        <code className="num block break-all rounded-lg border border-line bg-bg px-3 py-2 text-xs text-ink">{s.install}</code>
        <button type="button" onClick={() => void local.reload()} className={PILL}>
          <RotateCcw size={13} aria-hidden="true" />
          Check again
        </button>
      </div>
    );
  }
  return (
    <>
      {!s.engines[engine].downloaded && <GetModel local={local} status={s} engine={engine} />}
      {children}
    </>
  );
}

/** Download an engine's model, once, with how far it's got. */
function GetModel({ local, status, engine }: { local: Local; status: SpeechStatus; engine: SpeechEngine }) {
  const [said, setSaid] = useState<Said>(null);
  const [busy, setBusy] = useState(false);
  const d = status.download;
  const mine = d?.engine === engine;
  const other = d?.state === "running" && !mine;
  const pct = mine && d?.total ? Math.min(100, Math.round(((d.done ?? 0) / d.total) * 100)) : null;
  if (mine && d?.state === "running") {
    return (
      <div className="space-y-1.5">
        <div
          role="progressbar"
          aria-label={`Downloading ${NAMES[engine]}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct ?? undefined}
          className="h-2 w-full max-w-sm overflow-hidden rounded-full bg-surface-2"
        >
          <div className={cn("h-full rounded-full bg-accent", pct === null && "w-1/4 animate-pulse")} style={pct === null ? undefined : { width: `${pct}%` }} />
        </div>
        <p className="text-xs text-muted" aria-live="polite">
          {d.total ? `${mb(d.done ?? 0)} of ${mb(d.total)}` : "Starting the download…"}
          {pct === 100 ? ". Getting it ready…" : ""}
        </p>
      </div>
    );
  }
  const get = async () => {
    setBusy(true);
    const answer = await local.getModel(engine);
    setSaid(answer.ok ? null : { ok: false, text: answer.message });
    setBusy(false);
  };
  return (
    <div className="space-y-2">
      <p className={note}>
        Its model, {status.engines[engine].size}, comes from Hugging Face once. After that it runs here with no connection, and
        nothing you hear is sent anywhere.
      </p>
      <PrimaryButton onClick={get} disabled={busy || other}>
        <Download size={14} aria-hidden="true" />
        {other ? "Another download is going" : `Download ${NAMES[engine]}`}
      </PrimaryButton>
      {mine && d?.state === "failed" && <SaidLine said={{ ok: false, text: d.message ?? "The download didn't finish." }} />}
      <SaidLine said={said} />
    </div>
  );
}

/** The natural voice: Kokoro, with a few of its voices to pick from. */
export function NaturalVoice({ local }: { local: Local }) {
  const r = useReading();
  const s = local.status;
  return (
    <Needs local={local} engine="natural">
      {s?.engines.natural.downloaded && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="min-w-0">
            <p className="text-sm text-ink">Natural voice</p>
            <p className="text-xs leading-relaxed text-muted">Made on this Mac by Kokoro, an open model. Nothing is sent anywhere.</p>
          </div>
          <select
            value={r.natural ?? s.default_voice}
            onChange={(e) => setReading({ natural: e.target.value })}
            aria-label="Natural voice"
            className="w-full max-w-[16rem] rounded-lg border border-line-strong bg-bg px-3 py-2 text-sm text-ink"
          >
            {s.voices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.accent})
              </option>
            ))}
          </select>
        </div>
      )}
    </Needs>
  );
}

/** Your own voice: a clip of you reading, kept in the vault, and the model that speaks like it. */
export function OwnVoice({ local }: { local: Local }) {
  return (
    <div className="space-y-4">
      <p className={note}>
        Listen can read in your own voice, made on this Mac from a short clip of you reading. It copies only your own voice, from a
        clip you record of yourself. The clip stays on this computer, in your vault (<code className="num">state/speech/</code>),
        readable only by you; it&apos;s never sent anywhere, and you can delete it whenever you like.
      </p>
      <Needs local={local} engine="own">
        <Clip local={local} />
      </Needs>
    </div>
  );
}

type Take = { wav: Blob; seconds: number; url: string; recorded: boolean };

/** The clip: what's kept, or a way to record one (or pick a recording), hear it, and keep it. */
function Clip({ local }: { local: Local }) {
  const s = local.status;
  const [again, setAgain] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const [busy, setBusy] = useState(false);
  if (!s) return null;
  const kept = s.clip;

  if (kept && !again) {
    const when = kept.at ? new Date(kept.at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : null;
    const remove = async () => {
      setBusy(true);
      const answer = await local.deleteClip();
      setSaid({ ok: answer.ok, text: answer.ok ? "Your clip is deleted." : answer.message });
      setBusy(false);
      setConfirm(false);
    };
    return (
      <div className="space-y-3">
        <p className="text-sm text-ink">
          Your clip: {kept.seconds ?? "?"} seconds{when ? `, saved ${when}` : ""}.
        </p>
        {confirm ? (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-bad-line bg-bad-bg px-3.5 py-2.5 text-sm text-bad-ink">
            <span className="min-w-0 flex-1">Delete your clip? Listen goes back to another voice until you record a new one.</span>
            <button
              type="button"
              disabled={busy}
              onClick={remove}
              className="rounded-full bg-bad-ink px-3 py-1 text-[0.8125rem] font-medium text-bg disabled:opacity-50"
            >
              Delete
            </button>
            <button type="button" onClick={() => setConfirm(false)} className="text-[0.8125rem] text-bad-ink/80 hover:text-bad-ink">
              Keep
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setAgain(true)} className={PILL}>
              <Mic size={13} aria-hidden="true" />
              Record a new one
            </button>
            <button type="button" onClick={() => setConfirm(true)} className={cn(PILL, "hover:text-bad-ink")}>
              <Trash2 size={13} aria-hidden="true" />
              Delete your clip
            </button>
          </div>
        )}
        <SaidLine said={said} />
      </div>
    );
  }

  return (
    <Recorder
      passage={s.passage}
      onCancel={kept ? () => setAgain(false) : undefined}
      onKeep={async (take, text) => {
        const answer = await local.saveClip(take.wav, text);
        if (answer.ok) setAgain(false);
        setSaid(answer.ok ? { ok: true, text: "Your clip is kept on this computer." } : { ok: false, text: answer.message });
        return answer.ok;
      }}
      said={said}
    />
  );
}

function Recorder({
  passage,
  onKeep,
  onCancel,
  said,
}: {
  passage: string;
  onKeep: (take: Take, text: string | null) => Promise<boolean>;
  onCancel?: () => void;
  said: Said;
}) {
  const [recording, setRecording] = useState<Recording | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [take, setTake] = useState<Take | null>(null);
  const [text, setText] = useState(passage);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(0);

  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => setSeconds((Date.now() - started.current) / 1000), 250);
    return () => window.clearInterval(timer);
  }, [recording]);
  // Leaving Settings while recording drops the recording and lets go of the microphone.
  useEffect(() => () => recording?.cancel(), [recording]);
  useEffect(() => () => void (take && URL.revokeObjectURL(take.url)), [take]);

  const use = async (blob: Blob, recorded: boolean) => {
    try {
      const clip = await toClip(blob);
      if (clip.seconds < CLIP_MIN) setProblem(`That's ${clip.seconds} seconds; read the whole passage, about 15 seconds.`);
      else if (clip.seconds > CLIP_MAX) setProblem(`That's ${clip.seconds} seconds; a clip can be at most ${CLIP_MAX}.`);
      else {
        setProblem(null);
        setTake({ ...clip, url: URL.createObjectURL(clip.wav), recorded });
        if (recorded) setText(passage);
      }
    } catch {
      setProblem("This page couldn't read that recording. Record again here, or pick a WAV or MP3 file.");
    }
  };
  const begin = async () => {
    setProblem(null);
    setTake(null);
    let r: Recording;
    try {
      r = await record(CLIP_MAX);
    } catch {
      setProblem("The microphone isn't available. Allow it for Proxenos (or your browser) in your computer's privacy settings, or pick a recording instead.");
      return;
    }
    started.current = Date.now();
    setSeconds(0);
    setRecording(r);
    void r.done.then((blob) => {
      setRecording(null);
      if (blob) void use(blob, true);
    });
  };
  const keep = async () => {
    if (!take) return;
    setBusy(true);
    const ok = await onKeep(take, take.recorded ? passage : text.trim() || null);
    setBusy(false);
    if (ok) setTake(null);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <p className="text-sm text-ink">Read this aloud, at your usual pace, somewhere quiet:</p>
        <blockquote className="rounded-xl border border-line bg-surface-2 px-4 py-3 text-[0.9375rem] leading-relaxed text-ink">{passage}</blockquote>
      </div>

      {recording ? (
        <div className="flex flex-wrap items-center gap-3">
          <PrimaryButton onClick={() => recording.stop()}>
            <Square size={12} aria-hidden="true" />
            Stop
          </PrimaryButton>
          <span className="num text-sm text-ink" role="timer" aria-live="off">
            0:{String(Math.floor(seconds)).padStart(2, "0")}
          </span>
          <span className="text-xs text-muted">Recording. It stops by itself at {CLIP_MAX} seconds.</span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <PrimaryButton onClick={() => void begin()}>
            <Mic size={14} aria-hidden="true" />
            {take ? "Record again" : "Record"}
          </PrimaryButton>
          <label className={cn(PILL, "cursor-pointer focus-within:ring-2 focus-within:ring-accent")}>
            <FileAudio size={13} aria-hidden="true" />
            Pick a recording
            <input
              type="file"
              accept="audio/*"
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void use(file, false);
              }}
            />
          </label>
          {onCancel && (
            <button type="button" onClick={onCancel} className="rounded-full px-2 py-1.5 text-sm text-muted hover:text-ink">
              Cancel
            </button>
          )}
        </div>
      )}

      {take && (
        <div className="space-y-3 rounded-xl border border-line px-3.5 py-3">
          <p className="text-sm text-ink">Listen back: {take.seconds} seconds.</p>
          {/* eslint-disable-next-line jsx-a11y/media-has-caption -- the user's own reading of the passage shown above */}
          <audio controls src={take.url} className="w-full max-w-sm" />
          {!take.recorded && (
            <label className="block space-y-1">
              <span className="text-sm text-ink">What it says</span>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                className="w-full rounded-lg border border-line-strong bg-bg px-3 py-2 text-sm text-ink"
              />
              <span className="block text-xs text-muted">Word for word, so your voice comes out right.</span>
            </label>
          )}
          <PrimaryButton onClick={() => void keep()} disabled={busy || (!take.recorded && !text.trim())}>
            <Save size={14} aria-hidden="true" />
            {busy ? "Keeping…" : "Keep this clip"}
          </PrimaryButton>
        </div>
      )}
      {problem && <SaidLine said={{ ok: false, text: problem }} />}
      <SaidLine said={said} />
    </div>
  );
}
