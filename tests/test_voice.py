"""Examples of the user's own writing, picked for a draft, on a synthetic vault. No model, no
real data."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import chats, voice

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def person(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_EMAILS", "tess@x.org")


def write_month(vault, folder, month, records):
    path = vault / "raw" / folder / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in records))


def wa(chat, name, day, text, mine=False, kind="direct"):
    return {
        "id": f"{chat}/{day}/{text[:8]}",
        "ts": f"2026-03-{day:02d}T09:00:00Z",
        "chat_id": chat,
        "chat_name": name,
        "chat_type": kind,
        "from_me": mine,
        "sender_name": None if mine else name,
        "text": text,
    }


def sent(n, body_new, to=("ana@acme.org",), month="2026-03", **fields):
    return {
        "id": f"e{n}",
        "ts": f"{month}-{n:02d}T10:00:00Z",
        "from_address": "tess@x.org",
        "from_me": True,
        "to": list(to),
        "cc": None,
        "subject": f"Note {n}",
        "body_new": body_new,
        "body": body_new + "\n\nOn Monday, Ana wrote:\n> the quoted words of someone else",
    } | fields


def long(text):
    return (text + " ") * (voice.LONG_MIN // len(text) + 1)


def chat_vault(tmp_path):
    vault = tmp_path / "vault"
    write_month(
        vault,
        "whatsapp/messages",
        "2026-03",
        [
            wa("asha", "Asha", 1, "okiees see you thurs", mine=True),
            wa("asha", "Asha", 2, "ok", mine=True),  # too short to show anything
            wa("asha", "Asha", 3, "lol yaa that was wild", mine=True),
            wa("asha", "Asha", 9, "are you coming friday?"),
            wa("ben", "Ben", 4, "can u send the pics"),
            wa("ben", "Ben", 5, "sure thing will do tonight", mine=True),
            wa("ben", "Ben", 7, "👍 👍", mine=True),
            wa("fam", "Family", 6, "home by 8 probably", mine=True, kind="group"),
            wa("fam", "Family", 6, "dinner?", kind="group"),
            wa("me", "Tess", 8, "headache again, log it", mine=True),  # a note to self
        ],
    )
    write_month(
        vault,
        "instagram/messages",
        "2026-03",
        [
            {
                "id": "ig1",
                "ts": "2026-03-08T09:00:00Z",
                "chat_id": "ig-asha",
                "chat_name": "Asha",
                "chat_type": "direct",
                "from_me": True,
                "author": "Tess",
                "text": "omg this reel is so us",
            },
            {
                "id": "ig2",
                "ts": "2026-03-08T09:01:00Z",
                "chat_id": "ig-asha",
                "chat_name": "Asha",
                "chat_type": "direct",
                "from_me": False,
                "author": "Asha",
                "text": "hahaha",
            },
        ],
    )
    return vault


def test_a_reply_shows_my_messages_in_that_chat_then_on_that_channel_newest_first(tmp_path):
    vault = chat_vault(tmp_path)
    (chat,) = chats.waiting(vault, NOW)

    shown = voice.examples(
        voice.Writing(vault), chat["source"], chat=(chat["source"], chat["chat"]), here=chat["own"]
    )

    assert shown.splitlines() == [
        "How Tess writes, their own messages, newest first. " + voice._COPY,
        "In this conversation:",
        "- lol yaa that was wild",
        "- okiees see you thurs",
        "To others on WhatsApp:",
        "- home by 8 probably",
        "- sure thing will do tonight",
    ]  # not "ok" or an emoji, nor anyone else's words, the note to self or another channel


def test_a_message_to_someone_by_name_shows_our_chat_first(tmp_path):
    vault = chat_vault(tmp_path)
    written = voice.Writing(vault)

    shown = voice.examples(written, "whatsapp", name="  asha ")
    assert shown.splitlines()[1:4] == [
        "In their chat with Asha:",
        "- lol yaa that was wild",
        "- okiees see you thurs",
    ]
    assert "reel" not in shown

    # No chat by that name: what they wrote others on the channel. None there: nothing.
    shown = voice.examples(written, "instagram", name="Nobody")
    assert shown.splitlines()[1:] == ["On Instagram:", "- omg this reel is so us"]
    assert voice.examples(written, "messenger", name="Asha") == ""


def test_slack_examples_stay_in_the_workspace(tmp_path):
    vault = tmp_path / "vault"
    for team, text in (("lab", "pushed the fix, can u check"), ("club", "see yall at the crag")):
        write_month(
            vault,
            f"slack/{team}/messages",
            "2026-03",
            [
                {
                    "id": f"{team}1",
                    "ts": "2026-03-02T09:00:00Z",
                    "slack_ts": "1.0",
                    "channel_id": "D1",
                    "channel_name": "Ana",
                    "channel_type": "dm",
                    "user_id": "U2",
                    "user_name": "Ana",
                    "from_me": False,
                    "text": "hey there",
                },
                {
                    "id": f"{team}2",
                    "ts": "2026-03-03T09:00:00Z",
                    "slack_ts": "2.0",
                    "channel_id": "D1",
                    "channel_name": "Ana",
                    "channel_type": "dm",
                    "user_id": "U1",
                    "user_name": "Tess",
                    "from_me": True,
                    "text": text,
                },
            ],
        )

    shown = voice.examples(voice.Writing(vault), "slack", chat=("slack", "lab/D9"), here=[])

    assert "pushed the fix" in shown and "crag" not in shown


def test_examples_are_capped_and_the_newest_kept(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    texts = [f"message number {n:02d} from me" for n in range(1, 29)]
    write_month(
        vault,
        "whatsapp/messages",
        "2026-03",
        [wa("ben", "Ben", 1, "hi there you")]
        + [wa("ben", "Ben", n, text, mine=True) for n, text in enumerate(texts, 1)],
    )
    monkeypatch.setattr(voice, "MESSAGE_CHARS", 100)

    shown = voice.examples(voice.Writing(vault), "whatsapp")

    listed = [line[2:] for line in shown.splitlines() if line.startswith("- ")]
    assert listed == texts[::-1][: len(listed)] and sum(map(len, listed)) <= 100
    assert len(listed) == 100 // len(texts[0])


def test_only_the_months_read_count(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    write_month(vault, "whatsapp/messages", "2025-01", [wa("ben", "Ben", 1, "an old one now")])
    write_month(vault, "whatsapp/messages", "2025-01", [wa("ben", "Ben", 2, "said long ago", True)])
    write_month(vault, "whatsapp/messages", "2026-03", [wa("ben", "Ben", 1, "a new one now")])
    write_month(
        vault, "whatsapp/messages", "2026-03", [wa("ben", "Ben", 2, "said this week", True)]
    )
    monkeypatch.setattr(voice, "MONTHS", 1)

    shown = voice.examples(voice.Writing(vault), "whatsapp")

    assert "said this week" in shown and "said long ago" not in shown


def long_vault(tmp_path):
    vault = tmp_path / "vault"
    write_month(
        vault,
        "email/tess",
        "2026-03",
        [
            sent(1, long("Hi Ana, I think the poster is kind of done.") + "\n\n\n\nbest,\nT"),
            sent(2, "Thanks, will do!"),  # short
            sent(3, long("Notes to self about the draft."), to=["tess@x.org"]),  # to themselves
            sent(4, long("I forwarded it."), from_me=False, from_address="ana@acme.org"),
            sent(5, ""),  # nothing of their own: only what they quoted
        ],
    )
    for n, month in enumerate(("2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02")):
        write_month(
            vault, "email/tess", month, [sent(n + 6, long(f"Older note {month}."), month=month)]
        )
    write_month(
        vault,
        "twitter/posts",
        "2026-02",
        [
            {"id": "t1", "ts": "2026-02-03T09:00:00Z", "from_me": True, "text": long("my tweet")},
            {"id": "t2", "ts": "2026-02-04T09:00:00Z", "from_me": False, "text": long("RT them")},
        ],
    )
    write_month(
        vault,
        "bluesky/posts",
        "2026-02",
        [
            {"id": "b1", "ts": "2026-02-05T09:00:00Z", "kind": "post", "text": long("my skeet")},
            {"id": "b2", "ts": "2026-02-06T09:00:00Z", "kind": "repost", "text": long("a repost")},
        ],
    )
    write_month(
        vault,
        "website/pages",
        "2026-01",
        [
            {
                "id": "p1",
                "ts": "2026-01-05T09:00:00Z",
                "kind": "post",
                "title": 'On "spirals"',
                "text": long("An essay of mine."),
            },
            {
                "id": "p2",
                "ts": "2026-01-06T09:00:00Z",
                "kind": "page",
                "title": "Publications",
                "text": long("A list of papers."),
            },
        ],
    )
    return vault


def test_longer_writing_is_my_sent_email_and_my_posts(tmp_path):
    vault = long_vault(tmp_path)

    written = voice.Writing(vault)
    shown = voice.examples(written, "email")

    assert "Hi Ana, I think the poster is kind of done." in shown
    assert "best,\nT" in shown and "\n\n\n" not in shown  # their own line breaks, tidied
    assert '<example kind="email" date="2026-03-01" title="Note 1">' in shown
    for missing in ("quoted words", "Thanks, will do", "Notes to self", "I forwarded it"):
        assert missing not in shown
    assert "Older note 2025-09" not in json.dumps(written.long)  # past the months chats reads
    assert "my tweet" in shown and "my skeet" in shown
    assert '<example kind="post" date="2026-01-05" on="website" title="On \'spirals\'">' in shown
    for missing in ("RT them", "a repost", "A list of papers"):
        assert missing not in shown
    assert shown.index("Hi Ana") < shown.index("Older note 2026-02") < shown.index("my skeet")

    posts_first = voice.examples(written, "other", first="post")
    assert (
        posts_first.index("my skeet") < posts_first.index("my tweet") < posts_first.index("Hi Ana")
    )


def test_longer_writing_is_cut_and_capped(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    write_month(
        vault, "email/tess", "2026-03", [sent(n, long(f"Mail {n}.") * 9) for n in range(1, 9)]
    )
    monkeypatch.setattr(voice, "LONG_CHARS", 3500)

    shown = voice.longer(voice.Writing(vault))

    pieces = shown.split("</example>")[:-1]
    assert len(pieces) == 2 and "Mail 8." in pieces[0] and "Mail 7." in pieces[1]
    assert all(len(p.split(">\n", 1)[1]) <= voice.EXAMPLE_CHARS + 1 for p in pieces)
    assert pieces[0].rstrip().endswith("…")


def test_not_knowing_the_channel_shows_both_and_none_is_nothing(tmp_path):
    vault = chat_vault(tmp_path)
    write_month(vault, "email/tess", "2026-03", [sent(1, long("Hi Ana, sure."))])

    shown = voice.examples(voice.Writing(vault), None)

    assert shown.index("In their chats:") < shown.index("- omg this reel") < shown.index("Hi Ana")
    assert voice.examples(voice.Writing(tmp_path / "empty"), None) == ""


def test_the_rules_say_how_not_to_write_like_a_model():
    rules = voice.rules("Tess")
    for text in (
        "not as an AI writes",
        "never what to say",
        '"I think", "kind of"',
        "No em dashes",
        "It's not X, it's Y",
        "lists of three",
        "moral at the end",
        "headings or bold in a message",
        "I hope this finds you well",
        "more polished or more organized",
    ):
        assert text in rules
    assert "—" not in rules
