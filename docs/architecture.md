# Architecture: one master, many clones

There is exactly **one model of you**, and many clones that use it. Clones are roles, not separate personalities. If each clone kept its own idea of who you are, they'd drift apart within weeks and none of them would be you.

```
                    ┌──────────────────────── master ────────────────────────┐
  sources ──ingest──▶ raw/ ──observers──▶ observations/ ──consolidate──▶ self/ │
                    └──────────────────────────────┬─────────────────────────┘
                                                   │ read-only
          ┌──────────┬──────────┬──────────┼──────────┬──────────┬──────────┐
       tracker     tasks     advisor   network    recall      work      web page
       (feed)   (on your   (advice)  (people,  (memories  (drafts,   shows outputs,
                  plate)              ideas)   for today) never sent) collects reactions
          └──────────────── outputs + your reactions ──────────────────────┘
                                                   │
                                     back to the master as evidence
```

## The pieces

- **Ingesters** (`proxenos ingest <source>`, or `proxenos import` for downloaded exports): pull each source into `raw/`. The supported sources are listed in [data_sources.md](data_sources.md).
- **Observer clones**, one per source: read new raw data and write dated notes on what it says about you (`observations/<source>/YYYY-MM.md`). The WhatsApp observer is the expert on how you talk to friends; the Spotify one on your moods and routines. They only ever read *your* side of conversations.
- **The master** (`proxenos master`):
  - runs everything on a schedule;
  - is the **only writer** of `self/` (identity, interests, taste, voice, routines, open questions);
  - folds new observations and your reactions into `self/`. Fast state (what you're into this week) updates directly; slow state (values, beliefs, voice) changes as proposals you approve.
  - Every change is a commit in the vault's private git history, so how you've changed is a `git log`.
- **Worker clones** (`proxenos clone <name>`), one per job. They read `self/`, do one job, and write output for you to react to. They never change `self/` directly.
  - **tracker:** a research and news feed, ranked against your interests.
  - **tasks:** what's on your plate, from recent conversations.
  - **advisor:** small, evidence-based changes to how you work and live.
  - **network:** the people you know, how they connect, and project and outreach ideas.
  - **recall:** memories relevant to today (below).
  - **work:** drafts of replies, emails, plans and reading notes in your voice. Drafts only; nothing is sent.
- **Memory** (`proxenos index`, no model): a full-text index (SQLite FTS5, `vault/memory/index.sqlite`) over every raw record, searchable by words, person, source and date, with the surrounding conversation for any hit. It is derived data, rebuilt from `raw/` at any time, and `proxenos sync` keeps it current. The **recall** clone (`proxenos clone recall`) turns it into proactive memory: for today's calendar, open tasks, feed items and closest people it finds the past conversations, mail and notes that bear on them, or nothing when nothing fits.
- **Web page** (`web/`): local only. A landing page (`/`) with live counts from the vault, then the app (`/app`): a daily briefing, clone outputs, memory search, the current self-model, and sync status. Your reactions there are Proxenos's best training signal.

## Ground rules

- **Read and draft, never act.** No clone sends a message, buys anything, or posts as you. Acting on your behalf comes later, per clone, only after its predictions about you are measurably good, and always with your approval.
- **Only your behavior is evidence about you.** Clone outputs are tagged as made by Proxenos and never fed back as if you wrote them.
- **The model is Claude Opus 5.5 through your own API key** (`proxenos/llm.py`), kept separate from any work or school account. Clones send the distilled self-model and public items. Observers send your own messages, never other people's.
