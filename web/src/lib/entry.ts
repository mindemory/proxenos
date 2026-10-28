// Whether the reader has already come in past the landing page in this browser session.
// Kept in sessionStorage: a new session starts at the landing again.

export const ENTERED_KEY = "proxenos.entered";

/**
 * Runs before the landing paints, on a full page load only: a reader who came in earlier in
 * this session goes straight on to the app. Client-side navigation back to the landing (the
 * wordmark) renders it without running this, so the landing stays reachable.
 */
export const SKIP_LANDING_SCRIPT = `try{if(sessionStorage.getItem("${ENTERED_KEY}")==="1"&&!location.search)location.replace("/app")}catch(e){}`;

export function markEntered(): void {
  try {
    sessionStorage.setItem(ENTERED_KEY, "1");
  } catch {
    // Blocked storage: the landing simply shows again next time.
  }
}

/** Going back to the landing on purpose: it stays until Enter is pressed again. */
export function forgetEntered(): void {
  try {
    sessionStorage.removeItem(ENTERED_KEY);
  } catch {
    // Nothing to forget.
  }
}
