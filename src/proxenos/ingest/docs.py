"""Folders of documents kept current: PROXENOS_DOCS_DIRS, comma-separated (a health records
folder, say). Each is read the way notes.py reads Markdown notes and PDFs, into vault/raw/notes/, so a
document saved there is in the vault, the memory index and Care within a sync. A folder is read
again only when something in it is newer than the last read, kept in vault/state/docs.json, so a
quiet folder costs a sync nothing. It only reads.
"""

import argparse
import json
from pathlib import Path

from proxenos.config import env
from proxenos.ingest import notes


def folders() -> list[Path]:
    return [Path(p.strip()).expanduser() for p in env("DOCS_DIRS").split(",") if p.strip()]


def ingest(vault: Path, dirs: list[Path], full: bool = False) -> dict[str, int]:
    state_path = vault / "state" / "docs.json"
    state = json.loads(state_path.read_text()) if state_path.exists() and not full else {}
    stats = {"folders_read": 0, "folders_unchanged": 0}
    for folder in dirs:
        if not folder.is_dir():
            raise SystemExit(f"docs: no folder at {folder}")
        newest = max((p.stat().st_mtime for p in folder.rglob("*") if p.is_file()), default=0.0)
        if newest <= state.get(str(folder), -1):
            stats["folders_unchanged"] += 1
            continue
        try:  # its Markdown notes and its PDFs, each as notes.py reads them
            found = notes.ingest(vault, folder, folder)
        except FileNotFoundError:  # nothing in it that's a note yet
            found = {}
        for key, value in found.items():
            stats[key] = stats.get(key, 0) + value
        state[str(folder)] = newest
        stats["folders_read"] += 1
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state))
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--full", action="store_true", help="read every folder again")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, folders(), args.full)
