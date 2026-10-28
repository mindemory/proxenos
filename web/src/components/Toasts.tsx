"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ToastTone = "info" | "ok";

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
}

const LIFETIME_MS = 3200;

type Notify = (message: string, tone?: ToastTone) => void;

const ToastContext = createContext<Notify>(() => {});

/**
 * Short confirmations for actions that otherwise happen in silence (marked
 * useful, task done). Never used for errors: those get a banner that stays,
 * because an error you can miss by looking away gets repeated.
 */
export function useToast(): Notify {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((t) => window.clearTimeout(t));
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback<Notify>(
    (message, tone = "info") => {
      const id = nextId.current++;
      setToasts((prev) => [...prev.slice(-2), { id, message, tone }]);
      timers.current.push(window.setTimeout(() => dismiss(id), LIFETIME_MS));
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 z-[60] flex flex-col items-center gap-2 px-4 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] md:bottom-6"
      >
        {toasts.map((t) => (
          <button
            key={t.id}
            onClick={() => dismiss(t.id)}
            className={`toast-in pointer-events-auto max-w-full rounded-full border px-4 py-2 text-sm shadow-pop ${
              t.tone === "ok" ? "border-ok-line bg-ok-bg text-ok-ink" : "border-line-strong bg-surface-2 text-ink"
            }`}
          >
            {t.message}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
