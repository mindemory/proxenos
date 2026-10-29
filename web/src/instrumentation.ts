/**
 * Runs once when the page's server starts. The first Home, Drafts and Status reads walk the whole vault
 * (when each source last synced; addresses and phones for drafts; every stream's counts), which can take a minute on a large one,
 * so they're made here in the background, not on the reader's first click. Never throws.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const [{ getHome, getStatus }, { draftsView }] = await Promise.all([import("@/lib/vault"), import("@/lib/draftsView")]);
  setTimeout(() => {
    // One at a time, Home first (what a reader opens first), so they don't compete for the disk.
    (async () => {
      for (const read of [() => getHome(null), draftsView, getStatus]) await read().catch(() => undefined);
    })();
  }, 1000);
}
