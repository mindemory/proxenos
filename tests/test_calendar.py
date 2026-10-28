"""Calendar ingester against synthetic .ics files. No real data lives in this repo."""

import json

from proxenos.ingest import calendar

LONG = "x" * 600
ICS = (
    "BEGIN:VCALENDAR\r\n"
    "PRODID:-//Example//EN\r\n"
    "BEGIN:VTIMEZONE\r\n"
    "TZID:America/New_York\r\n"
    "BEGIN:STANDARD\r\n"
    "DTSTART:19701101T020000\r\n"
    "END:STANDARD\r\n"
    "END:VTIMEZONE\r\n"
    # A weekly meeting in New York time, folded mid-word and mid-character.
    "BEGIN:VEVENT\r\n"
    "DTSTART;TZID=America/New_York:20240305T090000\r\n"
    "DTEND;TZID=America/New_York:20240305T100000\r\n"
    "RRULE:FREQ=WEEKLY;BYDAY=TU\r\n"
    "UID:weekly@example.com\r\n"
    "ORGANIZER;CN=Sam Sample:mailto:Sam@Example.com\r\n"
    'ATTENDEE;CN="Sample, Sam";PARTSTAT=ACCEPTED:mailto:sam@example.com\r\n'
    "ATTENDEE;CN=Kai:mailto:kai@example.com\r\n"
    "ATTENDEE;CN=noa@example.com;PARTSTAT=DECLINED:mailto:Noa@Example.com\r\n"
    "ATTENDEE;CUTYPE=RESOURCE;CN=Room 1:mailto:room1@resource.example.com\r\n"
    "ATTENDEE;CUTYPE=GROUP;CN=All lab:mailto:lab-list@example.com\r\n"
    "SUMMARY:Lab meet\r\n ing \xe2\x98\r\n \x95\r\n"
    "LOCATION:Room 1\\, Building 2\r\n"
    "DESCRIPTION:Agenda:\\nfirst item\\; second\r\n"
    "STATUS:CONFIRMED\r\n"
    "BEGIN:VALARM\r\n"
    "ACTION:DISPLAY\r\n"
    "DESCRIPTION:This is an alarm\r\n"
    "TRIGGER:-PT10M\r\n"
    "END:VALARM\r\n"
    "END:VEVENT\r\n"
    # One changed instance of it, in UTC.
    "BEGIN:VEVENT\r\n"
    "DTSTART:20240312T150000Z\r\n"
    "DTEND:20240312T160000Z\r\n"
    "RECURRENCE-ID;TZID=America/New_York:20240312T090000\r\n"
    "UID:weekly@example.com\r\n"
    "SUMMARY:Lab meeting (moved)\r\n"
    f"DESCRIPTION:{LONG}\r\n"
    "END:VEVENT\r\n"
    # All day, no UID.
    "BEGIN:VEVENT\r\n"
    "DTSTART;VALUE=DATE:20240401\r\n"
    "DTEND;VALUE=DATE:20240402\r\n"
    "SUMMARY:Holiday\r\n"
    "END:VEVENT\r\n"
    # A floating time and an unknown zone are taken as UTC.
    "BEGIN:VEVENT\r\n"
    "UID:floating\r\n"
    "DTSTART:20240501T120000\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:unknown-zone\r\n"
    "DTSTART;TZID=Nowhere/Special:20240502T120000\r\n"
    "END:VEVENT\r\n"
    # Malformed: no DTSTART, and a start that won't parse.
    "BEGIN:VEVENT\r\n"
    "UID:no-start\r\n"
    "SUMMARY:Broken\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:bad-start\r\n"
    "DTSTART:tomorrow\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
).encode("latin-1")


def write(path, data=ICS):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def by_id(records):
    return {r["id"]: r for r in records if r}


def test_events_are_unfolded_and_parsed_with_their_zones(tmp_path):
    records = calendar.read_events(write(tmp_path / "me@example.com.ics"))
    assert records.count(None) == 2
    events = by_id(records)

    weekly = events["weekly@example.com"]
    assert weekly["summary"] == "Lab meeting ☕"
    assert (weekly["ts"], weekly["start"], weekly["end"]) == (
        "2024-03-05T14:00:00Z",
        "2024-03-05T14:00:00Z",
        "2024-03-05T15:00:00Z",
    )
    assert (weekly["timezone"], weekly["all_day"]) == ("America/New_York", False)
    assert weekly["rrule"] == "FREQ=WEEKLY;BYDAY=TU"
    assert weekly["location"] == "Room 1, Building 2"
    assert weekly["description"] == "Agenda:\nfirst item; second"  # not the alarm's
    assert (weekly["organizer"], weekly["attendees"], weekly["status"]) == (
        "sam@example.com",
        5,
        "CONFIRMED",
    )
    # The people among them: a name only when CN is one, never a room or a list.
    assert weekly["guests"] == [
        {"name": "Sample, Sam", "email": "sam@example.com", "status": "accepted"},
        {"name": "Kai", "email": "kai@example.com", "status": None},
        {"name": None, "email": "noa@example.com", "status": "declined"},
    ]

    moved = events["weekly@example.com/2024-03-12T13:00:00Z"]
    assert (moved["ts"], moved["rrule"], moved["attendees"]) == ("2024-03-12T15:00:00Z", None, 0)
    assert moved["guests"] == []
    assert moved["description"] == "x" * 500

    (holiday,) = [e for e in events.values() if e["summary"] == "Holiday"]
    assert (holiday["ts"], holiday["start"], holiday["end"], holiday["all_day"]) == (
        "2024-04-01T00:00:00Z",
        "2024-04-01",
        "2024-04-02",
        True,
    )
    assert len(holiday["id"]) == 16

    assert events["floating"]["ts"] == "2024-05-01T12:00:00Z"
    assert events["unknown-zone"]["ts"] == "2024-05-02T12:00:00Z"


def test_each_calendar_file_is_its_own_stream_and_reruns_are_no_ops(tmp_path):
    export = tmp_path / "export"
    write(export / "Me@Example.com.ics")
    write(export / "Takeout" / "Calendar" / "Birthdays_me@example.com.ics", ICS)
    write(export / "__MACOSX" / "._Me@Example.com.ics", b"junk")
    vault = tmp_path / "vault"

    stats = calendar.ingest(vault, export)
    assert stats["skipped"] == 4
    out = vault / "raw" / "calendar"
    assert sorted(p.name for p in out.iterdir()) == ["birthdays_me-example-com", "me-example-com"]
    march = (out / "me-example-com" / "2024-03.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in march] == [
        "weekly@example.com",
        "weekly@example.com/2024-03-12T13:00:00Z",
    ]

    again = calendar.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)
