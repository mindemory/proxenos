"""The day's journal on a synthetic vault, with the model faked out. No network, no real data."""

import argparse
import json
import os
import stat
import time
from datetime import UTC, date, datetime

import pytest

from proxenos import llm, plain
from proxenos.clones import journal

NOW = datetime(2026, 3, 10, 20, 0, tzinfo=UTC)
DAY = date(2026, 3, 10)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def jsonl(path, records, torn=False):
    """Records a line each; with torn, a half-written last line, as the page's files can have."""
    write(path, "".join(json.dumps(r) + "\n" for r in records) + ("{torn\n" if torn else ""))


def wa(n, text, me):
    return {
        "id": f"asha/{n}", "ts": f"2026-03-10T15:0{n}:00Z", "chat_id": "asha@s.whatsapp.net",
        "chat_name": "Asha", "chat_type": "direct", "from_me": me, "sender_id": None if me else "1",
        "sender_name": None if me else "Asha", "kind": "text", "wa_type": 0, "text": text, "caption": None,
    }  # fmt: skip


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    tasks = [
        {"id": "t1", "title": "Send Asha the slides", "status": "done", "priority": "medium"},
        {"id": "t2", "title": "Hear back from Ben", "status": "waiting", "priority": "low", "with": "Ben"},
        {"id": "t3", "title": "Pay the clinic", "status": "open", "priority": "high", "due": "2026-03-11"},
        {"id": "t4", "title": "Someday tidy the shed", "status": "open", "priority": "low", "due": None},
    ]  # fmt: skip
    write(vault / "clones" / "tasks" / "tasks.json", json.dumps({"tasks": tasks}))
    closed = {
        "t1": {"title": "Send Asha the slides", "action": None, "closed_at": "2026-03-10T16:00:00Z"}
    }
    write(vault / "clones" / "tasks" / "closed.json", json.dumps(closed))
    draft = '---\nid: reply-1\ntitle: "Reply to Ben"\nto: "Ben"\nstatus: sent\ncreated: 2026-03-09T09:00:00Z\n---\n\nhi\n'
    write(vault / "clones" / "drafts" / "reply-1.md", draft)
    waiting = '---\nid: email-2\ntitle: "Ask the clinic for the bill"\nto: "Clinic"\nstatus: draft\ncreated: 2026-03-10T09:00:00Z\n---\n\nHi\n'
    write(vault / "clones" / "drafts" / "email-2.md", waiting)
    jsonl(
        vault / "clones" / "drafts" / "feedback.jsonl",
        [{"draft_id": "reply-1", "action": "sent", "ts": "2026-03-10T17:00:00Z"}],
        torn=True,
    )
    jsonl(
        vault / "state" / "told.jsonl",
        [{"at": "2026-03-10T18:00:00Z", "text": "Not going to Friday's party.", "always": False}],
        torn=True,
    )
    jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa(1, "can you send the slides?", False),
            wa(2, "sure, sending now", True),
            wa(3, "sent!", True),
        ],
    )
    event = {"id": "e1", "start": "2026-03-11T15:00:00Z", "summary": "Lab meeting"}
    jsonl(vault / "raw" / "calendar" / "me-uni-edu" / "2026-03.jsonl", [event])
    return vault


def test_the_day_is_written_from_what_the_vault_already_holds(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    asked = []
    systems = []

    def ask(prompt, *, system=None, schema=None, **kw):
        asked.append(prompt)
        systems.append(system)
        return {
            "brief": "You sent the slides.  Tomorrow is the lab meeting.",
            "next_up": ["Pay the clinic"] * 4,
        }

    monkeypatch.setattr(llm, "ask", ask)
    stats = journal.write(vault, DAY, NOW)

    path = vault / "clones" / "journal" / "2026-03-10.json"
    entry = json.loads(path.read_text())
    assert os.name == "nt" or stat.S_IMODE(path.stat().st_mode) == 0o600
    sections = entry["sections"]
    assert sections["done"] == ["Done: Send Asha the slides", "Sent: Reply to Ben to Ben"]
    assert sections["said"] == [
        "Wrote in WhatsApp, Asha (direct chat): 2 messages",
        "Told Proxenos: Not going to Friday's party.",
    ]
    assert sections["waiting"] == ["Waiting: Hear back from Ben (with Ben)"]
    nxt = sections["next"]
    assert nxt[0].startswith("Calendar ") and nxt[0].endswith("Lab meeting")
    assert "Task: Pay the clinic (due 2026-03-11)" in nxt and not any("shed" in n for n in nxt)
    assert "Drafts to send: 1, the newest: Ask the clinic for the bill" in nxt
    assert entry["brief"] == "You sent the slides. Tomorrow is the lab meeting."
    assert entry["next_up"] == ["Pay the clinic"] * 3
    # A brief for the user to read, so in plain language, after what it may and may not say.
    assert systems[0].endswith(plain.rules("the person", "the brief and next_up"))
    assert "no praise, no advice beyond what they show" in systems[0]
    assert "## done\n- Done: Send Asha the slides" in asked[0]
    assert stats["briefs"] == 1 and stats["done lines"] == 2


def test_without_a_model_the_lists_stand_alone(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("no model is set up"))
    monkeypatch.setattr(llm, "configured", lambda: False)
    assert journal.write(vault, DAY, NOW)["briefs"] == 0


def test_the_command_reads_a_date_or_today(tmp_path, monkeypatch):
    days = []
    monkeypatch.setattr(journal, "write", lambda vault, day=None: days.append(day) or {})
    journal.run(tmp_path, argparse.Namespace(date="2026-03-09"))
    journal.run(tmp_path, argparse.Namespace(date=None))
    assert days == [date(2026, 3, 9), None]
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        journal.run(tmp_path, argparse.Namespace(date="yesterday"))


@pytest.fixture
def new_york(monkeypatch):
    """This process in a time zone whose clocks go back an hour on 2026-11-01."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="the time zone is set through tzset")
def test_a_day_the_clocks_change_runs_to_its_own_midnight(tmp_path, new_york):
    vault = tmp_path / "vault"
    msg = wa(1, "ok, see you", True) | {"ts": "2026-11-02T04:30:00Z"}  # 23:30 on Nov 1, EST
    jsonl(vault / "raw" / "whatsapp" / "messages" / "2026-11.jsonl", [msg])
    events = [
        {"id": "e1", "start": "2026-11-01T22:00:00Z", "summary": "Dinner tonight"},
        {"id": "e2", "start": "2026-11-02T15:00:00Z", "summary": "Lab meeting"},
    ]
    jsonl(vault / "raw" / "calendar" / "me-uni-edu" / "2026-11.jsonl", events)

    lines = journal.lines(vault, date(2026, 11, 1))

    assert lines["said"] == ["Wrote in WhatsApp, Asha (direct chat): 1 message"]
    assert [line for line in lines["next"] if "Calendar" in line] == [
        "Calendar Mon Nov 02 10:00: Lab meeting"
    ]
