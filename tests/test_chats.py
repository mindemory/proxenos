"""Chats waiting on the user, from synthetic raw messages. No real data."""

import json
from datetime import UTC, datetime

from proxenos import chats

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n", "utf-8")


def wa(chat, ts, text, mine=False, kind="direct", name=None):
    name = name or chat.title()
    return {
        "id": f"{chat}/{ts}",
        "ts": ts,
        "chat_id": chat,
        "chat_name": name,
        "chat_type": kind,
        "from_me": mine,
        "sender_name": None if mine else name,
        "text": text,
    }


def test_finds_direct_chats_where_someone_else_had_the_last_word(tmp_path):
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("asha", "2026-02-01T09:00:00Z", "old news", mine=True),
            wa("asha", "2026-03-08T09:00:00Z", "see  you\n\nsoon", mine=True),
            wa("asha", "2026-03-09T09:00:00Z", "are you okay?"),
            wa("asha", "2026-03-09T09:01:00Z", ""),  # a photo: no text
            wa("ben", "2026-03-09T09:00:00Z", "are you around?"),
            wa("ben", "2026-03-09T09:05:00Z", "yaa", mine=True),  # answered
            wa("crew", "2026-03-01T09:00:00Z", "hi all", mine=True, kind="group"),
            wa("crew", "2026-03-09T09:00:00Z", "who is in?", kind="group"),  # a group
            wa(
                "shop", "2026-03-09T09:00:00Z", "your order shipped, any questions?"
            ),  # never answered
            wa("jo", "2026-03-01T09:00:00Z", "thanks!", mine=True),
            wa("jo", "2026-03-09T09:00:00Z", "ok"),  # says nothing to answer
            wa("kim", "2026-02-01T09:00:00Z", "hey", mine=True),
            wa("kim", "2026-02-02T09:00:00Z", "what about it?"),  # over a week old
        ],
    )

    (chat,) = chats.waiting(tmp_path, NOW)

    assert (chat["source"], chat["chat"], chat["name"]) == ("whatsapp", "asha", "Asha")
    assert chat["since"] == "2026-03-09T09:00:00Z"
    assert [m["text"] for m in chat["waiting"]] == ["are you okay?"]
    assert [m["text"] for m in chat["recent"]] == ["see you / soon"]  # within 30 days, before it
    assert chat["own"] == ["old news", "see you / soon"]


def test_linkedin_conversations_count_but_not_sponsored_ones(tmp_path):
    def li(conv, ts, text, mine=False, folder="INBOX"):
        author = "Me Myself" if mine else "Sara Example"
        return {
            "id": f"{conv}/{ts}",
            "ts": ts,
            "conversation_id": conv,
            "conversation_title": None,
            "from_me": mine,
            "author": author,
            "to": "x",
            "text": text,
            "folder": folder,
        }

    write_jsonl(
        tmp_path / "raw" / "linkedin" / "messages" / "2026-03.jsonl",
        [
            li("c1", "2026-03-01T09:00:00Z", "nice to meet you", mine=True),
            li("c1", "2026-03-09T09:00:00Z", "Something to consider: https://example.org/b"),
            li("c2", "2026-03-01T09:00:00Z", "hi", mine=True, folder="SPONSORED"),
            li("c2", "2026-03-09T09:00:00Z", "a great offer for you?", folder="SPONSORED"),
        ],
    )

    (chat,) = chats.waiting(tmp_path, NOW)

    assert (chat["source"], chat["name"]) == ("linkedin", "Sara Example")
    assert chat["waiting"][0]["sender"] == "Sara Example"


def mail(thread, ts, sender, to, text, mine=False, labels=("Inbox",)):
    return {
        "id": f"<{thread}.{ts}@x>",
        "ts": ts,
        "from_address": sender,
        "from_name": None if mine else sender.split("@")[0].title(),
        "from_me": mine,
        "to": list(to),
        "cc": None,
        "subject": "Hi",
        "gmail_thread": thread,
        "gmail_labels": list(labels),
        "body_new": text,
    }


def test_an_email_waits_when_addressed_to_the_user_by_someone_they_write_to(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", "me@x.org")
    many = [f"p{n}@x.org" for n in range(8)]
    write_jsonl(
        tmp_path / "raw" / "email" / "me-x-org" / "2026-03.jsonl",
        [
            mail(
                "t1", "2026-02-20T09:00:00Z", "me@x.org", ["Ana <ana@x.org>"], "Hi Ana, sure.", True
            ),
            mail(
                "t2", "2026-03-09T09:00:00Z", "ana@x.org", ["me@x.org"], "Can you review my draft?"
            ),
            mail(
                "t3",
                "2026-03-09T09:00:00Z",
                "ana@x.org",
                ["list@x.org"],
                "Talk at noon, all welcome?",
            ),
            mail("t4", "2026-03-09T09:00:00Z", "ana@x.org", ["me@x.org", *many], "Who is coming?"),
            mail("t5", "2026-03-09T09:00:00Z", "news@x.org", ["me@x.org"], "Any questions? Reply!"),
            mail(
                "t6",
                "2026-03-09T09:00:00Z",
                "ana@x.org",
                ["me@x.org"],
                "Sale on now, want it?",
                labels=("Inbox", "Category Promotions"),
            ),
        ],
    )

    (chat,) = chats.waiting(tmp_path, NOW)

    assert (chat["source"], chat["chat"], chat["name"]) == ("email", "t2", "Ana")
    assert [m["text"] for m in chat["waiting"]] == ["Can you review my draft?"]
    assert chat["own"] == ["Hi Ana, sure."]  # what they wrote Ana in another thread
