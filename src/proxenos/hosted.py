"""OpenAI's and Gemini's own model lists, for checking a key and picking a model on the setup page.

A key is checked by asking the provider which models it has (GET <base>/models with the key as a
bearer token), which spends no tokens. The names it lists are the provider's own, so none is
written down here to go stale; only the chat ones are offered (embeddings, speech, images and the
like are left out), and one is suggested by a plain pattern: OpenAI's first "gpt-" model with
"mini" in its name, else its first "gpt-"; Gemini's first "gemini-" model with "flash" in it and
not "lite", "preview", "image" or "tts", else its first "gemini-". Requests go to the addresses
llm.CHAT_HOSTS pins, following no redirect, and what the provider says back is shown with the
key blanked from it.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from proxenos import llm

_TIMEOUT = 20
_NOT_CHAT = (
    *("embedding", "embed", "tts", "image", "audio", "realtime", "transcribe", "whisper"),
    *("moderation", "instruct", "search", "live", "dall", "davinci", "aqa", "robotics"),
)
_FLASH_NOT = ("lite", "preview", "image", "tts")
SITES = {llm.OPENAI: "platform.openai.com", llm.GEMINI: "aistudio.google.com"}


def prefix(provider: str) -> str:
    """The model-name prefix of a provider, "openai" or "gemini"."""
    if provider not in ("openai", "gemini"):
        raise ValueError("The provider is anthropic, openai or gemini.")
    return f"{provider}:"


def list_models(provider: str, key: str, opener: Callable | None = None) -> list[str]:
    """The chat models the key can use, by the provider's own names, sorted. ValueError, with a
    sentence for the page, when the key isn't accepted or the provider can't be reached."""
    lead = prefix(provider)
    label, base, _ = llm.CHAT_HOSTS[lead]
    request = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with (opener or llm._remote)(request, timeout=_TIMEOUT) as response:
            listed = json.load(response).get("data") or []
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            raise ValueError(
                f"{label} didn't accept that key. Copy it again from {SITES[lead]}."
            ) from None
        raise ValueError(
            f"{label} answered with an error ({e.code}). Try again in a minute."
        ) from None
    except (OSError, ValueError, AttributeError):
        raise ValueError(
            f"Couldn't reach {label}. Check the internet connection and try again."
        ) from None
    names = {
        str(m["id"]).removeprefix("models/")
        for m in listed
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    return sorted(n for n in names if _chat(lead, n))


def _chat(lead: str, name: str) -> bool:
    low = name.lower()
    if any(word in low for word in _NOT_CHAT):
        return False
    if lead == llm.OPENAI:
        return low.startswith("gpt-") or (low[:1] == "o" and low[1:2].isdigit())
    return low.startswith("gemini-")


def suggest(provider: str, names: list[str]) -> str | None:
    """The model to suggest from `names`, by the pattern in the module's notes; None for none."""
    if prefix(provider) == llm.OPENAI:
        gpt = [n for n in names if n.startswith("gpt-")]
        return next((n for n in gpt if "mini" in n), None) or next(iter(gpt), None)
    gemini = [n for n in names if n.startswith("gemini-")]
    flash = [n for n in gemini if "flash" in n and not any(w in n for w in _FLASH_NOT)]
    return next(iter(flash), None) or next(iter(gemini), None)
