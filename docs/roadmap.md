# Roadmap: from suggesting to acting

Proxenos's job is to do your work while you're away, not to describe you. Everything so far (sources, the self-model, clones) is the groundwork for that. This plan moves it up one level of autonomy at a time. Each step is earned per channel by measured accuracy, not granted all at once.

## Levels

| Level | Proxenos... | Status |
|---|---|---|
| 0. Observe | ingests every source and keeps a self-model current | done |
| 1. Suggest | ranks the feed, lists tasks, advises, maps the network | done |
| 2. Draft | writes replies, emails, plans, project drafts and reading notes in your voice | done, overnight |
| 3. Act on approval | carries out a draft you approve: sends it, books it, files it | week 2 |
| 4. Act within policy | handles low-risk actions alone, under rules you set, with a daily digest and undo | week 3 |
| 5. Delegated projects | works on projects for days at a time: literature reviews, analyses, writing, with checkpoints | week 4 |

## The gate between levels

A channel (Gmail, Slack, calendar, Notion, GitHub, ...) moves up a level only when Proxenos's work there is consistently right:
- **Drafts:** at least 80% approved with light edits over two weeks, measured from the Drafts view's approve, edit and discard log.
- **Predictions:** Proxenos predicts your reactions to its own picks before you make them, and its hit rate is tracked.

A channel that slips drops back a level automatically.

## 30 days

**Week 1: finish the ground.**
- Observer notes for every source, and a self-model refresh.
- Network corrections: real memberships, merged identities, aliases you can fix from the page.
- An ANTHROPIC_API_KEY and `scripts/install-night.sh`, so `proxenos night` runs every night with no session.
- An evaluation harness for the gate: draft approval and edit rates, and reaction predictions.

**Week 2: act on approval (level 3).**
- Executors that run only on drafts you approved: send email (Gmail API), post in Slack (user token with write scope), create or answer calendar events, update Notion tasks, open GitHub issues and PRs in your repos.
- Every action goes in an audit log, and is undoable where the service allows (unsend window, delete event, revert).
- WhatsApp has no official personal API, so it stays draft-and-copy.

**Week 3: act within policy (level 4).**
- A policy file you edit on the page, e.g.:
  - "answer scheduling requests with your real availability";
  - "decline invites that clash with protected blocks";
  - "file papers you save into the reading list";
  - "summarize and archive newsletters";
  - "keep Notion tasks in sync with what's done".
- Policy actions run on their own; anything else waits for approval.
- A morning digest lists everything done, with one-tap undo.
- A recall clone surfaces past conversations, notes and people relevant to today.

**Week 4: delegated projects (level 5).**
- Project agents take the top ideas and work on them over several nights, in a sandbox repo per project: literature review, an analysis notebook, draft sections, outreach drafts.
- Each night ends with a checkpoint to approve, redirect or stop.
- Channels that passed the gate get widened.

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
