"""Chrome browsing history from Google Takeout.

Reads Takeout/Chrome/History.json (BrowserHistory.json in older Takeouts) anywhere under
--export and writes one stream, vault/raw/chrome/visits. Takeout only holds the history Chrome
synced to the account, and every export is a full snapshot of it, so each run re-reads one and
merges by id. Exports from several accounts all go into the same stream.

The file has "Browser History"[] with url, title, time_usec (microseconds since 1970, UTC),
page_transition_qualifier and client_id (the device). A record keeps url and title. Entries
without a title are dropped, since they are mostly redirects and downloads. An entry without a
url or time, and a file that isn't JSON, is counted as skipped. The id hashes time_usec and url.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_FILES = ("History.json", "BrowserHistory.json")


def read_visits(export: Path) -> list[dict | None]:
    """Every titled visit. None marks an entry or file that couldn't be read."""
    records: list[dict | None] = []
    for path in _files(export):
        try:
            with path.open(encoding="utf-8") as f:
                entries = json.load(f)["Browser History"]
        except (OSError, ValueError, KeyError, TypeError):
            records.append(None)
            continue
        for entry in entries if isinstance(entries, list) else [None]:
            if isinstance(entry, dict) and not entry.get("title"):
                continue
            records.append(_parse(entry))
    return records


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not _files(export):
        raise FileNotFoundError(f"no Chrome History.json in {export}")
    records = read_visits(export)
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    # Keyed by id: a visit in two exports is one record, and the last copy wins.
    kept = {r["id"]: r for r in records if r is not None}
    if kept:
        stats = merge_monthly(kept.values(), vault / "raw" / "chrome" / "visits")
    return {**stats, "skipped": sum(r is None for r in records)}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="Takeout's Chrome folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _parse(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    try:
        micros, url = int(entry["time_usec"]), entry["url"]
        when = datetime.fromtimestamp(micros / 1_000_000, UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None
    if not url:
        return None
    return {
        "id": hashlib.sha256(f"{micros}\n{url}".encode()).hexdigest()[:16],
        "ts": when.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "url": url,
        "title": entry["title"],
    }


def _files(export: Path) -> list[Path]:
    return sorted(p for name in _FILES for p in export.rglob(name) if p.is_file())
