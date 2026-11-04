"""Examples of the user's own writing, picked for a draft, and the writing rules learned from
drafts the user changed, on a synthetic vault. A fake model, no real data."""

import json
import os
import re
from datetime import UTC, datetime

import pytest

from proxenos import chats, llm, master, voice

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
            wa("fam", "Family", 8, "dinner?", kind="group"),  # to everyone, days later
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


def test_a_draft_i_sent_as_written_is_no_example_of_mine_nor_evidence_for_a_rule(tmp_path):
    vault = tmp_path / "vault"
    write_month(
        vault,
        "whatsapp/messages",
        "2026-03",
        [
            wa("asha", "Asha", 1, "okiees see you thurs", mine=True),
            wa("asha", "Asha", 3, "Dear Asha, I would be delighted to come.", mine=True),
            wa("asha", "Asha", 9, "are you coming friday?"),
        ],
    )
    write_month(
        vault,
        "email/work",
        "2026-03",
        [sent(1, long("Dear Ana, thank you kindly for your note")), sent(2, long("hey ana so"))],
    )
    made = [["whatsapp", "asha/3/Dear Ash"], ["email", "e1"]]
    (vault / chats.DRAFTED).parent.mkdir(parents=True)
    (vault / chats.DRAFTED).write_text(json.dumps({"messages": made}))

    written = voice.Writing(vault)
    shown = voice.examples(written, None, name="Asha")
    checked_on = voice._sample(written, {"channel": "any", "to": ""}, set())

    assert [m["text"] for m in written.messages] == ["okiees see you thurs"]
    assert [t["text"][:7] for t in written.long] == ["hey ana"]
    assert "okiees" in shown and "hey ana" in shown
    assert "delighted" not in shown and "kindly" not in shown
    assert [m["text"][:7] for m in checked_on] == ["hey ana", "okiees "]


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


def test_drafts_i_changed_teach_the_next_one_with_what_i_sent(tmp_path):
    vault = chat_vault(tmp_path)
    measured = [
        {"source": "whatsapp", "to": "Ben", "closeness": 0.3, "draft_text": "Dear Ben, kindly.",
         "sent_text": "yo ben, all good"},
        {"source": "whatsapp", "to": "Asha", "closeness": 0.2, "draft_text": "Hello Asha!",
         "sent_text": "hey asha, ya sounds good"},
        {"source": "whatsapp", "to": "Asha", "closeness": 0.95, "draft_text": "same as sent",
         "sent_text": "same as sent"},  # barely changed: nothing to learn
        {"source": "email", "to": "ana@acme.org", "closeness": 0.1, "draft_text": "Hi Ana",
         "sent_text": "Ana, quick one about the grant"},
        {"source": "whatsapp", "to": "Cy", "closeness": 0.1, "draft_text": "Hi", "sent_text": "k"},
        "not a record",
    ]  # fmt: skip
    folder = vault / "clones" / "drafts"
    folder.mkdir(parents=True)
    (folder / "fidelity.json").write_text(json.dumps({"drafts": measured}))

    shown = voice.corrections(voice.Writing(vault), "whatsapp", "asha")

    assert shown.splitlines() == [
        "Drafts written for Tess that they changed before sending, newest first, each beside "
        "what they sent instead. Write like what they sent, never like the draft. " + voice._COPY,
        "<drafted>", "Hello Asha!", "</drafted>", "<sent>", "hey asha, ya sounds good", "</sent>",
        "<drafted>", "Dear Ben, kindly.", "</drafted>", "<sent>", "yo ben, all good", "</sent>",
    ]  # fmt: skip
    # Every draft to that channel gets them, after the examples of how Tess writes.
    examples = voice.examples(voice.Writing(vault), "whatsapp", name="Asha")
    assert examples.index("How Tess writes") < examples.index("<drafted>\nHello Asha!")
    assert "Ana, quick one" in voice.examples(voice.Writing(vault), "email")
    assert "Ana, quick one" not in examples
    assert voice.corrections(voice.Writing(tmp_path / "none"), None) == ""


def test_a_draft_i_rewrote_on_the_page_teaches_the_next_one(tmp_path):
    vault = chat_vault(tmp_path)
    folder = vault / "clones" / "drafts"
    folder.mkdir(parents=True)
    edits = [
        {"draft_id": "a", "action": "edit", "ts": "2026-03-09T10:00:00Z", "channel": "whatsapp",
         "to": "Asha", "before": "Dear Asha, I hope you are well.", "after": "hey asha!! all good?"},
        {"draft_id": "b", "action": "edit", "ts": "2026-03-09T11:00:00Z", "channel": "whatsapp",
         "to": "Ben", "before": "Same.", "after": "Same."},  # no change: nothing to learn
        {"draft_id": "c", "action": "copy", "ts": "2026-03-09T12:00:00Z"},
    ]  # fmt: skip
    (folder / "feedback.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edits))

    shown = voice.corrections(voice.Writing(vault), "whatsapp", "Asha")

    assert "<drafted>\nDear Asha, I hope you are well.\n</drafted>" in shown
    assert "<sent>\nhey asha!! all good?\n</sent>" in shown and "Same." not in shown


# Rules learned from drafts I changed

SENT = [  # what Tess sent instead of six drafts to Aai, the first also a message in their chat
    "ok aai coming sunday",
    "ho aai done",
    "yes yes all set",
    "theek aahe call later",
    "coming at six aai",
    "will bring it aai",
]
MINE = [  # her other messages to Aai, which the drafts weren't
    "haan will call you tonight",
    "reached home, all good",
    "kal bhetu, bye",
    "nako worry, all set here",
    "sending photos now",
]


class Teacher:
    """A fake model. Asked for rules, it gives `rules` (a text is a rule to Aai on WhatsApp);
    asked to check them, it judges each by its text as `verdicts` says: holding on every message
    it's asked about (the default), breaking on all of them, or holding on two ("few")."""

    def __init__(self, rules, verdicts=None):
        self.rules, self.verdicts, self.calls = rules, verdicts or {}, []

    def __call__(self, prompt, *, system=None, schema=None, **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        if "rules" in schema["properties"]:
            return {
                "rules": [
                    {"rule": r, "channel": "whatsapp", "to": "Aai"} if isinstance(r, str) else r
                    for r in self.rules
                ]
            }
        verdicts = []
        for n, ids, rule in re.findall(r'<rule n="(\d+)" messages="([\d, ]+)">(.*)</rule>', prompt):
            ids = [int(i) for i in ids.split(", ")]
            how = self.verdicts.get(rule, "holds")
            holds = {"holds": ids, "few": ids[:2]}.get(how, [])
            breaks = ids if how == "breaks" else []
            verdicts.append({"rule": int(n), "holds": holds, "breaks": breaks})
        return {"verdicts": verdicts}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))


def changed(vault, sent):
    """A draft to Aai for each text Tess sent instead, as fidelity measured them."""
    measured = [
        {"source": "whatsapp", "to": "Aai", "closeness": 0.2, "sent": f"2026-03-{day:02d}T10:00:00Z",
         "draft_text": f"Dear Mom, {text.capitalize()}. Best regards, Tess", "sent_text": text}
        for day, text in enumerate(sent, 1)
    ]  # fmt: skip
    folder = vault / "clones" / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fidelity.json").write_text(json.dumps({"drafts": measured}))


def lessons_vault(tmp_path):
    vault = tmp_path / "vault"
    write_month(
        vault,
        "whatsapp/messages",
        "2026-03",
        [
            wa("aai", "Aai", 1, SENT[0], mine=True),
            *(wa("aai", "Aai", day, text, mine=True) for day, text in enumerate(MINE, 2)),
            wa("aai", "Aai", 7, "jevlas ka? call me"),  # her words
            wa("ben", "Ben", 3, "can u send the pics"),
            wa("ben", "Ben", 4, "sure thing will do tonight", mine=True),
            wa("ben", "Ben", 5, "yep see you there", mine=True),
        ],
    )
    changed(vault, SENT)
    return vault


def test_a_rule_learned_from_drafts_i_changed_is_kept_only_where_my_messages_bear_it_out(
    tmp_path, monkeypatch
):
    vault = lessons_vault(tmp_path)
    teacher = Teacher(
        [
            "To Aai, all lower case, no sign-off",
            "To Aai, ends every message with a question",
            {"rule": "On WhatsApp, long formal paragraphs", "channel": "whatsapp", "to": ""},
            {"rule": "To Ben, one line", "channel": "whatsapp", "to": "Ben"},
        ],
        {
            "To Aai, ends every message with a question": "few",  # holds on two: not enough
            "On WhatsApp, long formal paragraphs": "breaks",
        },
    )
    monkeypatch.setattr(llm, "ask", teacher)

    stats = voice.lessons(vault, NOW)

    assert stats == {
        "new_changed_drafts": 6,
        "rules_inferred": 4,
        "rules_refused": 0,
        "rules_held": 1,
        "rules_proposed": 1,
    }
    infer, check = teacher.calls  # one batch of pairs, one of rules
    drafted = "<drafted>\nDear Mom, Ok aai coming sunday. Best regards, Tess\n</drafted>"
    assert drafted in infer["prompt"]
    assert '<pair n="1" channel="whatsapp" to="Aai">' in infer["prompt"]
    # Checked on what Tess sent Aai that no draft was, never on what Aai wrote.
    assert all(text in check["prompt"] for text in MINE)
    assert SENT[0] not in check["prompt"]
    assert "jevlas" not in infer["prompt"] + check["prompt"]
    assert "To Ben" not in check["prompt"]  # two of her messages to Ben: too few to check on
    # Proposed, not kept: no draft follows it until she accepts it.
    assert not (vault / voice.RULES_FILE).exists()
    proposal = (vault / voice.PROPOSED).read_text()
    assert proposal.startswith("# How Tess writes\n")
    assert voice._rules_in(proposal) == ["To Aai, all lower case, no sign-off"]
    assert voice.Writing(vault).rules == []


def test_a_rule_about_health_or_quoting_a_sentence_is_never_kept(tmp_path, monkeypatch):
    vault = lessons_vault(tmp_path)
    teacher = Teacher(
        [
            "To Aai, never mentions the doctor or how she slept",
            'To Aai, says "I will be there by six with everything you asked for"',
            'To Aai, opens with "ho aai"',  # a few of her own words may be quoted
        ]
    )
    monkeypatch.setattr(llm, "ask", teacher)

    stats = voice.lessons(vault, NOW)

    assert (stats["rules_inferred"], stats["rules_refused"], stats["rules_held"]) == (3, 2, 1)
    assert "doctor" not in teacher.calls[-1]["prompt"]
    assert "by six" not in teacher.calls[-1]["prompt"]
    assert voice._rules_in((vault / voice.PROPOSED).read_text()) == ['To Aai, opens with "ho aai"']
    assert not voice._allowed("Emails to the clinic: thanks first")
    assert voice._allowed("Emails to editors: two short paragraphs, thanks first")


def test_rules_i_accept_reach_every_draft_ahead_of_the_drafts_i_changed(tmp_path, monkeypatch):
    vault = lessons_vault(tmp_path)
    monkeypatch.setattr(llm, "ask", Teacher(["To Aai, all lower case, no sign-off"]))
    voice.lessons(vault, NOW)
    assert "no sign-off" not in voice.examples(voice.Writing(vault), "whatsapp", name="Aai")

    assert master.accept(vault) == {"accepted": 1}  # `proxenos master accept`
    path = vault / voice.RULES_FILE
    path.write_text(path.read_text() + "- Emails: no exclamation marks\n")  # and one of her own

    shown = voice.examples(voice.Writing(vault), "whatsapp", name="Aai")
    rules = shown.index("How Tess writes, in rules learned from drafts they changed")
    assert shown.index("How Tess writes, their own messages") < rules
    assert rules < shown.index("\n- To Aai, all lower case, no sign-off\n")
    assert shown.index("\n- Emails: no exclamation marks\n") < shown.index("<drafted>")
    monkeypatch.setattr(voice, "RULES_CHARS", len("To Aai, all lower case, no sign-off"))
    shown = voice.corrections(voice.Writing(vault), "whatsapp", "Aai")
    assert "no sign-off" in shown and "exclamation" not in shown  # capped


def test_only_new_changed_drafts_are_read_and_too_few_ask_no_model(tmp_path, monkeypatch):
    vault = lessons_vault(tmp_path)
    teacher = Teacher(["To Aai, all lower case, no sign-off"])
    monkeypatch.setattr(llm, "ask", teacher)
    voice.lessons(vault, NOW)
    state = json.loads((vault / voice.LESSONS).read_text())
    assert state["ran"] == "2026-03-10T12:00:00Z" and len(state["read"]) == len(SENT)
    if os.name != "nt":
        assert (vault / voice.LESSONS).stat().st_mode & 0o777 == 0o600
        assert (vault / voice.PROPOSED).stat().st_mode & 0o777 == 0o600
    teacher.calls.clear()

    assert voice.lessons(vault, NOW) == {"new_changed_drafts": 0}
    more = ["ok bye aai", "haan haan", "nahi aai later", "kal sangto aai", "done aai sorted"]
    changed(vault, [*SENT, *more[:4]])
    assert voice.lessons(vault, NOW) == {"new_changed_drafts": 4}
    assert teacher.calls == []

    # A fifth: only the new ones are read, and the rule she turned down isn't proposed again.
    (vault / voice.PROPOSED).unlink()
    changed(vault, [*SENT, *more])
    stats = voice.lessons(vault, NOW)
    assert (stats["new_changed_drafts"], stats["rules_proposed"]) == (5, 0)
    (infer,) = teacher.calls  # nothing new to check
    assert "kal sangto aai" in infer["prompt"] and SENT[1] not in infer["prompt"]
    assert not (vault / voice.PROPOSED).exists()
