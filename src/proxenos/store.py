"""Month-partitioned JSONL: the raw layer every ingester writes into.

Records need an "id" and an ISO-8601 UTC "ts". Writes merge by id into what is already
on disk, so re-running an ingester is safe: new ids are added, changed records replace
the old ones, and records the source has since dropped are kept.

State that isn't dated, such as who is in a group, goes to one snapshot.jsonl per stream
instead, merged by id the same way. It isn't a month file, so the observers never read it.
"""

import json
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path


def merge_monthly(records: Iterable[dict], directory: Path) -> dict[str, int]:
    by_month: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_month[record["ts"][:7]].append(record)

    directory.mkdir(parents=True, exist_ok=True)
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    for month, incoming in sorted(by_month.items()):
        path = directory / f"{month}.jsonl"
        existing = _load(path)
        merged = dict(existing)
        for record in incoming:
            stats["read"] += 1
            old = existing.get(record["id"])
            if old is None:
                stats["added"] += 1
            elif old != record:
                stats["updated"] += 1
            merged[record["id"]] = record
        if merged != existing:
            _write(path, sorted(merged.values(), key=lambda r: (r["ts"], r["id"])))
            stats["months_written"] += 1
    return stats


def drop_monthly(directory: Path, drop: Callable[[dict], bool], until: str = "9999") -> int:
    """Take the records `drop` picks out of directory's month files, those up to the month of
    `until` only, as when a fuller source replaces them. How many went."""
    dropped = 0
    for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        if path.name[:7] > until[:7]:
            continue
        records = _load(path)
        kept = [r for r in records.values() if not drop(r)]
        if len(kept) < len(records):
            dropped += len(records) - len(kept)
            _write(path, sorted(kept, key=lambda r: (r["ts"], r["id"])))
    return dropped


SNAPSHOT = "snapshot.jsonl"


def merge_snapshot(records: Iterable[dict], directory: Path) -> int:
    """Write records with an "id" (and no "ts" needed) to directory/snapshot.jsonl: those read
    now replace their old copies, the rest are kept. Returns how many were read."""
    incoming = {record["id"]: record for record in records}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SNAPSHOT
    existing = _load(path)
    merged = existing | incoming
    if merged != existing or not path.exists():
        _write(path, sorted(merged.values(), key=lambda r: r["id"]))
    return len(incoming)


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["id"]: r for r in map(json.loads, f)}


def _write(path: Path, records: list[dict]) -> None:
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:  # the same bytes on every platform
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
