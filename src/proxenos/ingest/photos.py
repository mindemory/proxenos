"""Photo and album metadata from Google Takeout's Google Photos folder.

Reads only the JSON files, never the photos and videos themselves (the importer leaves those in
the zip), and writes one stream into vault/raw/photos/: meta. Every export is a full snapshot, so
each run re-reads one and merges by id. The same photo in several exports is one record.

meta has two kinds of record:
- photo, from a sidecar (a JSON file next to the media, named like "IMG_1.jpg.json" or
  "IMG_1.jpg.supplemental-metadata.json"). title is the file's name, ts is photoTakenTime (else
  creationTime), geo is {"lat", "lon"} rounded to 3 decimals, or None for a photo without a
  location (0,0); Google's own location is used, then the one in the photo's EXIF. people are the
  names of the faces tagged, album is the folder the photo sits in ("Photos from 2019" or an
  album's name), and description and url are Google's. The id is album/title. Two photos of one
  album with the same file name but different times are different photos, so the later one's id
  ends in #2 (#3, ...), in time order.
- album, from a folder's metadata.json when it has a date or a description (an album's title is
  its folder name already): title, description, album, and ts, which is the album's date, else
  the file's modified time, which the importer keeps from the zip. The id is album/metadata.json.

Other JSON in the folder (shared-album comments, memory titles) is left alone. A file that
isn't JSON, or a sidecar whose time won't parse, is counted as skipped.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SIDECAR_SUFFIX = (".supplemental-metadata", ".supplemental-metadat", ".supplemental-metada")


def read_meta(export: Path) -> list[dict | None]:
    """Every photo and album. None marks a file that couldn't be read."""
    photos: list[tuple[str, dict]] = []
    others: list[dict | None] = []
    for path in sorted(export.rglob("*.json")):
        if any(part.startswith(".") for part in path.relative_to(export).parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            others.append(None)
            continue
        if not isinstance(data, dict):
            continue
        try:
            if "photoTakenTime" in data or "creationTime" in data:
                photos.append(_photo(data, path))
            elif path.name.lower() == "metadata.json" and (album := _album(data, path)):
                others.append(album)
        except (KeyError, TypeError, ValueError, OverflowError, OSError, AttributeError):
            others.append(None)
    return _with_ids(photos) + others


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not export.is_dir():
        raise FileNotFoundError(f"no folder at {export}")
    return _merge({"meta": read_meta(export)}, vault / "raw" / "photos")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="Takeout's Google Photos folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: a photo in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _photo(data: dict, path: Path) -> tuple[str, dict]:
    """(key, record) for a sidecar. The key is album/title, before duplicates are told apart."""
    taken = _time(data.get("photoTakenTime") or data["creationTime"])
    album = path.parent.name
    title = str(data.get("title") or _media_name(path))
    record = {
        "ts": _stamp(taken),
        "kind": "photo",
        "title": title,
        "geo": _geo(data.get("geoData")) or _geo(data.get("geoDataExif")),
        "people": [
            str(p["name"])
            for p in data.get("people") or []
            if isinstance(p, dict) and p.get("name")
        ],
        "album": album,
        "description": data.get("description") or None,
        "url": data.get("url") or None,
    }
    return f"{album}/{title}", record


def _album(data: dict, path: Path) -> dict | None:
    description = data.get("description") or None
    date = data.get("date")
    if not description and not date:
        return None
    folder = path.parent.name
    modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return {
        "id": f"{folder}/metadata.json",
        "ts": _stamp(_time(date) if date else modified),
        "kind": "album",
        "title": str(data.get("title") or folder),
        "description": description,
        "album": folder,
    }


def _media_name(path: Path) -> str:
    """The media file a sidecar belongs to, from its own name, for a sidecar without a title."""
    stem = path.name.removesuffix(".json")
    for suffix in _SIDECAR_SUFFIX:
        stem = stem.removesuffix(suffix)
    return stem


def _geo(place: Any) -> dict | None:
    """{"lat", "lon"} to 3 decimals, or None when there's no location (Google writes 0, 0)."""
    if not isinstance(place, dict):
        return None
    lat, lon = float(place.get("latitude") or 0), float(place.get("longitude") or 0)
    if lat == 0 and lon == 0:
        return None
    return {"lat": round(lat, 3), "lon": round(lon, 3)}


def _time(value: Any) -> datetime:
    """A {"timestamp": "<seconds>"} object as UTC."""
    return _EPOCH + timedelta(seconds=int(value["timestamp"]))


def _with_ids(keyed: list[tuple[str, dict]]) -> list[dict | None]:
    """Photos with ids from their keys. Photos that share a key but not a time are different
    photos: the earliest keeps the key and the rest get #2, #3, ... Exact copies are one."""
    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    for key, record in keyed:
        groups[key][record["ts"]] = record  # the last copy of a photo wins
    out: list[dict | None] = []
    for key, by_time in groups.items():
        for n, ts in enumerate(sorted(by_time), start=1):
            out.append({"id": key if n == 1 else f"{key}#{n}", **by_time[ts]})
    return out


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
