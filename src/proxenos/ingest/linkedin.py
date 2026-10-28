"""LinkedIn profile, posts, comments, messages and connections from the data export.

Reads an unzipped "Get a copy of your data" export (Settings, Data privacy) and writes five
streams into vault/raw/linkedin/: profile, posts, comments, messages and connections. Every
export is a full snapshot, so each run re-reads one and merges by id.

The files and columns below follow LinkedIn's export as documented. They have only been checked
against synthetic CSVs, since no real export has been read yet. File names match in any case,
and column names ignoring case, spaces and punctuation, with the alternatives in _COLUMNS:
- Profile.csv: First Name, Last Name, Headline, Summary, Industry, Geo Location. The full name
  marks from_me in messages.
- Positions.csv: Company Name, Title, Description, Location, Started On, Finished On.
- Education.csv: School Name, Degree Name, Notes, Activities, Start Date, End Date.
  Both take "Jan 2020" or "2020" dates.
- Shares.csv: Date, ShareLink, ShareCommentary, SharedUrl, Visibility.
- Comments.csv: Date, Link, Message.
- messages.csv: CONVERSATION ID, CONVERSATION TITLE, FROM, TO, DATE, SUBJECT, CONTENT, FOLDER.
- Connections.csv: First Name, Last Name, URL, Company, Position, Connected On ("12 Apr 2023").
  Email Address is never read, and URL only goes into the id.
Times ("2023-04-12 15:30:45", with or without " UTC") are taken as UTC. Some files open with
"Notes:" lines before the header row, which are skipped. A missing file reads as empty. A row
whose date won't parse is counted as skipped.

The profile stream has a record per position and per education entry, dated at its start (at
its end when there's no start, and skipped with neither). It also gets one snapshot of
Profile.csv per export, because LinkedIn doesn't say when the profile was edited. The snapshot
is dated by a YYYY-MM-DD (or MM-DD-YYYY) date in the export folder's name, else by when
Profile.csv was last modified.

Rows carry no ids, so ids hash the fields that identify them: a share's URN where its link has
one, otherwise its date and content. A position whose company, title or start date is edited on
LinkedIn becomes a new record next time, and the old one stays.
"""

import argparse
import csv
import hashlib
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from proxenos.store import merge_monthly

_FILES = ("Profile", "Positions", "Education", "Shares", "Comments", "messages", "Connections")

# Squashed column names, in the order they're tried.
_COLUMNS = {
    "first": ("firstname",),
    "last": ("lastname",),
    "headline": ("headline",),
    "summary": ("summary",),
    "industry": ("industry",),
    "geo": ("geolocation", "location"),
    "company": ("companyname", "company", "organization"),
    "title": ("title", "jobtitle", "position"),
    "description": ("description",),
    "location": ("location",),
    "started": ("startedon", "startdate", "start"),
    "finished": ("finishedon", "enddate", "end"),
    "school": ("schoolname", "school"),
    "degree": ("degreename", "degree"),
    "notes": ("notes",),
    "activities": ("activities",),
    "date": ("date", "createdat", "created"),
    "share_link": ("sharelink", "link", "url"),
    "commentary": ("sharecommentary", "commentary", "text"),
    "shared_url": ("sharedurl",),
    "visibility": ("visibility",),
    "link": ("link", "url"),
    "message": ("message", "comment", "text"),
    "conversation": ("conversationid",),
    "conversation_title": ("conversationtitle",),
    "from": ("from", "sender"),
    "to": ("to", "recipients"),
    "subject": ("subject",),
    "content": ("content", "body", "message"),
    "folder": ("folder",),
    "url": ("url", "profileurl"),
    "position": ("position", "title"),
    "connected": ("connectedon", "connected", "date"),
}
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
_DAY_FORMATS = ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d")
_MONTH_FORMATS = ("%b %Y", "%B %Y", "%Y-%m", "%m/%Y")
_ISO_DATE = re.compile(r"(19|20)\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
_US_DATE = re.compile(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])-((19|20)\d\d)")
_URN = re.compile(r"urn:li:\w+:\d+")

Row = dict[str, str]


def read_name(export: Path) -> str | None:
    """The full name on Profile.csv, or None without one."""
    profile = _profile(export)
    return _name(profile) if profile else None


def read_profile(export: Path) -> list[dict | None]:
    """Positions, education and a snapshot of the profile. None marks a skipped row."""
    profile = _profile(export)
    me = _name(profile) if profile else None
    records = [_parse(_position, row, me) for row in _rows(export, "Positions", "company")]
    records += [_parse(_education, row, me) for row in _rows(export, "Education", "school")]
    if profile:
        records.append(_snapshot(profile, me, _export_ts(export)))
    return records


def read_posts(export: Path) -> list[dict | None]:
    me = read_name(export)
    return [_parse(_share, row, me) for row in _rows(export, "Shares", "commentary")]


def read_comments(export: Path) -> list[dict | None]:
    me = read_name(export)
    return [_parse(_comment, row, me) for row in _rows(export, "Comments", "message")]


def read_messages(export: Path, me: Iterable[str] = ()) -> list[dict | None]:
    """Every message. from_me compares FROM with `me`, or with Profile.csv's name by default."""
    names = {_norm(name) for name in me if name.strip()}
    if not names and (name := read_name(export)):
        names = {_norm(name)}
    return [_parse(_message, row, names) for row in _rows(export, "messages", "conversation")]


def read_connections(export: Path) -> list[dict | None]:
    return [_parse(_connection, row) for row in _rows(export, "Connections", "connected")]


def ingest(vault: Path, export: Path, me: Iterable[str] = ()) -> dict[str, int]:
    if not export.is_dir() or not any(_find(export, name) for name in _FILES):
        raise FileNotFoundError(f"no LinkedIn export CSVs in {export}")
    streams = {
        "profile": read_profile(export),
        "posts": read_posts(export),
        "comments": read_comments(export),
        "messages": read_messages(export, me),
        "connections": read_connections(export),
    }
    return _merge(streams, vault / "raw" / "linkedin")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped export"
    )
    parser.add_argument(
        "--me",
        action="append",
        default=[],
        metavar="NAME",
        help="your name as messages show it (repeatable; default: from Profile.csv)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser(), args.me)


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


def _position(row: Row, me: str | None) -> dict:
    return _career("position", row, me, _get(row, "company"), _get(row, "title"))


def _education(row: Row, me: str | None) -> dict:
    return _career("education", row, me, _get(row, "school"), _get(row, "degree"))


def _career(kind: str, row: Row, me: str | None, where: str | None, title: str | None) -> dict:
    started, finished = _month(_get(row, "started")), _month(_get(row, "finished"))
    if not (started or finished):
        raise ValueError("no start or end date")
    return {
        "id": f"{kind}/{_hash(where, title, _get(row, 'started'))}",
        "ts": _utc((started or finished)[1]),
        "kind": kind,
        "from_me": True,
        "author": me,
        "organization": where,
        "title": title,
        "description": _get(row, "description") or _get(row, "notes"),
        "location": _get(row, "location"),
        "activities": _get(row, "activities"),
        "started": started[0] if started else None,
        "finished": finished[0] if finished else None,
    }


def _snapshot(row: Row, me: str | None, ts: str) -> dict:
    return {
        "id": f"profile/{ts[:10]}",
        "ts": ts,
        "kind": "profile",
        "from_me": True,
        "author": me,
        "headline": _get(row, "headline"),
        "summary": _get(row, "summary"),
        "industry": _get(row, "industry"),
        "location": _get(row, "geo"),
    }


def _share(row: Row, me: str | None) -> dict:
    link, text, date = _get(row, "share_link"), _get(row, "commentary"), _get(row, "date")
    urn = _URN.search(unquote(link or ""))
    return {
        "id": urn[0] if urn else f"share/{_hash(date, link, text)}",
        "ts": _utc(_when(date, _TIME_FORMATS)),
        "from_me": True,
        "author": me,
        "text": text,
        "url": link,
        "shared_url": _get(row, "shared_url"),
        "visibility": _get(row, "visibility"),
    }


def _comment(row: Row, me: str | None) -> dict:
    link, text, date = _get(row, "link"), _get(row, "message"), _get(row, "date")
    return {
        "id": f"comment/{_hash(date, link or text)}",
        "ts": _utc(_when(date, _TIME_FORMATS)),
        "from_me": True,
        "author": me,
        "text": text,
        "url": link,
    }


def _message(row: Row, me: set[str]) -> dict:
    conversation, sender, date = _get(row, "conversation"), _get(row, "from"), _get(row, "date")
    content = _get(row, "content")
    return {
        "id": f"{conversation}/{_hash(date, sender, content)}",
        "ts": _utc(_when(date, _TIME_FORMATS)),
        "conversation_id": conversation,
        "conversation_title": _get(row, "conversation_title"),
        "from_me": _norm(sender or "") in me,
        "author": sender,
        "to": _get(row, "to"),
        "subject": _get(row, "subject"),
        "text": content,
        "folder": _get(row, "folder"),
    }


def _connection(row: Row) -> dict:
    name, connected = _name(row), _get(row, "connected")
    # Not keyed on company or position: those are the connection's current ones and change.
    return {
        "id": _hash(_get(row, "url") or name, connected),
        "ts": _utc(_when(connected, _DAY_FORMATS)),
        "from_me": False,
        "name": name,
        "company": _get(row, "company"),
        "position": _get(row, "position"),
    }


def _parse(make: Callable[..., dict], row: Row | None, *context: Any) -> dict | None:
    if row is None:
        return None
    try:
        return make(row, *context)
    except (KeyError, TypeError, ValueError):
        return None


def _profile(export: Path) -> Row | None:
    return next((row for row in _rows(export, "Profile", "first") if row), None)


def _name(row: Row) -> str | None:
    return " ".join(filter(None, [_get(row, "first"), _get(row, "last")])) or None


def _find(export: Path, name: str) -> Path | None:
    """<name>.csv in the export folder, in any case."""
    filename = f"{name}.csv".lower()
    return next((p for p in export.iterdir() if p.name.lower() == filename and p.is_file()), None)


def _rows(export: Path, name: str, marker: str) -> list[Row | None]:
    """A CSV's rows keyed by squashed column name, or [] when the file is missing.

    The header is the first row with a `marker` column, which steps over a "Notes:" preamble.
    None stands for a line the csv module couldn't read.
    """
    path = _find(export, name)
    if path is None:
        return []
    lines: list[list[str] | None] = []
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f)
        while True:
            try:
                lines.append(next(reader))
            except StopIteration:
                break
            except csv.Error:
                lines.append(None)
    for i, line in enumerate(lines):
        header = [_squash(cell) for cell in line or []]
        if set(_COLUMNS[marker]) & set(header):
            rows = lines[i + 1 :]
            return [
                None if r is None else dict(zip(header, map(str.strip, r), strict=False))
                for r in rows
                if r is None or any(cell.strip() for cell in r)
            ]
    return []


def _get(row: Row, field: str) -> str | None:
    """The first non-empty value among the column names `field` goes by."""
    return next((row[name] for name in _COLUMNS[field] if row.get(name)), None)


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def _hash(*parts: str | None) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _when(text: str | None, formats: Iterable[str]) -> datetime:
    """The first format that fits, in UTC. A time without a zone is UTC already."""
    for fmt in formats:
        try:
            when = datetime.strptime(text or "", fmt)
        except ValueError:
            continue
        return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    raise ValueError(f"unrecognized date {text!r}")


def _month(text: str | None) -> tuple[str, datetime] | None:
    """'Jan 2020' as ('2020-01', its first day) and '2020' as ('2020', 1 Jan). None otherwise."""
    if text and re.fullmatch(r"(19|20)\d\d", text):
        return text, datetime(int(text), 1, 1, tzinfo=UTC)
    try:
        when = _when(text, _MONTH_FORMATS)
    except ValueError:
        return None
    return when.strftime("%Y-%m"), when


def _export_ts(export: Path) -> str:
    if match := _ISO_DATE.search(export.name):
        return f"{match[0]}T00:00:00Z"
    if match := _US_DATE.search(export.name):
        return f"{match[3]}-{match[1]}-{match[2]}T00:00:00Z"
    profile = _find(export, "Profile") or export
    return _utc(datetime.fromtimestamp(profile.stat().st_mtime, UTC))


def _utc(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
