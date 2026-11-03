"""The one place Proxenos talks to a model.

PROXENOS_MODEL picks it. A model on this computer needs no account or key, and nothing leaves the
computer: the prompt is everything the model knows, built in code from the vault each time.
"ollama:<name>" runs an open model through Ollama (ollama.com). "local:<name>" runs one through
any other server on this computer that speaks OpenAI's chat API, at PROXENOS_LOCAL_URL: LM Studio
(http://127.0.0.1:1234/v1, the default), llama.cpp's llama-server (http://127.0.0.1:8080/v1),
vLLM (http://127.0.0.1:8000/v1), Jan or LocalAI. That address has to be this computer's own
(localhost, 127.0.0.0/8 or ::1), and the request goes through no proxy and follows no redirect,
so nothing leaves the computer that way either. Any other name calls the Anthropic API with a
personal key (ANTHROPIC_API_KEY, in the Keychain or .env), kept apart from any work or university
account; its base URL is pinned so a host app's ANTHROPIC_BASE_URL (the Claude desktop app sets
one) never reroutes the key. Everything goes through `ask`.

PROXENOS_VOICE_MODEL, off when empty, names a voice model for reply drafts (proxenos.voicemodel): "mlx"
for `proxenos voice serve` on this computer ("mlx:<port>" on another port), or "ollama:<name>"
or "local:<name>" for one served the ways above. It goes through `ask_voice`. `using` points the
calls made inside it at other models than these settings name, so proxenos.compare can draft one
reply with two.

What goes to Anthropic has the numbers and secrets no draft needs blanked first: card and
Social Security numbers, one-time codes, passwords, keys and tokens, bank account numbers
(proxenos.redact).

Every call leaves one line in <vault>/state/model-calls.jsonl, for the privacy screen and for
seeing what a night costs: when, which step asked, the model, where it ran (this computer or
Anthropic), how many characters went in and came back, the tokens where the model counts them,
how many numbers and secrets were blanked, how long it took and whether it worked. Never the
words, nor what was blanked.
"""

import http.client
import ipaddress
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from proxenos import lock, redact
from proxenos.config import env, vault_path

# PROXENOS_MODEL overrides it; read on each call, so a value saved in Settings or .env counts too.
DEFAULT_MODEL = "claude-opus-5-5"
_API = "https://api.anthropic.com"
# On a policy decline the API reruns the request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

OLLAMA = "ollama:"
SERVER = "local:"  # an OpenAI-compatible server on this computer: LM Studio, llama-server, ...
# Either runs on this computer. A tuple, so `model.startswith(LOCAL)` asks about both.
LOCAL = (OLLAMA, SERVER)
_OLLAMA = "http://127.0.0.1:11434"
# LM Studio's server; PROXENOS_LOCAL_URL names another, such as llama-server's on port 8080.
DEFAULT_LOCAL_URL = "http://127.0.0.1:1234/v1"
# Tokens a local model reads and writes at once: room for a reply's chat and pages, within
# what a 32 GB Mac holds beside the model. A prompt past it fails rather than being cut.
LOCAL_CONTEXT = 65536
# A local answer streams in as it's written, so a long one isn't cut at a fixed time: a laptop
# writes ten to twenty-five tokens a second, slower the longer the prompt, and care's thinking and
# answer, about 10k tokens, take it twenty minutes. Ollama counts as not answering after
# _LOCAL_TIMEOUT seconds without a word (reading a long prompt comes first, a few minutes), and an
# answer still going at _LOCAL_DEADLINE fails.
_LOCAL_TIMEOUT = 900
_LOCAL_DEADLINE = 3600
_JSON_ONLY = "Answer with one JSON object and nothing else, matching this JSON schema:"
# What Ollama says when its build can't hold a model to a schema, what another server's refusal
# of `response_format` names, and the models (as PROXENOS_MODEL names them) either was said of.
_UNGRAMMATICAL = "structured output is unavailable"
_NO_SCHEMA = re.compile(r"response_format|schema|grammar|guided|structured", re.IGNORECASE)
_NO_GRAMMAR: set[str] = set()
# Thinking a server leaves in the words, where it doesn't part it out as reasoning_content.
_THINKING = re.compile(r"\A\s*<think>.*?</think>\s*", re.DOTALL)
# A local model answers one request at a time, so a question someone is waiting on (an Ask)
# marks itself here, and other calls, a sync's drafts or the night's notes, wait until it's
# answered: for at most FOREGROUND_MAX seconds, past which a mark counts as left behind.
_FOREGROUND = "state/asking"
FOREGROUND_MAX = 900
CALLS = "state/model-calls.jsonl"
CALLS_KEPT = 20000  # lines kept, newest last: months of nights and syncs
VOICE_PORT = 8899
VOICE_TEMPERATURE = 0.7
VOICE_TOKENS = 600
_VOICE_TIMEOUT = 120

_client: anthropic.Anthropic | None = None


class ModelError(RuntimeError):
    pass


def ask(
    prompt: str,
    *,
    system: str | None = None,
    schema: dict | None = None,
    effort: str = "medium",
    max_tokens: int = 32000,
    images: list[dict] | None = None,
    keep: Iterable[str] = (),
) -> str | dict:
    """One request, one answer: text, or a dict matching `schema` when one is given.

    The system prompt is marked cacheable, so repeated calls that share it (ranking runs
    against the same profile) only pay full price for it once. Requests stream, so long
    inputs and long answers don't hit HTTP timeouts. `keep` is what a hosted model is meant to
    read although it would be blanked, such as an account number a call may tell.
    """
    model = current()
    sent = len(prompt) + len(system or "")
    with _recorded(model, sent, len(images or [])) as answered:
        answer = _ask(model, prompt, system, schema, effort, max_tokens, images, keep)
        answered(answer)
    return answer


def _ask(
    model: str,
    prompt: str,
    system: str | None,
    schema: dict | None,
    effort: str,
    max_tokens: int,
    images: list[dict] | None,
    keep: Iterable[str] = (),
) -> str | dict:
    if model.startswith(LOCAL):
        return _ask_local(model, prompt, system, schema, effort, max_tokens, images)
    # Leaving this computer: the numbers and secrets no draft needs are blanked first, and the
    # log keeps only how many. Images go as they are; nothing here reads the text in them.
    prompt, blanked = redact.redact(prompt, keep)
    system, also = redact.redact(system, keep) if system else (system, {})
    _usage.redacted = sum(blanked.values()) + sum(also.values())
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": _content(prompt, images)}],
        "output_config": output_config,
        "betas": [_FALLBACK_BETA],
        "fallbacks": "default",
    }
    if system:
        params["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]

    with _get_client().beta.messages.stream(**params) as stream:
        response = stream.get_final_message()
    usage = getattr(response, "usage", None)
    _usage.tokens = (getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    if response.stop_reason == "refusal":
        raise ModelError(f"model declined: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise ModelError(f"answer cut off at max_tokens={max_tokens}")
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text) if schema is not None else text


# The models and step name `using` sets for the calls made inside it, per thread.
_using = threading.local()


@contextmanager
def using(
    model: str | None = None, voice: str | None = None, step: str | None = None
) -> Iterator[None]:
    """Inside it, in this thread only, `ask` goes to `model` (a PROXENOS_MODEL value),
    `ask_voice` to `voice` (a PROXENOS_VOICE_MODEL value), and each call is logged as `step`,
    in place of the settings and the asking module's name. proxenos.compare drafts the same
    reply with two models this way, through the same code a reply draft runs."""
    saved = tuple(getattr(_using, key, None) for key in ("model", "voice", "step"))
    _using.model, _using.voice, _using.step = model, voice, step
    try:
        yield
    finally:
        _using.model, _using.voice, _using.step = saved


def current() -> str:
    """The model `ask` goes to: PROXENOS_MODEL, unless `using` names another."""
    return getattr(_using, "model", None) or env("MODEL", DEFAULT_MODEL)


@contextmanager
def foreground(vault: Path) -> Iterator[None]:
    """While this runs, other processes' local model calls hold off (see `waiting`)."""
    mark = vault / _FOREGROUND
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(str(os.getpid()))
    try:
        yield
    finally:
        mark.unlink(missing_ok=True)


def waiting(vault: Path | None = None) -> bool:
    """Whether another process is answering a question someone is waiting on."""
    mark = (vault or vault_path()) / _FOREGROUND
    try:
        pid, age = int(mark.read_text()), time.time() - mark.stat().st_mtime
    except (OSError, ValueError):
        return False
    if pid == os.getpid() or age > FOREGROUND_MAX:
        return False
    return lock.alive(pid)  # not when it ended without clearing its mark


def configured() -> bool:
    """Whether a model is set up (a local one, or a key), so steps that are optional can skip
    the model rather than fail."""
    local = current().startswith(LOCAL)
    return local or bool(os.environ.get("ANTHROPIC_API_KEY"))


def prompt_chars() -> int | None:
    """How much prompt, in characters, the model set up takes in one request, for steps that
    trim what they send to fit; None when the limit is far past what any step sends."""
    if current().startswith(LOCAL):
        return (LOCAL_CONTEXT - LOCAL_CONTEXT // 4) * 3  # as _ask_local counts it
    return None


def fit(limit: int, overhead: int = 30_000) -> int:
    """`limit` characters of records, or fewer when the model can't take that many beside
    `overhead` characters of instructions and the rest of the prompt."""
    room = prompt_chars()
    return limit if room is None else max(10_000, min(limit, room - overhead))


def bare(model: str) -> str:
    """A model's name without what says where it runs: "gemma4:26b" for "ollama:gemma4:26b"."""
    for prefix in LOCAL:
        if model.startswith(prefix):
            return model.removeprefix(prefix)
    return model


def local_url(url: str | None = None) -> str:
    """The OpenAI-compatible server's address (`url`, else PROXENOS_LOCAL_URL, else LM Studio's),
    without a trailing slash, once it's sure to be this computer's own. Anything else is refused,
    so a "local:" model never sends a prompt off the computer, nor does setup ask another host."""
    url = (env("LOCAL_URL") if url is None else url).strip().rstrip("/") or DEFAULT_LOCAL_URL
    if not _loopback(url):
        raise ModelError(
            f"{url} isn't on this computer. A local model's server has to be at localhost, "
            f"127.0.0.1 or [::1], like {DEFAULT_LOCAL_URL}, so nothing leaves the computer."
        )
    return url


def _loopback(url: str) -> bool:
    """Whether `url` is plain http(s) to localhost, 127.0.0.0/8 or ::1. A user name, query or
    fragment is refused outright, as each can make a URL read as one host and reach another
    (http://127.0.0.1@example.com goes to example.com), and so is a host only named like
    loopback (127.0.0.1.example.com)."""
    if any(c <= " " or c in "@?#\\" for c in url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018 - a port that isn't a number raises here
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _Stay(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: the server on this computer answers itself, or the request fails."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener() -> urllib.request.OpenerDirector:
    """How a request reaches the server on this computer: through no proxy, even one the
    environment names, and following no redirect, so it goes there and nowhere else."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _Stay())


_direct = _opener().open


def _content(prompt: str, images: list[dict] | None) -> str | list[dict]:
    """The prompt, after any images ({type: "image/png", data: base64}) for the model to see."""
    if not images:
        return prompt
    seen = [
        {"type": "image", "source": {"type": "base64", "media_type": i["type"], "data": i["data"]}}
        for i in images
    ]
    return [*seen, {"type": "text", "text": prompt}]


def _ask_local(
    model: str,
    prompt: str,
    system: str | None,
    schema: dict | None,
    effort: str,
    max_tokens: int,
    images: list[dict] | None = None,
) -> str | dict:
    """`ask`, answered by a model on this computer: "ollama:<name>" through Ollama's API, and
    "local:<name>" through the OpenAI-compatible server's (`_complete`). A schema goes in the
    system prompt and in the request (Ollama's `format`, the server's `response_format`), which
    holds the model to it as it writes, thinking first or not. Some can't: Ollama installed from
    Homebrew answers "structured output is unavailable" (its build leaves out the grammar
    library), and another server may refuse `response_format` with an error that names it. Then
    the request goes again without it, and that model isn't asked with one again in this process.
    Either way the answer is held to the schema here (`_object`), with one more try when it isn't
    the JSON asked for."""
    served, name = model.startswith(SERVER), bare(model)
    answer_room = min(max_tokens, LOCAL_CONTEXT // 4)
    if schema is not None:
        system = f"{system or ''}\n\n{_JSON_ONLY}\n{json.dumps(schema)}".strip()
    if (len(prompt) + len(system or "")) // 3 > LOCAL_CONTEXT - answer_room:  # ~3 chars a token
        raise ModelError(f"prompt too long for the local model's {LOCAL_CONTEXT}-token context")
    messages = [{"role": "system", "content": system}] if system else []
    if served:
        chat, held, cant = _complete, "response_format", _NO_SCHEMA.search
        body = _served_body(name, messages, prompt, images, answer_room)
        holds: dict | None = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema},
        }
    else:
        chat, held, cant = _chat, "format", lambda said: _UNGRAMMATICAL in said
        body = {
            "model": name,
            "messages": [
                *messages,
                {"role": "user", "content": prompt}
                | ({"images": [i["data"] for i in images]} if images else {}),
            ],
            "stream": True,
            # Thinking first is for the hard jobs; a draft doesn't need it and is ten times faster.
            "think": effort in ("high", "xhigh", "max"),
            "options": {"num_ctx": LOCAL_CONTEXT, "num_predict": answer_room},
        }
        holds = schema
    if schema is not None and model not in _NO_GRAMMAR:
        body[held] = holds
    deadline = time.monotonic() + FOREGROUND_MAX
    while waiting() and time.monotonic() < deadline:
        time.sleep(2)
    for _ in range(2):
        try:
            text = chat(name, body, answer_room)
        except ModelError as e:
            if held not in body or not cant(str(e)):
                raise
            _NO_GRAMMAR.add(model)
            body.pop(held)
            text = chat(name, body, answer_room)
        if schema is None:
            return text
        if (answer := _object(text, schema)) is not None:
            return answer
    raise ModelError(f"local model {name} didn't answer with the JSON asked for")


def _served_body(
    model: str, messages: list[dict], prompt: str, images: list[dict] | None, answer_room: int
) -> dict:
    """A chat request as OpenAI's API has it, for the server on this computer. The context is
    the server's own, set when it loads the model, so it isn't asked for here as Ollama's is;
    nor is thinking, which each server turns on its own way, if at all."""
    seen = [
        {"type": "image_url", "image_url": {"url": f"data:{i['type']};base64,{i['data']}"}}
        for i in images or []
    ]
    content = [*seen, {"type": "text", "text": prompt}] if seen else prompt
    return {
        "model": model,
        "messages": [*messages, {"role": "user", "content": content}],
        "stream": True,
        "stream_options": {"include_usage": True},  # the tokens, in a last piece of their own
        "max_tokens": answer_room,
    }


def _object(text: str, schema: dict) -> dict | None:
    """The first JSON object in a local model's answer that fits the schema, held to it the way
    a hosted model's answer is (`_conform`). A model may echo the schema before its answer,
    whose own parts can have the same keys, or wrap the answer in a code fence."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            found, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(found, dict) and (held := _conform(found, schema)) is not _UNFIT:
            return held
        start = text.find("{", start + 1)  # inside it: the answer may be nested in the echo
    return None


_UNFIT = object()  # what _conform returns for a value the schema doesn't allow
_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _conform(value: object, schema: dict) -> object:
    """`value` as the schema allows it, or _UNFIT. A local model held to no grammar can leave a
    required key out of one item of a list ("first_step" in one idea of five): that item goes,
    and the rest stay, rather than one gap failing the whole answer or the clone that reads it.
    An object missing a required key, or a value of another type, is unfit; a key the schema
    doesn't list goes when it says additionalProperties is false."""
    kinds = schema.get("type")
    if kinds is not None:
        wanted = tuple(_TYPES[k] for k in ([kinds] if isinstance(kinds, str) else kinds))
        is_bool = isinstance(value, bool)
        if not isinstance(value, wanted) or (is_bool and bool not in wanted):
            return _UNFIT
    if "enum" in schema and value not in schema["enum"]:
        return _UNFIT
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        held = (_conform(item, schema["items"]) for item in value)
        return [item for item in held if item is not _UNFIT]
    if isinstance(value, dict) and ("properties" in schema or "required" in schema):
        props, kept = schema.get("properties"), {}
        for key, item in value.items():
            if props is None or key not in props:
                if props is None or schema.get("additionalProperties") is not False:
                    kept[key] = item
            elif (held := _conform(item, props[key])) is not _UNFIT:
                kept[key] = held
        return kept if set(schema.get("required", [])) <= set(kept) else _UNFIT
    return value


def _chat(model: str, body: dict, answer_room: int) -> str:
    """The answer to one Ollama chat request, read as it streams in, one JSON line at a time:
    its thinking, then its words, then a last line that says why it stopped."""
    request = urllib.request.Request(
        f"{_OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    deadline = time.monotonic() + _LOCAL_DEADLINE
    words: list[str] = []
    last: dict = {}
    try:
        with urllib.request.urlopen(request, timeout=_LOCAL_TIMEOUT) as response:
            for line in response:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ModelError(f"local model {model}: {str(chunk['error'])[:300]}")
                words.append((chunk.get("message") or {}).get("content") or "")
                if chunk.get("done"):
                    last = chunk
                    break
                if time.monotonic() > deadline:
                    raise ModelError(
                        f"local model {model} was still answering after "
                        f"{_LOCAL_DEADLINE // 60} minutes"
                    )
    except urllib.error.HTTPError as e:
        raise ModelError(f"local model {model}: {e.read().decode(errors='replace')[:300]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"the local model isn't answering ({e}); is Ollama running?") from e
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise ModelError(f"local model {model} stopped mid-answer ({e})") from e
    if not last:
        raise ModelError(f"local model {model} stopped mid-answer")
    _usage.tokens = (last.get("prompt_eval_count"), last.get("eval_count"))
    if last.get("done_reason") == "length":
        raise ModelError(f"answer cut off at {answer_room} tokens")
    return "".join(words)


def _complete(model: str, body: dict, answer_room: int) -> str:
    """The answer to one chat request to the OpenAI-compatible server, read as it streams in:
    server-sent events, each a `data:` line with a piece of the words, until one says why it
    stopped and `data: [DONE]` ends them. Thinking the server parts out (`reasoning_content`) is
    left out, and so is a <think> block a model leaves at the start of its words."""
    url = f"{local_url()}/chat/completions"
    request = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    deadline = time.monotonic() + _LOCAL_DEADLINE
    words: list[str] = []
    stopped, usage = None, {}
    try:
        with _direct(request, timeout=_LOCAL_TIMEOUT) as response:
            for line in response:
                field, _, data = line.strip().partition(b":")
                if field != b"data" or not data.strip():
                    continue  # a blank line between events, a comment, or another field
                data = data.strip()
                if data == b"[DONE]":
                    stopped = stopped or "stop"
                    break
                chunk = json.loads(data)
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    raise ModelError(f"local model {model}: {str(chunk['error'])[:300]}")
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    words.append((choice.get("delta") or {}).get("content") or "")
                    stopped = choice.get("finish_reason") or stopped
                if time.monotonic() > deadline:
                    raise ModelError(
                        f"local model {model} was still answering after "
                        f"{_LOCAL_DEADLINE // 60} minutes"
                    )
    except urllib.error.HTTPError as e:  # a redirect, too, which is followed no further
        said = e.read().decode(errors="replace")[:300] or f"HTTP {e.code} {e.reason}"
        raise ModelError(f"local model {model}: {said}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(
            f"the local model isn't answering ({e}); is its server running at {url}?"
        ) from e
    except (OSError, ValueError, AttributeError, http.client.HTTPException) as e:
        raise ModelError(f"local model {model} stopped mid-answer ({e})") from e
    if stopped is None:
        raise ModelError(f"local model {model} stopped mid-answer")
    _usage.tokens = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
    if stopped == "length":
        raise ModelError(f"answer cut off at {answer_room} tokens")
    return _THINKING.sub("", "".join(words), count=1)


def voice_on() -> bool:
    """Whether reply drafts go to a voice model."""
    return bool(env("VOICE_MODEL").strip())


def ask_voice(prompt: str, system: str, max_tokens: int = VOICE_TOKENS) -> str:
    """One answer from the voice model, as plain text: no schema, which a small model trained
    only to write as the user wouldn't keep to."""
    model = getattr(_using, "voice", None) or env("VOICE_MODEL").strip()
    with _recorded(f"voice:{model}", len(prompt) + len(system), 0) as answered:
        answer = _ask_voice(model, prompt, system, max_tokens)
        answered(answer)
    return answer


def _ask_voice(model: str, prompt: str, system: str, max_tokens: int) -> str:
    if model.startswith(LOCAL):
        return _ask_local(model, prompt, system, None, "low", max_tokens)
    kind, _, port = model.partition(":")
    if kind != "mlx" or not (port or str(VOICE_PORT)).isdigit():
        raise ModelError(
            f"{model} isn't a voice model: give mlx, mlx:<port>, ollama:<name> or local:<name>"
        )
    body = {
        "model": "default_model",  # the one `proxenos voice serve` started with, adapter and all
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": VOICE_TEMPERATURE,
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{port or VOICE_PORT}/v1/chat/completions",
        json.dumps(body).encode(),
        {"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_VOICE_TIMEOUT) as response:
            answer = json.load(response)
        return answer["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise ModelError(f"voice model: {e.read().decode(errors='replace')[:300]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"the voice model isn't answering ({e}); is it being served?") from e
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ModelError(f"the voice model's answer wasn't one ({e})") from e


# What one call cost and how much of it was blanked, set by the call, read by _recorded; per
# thread, as a phone call's turns can run beside a sync.
_usage = threading.local()


@contextmanager
def _recorded(model: str, sent: int, images: int) -> Iterator[Callable[[object], None]]:
    """Time the call inside it and leave its line in the calls log, whether it worked or not.
    The call hands its answer to the function this yields, for the answer's size."""
    began, got = time.monotonic(), {}
    _usage.tokens, _usage.redacted = (None, None), None
    try:
        yield lambda answer: got.setdefault("answer", answer)
    finally:
        answer = got.get("answer")
        size = len(answer if isinstance(answer, str) else json.dumps(answer)) if got else 0
        tokens_in, tokens_out = getattr(_usage, "tokens", (None, None))
        here = model.startswith((*LOCAL, *(f"voice:{p}" for p in (*LOCAL, "mlx"))))
        record = {
            "at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "step": _step(),
            "model": model,
            "where": "this computer" if here else "Anthropic",
            "sent_chars": sent,
            "images": images,
            "redacted": getattr(_usage, "redacted", None),  # None where nothing left
            "answer_chars": size,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "seconds": round(time.monotonic() - began, 1),
            "ok": bool(got),
        }
        _log(record)


def _step() -> str:
    """The part of Proxenos that asked: the innermost of its modules on the call's stack outside
    this one ("tasks", "forms", "calls"), else "proxenos"; inside `using`, the step it names."""
    if step := getattr(_using, "step", None):
        return step
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        if name.startswith("proxenos.") and name not in (__name__, "contextlib"):
            return name.rsplit(".", 1)[-1]
        frame = frame.f_back
    return "proxenos"


def _calls_path() -> Path | None:
    """The calls log, or None while there's no vault to keep it in."""
    try:
        vault = vault_path()
    except ValueError:
        return None
    return vault / CALLS if vault.is_dir() else None


def _log(record: dict) -> None:
    """Append one call's line, private to the user, keeping the newest CALLS_KEPT. A log that
    can't be written never fails the call it records."""
    path = _calls_path()
    if path is None:
        return
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        if path.stat().st_size > CALLS_KEPT * 400:  # about twice the lines kept: trim
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)[-CALLS_KEPT:]
            tmp = path.with_name(f".{path.name}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp, path)
    except OSError:
        pass


def calls(vault: Path, since: str | None = None) -> list[dict]:
    """The calls log's lines, oldest first, from `since` (an ISO time) on."""
    try:
        lines = (vault / CALLS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue  # a line being written
        if isinstance(item, dict) and (since is None or str(item.get("at", "")) >= since):
            found.append(item)
    return found


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set. Add a personal key from console.anthropic.com "
                "in the page's Settings, or in .env"
            )
        _client = anthropic.Anthropic(api_key=key, base_url=_API)
    return _client
