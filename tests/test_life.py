"""The life clone on a synthetic vault: a day's digest from a made-up index, the stories of its
months with the model faked out, and the night's choice of months. No network, no real data."""

import argparse
import json
import os
import stat
import time
from datetime import UTC, date, datetime

import pytest

from proxenos import cli, llm, memory
from proxenos.clones import life

DAY = date(2026, 3, 10)
NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
THEIRS = "PRIVATE-THEIRS keep this between us"  # someone else's words: never in a digest or prompt
THEIR_MAIL = "THEIR-MAIL the results are attached"


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def wa(n, ts, chat, text, me, sender=None):
    return {
        "id": f"m{n}", "ts": ts, "chat_id": f"{chat}@s.whatsapp.net", "chat_name": chat,
        "chat_type": "direct", "from_me": me, "sender_id": None if me else "1",
        "sender_name": None if me else sender or chat, "kind": "text", "wa_type": 0,
        "text": text, "caption": None,
    }  # fmt: skip


def mail(n, ts, me, subject, body, to):
    return {
        "id": f"e{n}", "ts": ts, "from_address": "me@example.com" if me else "lab@example.org",
        "from_name": "Sam Doe" if me else "Lab Desk", "from_me": me, "to": to, "cc": None,
        "subject": subject, "in_reply_to": None, "body_new": body,
    }  # fmt: skip


@pytest.fixture
def new_york(monkeypatch):
    """This process, and SQLite in it, on New York time: on 2026-03-10 that's UTC-4."""
    if not hasattr(time, "tzset"):
        pytest.skip("the time zone is set through tzset, which Windows doesn't have")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def vault(tmp_path, monkeypatch, new_york):
    """A month of made-up records around 2026-03-10, indexed."""
    monkeypatch.setenv("PROXENOS_NAME", "Sam Doe")
    monkeypatch.setenv("PROXENOS_EMAILS", "me@example.com")
    v = tmp_path / "vault"
    raw = v / "raw"
    jsonl(
        raw / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa(1, "2026-03-10T13:00:00Z", "Asha", THEIRS, False),
            wa(2, "2026-03-10T13:05:00Z", "Asha", "ok", True),
            wa(3, "2026-03-10T13:06:00Z", "Asha", "sure, I'll bring the soil and the seed trays", True),
            wa(4, "2026-03-11T02:00:00Z", "Garden club", "Planting starts Saturday", True),
            wa(5, "2026-03-04T15:00:00Z", "Asha", "see you then", True),
            wa(6, "2026-03-05T15:00:00Z", "Asha", "back home", True),
        ],
    )  # fmt: skip
    jsonl(
        raw / "email" / "personal" / "2026-03.jsonl",
        [
            mail(1, "2026-03-10T15:00:00Z", True, "Slides", "Here are the slides for Thursday", ["ben@example.com", "me@example.com"]),
            mail(2, "2026-03-10T16:00:00Z", False, "Your results", THEIR_MAIL, ["me@example.com"]),
        ],
    )  # fmt: skip
    jsonl(
        raw / "calendar" / "personal" / "2026-03.jsonl",
        [
            {"id": "c1", "ts": "2026-03-10T14:00:00Z", "start": "2026-03-10T14:00:00Z", "all_day": False,
             "summary": "Lab meeting", "location": "Room 3"},
            {"id": "c2", "ts": "2026-03-10T00:00:00Z", "start": "2026-03-10", "end": "2026-03-12",
             "all_day": True, "summary": "Spring break"},
            {"id": "c3", "ts": "2026-03-10T18:00:00Z", "start": "2026-03-10T18:00:00Z",
             "summary": "Called off", "status": "CANCELLED"},
        ],
    )  # fmt: skip
    birthday = {"id": "b1", "ts": "2026-03-10T00:00:00Z", "start": "2026-03-10", "all_day": True}
    jsonl(
        raw / "calendar" / "birthdays" / "2026-03.jsonl", [birthday | {"summary": "Bo's birthday"}]
    )
    jsonl(
        raw / "notes" / "pages" / "2026-03.jsonl",
        [{"id": "n1", "ts": "2026-03-10T20:00:00Z", "title": "Garden plan", "text": "Beds A to D"}],
    )
    jsonl(
        raw / "strava" / "activities" / "2026-03.jsonl",
        [{"id": "s1", "ts": "2026-03-10T11:00:00Z", "sport_type": "Walk", "name": "Morning walk",
          "distance_m": 4200, "moving_time_s": 3000}],
    )  # fmt: skip
    jsonl(
        raw / "spotify" / "plays" / "2026-03.jsonl",
        [{"id": f"p{n}", "ts": f"2026-03-10T2{n}:00:00Z", "ms_played": 1_800_000, "incognito": False,
          "kind": "track", "artist": "The Ferns", "track": "Rain"} for n in range(2)],
    )  # fmt: skip
    jsonl(
        raw / "youtube" / "watched" / "2026-03.jsonl",
        [{"id": "y1", "ts": "2026-03-10T23:00:00Z", "title": "How to prune roses", "channel": "Gardens"}],
    )  # fmt: skip
    jsonl(
        raw / "youtube" / "searched" / "2026-03.jsonl",
        [{"id": "q1", "ts": "2026-03-10T22:59:00Z", "text": "rose pruning"}],
    )
    jsonl(
        raw / "photos" / "meta" / "2026-03.jsonl",
        [{"id": "f1", "ts": "2026-03-10T19:00:00Z", "title": "IMG_1.jpg", "album": "Spring",
          "people": ["Asha"]}],
    )  # fmt: skip
    jsonl(
        raw / "healthrecords" / "encounters" / "2026-03.jsonl",
        [{"id": "h1", "ts": "2026-03-10T17:00:00Z", "name": "Office visit"}],
    )
    jsonl(
        raw / "healthrecords" / "observations" / "2026-03.jsonl",
        [{"id": f"o{n}", "ts": "2026-03-10T17:30:00Z", "name": name, "value": 5}
         for n, name in enumerate(["Hemoglobin", "Glucose"])],
    )  # fmt: skip
    jsonl(
        raw / "linkedin" / "connections" / "2026-03.jsonl",
        [{"id": "l1", "ts": "2026-03-10T12:00:00Z", "name": "Ravi Kumar", "company": "Acme"}],
    )
    entry = {"date": "2026-03-10", "brief": "You  sent the slides.", "next_up": ["Water beds"] * 4}
    (v / "clones" / "journal").mkdir(parents=True)
    (v / "clones" / "journal" / "2026-03-10.json").write_text(json.dumps(entry))
    note = "# whatsapp, 2026-03\n\n## Focus\nSam planned the spring garden with Asha.\n"
    (v / "observations" / "whatsapp").mkdir(parents=True)
    (v / "observations" / "whatsapp" / "2026-03.md").write_text(note)
    memory.build(v)
    return v


def test_a_day_is_titles_names_counts_and_only_the_user_s_own_words(vault):
    found = life.day(vault, DAY)

    assert found["date"] == "2026-03-10"
    assert found["wrote"] == [
        {"to": "Asha", "channel": "WhatsApp", "count": 2,
         "said": "sure, I'll bring the soil and the seed trays"},
        {"to": "ben@example.com", "channel": "Email", "count": 1,
         "said": "Here are the slides for Thursday"},
        # 02:00 UTC on the 11th is 22:00 on the 10th in New York.
        {"to": "Garden club", "channel": "WhatsApp", "count": 1, "said": "Planting starts Saturday"},
    ]  # fmt: skip
    assert found["events"] == ["All day: Spring break", "10:00 Lab meeting @ Room 3"]
    assert found["notes"] == ["Notes: Garden plan"]
    assert found["activity"] == [
        "Walk: Morning walk, 4.2 km in 50 min",
        "Spotify: 2 plays, 1.0 hours, most of it The Ferns",
        "YouTube: watched 1, among them How to prune roses",
        "YouTube searches: rose pruning",
        "Photos: 1, in Spring, with Asha",
    ]
    assert found["moved"] == ["Walk", "Spotify"]  # what leads its activity
    assert found["health"] == ["Visit: Office visit", "Results (2): Hemoglobin; Glucose"]
    assert found["other"] == [
        "Heard from Asha (WhatsApp, 1); Lab Desk (Email, 1)",  # names only, never their words
        "LinkedIn connections: 1",
    ]
    assert found["journal"] == {"brief": "You sent the slides.", "next_up": ["Water beds"] * 3}
    assert found["sources"]["WhatsApp"] == 4 and found["sources"]["Email"] == 2
    shown = json.dumps(found)
    assert "PRIVATE-THEIRS" not in shown and "THEIR-MAIL" not in shown
    assert "Your results" not in shown  # the subject someone else gave their mail
    assert "Bo's birthday" not in shown and "Called off" not in shown
    # The all-day event runs on into the 11th; a day with nothing is empty, not missing.
    assert life.day(vault, date(2026, 3, 11))["events"] == ["All day: Spring break"]
    assert life.day(vault, date(2026, 3, 25))["records"] == 0


def test_a_month_lists_its_days_from_one_count_of_the_whole_index(vault):
    counts = life.calendar(vault)
    assert counts["2026-03-10"]["whatsapp"] == 4  # local days, from one query
    # An all-day event, at midnight UTC in the index, counts on its own date, not the evening
    # before; Spotify's month of plays is one summary row, no day's.
    assert counts["2026-03-10"]["calendar"] == 4 and "2026-03-09" not in counts
    assert "spotify" not in counts["2026-03-10"]
    assert life.months(vault, DAY)["2026-03"] == {"days": 3, "records": 20}
    assert life.months(vault, date(2026, 3, 9))["2026-03"]["days"] == 2  # not what's ahead
    kept = vault / "clones" / "life" / "calendar.json"
    assert os.name == "nt" or stat.S_IMODE(kept.stat().st_mode) == 0o600

    listed = life.days(vault, "2026-03")
    assert [d["date"] for d in listed] == ["2026-03-04", "2026-03-05", "2026-03-10", "2026-03-11"]

    # Kept: when the index reads a month file again, only that file's days are counted again.
    assert life.calendar(vault) == counts
    saved = json.loads(kept.read_text())
    saved["files"]["notes/pages/2026-03.jsonl"]["days"] = {"2026-03-10": 7}  # a recount undoes it
    kept.write_text(json.dumps(saved))
    jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-04.jsonl",
        [wa(9, "2026-04-02T15:00:00Z", "Ana", "hi", True)],
    )
    memory.build(vault)
    counts = life.calendar(vault)
    assert counts["2026-04-02"] == {"whatsapp": 1} and counts["2026-03-10"]["notes"] == 7


RODE = "Rode 42 km with an average heart rate of 151."  # what Strava's details lead a model to


@pytest.fixture
def cared(vault):
    """The vault with care's timeline, what the user told Proxenos, and Strava's observer."""
    event = {"kind": "visit", "evidence": ["email/personal/e2"]}
    timeline = [
        event | {"date": "2026-03-12", "title": "Urgent care visit", "with": "urgent care clinic",
                 "detail": "Seen for chest pain; an ECG was done."},
        event | {"date": "2026-02-27", "title": "February checkup", "with": "", "detail": ""},
        event | {"date": "2026-03-16", "kind": "result", "title": "ECG result", "with": "",
                 "detail": "Normal sinus rhythm, as the report states."},
    ]  # fmt: skip
    (vault / "clones" / "care").mkdir(parents=True)
    (vault / "clones" / "care" / "care.json").write_text(json.dumps({"timeline": timeline}))
    jsonl(
        vault / "state" / "told.jsonl",
        [
            {"at": "2026-03-14T15:00:00+00:00", "text": "I was scared before the scan", "always": False},
            {"at": "2026-03-15T15:00:00+00:00", "text": "RULE keep replies short", "always": True},
            {"at": "2026-04-02T15:00:00+00:00", "text": "APRIL not this month", "always": False},
            {"at": "2026-03-17T15:00:00+00:00", "text": "GONE taken back", "always": False},
            {"at": "2026-03-17T16:00:00+00:00", "forget": "2026-03-17T15:00:00+00:00"},
        ],
    )  # fmt: skip
    (vault / "observations" / "strava").mkdir(parents=True)
    note = "# strava, 2026-03\n\nSam rode 42.1 km at an avg HR of 151 bpm.\n"
    (vault / "observations" / "strava" / "2026-03.md").write_text(note)
    return vault


# Paragraphs a blank line apart, one cut across lines, and one mainly about the ride.
ESSAY = (
    "March began in the garden. I planned the beds with Asha\nand sent Ben the slides.\n\n"
    f"{RODE}\n\n  \n\nThen I went to urgent care with chest pain, and the ECG came back normal."
)


def answer(prompt, *, system=None, schema=None, **kw):
    """A model that writes about the ride Strava recorded, as a local one did."""
    return {
        "summary": f"March was the garden, and a scare at urgent care. {RODE}",
        "essay": ESSAY,
        "entries": [
            {"day": "2026-03-12", "text": "I went to urgent care with chest pain. They did an ECG."},
            {"day": "2026-03-10", "text": "I  planned the garden with Asha. Then I went for a long ride by the river."},
            {"day": "2026-03-10", "text": "I sent Ben the slides."},
            {"day": "2026-02-28", "text": "OUTSIDE the month."},
            {"day": "2026-03-32", "text": "NO such day."},
            {"day": "2026-03-07", "text": RODE},
            {"day": "2026-03-11", "text": "  "},
        ],
        "highlights": ["Mar 12: Urgent care", "Mar 7: A 42 km ride", "Mar 10: The garden plan",
                       "2026-03-14: Scared before the scan", "Mar 16: The ECG result", "Mar 1: x", " "],
    }  # fmt: skip


def test_a_month_s_diary_reads_care_told_notes_and_days_never_anyone_else_s_words(
    cared, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append((prompt, system, schema))
        return answer(prompt)

    monkeypatch.setattr(llm, "ask", ask)
    entry = life.write(cared, "2026-03", NOW)

    prompt, system, schema = asked[0]
    assert schema is life._SCHEMA
    assert "PRIVATE-THEIRS" not in prompt and "THEIR-MAIL" not in prompt
    assert "Sam planned the spring garden with Asha." in prompt  # the observer's note
    assert 'Asha (WhatsApp, 2): "sure, I\'ll bring the soil and the seed trays"' in prompt
    assert "Journal: You sent the slides." in prompt
    # Care's timeline that month, and what the user told Proxenos: their facts, not their rules.
    assert (
        "- Thu Mar 12: Visit: Urgent care visit (urgent care clinic). Seen for chest pain; an ECG "
        "was done." in prompt
    )
    assert "- Mon Mar 16: Result: ECG result. Normal sinus rhythm" in prompt
    assert "February checkup" not in prompt
    assert "- Sat Mar 14: I was scared before the scan" in prompt
    assert "RULE" not in prompt and "APRIL" not in prompt and "GONE" not in prompt
    fence = system.split("inside <", 1)[1].split(">", 1)[0]
    assert fence.startswith("untrusted-")
    # The medical records' titles, which their providers wrote, and the days go inside the tag;
    # care's timeline is the user's own record and doesn't.
    records = prompt.index("- Tue Mar 10: Visit: Office visit; Results (2): Hemoglobin; Glucose")
    assert prompt.index(f"<{fence}>") < records < prompt.index(f"</{fence}>")
    assert prompt.index("Urgent care visit") < prompt.index(f"<{fence}>")
    days = prompt.index("### Tue Mar 10")
    assert prompt.index(f"<{fence}>", records) < days < prompt.rindex(f"</{fence}>")
    # Walks and listening only as counts a week: no distance, time, name or artist.
    assert "Week of Mon Mar 9: walked once; listened on 1 day" in prompt
    for detail in ("Morning walk", "4.2", "km", "50 min", "The Ferns", "1.0 hours", "bpm"):
        assert detail not in prompt
    assert "Activity: YouTube: watched 1" in prompt
    assert "don't assume anyone's pronouns" in system and "never diagnose" in system
    assert "first person" in system and "never play it down" in system

    # Sentences about a workout go, and so do days outside the month; a day's two are one.
    assert entry["summary"] == "March was the garden, and a scare at urgent care."
    assert entry["essay"] == (
        "March began in the garden. I planned the beds with Asha and sent Ben the slides.\n\n"
        "Then I went to urgent care with chest pain, and the ECG came back normal."
    )
    assert entry["entries"] == [
        {"day": "2026-03-10", "text": "I planned the garden with Asha. I sent Ben the slides."},
        {"day": "2026-03-12", "text": "I went to urgent care with chest pain. They did an ECG."},
    ]
    assert entry["highlights"] == [
        "Mar 12: Urgent care",
        "Mar 10: The garden plan",
        "2026-03-14: Scared before the scan",
        "Mar 16: The ECG result",
        "Mar 1: x",
    ]
    assert entry["days_with_records"] == 4
    path = cared / "clones" / "life" / "months" / "2026-03.json"
    assert json.loads(path.read_text()) == entry
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        for folder in (path.parent, path.parent.parent):
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_a_workout_stays_when_the_user_s_own_words_that_day_were_about_it(cared, monkeypatch):
    monkeypatch.setattr(llm, "ask", answer)
    with (cared / "state" / "told.jsonl").open("a") as f:
        f.write(json.dumps({"at": "2026-03-07T20:00:00+00:00", "text": "Went for a long ride to "
                            "clear my head", "always": False}) + "\n")  # fmt: skip

    entry = life.write(cared, "2026-03", NOW)

    assert {"day": "2026-03-07", "text": RODE} in entry["entries"]
    assert "Mar 7: A 42 km ride" in entry["highlights"]
    assert entry["summary"].endswith(RODE)
    assert RODE in entry["essay"].split("\n\n")
    # Only that day's: the ride on the 10th still goes.
    assert entry["entries"][1]["text"] == "I planned the garden with Asha. I sent Ben the slides."


def test_what_counts_as_a_workout_is_what_strava_would_record():
    for workout in (
        RODE,
        "Went for a hike up the ridge.",
        "A 12 km run along the river.",
        "My average pace was 5:10 min/km.",
        "Logged it on Strava.",
    ):
        assert life._without_workouts(workout) == "", workout
    for kept in (
        "I gave Asha a ride to the clinic.",
        "My heart rate was 120 at the emergency department.",
        "I ran into Ben at the market.",
        "I drove 300 km to see family.",
    ):
        assert life._without_workouts(kept) == kept


def test_the_schema_holds_each_entry_to_a_day_and_its_text():
    items = life._SCHEMA["properties"]["entries"]["items"]
    assert items["required"] == ["day", "text"] and items["additionalProperties"] is False
    held = llm._conform(
        {
            "summary": "s",
            "essay": "e",
            "entries": [{"day": "2026-03-10", "text": "t", "mood": "x"}, {"day": "2026-03-11"}],
            "highlights": ["Mar 10: t"],
        },
        life._SCHEMA,
    )
    assert held["entries"] == [{"day": "2026-03-10", "text": "t"}]  # the one with no text goes


def test_a_month_with_nothing_in_it_is_not_written(vault, monkeypatch):
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    assert life.write(vault, "2019-01", NOW) is None
    assert not (vault / "clones" / "life" / "months" / "2019-01.json").exists()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A vault whose months, June 2025 to March 2026, each hold five days of records, and a
    January 2025 that holds one; `write` faked to save a story and keep the month."""
    held = {f"2025-{m:02d}": {"days": 5, "records": 40} for m in range(6, 13)}
    held |= {"2026-01": {"days": 5, "records": 40}, "2026-02": {"days": 5, "records": 40}}
    held |= {"2026-03": {"days": 5, "records": 40}, "2025-01": {"days": 1, "records": 2}}
    monkeypatch.setattr(life, "months", lambda vault, today=None: dict(sorted(held.items())))
    monkeypatch.setattr(llm, "configured", lambda: True)
    written, failing = [], set()

    def write(vault, month, now=None):
        if month in failing:
            raise llm.ModelError("the model declined")
        written.append(month)
        life.save(vault, diary(month, life._iso(now)))
        return {}

    monkeypatch.setattr(life, "write", write)
    vault = tmp_path / "vault"
    life.save(vault, diary("2026-02", "2026-02-20T09:00:00Z"))
    life.save(vault, diary("2025-12", "2026-01-02T09:00:00Z"))
    return vault, written, failing


def diary(month, generated):
    return {"month": month, "generated": generated, "summary": "s", "essay": "e", "entries": []}


def test_the_night_writes_the_month_just_ended_this_one_then_backfills_newest_first(
    ledger, new_york
):
    vault, written, failing = ledger
    stats = life.night(vault, datetime(2026, 3, 2, 6, 30, tzinfo=UTC))  # 01:30 in New York

    # February was written while it was going; March is new; then four older months, newest
    # first, past December's story, never January 2025's single day.
    assert written == ["2026-02", "2026-03", "2026-01", "2025-11", "2025-10", "2025-09"]
    assert stats == {"months due": 6, "stories": 6, "failed": 0, "months left": 3}
    state = json.loads((vault / "state" / "life.json").read_text())
    assert state["left"] == 3 and state["wrote"] == written
    if os.name != "nt":
        assert stat.S_IMODE((vault / "state" / "life.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((vault / "state").stat().st_mode) == 0o700

    # The next night: February and March are fresh, so only the backfill goes on. A month that
    # fails waits a week, and the ones after it still get their turn.
    written.clear()
    failing.add("2025-08")
    stats = life.night(vault, datetime(2026, 3, 3, 6, 30, tzinfo=UTC))
    assert written == ["2025-07", "2025-06"]
    assert stats["failed"] == 1 and stats["months left"] == 1
    written.clear()
    assert life.night(vault, datetime(2026, 3, 4, 6, 30, tzinfo=UTC))["months due"] == 0
    assert written == []
    failing.clear()
    life.night(vault, datetime(2026, 3, 11, 6, 30, tzinfo=UTC))
    # A week on: the failed month again, and March rewritten, a week after the last.
    assert written == ["2026-03", "2025-08"]


def test_a_night_with_nothing_due_asks_no_model(vault, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    life.save(vault, diary("2026-03", "2026-03-18T09:00:00Z"))
    life.save(vault, diary("2026-02", "2026-03-01T09:00:00Z"))

    stats = life.night(vault, NOW)

    assert stats == {"months due": 0, "stories": 0, "failed": 0, "months left": 0}


def test_a_month_written_before_there_were_entries_is_written_again(ledger, new_york):
    vault, written, _ = ledger
    old = {
        "month": "2025-12",
        "generated": "2026-01-02T09:00:00Z",
        "story": "You",
        "highlights": [],
    }
    life.save(vault, old)
    assert life.stories(vault)["2025-12"]["story"] == "You"  # still read

    life.night(vault, datetime(2026, 3, 2, 6, 30, tzinfo=UTC))

    assert written == ["2026-02", "2026-03", "2026-01", "2025-12", "2025-11", "2025-10"]
    assert life.stories(vault)["2025-12"]["entries"] == []  # in the new form


def test_without_a_model_the_night_writes_nothing(ledger, monkeypatch):
    vault, written, _ = ledger
    monkeypatch.setattr(llm, "configured", lambda: False)
    stats = life.night(vault, NOW)
    assert stats["no model"] == 1 and stats["stories"] == 0 and written == []


def test_the_command_prints_a_day_or_a_month_as_json_alone(vault, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    cli.main(["clone", "life", "--day", "2026-03-10"])
    assert json.loads(capsys.readouterr().out)["wrote"][0]["to"] == "Asha"
    cli.main(["clone", "life", "--days", "2026-03"])
    assert len(json.loads(capsys.readouterr().out)["days"]) == 4
    cli.main(["clone", "life", "--calendar"])
    assert capsys.readouterr().out == "life: 3 days with records\n"

    args = argparse.Namespace(day=None, days=None, calendar=False, month="2026-3")
    with pytest.raises(SystemExit, match="YYYY-MM"):
        life.run(vault, args)
    month = argparse.Namespace(**{**vars(args), "month": "2026-03"})
    monkeypatch.setattr(llm, "configured", lambda: False)
    with pytest.raises(SystemExit, match="no model"):
        life.run(vault, month)

    def declined(*a, **k):
        raise llm.ModelError("the model\ndeclined")

    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(llm, "ask", declined)
    with pytest.raises(SystemExit, match=r"no diary for 2026-03 \(the model declined\)"):
        life.run(vault, month)  # a line the page can show, not a traceback


def test_a_backfill_now_writes_every_month_waiting_newest_first(ledger, new_york):
    vault, written, _ = ledger
    stats = life.night(vault, datetime(2026, 3, 2, 6, 30, tzinfo=UTC), backfill=None)

    assert written == ["2026-02", "2026-03", "2026-01", "2025-11", "2025-10", "2025-09"] + [
        "2025-08",
        "2025-07",
        "2025-06",
    ]
    assert stats["months left"] == 0  # never January 2025's single day


def append(path, *lines):
    """Lines appended to a file, as the page appends them to told, edits and corrections."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write("".join(json.dumps(line) + "\n" for line in lines))


def test_a_month_is_an_abstract_and_an_essay_or_not_written(cared, monkeypatch):
    assert life._SCHEMA["required"] == ["summary", "essay", "entries", "highlights"]
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append(system)
        return answer(prompt)

    monkeypatch.setattr(llm, "ask", ask)
    entry = life.write(cared, "2026-03", NOW)

    assert "the month's abstract, two to four sentences" in asked[0]
    assert "several paragraphs, about 600 to 1,200 words" in asked[0]
    assert entry["summary"] and entry["essay"].count("\n\n") == 1
    # A model that writes no essay writes no diary, and the one before stays.
    monkeypatch.setattr(llm, "ask", lambda *a, **k: answer("") | {"essay": f"{RODE}\n\n "})
    with pytest.raises(llm.ModelError, match="no diary"):
        life.write(cared, "2026-03", NOW)
    assert life.stories(cared)["2026-03"] == entry


def test_a_fact_the_user_told_is_a_milestone_of_its_month(cared, monkeypatch):
    append(
        cared / "state" / "told.jsonl",
        {"at": "2026-03-03T15:00:00+00:00", "text": "I got the fellowship at Kestrel Labs",
         "always": False},
    )  # fmt: skip
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append((prompt, system))
        return answer(prompt)

    monkeypatch.setattr(llm, "ask", ask)
    entry = life.write(cared, "2026-03", NOW)

    prompt, system = asked[0]
    milestones = prompt.index("# Milestones: what you told Proxenos this month")
    assert milestones < prompt.index("- Tue Mar 3: I got the fellowship at Kestrel Labs")
    assert milestones < prompt.index("# Health and care")
    assert "Each must be in the summary, the essay and the highlights." in prompt
    assert "The milestones they told Proxenos are the month's biggest events" in system
    assert "GONE" not in prompt  # a fact the user removed is no milestone
    # The model's highlights left it out, so one in the user's own words leads the card; the
    # fear before the scan, which a highlight is about, isn't added again.
    assert entry["highlights"][0] == "Mar 3: I got the fellowship at Kestrel Labs"
    assert sum("scan" in h.casefold() for h in entry["highlights"]) == 1


def test_a_month_told_or_marked_since_it_was_written_is_due_the_next_night(ledger, new_york):
    vault, written, _ = ledger
    life.save(vault, diary("2026-03", "2026-03-18T09:00:00Z"))  # fresh: a week isn't up
    life.save(vault, diary("2026-02", "2026-03-01T09:00:00Z"))  # once it ended
    night = datetime(2026, 3, 20, 6, 30, tzinfo=UTC)
    assert life.night(vault, night, backfill=0)["months due"] == 0

    told_at = vault / "state" / "told.jsonl"
    append(
        told_at,
        {"at": "2026-03-19T21:00:00+00:00", "text": "We moved into the new flat", "always": False},
        {"at": "2026-03-19T21:05:00+00:00", "text": "A rule", "always": True},
        {"at": "2026-02-10T12:00:00+00:00", "text": "Told before it was written", "always": False},
    )
    append(
        vault / life.CORRECTIONS,
        {"at": "2026-03-19T22:00:00Z", "month": "2025-12", "item": "highlight", "text": "s"},
    )
    life.night(vault, night, backfill=0)
    # This month, whatever the week says; December, marked not true; not February, written since.
    assert written == ["2026-03", "2025-12"]

    written.clear()
    append(told_at, {"at": "2026-03-20T08:00:00+00:00", "forget": "2026-02-10T12:00:00+00:00"})
    life.night(vault, datetime(2026, 3, 21, 6, 30, tzinfo=UTC), backfill=0)
    assert written == ["2026-02"]  # what it was told is taken back

    # A month with no other records is written for what the user told Proxenos about it.
    written.clear()
    append(told_at, {"at": "2026-04-01T14:00:00+00:00", "text": "I started", "always": False})
    life.night(vault, datetime(2026, 4, 2, 6, 30, tzinfo=UTC), backfill=0)
    assert written[:2] == ["2026-03", "2026-04"]


def test_an_edit_is_the_user_s_and_survives_the_nights(vault, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda: True)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    old = {"month": "2026-03", "generated": "2026-03-01T09:00:00Z", "summary": "s",
           "entries": [], "highlights": []}  # fmt: skip
    life.save(vault, old)  # from before there was an essay: due, but for the edit
    mine = "I planted the garden with Asha.\n\nThe scan was nothing in the end."
    append(
        vault / life.EDITS,
        {"at": "2026-03-02T10:00:00Z", "month": "2026-03", "summary": "Older", "essay": "x"},
        {"at": "2026-03-05T10:00:00Z", "month": "2026-03", "summary": " Mine,  now ",
         "essay": mine},
        {"at": "2026-03-05T10:00:00Z", "month": "March", "summary": "bad", "essay": "bad"},
    )  # fmt: skip
    append(
        vault / "state" / "told.jsonl",
        {"at": "2026-03-19T15:00:00+00:00", "text": "Told after the edit", "always": False},
    )
    assert life.edits(vault) == {
        "2026-03": {"at": "2026-03-05T10:00:00Z", "summary": "Mine, now", "essay": mine}
    }

    assert life.night(vault, NOW)["months due"] == 0
    assert life.stories(vault)["2026-03"] == old

    # Writing it again, which the page asks about first, reads the edit as the strongest guide.
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append((prompt, system))
        return answer(prompt)

    monkeypatch.setattr(llm, "ask", ask)
    life.write(vault, "2026-03", NOW)
    prompt, system = asked[0]
    own = prompt.index("# Your own account of the month")
    assert prompt.index("Abstract: Mine, now") > own
    assert prompt.index(mine) > own and own < prompt.index("# Milestones")
    assert "is the strongest guide to what's true" in system
    # Written after the edit, it's no longer the user's text, and the nights go on as before.
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    assert life.night(vault, NOW)["months due"] == 0


def test_what_the_user_marked_not_true_leads_the_next_write_and_stays_out(cared, monkeypatch):
    entry = "I planned the garden with Asha. I sent Ben the slides."
    line = {"at": "2026-03-19T10:00:00Z", "month": "2026-03", "item": "entry:2026-03-10",
            "text": entry, "correction": "It was  Ravi, not Asha."}  # fmt: skip
    append(
        cared / life.CORRECTIONS,
        line,
        line,  # sent twice: one
        {"at": "2026-03-19T10:01:00Z", "month": "2026-03", "item": "highlight",
         "text": "Mar 16: The ECG result"},
        {"at": "2026-03-19T10:02:00Z", "month": "2026-03", "item": "essay",
         "text": "Then I went to urgent care with chest pain, and the ECG came back normal."},
        {"at": "2026-03-19T10:03:00Z", "month": "2026-03", "item": "highlight",
         "text": "Mar 1: x"},
        {"at": "2026-03-19T10:04:00Z", "month": "2026-03", "item": "highlight",
         "text": "Mar 1: x", "undo": True},
        {"at": "2026-03-19T10:05:00Z", "month": "2026-02", "item": "highlight", "text": "Feb"},
        {"at": "2026-03-19T10:06:00Z", "month": "2026-03", "item": "entry:2026-02-01",
         "text": "Another month's day"},
        {"at": "2026-03-19T10:07:00Z", "month": "2026-03", "item": "summary", "text": "No"},
    )  # fmt: skip
    found = life.corrections(cared, "2026-03")
    assert [(m["item"], m["correction"]) for m in found] == [
        ("entry:2026-03-10", "It was Ravi, not Asha."),
        ("highlight", ""),
        ("essay", ""),
    ]
    assert len(life.corrections(cared)) == 4  # February's too
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append((prompt, system))
        return answer(prompt)

    monkeypatch.setattr(llm, "ask", ask)
    written = life.write(cared, "2026-03", NOW)

    prompt, system = asked[0]
    wrong = prompt.index("# What you said isn't true")
    assert wrong < prompt.index("# Milestones") < prompt.index("# Health and care")
    assert (
        f'- The entry for Tue Mar 10 said: "{entry}" Not true. What\'s true, in your words: '
        '"It was Ravi, not Asha."' in prompt
    )
    assert '- A highlight said: "Mar 16: The ECG result" Not true.' in prompt
    assert "Mar 1: x" not in prompt[wrong : prompt.index("# Milestones")]  # taken back
    assert "overrides everything else" in system
    # The model wrote them again word for word: they go, and the rest stays.
    assert [e["day"] for e in written["entries"]] == ["2026-03-12"]
    assert "Mar 16: The ECG result" not in written["highlights"]
    assert "Mar 1: x" in written["highlights"]
    assert "ECG came back normal" not in written["essay"]
    assert written["essay"].startswith("March began in the garden.")
    # Think, which reads a day's entry, doesn't read one marked not true.
    assert life.entry_on(cared, "2026-03-12").startswith("I went to urgent care")
    life.save(cared, written | {"entries": [{"day": "2026-03-10", "text": entry}]})
    assert life.entry_on(cared, "2026-03-10") == ""


def test_a_diary_from_before_there_was_an_essay_is_written_again(ledger, new_york):
    vault, written, _ = ledger
    no_essay = {"month": "2026-03", "generated": "2026-03-18T09:00:00Z", "summary": "s",
                "entries": [], "highlights": []}  # fmt: skip
    life.save(vault, no_essay)  # fresh, but in the old form
    life.save(vault, no_essay | {"month": "2025-12"})
    life.save(vault, diary("2026-02", "2026-03-01T09:00:00Z"))
    stats = life.night(vault, datetime(2026, 3, 20, 6, 30, tzinfo=UTC))

    assert written == ["2026-03", "2026-01", "2025-12", "2025-11", "2025-10"]
    assert stats["months left"] == 4
    assert life.stories(vault)["2025-12"]["essay"] == "e"
