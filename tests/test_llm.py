"""The model wrapper, against a fake client. No network, no key."""

import json
import os
import threading
import time
import types
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from proxenos import llm, lock

_real_waiting = llm.waiting  # conftest stands it in for every test; this one tests it


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


SAID = "Your verification code is 482913. Call 603-555-0142 on 11/03 about the $40."
SYSTEM = "Card 4111 1111 1111 1111; password: hunter2!"


def test_a_hosted_model_gets_numbers_and_secrets_blanked_and_the_log_counts_them(
    monkeypatch, tmp_path
):
    log = tmp_path / "state" / "model-calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)
    messages = fake(monkeypatch, text="ok")
    image = {"type": "image/png", "data": "UGFzc3dvcmQ6IGh1bnRlcjIh"}

    assert llm.ask(SAID, system=SYSTEM, images=[image]) == "ok"

    seen, text = messages.params["messages"][0]["content"]
    assert text["text"] == (
        "Your verification code is [code]. Call 603-555-0142 on 11/03 about the $40."
    )
    assert messages.params["system"][0]["text"] == "Card [card number]; password: [password]"
    assert seen["source"]["data"] == image["data"]  # an image goes as it is
    line = json.loads(log.read_text())
    assert line["where"] == "Anthropic" and line["redacted"] == 3
    for secret in ("482913", "4111", "hunter2", "[code]", "password"):
        assert secret not in log.read_text()


def test_what_the_caller_keeps_reaches_a_hosted_model(monkeypatch):
    messages = fake(monkeypatch, text="ok")
    llm.ask("Go on.", system="You may say: account number: 12345678", keep=["12345678"])
    assert messages.params["system"][0]["text"] == "You may say: account number: 12345678"


class Stream:
    """An answer from Ollama as it streams in: JSON lines, then `then` raised, if given."""

    def __init__(self, lines, then=None):
        self.lines, self.then = lines, then

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        import json

        for line in self.lines:
            yield json.dumps(line).encode() + b"\n"
        if self.then:
            raise self.then


def streamed(content, done_reason="stop"):
    """`content` as Ollama streams it: some thinking, the words in pieces, a last line."""
    pieces = [content[i : i + 4] for i in range(0, len(content), 4)]
    return [
        {"message": {"role": "assistant", "content": "", "thinking": "Hm."}, "done": False},
        *({"message": {"role": "assistant", "content": p}, "done": False} for p in pieces),
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason},
    ]


def local(monkeypatch, content, done_reason="stop", *, lines=None, then=None):
    """A fake Ollama: records each request body and streams `content` back, or `lines`."""
    import json

    sent = []

    def urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return Stream(streamed(content, done_reason) if lines is None else lines, then)

    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    return sent


def test_a_local_model_answers_through_ollama_with_the_schema(monkeypatch):
    fenced = '```json\n{"x": 1}\n```'
    sent = local(monkeypatch, fenced)
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("called the API"))
    schema = {"type": "object", "required": ["x"]}

    assert llm.ask("hi", system="sys", schema=schema, effort="high") == {"x": 1}

    url, body = sent[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert body["model"] == "gemma4:26b" and body["think"] is True and body["stream"] is True
    system, user = body["messages"]
    assert user == {"role": "user", "content": "hi"}
    assert system["content"].startswith("sys") and '"required": ["x"]' in system["content"]
    assert llm.configured()  # a local model needs no key


def test_a_local_model_gets_the_prompt_as_it_is(monkeypatch, tmp_path):
    log = tmp_path / "state" / "model-calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)
    sent = local(monkeypatch, "ok")

    assert llm.ask(SAID, system=SYSTEM) == "ok"

    system, user = sent[0][1]["messages"]
    assert (system["content"], user["content"]) == (SYSTEM, SAID)  # nothing left this computer
    assert json.loads(log.read_text())["redacted"] is None


def test_a_local_answer_that_isnt_the_json_asked_for_is_tried_again_then_fails(monkeypatch):
    sent = local(monkeypatch, '{"y": 1}')
    with pytest.raises(llm.ModelError, match="JSON asked for"):
        llm.ask("hi", schema={"type": "object", "required": ["x"]})
    assert len(sent) == 2 and sent[0][1]["think"] is False


def test_a_local_prompt_too_long_or_answer_cut_off_fails_rather_than_truncates(monkeypatch):
    sent = local(monkeypatch, "partial", "length")
    with pytest.raises(llm.ModelError, match="too long"):
        llm.ask("x" * llm.LOCAL_CONTEXT * 3)
    assert not sent  # never sent
    with pytest.raises(llm.ModelError, match="cut off"):
        llm.ask("hi")


def test_a_long_local_answer_isnt_cut_at_a_time_but_a_stalled_one_is(monkeypatch):
    # Each read waits at most _LOCAL_TIMEOUT for the next piece, however long the whole takes.
    local(monkeypatch, "a long answer")
    assert llm.ask("hi") == "a long answer"

    local(monkeypatch, "", lines=streamed("a long")[:2], then=TimeoutError("timed out"))
    with pytest.raises(llm.ModelError, match="isn't answering"):
        llm.ask("hi")
    local(monkeypatch, "", lines=streamed("a long")[:2])  # the stream ended with no last line
    with pytest.raises(llm.ModelError, match="stopped mid-answer"):
        llm.ask("hi")
    local(monkeypatch, "", lines=[{"error": "model runner has unexpectedly stopped"}])
    with pytest.raises(llm.ModelError, match="unexpectedly stopped"):
        llm.ask("hi")

    monkeypatch.setattr(llm, "_LOCAL_DEADLINE", -1)  # past the deadline, still going
    local(monkeypatch, "a long answer")
    with pytest.raises(llm.ModelError, match="still answering"):
        llm.ask("hi")


def test_steps_trim_to_what_a_local_model_takes(monkeypatch):
    assert llm.fit(400_000) == 400_000  # the API takes it all
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    assert llm.fit(400_000) == llm.prompt_chars() - 30_000 < 400_000
    assert llm.fit(50_000) == 50_000


def test_a_question_being_answered_holds_other_processes_off(tmp_path, monkeypatch):
    from proxenos.llm import foreground

    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")  # the model it holds them off

    waiting = _real_waiting
    assert not waiting(tmp_path)
    with foreground(tmp_path):
        assert (tmp_path / "state" / "asking").read_text() == str(os.getpid())
        assert not waiting(tmp_path)  # not this process's own calls
    assert not waiting(tmp_path)

    mark = tmp_path / "state" / "asking"
    mark.write_text(str(os.getppid()))  # another process, alive
    assert waiting(tmp_path)
    old = time.time() - 2000
    os.utime(mark, (old, old))  # left behind long ago
    assert not waiting(tmp_path)


def test_local_calls_take_turns_and_a_question_goes_first(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    monkeypatch.setattr(llm, "_TURN_EVERY", 0.01)
    monkeypatch.setattr(llm, "_calls_path", lambda: None)
    asked = []
    monkeypatch.setattr(llm, "_chat", lambda model, body, room: asked.append(1) or "ok")
    wanted = []  # a question someone is waiting on, in another process
    monkeypatch.setattr(llm, "waiting", lambda vault=None: bool(wanted))
    other = lock.Lock(tmp_path / "state" / "model.lock")
    assert other.acquire()  # another process's call has the model

    done = threading.Event()
    background = threading.Thread(target=lambda: llm.ask("a night's note") and done.set())
    background.start()
    time.sleep(0.2)
    assert not asked  # it waits for its turn
    wanted.append("Think")
    # Let the waiting call look again first: one that checked for a question just before it
    # came, then found the lock free as it's let go, would take a turn the test means to deny.
    time.sleep(0.1)
    other.release()
    time.sleep(0.2)
    assert not asked  # the model is free, but the question goes first
    wanted.clear()
    assert done.wait(5) and asked == [1]
    background.join()

    # The question's own process waits for the turn alone, never for itself.
    (tmp_path / "state" / "asking").write_text(str(os.getpid()))
    wanted.append("Think")
    assert llm.ask("the question") == "ok" and asked == [1, 1]


def test_what_someone_waits_on_goes_to_the_ask_model_and_the_rest_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    monkeypatch.setenv("PROXENOS_ASK_MODEL", "claude-opus-5-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with llm.foreground(tmp_path):
        assert llm.current() == "ollama:gemma4:26b"  # no key: Claude can't answer, so the local
        assert (tmp_path / "state" / "asking").exists()  # model does, and goes first
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert llm.current() == "ollama:gemma4:26b"  # the night's calls
    with llm.foreground(tmp_path):
        assert llm.current() == "claude-opus-5-5"
        assert not (tmp_path / "state" / "asking").exists()  # the local model isn't held up
        with llm.using(model="ollama:qwen3"):
            assert llm.current() == "ollama:qwen3"
    assert llm.current() == "ollama:gemma4:26b"


def test_a_voice_model_answers_from_the_server_on_this_computer(monkeypatch):
    import io
    import json

    sent = []

    def urlopen(request, timeout):
        sent.append((request.full_url, json.loads(request.data)))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "yaa"}}]}).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    assert not llm.voice_on()
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "mlx")
    assert llm.voice_on()

    assert llm.ask_voice("the chat", "You are Tess.") == "yaa"
    url, body = sent[0]
    assert url == f"http://127.0.0.1:{llm.VOICE_PORT}/v1/chat/completions"
    assert body["model"] == "default_model"
    assert body["messages"] == [
        {"role": "system", "content": "You are Tess."},
        {"role": "user", "content": "the chat"},
    ]
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "mlx:9000")
    llm.ask_voice("the chat", "You are Tess.")
    assert sent[1][0] == "http://127.0.0.1:9000/v1/chat/completions"


def test_a_voice_model_in_ollama_or_not_answering(monkeypatch):
    asked = []
    monkeypatch.setattr(llm, "_chat", lambda model, body, room: asked.append(body) or "yaa")
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "ollama:tess-voice")
    assert llm.ask_voice("the chat", "You are Tess.") == "yaa"
    assert asked[0]["model"] == "tess-voice" and asked[0]["think"] is False

    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "gpt-9")
    with pytest.raises(llm.ModelError, match="isn't a voice model"):
        llm.ask_voice("the chat", "You are Tess.")

    def down(request, timeout):
        raise llm.urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", down)
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "mlx")
    with pytest.raises(llm.ModelError, match="isn't answering"):
        llm.ask_voice("the chat", "You are Tess.")


def test_a_local_answer_is_held_to_the_schema_item_by_item(monkeypatch):
    idea = {"type": "object", "properties": {"title": {"type": "string"},
            "first_step": {"type": "string"}, "kind": {"type": "string", "enum": ["a", "b"]}},
            "required": ["title", "first_step"], "additionalProperties": False}  # fmt: skip
    schema = {
        "type": "object",
        "properties": {"ideas": {"type": "array", "items": idea}, "count": {"type": "integer"}},
        "required": ["ideas"],
    }
    answer = {
        "ideas": [
            {"title": "Kept", "first_step": "Write to Ana.", "extra": 1},
            {"title": "No first step"},  # a gap in one item drops that item only
            {"title": "Odd kind", "first_step": "x", "kind": "c"},  # a value off its enum goes
            "not an idea",
        ],
        "count": True,  # a boolean isn't an integer
    }
    sent = local(monkeypatch, f"{schema}\n{__import__('json').dumps(answer)}")

    assert llm.ask("hi", schema=schema) == {
        "ideas": [
            {"title": "Kept", "first_step": "Write to Ana."},
            {"title": "Odd kind", "first_step": "x"},
        ]
    }
    assert len(sent) == 1
    assert llm._object('{"ideas": {"type": "array"}}', schema) is None  # the echoed schema isn't it


def ask_another():
    return llm.ask("another secret", schema={"type": "object", "required": ["x"]})


def test_each_call_leaves_a_line_in_the_log_and_never_the_words(monkeypatch, tmp_path):
    log = tmp_path / "state" / "model-calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)
    lines = [
        {"message": {"content": '{"x": 1}'}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 12, "eval_count": 5},
    ]  # fmt: skip
    local(monkeypatch, None, lines=lines)

    assert llm.ask("a secret prompt", system="sys", schema={"type": "object", "required": ["x"]})
    local(monkeypatch, '{"y": 1}')
    # Asked from a clone's code: the same function, run as if it lived in the journal clone.
    as_clone = {"__name__": "proxenos.clones.journal", "llm": llm, "__builtins__": __builtins__}
    with pytest.raises(llm.ModelError):
        types.FunctionType(ask_another.__code__, as_clone)()

    import json

    first, second = [json.loads(line) for line in log.read_text().splitlines()]
    assert first["where"] == "this computer" and first["model"] == "ollama:gemma4:26b"
    assert (first["sent_chars"], first["answer_chars"], first["ok"]) == (18, 8, True)
    assert (first["tokens_in"], first["tokens_out"]) == (12, 5)
    assert first["step"] == "proxenos"  # a test isn't one of Proxenos's own parts
    assert second["step"] == "journal" and second["ok"] is False and second["answer_chars"] == 0
    assert "secret" not in log.read_text()
    assert os.name == "nt" or (log.stat().st_mode & 0o777) == 0o600
    assert [c["ok"] for c in llm.calls(tmp_path)] == [True, False]
    assert llm.calls(tmp_path, since="2999-01-01") == []


def test_a_local_answer_with_latex_left_unescaped_is_read_as_meant(monkeypatch):
    schema = {"type": "object", "properties": {"find": {"type": "string"}}, "required": ["find"]}
    # A backslash left single, a line break left raw, beside escapes written right.
    slipped = '{"find": "\\section{Results}\n\\usepackage{x} \\\\cite{a} caf\\u00e9"}'
    sent = local(monkeypatch, slipped)

    assert llm.ask("hi", schema=schema) == {
        "find": "\\section{Results}\n\\usepackage{x} \\cite{a} café"
    }
    assert len(sent) == 1  # read the first time, not asked again
    assert llm._object('{"find": "\\\\section"}', schema) == {"find": "\\section"}


def test_a_schema_holds_the_local_model_as_it_writes_where_ollama_can(monkeypatch):
    import io
    import json
    from urllib.error import HTTPError

    sent = []
    schema = {"type": "object", "required": ["x"]}

    def urlopen(request, timeout):
        body = json.loads(request.data)
        sent.append(body)
        if "format" in body and body["model"] == "plain":
            error = io.BytesIO(b'{"error":"structured output is unavailable"}')
            raise HTTPError(request.full_url, 501, "Not Implemented", {}, error)
        return Stream(streamed('{"x": 1}'))

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(llm, "_NO_GRAMMAR", set())
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:held")
    assert llm.ask("hi", schema=schema) == {"x": 1}
    assert sent[-1]["format"] == schema  # held to it as it writes

    monkeypatch.setenv("PROXENOS_MODEL", "ollama:plain")  # Homebrew's build: no grammar library
    sent.clear()
    assert llm.ask("hi", schema=schema) == {"x": 1}
    assert ["format" in body for body in sent] == [True, False]
    sent.clear()
    assert llm.ask("again", schema=schema) == {"x": 1}
    assert ["format" in body for body in sent] == [False]  # not asked with one again
    texts = local(monkeypatch, "hello")  # a text answer is held to nothing
    assert llm.ask("text") == "hello" and "format" not in texts[0][1]


class Events(Stream):
    """An OpenAI-compatible server's answer as it streams in: server-sent events, each a data:
    line and a blank one, then `then` raised, if given."""

    def __iter__(self):
        for chunk in self.lines:
            yield b"data: " + (chunk if isinstance(chunk, bytes) else json.dumps(chunk).encode())
            yield b"\n"
        if self.then:
            raise self.then


def piece(delta, finish=None):
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def evented(content, finish="stop"):
    """`content` as such a server streams it: thinking parted out, the words in pieces, why it
    stopped, the tokens, and [DONE]."""
    return [
        piece({"role": "assistant", "content": "", "reasoning_content": "Hm."}),
        *(piece({"content": content[i : i + 4]}) for i in range(0, len(content), 4)),
        piece({}, finish),
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
        b"[DONE]",
    ]


def served(monkeypatch, content, finish="stop", *, chunks=None, then=None, model="qwen3-8b"):
    """A fake server on this computer: records each request and streams `content` back, or
    `chunks`. Ollama's way is never taken."""
    sent = []

    def opened(request, timeout):
        sent.append((request.full_url, json.loads(request.data), timeout))
        return Events(evented(content, finish) if chunks is None else chunks, then)

    monkeypatch.setenv("PROXENOS_MODEL", f"local:{model}")
    monkeypatch.setattr(llm, "_direct", opened)
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *_, **__: pytest.fail("Ollama"))
    return sent


def test_a_model_on_another_server_answers_through_its_openai_api_with_the_schema(monkeypatch):
    sent = served(monkeypatch, '```json\n{"x": 1}\n```', model="qwen3-8b@q4_k_m")
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("called the API"))
    schema = {"type": "object", "required": ["x"]}

    assert llm.ask("hi", system="sys", schema=schema, effort="high", max_tokens=900) == {"x": 1}

    url, body, timeout = sent[0]
    assert url == "http://127.0.0.1:1234/v1/chat/completions" and timeout == llm._LOCAL_TIMEOUT
    assert body["model"] == "qwen3-8b@q4_k_m" and body["stream"] is True
    assert body["max_tokens"] == 900 and body["stream_options"] == {"include_usage": True}
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "answer", "schema": schema},
    }
    system, user = body["messages"]
    assert user == {"role": "user", "content": "hi"}
    assert system["content"].startswith("sys") and '"required": ["x"]' in system["content"]
    assert "think" not in body and "options" not in body  # Ollama's own
    assert llm.configured()  # a local model needs no key
    assert llm.fit(400_000) == llm.prompt_chars() - 30_000 < 400_000  # trimmed as Ollama's are


def test_a_servers_address_is_its_own_setting_and_images_go_as_data_urls(monkeypatch):
    sent = served(monkeypatch, "a cat")
    monkeypatch.setenv("PROXENOS_LOCAL_URL", "http://localhost:8080/v1/")  # llama-server's
    image = {"type": "image/png", "data": "aGVsbG8="}

    assert llm.ask("what is it?", images=[image]) == "a cat"

    url, body, _ = sent[0]
    assert url == "http://localhost:8080/v1/chat/completions" and "response_format" not in body
    assert body["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                {"type": "text", "text": "what is it?"},
            ],
        }
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.example.com:1234/v1",  # named like loopback, but another host
        "http://127.0.0.1@evil.example/v1",  # user info: the host is evil.example
        "http://evil.example@127.0.0.1:1234/v1",  # user info, either way round
        "http://evil.example#@127.0.0.1/v1",
        "http://evil.example?@127.0.0.1/v1",
        "http://127.0.0.1\\@evil.example/v1",
        "http://localhost.evil.example/v1",
        "http://192.168.1.20:1234/v1",
        "http://10.0.0.1/v1",
        "http://0.0.0.0:1234/v1",
        "http://[::ffff:8.8.8.8]/v1",
        "http://[2001:db8::1]/v1",
        "http://2130706433/v1",  # a number some read as 127.0.0.1: refused all the same
        "http://127.1/v1",
        "http://127.0.0.1:port/v1",
        "http://127.0.0.1 .evil.example/v1",
        "http://127.0.0.1\t.evil.example/v1",
        "ftp://127.0.0.1/v1",
        "file:///etc/passwd",
        "127.0.0.1:1234/v1",
        "http:///v1",
    ],
)
def test_a_server_anywhere_but_this_computer_is_refused_before_anything_is_sent(monkeypatch, url):
    sent = served(monkeypatch, "ok")
    monkeypatch.setenv("PROXENOS_LOCAL_URL", url)
    with pytest.raises(llm.ModelError, match="isn't on this computer"):
        llm.ask("a private prompt")
    assert not sent


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        ("", "http://127.0.0.1:1234/v1"),  # LM Studio's, when none is set
        ("http://127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1"),  # llama-server's
        ("http://localhost:8000/v1/", "http://localhost:8000/v1"),  # vLLM's
        ("HTTP://LOCALHOST:1337/v1", "HTTP://LOCALHOST:1337/v1"),
        ("http://127.8.9.10:1234/v1", "http://127.8.9.10:1234/v1"),  # all of 127.0.0.0/8
        ("http://[::1]:1234/v1", "http://[::1]:1234/v1"),
        ("https://localhost/v1", "https://localhost/v1"),
    ],
)
def test_a_server_on_this_computer_is_used_where_it_is(url, kept):
    assert llm.local_url(url) == kept


def test_a_servers_requests_go_through_no_proxy_and_follow_no_redirect(monkeypatch):
    import urllib.request

    def proxied(opener):
        return any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)

    monkeypatch.setenv("http_proxy", "http://proxy.example:3128")
    assert proxied(urllib.request.build_opener())  # as urlopen would go: through the proxy
    assert not proxied(llm._opener()) and not proxied(llm._direct.__self__)
    handlers = llm._direct.__self__.handlers
    redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert redirects and all(isinstance(h, llm._Stay) for h in redirects)
    request = urllib.request.Request("http://127.0.0.1:1234/v1/models")
    assert redirects[0].redirect_request(request, None, 302, "Found", {}, "http://x.ex") is None


def test_a_servers_answer_leaves_its_line_in_the_log_as_this_computers(monkeypatch, tmp_path):
    log = tmp_path / "state" / "model-calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)
    sent = served(monkeypatch, "<think>\nShe asked about the 3rd.\n</think>\n\nSee you then.")

    assert llm.ask(SAID, system=SYSTEM) == "See you then."  # its thinking isn't the answer

    system, user = sent[0][1]["messages"]
    assert (system["content"], user["content"]) == (SYSTEM, SAID)  # nothing left this computer
    line = json.loads(log.read_text())
    assert line["where"] == "this computer" and line["model"] == "local:qwen3-8b"
    assert line["redacted"] is None and (line["tokens_in"], line["tokens_out"]) == (12, 5)
    assert line["answer_chars"] == len("See you then.") and line["ok"] is True
    for secret in ("482913", "hunter2", "See you"):
        assert secret not in log.read_text()


def test_a_server_that_cant_hold_a_schema_is_asked_again_without_one(monkeypatch):
    import io
    from urllib.error import HTTPError

    sent = []
    schema = {"type": "object", "required": ["x"]}

    def opened(request, timeout):
        body = json.loads(request.data)
        sent.append(body)
        if "response_format" in body and body["model"] == "plain":
            said = b"{\"error\":\"'response_format.type' must be 'json_schema' or 'text'\"}"
            raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(said))
        return Events(evented('{"x": 1}'))

    monkeypatch.setattr(llm, "_direct", opened)
    monkeypatch.setattr(llm, "_NO_GRAMMAR", set())
    monkeypatch.setenv("PROXENOS_MODEL", "local:held")
    assert llm.ask("hi", schema=schema) == {"x": 1}
    assert "response_format" in sent[-1]

    monkeypatch.setenv("PROXENOS_MODEL", "local:plain")
    sent.clear()
    assert llm.ask("hi", schema=schema) == {"x": 1}
    assert ["response_format" in body for body in sent] == [True, False]
    sent.clear()
    assert llm.ask("again", schema=schema) == {"x": 1}
    assert ["response_format" in body for body in sent] == [False]  # not asked with one again
    assert llm._NO_GRAMMAR == {"local:plain"}

    def missing(request, timeout):  # any other refusal is the answer
        said = io.BytesIO(b'{"error":"model gone not found"}')
        raise HTTPError(request.full_url, 404, "Not Found", {}, said)

    monkeypatch.setattr(llm, "_direct", missing)
    monkeypatch.setenv("PROXENOS_MODEL", "local:gone")
    with pytest.raises(llm.ModelError, match="not found"):
        llm.ask("hi", schema=schema)
    assert "local:gone" not in llm._NO_GRAMMAR


def test_a_servers_answer_cut_off_stalled_or_failing_fails_rather_than_truncates(monkeypatch):
    sent = served(monkeypatch, "partial", "length")
    with pytest.raises(llm.ModelError, match="too long"):
        llm.ask("x" * llm.LOCAL_CONTEXT * 3)
    assert not sent  # never sent
    with pytest.raises(llm.ModelError, match="cut off"):
        llm.ask("hi")

    served(monkeypatch, "", chunks=evented("a long")[:2], then=TimeoutError("timed out"))
    with pytest.raises(llm.ModelError, match="isn't answering.*http://127.0.0.1:1234/v1"):
        llm.ask("hi")
    served(monkeypatch, "", chunks=evented("a long")[:2])  # the stream ended with no reason
    with pytest.raises(llm.ModelError, match="stopped mid-answer"):
        llm.ask("hi")
    served(monkeypatch, "", chunks=[{"error": {"message": "the model crashed"}}])
    with pytest.raises(llm.ModelError, match="the model crashed"):
        llm.ask("hi")
    served(monkeypatch, "", chunks=[b"{not json"])
    with pytest.raises(llm.ModelError, match="stopped mid-answer"):
        llm.ask("hi")

    def down(request, timeout):
        raise llm.urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm, "_direct", down)
    with pytest.raises(llm.ModelError, match="isn't answering"):
        llm.ask("hi")

    monkeypatch.setattr(llm, "_LOCAL_DEADLINE", -1)  # past the deadline, still going
    served(monkeypatch, "a long answer")
    with pytest.raises(llm.ModelError, match="still answering"):
        llm.ask("hi")


def test_a_voice_model_on_another_server(monkeypatch):
    sent = served(monkeypatch, "yaa")
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "local:tess-voice")
    assert llm.ask_voice("the chat", "You are Tess.") == "yaa"
    body = sent[0][1]
    assert body["model"] == "tess-voice" and body["max_tokens"] == llm.VOICE_TOKENS
    assert "response_format" not in body


def test_a_models_name_without_where_it_runs():
    assert llm.bare("ollama:gemma4:26b") == "gemma4:26b"
    assert llm.bare("local:qwen/qwen3-8b") == "qwen/qwen3-8b"
    assert llm.bare("claude-opus-5-5") == "claude-opus-5-5"
