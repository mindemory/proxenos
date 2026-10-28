/**
 * The mark: a filled disc and its outline, offset and overlapping. One is you, the other the
 * one who acts for you; the overlap is where Proxenos gets you right.
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

/** The name, set in the classical face. */
export function Wordmark({ className = "" }: { className?: string }) {
  return <span className={`font-brand leading-none tracking-[0.01em] text-ink ${className}`}>Proxenos</span>;
}
