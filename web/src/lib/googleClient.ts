// What the page makes of the file Google's console gives for an OAuth client ("Download JSON"):
// {"installed": {"client_id", "client_secret", ...}}. It's read in the browser and only the two
// values go on, in a request's body to /api/setup; nothing else in the file leaves the page.

export interface GoogleClient {
  client_id: string;
  client_secret: string;
}

/** The ID and secret in the file's text, or null when it isn't a Google OAuth client's. */
export function googleClientFrom(text: string): GoogleClient | null {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  const top = data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  const client = top.installed ?? top.web;
  if (!client || typeof client !== "object") return null;
  const { client_id: id, client_secret: secret } = client as Record<string, unknown>;
  if (typeof id !== "string" || typeof secret !== "string" || !id.trim() || !secret.trim()) return null;
  return { client_id: id.trim(), client_secret: secret.trim() };
}
