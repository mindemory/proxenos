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
    write(
        tmp_path / "clones" / "drafts" / "fidelity.json",
        json.dumps({"by_source": {"whatsapp": {"n": 6, "mean": 0.95}}}),
    )
    write(
        tmp_path / "clones" / "outbox" / "rules.json",
        json.dumps({"enabled": True, "channels": {"whatsapp": {"on": True}}}),
    )
    monkeypatch.setattr(
        outbox, "_routes", lambda: dict.fromkeys(outbox.CHANNELS) | {"whatsapp": "beeper"}
    )
    return tmp_path


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
        json.dumps({"enabled": True, "channels": {"whatsapp": {"on": True, "min_measured": 10}}}),
    )
    assert outbox.run(vault, NOW, {"beeper": send})["outbox_queued"] == 0  # 6 measured isn't 10

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
                "channels": {"email": {"on": True, "min_closeness": 0.2, "min_measured": 3}},
            }
        ),
    )
    rules = outbox.read_rules(tmp_path / "rules.json")
    assert rules["enabled"] is False and rules["daily_limit"] == 10
    assert rules["channels"]["email"] == {"on": True, "min_closeness": 0.9, "min_measured": 3}
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
    write(
        tmp_path / "clones" / "drafts" / "fidelity.json",
        json.dumps({"by_source": {"email": {"n": 6, "mean": 0.95}}}),
    )
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
