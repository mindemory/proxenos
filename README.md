# Proxenos

**An agent that holds your entire record and acts on your behalf.**

Proxenos gathers your own data (messages, email, calendar, notes, documents, activity) into one private vault on your computer. From that it keeps a written model of who you are, and runs small agents ("clones") that work for you:
- a feed of new papers and news, ranked for you;
- your open tasks, pulled from your conversations;
- advice grounded in your own patterns;
- a map of the people you know and how they connect;
- a searchable memory that brings the right past messages and notes to mind;
- drafts of replies, emails and plans, written in your voice.

It drafts; it never sends, posts or buys anything by itself. You approve what goes out. The longer-term plan, moving from drafting to acting on approval to acting within rules you set, is in [docs/roadmap.md](docs/roadmap.md).

> **Status: very early.** It's built and used by one person on macOS (Apple Silicon), and it's still primitive: expect rough edges and readers that assume a particular export format. Help of any kind is welcome, whether code, an issue, or an idea over a message or a call, especially about making it useful for people navigating hard systems like healthcare. See [CONTRIBUTING.md](CONTRIBUTING.md).

*The name: in the Greek city-states, a proxenos was the citizen who formally acted on someone else's behalf.*

## How it works

```
your sources ──ingest──▶ vault/raw ──observe──▶ notes ──consolidate──▶ self-model
                              │                                             │
                              └──index──▶ memory (full-text search)         ▼
                                                        clones: feed, tasks, advice,
                                                        network, recall, drafts
                                                                │
                                                        local page (127.0.0.1)
```

- **Ingesters** pull each source into the vault as monthly files. Re-running one is always safe.
- **Observers** read one month of one source (only your own side of conversations) and write notes about you.
- **The master** merges the notes into a single self-model: identity, interests, taste, voice, routines and open questions. Slow-changing parts change only through proposals you accept.
- **Clones** read the self-model and each do one job. The page shows their output and records your reactions, which feed back into the next run.

More detail: [architecture](docs/architecture.md), [data sources](docs/data_sources.md), [the feed and the page](docs/tracker.md), [related work](docs/landscape.md).

## Privacy

- **Code and data are separate.** This repository holds code only. Everything personal lives in a private vault outside the repo (`PROXENOS_VAULT`, default `~/proxenos_vault`). The vault keeps its own local git history of how the self-model changes.
- **What reaches the model:** observers send the model only your side of conversations, never other people's messages. Clones send your self-model, plus public items such as papers and news.
- **The page is local only.** It binds to 127.0.0.1 and rejects requests from other sites.
- **Credentials** stay in `.env`, which git ignores.

## Quick start

Requirements: macOS, Python 3.12 (conda shown here), Node 22+, and an Anthropic API key for the steps that use a model.

```bash
git clone https://github.com/mindemory/proxenos && cd proxenos
CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml
conda activate proxenos
pip install -e ".[dev]"
cp .env.example .env            # add your name, email addresses and ANTHROPIC_API_KEY
```

Add data in any order. Each source works on its own:

```bash
proxenos ingest whatsapp        # reads the WhatsApp Mac app's local store
proxenos import ~/Downloads/takeout-*.zip   # Google Takeout: mail, calendar, Drive, YouTube, ...
proxenos sync                   # imports anything dropped into data/, refreshes every source
```

Then build the model and the clones, and open the page:

```bash
proxenos master                 # notes per month, then the self-model
proxenos clone tracker          # also: tasks, advisor, network, recall, work
proxenos web                    # http://127.0.0.1:4747
```

`proxenos night` runs the whole loop. `scripts/install-night.sh` schedules it every night with launchd.

`px` is a short alias for `proxenos`.

Some sources read a folder on your computer. Set those folders in `.env`: `PROXENOS_SPOTIFY_EXPORT`, `PROXENOS_WEBSITE_REPO` and `PROXENOS_SLACKDUMP_DIR`. `.env.example` lists every setting.

## Sources

| Source | How it gets in |
|---|---|
| WhatsApp | The Mac app's local database (`proxenos ingest whatsapp`) |
| Slack | [slackdump](https://github.com/rusq/slackdump) archives, or a user token |
| Gmail, Google Calendar, Drive, Photos metadata, Keep, Tasks, YouTube, Chrome | Google Takeout zips (`proxenos import`) |
| Email (any) | mbox exports; Gmail over IMAP with an app password |
| Strava | API (`proxenos auth strava`) |
| Spotify | Extended Streaming History export |
| LinkedIn, X, Instagram, Facebook, Threads | Each service's data export |
| Bluesky | Public posts by handle |
| Notion, Obsidian, PDFs | Exports or folders |
| Letterboxd | Data export |
| Personal website, papers and mentions | A local site repo; OpenAlex and news search |

See [docs/data_sources.md](docs/data_sources.md) for each one's details.

## Commands

| Command | What it does |
|---|---|
| `proxenos web` | The local page: a landing, then the app (Home, Feed, Tasks, Drafts, Advice, Network, Memory, Profile, Status) |
| `proxenos sync` | Import new downloads and refresh every source that needs no model; update the memory index and today's recall |
| `proxenos import [PATH ...]` | Recognize and import downloaded exports |
| `proxenos ingest <source>` | Pull one source into the vault |
| `proxenos auth strava` / `slack` | One-time sign-ins that write tokens to `.env` |
| `proxenos observe [--dry-run]` | Per-month notes on what each source says about you |
| `proxenos master [accept]` | Sync, observe and update the self-model; `accept` applies proposed changes |
| `proxenos index [--rebuild]` | Full-text memory index over the whole vault, no model |
| `proxenos clone <name>` | Run one clone: `tracker`, `tasks`, `advisor`, `network`, `recall` or `work` |
| `proxenos night` | Everything above, in order, for a schedule |

## Development

```bash
pytest                                   # tests use synthetic data only
ruff check src tests
npm --prefix web run lint && npm --prefix web run build
```

## License

[MIT](LICENSE)
