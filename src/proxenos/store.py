"""Month-partitioned JSONL: the raw layer every ingester writes into.

Records need an "id" and an ISO-8601 UTC "ts". Writes merge by id into what is already
on disk, so re-running an ingester is safe: new ids are added, changed records replace
the old ones, and records the source has since dropped are kept.

State that isn't dated, such as who is in a group, goes to one snapshot.jsonl per stream
instead, merged by id the same way. It isn't a month file, so the observers never read it.

Everything here is private, as the whole vault is: each file only the user can read (0600), in
folders only they can open (0700). `private_dir`, `write_private` and `private_tree` are how the
rest of Proxenos writes into the vault the same way.
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

    private_dir(directory)
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
    private_dir(directory)
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
    with _private(tmp) as f:  # the same bytes on every platform
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def private_dir(directory: Path) -> Path:
    """`directory`, made if it's missing, with each folder made on the way, only the user's to
    open (0700); one made before this was kept, more open, is made so too. (mkdir's own mode
    skips the parents it makes, and an existing folder.) On Windows the user's folder is what
    keeps it private."""
    missing = []
    at = directory
    while not at.exists():
        missing.append(at)
        at = at.parent
    for folder in reversed(missing):
        folder.mkdir(mode=0o700, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


def write_private(path: Path, text: str) -> None:
    """`text` in `path`, swapped in whole, only the user's to read, in a folder only theirs."""
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    with _private(tmp) as f:
        f.write(text)
    os.replace(tmp, path)


def private_tree(root: Path) -> None:
    """Everything under `root`, and `root`, made the user's alone: what an unpacked export or a
    moved download brings keeps the modes it had, readable by anyone on the computer."""
    if os.name == "nt":
        return
    if root.is_file():
        root.chmod(0o600)
        return
    for folder, _, files in os.walk(root):
        Path(folder).chmod(0o700)
        for name in files:
            path = Path(folder, name)
            if not path.is_symlink():
                path.chmod(0o600)


def _private(path: Path):
    """`path` opened to write text, new or emptied, 0600 either way (the mode os.open gives
    only applies to a new file; os.fchmod isn't on Windows)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if os.name != "nt":
        path.chmod(0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="\n")
