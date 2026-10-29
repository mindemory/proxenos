"""The model wrapper, against a fake client. No network, no key."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from proxenos import llm


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.params = None

    @contextmanager
    def stream(self, **params):
        self.params = params
        yield SimpleNamespace(get_final_message=lambda: self.response)


def fake(monkeypatch, *, text="", stop_reason="end_turn"):
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ]
    messages = FakeMessages(
        SimpleNamespace(content=blocks, stop_reason=stop_reason, stop_details=None)
    )
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    return messages


def test_text_answers_skip_thinking_blocks_and_cache_the_system_prompt(monkeypatch):
    messages = fake(monkeypatch, text="hello")
    assert llm.ask("hi", system="you are me") == "hello"
    assert messages.params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert messages.params["fallbacks"] == "default"
    assert "format" not in messages.params["output_config"]


def test_schema_answers_come_back_parsed(monkeypatch):
    messages = fake(monkeypatch, text='{"score": 0.8}')
    schema = {"type": "object", "properties": {"score": {"type": "number"}}}
    assert llm.ask("rank", schema=schema, effort="low") == {"score": 0.8}
    assert messages.params["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": schema},
    }


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_answers_raise(monkeypatch, stop_reason):
    fake(monkeypatch, text="partial", stop_reason=stop_reason)
    with pytest.raises(llm.ModelError):
        llm.ask("hi")


def test_missing_key_says_where_to_put_one(monkeypatch):
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        llm._get_client()


def local(monkeypatch, answer):
    """A fake Ollama: records each request body, answers with `answer`."""
    import io
    import json

    sent = []

    def urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return io.BytesIO(json.dumps(answer).encode())

    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    return sent


def test_a_local_model_answers_through_ollama_with_the_schema(monkeypatch):
    fenced = '```json\n{"x": 1}\n```'
    sent = local(monkeypatch, {"message": {"content": fenced}, "done_reason": "stop"})
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("called the API"))
    schema = {"type": "object", "required": ["x"]}

    assert llm.ask("hi", system="sys", schema=schema, effort="high") == {"x": 1}

    url, body = sent[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert body["model"] == "gemma4:26b" and body["think"] is True
    system, user = body["messages"]
    assert user == {"role": "user", "content": "hi"}
    assert system["content"].startswith("sys") and '"required": ["x"]' in system["content"]
    assert llm.configured()  # a local model needs no key


def test_a_local_answer_that_isnt_the_json_asked_for_is_tried_again_then_fails(monkeypatch):
    sent = local(monkeypatch, {"message": {"content": '{"y": 1}'}, "done_reason": "stop"})
    with pytest.raises(llm.ModelError, match="JSON asked for"):
        llm.ask("hi", schema={"type": "object", "required": ["x"]})
    assert len(sent) == 2 and sent[0][1]["think"] is False


def test_a_local_prompt_too_long_or_answer_cut_off_fails_rather_than_truncates(monkeypatch):
    sent = local(monkeypatch, {"message": {"content": "partial"}, "done_reason": "length"})
    with pytest.raises(llm.ModelError, match="too long"):
        llm.ask("x" * llm.LOCAL_CONTEXT * 3)
    assert not sent  # never sent
    with pytest.raises(llm.ModelError, match="cut off"):
        llm.ask("hi")
