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
    assert found["health"] == ["Visit: Office visit", "Results (2): Hemoglobin; Glucose"]
    assert found["other"] == ["LinkedIn connections: 1"]
    assert found["journal"] == {"brief": "You sent the slides.", "next_up": ["Water beds"] * 3}
    assert found["sources"]["WhatsApp"] == 4 and found["sources"]["Email"] == 2
    shown = json.dumps(found)
    assert "PRIVATE-THEIRS" not in shown and "THEIR-MAIL" not in shown
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


def test_a_month_s_story_reads_notes_and_days_never_anyone_else_s_words(vault, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    asked = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append((prompt, system))
        return {
            "story": "You planned  the garden with Asha.\n\n\nYou walked most mornings.\n",
            "highlights": [f"Mar {n}: something" for n in range(1, 9)] + ["  "],
        }

    monkeypatch.setattr(llm, "ask", ask)
    entry = life.write(vault, "2026-03", NOW)

    prompt, system = asked[0]
    assert "PRIVATE-THEIRS" not in prompt and "THEIR-MAIL" not in prompt
    assert "Sam planned the spring garden with Asha." in prompt  # the observer's note
    assert 'Asha (WhatsApp, 2): "sure, I\'ll bring the soil and the seed trays"' in prompt
    assert "Health records: Visit: Office visit" in prompt
    assert "Journal: You sent the slides." in prompt
    fence = system.split("inside <", 1)[1].split(">", 1)[0]
    assert fence.startswith("untrusted-")
    assert prompt.index(f"<{fence}>") < prompt.index("### Tue Mar 10") < prompt.index(f"</{fence}>")
    assert "don't assume anyone's pronouns" in system and "never diagnose" in system

    assert entry["story"] == "You planned the garden with Asha.\n\nYou walked most mornings."
    assert entry["highlights"] == [f"Mar {n}: something" for n in range(1, 7)]
    assert entry["days_with_records"] == 4
    path = vault / "clones" / "life" / "months" / "2026-03.json"
    assert json.loads(path.read_text()) == entry
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        for folder in (path.parent, path.parent.parent):
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700


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
        life.save(vault, {"month": month, "generated": life._iso(now), "story": "s"})
        return {}

    monkeypatch.setattr(life, "write", write)
    vault = tmp_path / "vault"
    life.save(vault, {"month": "2026-02", "generated": "2026-02-20T09:00:00Z", "story": "s"})
    life.save(vault, {"month": "2025-12", "generated": "2026-01-02T09:00:00Z", "story": "s"})
    return vault, written, failing


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
    life.save(vault, {"month": "2026-03", "generated": "2026-03-18T09:00:00Z", "story": "s"})
    life.save(vault, {"month": "2026-02", "generated": "2026-03-01T09:00:00Z", "story": "s"})

    stats = life.night(vault, NOW)

    assert stats == {"months due": 0, "stories": 0, "failed": 0, "months left": 0}


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
    monkeypatch.setattr(llm, "configured", lambda: False)
    with pytest.raises(SystemExit, match="no model"):
        life.run(vault, argparse.Namespace(**{**vars(args), "month": "2026-03"}))
