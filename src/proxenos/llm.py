"""The one place Proxenos talks to a model.

Calls the Anthropic API with a personal key (ANTHROPIC_API_KEY in .env), kept apart from any
work or university account. The base URL is pinned so a host app's ANTHROPIC_BASE_URL (the
Claude desktop app sets one) never reroutes the key. Everything goes through `ask`, so a
different backend later only touches this file.
"""

import json
import os

import anthropic

from proxenos.config import env

# PROXENOS_MODEL overrides it; read on each call, so the value in .env counts too.
DEFAULT_MODEL = "claude-opus-5-5"
_API = "https://api.anthropic.com"
# On a policy decline the API reruns the request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

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
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    params: dict = {
        "model": env("MODEL", DEFAULT_MODEL),
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
