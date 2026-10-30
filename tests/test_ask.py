"""`proxenos ask`, with the model faked out. No model, no real data."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import ask, voice

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
PNG = {"type": "image/png", "data": "iVBORw0KGgo="}


class Model:
    def __init__(self, draft_body="Hi Ana, thanks a lot."):
        self.calls, self.draft_body = [], draft_body

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", images=None, **kw):
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "schema": schema,
                "images": images,
                "effort": effort,
            }
        )
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

    result = ask.ask(tmp_path, "how should I reply?", [PNG], NOW, model, deep=True)

    see, answer = model.calls[0], model.calls[-1]
    assert see["images"] == [PNG] and "how should I reply?" in see["prompt"]
    assert "chosen another candidate" in answer["prompt"] and answer["effort"] == "high"
    assert result["status"] == "done" and result["asks"] == ["Mention your health?"]
    assert not (tmp_path / "clones" / "ask" / "images").exists()  # a deep ask keeps none
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
    assert ask.read_request(line) == ("hi", [PNG], False)
    assert ask.read_request(json.dumps({"text": "hi", "deep": True}))[2] is True
    with pytest.raises(SystemExit):
        ask.read_request(json.dumps({"text": "  ", "images": []}))


def test_a_quick_answer_is_one_call_without_thinking_and_keeps_its_screenshots(tmp_path):
    (tmp_path / "self").mkdir()
    (tmp_path / "self" / "identity.md").write_text("A researcher.\n" + "x" * 9000)
    (tmp_path / "self" / "interests.md").write_text("Not read for a quick answer.")
    model = Model()

    result = ask.ask(tmp_path, "how should I reply?", [PNG], NOW, model, deep=False)

    [call] = model.calls
    assert call["effort"] == "low" and call["images"] == [PNG]
    assert set(call["schema"]["required"]) == {"answer", "draft_to", "draft_channel", "draft_body"}
    assert result["status"] == "done" and result["deep"] is False and result["draft"]
    assert result["found"].startswith("A quick answer")
    kept = tmp_path / "clones" / "ask" / "images" / "ask-20260310T120000Z.json"
    assert json.loads(kept.read_text()) == {"images": [PNG]}
    assert not (tmp_path / "state" / "asking").exists()  # the mark is gone once it's answered


def test_a_quick_ask_is_thought_through_again_with_its_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr(ask, "datetime", _Clock([NOW, datetime(2026, 3, 10, 12, 5, tzinfo=UTC)]))
    ask.ask(tmp_path, "how should I reply?", [PNG], model=Model())
    model = Model()

    result = ask.again(tmp_path, "ask-20260310T120000Z", model)

    assert result["id"] == "ask-20260310T120500Z" and result["deep"] is True
    assert model.calls[0]["images"] == [PNG] and model.calls[-1]["effort"] == "high"
    with pytest.raises(SystemExit):
        ask.again(tmp_path, "../../etc/passwd", model)


def test_a_draft_follows_the_rules_and_my_own_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    folder = tmp_path / "raw" / "whatsapp" / "messages"
    folder.mkdir(parents=True)
    said = [("Ana Lee", "are we still on for friday"), (None, "sounds good, see you then")]
    (folder / "2026-03.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "id": f"m{n}",
                    "ts": f"2026-03-0{n}T09:00:00Z",
                    "chat_id": "ana",
                    "chat_name": "Ana Lee",
                    "chat_type": "direct",
                    "from_me": who is None,
                    "sender_name": who,
                    "text": text,
                }
            )
            + "\n"
            for n, (who, text) in enumerate(said, 1)
        )
    )

    deep = Model()
    ask.ask(tmp_path, "how should I reply?", [PNG], NOW, deep, deep=True)
    answer = deep.calls[-1]  # the screenshot is from Ana Lee: their chat first
    assert voice.rules("Tess") in answer["system"]
    assert "In their chat with Ana Lee:\n- sounds good, see you then" in answer["prompt"]

    quick = Model()
    ask.ask(tmp_path, "can you do friday?", [], NOW, quick)
    [call] = quick.calls
    assert voice.rules("Tess") in call["system"]
    assert "In their chats:\n- sounds good, see you then" in call["prompt"]


class _Clock:
    """datetime, with now() giving each of `times` in turn."""

    def __init__(self, times):
        self.times = list(times)

    def now(self, tz=None):
        return self.times.pop(0)

    def __getattr__(self, name):
        return getattr(datetime, name)
