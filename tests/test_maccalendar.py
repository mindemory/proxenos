"""The Mac Calendar app's database, as a synthetic SQLite file in its layout. No real data."""

import json
import sqlite3
from datetime import UTC, datetime

from proxenos.ingest import maccalendar

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def secs(iso):
    return (datetime.fromisoformat(iso) - EPOCH).total_seconds()


def database(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE Store (ROWID INTEGER PRIMARY KEY, name TEXT, type INTEGER);
        CREATE TABLE Calendar (ROWID INTEGER PRIMARY KEY, store_id INTEGER, title TEXT,
            owner_identity_email TEXT, self_identity_email TEXT);
        CREATE TABLE Location (ROWID INTEGER PRIMARY KEY, title TEXT);
        CREATE TABLE Identity (display_name TEXT, address TEXT);
        CREATE TABLE Participant (ROWID INTEGER PRIMARY KEY, owner_id INTEGER, identity_id INTEGER,
            email TEXT, status INTEGER);
        CREATE TABLE CalendarItem (ROWID INTEGER PRIMARY KEY, summary TEXT, location_id INTEGER,
            description TEXT, start_date REAL, start_tz TEXT, end_date REAL, all_day INTEGER,
            calendar_id INTEGER, orig_item_id INTEGER, orig_date REAL, organizer_id INTEGER,
            status INTEGER, unique_identifier TEXT, UUID TEXT, has_recurrences INTEGER,
            entity_type INTEGER);
    """)
    con.executemany("INSERT INTO Store VALUES (?,?,?)", [(1, "Exchange", 1), (2, "Holidays", 4)])
    con.executemany(
        "INSERT INTO Calendar VALUES (?,?,?,?,?)",
        [(1, 1, "Calendar", "mailto:Me@Example.edu", None), (2, 2, "US Holidays", None, None)],
    )
    con.execute("INSERT INTO Location VALUES (1, 'Room 101')")
    con.execute("INSERT INTO Identity VALUES ('Ana Lee', 'mailto:ana@example.edu')")
    con.executemany(
        "INSERT INTO Participant VALUES (?,?,?,?,?)",
        [(1, 1, 1, None, 1), (2, 1, None, "bo@example.edu", 2)],
    )
    items = [
        (
            1,
            "Lab meeting",
            1,
            "Agenda",
            secs("2026-10-29T18:00:00+00:00"),
            "America/New_York",
            secs("2026-10-29T19:00:00+00:00"),
            0,
            1,
            0,
            None,
            1,
            1,
            "uid-1",
            "u1",
            0,
            2,
        ),
        (
            2,
            "Weekly sync",
            None,
            None,
            secs("2026-10-30T14:00:00+00:00"),
            "America/New_York",
            secs("2026-10-30T15:00:00+00:00"),
            0,
            1,
            0,
            None,
            None,
            1,
            "uid-2",
            "u2",
            1,
            2,
        ),
        (
            3,
            "Weekly sync (moved)",
            None,
            None,
            secs("2026-11-06T16:00:00+00:00"),
            "America/New_York",
            secs("2026-11-06T17:00:00+00:00"),
            0,
            1,
            2,
            secs("2026-11-06T14:00:00+00:00"),
            None,
            1,
            "uid-2",
            "u3",
            1,
            2,
        ),
        (
            4,
            "Thanksgiving",
            None,
            None,
            secs("2026-11-26T00:00:00+00:00"),
            "_float",
            secs("2026-11-27T00:00:00+00:00"),
            1,
            2,
            0,
            None,
            None,
            1,
            "uid-4",
            "u4",
            0,
            2,
        ),
        (
            5,
            "Called off",
            None,
            None,
            secs("2026-10-31T14:00:00+00:00"),
            "UTC",
            secs("2026-10-31T15:00:00+00:00"),
            0,
            1,
            0,
            None,
            None,
            3,
            "uid-5",
            "u5",
            0,
            2,
        ),
    ]
    con.executemany(f"INSERT INTO CalendarItem VALUES ({','.join('?' * 17)})", items)
    con.commit()
    con.close()


def test_events_land_in_the_calendars_stream_like_an_exports(tmp_path):
    db = tmp_path / "Calendar.sqlitedb"
    database(db)

    assert maccalendar.available(db)
    stats = maccalendar.ingest(tmp_path / "vault", db, NOW)

    folder = tmp_path / "vault" / "raw" / "calendar" / "me-example-edu"
    rows = {
        r["id"]: r
        for f in folder.glob("*.jsonl")
        for r in map(json.loads, f.read_text().splitlines())
    }
    assert set(rows) == {"uid-1", "uid-2/2026-11-06T14:00:00Z"}  # no series, holiday or cancelled
    meeting = rows["uid-1"]
    assert (meeting["summary"], meeting["location"], meeting["start"]) == (
        "Lab meeting",
        "Room 101",
        "2026-10-29T18:00:00Z",
    )
    assert meeting["organizer"] == "ana@example.edu" and meeting["attendees"] == 2
    assert {g["email"]: g["status"] for g in meeting["guests"]} == {
        "ana@example.edu": "accepted",
        "bo@example.edu": "declined",
    }
    assert stats["added"] == 2


def test_without_the_database_or_access_nothing_is_read(tmp_path):
    assert not maccalendar.available(tmp_path / "missing.sqlitedb")
