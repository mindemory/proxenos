"""Advisor clone on a synthetic vault with the model faked out. No network, no real data."""

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from twin import llm
from twin.clones import advisor

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
GENERATED = "2026-03-10T12:00:00Z"
NOTES = [
    "observations/whatsapp/2025-12.md",
    "observations/spotify/2026-01.md",
    "observations/slack/lab/2026-02.md",
    "observations/whatsapp/2026-03.md",
]


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r) + "\n" for r in records))


def activity(ts, sport, km, minutes, hr=None, name=None):
    return {
        "id": f"strava:{ts}",
        "ts": ts,
        "name": name,
        "sport_type": sport,
        "distance_m": km * 1000,
        "moving_time_s": minutes * 60,
        "total_elevation_gain_m": 0,
        "average_heartrate": hr,
    }


def play(ts, minutes, artist="Band A", kind="track", show=None, skipped=False, incognito=False):
    return {
        "id": f"play:{ts}:{artist}",
        "ts": ts,
        "kind": kind,
        "track": "Song" if kind == "track" else None,
        "artist": artist if kind == "track" else None,
        "show": show,
        "ms_played": int(minutes * 60000),
        "skipped": skipped,
        "incognito": incognito,
    }


def given(area, text):
    return {
        "id": advisor.suggestion_id(area, text),
        "area": area,
        "pattern": "Earlier pattern.",
        "suggestion": text,
        "why": "Earlier why.",
        "confidence": "medium",
        "evidence": ["tasks"],
    }


DOING = given("training", "Row two easy sessions a week")
NOT_ME = given("sleep", "Stop screens at 11pm")
USEFUL = given("work", "Batch email twice a day")
QUIET = given("time", "Block mornings for writing")
OLD_QUIET = given("learning", "Read one paper a day")
OLD_DOING = given("money", "Review subscriptions monthly")


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    write(vault / "self" / "identity.md", "Goal: finish the PhD by 2027 and row a 2k under 7:00.")
    write(vault / "self" / "routines.md", "Trains early, writes late.")
    write(vault / "self" / "CHANGELOG.md", "## 2026-03-01\n\nInitial build")
    write(vault / "self" / "proposals" / "voice.md", "A proposal not yet accepted.")
    write(vault / "observations" / "whatsapp" / "2025-11.md", "# whatsapp, 2025-11\n\nTOO OLD")
    for path in NOTES:
        write(vault / path, f"# note\n\nSeen in {path}.")

    tasks = [
        {
            "id": "aaaaaaaaaaaa",
            "title": "Submit the travel form",
            "detail": "Prof asked for it.",
            "source": "email",
            "with": "Prof Example",
            "asked_at": "2026-03-08T12:00:00Z",
            "due": "2026-03-12",
            "priority": "high",
            "status": "open",
            "evidence": ["m1@x"],
        },
        {
            "id": "bbbbbbbbbbbb",
            "title": "Get Ben's comments",
            "detail": "",
            "source": "whatsapp",
            "with": None,
            "asked_at": None,
            "due": None,
            "priority": "low",
            "status": "waiting",
            "evidence": [],
        },
    ]
    write(vault / "clones" / "tasks" / "tasks.json", json.dumps({"generated": "x", "tasks": tasks}))

    write_jsonl(
        vault / "raw" / "strava" / "activities" / "2025-11.jsonl",
        [activity("2025-11-05T12:00:00Z", "Run", 10, 60)],
    )
    write_jsonl(
        vault / "raw" / "strava" / "activities" / "2026-02.jsonl",
        [activity("2026-02-25T12:00:00Z", "Run", 7, 45, hr=148, name="Easy")],
    )
    write_jsonl(
        vault / "raw" / "strava" / "activities" / "2026-03.jsonl",
        [
            activity("2026-03-04T12:00:00Z", "Ride", 40, 90),
            activity("2026-03-04T13:00:00Z", "Run", 8, 45, hr=152, name="Tempo"),
        ],
    )
    write_jsonl(
        vault / "raw" / "spotify" / "plays" / "2026-03.jsonl",
        [
            play("2026-03-02T12:00:00Z", 30),
            play("2026-03-03T12:00:00Z", 20, artist="Band B", skipped=True),
            play("2026-03-04T12:00:00Z", 50, kind="episode", show="A Science Show"),
            play("2026-03-05T12:00:00Z", 90, incognito=True),
            play("2026-03-06T12:00:00Z", 0),
        ],
    )

    out = vault / "clones" / "advisor"
    run = {"generated": "x", "suggestions": [DOING, NOT_ME, USEFUL, QUIET]}
    write(out / "2026-02-01.json", json.dumps(run))
    write(out / "2025-10-01.json", json.dumps({"suggestions": [OLD_QUIET, OLD_DOING]}))
    write(out / "notes.json", "not a run")
    feedback = [
        {"suggestion_id": DOING["id"], "action": "doing", "ts": ago(days=20)},
        {"suggestion_id": NOT_ME["id"], "action": "useful", "ts": ago(days=30)},
        {"suggestion_id": NOT_ME["id"], "action": "not_me", "ts": ago(days=25)},
        {"suggestion_id": USEFUL["id"], "action": "useful", "ts": ago(days=25)},
        {"suggestion_id": OLD_DOING["id"], "action": "doing", "ts": ago(days=120)},
        {"suggestion_id": QUIET["id"], "action": "open", "ts": ago(days=1)},  # not a reaction
    ]
    lines = [json.dumps(f) for f in feedback] + ['{"suggestion_id": "x", "act']
    write(out / "feedback.jsonl", "\n".join(lines) + "\n")
    return vault


class FakeModel:
    def __init__(self):
        self.calls = []
        self.suggestions = []

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=32000):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        return {"suggestions": self.suggestions}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.delenv("TWIN_NAME", raising=False)


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def suggestion(area, text, evidence, confidence="medium"):
    return {
        "area": area,
        "pattern": f" Pattern for {text}. ",
        "suggestion": text,
        "why": "Because of their goal.",
        "confidence": confidence,
        "evidence": evidence,
    }


@pytest.mark.parametrize("files", [{}, {"CHANGELOG.md": "## 2026-03-01"}, {"identity.md": " \n"}])
def test_without_a_self_model_it_stops_and_says_how_to_build_one(tmp_path, model, files):
    vault = tmp_path / "vault"
    (vault / "self").mkdir(parents=True)
    for name, text in files.items():
        write(vault / "self" / name, text)

    with pytest.raises(SystemExit, match="`twin master` builds it"):
        advisor.advise(vault, now=NOW)
    assert model.calls == []


def test_with_nothing_to_go_on_it_stops_before_the_model(tmp_path, model):
    vault = tmp_path / "vault"
    write(vault / "self" / "identity.md", "Someone.")

    with pytest.raises(SystemExit, match="nothing to go on"):
        advisor.advise(vault, now=NOW)
    assert model.calls == []


def test_the_model_gets_the_self_model_three_months_of_evidence_and_earlier_advice(tmp_path, model):
    vault = make_vault(tmp_path)

    advisor.advise(vault, now=NOW)

    [call] = model.calls
    prompt, system = call["prompt"], call["system"]
    assert call["effort"] == "high"
    assert "Nothing generic" in system
    assert "Nothing medical" in system and "No moralizing" in system and "not_me" in system

    # The whole self-model, identity first, but not its changelog or pending proposals.
    assert prompt.index("<identity>\nGoal: finish the PhD") < prompt.index("<routines>")
    assert "Initial build" not in prompt and "not yet accepted" not in prompt
    # Notes on months the window touches (it starts 2025-12-09), oldest first.
    positions = [prompt.index(f'<note path="{path}">') for path in NOTES]
    assert positions == sorted(positions) and "TOO OLD" not in prompt
    assert "Seen in observations/slack/lab/2026-02.md." in prompt

    assert '# Task list, kept by the twin from their recent messages (cite as "tasks")' in prompt
    assert "1 open, 1 waiting, 0 done lately." in prompt
    assert (
        "- [open, high, due 2026-03-12] Submit the travel form. Prof asked for it. "
        "(email, with Prof Example, asked 2026-03-0"
    ) in prompt
    assert "- [waiting, low] Get Ben's comments. (whatsapp)" in prompt
    assert '# Strava, worked out from their activities (cite as "strava")' in prompt
    assert "3 activities: 3.0 h moving, 55 km." in prompt
    assert '# Spotify, worked out from their plays (cite as "spotify")' in prompt

    history = prompt.split("# Earlier advice and how they took it")[1]
    doing, not_me, useful, quiet = history.strip().split("\n\n")
    assert doing.startswith("They're doing these. Follow up")
    assert "Row two easy sessions a week (given 2026-02-01)" in doing
    assert "[money] Review subscriptions monthly (given 2025-10-01)" in doing  # however old
    assert not_me.startswith("They marked these not them") and "Stop screens at 11pm" in not_me
    assert useful.startswith("They found these useful") and "Batch email twice a day" in useful
    assert quiet.startswith("No reaction yet") and "Block mornings for writing" in quiet
    assert "Read one paper a day" not in prompt  # unreacted, and from before the window

    items = call["schema"]["properties"]["suggestions"]["items"]
    assert items["properties"]["evidence"]["items"]["enum"] == [
        *NOTES,
        "tasks",
        "strava",
        "spotify",
    ]
    assert items["properties"]["area"]["enum"] == list(advisor.AREAS)
    assert items["properties"]["confidence"]["enum"] == ["high", "medium", "low"]


def test_missing_sources_are_said_to_be_missing_and_not_offered_as_evidence(tmp_path, model):
    vault = tmp_path / "vault"
    write(vault / "self" / "identity.md", "Someone.")
    write(vault / "observations" / "whatsapp" / "2026-03.md", "A note.")

    advisor.advise(vault, now=NOW)

    [call] = model.calls
    assert (
        "# Strava, worked out from their activities\n\nNone on record for this window."
        in (call["prompt"])
    )
    assert "No earlier advice yet." in call["prompt"]
    evidence = call["schema"]["properties"]["suggestions"]["items"]["properties"]["evidence"]
    assert evidence["items"]["enum"] == ["observations/whatsapp/2026-03.md"]


def test_suggestions_are_saved_in_the_contract_shape(tmp_path, model):
    vault = make_vault(tmp_path)
    text = "Do the long row on Saturday instead of Wednesday"
    model.suggestions = [
        suggestion("training", text, ["strava", "observations/whatsapp/2026-03.md"], "high"),
        suggestion("sleep", NOT_ME["suggestion"], ["strava"]),  # marked not_me before
        suggestion("work", "Something from too long ago", ["observations/whatsapp/2025-11.md"]),
        suggestion("tasks", "Answer the travel form today", ["tasks", "made up", "tasks"]),
        suggestion("training", f" {text} ", ["strava"]),  # the same one again
    ]

    stats = advisor.advise(vault, now=NOW)

    assert stats == {"suggestions": 2}
    path = vault / "clones" / "advisor" / f"{NOW.astimezone():%Y-%m-%d}.json"
    saved = json.loads(path.read_text())
    assert saved["generated"] == GENERATED
    first, second = saved["suggestions"]
    assert first == {
        "id": hashlib.sha1(f"training{text}".encode()).hexdigest()[:12],
        "area": "training",
        "pattern": f"Pattern for {text}.",
        "suggestion": text,
        "why": "Because of their goal.",
        "confidence": "high",
        "evidence": ["strava", "observations/whatsapp/2026-03.md"],
    }
    assert second["area"] == "tasks" and second["evidence"] == ["tasks"]
    assert not list(path.parent.glob("*.tmp"))


def test_strava_and_spotify_are_summarized_over_the_window(tmp_path):
    vault = make_vault(tmp_path)
    since = NOW - timedelta(days=91)

    strava = advisor.strava_summary(vault, since, NOW)
    assert strava.startswith("3 activities: 3.0 h moving, 55 km.\n")
    assert "By sport: Run 2 (15 km, 1.5 h, average HR 150); Ride 1 (40 km, 1.5 h)." in strava
    assert "02-23 1 (0.8 h), 03-02 2 (2.2 h), 03-09 0 (0.0 h)." in strava
    assert "12-08 0 (0.0 h), " in strava  # the window's first week, partial
    assert "Longest gap between activities: 7 days, 02-25 to 03-04." in strava
    assert "Last activity 6 day(s) ago." in strava
    assert "Longest sessions: 03-04 Ride, 40.0 km in 90 min; " in strava
    assert "02-25 Run 'Easy', 7.0 km in 45 min; 03-04 Run 'Tempo', 8.0 km in 45 min." in strava

    spotify = advisor.spotify_summary(vault, since, NOW)
    lines = spotify.splitlines()
    assert lines[0] == "3 plays, 1.7 h, 33% skipped; 50% of the time podcasts and audiobooks."
    assert lines[1].startswith("Hours per week, by the Monday it starts")
    assert "03-02 1.7, 03-09 0.0." in lines[1]
    assert lines[2].startswith("Listening by hour of day, local (minutes): 00h ")
    assert lines[3].startswith("Between midnight and 5am: ")
    assert lines[-3:] == [
        "  A Science Show (episode): 50",
        "  Band A (artist): 30",
        "  Band B (artist): 20",
    ]

    assert advisor.strava_summary(vault, NOW - timedelta(days=1), NOW) == ""
    assert advisor.spotify_summary(vault, NOW - timedelta(days=1), NOW) == ""


def test_the_command_line_reads_months():
    parser = argparse.ArgumentParser()
    advisor.add_arguments(parser)
    assert parser.parse_args([]).months == 3
    assert parser.parse_args(["--months", "6"]).months == 6
