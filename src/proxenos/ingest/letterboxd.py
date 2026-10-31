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

An export is a download the user has to remember, so with --user (or PROXENOS_LETTERBOXD_USER)
it also reads the member's public RSS feed, their last 50 or so diary entries, into a seventh
stream, feed, and sync does that on every run: films logged since the last export come in without
one. A feed entry adds liked (the heart) and tmdb ("movie/<id>" or "tv/<id>") and is keyed by the
feed's guid, not a boxd.it link, so a film that's in an export too is in both: readers match films
by title and year. The feed's lists and other non-diary items aren't read.
"""

import argparse
import csv
import hashlib
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from proxenos.config import env
from proxenos.store import merge_monthly

FEED_URL = "https://letterboxd.com/{user}/rss/"
TIMEOUT = 20  # seconds
# Letterboxd turns away urllib's own User-Agent.
USER_AGENT = "proxenos (+https://github.com/mindemory/proxenos)"

_STREAMS = {
    "diary": "diary.csv",
    "watched": "watched.csv",
    "ratings": "ratings.csv",
    "reviews": "reviews.csv",
    "watchlist": "watchlist.csv",
    "likes": "likes/films.csv",
}

Row = dict[str, str]
# Takes a URL and returns the response body, raising the way urlopen does.
Fetch = Callable[[str], bytes]

_NS = {"letterboxd": "https://letterboxd.com", "tmdb": "https://themoviedb.org"}
_TAG = re.compile(r"<[^>]+>")
# What the feed puts in a description besides a review: the poster, the date, a spoiler warning.
_BOILERPLATE = re.compile(r"^(Watched on \w+ \w+ \d+, \d{4}\.|This review may contain spoilers\.)$")


def read_stream(export: Path, stream: str) -> list[dict | None]:
    """One stream's records. None marks a row that couldn't be read."""
    return [_parse(row) for row in _rows(export / _STREAMS[stream])]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / "diary.csv").is_file() and not (export / "watched.csv").is_file():
        raise FileNotFoundError(f"no Letterboxd diary.csv or watched.csv in {export}")
    streams = {stream: read_stream(export, stream) for stream in _STREAMS}
    return _merge(streams, vault / "raw" / "letterboxd")


def read_feed(user: str, fetch: Fetch | None = None) -> list[dict | None]:
    """The diary entries in a member's public feed. None marks one that couldn't be read."""
    body = (fetch or _fetch)(FEED_URL.format(user=urllib.parse.quote(user.strip().lstrip("@"))))
    items = ET.fromstring(body).iter("item")
    return [_entry(i) for i in items if i.find("letterboxd:filmTitle", _NS) is not None]


def ingest_feed(vault: Path, user: str, fetch: Fetch | None = None) -> dict[str, int]:
    return _merge({"feed": read_feed(user, fetch)}, vault / "raw" / "letterboxd")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export", type=Path, metavar="DIR", help="the unzipped export")
    parser.add_argument(
        "--user",
        metavar="NAME",
        help="your Letterboxd username, to read your public diary feed "
        "(default: $PROXENOS_LETTERBOXD_USER)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    user = args.user or env("LETTERBOXD_USER")
    if not args.export and not user:
        raise SystemExit(
            "letterboxd: pass --export DIR (the unzipped export), or --user NAME (or set "
            "PROXENOS_LETTERBOXD_USER) to read your public diary feed"
        )
    stats = ingest(vault, args.export.expanduser()) if args.export else {}
    if user:
        for key, value in ingest_feed(vault, user).items():
            stats[key] = stats.get(key, 0) + value
    return stats


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def _entry(item: ET.Element) -> dict | None:
    """One feed item as a record, None when it has no guid or date that reads."""

    def text(tag: str) -> str:
        return (item.findtext(tag, "", _NS) or "").strip()

    try:
        watched, posted = text("letterboxd:watchedDate"), text("pubDate")
        when = _day(watched) if watched else parsedate_to_datetime(posted).astimezone(UTC)
        year, rating = text("letterboxd:filmYear"), text("letterboxd:memberRating")
        movie, show = text("tmdb:movieId"), text("tmdb:tvId")
        record = {
            "id": text("guid"),
            "ts": when.isoformat().replace("+00:00", "Z"),
            "title": text("letterboxd:filmTitle"),
            "year": int(year) if year else None,
            "rating": float(rating) if rating else None,
            "rewatch": text("letterboxd:rewatch").lower() == "yes",
            "liked": text("letterboxd:memberLike").lower() == "yes",
            "tags": None,
            "text": _review(text("description")),
            "url": text("link") or None,
            "tmdb": f"movie/{movie}" if movie else f"tv/{show}" if show else None,
        }
    except (TypeError, ValueError):
        return None
    return record if record["id"] and record["title"] else None


def _review(description: str) -> str | None:
    """The review in a feed item's HTML description, without the poster and the date line."""
    paragraphs = re.split(r"</p>|<br\s*/?>", description)
    lines = [" ".join(html.unescape(_TAG.sub(" ", p)).split()) for p in paragraphs]
    return "\n\n".join(line for line in lines if line and not _BOILERPLATE.match(line)) or None


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
