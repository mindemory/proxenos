"""Tasks clone on a synthetic vault with the model faked out. No network, no real data."""

import argparse
import hashlib
import itertools
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import llm
from proxenos.clones import tasks

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
GENERATED = "2026-03-10T12:00:00Z"
CONTRACT = ["id", "title", "detail", "source", "with", "asked_at", "due", "priority", "status"]
CONTRACT.append("evidence")
_n = itertools.count()


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_stream(directory, records):
    by_month = defaultdict(list)
    for r in records:
        by_month[r["ts"][:7]].append(r)
    directory.mkdir(parents=True, exist_ok=True)
    for month, rs in by_month.items():
        rs.sort(key=lambda r: (r["ts"], r["id"]))
        (directory / f"{month}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs))


def wa(ts, chat, text, *, me=False, sender=None, group=False, kind="text", caption=None):
    chat_id = f"{chat}@g.us" if group else f"{chat}@s.whatsapp.net"
    return {
        "id": f"{chat_id}/W{next(_n)}",
        "ts": ts,
        "chat_id": chat_id,
        "chat_name": chat,
        "chat_type": "group" if group else "direct",
        "from_me": me,
        "sender_id": None if me else "15550001111@s.whatsapp.net",
        "sender_name": None if me else sender or chat,
        "kind": kind,
        "wa_type": 0,
        "text": text,
        "caption": caption,
    }


def sl(ts, channel, name, text, *, kind="channel", me=False, user="Dana", subtype=None):
    return {
        "id": f"{channel}/{next(_n)}",
        "ts": ts,
        "slack_ts": "1",
        "channel_id": channel,
        "channel_name": name,
        "channel_type": kind,
        "user_id": "U0ME" if me else f"U{user.upper()}",
        "user_name": "Me Myself" if me else user,
        "from_me": me,
        "text": text,
        "thread_ts": None,
        "is_reply": False,
        "subtype": subtype,
        "files": None,
    }


def em(ts, subject, body, *, sender="prof@uni.example", to=("me@example.com",), **extra):
    me = extra.pop("me", False)
    return {
        "id": extra.pop("id", f"msg{next(_n)}@example"),
        "ts": ts,
        "account": "gmail",
        "from_address": "me@example.com" if me else sender,
        "from_name": None if me else extra.pop("name", "Prof Example"),
        "from_me": me,
        "to": list(to) or None,
        "cc": None,
        "subject": subject,
        "in_reply_to": extra.pop("reply_to", None),
        "gmail_labels": extra.pop("labels", None),
        "gmail_thread": None,
        "attachments": None,
        "body": body,
        "body_new": body,
    }


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    write_stream(
        vault / "raw" / "whatsapp" / "messages",
        [
            wa(ago(days=30), "Asha", "Ancient ask from last month"),
            wa(ago(days=13), "Asha", "Still inside the window, in February"),
            wa(ago(days=3), "Asha", "Can you send me the reading list by Friday?"),
            wa(ago(days=3, minutes=-5), "Asha", "Sure, will do tonight", me=True),
            wa(ago(days=2), "Ben", "Could you review my draft?"),
            wa(ago(days=2, minutes=-1), "Ben", None, kind="image"),
            wa(ago(days=2, minutes=-2), "Ben", None, kind="image", caption="Poster draft"),
            wa(ago(days=2, minutes=-3), "Ben", None, kind="system"),
            wa(ago(days=4), "Climbing", "Who books the wall?", sender="Cy", group=True),
            wa(ago(days=4, minutes=-3), "Climbing", "I'll book it", me=True, group=True),
            wa(ago(days=20), "Street", "Old note from me", me=True, group=True),
            wa(ago(days=1), "Street", "Lost cat, call me", sender="Di", group=True),
        ],
    )
    write_stream(
        vault / "raw" / "slack" / "lab" / "messages",
        [
            sl("2026-01-05T10:00:00Z", "C9", "ml", "an old message of mine", me=True),
            sl(ago(days=2), "D1", "Dana", "Please send the poster PDF", kind="dm"),
            sl(ago(days=1), "C1", "general", "<@U0ME> can you fix the cluster script?"),
            sl(ago(days=1), "C1", "general", "joined", user="Ed", subtype="channel_join"),
            sl(ago(days=1), "C2", "random", "Free pizza in the lounge"),
            sl(ago(days=5), "C3", "ml", "I'll present on Thursday", me=True),
        ],
    )
    write_stream(
        vault / "raw" / "email" / "gmail",
        [
            em("2026-01-10T10:00:00Z", "Old", "from me, long ago", me=True, to=("x@uni.example",)),
            em(ago(days=2), "Form", "Please submit the travel form by the 12th"),
            em(
                ago(days=2),
                "Sale",
                "50% off",
                sender="deals@shop.example",
                labels=["Category Promotions"],
            ),
            em(ago(days=2), "Alert", "Your build passed", sender="noreply@ci.example"),
            em(ago(days=2), "Winner", "Claim your prize", labels=["\\Spam"]),
            em(ago(days=3), "Seminar", "Talk on Friday", to=("list@uni.example",)),
            em(ago(days=3), "Retreat", "Who can host?", to=("list@uni.example",), id="r1@x"),
            em(
                ago(days=2),
                "Re: Retreat",
                "I can host",
                me=True,
                to=("list@uni.example",),
                reply_to="r1@x",
            ),
            em(ago(days=1), "Alias", "Sent to my other address", to=("alias@example.com",)),
        ],
    )
    return vault


class FakeModel:
    """Stands in for llm.ask and answers with whatever `answer(prompt)` returns."""

    def __init__(self):
        self.calls = []
        self.answer = lambda prompt: []

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=32000):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        return {"tasks": self.answer(prompt)}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.delenv("PROXENOS_EMAILS", raising=False)
    monkeypatch.delenv("PROXENOS_NAME", raising=False)


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def ref(prompt, text):
    return re.search(rf"^\[(m\d+)\] .*{re.escape(text)}", prompt, re.MULTILINE)[1]


def item(title, *, id="new", source="whatsapp", asked_in="", evidence=(), **fields):
    return {
        "id": id,
        "title": title,
        "detail": fields.get("detail", "Some detail."),
        "source": source,
        "with": fields.get("with_", ""),
        "asked_in": asked_in,
        "due": fields.get("due", ""),
        "priority": fields.get("priority", "medium"),
        "status": fields.get("status", "open"),
        "evidence": list(evidence),
    }


def saved(vault):
    return json.loads((vault / "clones" / "tasks" / "tasks.json").read_text())


def by_title(vault):
    return {t["title"]: t for t in saved(vault)["tasks"]}


def write_tasks(vault, *task_list, closed=None, feedback=()):
    out = vault / "clones" / "tasks"
    out.mkdir(parents=True, exist_ok=True)
    (out / "tasks.json").write_text(json.dumps({"generated": ago(days=1), "tasks": task_list}))
    if closed is not None:
        (out / "closed.json").write_text(json.dumps(closed))
    lines = [json.dumps(f) for f in feedback] + ['{"task_id": "x", "act']
    (out / "feedback.jsonl").write_text("\n".join(lines) + "\n")


def task(key, title, *, status="open", asked_at=None, source="whatsapp", evidence=("old/1",)):
    return {
        "id": key,
        "title": title,
        "detail": "Earlier detail.",
        "source": source,
        "with": "Asha",
        "asked_at": asked_at,
        "due": None,
        "priority": "medium",
        "status": status,
        "evidence": list(evidence),
    }


def test_the_model_sees_both_sides_of_my_conversations_and_nothing_else(tmp_path, model):
    vault = make_vault(tmp_path)
    (vault / "self").mkdir()
    (vault / "self" / "identity.md").write_text("A grad student who rows.")

    stats = tasks.plan(vault, now=NOW)

    [call] = model.calls
    prompt = call["prompt"]
    kept = [
        "Still inside the window, in February",
        "Can you send me the reading list by Friday?",
        "me: Sure, will do tonight",
        "Ben: Could you review my draft?",
        "Ben: Poster draft",
        "Cy: Who books the wall?",
        "me: I'll book it",
        "Dana: Please send the poster PDF",
        "Dana: @me can you fix the cluster script?",  # a channel the user only got mentioned in
        "me: I'll present on Thursday",
        "Prof Example: Please submit the travel form",
        "Prof Example: Who can host?",  # to a list, but the user answered
        "me: I can host",
    ]
    dropped = [
        "Ancient ask",
        "Old note from me",
        "Lost cat",  # a group the user didn't write in this window
        "joined",
        "Free pizza",
        "an old message of mine",
        "50% off",
        "Your build passed",
        "Claim your prize",
        "Talk on Friday",
        "Sent to my other address",  # the user's, but only PROXENOS_EMAILS could say so
        "15550001111",  # never a phone number
    ]
    assert [text for text in kept if text not in prompt] == []
    assert [text for text in dropped if text in prompt] == []
    assert prompt.index("reading list") < prompt.index("Sure, will do tonight")
    assert "### WhatsApp, Asha (direct chat)" in prompt
    assert "### Slack (lab), #general" in prompt
    assert "### Email (gmail): Retreat" in prompt
    assert "Current list\nEmpty: nothing yet." in prompt and "Closed by them" not in prompt
    assert "Only the newest fit" not in prompt
    assert NOW.astimezone().strftime("Today is %A %Y-%m-%d, %H:%M") in prompt
    assert "<identity>\nA grad student who rows.\n</identity>" in call["system"]
    assert call["schema"]["properties"]["tasks"]["items"]["properties"]["status"]["enum"] == [
        "open",
        "waiting",
        "done",
    ]
    assert stats == {"messages": 13, "open": 0, "waiting": 0, "done": 0, "new": 0}
    assert saved(vault) == {"generated": GENERATED, "tasks": []}


def test_my_other_addresses_come_from_proxenos_emails(tmp_path, model, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", " Alias@Example.com ,")
    vault = make_vault(tmp_path)

    tasks.plan(vault, now=NOW)

    assert "Prof Example: Sent to my other address" in model.calls[0]["prompt"]


def test_new_tasks_are_saved_in_the_contract_shape(tmp_path, model):
    vault = make_vault(tmp_path)
    records = [
        json.loads(line)
        for line in (vault / "raw/whatsapp/messages/2026-03.jsonl").read_text().splitlines()
    ]
    asked = next(r for r in records if r["text"] == "Can you send me the reading list by Friday?")
    reply = next(r for r in records if r["text"] == "Sure, will do tonight")

    def answer(prompt):
        ask, said = ref(prompt, "reading list"), ref(prompt, "will do tonight")
        form = ref(prompt, "travel form")
        return [
            item(
                "Send Asha the reading list",
                asked_in=f"[{ask}]",
                evidence=[ask, f"[{said}]", "m999"],
                due="2026-03-13",
                priority="high",
                with_="Asha",
            ),
            item("Submit the travel form", source="email", evidence=[form], due="the 12th"),
            item("Submit the travel form", source="email", evidence=[form], status="waiting"),
            item("   ", evidence=[form]),
        ]

    model.answer = answer
    stats = tasks.plan(vault, now=NOW)

    out = saved(vault)
    assert out["generated"] == GENERATED
    reading, form = out["tasks"]  # open before waiting
    assert list(reading) == CONTRACT
    key = "Send Asha the reading list" + "whatsapp" + asked["ts"]
    expected_id = hashlib.sha1(key.encode()).hexdigest()[:12]
    assert reading == {
        "id": expected_id,
        "title": "Send Asha the reading list",
        "detail": "Some detail.",
        "source": "whatsapp",
        "with": "Asha",
        "asked_at": asked["ts"],
        "due": "2026-03-13",
        "priority": "high",
        "status": "open",
        "evidence": [asked["id"], reply["id"]],
    }
    # Written twice by the model, kept once: the later copy wins. Asked at the first evidence.
    assert form["status"] == "waiting" and form["due"] is None and form["with"] is None
    assert form["asked_at"] == ago(days=2) and form["source"] == "email"
    assert form["id"] == tasks.task_id("Submit the travel form", "email", ago(days=2))
    assert stats == {"messages": 13, "open": 1, "waiting": 1, "done": 0, "new": 2}
    assert not (vault / "clones" / "tasks" / "tasks.json.tmp").exists()


def test_listed_tasks_keep_their_ids_and_are_never_dropped_by_the_model(tmp_path, model):
    vault = make_vault(tmp_path)
    asked_at = ago(days=3)
    write_tasks(
        vault,
        task("aaaaaaaaaaaa", "Send Asha the reading list", asked_at=asked_at),
        task("bbbbbbbbbbbb", "Review Ben's draft"),
    )

    def answer(prompt):
        said = ref(prompt, "will do tonight")
        done = item("Sent Asha the list", id="aaaaaaaaaaaa", status="done", evidence=[said])
        return [{**done, "source": "slack"}]  # the source of a listed task doesn't change

    model.answer = answer
    stats = tasks.plan(vault, now=NOW)

    prompt = model.calls[0]["prompt"]
    assert "- id aaaaaaaaaaaa [open, medium] Send Asha the reading list. Earlier detail." in prompt
    assert "- id bbbbbbbbbbbb [open, medium] Review Ben's draft." in prompt
    listed = {t["id"]: t for t in saved(vault)["tasks"]}
    assert listed["aaaaaaaaaaaa"]["status"] == "done"
    assert listed["aaaaaaaaaaaa"]["title"] == "Sent Asha the list"
    assert listed["aaaaaaaaaaaa"]["source"] == "whatsapp"
    assert listed["aaaaaaaaaaaa"]["asked_at"] == asked_at
    assert listed["aaaaaaaaaaaa"]["evidence"][0] == "old/1"
    assert len(listed["aaaaaaaaaaaa"]["evidence"]) == 2
    assert listed["bbbbbbbbbbbb"] == task("bbbbbbbbbbbb", "Review Ben's draft")
    assert stats["done"] == 1 and stats["open"] == 1 and stats["new"] == 0
    closed = json.loads((vault / "clones" / "tasks" / "closed.json").read_text())
    assert closed["aaaaaaaaaaaa"]["action"] is None
    assert closed["aaaaaaaaaaaa"]["closed_at"] == GENERATED


def test_what_i_closed_on_the_page_stays_closed(tmp_path, model):
    vault = make_vault(tmp_path)
    form_at = ago(days=2)
    write_tasks(
        vault,
        task("111111111111", "Fix the cluster script", source="slack"),
        task("222222222222", "Submit the travel form", source="email", asked_at=form_at),
        task("333333333333", "Send Dana the poster PDF", source="slack"),
        task("444444444444", "Book the climbing wall"),
        feedback=[
            {"task_id": "111111111111", "action": "not_mine", "ts": ago(hours=5)},
            {"task_id": "222222222222", "action": "dismiss", "ts": ago(hours=4)},
            {"task_id": "333333333333", "action": "done", "ts": ago(hours=3)},
            {"task_id": "444444444444", "action": "open", "ts": ago(hours=2)},  # not a verdict
        ],
    )

    def answer(prompt):
        form = ref(prompt, "travel form")
        return [
            item("Fix the cluster script", source="slack"),  # same title
            item("File travel paperwork", source="email", asked_in=form),  # same message
            item("send dana the POSTER pdf!", source="slack"),  # same title, any case
            item("Send Dana the poster PDF", id="333333333333", source="slack"),  # its old id
            item("Book the climbing wall", id="444444444444", priority="high"),
        ]

    model.answer = answer
    stats = tasks.plan(vault, now=NOW)

    prompt = model.calls[0]["prompt"]
    current = prompt.split("## Current list")[1].split("## Closed")[0]
    assert "444444444444" in current
    assert not re.search(r"111111111111|222222222222|333333333333", current)
    assert "- Fix the cluster script (slack, with Asha): not theirs" in prompt
    assert "- Submit the travel form (email, with Asha): dismissed" in prompt
    assert "- Send Dana the poster PDF (slack, with Asha): done" in prompt
    listed = {t["id"]: t for t in saved(vault)["tasks"]}
    assert set(listed) == {"333333333333", "444444444444"}
    assert listed["333333333333"]["status"] == "done"
    assert listed["333333333333"]["title"] == "Send Dana the poster PDF"
    assert listed["444444444444"]["priority"] == "high"
    assert stats["new"] == 0 and stats["done"] == 1 and stats["open"] == 1

    # Gone from the list, they're still remembered, so they can't come back next run either.
    closed = json.loads((vault / "clones" / "tasks" / "closed.json").read_text())
    assert {k: e["action"] for k, e in closed.items()} == {
        "111111111111": "not_mine",
        "222222222222": "dismiss",
        "333333333333": "done",
    }
    model.calls.clear()
    tasks.plan(vault, now=NOW + timedelta(hours=1))
    assert "- Fix the cluster script (slack, with Asha): not theirs" in model.calls[0]["prompt"]
    assert {t["id"] for t in saved(vault)["tasks"]} == {"333333333333", "444444444444"}


def test_done_tasks_leave_after_30_days_and_no_messages_means_no_model_call(tmp_path, model):
    vault = tmp_path / "vault"
    write_tasks(
        vault,
        task("dddddddddddd", "Long done", status="done"),
        task("eeeeeeeeeeee", "Just done", status="done"),
        task("ffffffffffff", "Still open"),
        task("gggggggggggg", "Marked done long ago"),
        closed={
            "dddddddddddd": {
                "title": "Long done",
                "source": "whatsapp",
                "with": None,
                "asked_at": None,
                "action": None,
                "closed_at": ago(days=31),
            }
        },
        feedback=[{"task_id": "gggggggggggg", "action": "done", "ts": ago(days=40)}],
    )

    stats = tasks.plan(vault, now=NOW)

    assert model.calls == []
    assert [t["title"] for t in saved(vault)["tasks"]] == ["Still open", "Just done"]
    assert stats == {"messages": 0, "open": 1, "waiting": 0, "done": 1, "new": 0}
    closed = json.loads((vault / "clones" / "tasks" / "closed.json").read_text())
    assert closed["eeeeeeeeeeee"]["closed_at"] == GENERATED
    assert closed["gggggggggggg"]["action"] == "done"  # remembered after it left the list


def test_over_the_cap_the_oldest_messages_go_first():
    def convo(title, *stamps):
        msgs = [{"id": f"{title}/{s}", "ts": s, "sender": "me", "text": "x" * 50} for s in stamps]
        return {"source": "slack", "title": title, "messages": msgs}

    convos = [
        convo("quiet", "2026-03-01T10:00:00Z", "2026-03-09T10:00:00Z"),
        convo("busy", *(f"2026-03-0{d}T12:00:00Z" for d in range(2, 9))),
    ]
    text, refs, cut = tasks.render(convos)
    assert not cut and len(refs) == 9

    text, refs, cut = tasks.render(convos, limit=450)
    assert cut
    kept = [m["id"] for m in refs.values()]
    assert kept == [
        "busy/2026-03-05T12:00:00Z",
        "busy/2026-03-06T12:00:00Z",
        "busy/2026-03-07T12:00:00Z",
        "busy/2026-03-08T12:00:00Z",
        "quiet/2026-03-09T10:00:00Z",
    ]
    assert list(refs) == ["m1", "m2", "m3", "m4", "m5"]
    assert text.startswith("### busy\n[m1] ") and "\n\n### quiet\n[m5] " in text
    assert len(text) <= 450


def test_the_command_line_reads_days(tmp_path, model):
    parser = argparse.ArgumentParser()
    tasks.add_arguments(parser)
    assert parser.parse_args([]).days == 14
    assert parser.parse_args(["--days", "3"]).days == 3
