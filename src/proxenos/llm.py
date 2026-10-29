"""The one place Proxenos talks to a model.

PROXENOS_MODEL picks it. "ollama:<name>" runs an open model on this Mac through Ollama
(ollama.com), so nothing leaves the computer and no account or key is needed: the prompt is
everything the model knows, built in code from the vault each time. Any other name calls the
Anthropic API with a personal key (ANTHROPIC_API_KEY, in the Keychain or .env), kept apart from
any work or university account; its base URL is pinned so a host app's ANTHROPIC_BASE_URL (the
Claude desktop app sets one) never reroutes the key. Everything goes through `ask`.
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import anthropic

from proxenos import lock
from proxenos.config import env, vault_path

# PROXENOS_MODEL overrides it; read on each call, so a value saved in Settings or .env counts too.
DEFAULT_MODEL = "claude-opus-5-5"
_API = "https://api.anthropic.com"
# On a policy decline the API reruns the request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

LOCAL = "ollama:"
_OLLAMA = "http://127.0.0.1:11434"
# Tokens a local model reads and writes at once: room for a reply's chat and pages, within
# what a 32 GB Mac holds beside the model. A prompt past it fails rather than being cut.
LOCAL_CONTEXT = 65536
_LOCAL_TIMEOUT = 900  # seconds; a long answer on a laptop takes minutes, not hours
_JSON_ONLY = "Answer with one JSON object and nothing else, matching this JSON schema:"
# A local model answers one request at a time, so a question someone is waiting on (an Ask)
# marks itself here, and other calls, a sync's drafts or the night's notes, wait until it's
# answered: for at most FOREGROUND_MAX seconds, past which a mark counts as left behind.
_FOREGROUND = "state/asking"
FOREGROUND_MAX = 900

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
) -> str | dict:
    """One request, one answer: text, or a dict matching `schema` when one is given.

    The system prompt is marked cacheable, so repeated calls that share it (ranking runs
    against the same profile) only pay full price for it once. Requests stream, so long
    inputs and long answers don't hit HTTP timeouts.
    """
    model = env("MODEL", DEFAULT_MODEL)
    if model.startswith(LOCAL):
        return _ask_local(
            model.removeprefix(LOCAL), prompt, system, schema, effort, max_tokens, images
        )
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
    if response.stop_reason == "refusal":
        raise ModelError(f"model declined: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise ModelError(f"answer cut off at max_tokens={max_tokens}")
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text) if schema is not None else text


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
    local = env("MODEL", DEFAULT_MODEL).startswith(LOCAL)
    return local or bool(os.environ.get("ANTHROPIC_API_KEY"))


def prompt_chars() -> int | None:
    """How much prompt, in characters, the model set up takes in one request, for steps that
    trim what they send to fit; None when the limit is far past what any step sends."""
    if env("MODEL", DEFAULT_MODEL).startswith(LOCAL):
        return (LOCAL_CONTEXT - LOCAL_CONTEXT // 4) * 3  # as _ask_local counts it
    return None


def fit(limit: int, overhead: int = 30_000) -> int:
    """`limit` characters of records, or fewer when the model can't take that many beside
    `overhead` characters of instructions and the rest of the prompt."""
    room = prompt_chars()
    return limit if room is None else max(10_000, min(limit, room - overhead))


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
    """`ask`, answered by a model on this Mac through Ollama's API. Ollama can't hold every
    model to a schema, so a schema goes in the system prompt and the answer is checked here,
    with one more try when it isn't the JSON asked for."""
    answer_room = min(max_tokens, LOCAL_CONTEXT // 4)
    if schema is not None:
        system = f"{system or ''}\n\n{_JSON_ONLY}\n{json.dumps(schema)}".strip()
    if (len(prompt) + len(system or "")) // 3 > LOCAL_CONTEXT - answer_room:  # ~3 chars a token
        raise ModelError(f"prompt too long for the local model's {LOCAL_CONTEXT}-token context")
    messages = [{"role": "system", "content": system}] if system else []
    body = {
        "model": model,
        "messages": [
            *messages,
            {"role": "user", "content": prompt}
            | ({"images": [i["data"] for i in images]} if images else {}),
        ],
        "stream": False,
        # Thinking first is for the hard jobs; a draft doesn't need it and is ten times faster.
        "think": effort in ("high", "xhigh", "max"),
        "options": {"num_ctx": LOCAL_CONTEXT, "num_predict": answer_room},
    }
    deadline = time.monotonic() + FOREGROUND_MAX
    while waiting() and time.monotonic() < deadline:
        time.sleep(2)
    for _ in range(2):
        text = _chat(model, body, answer_room)
        if schema is None:
            return text
        try:
            answer = json.loads(text[text.index("{") : text.rindex("}") + 1])
        except ValueError:
            continue
        if isinstance(answer, dict) and set(schema.get("required", [])) <= set(answer):
            return answer
    raise ModelError(f"local model {model} didn't answer with the JSON asked for")


def _chat(model: str, body: dict, answer_room: int) -> str:
    request = urllib.request.Request(
        f"{_OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=_LOCAL_TIMEOUT) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as e:
        raise ModelError(f"local model {model}: {e.read().decode(errors='replace')[:300]}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(f"the local model isn't answering ({e}); is Ollama running?") from e
    if answer.get("done_reason") == "length":
        raise ModelError(f"answer cut off at {answer_room} tokens")
    return answer["message"]["content"]


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
