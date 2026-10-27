"""The model wrapper, against a fake client. No network, no key."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from twin import llm


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
