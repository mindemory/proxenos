"""Google Keep notes from Google Takeout.

Reads the .json note files in Takeout's Keep folder (the .html copies beside them are ignored)
and writes one stream into vault/raw/keep/: notes. Every export is a full snapshot, so each run
re-reads one and merges by id. The same note in several exports is one record.

A note has title (None when it has none), text, labels (their names), archived, trashed, pinned
and color. text is the note's textContent, or for a checklist its items joined by line breaks.
ts is when the note was last edited, else created. The id is the file's name without .json, so
a note's id changes with its title, and the old record stays. Notes in the trash are left out.
Keep notes are my own words, so every record is from_me.

A file that isn't a JSON object, or whose time is missing or won't parse, is counted as skipped.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def read_notes(export: Path) -> list[dict | None]:
    """Every note that isn't in the trash. None marks a file that couldn't be read."""
    records = [_parse(path) for path in sorted(export.rglob("*.json"))]
    return [r for r in records if r is not False]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not export.is_dir():
        raise FileNotFoundError(f"no folder at {export}")
    return _merge({"notes": read_notes(export)}, vault / "raw" / "keep")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="Takeout's Keep folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: a note in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _parse(path: Path) -> dict | bool | None:
    """The note in a file, False for one left out on purpose (trashed), None for a bad file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        if data.get("isTrashed"):
            return False
        return _note(data, path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None


def _note(data: dict, path: Path) -> dict:
    when = data.get("userEditedTimestampUsec") or data["createdTimestampUsec"]
    return {
        "id": path.stem,
        "ts": _stamp(_EPOCH + timedelta(microseconds=int(when))),
        "from_me": True,
        "title": data.get("title") or None,
        "text": _text(data),
        "labels": [
            str(label["name"])
            for label in data.get("labels") or []
            if isinstance(label, dict) and label.get("name")
        ],
        "archived": bool(data.get("isArchived")),
        "trashed": False,
        "pinned": bool(data.get("isPinned")),
        "color": data.get("color") or None,
    }


def _text(data: dict) -> str:
    text: Any = data.get("textContent")
    if isinstance(text, str) and text:
        return text
    items = data.get("listContent") or []
    return "\n".join(
        str(item["text"]) for item in items if isinstance(item, dict) and item.get("text")
    )


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
