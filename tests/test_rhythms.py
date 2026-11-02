"""The rhythms clone on a synthetic vault: its weeks in local time and ISO weeks, kept per month
file and counted again only where one changed, artists labelled from a fixed vocabulary with the
model faked out, and the plain lines on what stands out. No network, no real data."""

import argparse
import json
import os
import stat
import time
from datetime import UTC, date, datetime

import pytest

from proxenos import cli, llm, memory
from proxenos.clones import rhythms

NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
THEIRS = "PRIVATE-THEIRS keep this between us"  # someone else's words: never in the series


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def wa(n, ts, chat, text, me):
    return {
        "id": f"m{n}", "ts": ts, "chat_id": f"{chat}@s.whatsapp.net", "chat_name": chat,
        "chat_type": "direct", "from_me": me, "sender_id": None if me else "1",
        "sender_name": None if me else chat, "kind": "text", "wa_type": 0, "text": text,
    }  # fmt: skip


def mail(n, ts, me, to):
    return {
        "id": f"e{n}", "ts": ts, "from_address": "me@example.com" if me else "lab@example.org",
        "from_name": "Sam Doe" if me else "Lab Desk", "from_me": me, "to": to,
        "subject": f"Note {n}", "body_new": "Here it is" if me else THEIRS,
    }  # fmt: skip


def play(n, ts, artist, ms, kind="track"):
    found = {"id": f"p{n}", "ts": ts, "kind": kind, "ms_played": ms, "incognito": False}
    return found | ({"artist": artist, "track": "Song"} if kind == "track" else {"show": artist})


def ride(n, ts, sport, km, minutes, climb=0):
    return {"id": f"s{n}", "ts": ts, "sport_type": sport, "distance_m": km * 1000,
            "moving_time_s": minutes * 60, "total_elevation_gain_m": climb}  # fmt: skip


@pytest.fixture
def new_york(monkeypatch):
    """This process, and SQLite in it, on New York time: in early March that's UTC-5."""
    if not hasattr(time, "tzset"):
        pytest.skip("the time zone is set through tzset, which Windows doesn't have")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def vault(tmp_path, monkeypatch, new_york):
    """Two weeks of made-up records either side of Sunday 2026-03-08, and the turn of the year,
    indexed."""
    monkeypatch.setenv("PROXENOS_NAME", "Sam Doe")
    monkeypatch.setenv("PROXENOS_EMAILS", "me@example.com")
    v = tmp_path / "vault"
    raw = v / "raw"
    jsonl(
        raw / "spotify" / "plays" / "2026-03.jsonl",
        [
            play(1, "2026-03-04T15:00:00Z", "The Ferns", 3_600_000),
            # 03:00 UTC on Monday the 9th is Sunday evening in New York: still week 10.
            play(2, "2026-03-09T03:00:00Z", "The Ferns", 1_800_000),
            play(3, "2026-03-05T15:00:00Z", "Low Tide", 1_800_000),
            play(4, "2026-03-05T16:00:00Z", "Low Tide", 10_000),  # played, not a play
            play(5, "2026-03-06T16:00:00Z", "Kiln Talk", 1_800_000, kind="episode"),
            play(6, "2026-03-10T15:00:00Z", "Grey Static", 3_600_000),
            play(7, "2026-03-10T16:00:00Z", "Secret", 3_600_000) | {"incognito": True},
        ],
    )
    jsonl(  # Monday 29 December 2025 is in the first ISO week of 2026.
        raw / "spotify" / "plays" / "2025-12.jsonl",
        [play(8, "2025-12-29T15:00:00Z", "The Ferns", 600_000)],
    )
    jsonl(
        raw / "strava" / "activities" / "2026-03.jsonl",
        [
            ride(1, "2026-03-07T14:00:00Z", "Ride", 40, 120, 350),
            ride(2, "2026-03-04T14:00:00Z", "GravelRide", 20, 60, 100),
            ride(3, "2026-03-05T11:00:00Z", "TrailRun", 8, 50),
            ride(4, "2026-03-06T11:00:00Z", "Walk", 3, 40),
            ride(5, "2026-03-06T12:00:00Z", "Yoga", 0, 30),
            ride(6, "2026-03-11T14:00:00Z", "Ride", 25, 70, 200),
        ],
    )
    event = {"start": "2026-03-04T14:00:00Z", "end": "2026-03-04T15:30:00Z", "summary": "Lab"}
    jsonl(
        raw / "calendar" / "personal" / "2026-03.jsonl",
        [
            {"id": "c1", "ts": "2026-03-04T14:00:00Z", **event},
            {"id": "c2", "ts": "2026-03-05T00:00:00Z", "start": "2026-03-05", "all_day": True,
             "summary": "Spring break"},
            {"id": "c3", "ts": "2026-03-06T18:00:00Z", "start": "2026-03-06T18:00:00Z",
             "end": "2026-03-06T19:00:00Z", "summary": "Called off", "status": "CANCELLED"},
        ],
    )  # fmt: skip
    jsonl(
        raw / "calendar" / "work" / "2026-03.jsonl", [{"id": "w1", "ts": event["start"], **event}]
    )
    jsonl(
        raw / "calendar" / "birthdays" / "2026-03.jsonl",
        [{"id": "b1", "ts": "2026-03-04T00:00:00Z", "start": "2026-03-04", "summary": "Bo"}],
    )
    jsonl(
        raw / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa(1, "2026-03-04T13:00:00Z", "Asha", THEIRS, False),
            wa(2, "2026-03-04T13:05:00Z", "Asha", "ok", True),
            wa(3, "2026-03-05T13:06:00Z", "Asha", "see you", True),
            wa(4, "2026-03-09T03:30:00Z", "Garden club", "Planting Saturday", True),  # Sunday
            wa(5, "2026-03-10T13:00:00Z", "Asha", "back home", True),
        ],
    )
    jsonl(
        raw / "email" / "personal" / "2026-03.jsonl",
        [
            mail(1, "2026-03-04T15:00:00Z", True, ["ben@example.com", "me@example.com"]),
            mail(2, "2026-03-04T16:00:00Z", True, ["ben@example.com", "ida@example.com"]),
            mail(3, "2026-03-05T16:00:00Z", False, ["me@example.com"]),
        ],
    )
    jsonl(  # a chat with an AI assistant isn't a message to a person
        raw / "chatgpt" / "messages" / "2026-03.jsonl",
        [{"id": "g1", "ts": "2026-03-04T12:00:00Z", "conversation_id": "x", "from_me": True,
          "conversation_title": "Soil pH", "text": "what soil for tomatoes"}],
    )  # fmt: skip
    memory.build(v)
    return v


def weeks_by_id(found):
    return {w["week"]: w for w in found}


def test_weeks_are_iso_weeks_in_local_time_across_every_source(vault):
    totals, counted = rhythms.update(vault)
    assert counted == 8  # every month file, the first time: not the chat with an assistant
    named = {"The Ferns": {"genre": "indie", "moods": ["calm"]}}
    found = weeks_by_id(rhythms.series(totals, named, date(2026, 3, 20)))

    # From the first week with a record to this one, empty weeks too, so charts line up.
    assert list(found)[:2] == ["2026-W01", "2026-W02"] and list(found)[-1] == "2026-W12"
    assert found["2026-W01"]["start"] == "2025-12-29"
    assert found["2026-W05"]["listening"]["hours"] == 0

    heard = found["2026-W10"]["listening"]
    assert heard["hours"] == 2.5 and heard["spoken_hours"] == 0.5
    assert heard["plays"] == 4 and heard["artists"] == 2  # under 30 seconds isn't a play
    assert heard["top"] == [{"name": "The Ferns", "hours": 1.5}, {"name": "Low Tide", "hours": 0.5}]
    assert heard["genres"] == {"indie": 1.5, "unlabelled": 0.5}  # music only: not the podcast
    assert heard["moods"] == {"calm": 1.5, "unlabelled": 0.5}
    assert (heard["top_genre"], heard["top_mood"]) == ("indie", "calm")
    # A private session isn't counted; a week with no label has no top genre.
    later = found["2026-W11"]["listening"]
    assert later["hours"] == 1.0 and later["top_genre"] is None
    assert later["genres"] == {"unlabelled": 1.0}

    moved = found["2026-W10"]["movement"]
    assert moved["rides"] == {"count": 2, "km": 60.0, "hours": 3.0, "climb_m": 450}
    assert moved["runs"] == {"count": 1, "km": 8.0, "hours": 0.83}
    assert moved["walks"]["count"] == 1 and moved["hikes"]["count"] == 0
    assert moved["other"] == {"count": 1, "hours": 0.5}

    said = found["2026-W10"]["messages"]
    assert said["sent"] == {"Email": 2, "WhatsApp": 3}  # the Sunday-evening one too
    assert said["received"] == {"WhatsApp": 1, "Email": 1}
    # Asha's chat, the garden club, and Ben and Ida by address: never Sam's own.
    assert said["people"] == 4
    assert found["2026-W11"]["messages"]["sent"] == {"WhatsApp": 1}

    # One event on two calendars counts once; birthdays and what was called off don't count.
    assert found["2026-W10"]["calendar"] == {"events": 2, "hours": 1.5}

    shown = json.dumps(list(found.values()))
    assert "PRIVATE-THEIRS" not in shown and "Soil" not in shown and "ChatGPT" not in shown


def test_only_files_that_changed_are_counted_again(vault):
    first, _ = rhythms.update(vault)
    assert rhythms.update(vault) == (first, 0)
    kept = vault / "clones" / "rhythms" / "files.json"
    if os.name != "nt":
        assert stat.S_IMODE(kept.stat().st_mode) == 0o600
        assert stat.S_IMODE(kept.parent.stat().st_mode) == 0o700
    # People and events are kept as hashes, never names or titles.
    text = kept.read_text()
    assert "Asha" not in text and "ben@example.com" not in text and "Lab" not in text

    jsonl(
        vault / "raw" / "strava" / "activities" / "2026-03.jsonl",
        [ride(9, "2026-03-17T14:00:00Z", "Ride", 30, 90)],
    )
    jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [wa(9, "2026-03-17T13:00:00Z", "Asha", "hi", True)],
    )
    memory.build(vault)
    totals, counted = rhythms.update(vault)
    assert counted == 2
    assert totals["2026-W12"]["move"]["rides"][0] == 1
    assert "move" not in totals["2026-W10"]  # the file holds only the new ride now
    assert totals["2026-W12"]["sent"] == {"WhatsApp": 1}
    assert totals["2026-W10"]["ms"] == first["2026-W10"]["ms"]  # Spotify's, kept as it was


def test_a_new_time_zone_counts_everything_again(vault, monkeypatch):
    rhythms.update(vault)
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    totals, counted = rhythms.update(vault)
    assert counted == 8
    # 03:00 UTC on the 9th is 08:30 on Monday in India: week 11 now.
    assert totals["2026-W11"]["artists"]["The Ferns"] == 1_800_000


def answer_with(answers, asked):
    def ask(prompt, *, system=None, schema=None, **kwargs):
        asked.append((prompt, system, schema))
        names = prompt.split("\n")[1:-1]
        return {"artists": [answers[n] | {"name": n} for n in names if n in answers]}

    return ask


def test_artists_are_labelled_most_played_first_from_the_vocabulary_only(vault, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda: True)
    asked = []
    answers = {
        "The Ferns": {"genre": "Indie", "moods": ["calm", "dreamy", "nostalgic", "focused"]},
        "Low Tide": {"genre": "vaporwave", "moods": ["calm"]},  # not a genre it knows: dropped
    }
    monkeypatch.setattr(llm, "ask", answer_with(answers, asked))
    monkeypatch.setattr(rhythms, "BATCH", 2)

    data, stats = rhythms.build(vault, label_up_to=10, now=NOW)

    # Most played first, two to a call: only artists' names, inside a tag of their own.
    assert [p.split("\n")[1:-1] for p, *_ in asked] == [["The Ferns", "Grey Static"], ["Low Tide"]]
    prompt, system, schema = asked[0]
    fence = system.split("inside <", 1)[1].split(">", 1)[0]
    assert prompt.startswith(f"<{fence}>") and prompt.endswith(f"</{fence}>")
    assert "Kiln Talk" not in prompt and "PRIVATE" not in prompt
    assert schema["properties"]["artists"]["items"]["properties"]["genre"]["enum"][0] == "pop"
    assert stats["artists labelled"] == 1 and stats["artists unlabelled"] == 2

    kept = json.loads((vault / "clones" / "rhythms" / "artists.json").read_text())
    assert kept["artists"]["The Ferns"]["genre"] == "indie"
    assert kept["artists"]["The Ferns"]["moods"] == ["calm", "nostalgic"]  # known, and two
    assert set(kept["unknown"]) == {"Grey Static", "Low Tide"}
    # Coverage is by listening time: The Ferns' 1.67 hours of 3.17 of music.
    assert data["coverage"] == {"share": 0.526, "artists": 3, "labelled": 1}

    # Labels are kept: the next run asks about no one, and one the model couldn't place waits.
    asked.clear()
    rhythms.build(vault, label_up_to=10, now=NOW)
    assert asked == []
    later = datetime(2026, 4, 25, tzinfo=UTC)
    rhythms.build(vault, label_up_to=10, now=later)
    assert [p.split("\n")[1:-1] for p, *_ in asked] == [["Grey Static", "Low Tide"]]

    # A label outside today's vocabulary is ignored, as if it had none.
    kept["artists"]["The Ferns"]["genre"] = "shoegaze"
    (vault / "clones" / "rhythms" / "artists.json").write_text(json.dumps(kept))
    assert "The Ferns" not in rhythms.labels(vault)


def test_a_night_labels_at_most_its_share(vault, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda: True)
    asked = []
    monkeypatch.setattr(llm, "ask", answer_with({}, asked))
    rhythms.build(vault, label_up_to=1, now=NOW)
    assert [p.split("\n")[1:-1] for p, *_ in asked] == [["The Ferns"]]


def test_with_no_model_everything_else_is_counted_and_nothing_is_asked(vault, monkeypatch):
    monkeypatch.setattr(llm, "configured", lambda: False)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))

    data, stats = rhythms.build(vault, label_up_to=300, now=NOW)

    assert stats["no model"] == 1 and stats["percent of listening labelled"] == 0
    assert data["model"] is False and data["coverage"]["share"] == 0
    found = weeks_by_id(data["weeks"])
    assert found["2026-W10"]["listening"]["genres"] == {"unlabelled": 2.0}
    assert found["2026-W10"]["listening"]["top_mood"] is None
    assert found["2026-W10"]["movement"]["rides"]["count"] == 2
    assert data["channels"] == ["WhatsApp", "Email"]
    assert data["people"]["1m"]["2026-03"] == 4  # Asha, the club, Ben and Ida: each once
    path = vault / "clones" / "rhythms" / "weeks.json"
    assert json.loads(path.read_text()) == data
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_command_prints_counts_or_the_series(vault, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    monkeypatch.setattr(llm, "configured", lambda: True)

    cli.main(["clone", "rhythms", "--json", "--weeks", "3"])  # never a model, for the page
    data = json.loads(capsys.readouterr().out)
    assert len(data["weeks"]) == 3 and data["coverage"]["artists"] == 3
    assert set(data["stands_out"]) == set(rhythms.RANGES)
    assert all(set(by) == set(rhythms.RESOLUTIONS) for by in data["stands_out"].values())

    monkeypatch.setattr(llm, "ask", answer_with({}, []))
    cli.main(["clone", "rhythms", "--weeks", "3", "--label", "0"])
    line = capsys.readouterr().out.strip()
    assert line.startswith("rhythms: 0 files counted, ") and " rides, " in line
    assert cli._defaults(rhythms) == argparse.Namespace(weeks=None, label=rhythms.LABEL, json=False)


# What stands out


def week(start, hours=0.0, top=None, rides=0, km=0.0, sent=None, got=None, moods=None):
    music = hours
    return {
        "week": rhythms._week(date.fromisoformat(start)),
        "start": start,
        "listening": {
            "hours": hours,
            "top": [{"name": top, "hours": hours}] if top else [],
            "genres": {"unlabelled": music} if music else {},
            "moods": moods or ({"unlabelled": music} if music else {}),
        },
        "movement": {"rides": {"count": rides, "km": km}},
        "messages": {"sent": sent or {}, "received": got or {}},
    }


def series():
    """Twelve weeks from Monday 2026-01-05: rides in weeks 2 to 4 and 7 to 8, a busy week of
    messages in the sixth, calm at the start and energetic at the end."""
    mondays = [date(2026, 1, 5).toordinal() + 7 * n for n in range(12)]
    starts = [date.fromordinal(d).isoformat() for d in mondays]
    found = []
    for n, start in enumerate(starts):
        found.append(
            week(
                start,
                hours=10 if n == 9 else 2,
                top="Low Tide" if n == 9 else "The Ferns",
                rides=1 if n in (1, 2, 3, 6, 7) else 0,
                km=30 if n in (1, 2, 3, 6, 7) else 0,
                sent={"WhatsApp": 40, "Email": 5} if n == 5 else {"WhatsApp": 3},
                got={"WhatsApp": 20} if n == 5 else {},
                moods={"calm": 2} if n < 6 else {"energetic": 2, "calm": 1},
            )
        )
    return found


def test_what_stands_out_says_what_happened_and_never_why():
    lines = rhythms.stands_out(series(), "all", "1w")
    assert lines == [
        {
            "kind": "listening",
            "text": "You listened most in the week of Mar 9, 2026: 10.0 hours, Low Tide the most.",
        },
        {
            "kind": "riding",
            "text": "Your longest riding streak was 3 weeks in a row with a ride, from the week "
            "of Jan 12, 2026 to the week of Jan 26, 2026: 90.0 km.",
        },
        {
            "kind": "messages",
            "text": "Your busiest week of messages was the week of Feb 9, 2026: 45 sent and 20 "
            "received, 60 of them on WhatsApp.",
        },
        {
            "kind": "mood",
            "text": "Your top mood went from calm (Jan to Feb 2026) to energetic (Feb to Mar 2026).",
        },
    ]
    for line in lines:
        assert not any(word in line["text"] for word in ("because", "due to", "so you", "led"))

    # A month at a time, the most listening is March's; a range is whole months back.
    by_month = rhythms.stands_out(series(), "all", "1m")
    assert by_month[0]["text"] == "You listened most in March 2026: 16.0 hours, Low Tide the most."
    assert rhythms.stands_out(series(), "all", "2w")[0]["text"].startswith(
        "You listened most in the two weeks from Mar 9, 2026: 12.0 hours"
    )


def test_ranges_widen_to_whole_periods_and_say_less_when_there_is_less():
    weeks = series()
    assert len(rhythms.in_range(weeks, "3m", "1w")) == 12  # less than three months held
    long = [
        week(date.fromordinal(date(2025, 1, 6).toordinal() + 7 * n).isoformat()) for n in range(60)
    ]
    assert len(rhythms.in_range(long, "3m", "1w")) == 13
    by_month = rhythms.in_range(long, "3m", "1m")
    # Thirteen weeks back is the first week of December: all of December, then.
    assert by_month[0]["start"] == "2025-12-01" and len(by_month) == 13
    assert all(len(rhythms.in_range(long, "1y", r)) >= 52 for r in rhythms.RESOLUTIONS)

    # Nothing held: nothing to say. One week of riding: said plainly.
    assert rhythms.stands_out(long, "all", "1w") == []
    one = [week("2026-01-05", rides=1, km=12), week("2026-01-12"), week("2026-01-19", rides=1)]
    assert rhythms.stands_out(one, "all", "1w") == [
        {"kind": "riding", "text": "You rode in 2 weeks of this range, never two in a row."}
    ]
    heard = [week("2026-01-05", hours=3, top="Low Tide"), week("2026-01-12", hours=1)]
    assert rhythms.stands_out(heard, "all", "1w")[-1] == {
        "kind": "mood",
        "text": "Moods aren't labelled yet for this range's listening.",
    }


def test_two_week_periods_and_months_match_the_page():
    # Two weeks count from Monday 2001-01-01, so a pair never depends on the range shown.
    assert rhythms.period(date(2026, 3, 16), "2w") == "2026-03-09"
    assert rhythms.period(date(2026, 3, 2), "2w") != rhythms.period(date(2026, 3, 9), "2w")
    # A week is in the month its Thursday is in.
    assert rhythms.period(date(2026, 3, 30), "1m") == "2026-04"
    assert rhythms.period(date(2026, 2, 23), "1m") == "2026-02"
    assert rhythms.period(date(2025, 12, 29), "1w") == "2026-W01"
