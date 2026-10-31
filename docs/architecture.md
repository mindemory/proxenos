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
  - **care:** where your health care stands, from the health-care admin in your mail, calendar, chats and notes: a timeline, open items and who they wait on, scripts for calls and messages, and a printable brief for the next clinician. It restates your records and never diagnoses.
  - **advisor:** small, evidence-based changes to how you work and live.
  - **network:** the people you know, how they connect, and project and outreach ideas.
  - **recall:** memories relevant to today (below).
  - **projects:** where each of your long-running projects stands (a paper, an analysis), from what your messages, mail and notes say about it: a status, a dated log, the next steps, what only you can decide, and up to two drafts a night that move it on. The projects are your own list, `clones/projects/projects.json`.
  - **steps:** the next piece of a project's work, done. A project on the list with its code's folder (`"repo"`, a git repository on this computer) and its data folders (`"data"`) takes one step a night, once its last one is accepted or discarded, and one more whenever you press "Do a step now" or queue one on the page's Projects view. The step is the one you queued, else one picked from the project's status and the steps before: run an analysis, fix a script, make a figure, draft a section as markdown. It's done on a new branch, `proxenos/<project>-<when>`, in a git worktree of its own, so your checkout is never touched, and it comes back as a report: what it did, what it found (numbers and figures), the files it changed, what it couldn't do and what's next. Accept merges the branch into the branch your checkout is on; Discard deletes the branch and the worktree. Nothing is pushed and no one is contacted. The work itself is done by a runner (`proxenos/agent.py`): Claude Code, headless, where it's installed, inside its sandbox (its commands write only in the worktree and reach no network; nothing it does reads the vault or your keys; at most 30 minutes, 100 turns and a spending budget, `PROXENOS_STEP_BUDGET`), on the account Claude Code is signed in to, never Proxenos's API key. Without Claude Code, or when it can't start, the local model takes the step, and it can only write: it reads a few of the project's files and writes a script, a fix or a section, runs nothing, and its report says so. `PROXENOS_STEP_RUNNER` (`claude` or `local`) picks one. Each step is `clones/projects/<id>/steps/<when>.json`, with what it made beside it.
  - **work:** drafts of replies, emails, plans and reading notes in your voice. Drafts only; nothing is sent. Each direct chat where someone else had the last word in the past week gets a reply (WhatsApp, Messenger, Instagram, LinkedIn, email, and Slack direct messages and threads that mention you or that you're in), drafted from the conversation, your own last messages in that chat (how you write to that person), and the pages linked in what's waiting, fetched and read first. With an API key, `proxenos sync` drafts these replies as chats come in: only chats with no draft yet, at most five a sync, so a quiet sync makes no model call.
- **Memory** (`proxenos index`, no model): a full-text index (SQLite FTS5, `vault/memory/index.sqlite`) over every raw record, searchable by words, person, source and date, with the surrounding conversation for any hit. It is derived data, rebuilt from `raw/` at any time, and `proxenos sync` keeps it current. Beside it, a vector index (`vault/memory/vectors.sqlite`, `proxenos index --vectors`) holds the last year by meaning: a chat's day of messages, or one email, note or document, embedded by a small model on this computer (Ollama, `qwen3-embedding:0.6b`), so a question finds what answers it even when the words differ. Each sync embeds what's new for a few minutes; reply research searches it first. The **recall** clone (`proxenos clone recall`) turns it into proactive memory: for today's calendar, open tasks, feed items and closest people it finds the past conversations, mail and notes that bear on them, or nothing when nothing fits.
- **Ask** (`proxenos ask`, the page's Ask view): a question, a pasted message or up to four screenshots. The model reads the screenshots (who wrote what), looks through memory as a reply does (the person, and what the answer depends on, by meaning and by words), then answers from the self-model and the "right now" note, and drafts a reply in your voice when it's a message to you. Each ask is a file in `clones/ask/`; a draft also lands in Drafts.
- **Errands** (`proxenos clone errands "GOAL"`, the page's Errands view): something to get done, such as reaching someone about a role, with your CV. An errand reads the goal, looks the person up, finds a way to reach them from your own mail and chats (an address they wrote from, one you wrote to, a chat with them through Beeper; never a guessed address), finds your newest CV, reads the emails you wrote before for the same kind of reach-out, and writes the message, plus, when there's no way to reach them, a note asking someone you know there for an introduction. Then it stops one tap short: the page shows each message, editable, with every step the errand took and why, and Send sends that one message, by Mail with the CV attached or through Beeper. Each night, errands still waiting on an address look again. Each is a file in `clones/errands/`.
- **Web page** (`web/`): local only. A landing page (`/`) with live counts from the vault, then the app (`/app`): a daily briefing, clone outputs, memory search, the current self-model, a Connect view (every source and whether it's connected, with buttons to sign in to Gmail and read WhatsApp) and sync status. Your reactions there are Proxenos's best training signal.

## Ground rules

- **Read and draft, never act.** No clone sends a message, buys anything, or posts as you; an errand's message goes only when you press Send on it. A project's step changes code only on a branch of its own, and it reaches your checkout only when you press Accept. Acting on your behalf comes later, per clone, only after its predictions about you are measurably good, and always with your approval.
- **Only your behavior is evidence about you.** Clone outputs are tagged as made by Proxenos and never fed back as if you wrote them.
- **The model is Claude Opus 5.5 through your own API key** (`proxenos/llm.py`), kept separate from any work or school account. Clones send the distilled self-model and public items. Observers send your own messages, never other people's. A project's steps go to Claude Code on its own account (or the local model): the project's name, its status and the steps before, and the code and data it reads.
