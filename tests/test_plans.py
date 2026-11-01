"""The plans calendar from a synthetic task list. No network, no model, no real data."""

import json
from datetime import UTC, date, datetime

from proxenos import plans

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def task(key, title, at, *, status="open", place=None, **fields):
    return {
        "id": key,
        "title": title,
        "detail": fields.get("detail", ""),
        "source": fields.get("source", "whatsapp"),
        "with": fields.get("with_"),
        "status": status,
        "at": at,
        "place": place,
    }


def write_events(vault, stream, month, events):
    path = vault / "raw" / "calendar" / stream / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def local(text):
    """A local time as the calendar reader stores it: UTC."""
    when = datetime.fromisoformat(text).astimezone(UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def events(text):
    return text.split("BEGIN:VEVENT")[1:]


def test_plans_with_a_time_become_events_and_the_rest_stay_off(tmp_path):
    vault = tmp_path / "vault"
    write_events(
        vault,
        "me-example-org",
        "2026-03",
        [
            {"id": "e1", "start": local("2026-03-12T15:30:00"), "summary": "Neurology visit"},
            {"id": "e2", "start": "2026-03-13", "all_day": True, "summary": "Asha's party"},
        ],
    )
    write_events(vault, "birthdays_me", "2026-03", [{"start": "2026-03-14", "summary": "Ben"}])
    tasks = [
        task("lunch1", "Lunch with Kim, then book Worthy", "2026-03-11T12:00", place="Worthy, VT"),
        task("trip1", "Hike day; bring snacks", "2026-03-14", detail="Line one\nline two"),
        task("neuro", "Attend the neurology video visit", "2026-03-12T16:00"),  # theirs already
        task("party", "Go to Asha's party", "2026-03-13", with_="Asha"),  # theirs already
        task("done1", "Coffee with Ben", "2026-03-11T09:00", status="done"),
        task("old1", "Last month's call", "2026-02-01T10:00"),
        task("none", "Send the slides", None),
        task("bad1", "A time the model made up", "tomorrow at noon"),
    ]

    assert plans.write(vault, tasks, NOW) == 2

    text = (vault / "clones" / "tasks" / "plans.ics").read_bytes().decode()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:Proxenos" in text
    lunch, trip = events(text)
    assert "UID:lunch1@proxenos" in lunch
    assert "DTSTART:20260311T120000\r\n" in lunch  # floating: local wherever it's read
    assert "DTEND:20260311T130000\r\n" in lunch
    assert "SUMMARY:Lunch with Kim\\, then book Worthy" in lunch
    assert "LOCATION:Worthy\\, VT" in lunch
    assert "DESCRIPTION:From WhatsApp." in lunch
    assert "DTSTART;VALUE=DATE:20260314" in trip and "DTEND;VALUE=DATE:20260315" in trip
    assert "SUMMARY:Hike day\\; bring snacks" in trip
    assert "DESCRIPTION:Line one\\nline two\\n\\nFrom WhatsApp." in trip


def test_long_lines_fold_without_splitting_a_character():
    title = "Dîner " + "très long " * 20
    text = plans.ics([(task("x", title, None), date(2026, 3, 11))], NOW)
    for line in text.split("\r\n"):
        assert len(line.encode()) <= 75
    unfolded = text.replace("\r\n ", "")
    assert f"SUMMARY:{title}\r\n" in unfolded


def test_at_reads_a_time_or_a_day_and_nothing_else():
    assert plans.at("2026-03-11T12:00") == datetime(2026, 3, 11, 12, 0)
    assert plans.at("2026-03-11") == date(2026, 3, 11)
    assert plans.at("2026-02-30") is None
    assert plans.at("noon") is None and plans.at(None) is None
