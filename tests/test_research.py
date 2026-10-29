"""Research before a reply, with the model faked out. No model, no real data."""

from proxenos import llm, research


def hit(i, text):
    return {
        "id": f"r{i}",
        "source": "email",
        "ts": "2026-07-09T12:00:00Z",
        "who": "Journal",
        "where_": "",
        "title": "",
        "snippet": text,
        "from_me": False,
    }


def test_the_gate_keeps_what_the_reply_depends_on_and_everything_if_it_cannot_say():
    hits = [hit(1, "abstract deadline May 31"), hit(2, "the revision is due by 7th Oct")]
    asked = []

    def ask(prompt, **kwargs):
        asked.append(prompt)
        return {"keep": [2, 9, "1"]}  # out of range and non-numbers are ignored

    kept = research._gate("Chat: when is the paper due?", hits, "Tess", ask)

    assert [h["id"] for h in kept] == ["r2"]
    assert "1. [2026-07-09, email, email] Journal: abstract deadline May 31" in asked[0]

    def muddled(prompt, **kwargs):
        raise llm.ModelError("not the JSON asked for")

    assert research._gate("Chat", hits, "Tess", muddled) == hits
    assert research._gate("Chat", [], "Tess", muddled) == []
