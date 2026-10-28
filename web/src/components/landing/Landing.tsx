"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

import { Logo } from "@/components/Logo";
import { markEntered } from "@/lib/entry";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { SummaryResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Constellation } from "./Constellation";

function useSummary() {
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch("/api/summary", { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<SummaryResponse>) : Promise.reject(new Error(String(res.status)))))
      .then(
        (d) => alive && setData(d),
        () => alive && setFailed(true),
      );
    return () => {
      alive = false;
    };
  }, []);
  return { data, failed };
}

const count = (n: number | null | undefined) => (n === null || n === undefined ? "–" : n.toLocaleString("en-US"));

function Stat({ value, label, title, loading }: { value: string; label: string; title?: string; loading: boolean }) {
  return (
    <div className="min-w-0 text-center" title={title}>
      <dt className="smallcaps text-muted">{label}</dt>
      <dd className="mt-1.5 flex h-8 items-center justify-center">
        {loading ? (
          <span className="skeleton block h-5 w-16" aria-hidden="true" />
        ) : (
          <span className="fade-in font-brand text-[1.85rem] leading-none text-ink [font-variant-numeric:lining-nums_tabular-nums] sm:text-[2.1rem]">
            {value}
          </span>
        )}
      </dd>
    </div>
  );
}

/** The landing: the name and what it means, the vault in five numbers, and Enter. */
export function Landing() {
  const router = useRouter();
  const { data, failed } = useSummary();
  const loading = !data && !failed;

  const enter = useCallback(() => {
    markEntered();
    router.push("/app");
  }, [router]);

  useEffect(() => {
    router.prefetch("/app");
    // Enter anywhere on the page goes in, unless a control has focus and its own meaning.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target instanceof Element ? e.target : null;
      if (t?.closest("a, button, input, textarea, select")) return;
      e.preventDefault();
      enter();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [router, enter]);

  const missing = data && !data.vault.exists;

  return (
    <main className="relative isolate flex min-h-dvh flex-col overflow-hidden bg-bg">
      <Constellation shape={data?.constellation ?? null} />
      {/* A pool of shade behind the words, so the sky never competes with them. */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0"
        style={{
          background:
            "radial-gradient(ellipse 54% 44% at 50% 45%, rgb(14 16 19 / 0.88) 0%, rgb(14 16 19 / 0.5) 55%, rgb(14 16 19 / 0) 100%)",
        }}
      />

      <header className="relative z-10 flex items-center justify-between px-5 pt-5 sm:px-8 sm:pt-7">
        <Logo size={26} className="text-accent" />
        <span className="smallcaps text-faint">Local · this Mac only</span>
      </header>

      <section className="landing-in relative z-10 mx-auto my-auto flex w-full max-w-4xl flex-col items-center px-5 py-16 text-center">
        <p lang="grc" className="font-brand text-xl italic text-muted sm:text-2xl">
          πρόξενος
        </p>
        <h1 className="mt-1 font-brand text-[clamp(4.25rem,17vw,11rem)] font-normal leading-[0.92] tracking-[-0.012em] text-ink">
          Proxenos
        </h1>
        <p className="mt-6 max-w-[34rem] text-balance font-brand text-xl leading-snug text-muted sm:text-[1.4rem]">
          An agent that holds your entire record and acts on your behalf.
        </p>

        <button
          onClick={enter}
          className="group mt-11 inline-flex items-center gap-2.5 rounded-full border border-accent/45 bg-accent/10 py-3 pl-7 pr-6 text-base font-medium text-ink shadow-card transition-[background-color,border-color,box-shadow] hover:border-accent hover:bg-accent/20 hover:shadow-raise"
        >
          Enter
          <ArrowRight size={18} className="text-accent transition-transform motion-safe:group-hover:translate-x-0.5" />
        </button>
        <p className="mt-3 text-xs text-faint">
          or press <kbd className="num rounded border border-line-strong px-1 text-muted">↵</kbd>
        </p>
      </section>

      <footer className="relative z-10 bg-linear-to-t from-bg via-bg/85 to-transparent px-5 pb-7 pt-10 sm:px-8 sm:pb-9">
        {missing ? (
          <p className="text-center text-sm text-muted">
            No vault at <code className="num">{data.vault.path}</code>. Set PROXENOS_VAULT in the repo&apos;s .env.
          </p>
        ) : (
          <>
            <p className="mb-4 flex items-center justify-center gap-2 text-xs text-muted">
              <span className={cn("h-1.5 w-1.5 rounded-full", failed ? "bg-bad-ink" : "bg-ok-ink")} aria-hidden="true" />
              {failed ? "Couldn't read the vault just now." : `Live from ${data?.vault.path ?? "the vault"}`}
            </p>
            <dl className="mx-auto grid max-w-4xl grid-cols-2 gap-x-4 gap-y-5 border-t border-line/80 pt-5 sm:grid-cols-5">
              <Stat label="Memories indexed" value={count(data?.memories)} loading={loading} />
              <Stat label="People" value={count(data?.people)} loading={loading} />
              <Stat label="Drafts to review" value={count(data?.drafts)} loading={loading} />
              <Stat label="Sources" value={count(data?.sources)} loading={loading} />
              <div className="col-span-2 sm:col-span-1">
                <Stat
                  label="Last sync"
                  value={data?.lastSync ? timeAgo(data.lastSync, data.now) : "never"}
                  title={data?.lastSync ? formatDateTime(data.lastSync) : undefined}
                  loading={loading}
                />
              </div>
            </dl>
          </>
        )}
      </footer>
    </main>
  );
}
