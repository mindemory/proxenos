"""`proxenos ask`, with the model faked out. No model, no real data."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import ask

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
PNG = {"type": "image/png", "data": "iVBORw0KGgo="}


class Model:
    def __init__(self, draft_body="Hi Ana, thanks a lot."):
        self.calls, self.draft_body = [], draft_body

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", images=None, **kw):
        self.calls.append({"prompt": prompt, "schema": schema, "images": images, "effort": effort})
        props = (schema or {}).get("properties", {})
        if "seen" in props:
            return {
                "seen": "Ana Lee: we have chosen another candidate for the role.",
                "from": "Ana Lee",
            }
        if "searches" in props:
            return {"searches": []}
        return {
            "answer": "It's a polite no; answer warmly.",
            "draft_to": "Ana Lee",
            "draft_channel": "email",
            "draft_body": self.draft_body,
            "found": "You met Ana in August.",
            "asks": ["Mention your health?", " "],
        }


def test_a_screenshot_is_read_researched_answered_and_its_reply_drafted(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    model = Model()

    result = ask.ask(tmp_path, "how should I reply?", [PNG], NOW, model)

    see, answer = model.calls[0], model.calls[-1]
    assert see["images"] == [PNG] and "how should I reply?" in see["prompt"]
    assert "chosen another candidate" in answer["prompt"] and answer["effort"] == "high"
    assert result["status"] == "done" and result["asks"] == ["Mention your health?"]
    assert result["draft"] == {
        "to": "Ana Lee",
        "channel": "email",
        "body": "Hi Ana, thanks a lot.",
    }
    saved = json.loads((tmp_path / "clones" / "ask" / "ask-20260310T120000Z.json").read_text())
    assert saved == result
    draft = (tmp_path / "clones" / "drafts" / "ask-20260310T120000Z.md").read_text()
    assert "for: ask" in draft and "Hi Ana, thanks a lot." in draft


def test_a_question_without_a_message_has_no_draft_and_a_failure_is_kept(tmp_path):
    result = ask.ask(tmp_path, "what's on this week?", [], NOW, Model(draft_body=""))
    assert result["draft"] is None and not (tmp_path / "clones" / "drafts").exists()

    def broken(prompt, **kw):
        raise RuntimeError("the local model isn't answering")

    failed = ask.ask(tmp_path, "anything", [], NOW, broken)
    assert failed["status"] == "failed" and "isn't answering" in failed["error"]


def test_the_pages_request_keeps_only_what_is_well_formed():
    line = json.dumps({"text": "hi", "images": [PNG, {"type": "image/gif", "data": "x"}, "junk"]})
    assert ask.read_request(line) == ("hi", [PNG])
    with pytest.raises(SystemExit):
        ask.read_request(json.dumps({"text": "  ", "images": []}))
