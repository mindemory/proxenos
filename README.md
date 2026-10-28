# Proxenos

*In the Greek city-states, the proxenos was the citizen who formally acted on someone else's behalf.*

Proxenos learns from my own data and works on my behalf. It is a digital twin of me in the plain sense. A master process keeps one shared model of who I am, and worker clones use it for one job each: a research and news feed, tasks, advice, my network, memories for the day, and drafts written as me. It drafts; it never sends anything by itself.

Design notes: [architecture](docs/architecture.md), [data sources](docs/data_sources.md), [tracker and page](docs/tracker.md), [landscape](docs/landscape.md), [roadmap](docs/roadmap.md).

## Privacy

This repository holds code only. Everything personal lives in a separate private vault (`PROXENOS_VAULT`, default `~/proxenos_vault`) that never enters this repo:
- raw exports and messages;
- observations and the self-model;
- tracker items and feedback.

The vault keeps its own local git history of how the self-model changes. Observers only send my own side of conversations to the model, never other people's messages.

## Setup

```bash
CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml
conda activate proxenos
conda config --env --set subdir osx-arm64
pip install -e ".[dev]"
cp .env.example .env    # then fill in keys
```

Settings in `.env` are `PROXENOS_*`. The older `TWIN_*` names are still read when the new one isn't set.

## Commands

Every command is `proxenos ...`; `px` is the same command, shorter (`px sync`, `px clone recall`).

| Command | What it does |
|---|---|
| `Proxenos.command` (double-click) or `proxenos web` | Open the local page at http://127.0.0.1:4747: the landing, then the app at `/app` |
| `proxenos sync` | Import new downloads from `data/` and refresh every source that needs no model, then update the memory index and today's recall |
| `proxenos index [--rebuild]` | Index every record in the raw layer for full-text search (`vault/memory/index.sqlite`, private, derived: safe to delete). Only changed month files are read again; no model |
| `proxenos import [PATH ...]` | Import downloaded exports (Takeout, X, LinkedIn, Instagram, Spotify, ...) |
| `proxenos ingest <source>` | Pull one source into the vault (whatsapp, slack, slackdump, strava, gmail, ...) |
| `proxenos auth strava` / `proxenos auth slack` | One-time sign-ins that write tokens to `.env` |
| `proxenos observe [--dry-run]` | Write per-month notes on what each source says about me |
| `proxenos master` | Sync, observe and update the self-model (`proxenos master accept` applies proposals) |
| `proxenos clone tracker\|tasks\|advisor` | Feed of new papers and news, tasks on my plate, and advice |
| `proxenos clone network [--people-only]` | People I've met, know of or want to read, and who shares a chat, thread, paper or employer with whom (the page's graph); then project and outreach ideas. `--people-only` needs no model |
| `proxenos clone recall [--people N]` | Memories for today, no model: for each calendar event in the next 48 hours, open task, top feed item and top person, the best past messages, mail and notes about it. Shown on the page's Home; the Memory view and ⌘K search the same index |
| `proxenos clone work [--max N]` | Drafts written as me for open tasks, the top outreach and projects, and the top feed items, to approve, edit, copy or discard in the page's Drafts view. Never sends anything |
| `proxenos night` | `proxenos master`, then the tracker, tasks, advisor, network, recall and work clones, one line each; a failed step doesn't stop the rest. `scripts/install-night.sh` schedules it daily at 01:30 |

## The page

`proxenos web` serves it on http://127.0.0.1:4747, local only. It opens on a landing page: the name, a few live counts from the vault (memories indexed, people, drafts to review, sources, last sync) and the network's shape drawn as a slowly turning sky, with no names. Enter (or the Enter key) goes to the app at `/app`, and is remembered for the browser session; the wordmark in the sidebar goes back.

The app starts on Home, a briefing: today's agenda and tasks, drafts waiting for review with their approval record, memories the day brings to mind, activity per source over 30 days, how fresh each source is, then the feed, advice, network and profile. ⌘K (or `/`) opens the command palette: jump to a view, find someone in the network, or search memory.

Tests: `pytest`. Lint: `ruff check src tests`; for the page, `npm --prefix web run lint` and `npm --prefix web run build`.
