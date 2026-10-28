"""Drop-folder imports: put downloaded export zips in vault/inbox/ and run `twin import`.

Each zip (or already-unzipped folder) is unpacked into vault/exports/<name>/, recognized by
the files inside it, and handed to the matching ingester:
- Google Takeout mail: one stream per address;
- X/Twitter archives;
- Instagram and LinkedIn exports;
- Spotify Extended Streaming History.

Takeout splits big exports into -001, -002, ... zips, and parts of one export unpack into the
same folder. Imported zips move to inbox/imported/, so the inbox only holds what's still
waiting. Anything unrecognized stays where it is and is reported.
"""

import argparse
import importlib
import os
import re
import shutil
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

_PART = re.compile(r"^(?P<export>.+)-\d{3}$")
_DELIVERED_TO = re.compile(rb"^Delivered-To:\s*<?([^\s>]+@[^\s>]+)>?", re.IGNORECASE | re.MULTILINE)


def inboxes(vault: Path) -> list[Path]:
    """Where downloads wait: vault/inbox, plus the repo's own (git-ignored) data/ folder."""
    from twin.config import REPO_ROOT

    found = [vault / "inbox"]
    if (REPO_ROOT / "data").is_dir():
        found.append(REPO_ROOT / "data")
    return found


def run(vault: Path, paths: list[Path] | None = None, ingest=None) -> dict[str, int]:
    """Import every zip or folder in `paths` (default: everything waiting in the inboxes)."""
    (vault / "inbox").mkdir(mode=0o700, parents=True, exist_ok=True)
    ingest = ingest or _ingest
    if paths is None:
        paths = [p for inbox in inboxes(vault) for p in sorted(inbox.iterdir()) if _waiting(p)]
    # Parts of one Takeout export unpack together and are ingested once.
    groups: dict[str, list[Path]] = {}
    for path in paths:
        groups.setdefault(_export_name(path), []).append(path)

    stats = Counter()
    for name, parts in groups.items():
        dest = vault / "exports" / name
        for part in parts:
            _unpack(part, dest)
        jobs = jobs_for(dest)
        if not jobs:
            stats["unrecognized"] += len(parts)
            continue
        for source, argv in jobs:
            try:
                ingest(vault, source, argv)
                stats[f"{source}_imported"] += 1
            except (Exception, SystemExit) as e:  # noqa: BLE001 - report it, keep going
                print(f"import: {source} from {name} failed: {e}", file=sys.stderr)
                stats["failed"] += 1
        for part in parts:
            done = part.parent / "imported"
            done.mkdir(exist_ok=True)
            shutil.move(part, done / part.name)
    return dict(stats)


def _waiting(path: Path) -> bool:
    """A finished download that hasn't been imported: a zip or a folder, not a partial file."""
    if path.name.startswith(".") or path.name == "imported":
        return False
    return path.is_dir() or path.suffix == ".zip"


def jobs_for(dest: Path) -> list[tuple[str, list[str]]]:
    """(ingester, its CLI arguments) for every export recognized under dest."""
    jobs = []
    for mbox in sorted(dest.glob("**/Takeout/Mail/*.mbox")):
        jobs.append(("email", ["--account", mail_account(mbox), "--mbox", str(mbox)]))
    for manifest in sorted(dest.glob("**/data/manifest.js")):
        jobs.append(("twitter", ["--export", str(manifest.parent.parent)]))
    for activity in sorted(dest.glob("**/your_instagram_activity")):
        jobs.append(("instagram", ["--export", str(activity.parent)]))
    for connections in sorted(dest.glob("**/Connections.csv")):
        jobs.append(("linkedin", ["--export", str(connections.parent)]))
    for history in sorted({p.parent for p in dest.glob("**/Streaming_History_Audio_*.json")}):
        jobs.append(("spotify", ["--export", str(history)]))
    if not jobs and any(dest.glob("**/your_facebook_activity")):
        print(f"import: Facebook export kept at {dest}; it isn't ingested yet", file=sys.stderr)
    return jobs


def mail_account(mbox: Path, scan_bytes: int = 20_000_000) -> str:
    """The stream name for a Takeout mbox: its owner's address, made path-safe."""
    with mbox.open("rb") as f:
        head = f.read(scan_bytes)
    addresses = Counter(a.lower() for a in _DELIVERED_TO.findall(head))
    if not addresses:
        return re.sub(r"[^\w-]", "-", mbox.parent.parent.parent.name.lower()) or "takeout"
    address = addresses.most_common(1)[0][0].decode("ascii", "replace")
    return re.sub(r"[^\w-]", "-", address)


def _export_name(path: Path) -> str:
    stem = path.name.removesuffix(".zip")
    match = _PART.match(stem)
    return match.group("export") if match else stem


def _unpack(path: Path, dest: Path) -> None:
    """Unpack a zip, or copy a folder, into dest once. A marker file skips it on later passes,
    since exports that aren't recognized yet stay in the inbox and come back every sync."""
    marker = dest / f".unpacked-{path.name}"
    if marker.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, dest, dirs_exist_ok=True)
    elif zipfile.is_zipfile(path):
        # zipfile drops absolute paths and ".." parts, so nothing lands outside dest.
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                target = archive.extract(info, dest)
                # Files keep their time from the zip (local time), which notes fall back on.
                if not info.is_dir():
                    when = time.mktime((*info.date_time, 0, 0, -1))
                    os.utime(target, (when, when))
    else:
        return
    marker.touch()


def _ingest(vault: Path, source: str, argv: list[str]) -> dict[str, int]:
    module = importlib.import_module(f"twin.ingest.{source}")
    parser = argparse.ArgumentParser(prog=f"twin ingest {source}")
    module.add_arguments(parser)
    stats = module.run(vault, parser.parse_args(argv))
    print(f"import: {source}: " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    return stats
