"""Letterboxd diary, watched films, ratings, reviews, watchlist and liked films.

Reads an unzipped Letterboxd export (Settings, Data, Export your data) and writes six streams
into vault/raw/letterboxd/: diary, watched, ratings, reviews, watchlist and likes, from
diary.csv, watched.csv, ratings.csv, reviews.csv, watchlist.csv and likes/films.csv. The
deleted/ and orphaned/ folders aren't read. Every export is a full snapshot, so each run re-reads
one and merges by id.

Every file has Date, Name, Year and Letterboxd URI. Some add Rating (0.5 to 5 stars), Rewatch
("Yes" or empty), Tags (comma-separated), Review and Watched Date. Each record has title (the
film), year, rating, rewatch, tags, text (the review) and url, with None for a column its file
doesn't have. ts is the Watched Date, else the Date the entry was made, at midnight UTC, since
Letterboxd keeps no times.

The Letterboxd URI is the id. A diary entry and a review have their own, and a film in watched,
ratings, watchlist or likes has the film's. A row without a URI is keyed by a hash of its film
and date. A row without a film name or with a date that won't parse is counted as skipped.
"""

import argparse
import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from twin.store import merge_monthly

_STREAMS = {
    "diary": "diary.csv",
    "watched": "watched.csv",
    "ratings": "ratings.csv",
    "reviews": "reviews.csv",
    "watchlist": "watchlist.csv",
    "likes": "likes/films.csv",
}

Row = dict[str, str]


def read_stream(export: Path, stream: str) -> list[dict | None]:
    """One stream's records. None marks a row that couldn't be read."""
    return [_parse(row) for row in _rows(export / _STREAMS[stream])]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / "diary.csv").is_file() and not (export / "watched.csv").is_file():
        raise FileNotFoundError(f"no Letterboxd diary.csv or watched.csv in {export}")
    streams = {stream: read_stream(export, stream) for stream in _STREAMS}
    return _merge(streams, vault / "raw" / "letterboxd")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped export"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: a row the export repeats is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _parse(row: Row | None) -> dict | None:
    if row is None:
        return None
    try:
        return _record(row)
    except (KeyError, ValueError):
        return None


def _record(row: Row) -> dict:
    name, year, logged = row["Name"], row.get("Year"), row.get("Date")
    if not name:
        raise ValueError("no film name")
    when = _day(row.get("Watched Date") or logged)
    rating, rewatch, tags = row.get("Rating"), row.get("Rewatch"), row.get("Tags")
    url = row.get("Letterboxd URI") or None
    return {
        "id": url or _hash(name, year, logged),
        "ts": when.isoformat().replace("+00:00", "Z"),
        "title": name,
        "year": int(year) if year else None,
        "rating": float(rating) if rating else None,
        "rewatch": None if rewatch is None else rewatch.lower() == "yes",
        "tags": _tags(tags) if tags is not None else None,
        "text": row.get("Review") or None,
        "url": url,
    }


def _rows(path: Path) -> list[Row | None]:
    """A CSV's rows by column name, or [] when the file is missing. None stands for a line the
    csv module couldn't read."""
    if not path.is_file():
        return []
    rows: list[Row | None] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error:
                rows.append(None)
                continue
            rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k})
    return rows


def _tags(text: str) -> list[str] | None:
    return [tag.strip() for tag in text.split(",") if tag.strip()] or None


def _day(text: str | None) -> datetime:
    return datetime.strptime(text or "", "%Y-%m-%d").replace(tzinfo=UTC)


def _hash(*parts: str | None) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()[:16]
