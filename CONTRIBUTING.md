# Contributing

Thanks for looking. Proxenos is early. The most useful contributions right now are ideas, bug reports and new source readers.

## Ideas and issues

Open an issue for anything that would make Proxenos more useful to you. Ideas for people dealing with hard systems, such as healthcare, insurance or benefits, are especially welcome.

**Please never paste personal data into an issue:** no messages, emails, names or exports. Describe the shape of the problem instead, e.g. the file layout or field names.

## Setup

See the Quick start in the [README](README.md). The `dev` extra installs pytest and ruff.

## Ground rules

- **No personal data in the repo, ever.** Tests build synthetic data inside the test, and `tests/conftest.py` keeps tests away from real credentials and the `data/` folder.
- **Nothing sends, posts or buys on its own.** Clones write drafts; acting is the user's choice. See [docs/roadmap.md](docs/roadmap.md) for how that is meant to change, channel by channel.
- **Re-runs must be safe.** Ingesters merge by id into monthly files (`proxenos.store.merge_monthly`), so running one twice changes nothing.
- **Match the surrounding code:** small modules, docstrings that explain why, stdlib first.

## Adding a source

1. Write `src/proxenos/ingest/<source>.py` with a docstring (its first line is the CLI help), `add_arguments(parser)` and `run(vault, args)`, returning `merge_monthly` stats. The CLI finds it automatically.
2. If the source arrives as a downloaded export, add a route in `proxenos.importer.jobs_for`.
3. Add `tests/test_<source>.py` with a synthetic export.

## Adding a clone

Write `src/proxenos/clones/<name>.py` the same way. Clones read the vault's `self/` folder, never write to it, and put their output under `vault/clones/<name>/`.

## Checks

```bash
pytest
ruff check src tests && ruff format --check src tests
npm --prefix web run lint && npm --prefix web run build
```
