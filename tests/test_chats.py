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


def slack(channel, ts, text, user="U2", name="Ana", kind="channel", thread=None, mine=False):
    return {
        "id": f"{channel}/{ts}",
        "ts": ts,
        "slack_ts": ts,
        "thread_ts": thread,
        "channel_id": channel,
        "channel_name": name if kind == "dm" else "lab",
        "channel_type": kind,
        "user_id": "U1" if mine else user,
        "user_name": "Me" if mine else name,
        "from_me": mine,
        "text": text,
    }


def test_slack_dms_and_threads_that_mention_the_user_or_they_are_in(tmp_path):
    write_jsonl(
        tmp_path / "raw" / "slack" / "lab" / "messages" / "2026-03.jsonl",
        [
            slack("D1", "2026-03-01T09:00:00Z", "sure thing", kind="dm", mine=True),
            slack("D1", "2026-03-09T09:00:00Z", "can you send the slides?", kind="dm"),
            slack("C1", "2026-03-09T09:00:00Z", "<@U1> could you check the run?"),
            slack("C1", "2026-03-09T10:00:00Z", "anyone free for lunch today?"),  # not to them
            slack("C1", "2026-03-08T09:00:00Z", "the new data is up"),
            slack(
                "C1",
                "2026-03-08T09:05:00Z",
                "nice, thanks",
                mine=True,
                thread="2026-03-08T09:00:00Z",
            ),
            slack(
                "C1", "2026-03-09T11:00:00Z", "did it load for you?", thread="2026-03-08T09:00:00Z"
            ),
        ],
    )

    found = {c["chat"]: c for c in chats.waiting(tmp_path, NOW)}

    assert set(found) == {"lab/D1", "lab/C1/2026-03-09T09:00:00Z", "lab/C1/2026-03-08T09:00:00Z"}
    assert found["lab/D1"]["name"] == "Ana"
    mention = found["lab/C1/2026-03-09T09:00:00Z"]
    assert (mention["source"], mention["name"]) == ("slack", "#lab")
    assert [m["text"] for m in mention["waiting"]] == ["@Me could you check the run?"]
    assert mention["own"] == ["sure thing", "nice, thanks"]  # how they write in the workspace
    assert [m["text"] for m in found["lab/C1/2026-03-08T09:00:00Z"]["waiting"]] == [
        "did it load for you?"
    ]


def test_instagram_chats_count_like_messenger(tmp_path):
    def ig(ts, text, mine=False):
        return {
            "ts": ts,
            "chat_id": "ana_1",
            "chat_name": "Ana",
            "chat_type": "direct",
            "from_me": mine,
            "author": None if mine else "Ana",
            "text": text,
        }

    write_jsonl(
        tmp_path / "raw" / "instagram" / "messages" / "2026-03.jsonl",
        [
            ig("2026-03-08T09:00:00Z", "haha yes", mine=True),
            ig("2026-03-09T09:00:00Z", "coming sat?"),
        ],
    )

    (chat,) = chats.waiting(tmp_path, NOW)

    assert (chat["source"], chat["name"], chat["own"]) == ("instagram", "Ana", ["haha yes"])


def test_mail_without_a_thread_id_threads_by_subject_and_people_and_skips_the_unanswerable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PROXENOS_EMAILS", "me@x.org")

    def apple(ts, sender, to, text, subject, mine=False, **extra):
        return mail(None, ts, sender, to, text, mine) | {"subject": subject} | extra

    write_jsonl(
        tmp_path / "raw" / "email" / "me-x-org" / "2026-03.jsonl",
        [
            apple(
                "2026-03-01T09:00:00Z", "me@x.org", ["ana@x.org"], "Draft attached.", "Paper", True
            ),
            apple(
                "2026-03-08T09:00:00Z",
                "ana@x.org",
                ["me@x.org"],
                "Looks good, one question?",
                "Re: Paper",
            ),
            apple(
                "2026-03-09T09:00:00Z", "ana@x.org", ["me@x.org"], "Also, the figure?", "RE: paper"
            ),
            apple(
                "2026-03-09T09:00:00Z", "no-reply@x.org", ["me@x.org"], "Your code is 123?", "Code"
            ),
            apple(
                "2026-03-09T09:00:00Z",
                "ana@x.org",
                ["me@x.org"],
                "Lab news this week!",
                "News",
                bulk=True,
            ),
        ],
    )

    (chat,) = chats.waiting(tmp_path, NOW)

    assert chat["chat"] == "paper|ana@x.org"
    assert [m["text"] for m in chat["waiting"]] == [
        "Looks good, one question?",
        "Also, the figure?",
    ]
    assert chat["own"] == ["Draft attached."]
