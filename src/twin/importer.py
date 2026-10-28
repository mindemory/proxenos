"""Drop-folder imports: put downloaded export zips in vault/inbox/ and run `twin import`.

Each zip (or already-unzipped folder) is unpacked into vault/exports/<name>/, recognized by
the files inside it, and handed to the matching ingester:
- Google Takeout mail: one stream per address;
- Google Takeout's YouTube history and Chrome history;
- calendars: .ics files, such as Google Calendar's export or Takeout/Calendar;
- X/Twitter archives;
- Instagram, Facebook, Threads and LinkedIn exports;
- Spotify Extended Streaming History;
- Letterboxd exports;
- Notion exports and Obsidian vaults.

Takeout splits big exports into -001, -002, ... zips, and parts of one export unpack into the
same folder. Loose PDFs are read as notes. Once imported, downloads are filed away in the
vault under downloads/<source>/, so the inboxes only hold what's still waiting; anything
unrecognized stays where it is.
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
        key = "__pdfs__" if path.suffix.lower() == ".pdf" else _export_name(path)
        groups.setdefault(key, []).append(path)

    stats = Counter()
    pdfs = groups.pop("__pdfs__", [])
    for name, parts in groups.items():
        dest = vault / "exports" / name
        try:
            for part in parts:
                _unpack(part, dest)
        except (OSError, zipfile.BadZipFile) as e:  # one broken download must not stop the rest
            print(f"import: couldn't unpack {name}: {e}", file=sys.stderr)
            stats["failed"] += 1
            continue
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
        sources = sorted({source for source, _ in jobs})
        label = sources[0] if len(sources) == 1 else "google" if "takeout" in name else "mixed"
        _file_away(parts, vault / "downloads" / label)

    if pdfs:
        folder = vault / "downloads" / "notes" / "pdfs"
        _file_away(pdfs, folder)
        try:
            ingest(vault, "notes", ["--pdf-dir", str(folder)])
            stats["notes_imported"] += 1
        except (Exception, SystemExit) as e:  # noqa: BLE001 - report it, keep going
            print(f"import: notes from loose PDFs failed: {e}", file=sys.stderr)
            stats["failed"] += 1
    return dict(stats)


def _file_away(paths: list[Path], folder: Path) -> None:
    """Move imported downloads into the vault, never overwriting one already there."""
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in paths:
        target = folder / path.name
        n = 1
        while target.exists():
            target = folder / f"{path.stem}-{n}{path.suffix}"
            n += 1
        shutil.move(path, target)


def _waiting(path: Path) -> bool:
    """A finished download that hasn't been imported: a zip, a folder or a PDF; never a partial."""
    if path.name.startswith(".") or path.name == "imported":
        return False
    return path.is_dir() or path.suffix.lower() in {".zip", ".pdf"}


def jobs_for(dest: Path) -> list[tuple[str, list[str]]]:
    """(ingester, its CLI arguments) for every export recognized under dest.

    Notes are only looked for outside Takeout folders, since Takeout's Drive can hold anything,
    and a Notion export's PDFs are read as notes too. A pile of loose PDFs is never a zip or a
    folder of its own, so it isn't imported: `twin ingest notes --pdf-dir DIR` reads one.
    """
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
    for history in sorted({p.parent.parent for p in dest.glob("**/Takeout/YouTube*/history/*")}):
        jobs.append(("youtube", ["--export", str(history)]))
    for chrome in sorted({p.parent for p in dest.glob("**/Takeout/Chrome/*History.json")}):
        jobs.append(("chrome", ["--export", str(chrome)]))
    for activity in sorted(dest.glob("**/your_facebook_activity")):
        jobs.append(("facebook", ["--export", str(activity.parent)]))
    for posts in sorted(dest.glob("**/threads/threads_and_replies.json")):
        jobs.append(("threads", ["--export", str(posts.parent.parent)]))
    for diary in sorted(dest.glob("**/diary.csv")):
        if (diary.parent / "watched.csv").is_file():
            jobs.append(("letterboxd", ["--export", str(diary.parent)]))

    # One calendar job per topmost folder holding .ics files (Google's export, Takeout/Calendar).
    calendars = {p.parent for p in dest.glob("**/*.ics") if "__MACOSX" not in p.parts}
    for folder in sorted(calendars):
        if not any(parent in calendars for parent in folder.parents):
            jobs.append(("calendar", ["--export", str(folder)]))

    # Notion names files "Title <32 hex id>", and an Obsidian vault holds a .obsidian folder.
    found = [p for p in dest.rglob("*") if "Takeout" not in p.relative_to(dest).parts]
    notion = any(re.search(r" [0-9a-f]{32}(_all)?(\.\w+)?$", p.name) for p in found)
    obsidian = any(p.name == ".obsidian" for p in found)
    markdown = sum(p.suffix.lower() == ".md" and "__MACOSX" not in p.parts for p in found)
    if notion or obsidian or (markdown >= 10 and not jobs):
        argv = ["--export", str(dest)]
        if notion and any(p.suffix.lower() == ".pdf" for p in found):
            argv += ["--pdf-dir", str(dest)]
        jobs.append(("notes", argv))
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
                if not _wanted(info.filename):
                    continue
                try:
                    target = archive.extract(info, dest)
                except OSError as e:
                    # e.g. a Takeout file whose name is longer than the file system allows
                    print(f"import: skipped {info.filename[:80]}...: {e.strerror}", file=sys.stderr)
                    continue
                # Files keep their time from the zip (local time), which notes fall back on.
                if not info.is_dir():
                    when = time.mktime((*info.date_time, 0, 0, -1))
                    os.utime(target, (when, when))
    else:
        return
    marker.touch()


# Takeout parts can be tens of GB, nearly all of it photo and video files. Those stay in the zip
# (kept under downloads/); everything else, including Photos' metadata and Drive's documents,
# is unpacked.
_MEDIA = (
    ".jpg",
    ".jpeg",
    ".heic",
    ".png",
    ".gif",
    ".webp",
    ".dng",
    ".raw",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".3gp",
    ".mkv",
    ".mts",
    ".wmv",
    ".mpg",
)


def _wanted(name: str) -> bool:
    """Everything outside Takeout; inside it, everything but the photo and video files."""
    return "Takeout/" not in name or not name.lower().endswith(_MEDIA)


def _ingest(vault: Path, source: str, argv: list[str]) -> dict[str, int]:
    module = importlib.import_module(f"twin.ingest.{source}")
    parser = argparse.ArgumentParser(prog=f"twin ingest {source}")
    module.add_arguments(parser)
    stats = module.run(vault, parser.parse_args(argv))
    print(f"import: {source}: " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    return stats
