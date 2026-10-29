"""The one place Proxenos talks to a model.

PROXENOS_MODEL picks it. "ollama:<name>" runs an open model on this Mac through Ollama
(ollama.com), so nothing leaves the computer and no account or key is needed: the prompt is
everything the model knows, built in code from the vault each time. Any other name calls the
Anthropic API with a personal key (ANTHROPIC_API_KEY in .env), kept apart from any work or
university account; its base URL is pinned so a host app's ANTHROPIC_BASE_URL (the Claude
desktop app sets one) never reroutes the key. Everything goes through `ask`.
"""

import json
import os
import urllib.error
import urllib.request

import anthropic

from proxenos.config import env

# PROXENOS_MODEL overrides it; read on each call, so the value in .env counts too.
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
) -> str | dict:
    """One request, one answer: text, or a dict matching `schema` when one is given.

    The system prompt is marked cacheable, so repeated calls that share it (ranking runs
    against the same profile) only pay full price for it once. Requests stream, so long
    inputs and long answers don't hit HTTP timeouts.
    """
    model = env("MODEL", DEFAULT_MODEL)
    if model.startswith(LOCAL):
        return _ask_local(model.removeprefix(LOCAL), prompt, system, schema, effort, max_tokens)
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
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


def configured() -> bool:
    """Whether a model is set up (a local one, or a key), so steps that are optional can skip
    the model rather than fail."""
    local = env("MODEL", DEFAULT_MODEL).startswith(LOCAL)
    return local or bool(os.environ.get("ANTHROPIC_API_KEY"))


def _ask_local(
    model: str, prompt: str, system: str | None, schema: dict | None, effort: str, max_tokens: int
) -> str | dict:
    """`ask`, answered by a model on this Mac through Ollama's API."""
    answer_room = min(max_tokens, LOCAL_CONTEXT // 4)
    if (len(prompt) + len(system or "")) // 3 > LOCAL_CONTEXT - answer_room:  # ~3 chars a token
        raise ModelError(f"prompt too long for the local model's {LOCAL_CONTEXT}-token context")
    messages = [{"role": "system", "content": system}] if system else []
    body: dict = {
        "model": model,
        "messages": [*messages, {"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": LOCAL_CONTEXT, "num_predict": answer_room},
    }
    if effort in ("high", "xhigh", "max"):
        body["think"] = True
    if schema is not None:
        body["format"] = schema
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
    text = answer["message"]["content"]
    return json.loads(text) if schema is not None else text


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set. Put a personal key from "
                "console.anthropic.com in .env"
            )
        _client = anthropic.Anthropic(api_key=key, base_url=_API)
    return _client
