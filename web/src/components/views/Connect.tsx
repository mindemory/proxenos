"use client";

import { Plug } from "lucide-react";

import { AppleMailCard, BeeperCard, GmailCard, PhoneCard, SlackCard, WhatsAppCard } from "@/components/connect/cards";
import { SourceRow } from "@/components/connect/parts";
import { Command, ErrorBanner, NoVault } from "@/components/EmptyState";
import { StatusSkeleton } from "@/components/Skeleton";
import { useConnect } from "@/lib/connectClient";
import type { ConnectHow, ConnectSource } from "@/lib/types";

/** Sources with a card of their own here; the rest are rows that say how to connect them. */
const WITH_BUTTONS = ["applemail", "gmail", "whatsapp", "slack", "beeper"];

function Group({ kicker, title, children, note }: { kicker: string; title: string; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <p className="smallcaps">{kicker}</p>
        <h2 className="title-2">{title}</h2>
        {note && <p className="mt-1 text-sm leading-relaxed text-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Rows({ sources, now }: { sources: ConnectSource[]; now: string }) {
  if (!sources.length) return null;
  return (
    <div className="card divide-y divide-line">
      {sources.map((s) => (
        <SourceRow key={s.id} s={s} now={now} />
      ))}
    </div>
  );
}

export function Connect() {
  const { data, error, clearError, job, signInGmail, readWhatsApp, saveBeeperToken, cancel } = useConnect();

  if (!data) {
    return error ? <ErrorBanner message={`Couldn't load sources: ${error}`} /> : <StatusSkeleton />;
  }
  if (!data.vault.exists) return <NoVault path={data.vault.path} />;

  const of = (how: ConnectHow) => data.sources.filter((s) => s.how === how && !WITH_BUTTONS.includes(s.id));
  const applemail = data.sources.find((s) => s.id === "applemail");
  const gmail = data.sources.find((s) => s.id === "gmail");
  const whatsapp = data.sources.find((s) => s.id === "whatsapp");
  const slack = data.sources.find((s) => s.id === "slack");
  const beeper = data.sources.find((s) => s.id === "beeper");
  const connected = data.sources.filter((s) => s.connected).length;

  return (
    <div className="space-y-8 p-4 pb-24 sm:p-6 md:pb-20">
      {error && <ErrorBanner message={error} onDismiss={clearError} />}
      {data.error && <ErrorBanner message={data.error} />}

      <section className="card flex items-start gap-3 p-5 sm:p-6">
        <div className="rounded-full bg-accent/10 p-2.5 text-accent">
          <Plug size={17} />
        </div>
        <div className="min-w-0 space-y-1">
          <p className="smallcaps">
            <span className="num">{connected}</span> of <span className="num">{data.sources.length}</span> connected
          </p>
          <p className="leading-relaxed text-muted">
            Connect a source once and Proxenos reads it on every sync. It only reads: nothing here sends, posts or changes
            anything in your accounts. Tokens and passwords stay on this computer, and this page never shows one back. The
            Beeper token is the only one you paste here.
          </p>
        </div>
      </section>

      <Group kicker="Live" title="Sign in or read directly">
        {applemail && <AppleMailCard s={applemail} now={data.now} />}
        {gmail && <GmailCard s={gmail} now={data.now} job={job("gmail")} onSignIn={signInGmail} onCancel={() => cancel("gmail")} />}
        {whatsapp && (
          <WhatsAppCard s={whatsapp} now={data.now} job={job("whatsapp")} onRead={readWhatsApp} onCancel={() => cancel("whatsapp")} />
        )}
        {slack && <SlackCard s={slack} now={data.now} />}
        {beeper && (
          <BeeperCard s={beeper} now={data.now} job={job("beeper")} onSave={saveBeeperToken} onCancel={() => cancel("beeper")} />
        )}
        <Rows sources={of("live")} now={data.now} />
      </Group>

      <Group kicker="Phone" title="Reach it from your phone">
        <PhoneCard phone={data.phone} />
      </Group>

      <Group
        kicker="Downloads"
        title="From an export"
        note={
          <>
            Ask each service for a copy of your data. When it arrives, put the zip in the repo&apos;s data/ folder or the
            vault&apos;s inbox/, then run <Command>proxenos import</Command>
          </>
        }
      >
        <Rows sources={of("download")} now={data.now} />
      </Group>

      <Group kicker="Folders" title="From a folder on this computer">
        <Rows sources={of("folder")} now={data.now} />
      </Group>
    </div>
  );
}
