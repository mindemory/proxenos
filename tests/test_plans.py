"""The plans calendar from a synthetic task list. No network, no model, no real data."""

import json
import subprocess
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


class Calendar:
    """Stands in for osascript and the Calendar app: keeps the events made, by uid."""

    def __init__(self):
        self.events, self.calls, self.n = {}, [], 0

    def __call__(self, command, *, input, **kw):
        action, calendar, old, *fields = command[2:]
        self.calls.append((action, calendar, old))
        self.events.pop(old, None)
        uid = ""
        if action == "make":
            self.n += 1
            uid = f"UID-{self.n}"
            self.events[uid] = fields
        return subprocess.CompletedProcess(command, 0, stdout=uid + "\n", stderr="")


def test_plans_go_on_my_own_calendar_and_only_its_own_events_change(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("PROXENOS_PLANS_CALENDAR", "me@gmail.com")
    monkeypatch.setattr(plans.sys, "platform", "darwin")
    cal = Calendar()
    lunch = task("lunch1", "Lunch with Kim", "2026-03-11T12:00", place="Worthy", with_="Kim")
    hike = task("hike1", "Hike", "2026-03-14")

    assert plans.write(vault, [lunch, hike], NOW, run=cal) == 2
    assert sorted(cal.events) == ["UID-1", "UID-2"]
    title, place, notes, whole, start, end = cal.events["UID-1"]
    assert (title, place, whole, start, end) == (
        "Lunch with Kim",
        "Worthy",
        "0",
        "2026 03 11 12 00",
        "2026 03 11 13 00",
    )
    assert notes.endswith("From WhatsApp, with Kim. Added by Proxenos.")
    assert cal.events["UID-2"][3:] == ["1", "2026 03 14 00 00", "2026 03 15 00 00"]

    # The calendar is read back in with the sync: its own events don't count as mine.
    write_events(
        vault,
        "me-gmail-com",
        "2026-03",
        [{"id": "UID-1", "start": local("2026-03-11T12:00:00"), "summary": "Lunch with Kim"}],
    )
    plans.write(vault, [lunch, hike], NOW, run=cal)
    assert len(cal.calls) == 2  # nothing changed, so nothing touched

    moved = lunch | {"at": "2026-03-11T13:00"}
    plans.write(vault, [moved], NOW, run=cal)  # the lunch moved, the hike is off
    assert sorted(cal.events) == ["UID-3"] and cal.events["UID-3"][4] == "2026 03 11 13 00"
    assert ("make", "me@gmail.com", "UID-1") in cal.calls  # the old one deleted first
    assert ("delete", "me@gmail.com", "UID-2") in cal.calls
    pushed = json.loads((vault / "clones" / "tasks" / "pushed.json").read_text())
    assert list(pushed) == ["lunch1"] and pushed["lunch1"]["uid"] == "UID-3"


def test_without_a_calendar_named_nothing_is_touched(tmp_path, monkeypatch):
    monkeypatch.delenv("PROXENOS_PLANS_CALENDAR", raising=False)
    plans.write(tmp_path, [task("x", "Lunch", "2026-03-11T12:00")], NOW, run=untouched)


def untouched(*a, **kw):
    raise AssertionError("the Calendar app was called")
