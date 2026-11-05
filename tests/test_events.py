"""Booked events found in synthetic mail, with no model. No network, no real data."""

import json
import subprocess
from datetime import UTC, date, datetime

from proxenos import events, plans

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

HOP = """Thank you for your order from the Hop

Order Date: Tuesday, November 3, 2026 2:07PM
Stories from the Siberian Arctic
Thursday, November 5, 2026 7:00 PM
2 tickets
"""
LD = (
    '<script type="application/ld+json">{"@context":"http://schema.org",'
    '"@type":"EventReservation","reservationFor":{"@type":"Event","name":"Harbor Choir",'
    '"startDate":"2026-11-20T19:30:00"}}</script>'
)
ICS = (
    "See you on the 18th\nBEGIN:VEVENT\nDTSTART:20261118T180000\nSUMMARY:Pottery class\nEND:VEVENT"
)


def mail(key, subject, body, ts="2026-11-03T14:07:00Z", name="Hop"):
    return {
        "id": key,
        "ts": ts,
        "account": "me",
        "from_address": "no-reply@hop.example",
        "from_name": name,
        "subject": subject,
        "body": body,
        "body_new": body,
        "attachments": None,
    }


def vault_with(tmp_path, records, calendar=()):
    vault = tmp_path / "vault"
    path = vault / "raw" / "email" / "me" / "2026-11.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    if calendar:
        cal = vault / "raw" / "calendar" / "me" / "2026-11.jsonl"
        cal.parent.mkdir(parents=True)
        cal.write_text("".join(json.dumps(r) + "\n" for r in calendar))
    return vault


def records():
    return [
        mail("hop", "Thank you for your order from the Hop", HOP),
        mail("ld", "Your reservation", LD + "\nSee you there", name="Choir"),
        mail("ics", "Your info for pottery", ICS, name="Clay"),
        mail("old", "Booking confirmation", "Show\nThursday, October 8, 2026 7:00 PM"),
        mail("news", "This week", "Concert\nFriday, November 6, 2026 8:00 PM", name="Letter"),
    ]


def test_finds_the_booked_events_and_ignores_the_rest(tmp_path):
    vault = vault_with(tmp_path, records())
    found = events.find(vault, NOW)
    assert [(p["at"], p["title"]) for p in found] == [
        ("2026-11-05T19:00", "Stories from the Siberian Arctic (Hop)"),
        ("2026-11-18T18:00", "Pottery class (Clay)"),
        ("2026-11-20T19:30", "Harbor Choir (Choir)"),
    ]
    assert all(p["event"] is True and p["source"] == "email" for p in found)
    assert found == events.find(vault, NOW)  # stable ids


def test_a_date_without_a_year_takes_the_weekday_and_a_label_is_not_the_event():
    sent = date(2026, 11, 3)
    assert events._parse("Thu, Nov 5 at 7pm", sent) == datetime(2026, 11, 5, 19, 0)
    assert events._parse("11/05/2026 19:00", sent) == datetime(2026, 11, 5, 19, 0)
    assert events._parse("November 5 · 7:00 PM", sent) == datetime(2026, 11, 5, 19, 0)
    assert events._parse("Friday, November 5 at 7pm", sent) == datetime(2027, 11, 5, 19, 0)
    assert events._parse("November 5, 2026", sent) is None  # no time
    assert events._date_lines("Order Date: Nov 3, 2026 2:07PM", sent, "x") == []


def test_plans_write_leaves_off_what_the_users_own_calendar_has(tmp_path):
    own = {"id": "c1", "start": "2026-11-05T19:00:00", "summary": "Siberian Arctic talk"}
    vault = vault_with(tmp_path, records(), calendar=[own])
    assert plans.write(vault, [], NOW) == 2  # the Hop one is theirs already
    text = (vault / "clones" / "tasks" / "plans.ics").read_text()
    assert "Pottery class (Clay)" in text and "Harbor Choir (Choir)" in text
    assert "Hop)" not in text


def test_plans_write_pushes_them_when_a_calendar_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_PLANS_CALENDAR", "me@example.com")
    monkeypatch.setattr(plans.sys, "platform", "darwin")
    vault = vault_with(tmp_path, records())
    made = []

    def cal(cmd, **kw):
        made.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=f"uid{len(made)}\n", stderr="")

    assert plans.write(vault, [], NOW, run=cal) == 3
    assert len(made) == 3
    plans.write(vault, [], NOW, run=cal)  # nothing changed, nothing made again
    assert len(made) == 3


def test_refresh_writes_the_plans_with_no_task_list(tmp_path):
    vault = vault_with(tmp_path, records())
    assert plans.refresh(vault, NOW) == 3
