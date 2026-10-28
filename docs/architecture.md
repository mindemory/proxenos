# Architecture: one master, many clones

There is exactly **one model of me**, and many clones that use it. Clones are roles, not separate personalities. If each clone kept its own idea of who I am, they'd drift apart within weeks and none of them would be me.

```
                    ┌──────────────────────── master ────────────────────────┐
  sources ──ingest──▶ raw/ ──observers──▶ observations/ ──consolidate──▶ self/ │
                    └──────────────────────────────┬─────────────────────────┘
                                                   │ read-only
                      ┌──────────────┬─────────────┼──────────────┬──────────────┐
                   tracker        inbox          shopping       (more)        web page
               (research feed) (drafts, never  (later)                     shows outputs,
                                  sends)                                   collects reactions
                      └──────────── outputs + my reactions ─────────────────────┘
                                                   │
                                     back to the master as evidence
```

## The pieces

- **Ingesters** (`twin ingest <source>`): pull each source into `raw/`. Done: WhatsApp, Spotify, Strava, email (mbox), Slack.
- **Observer clones**, one per source: read new raw data and write dated notes on what it says about me (`observations/<source>/YYYY-MM.md`). The WhatsApp observer is the expert on how I talk to friends; the Spotify one on my moods and routines. They only ever read *my* side of conversations.
- **The master** (`twin master`):
  - runs everything on a schedule;
  - is the **only writer** of `self/` (identity, interests, taste, voice, routines, open questions);
  - folds new observations and my reactions into `self/`. Fast state (what I'm into this week) updates directly; slow state (values, beliefs, voice) changes as proposals I approve.
  - Every change is a commit in the vault's private git history, so how I've changed is a `git log`.
- **Worker clones** (`twin clone <name>`), one per job. They read `self/`, do one job, and write output for me to react to. They never change `self/` directly.
  - **tracker:** a research and news feed every few hours.
  - **inbox:** triage, plus reply drafts in my voice for email, Slack and WhatsApp. Drafts only.
  - **shopping:** later.
- **Memory** (`twin index`, no model): a full-text index (SQLite FTS5, `vault/memory/index.sqlite`) over every raw record, searchable by words, person, source and date, with the surrounding conversation for any hit. It is derived data, rebuilt from `raw/` at any time, and `twin sync` keeps it current. The **recall** clone (`twin clone recall`) turns it into proactive memory: for today's calendar, open tasks, feed items and closest people it finds the past conversations, mail and notes that bear on them, or nothing when nothing fits.
- **Web page** (`web/`): local only. Shows clone outputs, the current self-model, and sync status. My reactions there are the twin's best training signal.

## Ground rules

- **Read and draft, never act.** No clone sends a message, buys anything, or posts as me. Acting on my behalf comes later, per clone, only after its predictions about me are measurably good, and always with my approval.
- **Only my behavior is evidence about me.** Clone outputs are tagged as twin-made and never fed back as if I wrote them.
- **The model is Claude Opus 5.5 through a personal API key** (`twin/llm.py`), kept off university accounts. Clones send the distilled self-model and public items. Observers send my own messages, never other people's.
