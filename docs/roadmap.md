# Roadmap: from suggesting to acting

Proxenos's job is to do your work while you're away, not to describe you. Everything so far (sources, the self-model, clones) is the groundwork for that. This plan moves it up one level of autonomy at a time. Each step is earned per channel by measured accuracy, not granted all at once.

## Levels

| Level | Proxenos... | Status |
|---|---|---|
| 0. Observe | ingests every source and keeps a self-model current | done |
| 1. Suggest | ranks the feed, lists tasks, advises, maps the network | done |
| 2. Draft | writes replies, emails, plans, project drafts and reading notes in your voice | done, overnight |
| 3. Act on approval | carries out a draft you approve: sends it, books it, files it | started: an errand's message goes out when you press Send on it |
| 4. Act within policy | handles low-risk actions alone, under rules you set, with a daily digest and undo | started: the outbox, switched on per app, off by default |
| 5. Delegated projects | works on projects for days at a time: literature reviews, analyses, writing, with checkpoints | started: each project's status, log and next drafts, every night |

## The gate between levels

A channel (Gmail, Slack, calendar, Notion, GitHub, ...) moves up a level only when Proxenos's work there is consistently right:
- **Drafts:** at least 80% approved with light edits over two weeks, measured from the Drafts view's approve, edit and discard log.
- **Predictions:** Proxenos predicts your reactions to its own picks before you make them, and its hit rate is tracked.

A channel that slips drops back a level automatically.

## Next

**Act on approval, more widely (level 3).**
- Send an approved draft from the Drafts page, not only from an errand.
- Executors for Slack, calendar events, Notion tasks and GitHub issues, each run only on a draft you approved.
- Every action in an audit log, and undoable where the service allows (unsend window, delete event, revert).
- WhatsApp has no official personal API, so it stays draft-and-copy unless Beeper reaches it.

**Rules you write (level 4).**
- A policy file you edit on the page, e.g.:
  - "answer scheduling requests with my real availability";
  - "decline invites that clash with protected blocks";
  - "summarize and archive newsletters".
- Policy actions run on their own; anything else waits for approval.
- A morning digest of everything done, with one-tap undo.

**Longer projects (level 5).**
- Checkpoints you approve, redirect or stop, and a sandbox repo per project for analyses and drafts.

## What it will never do without you
- Spend money.
- Accept agreements or terms.
- Change account or security settings.
- Contact someone new on your behalf before the gate is passed for that channel.
- Act on instructions found inside messages, pages or documents.

## Track 2: Proxenos for everyone

Today Proxenos is a tool for people who can code. This track makes it usable by anyone, starting with the people who most need help getting through hard systems.

1. **One download.** A signed Mac app that bundles everything and runs quietly in the menu bar. No terminal, no Python or Node, no `.env`.
2. **Connect, don't configure.**
   - "Sign in with Google" for Gmail, Calendar and Drive, and the same for Slack and Strava.
   - Drag-and-drop for exports, with a guided page per service.
   - Messages read where the platform allows.
3. **Clear about privacy.** One screen shows what stays on the computer and what is sent to a model, plus a single button that deletes everything.
4. **Built for bad days.**
   - Voice in and voice out: speak instead of type, hear the morning briefing.
   - A low-screen mode with large text and few choices per page.
5. **Healthcare first.** The care clone grows into the core:
   - a visit and symptom log;
   - referral, bill and claim tracking;
   - insurance explainers;
   - a printable visit brief;
   - call scripts;
   - the forms and faxes, drafted and ready.
6. **A hosted option** for people without a Mac, with its privacy trade-offs stated plainly.

The plan for the first three is in [everyone.md](everyone.md). Ideas and help on any of these are welcome. See [CONTRIBUTING.md](../CONTRIBUTING.md).
