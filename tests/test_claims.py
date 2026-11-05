"""Claims in a draft that the user did something. Synthetic text only."""

from datetime import UTC, datetime

from proxenos import claims, voice
from proxenos.clones import work

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def test_a_claim_nothing_shows_becomes_a_question():
    text = "Hi Ana, I've actually just settled the invoice. Thanks."

    assert claims.unproven(text, []) == ["Did you already settle the invoice?"]
    assert claims.unproven("i paid last week", []) == ["Did you already pay last week?"]
    assert claims.unproven("I sent you the form on Monday, and she", []) == [
        "Did you already send them the form on Monday?"
    ]
    for said, ask in (
        ("I submitted my CV.", "Did you already submit my CV?"),
        ("I've booked the room", "Did you already book the room?"),
        ("I signed it", "Did you already sign it?"),
        ("I called my bank", "Did you already call your bank?"),
    ):
        assert claims.unproven(said, []) == [ask.replace("my CV", "your CV")]


def test_what_the_users_own_messages_show_is_not_asked_about():
    assert claims.unproven("I paid it", ["did the payment go through?"]) == []
    assert claims.unproven("I've sent it", ["Sending it now"]) == []
    # A message about something else doesn't show it.
    assert claims.unproven("I paid it", ["I called the bank"]) == ["Did you already pay it?"]


def test_only_a_plain_first_person_claim_counts():
    for text in (
        "I haven't paid yet.",
        "I will pay on Friday.",
        "Once I've paid, I'll send the receipt.",
        "If I sent it twice, tell me.",
        "Have I sent it? Did I sign?",
        "She paid and he signed.",
        "I'm calling you tomorrow.",
    ):
        assert claims.unproven(text, []) == [], text


def test_a_draft_asks_first_about_what_it_claims_and_the_model_asks_after():
    job = {"id": "reply-1", "for": "reply", "title": "T", "chat": None}
    answer = {
        "title": "T",
        "kind": "reply",
        "channel": "email",
        "to": "Ana",
        "body": "I paid it on Monday.",
        "asks": ["Which room?"],
    }

    draft = work._draft(job, answer, NOW, [])
    shown = work._draft(job, answer, NOW, ["I paid on Monday, check"])

    assert draft["asks"] == ["Did you already pay it on Monday?", "Which room?"]
    assert shown["asks"] == ["Which room?"]
    chat = {"own": ["thanks"], "recent": [], "waiting": [{"mine": True, "text": "payment sent"}]}
    assert work._said({"chat": chat}, "") == ["thanks", "payment sent"]


def test_every_drafting_prompt_says_never_to_claim_what_the_records_dont_show():
    assert "Never say Tess did something" in voice.rules("Tess")
