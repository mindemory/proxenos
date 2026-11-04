"""The outbox, on a synthetic vault with a fake way to send. Nothing is ever sent for real."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import chats, outbox
from proxenos.clones import work

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def wa(ts, text, mine=False, chat="1555@s.whatsapp.net"):
    return {
        "id": f"{chat}/{ts}",
        "ts": ts,
        "chat_id": chat,
        "chat_name": "Asha",
        "chat_type": "direct",
        "from_me": mine,
        "sender_name": None if mine else "Asha",
        "text": text,
    }


@pytest.fixture
def vault(tmp_path, monkeypatch):
    write(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        "\n".join(
            json.dumps(r)
            for r in [
                wa("2026-03-08T09:00:00Z", "see you soon", mine=True),
                wa("2026-03-10T09:00:00Z", "coming friday?"),
            ]
        )
        + "\n",
    )
    (chat,) = chats.waiting(tmp_path, NOW)
    reply(tmp_path, work.reply_key(chat), "yaa coming")
    measured(tmp_path, "whatsapp", [1.0] * 35)
    write(
        tmp_path / "clones" / "outbox" / "rules.json",
        json.dumps({"enabled": True, "channels": {"whatsapp": {"on": True}}}),
    )
    monkeypatch.setattr(
        outbox, "_routes", lambda: dict.fromkeys(outbox.CHANNELS) | {"whatsapp": "beeper"}
    )
    return tmp_path


def measured(vault, source, closeness):
    """fidelity.json with one measured reply draft per closeness, none of them used."""
    drafts = [
        {"id": f"reply-past{i:08d}", "source": source, "closeness": c}
        for i, c in enumerate(closeness)
    ]
    write(
        vault / "clones" / "drafts" / "fidelity.json",
        json.dumps({"by_source": {source: {"n": len(drafts), "mean": 0.9}}, "drafts": drafts}),
    )


def reply(vault, draft_id, body, status="draft", asks="[]"):
    write(
        vault / "clones" / "drafts" / f"{draft_id}.md",
        f'---\nid: {draft_id}\ntitle: "Reply"\nkind: reply\nfor: reply\nchannel: whatsapp\n'
        f'to: "Asha"\ncreated: 2026-03-10T10:00:00Z\nstatus: {status}\nasks: {asks}\n---\n\n{body}\n',
    )


class Sender:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, thread, text):
        if self.fail:
            raise RuntimeError("Beeper isn't answering")
        self.sent.append((thread, text))


def state(vault):
    return json.loads((vault / "clones" / "outbox" / "state.json").read_text())


def test_a_qualifying_reply_is_queued_then_sent_at_the_next_sync_and_logged(vault):
    send = Sender()
    first = outbox.run(vault, NOW, {"beeper": send})
    assert first["outbox_queued"] == 1 and not send.sent  # a window to cancel first
    assert state(vault)["earned"]["whatsapp"] and state(vault)["queue"][0]["to"] == "Asha"

    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})

    ((thread, text),) = send.sent
    assert text == "yaa coming" and thread["chat"] == "1555@s.whatsapp.net"
    (draft,) = (vault / "clones" / "drafts").glob("reply-*.md")
    assert "status: sent" in draft.read_text()
    (entry,) = [
        json.loads(line)
        for line in (vault / "clones" / "outbox" / "log.jsonl").read_text().splitlines()
    ]
    assert (entry["ok"], entry["via"], entry["channel"]) == (True, "beeper", "whatsapp")


def test_nothing_goes_while_off_unearned_cancelled_or_unsafe(vault):
    send = Sender()
    rules = vault / "clones" / "outbox" / "rules.json"
    write(rules, json.dumps({"enabled": False, "channels": {"whatsapp": {"on": True}}}))
    assert outbox.run(vault, NOW, {"beeper": send})["outbox_queued"] == 0  # the master switch

    write(
        rules,
        json.dumps({"enabled": True, "channels": {"whatsapp": {"on": True, "min_measured": 40}}}),
    )
    assert outbox.run(vault, NOW, {"beeper": send})["outbox_queued"] == 0  # 35 measured isn't 40

    write(rules, json.dumps({"enabled": True, "channels": {"whatsapp": {"on": True}}}))
    outbox.run(vault, NOW, {"beeper": send})
    (draft_id,) = [q["draft_id"] for q in state(vault)["queue"]]
    write(
        vault / "clones" / "outbox" / "cancelled.jsonl", json.dumps({"draft_id": draft_id}) + "\n"
    )
    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})
    assert not send.sent  # cancelled on the page

    for body, asks in (("yaa [time] works", "[]"), ("yaa coming", '["Going?"]')):
        (vault / "clones" / "outbox" / "cancelled.jsonl").unlink(missing_ok=True)
        (vault / "clones" / "outbox" / "state.json").unlink()
        reply(vault, draft_id, body, asks=asks)
        assert outbox.run(vault, NOW, {"beeper": send})["outbox_queued"] == 0


def test_a_reply_whose_chat_moved_on_or_that_fails_doesnt_go(vault):
    send = Sender(fail=True)
    outbox.run(vault, NOW, {"beeper": send})
    stats = outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})
    assert stats["outbox_failed"] == 1
    (entry,) = [
        json.loads(line)
        for line in (vault / "clones" / "outbox" / "log.jsonl").read_text().splitlines()
    ]
    assert entry["ok"] is False and "Beeper" in entry["error"]

    messages = vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl"
    messages.write_text(
        messages.read_text() + json.dumps(wa("2026-03-10T11:00:00Z", "also bring snacks")) + "\n"
    )
    ok = Sender()
    outbox.run(vault, NOW + timedelta(minutes=30), {"beeper": ok})
    outbox.run(vault, NOW + timedelta(minutes=45), {"beeper": ok})
    assert not ok.sent  # a new message: the draft no longer answers the chat


def test_rules_are_read_as_strictly_as_the_page_reads_them(tmp_path):
    write(
        tmp_path / "rules.json",
        json.dumps(
            {
                "enabled": "yes",
                "daily_limit": 500,
                "channels": {
                    "email": {"on": True, "min_closeness": 0.2, "min_measured": 3},
                    "whatsapp": {"on": True, "min_closeness": 0.95, "sign": "yes"},
                    "x": {"on": True, "min_share": 1, "min_closeness": 0.6, "sign": True},
                },
            }
        ),
    )
    rules = outbox.read_rules(tmp_path / "rules.json")
    assert rules["enabled"] is False and rules["daily_limit"] == 10
    email = {"on": True, "min_share": 0.9, "min_measured": 3, "sign": False}
    assert rules["channels"]["email"] == email
    # An older file's bar on the mean is read as the bar on the share; 1 can never be shown.
    assert rules["channels"]["whatsapp"]["min_share"] == 0.95
    assert rules["channels"]["whatsapp"]["sign"] is False
    assert rules["channels"]["x"]["min_share"] == 0.99 and rules["channels"]["x"]["sign"] is True
    assert outbox.read_rules(tmp_path / "missing.json")["channels"]["whatsapp"]["on"] is False


def log(vault):
    path = vault / "clones" / "outbox" / "log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_someone_new_is_never_answered_on_their_own(vault, monkeypatch):
    real = chats.waiting
    monkeypatch.setattr(
        chats, "waiting", lambda v, now: [c | {"first": True} for c in real(v, now)]
    )
    assert outbox.run(vault, NOW, {"beeper": Sender()})["outbox_queued"] == 0


@pytest.mark.parametrize(
    "body, why",
    [
        ("yaa coming, pay here first https://pay.example/x", "a link"),
        ("yaa coming, see www.pay.example", "a link"),
        ("yaa coming, write to desk@pay.example", "an email address"),
        ("yaa coming, call me on +1 (555) 010-2030", "a number"),
        ("yaa coming, the code is 482913", "a number"),
    ],
)
def test_a_reply_with_a_link_address_or_number_the_chat_never_had_is_held(vault, body, why):
    (path,) = (vault / "clones" / "drafts").glob("reply-*.md")
    reply(vault, path.stem, body)
    send = Sender()

    stats = outbox.run(vault, NOW, {"beeper": send})
    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})

    assert stats["outbox_held"] == 1 and stats["outbox_queued"] == 0 and not send.sent
    (entry,) = log(vault)  # logged once, not at every sync
    assert entry["ok"] is False and entry["held"].startswith(f"it has {why}")
    assert entry["error"].startswith("Held for you to send: ")
    assert "status: draft" in path.read_text()  # still the user's to send


def test_a_link_address_or_number_the_chat_already_had_can_go(vault):
    messages = vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl"
    asked = "coming? form at https://pay.example/x, or ring +1 (555) 010-2030 or desk@pay.example"
    write(
        messages,
        json.dumps(wa("2026-03-08T09:00:00Z", "door code is 4417 2290", mine=True))
        + "\n"
        + json.dumps(wa("2026-03-10T09:00:00Z", asked))
        + "\n",
    )
    (chat,) = chats.waiting(vault, NOW)
    body = (
        "yaa, done at https://pay.example/x, will ring 555-010-2030, cc DESK@pay.example. 44172290"
    )
    reply(vault, work.reply_key(chat), body)
    send = Sender()

    outbox.run(vault, NOW, {"beeper": send})
    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})

    assert [text for _, text in send.sent] == [body] and not log(vault)[0].get("held")


def mail(key, ts, sender, to, body, mine=False, **extra):
    return {
        "id": key,
        "ts": ts,
        "account": "work",
        "from_address": sender,
        "from_name": None if mine else "Ravi",
        "from_me": mine,
        "to": to,
        "cc": None,
        "subject": "Poster",
        "in_reply_to": None,
        "gmail_labels": None,
        "gmail_thread": "t1",
        "bulk": False,
        "body": body,
        "body_new": body,
        **extra,
    }


@pytest.mark.parametrize(
    "kept, held",
    [
        ({"reply_to": None}, None),
        ({"reply_to": ["Ravi@Lab.example"]}, None),
        ({"reply_to": ["billing@elsewhere.example"]}, "asks for replies to another address"),
        ({}, "read before Proxenos kept its Reply-To"),
    ],
)
def test_an_email_reply_goes_on_its_own_only_where_the_sender_asks(
    tmp_path, monkeypatch, kept, held
):
    monkeypatch.setenv("PROXENOS_EMAILS", "me@lab.example")
    write(
        tmp_path / "raw" / "email" / "work" / "2026-03.jsonl",
        json.dumps(
            mail(
                "m1",
                "2026-03-08T09:00:00Z",
                "me@lab.example",
                ["ravi@lab.example"],
                "here's the poster",
                mine=True,
                reply_to=None,
            )
        )
        + "\n"
        + json.dumps(
            mail(
                "m2",
                "2026-03-10T09:00:00Z",
                "ravi@lab.example",
                ["me@lab.example"],
                "thanks! can you send the final version?",
                **kept,
            )
        )
        + "\n",
    )
    (chat,) = chats.waiting(tmp_path, NOW)
    reply(tmp_path, work.reply_key(chat), "Sure, attaching it now.")
    measured(tmp_path, "email", [1.0] * 35)
    write(
        tmp_path / "clones" / "outbox" / "rules.json",
        json.dumps({"enabled": True, "channels": {"email": {"on": True}}}),
    )
    monkeypatch.setattr(
        outbox, "_routes", lambda: dict.fromkeys(outbox.CHANNELS) | {"email": "apple_mail"}
    )
    send = Sender()

    outbox.run(tmp_path, NOW, {"apple_mail": send})
    outbox.run(tmp_path, NOW + timedelta(minutes=15), {"apple_mail": send})

    if held:
        assert not send.sent and held in log(tmp_path)[0]["held"]
    else:
        ((thread, _),) = send.sent
        assert thread["last"] == "m2"


def test_wilson_bound_takes_35_unchanged_drafts_for_ninety_percent():
    assert outbox.needed(0.9) == 35
    assert outbox.wilson(35, 35) >= 0.9 > outbox.wilson(34, 34)
    assert outbox.wilson(0, 0) == 0 and outbox.wilson(38, 40) < 0.9


@pytest.mark.parametrize(
    "closeness, earned",
    [([1.0] * 35, True), ([1.0] * 34, False), ([1.0] * 34 + [0.5], False), ([0.95] * 60, True)],
)
def test_an_app_earns_sending_by_untouched_drafts_sent_nearly_unchanged(vault, closeness, earned):
    measured(vault, "whatsapp", closeness)
    outbox.run(vault, NOW, {"beeper": Sender()})
    assert state(vault)["earned"]["whatsapp"] is earned
    evidence = state(vault)["evidence"]["whatsapp"]
    assert evidence["n"] == len(closeness)
    assert evidence["unchanged"] == sum(c >= 0.9 for c in closeness)


def test_drafts_the_user_used_or_the_outbox_sent_dont_count(vault):
    measured(vault, "whatsapp", [1.0] * 40)
    used = [("copy", 0), ("opened", 1), ("edit", 2), ("approve", 3), ("sent", 4), ("discard", 5)]
    write(
        vault / "clones" / "drafts" / "feedback.jsonl",
        "".join(
            json.dumps({"draft_id": f"reply-past{i:08d}", "action": a}) + "\n" for a, i in used
        ),
    )
    thread = {"id": "t1", "context": {"kind": "draft", "id": "reply-past00000006"}}
    write(vault / "clones" / "think" / "t1.json", json.dumps(thread))
    sent = {"draft_id": "reply-past00000007", "ok": True, "at": "2026-03-01T00:00:00Z"}
    write(vault / "clones" / "outbox" / "log.jsonl", json.dumps(sent) + "\n")

    assert outbox.run(vault, NOW, {"beeper": Sender()})["outbox_queued"] == 0
    # 40 measured, less five used on the page, one thought through and one the outbox sent; a
    # discarded draft still counts, as a reply the user wouldn't have sent.
    assert state(vault)["evidence"]["whatsapp"]["n"] == 33
    assert not state(vault)["earned"]["whatsapp"]


def test_a_signed_reply_says_it_was_sent_by_the_assistant(vault):
    rules = {"enabled": True, "channels": {"whatsapp": {"on": True, "sign": True}}}
    write(vault / "clones" / "outbox" / "rules.json", json.dumps(rules))
    send = Sender()
    outbox.run(vault, NOW, {"beeper": send})
    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})
    ((_, text),) = send.sent
    assert text == "yaa coming" + outbox.SIGN


def held_for(vault, body, **front):
    """Why the outbox held a reply with `body` and these front matter fields, or None."""
    (path,) = (vault / "clones" / "drafts").glob("reply-*.md")
    reply(vault, path.stem, body)
    extra = "".join(f"{k}: {json.dumps(v)}\n" for k, v in front.items())
    path.write_text(path.read_text().replace("asks: []\n", "asks: []\n" + extra))
    send = Sender()
    outbox.run(vault, NOW, {"beeper": send})
    outbox.run(vault, NOW + timedelta(minutes=15), {"beeper": send})
    entries = log(vault)
    return entries[0].get("held") if entries else None


@pytest.mark.parametrize(
    "body, front, why",
    [
        ("yaa coming", {"found": "The trip is booked for Friday."}, "beyond this chat"),
        ("yaa coming, after the doctor", {}, "health (doctor)"),
        ("yaa coming, my back pain is better", {}, "health (pain)"),
        ("yaa coming with Priya", {}, "names something the chat doesn't (Priya)"),
        ("yaa coming, see you at Stanford", {}, "(Stanford)"),
    ],
)
def test_a_reply_drawing_on_more_than_its_chat_is_held(vault, body, front, why):
    assert why in (held_for(vault, body, **front) or "")


@pytest.mark.parametrize(
    "body",
    [
        "Yaa coming. See you Friday, Asha!",
        "yaa coming in March. Haha ok, Joe here",
        "yaa, I'm coming / Bringing snacks",
    ],
)
def test_names_days_and_sentence_starts_can_go(vault, monkeypatch, body):
    monkeypatch.setenv("PROXENOS_NAME", "Joe Bloggs")
    assert held_for(vault, body) is None


@pytest.mark.parametrize("kind", ["group", None])
def test_a_group_chat_or_one_whose_records_dont_say_is_held(vault, kind):
    # Asked back in a group within hours of the user's own message, so it waits on them.
    rows = [
        wa("2026-03-10T08:00:00Z", "see you soon", mine=True) | {"chat_type": kind},
        wa("2026-03-10T09:00:00Z", "coming friday?") | {"chat_type": kind},
    ]
    messages = vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl"
    messages.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert "a group" in (held_for(vault, "yaa coming") or "")


@pytest.mark.parametrize(
    "source, record, held",
    [
        ("linkedin", {"to": "Asha Rao"}, False),
        ("linkedin", {"to": "Asha Rao, Ben Ode"}, True),
        ("linkedin", {"conversation_type": "direct"}, False),
        ("linkedin", {}, True),
        ("twitter", {"conversation_type": "direct"}, False),
        ("twitter", {}, True),
        ("instagram", {"chat_type": "direct"}, False),
        ("facebook", {"chat_type": "group"}, True),
    ],
)
def test_each_chat_app_must_say_it_is_one_to_one(source, record, held):
    assert (outbox._kind(source, record) != "direct") is held


def test_an_email_to_others_too_is_held(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", "me@lab.example")
    chat = {"source": "email", "id": "m2", "waiting": [{"ts": "2026-03-10T09:00:00Z"}]}
    one = {"from_address": "ravi@lab.example", "to": ["me@lab.example"], "cc": None}
    for record, held in (
        (one, False),
        (one | {"cc": ["Ann <ann@lab.example>"]}, True),
        (one | {"to": ["me@lab.example", "team@lab.example"]}, True),
    ):
        monkeypatch.setattr(outbox, "_answered", lambda v, c, r=record: r)
        assert (outbox._group(tmp_path, chat) is not None) is held
    monkeypatch.delenv("PROXENOS_EMAILS")
    assert outbox._group(tmp_path, chat) is not None  # who the user is can't be told
