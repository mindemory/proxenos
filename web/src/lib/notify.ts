// Server side of Settings' phone notices. Import only from route handlers.
//
// A test notice goes through `proxenos notify test`, which reads the ntfy topic and token where
// Proxenos keeps them and never prints either: this only passes on the line it says, whether
// the test got through and if not, why.

import { lastLine, NO_COMMAND } from "./connect";
import type { NoticeTest } from "./types";
import { proxenos } from "./vault";

// One request to the ntfy server, which the command gives up on after 15 seconds.
const TEST_MS = 30_000;
const MAX_OUTPUT = 64 * 1024;

/** Send one test notice to the phone, and say how it went. Never throws. */
export async function sendTestNotice(): Promise<NoticeTest> {
  const cli = await proxenos();
  if (!cli) return { ok: false, message: NO_COMMAND };
  return new Promise((resolve) => {
    cli.exec(["notify", "test"], { timeout: TEST_MS, maxBuffer: MAX_OUTPUT }, (error, stdout, stderr) => {
      const said = lastLine(stdout) || lastLine(stderr);
      if (!error) resolve({ ok: true, message: said || "Sent a test notice." });
      else resolve({ ok: false, message: error.killed ? "The test took too long. Check the ntfy server." : said || "The test didn't go through." });
    });
  });
}
