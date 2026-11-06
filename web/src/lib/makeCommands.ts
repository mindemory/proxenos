// The commands an empty view's "Make it now" can run, by the line the view shows, and the
// arguments each is run with (`proxenos` dropped). The page shows the button only for a command
// listed here, and /api/make runs nothing else: whatever the page sends is looked up as it is,
// never split, so no argument can be added to it. Safe for the page and the server to share.

export const MAKE_COMMANDS: Readonly<Record<string, readonly string[]>> = {
  "proxenos clone tasks": ["clone", "tasks"],
  "proxenos clone care": ["clone", "care"],
  "proxenos clone advisor": ["clone", "advisor"],
  "proxenos clone network": ["clone", "network"],
  "proxenos clone network --people-only": ["clone", "network", "--people-only"],
  "proxenos clone work": ["clone", "work"],
  "proxenos clone tracker": ["clone", "tracker"],
  "proxenos clone jobs": ["clone", "jobs"],
  "proxenos clone rhythms": ["clone", "rhythms"],
  "proxenos clone watch --force": ["clone", "watch", "--force"],
  "proxenos clone choices --force": ["clone", "choices", "--force"],
  "proxenos clone journal --date today": ["clone", "journal", "--date", "today"],
  "proxenos master": ["master"],
  "proxenos index": ["index"],
};

/** The arguments to run for a command line, or null when it isn't one the page may run. */
export function makeArgs(command: unknown): readonly string[] | null {
  return typeof command === "string" && Object.hasOwn(MAKE_COMMANDS, command) ? MAKE_COMMANDS[command] : null;
}
