"""Ingesters: one module per source, each writing into the vault's raw layer.

`twin ingest <source>` finds every module here that defines `run`. A module provides:

- a docstring whose first line is the CLI help text;
- `add_arguments(parser)` (optional) for source-specific flags;
- `run(vault: Path, args: argparse.Namespace) -> dict[str, int]`, returning the stats from
  `twin.store.merge_monthly` (or a sum of them).

Normalized records go under `vault / "raw" / <source> / <stream>/` as monthly JSONL via
`merge_monthly`. Each record needs a stable "id" and an ISO-8601 UTC "ts" ending in "Z".
"""
