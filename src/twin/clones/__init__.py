"""Worker clones: each does one job for me, using the shared self-model.

Clones read `vault/self/` (written only by the master) and never change it. Each writes its
output under its own corner of the vault, and anything it learns about me goes back through
the master as feedback or observations, never directly into `self/`.

`twin clone <name>` finds every module here that defines `run`. A module provides:

- a docstring whose first line is the CLI help text;
- `add_arguments(parser)` (optional);
- `run(vault: Path, args: argparse.Namespace) -> dict[str, int]`, returning counts to print.
"""
