"""Choices clone on a synthetic vault with the model faked out. No network, no real data."""

import argparse
import json
import re
from datetime import UTC, datetime

import pytest

from proxenos import chats, cli, llm
from proxenos.clones import choices, work

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
DAY = "2026-03-10"
ME = "tess@uni.edu"
CFP_URL = "https://wm-symposium.example.org/abstracts"
SAFE = "https://nam12.safelinks.protection.outlook.com/?url=https%3A%2F%2Ffund.example.org%2Fapply&data=x"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path, data):
    write(path, json.dumps(data))


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r) + "\n" for r in records) + '{"torn": \n')


def mail(key, ts, sender, address, subject, body, to=(ME,), mine=False, bulk=False, labels=()):
    return {
        "id": key,
        "ts": ts,
        "account": "uni",
        "from_address": ME if mine else address,
        "from_name": "Tess" if mine else sender,
        "from_me": mine,
        "to": list(to),
        "cc": [],
        "subject": subject,
        "in_reply_to": None,
        "gmail_labels": list(labels),
        "bulk": bulk,
        "body": body,
        "body_new": body,
    }


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    write(vault / "self" / "identity.md", "# Identity\n\nTess studies working memory capacity.")
    write(vault / "self" / "interests.md", "- Working memory, attention, computational models")
    write(vault / "self" / "voice.md", "Short sentences, never a sign-off.")
    write(vault / "self" / "CHANGELOG.md", "- 2026-03-01: first model")
    letters = [
        mail(
            "cfp",
            "2026-03-05T14:00:00Z",
            "Memory Society",
            "office@memsoc.org",
            "Call for abstracts: Working Memory Symposium",
            f"Submit an abstract on working memory capacity by April 1. Details: {CFP_URL} "
            "Unsubscribe: https://memsoc.org/unsubscribe?u=1",
            to=("members@memsoc.org",),
            bulk=True,
        ),
        mail(
            "cfp-again",
            "2026-03-02T14:00:00Z",
            "Memory Society",
            "office@memsoc.org",
            "Re: Call for abstracts: Working Memory Symposium",
            "Reminder: submit your abstract.",
            to=("members@memsoc.org",),
            bulk=True,
        ),
        mail(
            "fund",
            "2026-03-08T09:00:00Z",
            "Founders Office",
            "office@founders.org",
            "Applications open: Founders Fellowship",
            "You don't often get email from office@founders.org. Learn why this is important"
            "<https://aka.ms/LearnAboutSenderIdentification> "
            f"The fellowship funds a year of building. Apply here: {SAFE}",
            to=("fellows@founders.org",),
            bulk=True,
        ),
        mail(
            "receipt",
            "2026-03-07T09:00:00Z",
            "Shop",
            "orders@shop.com",
            "Your order has shipped",
            "Thanks for shopping.",
        ),
        mail(
            "clinic",
            "2026-03-06T09:00:00Z",
            "Clinic",
            "front@clinic.org",
            "Register for your appointment and referral",
            "Bring your insurance card to the visit; the prescription refill is ready.",
        ),
        mail(
            "old",
            "2026-01-20T09:00:00Z",
            "Old Society",
            "old@society.org",
            "Call for papers: a conference long gone",
            "Submit by February.",
        ),
        mail(
            "spam",
            "2026-03-09T09:00:00Z",
            "Prize",
            "win@prize.biz",
            "You won an award, apply now",
            "Claim the prize.",
            labels=("SPAM",),
        ),
        mail(
            "mine", "2026-03-09T10:00:00Z", "", "", "Notes", "Here.", to=("ana@lab.org",), mine=True
        ),
    ]
    letters += [
        mail(
            f"news{n}",
            f"2026-03-0{n}T08:00:00Z",
            "Daily Brief",
            "news@brief.com",
            f"Today's brief {n}",
            "Headlines.",
            to=("list@brief.com",),
            bulk=True,
        )
        for n in range(1, 10)
    ]
    write_jsonl(vault / "raw" / "email" / "uni" / "2026-03.jsonl", letters)
    write_jsonl(vault / "raw" / "email" / "uni" / "2026-01.jsonl", [])

    slack = [
        {
            "id": "C1/1",
            "ts": "2026-03-09T15:00:00Z",
            "channel_id": "C1",
            "channel_name": "announcements",
            "channel_type": "channel",
            "user_id": "U2",
            "user_name": "Ana Lee",
            "from_me": False,
            "text": "Speakers wanted: <https://talks.example.org/apply|apply to give a talk> at "
            "the spring seminar, <@U9|Ben> is organizing",
            "is_reply": False,
            "subtype": None,
        },
        {
            "id": "C2/1",
            "ts": "2026-03-09T16:00:00Z",
            "channel_id": "C2",
            "channel_name": "random",
            "channel_type": "channel",
            "user_id": "U2",
            "user_name": "Ana Lee",
            "from_me": False,
            "text": "Apply for the talk and workshop grant here",
            "is_reply": False,
            "subtype": None,
        },
    ]
    write_jsonl(vault / "raw" / "slack" / "lab" / "messages" / "2026-03.jsonl", slack)

    group = [
        {
            "id": f"g/{n}",
            "ts": f"2026-03-0{1 + n % 9}T10:{n % 60:02d}:00Z",
            "chat_id": "123@g.us",
            "chat_name": "Building chat",
            "chat_type": "group",
            "from_me": False,
            "text": "hi",
        }
        for n in range(60)
    ]
    write_jsonl(vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl", group)

    me = {"name": "Tess", "email": ME, "status": "accepted"}
    events = [
        {
            "id": "weekly",
            "ts": "2026-03-03T15:00:00Z",
            "start": "2026-03-03T15:00:00Z",
            "end": "2026-03-03T16:00:00Z",
            "all_day": False,
            "summary": "Reading group",
            "rrule": "FREQ=WEEKLY;BYDAY=TU",
            "organizer": "ana@lab.org",
            "guests": [{"name": "Ana Lee", "email": "ana@lab.org", "status": "accepted"}, me],
        },
        {
            "id": "panel",
            "ts": "2026-03-20T18:00:00Z",
            "start": "2026-03-20T18:00:00Z",
            "end": "2026-03-20T20:00:00Z",
            "all_day": False,
            "summary": "Review panel",
            "rrule": None,
            "organizer": "dean@uni.edu",
            "guests": [
                {"name": "Dean Ray", "email": "dean@uni.edu", "status": "accepted"},
                me | {"status": "needs-action"},
            ],
        },
        {
            "id": "block",
            "ts": "2026-03-11T09:00:00Z",
            "start": "2026-03-11T09:00:00Z",
            "end": "2026-03-11T17:00:00Z",
            "all_day": False,
            "summary": "Writing day",
            "rrule": None,
            "organizer": ME,
            "guests": [me, {"name": "Ana Lee", "email": "ana@lab.org"}],
        },
    ]
    write_jsonl(vault / "raw" / "calendar" / "uni" / "2026-03.jsonl", events)
    write_jsonl(
        vault / "raw" / "calendar" / "uni-appointment_schedule" / "2026-03.jsonl",
        [events[0] | {"id": "slots", "summary": "Office hours slots"}],
    )

    write_json(
        vault / "clones" / "tasks" / "tasks.json",
        {
            "tasks": [
                {
                    "id": "t-old",
                    "title": "Send Ben the slides",
                    "status": "open",
                    "source": "slack",
                    "with": "Ben",
                    "asked_at": "2026-02-01T10:00:00Z",
                },
                {
                    "id": "t-new",
                    "title": "Book the climbing wall",
                    "status": "open",
                    "source": "whatsapp",
                    "asked_at": "2026-03-09T10:00:00Z",
                    "due": "2026-03-12",
                },
            ]
        },
    )
    write_json(
        vault / "clones" / "network" / "ideas.json",
        {
            "projects": [{"id": "p1", "title": "A capacity benchmark"}],
            "outreach": [{"id": "x1", "name": "Ana Lee", "ask": "Ask about the dataset"}],
        },
    )
    return vault


class FakeModel:
    """Answers with the lists the test sets, after finding the refs it cites in the prompt."""

    def __init__(self):
        self.calls = []
        self.answer = None

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=32000):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        return self.answer(prompt) if callable(self.answer) else self.answer


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    waiting = {
        "source": "whatsapp",
        "chat": "555@s.whatsapp.net",
        "name": "Sam",
        "id": "w1",
        "since": "2026-02-20T10:00:00Z",
        "waiting": [
            {"ts": "2026-02-20T10:00:00Z", "mine": False, "sender": "Sam", "text": "Coffee?"}
        ],
        "recent": [],
        "own": ["sure"],
        "first": False,
    }
    fresh = waiting | {"chat": "666@s.whatsapp.net", "name": "Uma", "since": "2026-03-09T10:00:00Z"}
    monkeypatch.setattr(chats, "waiting", lambda vault, now, days: [fresh, waiting, waiting])


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def ref(prompt, pattern):
    return re.search(pattern, prompt, re.MULTILINE)[1]


def answer(prompt):
    cfp = ref(prompt, r'<opening ref="(o\d+)"[^>]*>\nCall for abstracts')
    link = ref(prompt, r"Details: \[(L\d+)\]")
    invite = ref(prompt, r"^- \[(k\d+)\] invitation:")
    brief = ref(prompt, r'^- \[(k\d+)\] list: mail from "Daily Brief"')
    return {
        "take_on": [
            {
                "kind": "cfp",
                "title": "Submit an abstract to the Working Memory Symposium",
                "why": "Your capacity work fits its theme.",
                "refs": [cfp, "self/interests", "o99"],
                "deadline": "2026-04-01",
                "link": link,
                "step": {
                    "kind": "draft",
                    "what": "A 250-word abstract from the capacity paper",
                    "to": "",
                    "channel": "other",
                },
            },
            {
                "kind": "event",
                "title": "Go to last week's talk",
                "why": "Missed.",
                "refs": [cfp],
                "deadline": "2026-03-01",
                "link": "",
                "step": {"kind": "draft", "what": "Notes", "to": "", "channel": "other"},
            },
            {
                "kind": "writing",
                "title": "Write up the capacity result as a post",
                "why": "Your notes are ready for it.",
                "refs": ["self/identity", "network"],
                "deadline": "someday",
                "link": "L999",
                "step": {
                    "kind": "errand",
                    "what": "Reach Ana Lee about co-writing it, by email",
                    "to": "Ana Lee",
                    "channel": "email",
                },
            },
            {
                "kind": "grant",
                "title": "Something resting on nothing",
                "why": "",
                "refs": ["zz"],
                "deadline": "",
                "link": "",
                "step": {"kind": "draft", "what": "x", "to": "", "channel": "other"},
            },
            {
                "kind": "cfp",
                "title": "submit an abstract to the working-memory symposium!",
                "why": "The same again.",
                "refs": [cfp],
                "deadline": "",
                "link": "",
                "step": {"kind": "draft", "what": "x", "to": "", "channel": "other"},
            },
        ],
        "skip": [
            {
                "kind": "invitation",
                "title": "Decline the review panel",
                "why": "Two hours on work far from yours.",
                "cost": "2 h",
                "refs": [invite],
                "decline": {
                    "what": "Thank Dean and say no this time.",
                    "to": "",
                    "channel": "email",
                },
            },
            {
                "kind": "list",
                "title": "Leave the Daily Brief",
                "why": "Nine a week, none read.",
                "cost": "9 emails in 10 days",
                "refs": [brief],
                "decline": {"what": "", "to": "", "channel": "other"},
            },
        ],
    }


def run(vault, now=NOW, force=False):
    return choices.choose(vault, force=force, now=now)


def test_a_week_s_choices_from_mail_slack_calendar_tasks_and_chats(tmp_path, model):
    vault = make_vault(tmp_path)
    model.answer = answer

    stats = run(vault)

    assert stats == {
        "openings_read": 3,
        "costs_read": 6,
        "to_take_on": 2,
        "to_skip": 2,
        "old_drafts_cleared": 0,
    }
    (call,) = model.calls
    assert call["effort"] == "high"
    prompt, system = call["prompt"], call["system"]
    assert "Tess" in system and "{" not in system

    # Who they are, without their voice or the changelog; what's on their plate; their ideas.
    assert "working memory capacity" in prompt and "never a sign-off" not in prompt
    assert "first model" not in prompt
    assert (
        "- Send Ben the slides" in prompt and "- Book the climbing wall (due 2026-03-12)" in prompt
    )
    assert "- project: A capacity benchmark" in prompt
    assert "- reach out to Ana Lee: Ask about the dataset" in prompt

    # Openings: the announcements, once each, links as tags; not health care, receipts, spam,
    # the user's own mail, chatter, or mail from before the window.
    assert prompt.count("Call for abstracts: Working Memory Symposium") == 1
    assert 'from="Memory Society" date="2026-03-05", sent 2 times>' in prompt
    assert "Applications open: Founders Fellowship" in prompt
    assert "Apply here: [L" in prompt and "safelinks" not in prompt
    assert CFP_URL not in prompt and "unsubscribe" not in prompt
    assert "Learn why" not in prompt and "aka.ms" not in prompt  # Outlook's banner
    assert 'where="Slack #announcements in lab" from="Ana Lee"' in prompt
    assert "apply to give a talk https://" not in prompt and "@U9" not in prompt
    assert "Ben is organizing" in prompt
    for absent in ("shipped", "appointment", "insurance", "long gone", "You won", "random"):
        assert absent not in prompt
    assert prompt.index("Working Memory Symposium") < prompt.index("Founders Fellowship")

    # Costs: the user's meetings with others, invitations, old threads and tasks, lists, groups.
    lines = [line for line in prompt.splitlines() if re.match(r"- \[k\d+\] ", line)]
    assert [line.split("] ", 1)[1].split(":", 1)[0] for line in lines] == [
        "invitation",
        "meeting",
        "thread",
        "task",
        "list",
        "channel",
    ]
    text = "\n".join(lines)
    assert '"Review panel", Fri 2026-03-20' in text and "not answered yet; from Dean Ray" in text
    assert '"Reading group", 2 time(s) in the next 14 days, 2.0 h, repeating: 1.0 h a week' in text
    assert "organized by Ana Lee" in text
    assert "Writing day" not in text and "Office hours slots" not in text
    assert text.count("chat with Sam") == 1 and "Uma" not in text
    assert 'waiting on you 18 days, since 2026-02-20: "Coffee?"' in text
    assert '"Send Ben the slides", on the list since 2026-02-01 (open, with Ben, slack)' in text
    assert "Book the climbing wall" not in text
    assert 'mail from "Daily Brief" (brief.com), 9 in 30 days' in text
    assert "Memory Society" not in text  # it mails, but not often enough to be a list
    assert 'WhatsApp group "Building chat", 60 posts in 30 days, none of them yours' in text
    assert "No earlier choices yet." in prompt

    # The schema holds the model to the refs it was given.
    refs = call["schema"]["properties"]["take_on"]["items"]["properties"]["refs"]["items"]["enum"]
    assert "self/identity" in refs and "self/voice" not in refs and "tasks" in refs

    saved = json.loads((vault / "clones" / "choices" / f"{DAY}.json").read_text())
    assert saved["generated"] == "2026-03-10T12:00:00Z"
    first, post = saved["take_on"]
    assert first["title"] == "Submit an abstract to the Working Memory Symposium"
    assert first["deadline"] == "2026-04-01" and first["link"] == CFP_URL
    assert [e["ref"] for e in first["evidence"]] == [
        ref(prompt, r'<opening ref="(o\d+)"[^>]*>\nCall for abstracts'),
        "self/interests",
    ]
    assert first["evidence"][0] == {
        "ref": first["evidence"][0]["ref"],
        "label": "Email from Memory Society, 2026-03-05: Call for abstracts: Working Memory Symposium",
        "id": "email/uni/cfp",
    }
    assert first["evidence"][1]["label"] == "Your interests"
    assert first["step"] == {
        "kind": "draft",
        "what": "A 250-word abstract from the capacity paper",
        "to": "",
        "channel": "other",
    }
    assert first["draft_id"] == f"choice-{first['id']}"
    assert CFP_URL in first["excerpt"]  # the draft gets the announcement as it was
    assert post["deadline"] == "" and post["link"] == "" and post["draft_id"] is None
    assert post["step"]["kind"] == "errand" and post["step"]["to"] == "Ana Lee"
    assert post["id"] == choices.item_id("take_on", post["title"])

    panel, brief = saved["skip"]
    assert panel["decline"] == {
        "what": "Thank Dean and say no this time.",
        "to": "Dean Ray",
        "channel": "email",
    }
    assert panel["draft_id"] == f"choice-{panel['id']}" and panel["cost"] == "2 h"
    assert panel["evidence"][0]["label"].startswith('Invitation: "Review panel"')
    assert brief["decline"] is None and brief["draft_id"] is None

    history = json.loads((vault / "clones" / "choices" / "history.json").read_text())
    assert history[first["id"]] == {
        "side": "take_on",
        "kind": "cfp",
        "title": first["title"],
        "given": DAY,
        "sources": ["email/uni/cfp"],
        "senders": ["office@memsoc.org"],
    }
    assert history[panel["id"]]["sources"] == ["invite:panel"]
    assert history[panel["id"]]["senders"] == []


def test_it_runs_once_a_week_unless_forced(tmp_path, model):
    vault = make_vault(tmp_path)
    model.answer = {"take_on": [], "skip": []}
    write_json(vault / "clones" / "choices" / "2026-03-07.json", {"take_on": [], "skip": []})

    assert run(vault) == {"days_until_next_run": 4}
    assert model.calls == []
    assert run(vault, now=datetime(2026, 3, 14, 12, tzinfo=UTC))["to_take_on"] == 0
    assert len(model.calls) == 1
    # A later run reads from three days before the last one.
    assert "Openings that reached Tess since 2026-03-04" in model.calls[0]["prompt"]
    assert "since 2026-03-04" in model.calls[0]["prompt"]
    assert run(vault, force=True)["to_skip"] == 0  # a run from the page, whenever


def test_a_first_run_reads_three_weeks(tmp_path, model):
    vault = make_vault(tmp_path)
    model.answer = {"take_on": [], "skip": []}
    run(vault)
    assert "Openings that reached Tess since 2026-02-17" in model.calls[0]["prompt"]


def test_what_i_marked_never_comes_back_and_teaches_the_next_run(tmp_path, model):
    vault = make_vault(tmp_path)
    out = vault / "clones" / "choices"
    write_json(
        out / "history.json",
        {
            "a1": {
                "side": "take_on",
                "kind": "program",
                "title": "Apply to the Founders Fellowship",
                "given": "2026-03-01",
                "sources": ["email/uni/fund"],
                "senders": ["office@founders.org"],
            },
            "a2": {
                "side": "skip",
                "kind": "meeting",
                "title": "Drop the reading group",
                "given": "2026-03-01",
                "sources": ["meeting:reading group"],
                "senders": [],
            },
            "a3": {
                "side": "take_on",
                "kind": "cfp",
                "title": "Submit to the symposium",
                "given": "2026-03-01",
                "sources": [],
                "senders": ["office@memsoc.org"],
            },
        },
    )
    write_jsonl(
        out / "feedback.jsonl",
        [
            {"item_id": "a1", "action": "useful", "ts": "2026-03-02T10:00:00Z"},
            {"item_id": "a1", "action": "not_me", "ts": "2026-03-03T10:00:00Z"},
            {"item_id": "a2", "action": "doing", "ts": "2026-03-03T10:00:00Z"},
            {"item_id": "a3", "action": "useful", "ts": "2026-03-03T10:00:00Z"},
            {"item_id": "a3", "action": "bogus", "ts": "2026-03-04T10:00:00Z"},
        ],
    )

    def again(prompt):
        return {
            "take_on": [
                {
                    "kind": "program",
                    "title": "Apply to the founders fellowship.",
                    "why": "",
                    "refs": ["self/identity"],
                    "deadline": "",
                    "link": "",
                    "step": {"kind": "draft", "what": "x", "to": "", "channel": "other"},
                }
            ],
            "skip": [
                {
                    "kind": "meeting",
                    "title": "Drop the reading group",
                    "why": "",
                    "cost": "",
                    "refs": ["tasks"],
                    "decline": {"what": "", "to": "", "channel": "other"},
                }
            ],
        }

    model.answer = again
    stats = run(vault)

    prompt = model.calls[0]["prompt"]
    assert "Founders Fellowship" not in prompt.split("# Openings")[1].split("# Earlier")[0]
    assert "Reading group" not in prompt.split("# What Tess's time")[1].split("# Earlier")[0]
    assert "They marked these not them" in prompt
    assert "- [take_on, program] Apply to the Founders Fellowship (given 2026-03-01)" in prompt
    assert "They're doing these" in prompt and "They found these useful" in prompt
    assert "- take_on cfp: 1 useful" in prompt and "- skip meeting: 1 doing" in prompt
    assert stats["to_take_on"] == 0 and stats["to_skip"] == 0


def test_how_i_took_a_sender_s_items_moves_its_openings(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    since = datetime(2026, 2, 17, tzinfo=UTC)
    history = {key: {"side": "take_on", "senders": ["office@memsoc.org"]} for key in ("h", "i")}

    def order(reactions):
        found = choices.gather_openings(vault, since, {ME}, history, reactions)
        return [o["sender"] for o in found if o["where"] == "email"]

    assert order({}) == ["Memory Society", "Founders Office"]
    assert order({"h": "not_me", "i": "not_me"}) == ["Founders Office", "Memory Society"]
    assert order({"h": "not_me", "i": "useful"}) == ["Memory Society", "Founders Office"]


def test_without_a_self_model_it_says_so(tmp_path, model):
    with pytest.raises(SystemExit, match="no self-model"):
        run(tmp_path / "vault")
    assert model.calls == []


def test_earlier_weeks_untouched_drafts_go(tmp_path, model):
    vault = make_vault(tmp_path)
    model.answer = {"take_on": [], "skip": []}
    folder = vault / "clones" / "drafts"
    for key, status in [("old", "draft"), ("kept", "draft"), ("edited", "draft"), ("sent", "sent")]:
        write(folder / f"choice-{key}.md", f"---\nid: choice-{key}\nstatus: {status}\n---\n\nHi\n")
    write(folder / "reply-x.md", "---\nid: reply-x\nstatus: draft\n---\n\nHi\n")
    write_jsonl(
        vault / "clones" / "choices" / "feedback.jsonl",
        [{"item_id": "kept", "action": "doing", "ts": "2026-03-01T10:00:00Z"}],
    )
    write_jsonl(folder / "feedback.jsonl", [{"draft_id": "choice-edited", "action": "edit"}])

    assert run(vault)["old_drafts_cleared"] == 1
    assert sorted(p.stem for p in folder.glob("*.md")) == [
        "choice-edited",
        "choice-kept",
        "choice-sent",
        "reply-x",
    ]


def test_work_drafts_each_first_step_and_decline_but_not_errands_or_not_me(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(chats, "waiting", lambda vault, now, days=7: [])
    item = {
        "id": "c1",
        "kind": "cfp",
        "title": "Submit an abstract",
        "why": "It fits.",
        "deadline": "2026-04-01",
        "link": CFP_URL,
        "evidence": [{"ref": "o1", "label": "Email from Memory Society", "id": "email/uni/cfp"}],
        "step": {"kind": "draft", "what": "A 250-word abstract", "to": "", "channel": "other"},
        "draft_id": "choice-c1",
        "excerpt": "Submit by April 1.",
    }
    write_json(vault / "clones" / "choices" / "2026-03-03.json", {"take_on": [item | {"id": "x"}]})
    write_json(
        vault / "clones" / "choices" / f"{DAY}.json",
        {
            "take_on": [
                item,
                item | {"id": "c2", "draft_id": None, "step": {"kind": "errand", "what": "Reach"}},
                item | {"id": "c3", "draft_id": "choice-c3", "title": "Not for me"},
            ],
            "skip": [
                {
                    "id": "s1",
                    "kind": "invitation",
                    "title": "Decline the review panel",
                    "why": "Far from your work.",
                    "cost": "2 h",
                    "evidence": [{"ref": "k1", "label": "Invitation: Review panel"}],
                    "decline": {"what": "Say no kindly.", "to": "Dean Ray", "channel": "email"},
                    "draft_id": "choice-s1",
                }
            ],
        },
    )
    write_jsonl(
        vault / "clones" / "choices" / "feedback.jsonl",
        [{"item_id": "c3", "action": "not_me", "ts": "2026-03-10T10:00:00Z"}],
    )
    for name in ("tasks", "network"):  # only the choices to draft here
        (vault / "clones" / name).joinpath(
            "tasks.json" if name == "tasks" else "ideas.json"
        ).unlink()
    calls = []

    def draft(prompt, *, system=None, schema=None, effort="medium", max_tokens=32000):
        calls.append(prompt)
        return {"title": "A draft", "kind": "doc", "channel": "other", "to": "", "body": "Text."}

    monkeypatch.setattr(llm, "ask", draft)

    stats = work.work(vault, limit=10, now=NOW)

    assert stats["drafts_written"] == 2
    assert sorted(p.stem for p in (vault / "clones" / "drafts").glob("*.md")) == [
        "choice-c1",
        "choice-s1",
    ]
    opening, decline = calls
    assert "An opening their digital twin picked for them to take on this week:" in opening
    assert (
        "- Deadline: 2026-04-01" in opening and "- The announcement: Submit by April 1." in opening
    )
    assert "- What it rests on: Email from Memory Society" in opening
    assert "Draft the first step: A 250-word abstract" in opening
    assert "- To: Dean Ray" in decline and "Draft a short, kind decline: Say no kindly." in decline
    assert (
        work._front((vault / "clones" / "drafts" / "choice-s1.md").read_text())["for"] == "choice"
    )


def test_the_command_line_runs_it_weekly(tmp_path, model, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    write_json(vault / "clones" / "choices" / f"{datetime.now().astimezone():%Y-%m-%d}.json", {})

    cli.main(["clone", "choices"])

    assert capsys.readouterr().out.strip() == "choices: 7 days until next run"
    assert model.calls == []
    parser = argparse.ArgumentParser()
    choices.add_arguments(parser)
    assert parser.parse_args(["--force"]).force is True


def test_a_skip_never_cuts_off_an_opening_s_source_and_only_people_owed_one_get_a_decline():
    opening = {
        "ref": "o1",
        "key": "email/uni/cfp",
        "where": "email",
        "sender": "Memory Society",
        "address": "list@memsoc.org",
        "home": "list:list@memsoc.org",
        "ts": "2026-03-05T14:00:00Z",
        "title": "Call for abstracts",
        "links": [],
        "excerpt": "",
    }
    costs = {
        "k1": {"key": "list:list@memsoc.org", "kind": "list", "line": "the society's list"},
        "k2": {"key": "thread:whatsapp:1", "kind": "thread", "line": "Sam", "to": "Sam"},
        "k3": {"key": "invite:panel", "kind": "invitation", "line": "panel", "to": "Dean Ray"},
        "k4": {"key": "list:news@brief.com", "kind": "list", "line": "the brief"},
    }
    by_ref = {"o1": opening} | {r: c | {"ref": r} for r, c in costs.items()}
    no = {"what": "Say no.", "to": "", "channel": "email"}

    def skip(ref, kind):
        return {
            "kind": kind,
            "title": f"Skip {ref}",
            "why": "",
            "cost": "",
            "refs": [ref],
            "decline": no,
        }

    answer = {
        "take_on": [
            {
                "kind": "cfp",
                "title": "Submit an abstract",
                "why": "",
                "refs": ["o1", "self/open_questions"],
                "deadline": "",
                "link": "",
                "step": {"kind": "draft", "what": "An abstract", "to": "", "channel": "other"},
            }
        ],
        "skip": [
            skip("k1", "list"),
            skip("k2", "thread"),
            skip("k3", "invitation"),
            skip("k4", "list"),
        ],
    }

    result = choices._accept(answer, by_ref, {"self/open_questions"}, {}, set(), set(), NOW)

    assert result["take_on"][0]["evidence"][1]["label"] == "Your open questions"
    thread, panel, brief = result["skip"]  # the society's list stays: the abstract came from it
    assert [s["title"] for s in result["skip"]] == ["Skip k2", "Skip k3", "Skip k4"]
    assert (
        thread["decline"] is None and thread["draft_id"] is None
    )  # letting it go is not answering
    assert brief["decline"] is None
    assert panel["decline"] == {"what": "Say no.", "to": "Dean Ray", "channel": "email"}
    assert panel["draft_id"] == f"choice-{panel['id']}"
