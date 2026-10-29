/**
 * Runs once when the page's server starts. The first Home and Drafts reads walk the whole vault (when
 * each source last synced; addresses and phones for drafts), which can take a minute on a large one,
 * so they're made here in the background, not on the reader's first click. Never throws.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const [{ getHome }, { draftsView }] = await Promise.all([import("@/lib/vault"), import("@/lib/draftsView")]);
  setTimeout(() => {
    Promise.allSettled([getHome(null), draftsView()]).catch(() => undefined);
  }, 1000);
}
