import { cn } from "@/lib/utils";

/** One shimmering block. Sizes come from the caller. */
export function Bone({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden="true" />;
}

function Busy({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <div className={className} role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/** Home: the greeting, then the briefing's cards. */
export function HomeSkeleton() {
  return (
    <Busy label="Loading the briefing" className="mx-auto w-full max-w-[1500px] px-4 pb-28 pt-7 sm:px-6 md:pb-12 lg:px-8">
      <Bone className="h-3 w-40" />
      <Bone className="mt-4 h-10 w-72 max-w-full" />
      <Bone className="mt-4 h-4 w-[34rem] max-w-full" />
      <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-6 xl:grid-cols-12">
        {["lg:col-span-6 xl:col-span-7", "lg:col-span-6 xl:col-span-5", "md:col-span-2 lg:col-span-6 xl:col-span-12"].map((span, i) => (
          <div key={i} className={cn("card p-5", span)}>
            <div className="flex items-center gap-3">
              <Bone className="h-8 w-8 rounded-lg" />
              <Bone className="h-5 w-40" />
            </div>
            <div className="mt-5 space-y-3">
              <Bone className="h-4 w-full" />
              <Bone className="h-4 w-5/6" />
              <Bone className="h-4 w-2/3" />
            </div>
          </div>
        ))}
      </div>
    </Busy>
  );
}

/** Feed and Saved: cards with a source line, a title and a summary. */
export function FeedSkeleton({ label = "Loading the feed" }: { label?: string }) {
  return (
    <Busy label={label} className="divide-y divide-line">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="flex gap-4 p-5 sm:p-6">
          <Bone className="h-9 w-9 flex-shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-3">
            <Bone className="h-3.5 w-1/3" />
            <Bone className="h-5 w-11/12" />
            <Bone className="h-16 w-full rounded-xl" />
          </div>
        </div>
      ))}
    </Busy>
  );
}

/** Tasks: grouped rows with a checkbox, a title and a due date. */
export function TaskSkeleton() {
  return (
    <Busy label="Loading tasks" className="p-4 sm:p-6">
      <Bone className="h-3 w-24" />
      <div className="mt-4 divide-y divide-line rounded-2xl border border-line">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-start gap-3 p-4">
            <Bone className="mt-0.5 h-5 w-5 rounded-md" />
            <div className="min-w-0 flex-1 space-y-2">
              <Bone className="h-4 w-4/5" />
              <Bone className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    </Busy>
  );
}

/** Drafts: tall cards with badges, a title and body lines. */
export function DraftSkeleton() {
  return (
    <Busy label="Loading drafts" className="space-y-4 p-4 sm:p-6">
      {[0, 1, 2].map((i) => (
        <div key={i} className="card space-y-3 p-5">
          <div className="flex gap-2">
            <Bone className="h-5 w-16" />
            <Bone className="h-5 w-20" />
          </div>
          <Bone className="h-6 w-2/3" />
          <Bone className="h-4 w-full" />
          <Bone className="h-4 w-11/12" />
          <Bone className="h-4 w-3/4" />
        </div>
      ))}
    </Busy>
  );
}

/** Advice and the profile: blocks of prose. */
export function ProseSkeleton({ label }: { label: string }) {
  return (
    <Busy label={label} className="space-y-5 p-4 sm:p-6">
      {[0, 1].map((i) => (
        <div key={i} className="card space-y-3 p-5 sm:p-6">
          <Bone className="h-6 w-1/2" />
          <Bone className="h-4 w-full" />
          <Bone className="h-4 w-full" />
          <Bone className="h-4 w-4/5" />
        </div>
      ))}
    </Busy>
  );
}

/** Memory: result rows with a source badge and two lines of text. */
export function ResultSkeleton() {
  return (
    <Busy label="Searching memory" className="divide-y divide-line">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="space-y-2 px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-2">
            <Bone className="h-5 w-20" />
            <Bone className="h-3 w-32" />
          </div>
          <Bone className="h-4 w-11/12" />
          <Bone className="h-4 w-2/3" />
        </div>
      ))}
    </Busy>
  );
}

/** Network: the canvas area, with a few points standing in for people. */
export function GraphSkeleton() {
  return (
    <Busy label="Loading the network" className="relative h-[calc(100dvh-7rem)] min-h-80 overflow-hidden">
      <div className="absolute inset-6 rounded-2xl border border-line" />
      {[
        [30, 40],
        [44, 52],
        [58, 38],
        [52, 64],
        [68, 58],
        [38, 66],
      ].map(([x, y], i) => (
        <div key={i} className="absolute" style={{ left: `${x}%`, top: `${y}%` }}>
          <Bone className="h-3 w-3 rounded-full" />
        </div>
      ))}
    </Busy>
  );
}

/** Status: one row per source. */
export function StatusSkeleton() {
  return (
    <Busy label="Loading sync status" className="space-y-3 p-4 sm:p-6">
      <Bone className="h-28 w-full rounded-2xl" />
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="card flex items-center gap-3.5 px-4 py-3.5">
          <Bone className="h-9 w-9 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Bone className="h-4 w-1/3" />
            <Bone className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </Busy>
  );
}
