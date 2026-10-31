# AGENTS.md

Notes for AI coding agents (and people) working in this repo. The README says what Proxenos is; this says how to change it safely.

## The repo

- `src/proxenos/`: the Python package and the `proxenos` command (`cli.py`).
  - `ingest/`: one module per source. Each pulls its source into the vault as monthly JSONL files, merged by id, so a re-run changes nothing.
  - `clones/`: one module per agent (tasks, care, advisor, network, recall, projects, steps, errands, work). Each reads the vault and writes its output under `vault/clones/<name>/`.
  - `master.py`: sync, observe and the self-model. `chats.py`: conversations waiting on the user. `voice.py`: writing as the user. `fidelity.py`: how close drafts came to what was sent. `llm.py`: the model, local (Ollama) or hosted.
- `web/`: the local page (Next.js). API routes in `web/src/app/api/` read the vault and run the `proxenos` command; views in `web/src/components/views/`.
- `tests/`: pytest, synthetic data only.
- `docs/`: architecture, memory, data sources, roadmap, the plan for everyone ([docs/everyone.md](docs/everyone.md)).
- `scripts/`: installers for the Mac (launchd jobs, the app), and the README's screenshots.

## Commands

```bash
pytest -q                                         # all tests, no network, no model
ruff check src tests && ruff format --check src tests
npm --prefix web run lint && (cd web && npx tsc --noEmit -p .) && npm --prefix web run build
proxenos demo                                      # a made-up vault to try the page on
```

GitHub runs the same checks on macOS and Windows for every push ([.github/workflows/checks.yml](.github/workflows/checks.yml)).

## Rules

- **No personal data in the repo, ever.** The vault lives outside it. Tests build synthetic data inside the test; `tests/conftest.py` keeps them away from real credentials and the `data/` folder. Never paste real messages, names or exports into code, tests, docs or issues.
- **Nothing sends, posts or buys on its own.** Clones write drafts; the user sends. The one exception is the outbox the user switches on per app ([docs/memory.md](docs/memory.md)).
- **Re-runs are safe.** Ingesters merge by id (`proxenos.store.merge_monthly`).
- **Other people's messages reach a model only where a clone needs them**, picked out in code, as the README's Privacy section lists. Keep it that way, and update that list when it changes.
- **Files are private:** the vault's files are 0600 in 0700 folders. Tests check modes only where the platform has them (`os.name == "nt" or ...`).
- **Match the surrounding code:** small modules, a docstring that says why, stdlib first, the same comment density and naming as the file you're in. Ruff's line length is 100.
- **Credit what you borrow.** Code or data from another project keeps its licence and copyright notice and goes in [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md). Prefer permissive licences.
- **Commits:** one plain sentence saying what changed, no attribution trailers.

## Adding things

- A source: [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-source).
- A clone: [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-clone).
- A view on the page: a component in `web/src/components/views/`, an API route under `web/src/app/api/`, and its types in `web/src/lib/types.ts`.
