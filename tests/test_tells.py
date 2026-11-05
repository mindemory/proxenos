"""The tells of a model's writing, taken out of drafts unless the user writes them. Synthetic
text and vaults only."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import tells, voice
from proxenos.clones import work

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def person(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_EMAILS", "tess@x.org")


def test_em_dashes_become_what_the_sentence_allows():
    assert tells.clean("The grant — due soon — needs a budget.") == (
        "The grant (due soon) needs a budget."
    )
    assert tells.clean("It is late — can we move it?") == "It is late, can we move it?"
    assert (
        tells.clean("It is late — Then again, it is fine.") == "It is late. Then again, it is fine."
    )
    assert tells.clean("pages 2–3 and a-b") == "pages 2–3 and a-b"  # an unspaced en dash is a range


def test_openers_and_a_stack_of_closers_go_and_what_they_carried_stays():
    body = (
        "Hi Ana,\n\nI hope this email finds you well. I wanted to reach out to ask about the grant.\n"
        "Just following up on the invoice.\n\nPlease don't hesitate to reach out if you have "
        "questions. Looking forward to hearing from you!\n\nBest,\nTess"
    )

    assert tells.clean(body) == (
        "Hi Ana,\n\nI'm writing to ask about the grant.\nFollowing up on the invoice.\n\nBest,\nTess"
    )
    assert tells.clean("Hi Ana, I hope you're doing well. Thanks for the file.") == (
        "Hi Ana, Thanks for the file."
    )
    # A lone "looking forward" is the one closer, and what isn't a tell is never touched.
    assert tells.clean("Looking forward to hearing from you.") == (
        "Looking forward to hearing from you."
    )
    assert tells.clean("I hope you're well enough to come.") == "I hope you're well enough to come."


def test_the_words_are_swapped_for_plain_ones_and_only_a_figurative_navigate():
    text = (
        "We can delve into a robust, seamless plan to leverage it. Crucial and pivotal. "
        "Navigate the process. Navigate to the page. I'd be more than happy to help."
    )

    assert tells.clean(text) == (
        "We can look into a solid, smooth plan to use it. Important and key. "
        "Work through the process. Navigate to the page. I'm glad to help."
    )


def test_thanks_so_much_is_kept_once_and_exclamations_to_one():
    text = "Thank you so much for the file! Thank you so much for the call! Great! Yes!!"

    assert tells.clean(text) == "Thank you so much for the file! Thanks for the call. Great. Yes."


def test_a_chat_message_loses_the_sign_off_and_title_block_but_an_email_keeps_it():
    text = "Sounds good\n\nBest,\nTess Bloggs\nProfessor of Baking"

    assert tells.clean(text, chat=True) == "Sounds good"
    assert tells.clean("Sounds good\nBest, Tess Bloggs", chat=True) == "Sounds good"
    assert tells.clean(text) == text
    assert tells.clean("Best,\nme\nI will call you tomorrow, and we can talk.", chat=True) == (
        "Best,\nme\nI will call you tomorrow, and we can talk."
    )


def test_a_tell_is_theirs_only_when_several_of_their_own_texts_use_it():
    own = ["a — b", "c — d", "plain", "plain too"] + ["fine"] * 50
    stray = ["a — b"] + ["fine"] * 50

    assert tells.used(own) == frozenset({"em dash"})  # twice, and 2 in 54 is over 1 in 50
    assert tells.used(stray) == frozenset()  # once is a stray
    assert tells.used(["a — b", "c — d"] + ["fine"] * 200) == frozenset()  # 2 in 202 is noise
    assert tells.frequencies(["a — b", "c"])["em dash"] == 0.5
    assert tells.frequencies([])["em dash"] == 0.0
    assert tells.clean("x — y", tells.used(own)) == "x — y"


def write_chats(vault, texts):
    path = vault / "raw" / "whatsapp" / "messages" / "2026-10.jsonl"
    path.parent.mkdir(parents=True)
    records = []
    for n, text in enumerate(texts):
        for mine, said in ((False, "hello there"), (True, text)):
            records.append(
                {
                    "id": f"m{n}{mine}",
                    "ts": f"2026-10-{n + 1:02d}T09:0{int(mine)}:00Z",
                    "chat_id": f"c{n}",
                    "chat_name": "Ana",
                    "chat_type": "direct",
                    "from_me": mine,
                    "sender_name": None if mine else "Ana",
                    "text": said,
                }
            )
    path.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")


def draft_for(vault, body, channel="whatsapp"):
    job = {"id": "reply-1", "for": "reply", "title": "T", "chat": None, "channel": channel}
    answer = {"title": "T", "kind": "reply", "channel": channel, "to": "Ana", "body": body}
    return work._draft(job, answer, NOW, [], voice.Writing(vault))["body"]


def test_a_user_who_writes_em_dashes_keeps_them_and_one_who_doesnt_loses_them(tmp_path):
    dashes = tmp_path / "with"
    write_chats(dashes, ["yes — see you then", "ok — thanks a lot", "fine — talk soon"])
    plain = tmp_path / "without"
    write_chats(plain, ["yes see you then", "ok thanks a lot", "fine talk soon"])
    body = "Thursday works — see you there.\n\nBest,\nTess Bloggs"

    assert "em dash" in voice.Writing(dashes).tells
    assert "em dash" not in voice.Writing(plain).tells
    assert draft_for(dashes, "Thursday works — see you there.") == "Thursday works — see you there."
    assert draft_for(plain, "Thursday works — see you there.") == "Thursday works, see you there."
    # In a chat the signature goes too; an email draft keeps it.
    assert draft_for(plain, body) == "Thursday works, see you there."
    assert draft_for(plain, body, "email").endswith("Best,\nTess Bloggs")


def test_every_drafting_prompt_lists_the_tells_with_the_users_own_exception():
    rules = voice.rules("Tess")

    assert "Never write these tells of an AI's writing, unless their own examples use them" in rules
    for tell in ("em dashes", "I wanted to reach out", "delve", "I'd be more than happy to"):
        assert tell in rules
