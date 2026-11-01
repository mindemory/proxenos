"""Research before a reply, with the model faked out. No model, no real data."""

import json
import os
import re
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


def test_a_plan_may_leave_out_what_to_open_and_opens_only_records_found():
    schema = research._PLAN_SCHEMA
    assert llm._conform({"searches": []}, schema) == {"searches": []}
    assert llm._conform({"searches": [], "open": "3"}, schema) == {"searches": []}
    held = llm._conform({"searches": [], "open": [2, "3", 1.5, True]}, schema)
    assert held == {"searches": [], "open": [2]}  # a local model's stray items go, the rest stay

    hits = [hit(i, "x") for i in range(1, 6)]
    asked = [5, 9, 0, "2", 5, 1, 2, 3, 4]  # out of range, not a number, twice, opened before
    chosen = research._chosen(asked, hits, {"r1": []})

    assert [h["id"] for h in chosen] == ["r5", "r2", "r3"]  # OPENS a round
    assert research._chosen(None, hits, {}) == []


def message(i, text, target=False, mine=False):
    return {
        "id": f"c{i}",
        "ts": f"2026-10-0{i}T09:30:00Z",
        "who": "Ravi",
        "title": "",
        "text": text,
        "from_me": mine,
        "target": target,
    }


def test_an_opened_record_shows_whats_around_it_its_own_words_first():
    rows = [
        message(1, "lovely to meet"),
        message(2, "which draft?", mine=True),
        message(3, "the second one, by the 7th", target=True),
        message(4, "ok", mine=True),
        message(5, "thanks"),
    ]

    assert research._around(rows, "Tess", 1, 800) == [
        "  [2026-10-02 09:30] Tess: which draft?",
        "> [2026-10-03 09:30] Ravi: the second one, by the 7th",
        "  [2026-10-04 09:30] Tess: ok",
    ]

    long = [message(1, "w " * 2000), message(2, "x " * 2000, target=True), message(3, "y " * 2000)]
    lines = research._around(long, "Tess", 3, 600)
    assert sum(map(len, lines)) <= 600
    assert lines[1].count("x") > lines[0].count("w") > 10  # its own words get the most
    (alone,) = research._around([message(1, "x " * 2000, target=True)], "Tess", 3, 600)
    assert len(alone) == 600
    assert research._around([message(1, "no target")], "Tess", 3, 600) == []


def editor_vault(tmp_path):
    """A chat with an editor where "due by the 7th" says nothing without the question before
    it, and another chat that shares the word."""
    chat = [
        ("2026-10-01T09:00:00Z", "ravi", False, "lovely to meet at the fair"),
        ("2026-10-02T09:00:00Z", "ravi", True, "which cookbook draft comes first?"),
        ("2026-10-02T10:00:00Z", "ravi", False, "the second one, due by the 7th"),
        ("2026-10-03T09:00:00Z", "ravi", True, "got it, will send"),
        ("2026-10-04T09:00:00Z", "ravi", False, "thanks!"),
        ("2026-10-05T09:00:00Z", "asha", False, "rent is due friday"),
    ]
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-10.jsonl",
        [
            {
                "id": f"c{i}",
                "ts": ts,
                "chat_id": name,
                "chat_name": name.title(),
                "chat_type": "direct",
                "from_me": mine,
                "sender_name": None if mine else name.title(),
                "text": text,
            }
            for i, (ts, name, mine, text) in enumerate(chat, 1)
        ],
    )
    memory.build(tmp_path)
    return tmp_path


def test_a_round_opens_what_it_found_reads_around_it_and_the_reply_gets_a_few_lines(tmp_path):
    vault = editor_vault(tmp_path)
    plans, gated = [], []
    answer = re.compile(r"(\d+)\. \[[^]]*\] Ravi: the second one")

    def ask(prompt, *, schema, **kwargs):
        if "keep" in schema["properties"]:
            gated.append(prompt)
            return {"keep": [int(n) for n in answer.findall(prompt)]}
        plans.append(prompt)
        if len(plans) == 1:
            return {"searches": [{"words": "due"}]}
        if len(plans) == 2:  # the editor's answer, twice, and a number no record has
            (n,) = answer.findall(prompt)
            return {"searches": [], "open": [int(n), int(n), 99]}
        return {"searches": []}  # it read what was opened, and needs nothing more

    found, _ = research.matter(vault, "Chat: is the draft on track?", "Tess", ask)

    assert len(plans) == 3  # searched, opened, then read what was opened
    (fence,) = set(re.findall(r"</?(untrusted-[0-9a-f]{8})>", plans[2]))
    shown = plans[2].split(f"<{fence}>")[1].split(f"</{fence}>")[0]  # all of it inside the tag
    opened = shown.split("opened, with what's around it")[1].split("Search")[0]
    for line in (
        "  [2026-10-01 09:00] Ravi: lovely to meet at the fair",
        "  [2026-10-02 09:00] Tess: which cookbook draft comes first?",
        "> [2026-10-02 10:00] Ravi: the second one, due by the 7th",
        "  [2026-10-04 09:00] Ravi: thanks!",
    ):
        assert line in opened
    assert "rent" not in opened  # another chat's
    assert "  > [2026-10-02 10:00] Ravi: the second one" in gated[0] and f"<{fence}>" in gated[0]

    lines = found.splitlines()
    assert lines[0] == "- [2026-10-02, whatsapp, Ravi] Ravi: the second one, due by the 7th"
    assert "    [2026-10-02 09:00] Tess: which cookbook draft comes first?" in lines
    assert "    [2026-10-03 09:00] Tess: got it, will send" in lines
    assert "fair" not in found and "thanks!" not in found  # a few lines, not the whole chat
    assert fence not in found  # the caller puts what comes back inside its own tag

    run = json.loads((vault / research.LOG).read_text(encoding="utf-8"))
    assert run["opened"] == ["whatsapp/messages/c3"] and run["kept"] == ["whatsapp/messages/c3"]
    assert "cookbook" not in json.dumps(run)  # ids, never what a record says
