"use client";

import { Segmented } from "@/components/layout/Segmented";
import { Listen } from "@/components/reading/Listen";
import { NaturalVoice, OwnVoice } from "@/components/reading/MadeVoices";
import { useMedia } from "@/lib/hooks";
import {
  type Engine,
  type Face,
  RATE_MAX,
  RATE_MIN,
  setReading,
  type Spacing,
  type TextSize,
  type Theme,
  useReading,
} from "@/lib/reading";
import { DEVICE_CALM, DEVICE_CONTRAST } from "@/lib/readingScript";
import { useSpeech } from "@/lib/speech";
import { useSpeechStatus } from "@/lib/speechClient";
import { cn } from "@/lib/utils";

const SIZES: { id: TextSize; label: string }[] = [
  { id: "default", label: "Default" },
  { id: "large", label: "Large" },
  { id: "larger", label: "Larger" },
];

const FACES: { id: Face; label: string }[] = [
  { id: "default", label: "Default" },
  { id: "hyperlegible", label: "Hyperlegible" },
];

const SPACINGS: { id: Spacing; label: string }[] = [
  { id: "normal", label: "Normal" },
  { id: "relaxed", label: "Relaxed" },
];

const THEMES: { id: Theme; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "system", label: "Match device" },
];

const ENGINES: { id: Engine; label: string }[] = [
  { id: "natural", label: "Natural" },
  { id: "own", label: "Your voice" },
  { id: "device", label: "This device's" },
];

const SAMPLE =
  "This is how Listen sounds. It reads with a voice made on this computer, and nothing you hear is sent anywhere.";

/**
 * One setting: its name and what it does on the left, its control on the right (below, when
 * narrow). Compact, for the Aa panel, drops the line on what it does unless `always`, and keeps a
 * switch (`inline`) beside its name.
 */
function Row({
  label,
  hint,
  children,
  compact,
  inline,
  always,
}: {
  label: string;
  hint: React.ReactNode;
  children: React.ReactNode;
  compact?: boolean;
  inline?: boolean;
  always?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex gap-2",
        compact && inline ? "flex-row items-center justify-between gap-4" : "flex-col",
        !compact && "sm:flex-row sm:items-center sm:justify-between sm:gap-4",
      )}
    >
      <div className="min-w-0">
        <p className="text-sm text-ink">{label}</p>
        {(!compact || always) && <p className="text-xs leading-relaxed text-muted">{hint}</p>}
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  );
}

/** An on or off setting. Held on, and saying why, while the device itself asks for it. */
function Switch({ label, on, held, onChange }: { label: string; on: boolean; held: boolean; onChange: (on: boolean) => void }) {
  const checked = on || held;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={held}
      onClick={() => onChange(!on)}
      className={cn(
        "relative inline-flex h-7 w-12 flex-shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-70",
        checked ? "border-accent bg-accent" : "border-line-strong bg-surface-2",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-block h-5 w-5 rounded-full transition-transform",
          checked ? "translate-x-[1.375rem] bg-accent-ink" : "translate-x-1 bg-muted",
        )}
      />
    </button>
  );
}

/**
 * How the page looks on this device: text size, typeface, spacing, theme, contrast and motion.
 * `compact` drops the lines that say what each does, for the panel behind the header's Aa.
 */
export function ReadingControls({ compact = false }: { compact?: boolean }) {
  const r = useReading();
  const deviceContrast = useMedia(DEVICE_CONTRAST);
  const deviceCalm = useMedia(DEVICE_CALM);
  return (
    <div className={cn(compact ? "space-y-3.5" : "space-y-5")}>
      <Row compact={compact} label="Text size" hint="Makes every word bigger, with the room around it to match.">
        <Segmented label="Text size" tabs={SIZES} value={r.size} onChange={(size) => setReading({ size })} />
      </Row>
      <Row
        compact={compact}
        label="Typeface"
        hint="Atkinson Hyperlegible, from the Braille Institute, draws letters that are easy to mix up (I, l and 1; O and 0) so they look different."
      >
        <Segmented label="Typeface" tabs={FACES} value={r.face} onChange={(face) => setReading({ face })} />
      </Row>
      <Row compact={compact} label="Spacing" hint="More room between lines, and a little between letters and words.">
        <Segmented label="Spacing" tabs={SPACINGS} value={r.spacing} onChange={(spacing) => setReading({ spacing })} />
      </Row>
      <Row compact={compact} label="Theme" hint="Light is dark text on a soft off-white. Match device follows this device's light or dark setting.">
        <Segmented label="Theme" tabs={THEMES} value={r.theme} onChange={(theme) => setReading({ theme })} />
      </Row>
      <Row
        compact={compact}
        inline
        always={deviceContrast}
        label="More contrast"
        hint={
          deviceContrast
            ? "On, because this device asks for more contrast."
            : "Black and white, with stronger lines and borders, in either theme."
        }
      >
        <Switch label="More contrast" on={r.contrast} held={deviceContrast} onChange={(contrast) => setReading({ contrast })} />
      </Row>
      <Row
        compact={compact}
        inline
        always={deviceCalm}
        label="Less motion"
        hint={deviceCalm ? "On, because this device asks for reduced motion." : "Nothing slides, fades or shimmers: it just appears."}
      >
        <Switch label="Less motion" on={r.calm} held={deviceCalm} onChange={(calm) => setReading({ calm })} />
      </Row>
    </div>
  );
}

/**
 * How Listen reads: with which voice (a natural one or the user's own, made on this Mac, or this
 * device's), at what speed, with a sentence to try them on.
 */
export function VoiceControls() {
  const r = useReading();
  const speech = useSpeech();
  const local = useSpeechStatus();
  const known = r.voice !== null && speech.voices.some((v) => v.id === r.voice);
  return (
    <div className="space-y-5">
      <Row
        label="Voice"
        hint="Natural and Your voice are made on this Mac; This device's is the browser's own. Nothing is sent anywhere, and when one made here can't read, this device's does."
      >
        <Segmented label="Voice" tabs={ENGINES} value={r.engine} onChange={(engine) => setReading({ engine })} />
      </Row>
      {r.engine === "natural" && <NaturalVoice local={local} />}
      {r.engine === "own" && <OwnVoice local={local} />}
      {r.engine === "device" &&
        (speech.available ? (
          <Row label="Device voice" hint="Only voices on this device are listed, so what's read never leaves it.">
            <select
              value={known ? (r.voice ?? "") : ""}
              onChange={(e) => setReading({ voice: e.target.value || null })}
              aria-label="Device voice"
              className="w-full max-w-[16rem] rounded-lg border border-line-strong bg-bg px-3 py-2 text-sm text-ink"
            >
              <option value="">This device&apos;s voice</option>
              {speech.voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.lang})
                </option>
              ))}
            </select>
          </Row>
        ) : (
          <p className="text-sm leading-relaxed text-muted">
            This browser has no voice that reads on this device, so Listen doesn&apos;t show. Safari, and Chrome or Edge with the
            system&apos;s voices, have one; or pick Natural.
          </p>
        ))}
      <Row label="Reading speed" hint="Slower gives more time to take each sentence in.">
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={RATE_MIN}
            max={RATE_MAX}
            step={0.05}
            value={r.rate}
            onChange={(e) => setReading({ rate: Number(e.target.value) })}
            aria-label="Reading speed"
            aria-valuetext={`${r.rate.toFixed(2)} times`}
            className="w-40 min-w-0 shrink accent-[var(--c-accent)]"
          />
          <span className="num w-12 text-right text-sm text-ink">{r.rate.toFixed(2)}×</span>
        </div>
      </Row>
      <Listen id="reading-sample" text={SAMPLE} label="Try it" what="a sentence in this voice, at this speed" />
    </div>
  );
}
