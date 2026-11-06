"use client";

import { Check, ExternalLink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { FULL_DISK_ACCESS } from "@/components/connect/parts";
import { getJson } from "@/lib/client";
import { JSON_HEADERS } from "@/lib/headers";
import type { ConnectResponse, ConnectSource, SetupStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const button =
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line-strong px-3 py-1 text-[0.8125rem] text-muted transition-colors hover:text-ink disabled:opacity-50";

/**
 * "Get Proxenos ready": what's set and what's left, one line each with one button, so nothing needs
 * a terminal. The model, Full Disk Access, Google sign-in, Slack and WhatsApp. It asks Connect what
 * it knows, and again whenever the window gets focus back (from System Settings, or a browser tab
 * a sign-in used) and while WhatsApp is being read.
 */
export function Ready({ status, onModel, onConnect }: { status: SetupStatus; onModel: () => void; onConnect: () => void }) {
  const [connect, setConnect] = useState<ConnectResponse | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const load = useCallback(() => {
    getJson<ConnectResponse>("/api/connect").then(setConnect, () => setConnect(null));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, [load]);
  const reading = connect?.jobs.some((j) => j.kind === "whatsapp" && j.state === "running") ?? false;
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [reading, load]);

  const source = (id: string): ConnectSource | undefined => connect?.sources.find((s) => s.id === id);
  const google = [source("gmail"), source("gcalendar"), source("gdocs")];
  const googleDone = google.some((s) => s?.connected);
  const noClient = google.some((s) => s?.problem === "no_google_client");
  const slack = source("slack");
  const whatsapp = source("whatsapp");
  const inApp = connect?.inApp ?? false;
  const access = connect?.fullDiskAccess ?? null;

  const readWhatsApp = () => {
    setProblem(null);
    fetch("/api/connect/whatsapp", { method: "POST", headers: JSON_HEADERS, body: "{}" })
      .then(async (res) => {
        if (!res.ok) setProblem(((await res.json().catch(() => ({}))) as { error?: string }).error ?? "WhatsApp couldn't be read.");
        load();
      })
      .catch(() => setProblem("WhatsApp couldn't be read."));
  };

  return (
    <div className="space-y-2">
      <ul className="divide-y divide-line rounded-xl border border-line text-sm">
        <Row
          done={status.model.kind !== "none"}
          label="A model"
          detail={status.model.kind === "none" ? "None yet. Nothing is drafted until you choose one." : `Using ${status.model.label}.`}
          action={status.model.kind === "none" ? <button type="button" className={button} onClick={onModel}>Choose a model</button> : null}
        />
        {access !== null && (
          <Row
            done={access}
            label="Full Disk Access"
            detail={access ? `${inApp ? "Proxenos" : "This Python"} can read Mail and WhatsApp.` : "Lets Proxenos read Mail and WhatsApp on this Mac."}
            action={
              access ? null : (
                <a href={FULL_DISK_ACCESS} className={button}>
                  Open Full Disk Access
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              )
            }
            note={
              access
                ? null
                : inApp
                  ? "Press the button, then turn on the switch beside Proxenos. If it isn't listed, press + and choose Proxenos in Applications. If macOS offers Quit & Reopen, choose it."
                  : "Press the button, then turn on the app that runs Proxenos (Terminal, if you started it there). If it isn't listed, press + and choose it."
            }
          />
        )}
        <Row
          done={googleDone}
          label="Google sign-in"
          detail={
            googleDone
              ? "Signed in."
              : noClient && inApp
                ? "This copy of Proxenos has no Google sign-in built in, so Gmail and Calendar can't connect here."
                : "For Gmail, Google Calendar and Google Docs. This opens Connect, where you sign in."
          }
          action={googleDone || (noClient && inApp) ? null : <button type="button" className={button} onClick={onConnect}>Sign in with Google</button>}
        />
        <Row
          done={!!slack?.connected}
          label="Slack"
          detail={slack?.connected ? slack.workspaces.join(", ") || "Connected." : "Not connected. This opens Connect, where you sign in."}
          action={slack?.connected ? null : <button type="button" className={button} onClick={onConnect}>Sign in to Slack</button>}
        />
        <Row
          done={!!whatsapp?.connected}
          label="WhatsApp"
          detail={
            whatsapp?.connected
              ? "Read."
              : whatsapp?.problem === "missing"
                ? "WhatsApp for Mac isn't on this Mac. Install it and sign in with your phone, then come back."
                : whatsapp?.problem === "blocked"
                  ? "Turn on Full Disk Access first (above)."
                  : "Not read yet."
          }
          action={
            whatsapp?.connected || whatsapp?.problem === "missing" ? null : (
              <button type="button" className={button} disabled={reading || whatsapp?.problem === "blocked"} onClick={readWhatsApp}>
                {reading ? "Reading…" : "Read WhatsApp"}
              </button>
            )
          }
        />
      </ul>
      {problem && (
        <p className="text-sm text-bad-ink" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

function Row({ done, label, detail, action, note }: { done: boolean; label: string; detail: string; action: React.ReactNode; note?: string | null }) {
  return (
    <li className="space-y-1 px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span
          className={cn(
            "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full",
            done ? "bg-ok-bg text-ok-ink" : "bg-surface-2 text-faint",
          )}
        >
          {done ? <Check size={12} aria-hidden="true" /> : <span className="h-1 w-1 rounded-full bg-current" aria-hidden="true" />}
        </span>
        <span className="w-32 flex-shrink-0 text-ink">{label}</span>
        <span className={cn("min-w-0 flex-1 break-words", done ? "text-ok-ink" : "text-muted")}>{detail}</span>
        {action}
      </div>
      {note && <p className="pl-8 text-xs leading-relaxed text-muted">{note}</p>}
    </li>
  );
}
