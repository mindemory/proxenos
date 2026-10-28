"""Triggered recall on a synthetic vault: no model, no real data."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from twin import cli, memory
from twin.clones import recall

NOW = datetime(2025, 3, 10, 9, 0, tzinfo=UTC)  # a Monday


@pytest.fixture(autouse=True)
def small_corpus(monkeypatch):
    # bm25 scores grow with the size of the corpus; a handful of rows can't reach the real bar.
    monkeypatch.setattr(recall, "MIN_SCORE", -1.0)


def write_month(vault, folder, month, records):
    path = vault / folder / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def write_json(vault, rel, data):
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def message(n, text, chat="Lab chat", sender="Dana Whitfield", day=1, month="2025-01"):
    return {
        "id": f"{month}-{day}-{n}",
        "ts": f"{month}-{day:02d}T10:{n:02d}:00Z",
        "chat_id": chat,
        "chat_name": chat,
        "sender_name": sender,
        "from_me": False,
        "text": text,
    }


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    write_month(
        v,
        "raw/whatsapp/messages",
        "2025-01",
        [
            message(1, "The lichen symposium needs a keynote speaker"),
            message(2, "I could ask about the lichen symposium budget"),
            message(3, "Unrelated chatter about lunch", sender="Tobias Okafor"),
        ],
    )
    write_month(
        v,
        "raw/email/me",
        "2024-11",
        [
            {
                "id": "e1",
                "ts": "2024-11-02T08:00:00Z",
                "subject": "Reimbursement forms",
                "from_name": "Priya Raman",
                "to": ["me@example.org"],
                "body_new": "Attached the forms for the quarterly reimbursement.",
                "from_me": False,
            },
            {
                "id": "e2",
                "ts": "2025-02-02T08:00:00Z",
                "subject": "Sequencing run",
                "from_name": "Priya Raman",
                "body_new": "The nanopore sequencing run finished.",
                "from_me": False,
            },
        ],
    )
    write_month(
        v,
        "raw/chrome/visits",
        "2025-02",
        [
            {
                "id": "c",
                "ts": "2025-02-03T00:00:00Z",
                "title": "Lichen symposium schedule",
                "url": "https://a.test/",
            }
        ],
    )
    write_month(
        v,
        "raw/calendar/work",
        "2025-02",
        [
            {
                "id": "old",
                "ts": "2025-02-01T15:00:00Z",
                "summary": "Lichen symposium planning",
                "status": "CONFIRMED",
            }
        ],
    )
    # Events: one tomorrow with guests, one in a week, a cancelled one, an all-day one today, and
    # a weekly one that began last year and meets on Tuesdays.
    write_month(
        v,
        "raw/calendar/work",
        "2025-03",
        [
            {
                "id": "ev1",
                "ts": "2025-03-11T15:00:00Z",
                "summary": "Lichen symposium kickoff",
                "status": "CONFIRMED",
                "guests": [{"name": "Dana Whitfield", "email": "d@example.org"}],
            },
            {"id": "ev2", "ts": "2025-03-20T15:00:00Z", "summary": "Lichen symposium dinner"},
            {
                "id": "ev3",
                "ts": "2025-03-11T16:00:00Z",
                "summary": "Lichen symposium cancelled talk",
                "status": "CANCELLED",
            },
            {
                "id": "ev4",
                "ts": "2025-03-10T00:00:00Z",
                "summary": "Sequencing day",
                "all_day": True,
            },
        ],
    )
    write_month(
        v,
        "raw/calendar/work",
        "2024-06",
        [
            {
                "id": "weekly",
                "ts": "2024-06-04T13:00:00Z",
                "summary": "Reimbursement office hours",
                "rrule": "FREQ=WEEKLY;BYDAY=TU",
            }
        ],
    )
    write_json(
        v,
        "clones/tasks/tasks.json",
        {
            "generated": "2025-03-09T00:00:00Z",
            "tasks": [
                {"id": "t1", "title": "Send Dana the lichen symposium budget", "status": "open",
                 "with": "Dana Whitfield", "due": "2025-03-12"},
                {"id": "t2", "title": "Finish the nanopore sequencing report", "status": "done"},
                {"id": "t3", "title": "Chase the reimbursement forms", "status": "waiting"},
                {"id": "t4", "title": "Order lichen symposium posters", "status": "open"},
                {"id": "t5", "title": "Plan the zzzunmatchable thing", "status": "open"},
            ],
        },
    )  # fmt: skip
    # t4 was closed on the page after the task list was last written.
    (v / "clones/tasks/feedback.jsonl").write_text(
        json.dumps({"task_id": "t4", "action": "not_mine", "ts": "2025-03-09T12:00:00Z"}) + "\n"
    )
    write_month(
        v,
        "tracker/items",
        "2025-03",
        [
            {"id": "old", "batch": "b1", "ts": "2025-03-01T00:00:00Z", "title": "Lichen atlas", "score": 0.9},
            {"id": "f1", "batch": "b2", "ts": "2025-03-09T00:00:00Z", "title": "Nanopore sequencing of lichen",
             "score": 0.8, "authors": ["Priya Raman"], "published": "2025-03-08"},
            {"id": "f2", "batch": "b2", "ts": "2025-03-09T00:00:01Z", "title": "Reimbursement policy changes",
             "score": 0.95},
            {"id": "f3", "batch": "b2", "ts": "2025-03-09T00:00:02Z", "title": "Lichen symposium recap",
             "score": 0.99},
            {"id": "f4", "batch": "b2", "ts": "2025-03-09T00:00:03Z", "title": "Quantum widgets", "score": 0.5},
        ],
    )  # fmt: skip
    (v / "tracker/feedback.jsonl").write_text(
        json.dumps({"item_id": "f3", "action": "not_me", "ts": "2025-03-09T01:00:00Z"}) + "\n"
    )
    write_json(
        v,
        "clones/network/people.json",
        {
            "people": [
                {"id": "p-dana", "name": "Dana Whitfield", "interactions": 400, "last_seen": "2025-03-01T00:00:00Z"},
                {"id": "p-priya", "name": "Priya Raman", "interactions": 100, "last_seen": "2025-03-05T00:00:00Z"},
                {"id": "p-old", "name": "Tobias Okafor", "interactions": 100, "last_seen": "2015-01-01T00:00:00Z"},
                {"id": "p-none", "name": "Nobody Atall", "interactions": 900, "last_seen": "2025-03-09T00:00:00Z"},
            ]
        },
    )  # fmt: skip
    memory.build(v)
    return v


def today(vault):
    return json.loads((vault / "clones/recall/today.json").read_text())


def triggers(vault, kind):
    return {t["id"]: t for t in today(vault)["triggers"] if t["kind"] == kind}


def test_it_writes_today_and_people(vault):
    stats = recall.recall(vault, now=NOW)

    data = today(vault)
    assert data["generated"] == "2025-03-10T09:00:00Z"
    assert {t["kind"] for t in data["triggers"]} == {"event", "task", "feed", "person"}
    assert set(data["triggers"][0]) == {"kind", "id", "title", "when", "memories"}
    assert stats["triggers_with_memories"] == len(data["triggers"])
    assert stats["memories"] == sum(len(t["memories"]) for t in data["triggers"])
    people = json.loads((vault / "clones/recall/people.json").read_text())
    assert stats["people"] == len(people)


def test_a_memory_is_a_search_hit_with_marks(vault):
    recall.recall(vault, now=NOW)

    [memory_] = [m for m in triggers(vault, "task")["t1"]["memories"] if m["source"] == "whatsapp"]
    assert memory_["id"] in {"whatsapp/messages/2025-01-1-1", "whatsapp/messages/2025-01-1-2"}
    assert set(memory_) == {
        "id",
        "source",
        "stream",
        "ts",
        "who",
        "where_",
        "title",
        "snippet",
        "score",
        "from_me",
    }
    assert memory.MARK_START in memory_["snippet"]


def test_events_in_the_next_48_hours_recall_past_conversations(vault):
    recall.recall(vault, now=NOW)

    events = triggers(vault, "event")
    assert set(events) == {"ev1", "ev4", "weekly"}  # not next week's, not the cancelled one
    kickoff = events["ev1"]
    assert (kickoff["title"], kickoff["when"]) == (
        "Lichen symposium kickoff",
        "2025-03-11T15:00:00Z",
    )
    sources = {m["source"] for m in kickoff["memories"]}
    assert "whatsapp" in sources
    assert sources.isdisjoint({"calendar", "chrome"})  # no other calendar entries, no browsing
    assert (
        len([m for m in kickoff["memories"] if m["where_"] == "Lab chat"]) == 1
    )  # one per chat and day
    assert events["weekly"]["when"] == "2025-03-11T13:00:00Z"
    assert events["weekly"]["memories"][0]["source"] == "email"


def test_open_tasks_minus_the_ones_closed_on_the_page(vault):
    recall.recall(vault, now=NOW)

    tasks = triggers(vault, "task")
    assert set(tasks) == {"t1"}  # t2 done, t3 waiting, t4 closed since, t5 finds nothing
    assert tasks["t1"]["when"] == "2025-03-12"
    assert tasks["t1"]["title"] == "Send Dana the lichen symposium budget"


def test_the_newest_batch_of_the_feed_minus_what_i_rejected(vault):
    recall.recall(vault, now=NOW)

    feed = triggers(vault, "feed")
    assert set(feed) == {"f1", "f2"}  # f3 was marked not me, f4 matches nothing, "old" isn't newest
    assert feed["f1"]["when"] == "2025-03-08"
    assert {m["source"] for m in feed["f1"]["memories"]} >= {"email"}  # by its author, Priya


def test_people_are_found_by_name_newest_first_and_the_forgotten_ranked_last(vault):
    recall.recall(vault, now=NOW)

    people = triggers(vault, "person")
    assert set(people) == {"p-dana", "p-priya", "p-old"}  # p-none is in no record
    dana = people["p-dana"]["memories"]
    assert [m["ts"] for m in dana] == sorted((m["ts"] for m in dana), reverse=True)
    assert dana[0]["who"].startswith("Dana Whitfield")
    assert people["p-dana"]["when"] == "2025-03-01T00:00:00Z"

    by_person = json.loads((vault / "clones/recall/people.json").read_text())
    assert set(by_person) == {"p-dana", "p-priya", "p-old"}
    assert len(by_person["p-dana"]) <= recall.PER_PERSON

    # Nobody, Dana and Priya count most; Tobias was last seen ten years ago.
    recall.recall(vault, now=NOW, people=3)
    assert set(json.loads((vault / "clones/recall/people.json").read_text())) == {
        "p-dana",
        "p-priya",
    }


def test_a_poor_match_is_no_memory(vault, monkeypatch):
    monkeypatch.setattr(recall, "MIN_SCORE", -1000.0)

    stats = recall.recall(vault, now=NOW)

    kinds = {t["kind"] for t in today(vault)["triggers"]}
    assert kinds == {"person"}  # people have no score to fall short of
    assert stats["triggers_with_memories"] == len(today(vault)["triggers"])


def test_words_that_are_everywhere_are_not_searched(vault, monkeypatch):
    monkeypatch.setattr(recall, "MAX_DOCS", 0)

    recall.recall(vault, now=NOW)

    assert {t["kind"] for t in today(vault)["triggers"]} == {"person"}


def test_a_memory_per_trigger_is_capped(vault):
    recall.recall(vault, now=NOW)

    assert all(len(t["memories"]) <= recall.PER_TRIGGER for t in today(vault)["triggers"])


def test_it_needs_the_index(tmp_path):
    with pytest.raises(SystemExit, match="twin index"):
        recall.recall(tmp_path, now=NOW)


def test_an_empty_vault_recalls_nothing(tmp_path):
    memory.build(tmp_path)

    stats = recall.recall(tmp_path, now=NOW)

    assert stats == {"triggers": 0, "triggers_with_memories": 0, "memories": 0, "people": 0}
    assert today(tmp_path) == {"generated": "2025-03-10T09:00:00Z", "triggers": []}


def test_the_clone_runs_from_the_command_line(vault, monkeypatch, capsys):
    monkeypatch.setenv("TWIN_VAULT", str(vault))

    cli.main(["clone", "recall"])

    line = capsys.readouterr().out.strip()
    assert line.startswith("recall: ") and "memories" in line
    assert (vault / "clones/recall/today.json").exists()


@pytest.mark.parametrize(
    ("rule", "start", "expected"),
    [
        # The window is Monday 09:00 to Wednesday 09:00, so the 10th at 08:00 has already passed.
        ("FREQ=DAILY;INTERVAL=2", "2025-03-06T08:00:00Z", ["2025-03-12T08:00:00Z"]),
        ("FREQ=DAILY", "2025-03-06T08:00:00Z", ["2025-03-11T08:00:00Z", "2025-03-12T08:00:00Z"]),
        # Weekly on Tuesdays; every second week counts from the start's week.
        ("FREQ=WEEKLY;BYDAY=TU", "2024-01-02T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU", "2025-02-18T08:00:00Z", []),
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU", "2025-02-25T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=WEEKLY", "2025-03-05T08:00:00Z", ["2025-03-12T08:00:00Z"]),  # the start's weekday
        # It stops: UNTIL (a date takes in its whole day) and COUNT.
        ("FREQ=DAILY;UNTIL=20250301T000000Z", "2025-02-01T08:00:00Z", []),
        ("FREQ=DAILY;UNTIL=20250311", "2025-03-01T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=DAILY;COUNT=6", "2025-03-06T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=DAILY;COUNT=5", "2025-03-06T08:00:00Z", []),
        # Monthly: the 11th, the second Tuesday, the first Tuesday, the last day.
        ("FREQ=MONTHLY", "2024-12-11T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=MONTHLY;BYDAY=2TU", "2024-12-10T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=MONTHLY;BYDAY=1TU", "2024-12-03T08:00:00Z", []),
        ("FREQ=MONTHLY;BYMONTHDAY=-1", "2024-12-31T08:00:00Z", []),
        ("FREQ=MONTHLY;INTERVAL=2", "2025-01-11T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=YEARLY", "2023-03-11T08:00:00Z", ["2025-03-11T08:00:00Z"]),
        ("FREQ=YEARLY;INTERVAL=2", "2024-03-11T08:00:00Z", []),
        # Not understood, or wrong: no occurrences rather than a crash.
        ("FREQ=HOURLY", "2025-03-06T08:00:00Z", []),
        ("FREQ=DAILY;INTERVAL=x", "2025-03-06T08:00:00Z", []),
        ("nonsense", "2025-03-06T08:00:00Z", []),
    ],
)
def test_repeat_rules(rule, start, expected):
    begin = datetime.fromisoformat(start)

    found = recall._repeats(rule, begin, NOW, NOW + recall.WINDOW, date(2025, 3, 10), False)

    assert [recall._iso(f) for f in found] == expected


def test_a_repeating_event_never_starts_before_its_first_time():
    start = datetime(2025, 3, 11, 8, 0, tzinfo=UTC)

    found = recall._repeats("FREQ=DAILY", start, NOW, NOW + recall.WINDOW, date(2025, 3, 10), False)

    assert found == [start, start + timedelta(days=1)]


def test_words_drop_filler_and_keep_the_order():
    assert recall._words("Send Dana the 2025 lichen budget, and the Lichen map for Dana") == [
        "send",
        "dana",
        "lichen",
        "budget",
        "map",
    ]
    assert recall._words("A to Z") == []
    assert len(recall._words(" ".join(f"word{i}" for i in range(50)))) == recall.MAX_WORDS
