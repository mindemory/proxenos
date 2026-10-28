# digital_twin

A digital twin of me that keeps learning from my own data: one shared model of who I am, maintained by a master process, and worker clones that use it for one job each. The first worker is a research and news feed.

Design notes: [architecture](docs/architecture.md), [data sources](docs/data_sources.md), [tracker and page](docs/tracker.md), [landscape](docs/landscape.md).

## Privacy

This repository holds code only. Everything personal lives in a separate private vault (`TWIN_VAULT`, default `~/twin_vault`) that never enters this repo:
- raw exports and messages;
- observations and the self-model;
- tracker items and feedback.

The vault keeps its own local git history of how the self-model changes. Observers only send my own side of conversations to the model, never other people's messages.

## Setup

```bash
CONDA_SUBDIR=osx-arm64 conda env create -f environment.yml
conda activate digital_twin
conda config --env --set subdir osx-arm64
pip install -e ".[dev]"
cp .env.example .env    # then fill in keys
```

## Commands

| Command | What it does |
|---|---|
| `Twin.command` (double-click) or `twin web` | Open the local page at http://127.0.0.1:4747 |
| `twin sync` | Import new downloads from `data/` and refresh every source that needs no model |
| `twin import [PATH ...]` | Import downloaded exports (Takeout, X, LinkedIn, Instagram, Spotify, ...) |
| `twin ingest <source>` | Pull one source into the vault (whatsapp, slack, slackdump, strava, gmail, ...) |
| `twin auth strava` / `twin auth slack` | One-time sign-ins that write tokens to `.env` |
| `twin observe [--dry-run]` | Write per-month notes on what each source says about me |
| `twin master` | Sync, observe and update the self-model (`twin master accept` applies proposals) |
| `twin clone tracker\|tasks\|advisor` | Feed of new papers and news, tasks on my plate, and advice |

Tests: `pytest`. Lint: `ruff check src tests`.
