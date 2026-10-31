# Contributing

Thanks for looking. Proxenos is early. The most useful contributions right now are ideas, bug reports and new source readers.

## Good first contributions

Pick one, say so in an issue, and ask anything along the way:

- **A source people need:** iMessage (the Messages app's local database), Signal or Telegram exports, or a patient portal's record download as C-CDA (XML). See [Adding a source](#adding-a-source).
- **A smaller Mac:** find and document an Ollama model that drafts well on a 16 GB Mac, and what the setup page should suggest for it.
- **Windows:** run Proxenos from source on Windows and report or fix what breaks. The checks already run there; the sources and the schedule need people.
- **The privacy screen:** what stays on the computer, what reaches a model, and Delete everything, as [docs/everyone.md](docs/everyone.md#the-privacy-screen) plans it.
- **A setup guide for non-coders:** every step from a new Mac to a first draft, with pictures from `proxenos demo`.
- **If you work in health care:** read what the care view shows on the demo (`proxenos demo`) and say what's missing, what to track, and what a patient should ask. That's what would make it preventive.

Using an AI coding agent? Point it at [AGENTS.md](AGENTS.md) first.

## Ideas and issues

Open an issue for anything that would make Proxenos more useful to you. Ideas for people dealing with hard systems, such as healthcare, insurance or benefits, are especially welcome.

**Please never paste personal data into an issue:** no messages, emails, names or exports. Describe the shape of the problem instead, e.g. the file layout or field names.

Security problems go privately, not in an issue: see [SECURITY.md](SECURITY.md).

Everyone taking part agrees to the [code of conduct](CODE_OF_CONDUCT.md).

## Setup

See the Quick start in the [README](README.md). The `dev` extra installs pytest and ruff.

## Ground rules

- **No personal data in the repo, ever.** Tests build synthetic data inside the test, and `tests/conftest.py` keeps tests away from real credentials and the `data/` folder.
- **Nothing sends, posts or buys on its own.** Clones write drafts; acting is the user's choice. See [docs/roadmap.md](docs/roadmap.md) for how that is meant to change, channel by channel.
- **Re-runs must be safe.** Ingesters merge by id into monthly files (`proxenos.store.merge_monthly`), so running one twice changes nothing.
- **Match the surrounding code:** small modules, docstrings that explain why, stdlib first.
- **Credit what you borrow.** Code or data from another project keeps its licence and copyright notice, and goes in [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md). Prefer permissive licences.

## Adding a source

1. Write `src/proxenos/ingest/<source>.py` with a docstring (its first line is the CLI help), `add_arguments(parser)` and `run(vault, args)`, returning `merge_monthly` stats. The CLI finds it automatically.
2. If the source arrives as a downloaded export, add a route in `proxenos.importer.jobs_for`.
3. Add `tests/test_<source>.py` with a synthetic export.

## Adding a clone

Write `src/proxenos/clones/<name>.py` the same way. Clones read the vault's `self/` folder, never write to it, and put their output under `vault/clones/<name>/`.

## Checks

These also run on GitHub for every push and pull request ([.github/workflows/checks.yml](.github/workflows/checks.yml)).

```bash
pytest
ruff check src tests && ruff format --check src tests
npm --prefix web run lint && npm --prefix web run build
```
