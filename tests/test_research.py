"""Research before a reply, with the model faked out. No model, no real data."""

import json
import os
import stat
from datetime import UTC, date, datetime

from proxenos import llm, memory, research, vectors

WORDS = ["conference", "hotel", "slides", "see"]


def fake_embed(texts):
    """A vector per text: how often each of WORDS appears, plus one so none is all zero."""
    return [[t.lower().count(w) + 0.01 for w in WORDS] for t in texts]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def hit(i, text):
    return {
        "id": f"r{i}",
        "source": "email",
        "ts": "2026-07-09T12:00:00Z",
        "who": "Journal",
        "where_": "",
        "title": "",
        "snippet": text,
        "from_me": False,
    }


def test_the_gate_keeps_what_the_reply_depends_on_and_everything_if_it_cannot_say():
    hits = [hit(1, "abstract deadline May 31"), hit(2, "the revision is due by 7th Oct")]
    asked = []

    def ask(prompt, **kwargs):
        asked.append(prompt)
        return {"keep": [2, 9, "1"]}  # out of range and non-numbers are ignored

    kept = research._gate("Chat: when is the paper due?", hits, "Tess", ask)

    assert [h["id"] for h in kept] == ["r2"]
    assert "1. [2026-07-09, email, email] Journal: abstract deadline May 31" in asked[0]

    def muddled(prompt, **kwargs):
        raise llm.ModelError("not the JSON asked for")

    assert research._gate("Chat", hits, "Tess", muddled) == hits
    assert research._gate("Chat", [], "Tess", muddled) == []


def test_a_query_keeps_a_share_for_each_search_that_found_any_best_fused_first():
    agreed = [hit(i, "x") for i in range(1, 16)]
    alone = [hit(20, "only by meaning")]
    lists = {"meaning": alone, "their_meaning": [], "words": agreed, "their_words": agreed}

    fused = research._fused(lists)

    assert len(fused) == research.HITS * 3  # three searches found something
    assert fused[0]["id"] == "r1" and "r20" in [h["id"] for h in fused]
    assert research._fused({"meaning": [], "words": []}) == []


def test_a_searchs_days_are_checked():
    today = date(2026, 11, 1)

    assert research._span("2026-03-01", "2026-03-31", today) == ("2026-03-01", "2026-03-31")
    assert research._span("2026-03-31", "2026-03-01", today) == ("2026-03-01", "2026-03-31")
    assert research._span("March", "2026-02-30", today) == (None, None)  # not days
    assert research._span(" 2026-03-01 ", 20260331, today) == ("2026-03-01", None)
    assert research._span("2027-01-01", None, today) == (None, None)  # nothing after today
    assert research._span(None, "2027-01-01", today) == (None, "2027-01-01")
    assert research._planned({"words": "  ", "after": "2026-01-01"}, today) is None
    assert research._planned("cookbook", today) is None
    assert research._planned({"words": " cookbook  draft ", "before": "2026-10-01"}, today) == (
        "cookbook draft",
        None,
        "2026-10-01",
    )


def test_a_local_model_keeps_a_search_without_days_and_drops_one_without_words():
    answer = {
        "searches": [
            {"words": "retreat"},
            {"after": "2026-01-01"},
            {"words": "dinner", "before": "2026-10-01", "why": "ignored"},
        ]
    }

    held = llm._conform(answer, research._PLAN_SCHEMA)

    assert held == {"searches": [{"words": "retreat"}, {"words": "dinner", "before": "2026-10-01"}]}


def conference_vault(tmp_path, monkeypatch):
    """Mail and a chat about a conference in March, and mail about another in October, indexed
    by words and by meaning, with the fake embedding model answering questions."""
    write_jsonl(
        tmp_path / "raw" / "email" / "me" / "2026-03.jsonl",
        [
            {
                "id": "m1",
                "ts": "2026-03-12T09:00:00Z",
                "subject": "Conference travel",
                "from_name": "Lab",
                "body": "The conference hotel is booked.",
            }
        ],
    )
    write_jsonl(
        tmp_path / "raw" / "email" / "me" / "2026-10.jsonl",
        [
            {
                "id": "m2",
                "ts": "2026-10-05T09:00:00Z",
                "subject": "Conference recap",
                "from_name": "Lab",
                "body": "Slides from the conference are up.",
            }
        ],
    )
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            {
                "id": "w1",
                "ts": "2026-03-14T09:00:00Z",
                "chat_id": "asha",
                "chat_name": "Asha",
                "chat_type": "direct",
                "from_me": False,
                "sender_name": "Asha",
                "text": "see you at the conference",
            }
        ],
    )
    memory.build(tmp_path)
    monkeypatch.setattr(vectors, "DAYS", 100_000)
    monkeypatch.setattr(research, "RECENT_DAYS", 100_000)
    vectors.update(tmp_path, embed=fake_embed)
    monkeypatch.setattr(vectors, "_ollama", fake_embed)
    return tmp_path


def test_a_search_looks_only_between_its_days_and_each_run_leaves_ids_in_the_log(
    tmp_path, monkeypatch
):
    vault = conference_vault(tmp_path, monkeypatch)
    plans = []

    def ask(prompt, *, schema, **kwargs):
        if "searches" in schema["properties"]:
            plans.append(prompt)
            first = [{"words": "conference", "after": "2026-03-31", "before": "2026-03-01"}]
            return {"searches": first if len(plans) == 1 else []}
        return {"keep": [1]}

    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    found, searched = research.matter(
        vault, "Chat: how was the March one?", "Tess", ask, "Asha", now
    )

    assert searched == ["conference (2026-03-01 to 2026-03-31)"]  # the days, put in order
    assert "Today is" in plans[0] and "2026-11-01" in plans[0]
    assert '"conference (2026-03-01 to 2026-03-31)"' in plans[1]
    assert "Slides" not in found  # October's is outside the days

    log = vault / "memory" / "research.jsonl"
    (line,) = log.read_text(encoding="utf-8").splitlines()
    run = json.loads(line)
    (search,) = run["searches"]
    assert (search["words"], search["after"], search["before"]) == (
        "conference",
        "2026-03-01",
        "2026-03-31",
    )
    assert set(search["lists"]) == {"meaning", "their_meaning", "words", "their_words"}
    march = {"email/me/m1", "whatsapp/messages/w1"}
    assert all(set(ranked) <= march for ranked in search["lists"].values())
    assert search["lists"]["meaning"] and search["lists"]["their_words"] == ["whatsapp/messages/w1"]
    assert set(search["fused"]) == march
    assert run["kept"] == search["fused"][:1] and run["at"] == "2026-11-01T12:00:00Z"
    assert "hotel" not in line and "see you" not in line  # ids, never what a record says
    assert os.name == "nt" or stat.S_IMODE(log.stat().st_mode) == 0o600
    assert os.name == "nt" or stat.S_IMODE(log.parent.stat().st_mode) == 0o700


def test_without_the_embedding_model_a_search_goes_on_by_words(tmp_path, monkeypatch):
    vault = conference_vault(tmp_path, monkeypatch)

    def gone(texts):
        raise RuntimeError("the embedding model isn't answering")

    monkeypatch.setattr(vectors, "_ollama", gone)

    lists = research._ranked(vault, "conference", None, "2026-10-01")

    assert lists["meaning"] == [] and [h["id"] for h in lists["words"]] == ["email/me/m2"]
    assert [h["id"] for h in research._search(vault, "conference", None)] == [
        h["id"] for h in memory.search("conference", limit=research.HITS, vault=vault)
    ]


def test_the_log_keeps_its_newer_half_past_its_size(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "LOG_BYTES", 200)

    for n in range(10):
        research._log(tmp_path, {"n": n, "pad": "x" * 30})

    kept = [json.loads(line)["n"] for line in (tmp_path / research.LOG).read_text().splitlines()]
    assert kept == list(range(kept[0], 10)) and len(kept) < 10
