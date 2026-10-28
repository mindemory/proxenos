/**
 * The mark: a filled disc and its outline, offset and overlapping. One is you,
 * the other the model of you; the overlap is the part the twin gets right.
 * Drawn inline so it takes `currentColor` and needs no asset.
 */
export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={className} aria-hidden="true" fill="none">
      <circle cx="12.5" cy="12.5" r="8.5" fill="currentColor" />
      <circle cx="19.5" cy="19.5" r="8.5" stroke="currentColor" strokeWidth="1.75" strokeOpacity="0.65" />
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`flex items-center gap-2.5 ${className}`}>
      <Logo className="text-accent" />
      <span className="font-display text-[1.65rem] leading-none tracking-tight text-ink">Twin</span>
    </span>
  );
}
