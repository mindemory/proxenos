"use client";

import { BellRing, Cpu, Globe, HardDrive, ShieldCheck, type LucideIcon } from "lucide-react";

import { Chip, copyFor, LastRead, StatePill } from "@/components/connect/parts";
import { ErrorBanner, NoVault } from "@/components/EmptyState";
import { CloudWarning, originLabel, secretLabel } from "@/components/setup/parts";
import { StatusSkeleton } from "@/components/Skeleton";
import { usePrivacy } from "@/lib/client";
import { formatDateTime, joinAnd, plural } from "@/lib/format";
import { VAULT_FOLDERS, type CallTotals, type PrivacyReport, type VaultFolder } from "@/lib/types";
import { cn } from "@/lib/utils";

const FOLDER_COPY: Record<VaultFolder, { label: string; note: string }> = {
  raw: { label: "Raw data", note: "every source, as monthly files" },
  memory: { label: "Memory index", note: "search by words and by meaning" },
  clones: { label: "The clones' work", note: "tasks, drafts, advice, the journal" },
  self: { label: "Self-model", note: "the picture of you" },
  observations: { label: "Notes", note: "what each month says about you" },
  state: { label: "State", note: "sync marks and the model-call log" },
  other: { label: "Everything else", note: "its history, the feed, the inbox" },
};

const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

function compact(n: number | null): string {
  return n === null ? "–" : COMPACT.format(n);
}

/** Bytes as Finder counts them: 1 KB is 1,000 bytes. */
function size(bytes: number): string {
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let n = bytes;
  let i = 0;
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000;
    i += 1;
  }
  return i === 0 ? plural(n, "byte") : `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

function took(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  return `${Math.round(seconds / 60)} min`;
}

function Section({
  icon: Icon,
  kicker,
  title,
  lead,
  children,
}: {
  icon: LucideIcon;
  kicker: string;
  title: string;
  lead: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3" aria-label={title}>
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <Icon size={17} aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <p className="smallcaps">{kicker}</p>
          <h2 className="title-2">{title}</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">{lead}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

/**
 * What happens to your data, drawn from what Proxenos does: what stays on this computer, what went
 * to a model in the last 30 days (from the line each call leaves, never its words), and what's read
 * from elsewhere. Read-only; nothing on it is a message, a prompt or a key.
 */
export function Privacy() {
  const { data, error } = usePrivacy();
  if (!data) return error ? <ErrorBanner message={`Couldn't load the privacy report: ${error}`} /> : <StatusSkeleton />;
  const { report } = data;
  if (!report) {
    return data.vault.exists ? <ErrorBanner message={data.error ?? "Couldn't read the privacy report."} /> : <NoVault path={data.vault.path} />;
  }

  return (
    <div className="space-y-10 p-4 pb-24 sm:p-6 md:pb-20">
      <section className="card flex items-start gap-3 p-5 sm:p-6">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <ShieldCheck size={17} aria-hidden="true" />
        </div>
        <p className="min-w-0 leading-relaxed text-muted">
          Drawn from what Proxenos does: the vault&apos;s folders, the line every model call leaves, and the sources it finds
          connected. Nothing on this page is a message, a prompt or a key.
        </p>
      </section>
      <StaysHere here={report.here} />
      <SentToModel sent={report.sent} />
      <Notices notices={report.notices} />
      <Fetched fetched={report.fetched} now={data.now} />
    </div>
  );
}

// ── Stays on this computer ──────────────────────────────────────────────────

function StaysHere({ here }: { here: PrivacyReport["here"] }) {
  const { vault } = here;
  const folders = VAULT_FOLDERS.filter((f) => vault.folders[f] > 0).sort((a, b) => vault.folders[b] - vault.folders[a]);
  return (
    <Section
      icon={HardDrive}
      kicker="Stays here"
      title="On this computer"
      lead={`Your records, notes, self-model, drafts and memory index live in the vault, a folder only you can open, and keys and sign-ins in the ${here.secretStore}.`}
    >
      <div className="card divide-y divide-line">
        <div className="space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <code className="num min-w-0 break-all text-ink">{vault.path}</code>
            <span className="num whitespace-nowrap text-sm text-muted">{size(vault.bytes)}</span>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            <StatePill on={vault.exists} tone={vault.exists ? undefined : "bad"} label={vault.exists ? "Found" : "Not there yet"} />
            <StatePill on={!vault.cloud} tone={vault.cloud ? "bad" : undefined} label={vault.cloud ? "A cloud syncs it" : "No cloud syncs it"} />
            {here.filevault !== null && (
              <StatePill
                on={here.filevault}
                tone={here.filevault ? undefined : "bad"}
                label={here.filevault ? "FileVault on: the disk is encrypted" : "FileVault off"}
              />
            )}
          </div>
          {here.filevault === false && (
            <p className="text-xs leading-relaxed text-warn-ink">
              Anyone who has this Mac&apos;s disk could read the vault. Turn FileVault on in System Settings, Privacy &amp;
              Security.
            </p>
          )}
          <CloudWarning where={vault.cloud} />
        </div>

        {folders.length > 0 && (
          <ul aria-label="The vault's folders" className="divide-y divide-line">
            {folders.map((f) => (
              <li key={f} className="flex items-baseline justify-between gap-3 px-4 py-2.5 sm:px-5">
                <span className="min-w-0 text-sm text-ink">
                  {FOLDER_COPY[f].label} <span className="text-xs text-muted">{FOLDER_COPY[f].note}</span>
                </span>
                <span className="num whitespace-nowrap text-sm text-muted">{size(vault.folders[f])}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2 p-4 sm:p-5">
          <p className="smallcaps">Keys and sign-ins</p>
          {here.secrets.length ? (
            <ul className="space-y-1 text-sm">
              {here.secrets.map((s) => (
                <li key={s.name} className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-ink">{secretLabel(s.name)}</span>
                  <span className="text-xs text-muted">{originLabel(s.from, here.secretStore)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">None saved.</p>
          )}
          <p className="text-xs leading-relaxed text-muted">
            By name only: this page never shows one. Settings are in <code className="num break-all">{here.settingsFile}</code>.
          </p>
        </div>
      </div>
    </Section>
  );
}

// ── Sent to a model ─────────────────────────────────────────────────────────

function where(t: CallTotals): string {
  if (t.hosted === 0) return "This computer";
  return t.hosted === t.calls ? "Anthropic" : `${t.hosted.toLocaleString()} at Anthropic`;
}

function SentToModel({ sent }: { sent: PrivacyReport["sent"] }) {
  const { model, totals, days } = sent;
  const hosted = sent.byWhere.Anthropic.calls;
  const partOf = new Map(sent.sends.flatMap((s) => s.steps.map((step) => [step, s.part] as const)));
  const lead =
    model.kind === "local"
      ? `Proxenos writes with ${model.name} on this computer, so what it reads stays here.`
      : model.kind === "api"
        ? `Proxenos writes with ${model.name} at Anthropic, under your key. Each part sends only what's listed below.`
        : "No model is set up, so nothing is drafted and nothing is sent.";
  const said =
    totals.calls === 0
      ? `No model calls in the last ${days} days.`
      : hosted === 0
        ? `Nothing went to a hosted model in the last ${days} days: all ${plural(totals.calls, "call")} ran on this computer.`
        : `${hosted.toLocaleString()} of ${plural(totals.calls, "call")} in the last ${days} days went to Anthropic.`;

  return (
    <Section icon={Cpu} kicker="Sent to a model" title="To a model" lead={lead}>
      <p
        role="status"
        className={cn(
          "rounded-xl border px-3.5 py-2.5 text-sm leading-relaxed",
          hosted === 0 ? "border-ok-line bg-ok-bg text-ok-ink" : "border-line-strong bg-surface text-ink",
        )}
      >
        {said}
        {model.voice && ` Reply drafts are written in your voice by ${model.voice}, on this computer.`}
      </p>
      {hosted > 0 && (
        <p className="px-1 text-sm leading-relaxed text-muted">
          Numbers and secrets blanked before sending: {sent.byWhere.Anthropic.redacted.toLocaleString()} in {days} days (card and
          Social Security numbers, one-time codes, passwords, keys and tokens, and bank account numbers).
        </p>
      )}

      {totals.calls > 0 && (
        <>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {[
              { label: "Calls", value: totals.calls.toLocaleString() },
              { label: "To Anthropic", value: hosted.toLocaleString() },
              { label: "Characters sent", value: compact(totals.sentChars) },
              { label: "Tokens in · out", value: `${compact(totals.tokensIn)} · ${compact(totals.tokensOut)}` },
            ].map((t) => (
              <div key={t.label} className="min-w-0 rounded-xl border border-line bg-bg px-3 py-2.5">
                <div className="num truncate text-xl">{t.value}</div>
                <div className="text-xs text-muted">{t.label}</div>
              </div>
            ))}
          </div>

          <div className="card overflow-x-auto">
            <table className="w-full min-w-[34rem] whitespace-nowrap text-sm">
              <caption className="sr-only">Model calls in the last {days} days, by part</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Part
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    Calls
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    Where
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    Characters sent
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    Tokens in · out
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Failed
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line border-t border-line">
                {sent.byStep.map((s) => (
                  <tr key={s.step}>
                    <th scope="row" className="px-4 py-2.5 text-left font-normal">
                      <span className="text-ink">{s.part ?? s.step}</span>
                      {s.part && <span className="num ml-2 text-xs text-faint">{s.step}</span>}
                    </th>
                    <td className="num px-3 py-2.5 text-right">{s.calls.toLocaleString()}</td>
                    <td className={cn("px-3 py-2.5", s.hosted ? "text-ink" : "text-muted")}>{where(s)}</td>
                    <td className="num px-3 py-2.5 text-right text-muted">{compact(s.sentChars)}</td>
                    <td className="num px-3 py-2.5 text-right text-muted">
                      {compact(s.tokensIn)} · {compact(s.tokensOut)}
                    </td>
                    <td className={cn("num px-4 py-2.5 text-right", s.failed ? "text-bad-ink" : "text-faint")}>{s.failed || "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="card p-4 sm:p-5">
        <p className="smallcaps mb-3">What each part sends</p>
        <dl className="grid gap-x-4 gap-y-2.5 text-sm sm:grid-cols-[9rem_minmax(0,1fr)]">
          {sent.sends.map((s) => (
            <div key={s.part} className="contents">
              <dt className="font-medium text-ink">{s.part}</dt>
              <dd className="leading-relaxed text-muted">{s.sends}</dd>
            </div>
          ))}
        </dl>
      </div>

      {sent.recent.length > 0 && (
        <div className="space-y-2">
          <p className="smallcaps px-1">The newest calls</p>
          <div className="card overflow-x-auto">
            <table className="w-full min-w-[36rem] whitespace-nowrap text-sm">
              <caption className="sr-only">The newest {sent.recent.length} model calls, newest first</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    When
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    Part
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    Where, which model
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    Sent
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    Back
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    Took
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line border-t border-line">
                {sent.recent.map((c, i) => (
                  <tr key={`${c.at}-${i}`}>
                    <td className="num whitespace-nowrap px-4 py-2 text-muted" title={c.at}>
                      {formatDateTime(c.at)}
                    </td>
                    <td className="px-3 py-2 text-ink">{partOf.get(c.step) ?? c.step}</td>
                    <td className="px-3 py-2" title={c.model}>
                      <span className={c.where === "Anthropic" ? "text-ink" : "text-muted"}>
                        {c.where === "Anthropic" ? "Anthropic" : "This computer"}
                      </span>
                      <span className="num ml-2 text-xs text-faint">{c.model.replace(/^ollama:/, "")}</span>
                    </td>
                    <td className="num px-3 py-2 text-right text-muted">
                      {compact(c.sentChars)}
                      {c.images ? ` + ${plural(c.images, "image")}` : ""}
                    </td>
                    <td className="num px-3 py-2 text-right">
                      {c.ok ? <span className="text-muted">{compact(c.answerChars)}</span> : <span className="text-bad-ink">failed</span>}
                    </td>
                    <td className="num whitespace-nowrap px-4 py-2 text-right text-muted">{took(c.seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="px-1 text-xs leading-relaxed text-muted">
        From <code className="num">state/model-calls.jsonl</code> in the vault: one line a call, with when, which part asked, the
        model, where it ran, how many characters went in and came back (tokens where the model counted them) and how many numbers
        and secrets were blanked, never the words.
      </p>
    </Section>
  );
}

// ── Notices on the phone ────────────────────────────────────────────────────

function Notices({ notices }: { notices: PrivacyReport["notices"] }) {
  const server = notices.server || "ntfy.sh";
  return (
    <Section
      icon={BellRing}
      kicker="Sent to your phone"
      title="Notices"
      lead="Off until you save a topic in Settings. Then, when something new waits on you, one short notice goes to your phone through ntfy, a push service, on its server or your own."
    >
      <div className="card space-y-1.5 p-4 sm:p-5">
        <StatePill on={notices.on} label={notices.on ? `On, through ${server}` : "Off"} />
        {notices.sends && <p className="text-sm leading-relaxed text-muted">{notices.sends}</p>}
        {notices.on && (
          <p className="text-sm leading-relaxed text-muted">
            {notices.quiet ? `None from ${notices.quiet.replace("-", " to ")}: one waits until then.` : "No quiet hours."}
          </p>
        )}
      </div>
    </Section>
  );
}

// ── Fetched from elsewhere ──────────────────────────────────────────────────

function Fetched({ fetched, now }: { fetched: PrivacyReport["fetched"]; now: string }) {
  const live = fetched.sources.filter((s) => s.how === "live");
  const given = fetched.sources.filter((s) => s.how !== "live");
  return (
    <Section
      icon={Globe}
      kicker="Fetched from elsewhere"
      title="From elsewhere"
      lead="The services you connected, read with your own sign-in, and the downloads and folders you gave it. Nothing else is read from outside, apart from the links below."
    >
      {live.length > 0 ? (
        <div className="card divide-y divide-line">
          {live.map((s) => (
            <div key={s.id} className="flex items-start gap-3.5 px-4 py-3.5">
              <Chip id={s.id} />
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium text-ink">{copyFor(s.id).label}</span>
                  <span className="text-xs text-muted">
                    <LastRead iso={s.lastRead} now={now} />
                  </span>
                </div>
                {(s.accounts.length > 0 || s.workspaces.length > 0) && (
                  <p className="num mt-0.5 break-all text-xs text-muted">
                    {[...s.accounts.map((a) => a.address || a.name), ...s.workspaces].join(", ")}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="card p-4 text-sm text-muted">Nothing is signed in yet. Connect lists every source.</p>
      )}
      {given.length > 0 && (
        <p className="px-1 text-sm leading-relaxed text-muted">
          Read from files you gave it: {joinAnd(given.map((s) => copyFor(s.id).label))}.
        </p>
      )}
      <div className="card space-y-1.5 p-4 sm:p-5">
        <StatePill on={fetched.links} label={fetched.links ? "Links in chats are read" : "Links in chats aren't read"} />
        <p className="text-sm leading-relaxed text-muted">
          {fetched.links
            ? "To draft a reply, the pages linked in a chat waiting on you are read, only from hosts on the public internet, never this computer or your local network."
            : "No model is set up, so no replies are drafted and no links are opened."}
        </p>
      </div>
    </Section>
  );
}
