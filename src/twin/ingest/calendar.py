"""Calendar events from iCalendar (.ics) files, such as Google Calendar's export.

Reads every .ics file under --export and writes one stream per file into vault/raw/calendar/,
named after the file: mdd@example.edu.ics goes to calendar/mdd-example-edu. Google's export
(Settings, Import & export) is a zip with one .ics per calendar, and Takeout has the same files
under Takeout/Calendar/. Every file is a full snapshot, so each run re-reads one and merges by id.

Only VEVENTs are read, with the standard library, and properties of a VALARM inside one are
ignored. Folded lines (a line break and then a space or tab) are joined first, on the raw bytes,
since a fold can split a UTF-8 character.
- SUMMARY, LOCATION, STATUS and RRULE are kept as text. A repeating event is one record with its
  RRULE, not expanded, plus a record for each changed instance (RECURRENCE-ID).
- DESCRIPTION is cut to its first 500 characters.
- organizer is ORGANIZER's email, and attendees counts the ATTENDEE lines.
- guests lists the people among them, each with name (CN, when it's a name and not an address),
  email and status (PARTSTAT, lower case: accepted, declined, tentative, needs-action). Rooms,
  resources and mailing groups (CUTYPE other than INDIVIDUAL) aren't people and are left out.
  Names and addresses stay in the vault: nothing but the network clone reads them.
- DTSTART and DTEND are UTC ("...Z"), local with a TZID (an IANA zone name), or dates
  (VALUE=DATE) for all-day events. A local time without a TZID, or with one zoneinfo doesn't
  know, is taken as UTC. ts is the start in UTC (midnight for an all-day event). start and end
  are UTC times too, except for all-day events, which keep their dates.

The id is the event's UID, plus its RECURRENCE-ID for a changed instance, or a hash of the start
and summary for an event without a UID. An event without a DTSTART, or one that won't parse, is
counted as skipped.
"""

import argparse
import hashlib
import re
from datetime import UTC, datetime, tzinfo
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from twin.store import merge_monthly

DESCRIPTION_CHARS = 500

_FOLD = re.compile(rb"\r?\n[ \t]")
_PARAM = re.compile(r';([^=;:]+)=("[^"]*"|[^;:]*)')
_ESCAPE = re.compile(r"\\([\\;,nN])")


def read_events(path: Path) -> list[dict | None]:
    """Every event in an .ics file. None marks one that couldn't be parsed."""
    lines = _FOLD.sub(b"", path.read_bytes()).decode("utf-8", errors="replace").splitlines()
    events: list[dict | None] = []
    nesting: list[str] = []
    event: list[str] | None = None
    for line in lines:
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            nesting.append(upper[6:].strip())
            if nesting[-1] == "VEVENT":
                event = []
        elif upper.startswith("END:"):
            if nesting and nesting.pop() == "VEVENT" and event is not None:
                events.append(_parse(event))
                event = None
        elif event is not None and nesting and nesting[-1] == "VEVENT":
            event.append(line)
    return events


def stream_name(path: Path) -> str:
    """The stream for a calendar file: its name without .ics, made path-safe."""
    return re.sub(r"[^\w-]", "-", path.stem.lower()) or "calendar"


def ingest(vault: Path, export: Path) -> dict[str, int]:
    files = _files(export)
    if not files:
        raise FileNotFoundError(f"no .ics files in {export}")
    streams: dict[str, list[dict | None]] = {}
    for path in files:
        streams.setdefault(stream_name(path), []).extend(read_events(path))
    return _merge(streams, vault / "raw" / "calendar")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="a folder with .ics files"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: an event in two copies of a calendar is one record, and the last wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _parse(lines: list[str]) -> dict | None:
    try:
        return _event(lines)
    except (KeyError, ValueError):
        return None


def _event(lines: list[str]) -> dict:
    props: dict[str, tuple[dict[str, str], str]] = {}
    attendees = 0
    guests: dict[str, dict] = {}
    for line in lines:
        prop = _split(line)
        if prop is None:
            continue
        name, params, value = prop
        if name == "ATTENDEE":
            attendees += 1
            if (guest := _guest(params, value)) is not None:
                guests.setdefault(guest["email"], guest)
        props.setdefault(name, (params, value))

    start, all_day = _time(*props["DTSTART"])
    end, _ = _time(*props["DTEND"]) if "DTEND" in props else (None, False)
    summary = _text(props, "SUMMARY")
    key = _text(props, "UID") or _hash(props["DTSTART"][1], summary)
    if "RECURRENCE-ID" in props:
        key += "/" + _stamp(_time(*props["RECURRENCE-ID"])[0])
    organizer = _text(props, "ORGANIZER")
    description = _text(props, "DESCRIPTION")
    return {
        "id": key,
        "ts": _stamp(start),
        "start": _day(start) if all_day else _stamp(start),
        "end": None if end is None else _day(end) if all_day else _stamp(end),
        "all_day": all_day,
        "timezone": props["DTSTART"][0].get("TZID") or None,
        "summary": summary,
        "location": _text(props, "LOCATION"),
        "description": description[:DESCRIPTION_CHARS] if description else None,
        "rrule": _text(props, "RRULE"),
        "status": _text(props, "STATUS"),
        "organizer": _email(organizer) if organizer else None,
        "attendees": attendees,
        "guests": list(guests.values()),
    }


def _guest(params: dict[str, str], value: str) -> dict | None:
    """One ATTENDEE who is a person, or None for a room, a resource, a group or no address."""
    if params.get("CUTYPE", "INDIVIDUAL").upper() != "INDIVIDUAL":
        return None
    email = _email(value)
    if "@" not in email:
        return None
    name = " ".join(params.get("CN", "").split())
    status = params.get("PARTSTAT", "").strip().lower()
    return {
        "name": name if name and "@" not in name else None,
        "email": email,
        "status": status or None,
    }


def _split(line: str) -> tuple[str, dict[str, str], str] | None:
    """'DTSTART;TZID=America/New_York:20240305T090000' as its name, parameters and value.

    The value starts at the first colon outside a quoted parameter. None for a line without one.
    """
    quoted = False
    for i, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            head, value = line[:i], line[i + 1 :]
            break
    else:
        return None
    name = head.split(";", 1)[0].strip().upper()
    params = {key.strip().upper(): value.strip('"') for key, value in _PARAM.findall(head)}
    return name, params, value


def _time(params: dict[str, str], value: str) -> tuple[datetime, bool]:
    """A DTSTART-like value in UTC, and whether it's a date (an all-day event)."""
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC), True
    utc = value.upper().endswith("Z")
    local = datetime.strptime(value[:-1] if utc else value, "%Y%m%dT%H%M%S")
    zone = UTC if utc else _zone(params.get("TZID", ""))
    return local.replace(tzinfo=zone).astimezone(UTC), False


@cache
def _zone(tzid: str) -> tzinfo:
    """The zone a TZID names, or UTC. Some writers put a path before the zone's name
    ("/mozilla.org/20050126_1/America/New_York"), so its tails are tried too."""
    parts = tzid.strip().strip("/").split("/")
    for i in range(len(parts)):
        try:
            return ZoneInfo("/".join(parts[i:]))
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return UTC


def _email(organizer: str) -> str:
    return re.sub(r"^mailto:", "", organizer, flags=re.IGNORECASE).strip().lower()


def _text(props: dict[str, tuple[dict[str, str], str]], name: str) -> str | None:
    if name not in props:
        return None
    value = _ESCAPE.sub(lambda m: "\n" if m[1] in "nN" else m[1], props[name][1]).strip()
    return value or None


def _files(export: Path) -> list[Path]:
    return sorted(
        p
        for p in export.rglob("*.ics")
        if p.is_file()
        and not any(
            part.startswith(".") or part == "__MACOSX" for part in p.relative_to(export).parts
        )
    )


def _hash(*parts: str | None) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _day(when: datetime) -> str:
    return when.date().isoformat()


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
