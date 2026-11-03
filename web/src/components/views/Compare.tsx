"use client";

import { ChevronLeft, ChevronRight, LoaderCircle, Play, Scale } from "lucide-react";
import { useId, useState } from "react";

import { PrimaryButton } from "@/components/connect/parts";
import { ErrorBanner } from "@/components/EmptyState";
import { Listen } from "@/components/reading/Listen";
import { Field, inputClass, NOT_A_LOGIN } from "@/components/setup/parts";
import { useCompare } from "@/lib/compareClient";
import { plural, shortDate } from "@/lib/format";
import {
  COMPARE_MAX_ROUND,
  COMPARE_MIN_PICKS,
  COMPARE_ROUND,
  type CompareFared,
  type CompareItem,
  type CompareMessage,
  type ComparePick,
  type CompareResponse,
  type CompareResults,
  type SetupStatus,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const WHERE: Record<string, string> = {
  whatsapp: "WhatsApp",
  facebook: "Messenger",
  instagram: "Instagram",
  twitter: "X",
  linkedin: "LinkedIn",
  slack: "Slack",
  email: "Email",
};
const PICK_LABELS: Record<ComparePick, string> = { A: "Pick A", B: "Pick B", both: "Both fine", neither: "Neither" };
const PICKED: Record<ComparePick, string> = {
  A: "You picked A.",
  B: "You picked B.",
  both: "You said both were fine.",
  neither: "You said neither was.",
};
const EARLIER_SHOWN = 4; // of the conversation before what waited, the newest shown at first

const pct = (n: number | null) => (n === null ? "–" : `${Math.round(n * 100)}%`);

/** A model's name as the page shows it: a local one without "ollama:", a voice model as such. */
function modelLabel(name: string): string {
  if (name === "voice") return "your voice model";
  if (name.startsWith("voice:")) return `voice model ${name.slice(6).replace(/^ollama:/, "")}`;
  return name.replace(/^ollama:/, "");
}

/**
 * Which writes like you? Two models redraft the reader's own recent replies, each as the chat stood just before they
 * answered, so neither sees what they sent. The reader sees the two drafts as A and B, picks blind, and only then
 * learns which model wrote which. Opened from Settings, under the model; nothing loads until it's opened.
 */
export function Compare({ status }: { status: SetupStatus }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <div className="card space-y-4 p-4 sm:p-5">
      <p className="text-sm leading-relaxed text-muted">
        Two models write your replies in your {COMPARE_ROUND} most recent conversations again, each as the chat stood just before
        you answered, so neither sees what you sent. You read both as A and B and pick the one that sounds more like you. Which
        model wrote which shows only after you pick. Nothing is sent to anyone.
      </p>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panel}
        className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-3.5 py-1.5 text-sm text-muted transition-colors hover:text-ink"
      >
        <Scale size={14} aria-hidden="true" />
        {open ? "Close" : "Compare two models"}
      </button>
      <div id={panel} hidden={!open}>
        {open && <CompareBody status={status} />}
      </div>
    </div>
  );
}

function CompareBody({ status }: { status: SetupStatus }) {
  const { data, error, clearError, show, start, pick, stop, starting } = useCompare();
  if (!data) {
    return error ? (
      <ErrorBanner message={`Couldn't read the comparisons: ${error}`} />
    ) : (
      <p role="status" className="text-sm text-muted">
        Loading…
      </p>
    );
  }
  const running = data.job?.state === "running";
  const round = data.round;
  // This page's new round, before its file is there: its replies are still being found.
  const finding = (starting || running) && (!round || Date.parse(round.started) < Date.parse(data.job?.started ?? "") - 2000);
  const drafting = running || round?.status === "drafting";

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {drafting || finding ? (
        <Progress data={data} finding={finding} onStop={running ? stop : null} />
      ) : (
        <StartForm data={data} status={status} onStart={start} />
      )}
      {round && !finding && (
        <>
          <RoundHead data={data} onShow={show} />
          {data.results && data.results.picks > 0 && <Results results={data.results} title="How they did in this round" />}
          {data.pooled && data.pooled.picks > 0 && (
            <Results results={data.pooled} title={`In all ${data.pooled.rounds} rounds of these two`} />
          )}
          <Replies key={round.id} data={data} onPick={(item, choice) => pick(round.id, item, choice)} />
        </>
      )}
    </div>
  );
}

function StartForm({
  data,
  status,
  onStart,
}: {
  data: CompareResponse;
  status: SetupStatus;
  onStart: (model: string, n: number) => Promise<boolean>;
}) {
  const setUp = data.setUp;
  const drafting = setUp?.drafting ?? (status.model.kind === "local" ? `ollama:${status.model.name}` : status.model.name);
  const options = [
    ...status.ollama.models.map((m) => ({ value: `ollama:${m}`, label: `${m}, on this computer` })),
    ...(setUp?.key ? [{ value: setUp.hosted, label: `${setUp.hosted}, through Anthropic` }] : []),
    ...(setUp?.voice ? [{ value: "voice", label: "your voice model, on this computer" }] : []),
  ].filter((o) => o.value !== drafting);
  const [model, setModel] = useState(options[0]?.value ?? "");
  const [n, setN] = useState(String(COMPARE_ROUND));
  const [busy, setBusy] = useState(false);
  const list = useId();
  const count = Number(n);
  const valid = model.trim() !== "" && Number.isInteger(count) && count >= 1 && count <= COMPARE_MAX_ROUND;
  const hosted = valid && !/^(ollama:|voice)/.test(model.trim());

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        setBusy(true);
        onStart(model.trim(), count).finally(() => setBusy(false));
      }}
      className="space-y-3"
    >
      <div className="grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_7rem_auto] sm:items-end">
        <Field label="Compare with">
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            list={list}
            placeholder="ollama:gemma4:26b"
            className={cn(inputClass, "num")}
            {...NOT_A_LOGIN}
          />
        </Field>
        <datalist id={list}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </datalist>
        <Field label="Replies">
          <input
            type="number"
            min={1}
            max={COMPARE_MAX_ROUND}
            value={n}
            onChange={(e) => setN(e.target.value)}
            className={cn(inputClass, "num")}
          />
        </Field>
        <PrimaryButton type="submit" disabled={busy || !valid}>
          <Play size={14} aria-hidden="true" />
          Start a round
        </PrimaryButton>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        Against your drafting model, <span className="num text-ink">{modelLabel(drafting)}</span>. A local model takes a minute
        or two a reply, so a round takes a while; you can pick as each reply is ready.
        {hosted && " The other model gets what a reply draft sends it: each conversation, with the same numbers and secrets blanked."}
      </p>
    </form>
  );
}

function Progress({ data, finding, onStop }: { data: CompareResponse; finding: boolean; onStop: (() => void) | null }) {
  const round = data.round;
  const total = (round?.n ?? 0) * 2;
  return (
    <div className="flex items-start gap-2.5 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-2.5 text-sm" role="status">
      <LoaderCircle size={16} className="mt-0.5 flex-shrink-0 animate-spin text-accent" aria-hidden="true" />
      <span className="min-w-0 flex-1 leading-relaxed text-ink">
        {finding || !round ? (
          "Finding your recent replies…"
        ) : (
          <>
            Drafting: <span className="num">{round.drafted}</span> of <span className="num">{total}</span> drafts written. Each reply
            shows below once both of its drafts are.
          </>
        )}
      </span>
      {onStop && (
        <button type="button" onClick={onStop} className="flex-shrink-0 text-muted underline-offset-2 hover:text-ink hover:underline">
          Stop
        </button>
      )}
    </div>
  );
}

function RoundHead({ data, onShow }: { data: CompareResponse; onShow: (round: string | null) => void }) {
  const round = data.round!;
  const [first, second] = round.models;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h3 className="text-lg text-ink">
          <span className="num">{first.label}</span> and <span className="num">{second.label}</span>
        </h3>
        {data.rounds.length > 1 && (
          <label className="inline-flex items-center gap-2 text-sm text-muted">
            <span>Round</span>
            <select
              value={round.id}
              onChange={(e) => onShow(e.target.value === data.rounds[0].id ? null : e.target.value)}
              className="num rounded-full border border-line-strong bg-surface px-3 py-1 text-sm text-ink hover:border-accent/40"
            >
              {data.rounds.map((r) => (
                <option key={r.id} value={r.id}>
                  {shortDate(r.started, data.now)}: {r.models.join(" and ")}, {r.picked} of {r.n} picked
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <p className="text-sm text-muted">
        Started {shortDate(round.started, data.now)}, {plural(round.n, "reply", "replies")}.{" "}
        {first.where === "Anthropic" || second.where === "Anthropic"
          ? "One of them runs at Anthropic."
          : "Both run on this computer."}
      </p>
      {(round.status === "failed" || round.status === "stopped") && (
        <p className="text-sm text-bad-ink" role="alert">
          This round stopped before every draft was written{round.error ? `: ${round.error}` : "."} The replies drafted by both
          can still be picked.
        </p>
      )}
    </div>
  );
}

function Results({ results, title }: { results: CompareResults; title: string }) {
  const head = useId();
  return (
    <section aria-labelledby={head} className="space-y-3 rounded-xl border border-line bg-surface-2/40 p-3.5">
      <h4 id={head} className="smallcaps">
        {title}
      </h4>
      <ul className="space-y-3">
        {results.models.map((m) => (
          <Fared key={m.name} m={m} picks={results.picks} />
        ))}
      </ul>
      <p className="text-sm text-muted">
        {plural(results.picks, "pick")}: {results.both} both fine, {results.neither} neither.{" "}
        {results.picks < COMPARE_MIN_PICKS ? (
          <span className="text-warn-ink">
            Under about {COMPARE_MIN_PICKS} picks this tells little, as the wide ranges show. Another round adds more.
          </span>
        ) : (
          results.note
        )}
      </p>
    </section>
  );
}

function Fared({ m, picks }: { m: CompareFared; picks: number }) {
  return (
    <li className="space-y-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="num text-ink">{m.label}</span>
        <span className="text-sm text-muted">
          won <span className="num text-ink">{m.won}</span> of <span className="num">{picks}</span> ({pct(m.share)}), likely between{" "}
          <span className="num">{pct(m.low)}</span> and <span className="num">{pct(m.high)}</span>
        </span>
      </div>
      {/* The share and its 95% range on a line from 0 to 100%; the sentence above says the same. */}
      <div className="relative h-2 rounded-full bg-line" aria-hidden="true">
        {m.low !== null && m.high !== null && (
          <div
            className="absolute inset-y-0 rounded-full bg-accent/30"
            style={{ left: `${m.low * 100}%`, width: `${Math.max((m.high - m.low) * 100, 1)}%` }}
          />
        )}
        {m.share !== null && (
          <div className="absolute inset-y-[-2px] w-1 rounded-full bg-accent" style={{ left: `calc(${m.share * 100}% - 2px)` }} />
        )}
      </div>
      <p className="text-xs text-muted">
        {m.closeness === null ? (
          "No drafts to measure yet."
        ) : (
          <>
            On average <span className="num text-ink">{pct(m.closeness)}</span> of its drafts was in what you sent.
          </>
        )}
        {m.failed > 0 && ` ${plural(m.failed, "draft")} failed.`}
      </p>
    </li>
  );
}

function Replies({ data, onPick }: { data: CompareResponse; onPick: (item: number, choice: ComparePick) => Promise<boolean> }) {
  const items = data.items;
  const firstOpen = items.find((i) => i.state === "ready" && !i.pick) ?? items.find((i) => i.state === "ready") ?? items[0];
  const [shown, setShown] = useState<number | null>(null);
  if (!items.length) return null;
  const index = Math.max(
    0,
    items.findIndex((i) => i.n === (shown ?? firstOpen.n)),
  );
  const item = items[index];
  const picked = items.filter((i) => i.pick).length;
  const ready = items.filter((i) => i.state === "ready").length;

  return (
    <section aria-label="The replies" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-sm text-muted">
          <span className="num text-ink">{picked}</span> of <span className="num">{ready}</span> ready picked
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShown(items[index - 1].n)}
            disabled={index === 0}
            className="inline-flex items-center gap-1 rounded-full border border-line-strong px-3 py-1 text-sm text-muted hover:text-ink disabled:opacity-40"
          >
            <ChevronLeft size={14} aria-hidden="true" />
            Previous
          </button>
          <span className="num text-sm text-muted" aria-live="polite">
            Reply {item.n} of {items.length}
          </span>
          <button
            type="button"
            onClick={() => setShown(items[index + 1].n)}
            disabled={index === items.length - 1}
            className="inline-flex items-center gap-1 rounded-full border border-line-strong px-3 py-1 text-sm text-muted hover:text-ink disabled:opacity-40"
          >
            Next
            <ChevronRight size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
      <Reply
        key={item.n}
        item={item}
        round={data.round!.id}
        now={data.now}
        onPick={(n, choice) => {
          setShown(n); // stay on it, to see which model wrote which
          return onPick(n, choice);
        }}
      />
    </section>
  );
}

function Reply({
  item,
  round,
  now,
  onPick,
}: {
  item: CompareItem;
  round: string;
  now: string;
  onPick: (item: number, choice: ComparePick) => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  const [showSent, setShowSent] = useState(false);
  const [earlier, setEarlier] = useState(false);
  const head = useId();
  const choose = (choice: ComparePick) => {
    setBusy(true);
    onPick(item.n, choice).finally(() => setBusy(false));
  };
  const hidden = earlier ? 0 : Math.max(0, item.recent.length - EARLIER_SHOWN);

  return (
    <article aria-labelledby={head} className="space-y-4">
      <h4 id={head} className="text-base text-ink">
        {item.name}, on {WHERE[item.source] ?? item.source}{" "}
        <span className="text-sm text-muted">· you answered {shortDate(item.replied, now)}</span>
      </h4>

      <div className="space-y-2">
        {hidden > 0 && (
          <button type="button" onClick={() => setEarlier(true)} className="text-sm text-accent hover:underline">
            Show {plural(hidden, "earlier message")}
          </button>
        )}
        <ol aria-label="The conversation before your reply" className="space-y-1.5">
          {item.recent.slice(hidden).map((m, i) => (
            <Message key={`r${i}`} m={m} name={item.name} />
          ))}
          {item.waiting.map((m, i) => (
            <Message key={`w${i}`} m={m} name={item.name} waiting />
          ))}
        </ol>
      </div>

      {item.state === "ready" && item.a !== null && item.b !== null ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <Draft side="A" text={item.a} id={`compare:${round}:${item.n}:A`} chosen={item.pick === "A"} />
            <Draft side="B" text={item.b} id={`compare:${round}:${item.n}:B`} chosen={item.pick === "B"} />
          </div>
          <div role="group" aria-label="Which sounds more like you?" className="flex flex-wrap items-center gap-2">
            <span className="mr-1 text-sm text-ink">Which sounds more like you?</span>
            {(Object.keys(PICK_LABELS) as ComparePick[]).map((p) => (
              <button
                key={p}
                type="button"
                disabled={busy}
                onClick={() => choose(p)}
                aria-pressed={item.pick === p}
                className={cn(
                  "rounded-full border px-3.5 py-1.5 text-sm transition-colors disabled:opacity-50",
                  item.pick === p
                    ? "border-accent bg-accent text-accent-ink"
                    : "border-line-strong text-muted hover:border-accent/40 hover:text-ink",
                )}
              >
                {PICK_LABELS[p]}
              </button>
            ))}
          </div>
          {item.pick && item.revealed && (
            <div className="space-y-2 rounded-xl border border-line bg-surface-2/40 p-3.5 text-sm" role="status">
              <p className="text-ink">
                {PICKED[item.pick]} A was <span className="num">{item.revealed.a}</span>
                {item.revealed.aCloseness !== null && ` (${pct(item.revealed.aCloseness)} of it in what you sent)`}; B was{" "}
                <span className="num">{item.revealed.b}</span>
                {item.revealed.bCloseness !== null && ` (${pct(item.revealed.bCloseness)})`}. You can change your pick.
              </p>
              <button
                type="button"
                onClick={() => setShowSent(!showSent)}
                aria-expanded={showSent}
                className="text-accent hover:underline"
              >
                {showSent ? "Hide what you sent" : "Show what you sent"}
              </button>
              {showSent && <p className="whitespace-pre-wrap rounded-lg bg-bg p-3 leading-relaxed text-ink">{item.revealed.sent}</p>}
            </div>
          )}
        </>
      ) : item.state === "failed" ? (
        <p className="text-sm text-muted">One of the two drafts couldn&apos;t be written, so this reply can&apos;t be picked.</p>
      ) : (
        <p className="text-sm text-muted">Not drafted by both yet.</p>
      )}
    </article>
  );
}

function Message({ m, name, waiting = false }: { m: CompareMessage; name: string; waiting?: boolean }) {
  return (
    <li className={cn("rounded-lg px-3 py-2 text-sm leading-relaxed", m.mine ? "ml-8 bg-accent/10" : "mr-8 bg-surface-2")}>
      <span className="block text-xs text-muted">
        {m.mine ? "You" : m.sender || name}
        {waiting && " · waiting for your reply"}
      </span>
      <span className="whitespace-pre-wrap break-words text-ink">{m.text.replace(/ \/ /g, "\n")}</span>
    </li>
  );
}

function Draft({ side, text, id, chosen }: { side: "A" | "B"; text: string; id: string; chosen: boolean }) {
  const head = useId();
  return (
    <section
      aria-labelledby={head}
      className={cn("space-y-2 rounded-xl border p-3.5", chosen ? "border-accent/60 bg-accent/5" : "border-line-strong")}
    >
      <div className="flex items-center justify-between gap-2">
        <h5 id={head} className="font-display text-xl text-ink">
          {side}
        </h5>
        <Listen id={id} text={text} what={`draft ${side}`} />
      </div>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{text}</p>
    </section>
  );
}
