"""YouTube watch and search history from Google Takeout.

Reads Takeout's "YouTube and YouTube Music" folder and writes two streams into
vault/raw/youtube/: watched, from history/watch-history.json, and searched, from
history/search-history.json. Takeout writes these as HTML unless JSON is picked when the export
is made, so watch-history.html and search-history.html are read too. Every export is a full
snapshot, so each run re-reads one and merges by id. Exports from several accounts all go into
the same streams.

JSON entries have header ("YouTube" or "YouTube Music"), title ("Watched <video>" or "Searched
for <query>"), titleUrl, subtitles[] (name and url of the channel), time (ISO 8601) and
details[]. The HTML has one outer-cell per entry: the header, then a body cell with the same
title as a link, the channel's link, and the time ("Mar 5, 2024, 9:15:02 PM EDT"), then a
caption cell with the details. The HTML names the zone by abbreviation, read with the fixed
offset in _ZONES.

watched has title (the video), url, channel, channel_url and product. searched has text (the
query, which is the user's own words, so from_me) and url. Other entries (a community post viewed, a
survey answered) are left out, and so are ads: entries whose details say "From Google Ads".
The id hashes the time and the video's url (the query's, for a search). An entry whose time
won't parse, or that isn't laid out as above, is counted as skipped.
"""

import argparse
import hashlib
import html
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_WATCHED, _SEARCHED = "Watched ", "Searched for "
_AD = "From Google Ads"
_ZONES = {
    "UTC": 0,
    "GMT": 0,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
    "AKST": -9,
    "AKDT": -8,
    "HST": -10,
    "IST": 5.5,
    "BST": 1,
    "CET": 1,
    "CEST": 2,
    "EET": 2,
    "EEST": 3,
    "JST": 9,
}
_FORMATS = ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S", "%d %b %Y, %H:%M:%S")
_BODY = re.compile(r'mdl-typography--body-1">(.*?)</div>', re.DOTALL)
_HEADER = re.compile(r'mdl-typography--title">(.*?)<br', re.DOTALL)
_LINK = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def read_watched(export: Path) -> list[dict | None]:
    """Videos watched. None marks an entry or file that couldn't be read."""
    records = [_parse(_watch, entry) for entry in _entries(export, "watch-history")]
    return [r for r in records if r is not False]


def read_searched(export: Path) -> list[dict | None]:
    records = [_parse(_search, entry) for entry in _entries(export, "search-history")]
    return [r for r in records if r is not False]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not _files(export, "watch-history") and not _files(export, "search-history"):
        raise FileNotFoundError(f"no YouTube watch-history or search-history in {export}")
    streams = {"watched": read_watched(export), "searched": read_searched(export)}
    return _merge(streams, vault / "raw" / "youtube")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export",
        type=Path,
        required=True,
        metavar="DIR",
        help="Takeout's YouTube and YouTube Music folder",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: an entry in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _watch(entry: dict) -> dict | None:
    title = entry["title"]
    if not title.startswith(_WATCHED) or _is_ad(entry):
        return None
    channel = next(iter(entry.get("subtitles") or []), {})
    url = entry.get("titleUrl") or None
    ts = _stamp(_when(entry["time"]))
    return {
        "id": _hash(ts, url or title),
        "ts": ts,
        "title": title.removeprefix(_WATCHED).strip(),
        "url": url,
        "channel": channel.get("name") or None,
        "channel_url": channel.get("url") or None,
        "product": entry.get("header") or None,
    }


def _search(entry: dict) -> dict | None:
    title = entry["title"]
    if not title.startswith(_SEARCHED) or _is_ad(entry):
        return None
    url = entry.get("titleUrl") or None
    query = title.removeprefix(_SEARCHED).strip()
    ts = _stamp(_when(entry["time"]))
    return {"id": _hash(ts, url or query), "ts": ts, "from_me": True, "text": query, "url": url}


def _parse(make: Callable[[dict], dict | None], entry: Any) -> dict | bool | None:
    """make's record, False for an entry that's left out on purpose, None for a malformed one."""
    if not isinstance(entry, dict):
        return None
    try:
        return make(entry) or False
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _is_ad(entry: dict) -> bool:
    return any(isinstance(d, dict) and d.get("name") == _AD for d in entry.get("details") or [])


def _files(export: Path, stem: str) -> list[Path]:
    return sorted(p for suffix in (".json", ".html") for p in export.rglob(stem + suffix))


def _entries(export: Path, stem: str) -> list[Any]:
    """Every entry in the JSON or HTML history files, in JSON's layout. A file that won't parse
    is one None."""
    entries: list[Any] = []
    for path in _files(export, stem):
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text) if path.suffix == ".json" else _from_html(text)
        except (OSError, ValueError):
            entries.append(None)
            continue
        entries += data if isinstance(data, list) else [None]
    return entries


def _from_html(text: str) -> list[dict | None]:
    """Takeout's HTML history as JSON-style entries."""
    entries: list[dict | None] = []
    for cell in text.split('<div class="outer-cell')[1:]:
        body = _BODY.search(cell)
        if body is None:
            entries.append(None)
            continue
        parts = [part for part in body[1].split("<br>") if part.strip()]
        links = [(html.unescape(href), _plain(label)) for href, label in _LINK.findall(body[1])]
        header = _HEADER.search(cell)
        entries.append(
            {
                "header": _plain(header[1]) if header else None,
                "title": _plain(parts[0]) if parts else "",
                "titleUrl": links[0][0] if links else None,
                "subtitles": [{"name": name, "url": url} for url, name in links[1:]],
                "time": _plain(parts[-1]) if parts else "",
                "details": [{"name": _AD}] if _AD in cell else [],
            }
        )
    return entries


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub("", fragment)).split())


def _when(text: str) -> datetime:
    """A JSON time ("2024-03-05T21:15:02.123Z") or an HTML one ("Mar 5, 2024, 9:15:02 PM EDT")."""
    text = " ".join(text.split())  # also turns the narrow no-break space before PM into a space
    try:
        when = datetime.fromisoformat(text)
        return when.astimezone(UTC) if when.tzinfo else when.replace(tzinfo=UTC)
    except ValueError:
        pass
    stamp, _, zone = text.rpartition(" ")
    offset = _offset(zone)
    for fmt in _FORMATS:
        try:
            local = datetime.strptime(stamp, fmt)
        except ValueError:
            continue
        return local.replace(tzinfo=timezone(offset)).astimezone(UTC)
    raise ValueError(f"unrecognized time {text!r}")


def _offset(zone: str) -> timedelta:
    """A zone abbreviation ("EDT") or offset ("GMT+05:30") as its offset from UTC."""
    if zone in _ZONES:
        return timedelta(hours=_ZONES[zone])
    match = re.fullmatch(r"(?:GMT|UTC)([+-])(\d{1,2})(?::?(\d{2}))?", zone)
    if not match:
        raise ValueError(f"unknown zone {zone!r}")
    sign = -1 if match[1] == "-" else 1
    return sign * timedelta(hours=int(match[2]), minutes=int(match[3] or 0))


def _hash(*parts: str | None) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
