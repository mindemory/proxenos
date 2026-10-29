"""Calendar events from the Mac's Calendar app, live, for any account added to it.

Google, Exchange (Outlook, Microsoft 365) and iCloud calendars added in System Settings, Internet
Accounts, sync into one database on the Mac, ~/Library/Group Containers/group.com.apple.calendar/
Calendar.sqlitedb, which macOS keeps private until the Python that runs Proxenos has Full Disk
Access (the same as for Mail). This reads it every sync, and writes vault/raw/calendar/<stream>/
in the calendar reader's shape (calendar.py), so a live event updates its copy from a Google
export, matched by its UID.

<stream> is the address the calendar belongs to (alice@example.edu → alice-example-edu, as for
an export's alice@example.edu.ics), else its title. Holidays, birthdays, subscribed calendars,
reminders and the events Calendar guesses from mail are left out. Cancelled events too.

A one-off event is one record, its id the event's UID. An edited instance of a repeating event
is one record, its id the UID and the original start. A repeating series itself isn't read: the
database keeps its rule in a form that doesn't map cleanly to an RRULE, and Calendar only expands
it for the days it shows, so the series comes from an export, which has the RRULE. Dates are
seconds since 2001-01-01 UTC; an all-day event keeps its date. It only reads.
"""

import argparse
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos.store import merge_monthly

DEFAULT_DB = Path("~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb")
PAST_DAYS, FUTURE_DAYS = 400, 365
DESCRIPTION_CHARS = 500
_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
_KEPT_STORES = {1, 2}  # Exchange, and CalDAV (Google, iCloud); not local, subscribed or reminders
_SKIPPED_TITLE = re.compile(r"holiday|birthday|found in", re.IGNORECASE)
_CANCELLED = 3
_STATUS = {1: "accepted", 2: "declined", 3: "tentative"}


def available(db: Path = DEFAULT_DB) -> bool:
    """Whether the database is there and macOS lets it be read."""
    try:
        with closing(_connect(db.expanduser())) as con:
            con.execute("SELECT 1 FROM CalendarItem LIMIT 1")
    except (sqlite3.Error, OSError):
        return False
    return True


def read(db: Path, now: datetime | None = None) -> dict[str, list[dict]]:
    """The events, by stream, from PAST_DAYS ago to FUTURE_DAYS ahead."""
    now = now or datetime.now(UTC)
    low = (now - timedelta(days=PAST_DAYS) - _EPOCH).total_seconds()
    high = (now + timedelta(days=FUTURE_DAYS) - _EPOCH).total_seconds()
    with closing(_connect(db)) as con:
        con.row_factory = sqlite3.Row
        calendars = {
            r["ROWID"]: _stream(r)
            for r in con.execute(
                "SELECT c.ROWID, c.title, c.owner_identity_email, c.self_identity_email, "
                "s.type AS store_type FROM Calendar c JOIN Store s ON s.ROWID = c.store_id"
            )
            if r["store_type"] in _KEPT_STORES and not _SKIPPED_TITLE.search(r["title"] or "")
        }
        people = _participants(con)
        streams: dict[str, list[dict]] = {}
        for item in con.execute(
            "SELECT i.*, l.title AS place FROM CalendarItem i "
            "LEFT JOIN Location l ON l.ROWID = i.location_id "
            "WHERE i.entity_type = 2 AND i.start_date BETWEEN ? AND ?",
            (low, high),
        ):
            stream = calendars.get(item["calendar_id"])
            if stream is None or item["status"] == _CANCELLED:
                continue
            if item["has_recurrences"] and not item["orig_item_id"]:
                continue  # a series: from an export, with its RRULE
            if record := _event(item, people.get(item["ROWID"], [])):
                streams.setdefault(stream, []).append(record)
    return streams


def _event(item: sqlite3.Row, guests: list[dict]) -> dict | None:
    uid = item["unique_identifier"] or item["UUID"]
    if not uid or item["start_date"] is None:
        return None
    all_day = bool(item["all_day"])
    start, end = _when(item["start_date"]), _when(item["end_date"])
    if item["orig_item_id"]:  # an edited instance of a series
        uid = f"{uid}/{_stamp(_when(item['orig_date']) or start)}"
    organizer = next((g["email"] for g in guests if g.pop("organizer", False)), None)
    for g in guests:
        g.pop("organizer", None)
    description = (item["description"] or "").strip()
    return {
        "id": uid,
        "ts": _stamp(start),
        "start": start.date().isoformat() if all_day else _stamp(start),
        "end": None if end is None else end.date().isoformat() if all_day else _stamp(end),
        "all_day": all_day,
        "timezone": None
        if all_day or (item["start_tz"] or "").startswith("_")
        else item["start_tz"],
        "summary": item["summary"] or None,
        "location": item["place"] or None,
        "description": description[:DESCRIPTION_CHARS] or None,
        "rrule": None,
        "status": None,
        "organizer": organizer,
        "attendees": len(guests),
        "guests": guests,
    }


def _participants(con: sqlite3.Connection) -> dict[int, list[dict]]:
    """Each event's guests ({name, email, status}), with its organizer marked."""
    found: dict[int, list[dict]] = {}
    for p in con.execute(
        "SELECT p.owner_id, p.email, p.status, p.ROWID, i.display_name, i.address, "
        "(SELECT COUNT(*) FROM CalendarItem c WHERE c.organizer_id = p.ROWID) AS organizes "
        "FROM Participant p LEFT JOIN Identity i ON i.rowid = p.identity_id"
    ):
        email = (
            p["email"] or re.sub(r"^mailto:", "", p["address"] or "", flags=re.IGNORECASE)
        ).lower()
        if not email or "@" not in email:
            continue
        name = p["display_name"] if p["display_name"] and "@" not in p["display_name"] else None
        found.setdefault(p["owner_id"], []).append(
            {
                "name": name,
                "email": email,
                "status": _STATUS.get(p["status"]),
                "organizer": bool(p["organizes"]),
            }
        )
    return found


def _stream(calendar: sqlite3.Row) -> str:
    """The calendar's address made path-safe, as an export's .ics file name is, else its title."""
    name = calendar["owner_identity_email"] or calendar["self_identity_email"] or calendar["title"]
    name = re.sub(r"^mailto:", "", name or "calendar", flags=re.IGNORECASE)
    return re.sub(r"[^\w-]", "-", name.lower()) or "calendar"


def _when(seconds: float | None) -> datetime | None:
    return None if seconds is None else _EPOCH + timedelta(seconds=seconds)


def _stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect(db: Path) -> sqlite3.Connection:
    if not db.exists():
        raise FileNotFoundError(db)
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def ingest(vault: Path, db: Path = DEFAULT_DB, now: datetime | None = None) -> dict[str, int]:
    db = db.expanduser()
    try:
        streams = read(db, now)
    except FileNotFoundError:
        raise SystemExit(
            "maccalendar: no Calendar database; add a calendar account first"
        ) from None
    except sqlite3.Error as e:
        raise SystemExit(
            f"maccalendar: can't read Calendar's database ({e}). Give the Python that runs "
            "Proxenos Full Disk Access, as for Mail."
        ) from None
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    for stream, records in streams.items():
        for key, value in merge_monthly(records, vault / "raw" / "calendar" / stream).items():
            stats[key] += value
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Calendar's database")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.db)
