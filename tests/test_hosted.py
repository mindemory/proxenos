"""OpenAI and Gemini as hosted models: the key check, a completion, a refused response_format, and
what may leave the computer. Fake HTTP answers only; no network, no key of anyone's."""

import io
import json
from urllib.error import HTTPError

import pytest
from test_llm import Events, evented  # the same fake server stream as test_llm uses

from proxenos import config, hosted, llm, setup

OPENAI_KEY = "sk-proj-" + "o" * 40
GEMINI_KEY = "AIza" + "g" * 35
OPENAI_MODELS = {
    "data": [
        {"id": "gpt-4.1"},
        {"id": "gpt-4.1-mini"},
        {"id": "text-embedding-3-small"},
        {"id": "gpt-4o-realtime-preview"},
        {"id": "o3"},
        {"id": "whisper-1"},
        {"id": "dall-e-3"},
    ]
}
GEMINI_MODELS = {
    "data": [
        {"id": "models/gemini-2.5-pro"},
        {"id": "models/gemini-2.5-flash-lite"},
        {"id": "models/gemini-2.5-flash-preview-tts"},
        {"id": "models/gemini-2.5-flash"},
        {"id": "models/text-embedding-004"},
        {"id": "models/gemini-embedding-001"},
    ]
}


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def listing(monkeypatch, answers):
    """Stand in for the provider's /models: answers by address, each a dict, or an error to raise."""
    asked = []

    def opened(request, timeout):
        asked.append((request.full_url, request.get_header("Authorization")))
        answer = answers[request.full_url]
        if isinstance(answer, Exception):
            raise answer
        return Reply(json.dumps(answer).encode())

    monkeypatch.setattr(llm, "_remote", opened)
    return asked


@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    monkeypatch.delenv("PROXENOS_VAULT")
    for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return folder


def test_only_chat_models_are_offered_and_one_is_suggested_by_pattern(monkeypatch):
    asked = listing(
        monkeypatch,
        {
            "https://api.openai.com/v1/models": OPENAI_MODELS,
            "https://generativelanguage.googleapis.com/v1beta/openai/models": GEMINI_MODELS,
        },
    )
    names = hosted.list_models("openai", OPENAI_KEY)
    assert names == ["gpt-4.1", "gpt-4.1-mini", "o3"]
    assert hosted.suggest("openai", names) == "gpt-4.1-mini"
    assert hosted.suggest("openai", ["gpt-4.1", "o3"]) == "gpt-4.1"
    assert hosted.suggest("openai", ["o3"]) is None

    names = hosted.list_models("gemini", GEMINI_KEY)
    assert names == ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
    assert hosted.suggest("gemini", names) == "gemini-2.5-flash"  # not lite, preview, tts
    assert hosted.suggest("gemini", ["gemini-2.5-pro", "gemini-2.5-flash-lite"]) == "gemini-2.5-pro"
    assert asked[0] == ("https://api.openai.com/v1/models", f"Bearer {OPENAI_KEY}")


def test_a_key_the_provider_refuses_or_cant_be_checked_says_so(monkeypatch):
    url = "https://api.openai.com/v1/models"
    body = io.BytesIO(b"{}")
    listing(monkeypatch, {url: HTTPError(url, 401, "Unauthorized", {}, body)})
    with pytest.raises(
        ValueError, match="OpenAI didn't accept that key. Copy it again from platform"
    ):
        hosted.list_models("openai", OPENAI_KEY)
    listing(monkeypatch, {url: HTTPError(url, 500, "Oops", {}, body)})
    with pytest.raises(ValueError, match="error \\(500\\)"):
        hosted.list_models("openai", OPENAI_KEY)
    listing(monkeypatch, {url: OSError("down")})
    with pytest.raises(ValueError, match="Couldn't reach OpenAI"):
        hosted.list_models("openai", OPENAI_KEY)
    with pytest.raises(ValueError, match="provider is"):
        hosted.list_models("claude", "x")


def test_an_openai_key_is_checked_by_listing_models_kept_and_made_the_ask_model(
    home, monkeypatch, fake_keychain
):
    asked = listing(monkeypatch, {"https://api.openai.com/v1/models": OPENAI_MODELS})
    config.save_setting("MODEL", "ollama:gemma4:e4b")

    result = setup.apply({"key": f" {OPENAI_KEY}\n", "provider": "openai"})

    assert result["ok"], result
    assert asked == [("https://api.openai.com/v1/models", f"Bearer {OPENAI_KEY}")]
    assert fake_keychain.items == {"OPENAI_API_KEY": OPENAI_KEY}
    assert config.env("ASK_MODEL") == "openai:gpt-4.1-mini"
    assert config.env("MODEL") == "ollama:gemma4:e4b"  # the model here keeps the rest
    assert "the rest stays on gemma4:e4b" in result["message"]
    assert result["models"] == {
        "provider": "openai",
        "names": ["gpt-4.1", "gpt-4.1-mini", "o3"],
        "suggested": "gpt-4.1-mini",
        "chosen": "gpt-4.1-mini",
    }
    assert (
        OPENAI_KEY not in json.dumps(result) and OPENAI_KEY not in config.SETTINGS_FILE.read_text()
    )
    secret = next(s for s in result["status"]["secrets"] if s["name"] == "OPENAI_API_KEY")
    assert secret["set"] is True

    # Another one the key lists is chosen, and one it doesn't list is refused.
    assert setup.apply({"hosted_model": "openai:gpt-4.1"})["ok"]
    assert config.env("ASK_MODEL") == "openai:gpt-4.1"
    assert "doesn't list gpt-9" in setup.apply({"hosted_model": "openai:gpt-9"})["error"]
    assert setup.apply({"models": "openai"})["models"]["chosen"] == "gpt-4.1"
    # A key saved again keeps the model chosen.
    assert setup.apply({"key": OPENAI_KEY, "provider": "openai"})["models"]["chosen"] == "gpt-4.1"


def test_with_no_model_on_this_computer_and_no_claude_key_a_gemini_key_answers_everything(
    home, monkeypatch, fake_keychain
):
    listing(
        monkeypatch,
        {"https://generativelanguage.googleapis.com/v1beta/openai/models": GEMINI_MODELS},
    )
    result = setup.apply({"key": GEMINI_KEY, "provider": "gemini"})
    assert result["ok"], result
    assert config.env("ASK_MODEL") == config.env("MODEL") == "gemini:gemini-2.5-flash"
    assert result["status"]["model"] == {
        "kind": "api",
        "name": "gemini-2.5-flash",
        "via": None,
        "provider": "gemini",
    }
    assert "and everything else" in result["message"]


def test_a_key_of_the_wrong_kind_is_refused_before_anyone_is_asked(home, monkeypatch):
    listing(monkeypatch, {})  # any request would raise KeyError
    assert "start with sk-" in setup.apply({"key": "nope", "provider": "openai"})["error"]
    assert "start with AIza" in setup.apply({"key": OPENAI_KEY, "provider": "gemini"})["error"]
    assert (
        "Anthropic key" in setup.apply({"key": "sk-ant-" + "a" * 30, "provider": "openai"})["error"]
    )
    assert (
        "anthropic, openai or gemini" in setup.apply({"key": OPENAI_KEY, "provider": "x"})["error"]
    )
    assert "No OpenAI key is saved" in setup.apply({"models": "openai"})["error"]
    assert not config.SETTINGS_FILE.exists()


def hosted_call(monkeypatch, model, content, key_name, *, chunks=None, opened=None):
    sent = []

    def default(request, timeout):
        sent.append(
            (request.full_url, json.loads(request.data), request.get_header("Authorization"))
        )
        return Events(evented(content) if chunks is None else chunks)

    monkeypatch.setenv(key_name, "sk-test-key-123456")
    monkeypatch.setenv("PROXENOS_MODEL", model)
    monkeypatch.setattr(llm, "_remote", opened or default)
    monkeypatch.setattr(llm, "_direct", lambda *a, **k: pytest.fail("the local path"))
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("called Anthropic"))
    return sent


def test_openai_answers_through_the_chat_api_at_its_own_address_with_the_key(monkeypatch, tmp_path):
    log = tmp_path / "state" / "model-calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)
    sent = hosted_call(monkeypatch, "openai:gpt-4.1-mini", '{"x": 1}', "OPENAI_API_KEY")
    schema = {"type": "object", "required": ["x"]}

    said = "Your verification code is 482913. Call 603-555-0142 on 11/03."
    assert llm.ask(said, system="Card 4111 1111 1111 1111", schema=schema, max_tokens=32000) == {
        "x": 1
    }

    url, body, auth = sent[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert auth == "Bearer sk-test-key-123456"
    assert body["model"] == "gpt-4.1-mini" and body["max_completion_tokens"] == llm.HOSTED_ANSWER
    assert "max_tokens" not in body and body["response_format"]["type"] == "json_schema"
    system, user = body["messages"]
    assert "4111" not in system["content"] and "482913" not in user["content"]  # blanked
    line = json.loads(log.read_text())
    assert line["where"] == "OpenAI" and line["model"] == "openai:gpt-4.1-mini"
    assert line["redacted"] > 0 and (line["tokens_in"], line["tokens_out"]) == (12, 5)
    assert "482913" not in log.read_text()
    assert llm.configured() and not llm.current().startswith(llm.LOCAL)


def test_gemini_answers_through_googles_openai_endpoint(monkeypatch):
    sent = hosted_call(monkeypatch, "gemini:gemini-2.5-flash", "hello", "GEMINI_API_KEY")
    assert llm.ask("hi", max_tokens=500) == "hello"
    url, body, auth = sent[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert body["max_tokens"] == 500 and "max_completion_tokens" not in body
    assert body["model"] == "gemini-2.5-flash" and auth.startswith("Bearer ")
    assert llm.where("gemini:x") == "Google" and llm.bare("gemini:x") == "x"


@pytest.mark.parametrize(
    ("model", "key_name"), [("openai:gpt-4.1", "OPENAI_API_KEY"), ("gemini:g", "GEMINI_API_KEY")]
)
def test_a_provider_that_refuses_response_format_is_asked_again_without_it_once(
    monkeypatch, model, key_name
):
    sent = []

    def opened(request, timeout):
        body = json.loads(request.data)
        sent.append(body)
        if "response_format" in body:
            said = b'{"error":"\'response_format\' is not supported with this model"}'
            raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(said))
        return Events(evented('{"x": 1}'))

    hosted_call(monkeypatch, model, "", key_name, opened=opened)
    monkeypatch.setattr(llm, "_NO_GRAMMAR", set())
    schema = {"type": "object", "required": ["x"]}
    assert llm.ask("hi", schema=schema) == {"x": 1}
    assert ["response_format" in b for b in sent] == [True, False]
    sent.clear()
    assert llm.ask("again", schema=schema) == {"x": 1}
    assert ["response_format" in b for b in sent] == [False]


def test_a_refusal_with_the_key_in_it_never_shows_the_key(monkeypatch):
    def opened(request, timeout):
        said = b'{"error":"Incorrect API key provided: sk-test-key-123456"}'
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(said))

    hosted_call(monkeypatch, "openai:gpt-4.1", "", "OPENAI_API_KEY", opened=opened)
    with pytest.raises(llm.ModelError) as stopped:
        llm.ask("hi")
    assert "sk-test-key-123456" not in str(stopped.value) and "OpenAI model gpt-4.1" in str(
        stopped.value
    )


def test_a_hosted_model_is_never_on_this_computer_and_needs_its_own_key(monkeypatch):
    monkeypatch.setenv("PROXENOS_MODEL", "openai:gpt-4.1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-" + "k" * 30)
    assert not llm.configured()  # Anthropic's key doesn't answer for OpenAI's model
    with pytest.raises(llm.ModelError, match="OPENAI_API_KEY is not set"):
        llm.ask("hi")
    # The fast model and the "local" rule are as they were: a hosted name is neither.
    monkeypatch.setenv("PROXENOS_FAST_MODEL", "openai:gpt-4.1-mini")
    with llm.using(step="tasks"):
        assert llm.fast() == ""
    assert llm.fit(400_000) == 400_000 and llm.prompt_chars() is None
    with pytest.raises(llm.ModelError, match="isn't on this computer"):
        llm.local_url("https://api.openai.com/v1")
    assert llm.where("ollama:x") == llm.where("voice:mlx") == "this computer"
    assert llm.where("claude-opus-5-5") == "Anthropic"


def test_the_ask_model_can_be_a_hosted_one_with_its_key(monkeypatch):
    monkeypatch.setenv("PROXENOS_ASK_MODEL", "gemini:g")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm._ask_model() == ""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "g" * 35)
    assert llm._ask_model() == "gemini:g"


def test_the_privacy_view_counts_each_provider_apart(tmp_path):
    from proxenos import privacy

    calls = [
        {"where": "OpenAI", "step": "tasks", "ok": True, "tokens_in": 3},
        {"where": "Google", "step": "tasks", "ok": True},
        {"where": "this computer", "step": "tasks", "ok": True},
        {"where": "somewhere else", "step": "tasks", "ok": True},
    ]
    shown = [privacy._call(c) for c in calls]
    assert [c["where"] for c in shown] == ["OpenAI", "Google", "this computer", "Anthropic"]
    assert privacy._totals(shown)["hosted"] == 3
