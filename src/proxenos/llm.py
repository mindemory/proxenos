"""The one place Proxenos talks to a model.

PROXENOS_MODEL picks it. A model on this computer needs no account or key, and nothing leaves the
computer: the prompt is everything the model knows, built in code from the vault each time.
"ollama:<name>" runs an open model through Ollama (ollama.com). "local:<name>" runs one through
any other server on this computer that speaks OpenAI's chat API, at PROXENOS_LOCAL_URL: LM Studio
(http://127.0.0.1:1234/v1, the default), llama.cpp's llama-server (http://127.0.0.1:8080/v1),
vLLM (http://127.0.0.1:8000/v1), Jan or LocalAI. That address has to be this computer's own
(localhost, 127.0.0.0/8 or ::1), and the request goes through no proxy and follows no redirect,
so nothing leaves the computer that way either. "openai:<name>" and "gemini:<name>" are hosted
models, spoken to in the same chat API at OpenAI's and Google's own addresses with a bearer key
(OPENAI_API_KEY, GEMINI_API_KEY): what goes to them is treated as what goes to Anthropic (the
same blanking, never the fast model, logged as not on this computer), and the rule that holds
"local:" to this computer's address stays as it was. Any other name calls the Anthropic API with a
personal key (ANTHROPIC_API_KEY, in the Keychain or .env), kept apart from any work or university
account; its base URL is pinned so a host app's ANTHROPIC_BASE_URL (the Claude desktop app sets
one) never reroutes the key. Everything goes through `ask`.

PROXENOS_VOICE_MODEL, off when empty, names a voice model for reply drafts (proxenos.voicemodel): "mlx"
for `proxenos voice serve` on this computer ("mlx:<port>" on another port), or "ollama:<name>"
or "local:<name>" for one served the ways above. It goes through `ask_voice`. `using` points the
calls made inside it at other models than these settings name, so proxenos.compare can draft one
reply with two.

PROXENOS_FAST_MODEL, off when empty or "off", names a model on this computer ("local:<name>" or
"ollama:<name>") for the light background jobs (FAST_STEPS: the task list, the network, the
notes on each month, the research picks, the rules read from changed drafts,
and the labels and moods), which a small fast one does well and a laptop's big one takes most of its
night on. Drafts, Ask, Think, errands and calls stay on PROXENOS_MODEL, and so does a question
someone is waiting on (`foreground`). A "local:" fast model is served at PROXENOS_FAST_URL
(`proxenos model serve-fast`, mlx-lm's server, by default), apart from PROXENOS_LOCAL_URL. A job
whose fast server isn't answering goes to the main model instead, rather than failing.

PROXENOS_SERVED_HERE lists the models the desktop app serves itself (`proxenos model get` sets it,
`proxenos model serve-app` serves them): Hugging Face repos from HERE_PORTS, each on a port of its
own on 127.0.0.1. A "local:<repo>" model named there is asked at that port, whichever of
PROXENOS_MODEL or PROXENOS_FAST_MODEL names it; PROXENOS_LOCAL_URL stays for another app's server.

What goes to Anthropic, OpenAI or Google has the numbers and secrets no draft needs blanked first: card and
Social Security numbers, one-time codes, passwords, keys and tokens, bank account numbers
(proxenos.redact).

Every call leaves one line in <vault>/state/model-calls.jsonl, for the privacy screen and for
seeing what a night costs: when, which step asked, the model, where it ran (this computer,
Anthropic, OpenAI or Google), how many characters went in and came back, the tokens where the model counts them,
how many numbers and secrets were blanked, how long it took and whether it worked. Never the
words, nor what was blanked. A project step leaves one line of the same shape for its run
(`log_run`): Claude Code takes one on the account it's signed in to, through no `ask`.
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
from functools import partial
from pathlib import Path

import anthropic

from proxenos import lock, redact
from proxenos.config import env, vault_path

# Claude, which the user chooses with a key (setup makes it what they wait on, PROXENOS_ASK_MODEL),
# and the model with nothing else to go to. PROXENOS_MODEL picks another; unset, a model on this
# computer goes first (`default`). Read on each call, so a value saved in Settings or .env counts.
DEFAULT_MODEL = "claude-opus-5-5"
_API = "https://api.anthropic.com"
# On a policy decline the API reruns the request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

OLLAMA = "ollama:"
SERVER = "local:"  # an OpenAI-compatible server on this computer: LM Studio, llama-server, ...
# Either runs on this computer. A tuple, so `model.startswith(LOCAL)` asks about both.
LOCAL = (OLLAMA, SERVER)
_OLLAMA = "http://127.0.0.1:11434"
OPENAI, GEMINI = "openai:", "gemini:"
# Hosted models spoken to in OpenAI's chat API, by their prefix: how the calls log names the
# provider, its base address (pinned here, never a setting) and the secret that holds the key.
CHAT_HOSTS = {
    OPENAI: ("OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    GEMINI: (
        "Google",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
    ),
}
HOSTED_ANSWER = 16000  # tokens a hosted answer may run to; some models stop short of the default
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
# A local model given two requests at once works on both, each the slower, so Proxenos's
# processes take turns: one local call at a time, holding _TURN while it's answered, and a
# question someone is waiting on (an Ask, a Think) marks itself, so other calls, a sync's drafts
# or the night's notes, let it go next and don't start until it's answered: for at most
# FOREGROUND_MAX seconds, past which a mark counts as left behind. A turn is waited for at most
# TURN_MAX seconds, past which a call goes ahead anyway, beside whatever holds it.
_FOREGROUND = "state/asking"
FOREGROUND_MAX = 900
_TURN = "state/model.lock"
TURN_MAX = 3900  # past _LOCAL_DEADLINE, the longest one call may take
_TURN_EVERY = 0.5  # seconds between looks for a turn
CALLS = "state/model-calls.jsonl"
CALLS_KEPT = 20000  # lines kept, newest last: months of nights and syncs
VOICE_PORT = 8899
# The jobs PROXENOS_FAST_MODEL takes, by the step that asks (the module's name, as _step gives
# it): light ones that read a lot and write to no one. Not the ones that write as the user.
FAST_STEPS = frozenset(
    {"tasks", "network", "observe", "tracker", "research", "voice", "mood", "rhythms"}
)
FAST_PORT = 8898  # where `proxenos model serve-fast` answers
DEFAULT_FAST_URL = f"http://127.0.0.1:{FAST_PORT}/v1"
# The models the desktop app can serve itself with mlx-lm (proxenos.localmodel), by Hugging Face
# repo, and the port each answers on: the small one at the fast model's port, the bigger one below.
HERE_PORTS = {
    "mlx-community/gemma-4-e4b-it-4bit": FAST_PORT,
    "mlx-community/gemma-4-26b-a4b-it-4bit": FAST_PORT - 1,
}
VOICE_TEMPERATURE = 0.7
VOICE_TOKENS = 600
_VOICE_TIMEOUT = 120

_client: anthropic.Anthropic | None = None
# Inside `foreground`: this process answers someone who is waiting, so PROXENOS_ASK_MODEL, when
# it's set and can answer, takes over from PROXENOS_MODEL (Claude for Ask and Think, say, with
# the night on the model on this computer).
_waited_on = False


class ModelError(RuntimeError):
    pass


class Unreachable(ModelError):
    """The model's server didn't answer at all, as when it isn't running."""


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
    try:
        return _logged(model, prompt, system, schema, effort, max_tokens, images, keep)
    except Unreachable:
        # The fast model's server isn't up (after a restart, say): the main model does the job.
        if (main := _chosen(light=False)) == model:
            raise
        return _logged(main, prompt, system, schema, effort, max_tokens, images, keep)


def _logged(
    model: str,
    prompt: str,
    system: str | None,
    schema: dict | None,
    effort: str,
    max_tokens: int,
    images: list[dict] | None,
    keep: Iterable[str],
) -> str | dict:
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
        return _ask_local(
            model, prompt, system, schema, effort, max_tokens, images, _url_for(model)
        )
    if chat_host(model):
        return _ask_hosted(model, prompt, system, schema, max_tokens, images, keep)
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
    """The model `ask` goes to: PROXENOS_MODEL, unless `using` names another, or someone is
    waiting on the answer and PROXENOS_ASK_MODEL can give it (`foreground`), or the step asking
    is a light job and PROXENOS_FAST_MODEL is set (`fast`). With none of those set, the
    `default`."""
    return _chosen(light=True)


def _chosen(light: bool) -> str:
    """`current`, with or without the fast model for a light job."""
    return (
        getattr(_using, "model", None)
        or (_waited_on and _ask_model())
        or (light and not _waited_on and fast())
        or env("MODEL")
        or default()
    )


def fast() -> str:
    """PROXENOS_FAST_MODEL when the step asking is one of FAST_STEPS, else "". Only a model on
    this computer counts: a light job reads other people's messages, and the main model setting
    alone says whether those may leave it."""
    model = env("FAST_MODEL").strip()
    return model if model.startswith(LOCAL) and _step() in FAST_STEPS else ""


def fast_url(url: str | None = None) -> str:
    """Where a "local:" fast model is served (`url`, else PROXENOS_FAST_URL, else mlx-lm's server
    at FAST_PORT), held to this computer's own address as `local_url` holds PROXENOS_LOCAL_URL."""
    return local_url((env("FAST_URL") if url is None else url).strip() or DEFAULT_FAST_URL)


def served_here() -> list[str]:
    """The repos the desktop app serves itself (PROXENOS_SERVED_HERE, comma-separated), those of
    HERE_PORTS only: nothing else is ever sent to a port this names."""
    return [r for r in (p.strip() for p in env("SERVED_HERE").split(",")) if r in HERE_PORTS]


def _url_for(model: str) -> str | None:
    """The address of the server that answers `model`, when it isn't the one at PROXENOS_LOCAL_URL
    (None then): the app's own server for a model it serves, else the fast model's. A model both
    settings name is the main one."""
    if model.startswith(SERVER) and bare(model) in served_here():
        return f"http://127.0.0.1:{HERE_PORTS[bare(model)]}/v1"
    fast_name = env("FAST_MODEL").strip()
    if model.startswith(SERVER) and model == fast_name and model != env("MODEL"):
        return fast_url()
    return None


def default() -> str:
    """The model when PROXENOS_MODEL names none: local first, so nothing leaves the computer
    unless the user chose it. The model Ollama has pulled that fits this computer's memory (the
    largest, as setup suggests it), kept in the vault as it's found. While Ollama isn't
    answering (after a reboot, or at night before the app is up), the one it last found, so the
    calls fail and are tried again later rather than going to Claude. Claude, which answers only
    with a key, only when no model on this computer was ever found. Asked once a process, since
    it takes a call to Ollama."""
    global _default
    if _default is None:
        from proxenos import machine  # only here: machine reads the computer, and llm needn't

        pulled = {n: s for n, s in (_pulled() or {}).items() if "embed" not in n}
        best = machine.best(pulled, machine.memory())
        if best:
            _remember(OLLAMA + best)
        _default = OLLAMA + best if best else _remembered() or DEFAULT_MODEL
    return _default


_default: str | None = None
_LAST_LOCAL = "state/local-model"  # the model on this computer `default` last found


def _remembered() -> str:
    """The local model `default` last found, or "" when none was, or there's no vault."""
    path = _last_local_path()
    try:
        name = path.read_text(encoding="utf-8").strip() if path else ""
    except OSError:
        return ""
    return name if name.startswith(OLLAMA) and len(name) <= 200 else ""


def _remember(model: str) -> None:
    """Keep `model` as the local one last found, private to the user. A vault that can't take
    it costs only the memory, never the call."""
    path = _last_local_path()
    if path is None or _remembered() == model:
        return
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(model + "\n")
        os.replace(tmp, path)
    except OSError:
        pass


def _last_local_path() -> Path | None:
    try:
        vault = vault_path()
    except ValueError:
        return None
    return vault / _LAST_LOCAL if vault.is_dir() else None


def _pulled() -> dict[str, int | None] | None:
    """The models Ollama has pulled, with each one's size in bytes, or None when it isn't
    running."""
    try:
        with _direct(f"{_OLLAMA}/api/tags", timeout=2) as response:
            listed = json.load(response).get("models", [])
        return {
            str(m["name"]): m.get("size") if isinstance(m.get("size"), int) else None
            for m in listed
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _ask_model() -> str:
    """PROXENOS_ASK_MODEL, when it's set and can answer: a local one, or Claude with a key.
    Unset, with a key and no PROXENOS_MODEL chosen, it's Claude: a key is saved for Claude to
    take what the user waits on, as setup now says by setting it, and a key saved before that
    meant all of it."""
    model = env("ASK_MODEL") or ("" if env("MODEL") else DEFAULT_MODEL)
    if model and (model.startswith(LOCAL) or has_key(model)):
        return model
    return ""


@contextmanager
def foreground(vault: Path) -> Iterator[None]:
    """While this runs, someone is waiting on its answer: it goes to PROXENOS_ASK_MODEL when that
    can answer, and while its model is the local one, other processes' local calls let it go
    first and hold off (see `waiting` and `_turn`)."""
    global _waited_on
    saved, _waited_on = _waited_on, True
    mark = vault / _FOREGROUND if current().startswith(LOCAL) else None
    if mark:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(str(os.getpid()))
    try:
        yield
    finally:
        _waited_on = saved
        if mark:
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


def _mine() -> bool:
    """Whether this process is answering a question someone is waiting on."""
    try:
        return int((vault_path() / _FOREGROUND).read_text()) == os.getpid()
    except (OSError, ValueError):
        return False


@contextmanager
def _turn() -> Iterator[None]:
    """This process's turn at the local model (see _TURN): taken once no other call holds it,
    and for a call no one is waiting on, once no question someone is waiting on wants it."""
    held = lock.Lock(vault_path() / _TURN)
    mine = _mine()
    deadline = time.monotonic() + TURN_MAX
    took = False
    while time.monotonic() < deadline:
        if (mine or not waiting()) and held.acquire():
            took = True
            break
        time.sleep(_TURN_EVERY)
    try:
        yield
    finally:
        if took:
            held.release()


def configured() -> bool:
    """Whether a model is set up (a local one, or a key), so steps that are optional can skip
    the model rather than fail."""
    model = current()
    return model.startswith(LOCAL) or has_key(model)


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


def chat_host(model: str) -> tuple[str, str, str] | None:
    """(provider, base address, key's name) when `model` is a hosted one in OpenAI's chat API
    ("openai:" or "gemini:"), else None."""
    return next((host for prefix, host in CHAT_HOSTS.items() if model.startswith(prefix)), None)


def has_key(model: str) -> bool:
    """Whether the key a hosted `model` needs is set: its provider's, and Anthropic's for any
    name that isn't OpenAI's or Google's."""
    host = chat_host(model)
    return bool(os.environ.get(host[2] if host else "ANTHROPIC_API_KEY"))


def where(model: str) -> str:
    """Where a model runs, as the calls log says it: "this computer", "OpenAI", "Google" or
    "Anthropic". A voice model on this computer counts as on it."""
    if model.startswith((*LOCAL, *(f"voice:{p}" for p in (*LOCAL, "mlx")))):
        return "this computer"
    host = chat_host(model)
    return host[0] if host else "Anthropic"


def bare(model: str) -> str:
    """A model's name without what says where it runs: "gemma4:26b" for "ollama:gemma4:26b"."""
    for prefix in (*LOCAL, *CHAT_HOSTS):
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
# A hosted provider is reached over the ordinary network (and a proxy the environment names), but
# follows no redirect, so the key goes to the address pinned here and nowhere else.
_remote = urllib.request.build_opener(_Stay()).open


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
    url: str | None = None,
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
        chat = _complete if url is None else partial(_complete, url=url)
        held, cant = "response_format", _NO_SCHEMA.search
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
    with _turn():
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


def _ask_hosted(
    model: str,
    prompt: str,
    system: str | None,
    schema: dict | None,
    max_tokens: int,
    images: list[dict] | None,
    keep: Iterable[str] = (),
) -> str | dict:
    """`ask`, answered by OpenAI or Gemini through the chat API the "local:" path speaks, at the
    provider's own address with the key as a bearer token. What leaves is blanked first, as for
    Anthropic. A schema goes in the system prompt and as `response_format`, as for a local
    server, and a provider that refuses it is asked again without, once, and not asked with one
    again in this process; the answer is held to the schema here either way."""
    host = chat_host(model)
    assert host is not None
    label, base, key_name = host
    key = os.environ.get(key_name)
    if not key:
        raise ModelError(
            f"{key_name} is not set. Add a key from "
            f"{'platform.openai.com' if label == 'OpenAI' else 'aistudio.google.com'} in Settings."
        )
    prefix = OPENAI if label == "OpenAI" else GEMINI
    name = model.removeprefix(prefix)
    prompt, blanked = redact.redact(prompt, keep)
    system, also = redact.redact(system, keep) if system else (system, {})
    _usage.redacted = sum(blanked.values()) + sum(also.values())
    answer_room = min(max_tokens, HOSTED_ANSWER)
    if schema is not None:
        system = f"{system or ''}\n\n{_JSON_ONLY}\n{json.dumps(schema)}".strip()
    messages = [{"role": "system", "content": system}] if system else []
    body = _served_body(name, messages, prompt, images, answer_room)
    if prefix == OPENAI:  # newer OpenAI models take only this name for the limit
        body["max_completion_tokens"] = body.pop("max_tokens")
    if schema is not None and model not in _NO_GRAMMAR:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema},
        }
    chat = partial(_complete, url=base, host=(label, key))
    for _ in range(2):
        try:
            text = chat(name, body, answer_room)
        except ModelError as e:
            if "response_format" not in body or not _NO_SCHEMA.search(str(e)):
                raise
            _NO_GRAMMAR.add(model)
            body.pop("response_format")
            text = chat(name, body, answer_room)
        if schema is None:
            return text
        if (answer := _object(text, schema)) is not None:
            return answer
    raise ModelError(f"{label} model {name} didn't answer with the JSON asked for")


# A backslash that starts one of JSON's escapes, or one on its own, as LaTeX's \section is.
_ESCAPE = re.compile(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _object(text: str, schema: dict) -> dict | None:
    """The first JSON object in a local model's answer that fits the schema, held to it the way
    a hosted model's answer is (`_conform`). A model may echo the schema before its answer,
    whose own parts can have the same keys, or wrap the answer in a code fence. One held to no
    grammar can also slip as it writes: a line break left raw in a string, or a backslash left
    single, as LaTeX's \\section easily is. When nothing fits, the answer is read again forgiving
    both, a single backslash standing for itself."""
    forgiven = _ESCAPE.sub(lambda m: m[0] if len(m[0]) > 1 else "\\\\", text)
    for decoder, said in ((json.JSONDecoder(), text), (json.JSONDecoder(strict=False), forgiven)):
        start = said.find("{")
        while start != -1:
            try:
                found, _ = decoder.raw_decode(said, start)
            except ValueError:
                start = said.find("{", start + 1)
                continue
            if isinstance(found, dict) and (held := _conform(found, schema)) is not _UNFIT:
                return held
            start = said.find("{", start + 1)  # inside it: the answer may be nested in the echo
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


def _down(error: Exception, said: str) -> ModelError:
    """The error for a server that didn't answer: Unreachable when the connection itself failed,
    as it does while the server isn't running, not when a model went quiet mid-answer."""
    return (Unreachable if isinstance(error, urllib.error.URLError) else ModelError)(said)


def _chat(model: str, body: dict, answer_room: int) -> str:
    """The answer to one Ollama chat request, read as it streams in, one JSON line at a time:
    its thinking, then its words, then a last line that says why it stopped."""
    request = urllib.request.Request(
        f"{_OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    began = deadline = time.monotonic()
    deadline += _LOCAL_DEADLINE
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
                if words[-1] and getattr(_usage, "first", None) is None:
                    _usage.first = time.monotonic() - began
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
        raise _down(e, f"the local model isn't answering ({e}); is Ollama running?") from e
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise ModelError(f"local model {model} stopped mid-answer ({e})") from e
    if not last:
        raise ModelError(f"local model {model} stopped mid-answer")
    _usage.tokens = (last.get("prompt_eval_count"), last.get("eval_count"))
    if last.get("done_reason") == "length":
        raise ModelError(f"answer cut off at {answer_room} tokens")
    return "".join(words)


def _complete(
    model: str,
    body: dict,
    answer_room: int,
    url: str | None = None,
    host: tuple[str, str] | None = None,
) -> str:
    """The answer to one chat request to the OpenAI-compatible server, read as it streams in:
    server-sent events, each a `data:` line with a piece of the words, until one says why it
    stopped and `data: [DONE]` ends them. Thinking the server parts out (`reasoning_content`) is
    left out, and so is a <think> block a model leaves at the start of its words. With `host`
    (provider, key), `url` is a hosted provider's own address, and the key goes as a bearer token,
    through the ordinary network, following no redirect, and is blanked from anything said back."""
    headers = {"Content-Type": "application/json"}
    if host:
        who, key = f"{host[0]} model {model}", host[1]
        url, opener = f"{url}/chat/completions", _remote
        headers["Authorization"] = f"Bearer {key}"
    else:
        who, key = f"local model {model}", ""
        url, opener = f"{local_url(url)}/chat/completions", _direct
    request = urllib.request.Request(url, json.dumps(body).encode(), headers)
    began = deadline = time.monotonic()
    deadline += _LOCAL_DEADLINE
    words: list[str] = []
    stopped, usage = None, {}
    try:
        with opener(request, timeout=_LOCAL_TIMEOUT) as response:
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
                    said = str(chunk["error"])[:300]
                    raise ModelError(f"{who}: {said.replace(key, '[hidden]') if key else said}")
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    words.append((choice.get("delta") or {}).get("content") or "")
                    if words[-1] and getattr(_usage, "first", None) is None:
                        _usage.first = time.monotonic() - began
                    stopped = choice.get("finish_reason") or stopped
                if time.monotonic() > deadline:
                    raise ModelError(
                        f"{who} was still answering after {_LOCAL_DEADLINE // 60} minutes"
                    )
    except urllib.error.HTTPError as e:  # a redirect, too, which is followed no further
        said = e.read().decode(errors="replace")[:300] or f"HTTP {e.code} {e.reason}"
        raise ModelError(f"{who}: {said.replace(key, '[hidden]') if key else said}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise _down(
            e,
            f"{host[0]} isn't answering ({e}); check the internet connection."
            if host
            else f"the local model isn't answering ({e}); is its server running at {url}?",
        ) from e
    except (OSError, ValueError, AttributeError, http.client.HTTPException) as e:
        raise ModelError(f"{who} stopped mid-answer ({e})") from e
    if stopped is None:
        raise ModelError(f"{who} stopped mid-answer")
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


def last_call() -> dict:
    """The last call this thread made: the tokens it read and wrote where the model counts them,
    and the seconds to its first word, which is the time spent reading the prompt (proxenos.
    fastmodel's bench sets reading and writing speed by them)."""
    tokens_in, tokens_out = getattr(_usage, "tokens", (None, None))
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "first": getattr(_usage, "first", None),
    }


@contextmanager
def _recorded(model: str, sent: int, images: int) -> Iterator[Callable[[object], None]]:
    """Time the call inside it and leave its line in the calls log, whether it worked or not.
    The call hands its answer to the function this yields, for the answer's size."""
    began, got = time.monotonic(), {}
    _usage.tokens, _usage.redacted, _usage.first = (None, None), None, None
    try:
        yield lambda answer: got.setdefault("answer", answer)
    finally:
        answer = got.get("answer")
        size = len(answer if isinstance(answer, str) else json.dumps(answer)) if got else 0
        tokens_in, tokens_out = getattr(_usage, "tokens", (None, None))
        record = {
            "at": _now(),
            "step": _step(),
            "model": model,
            "where": _where(model),
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


def log_run(step: str, model: str, seconds: float, ok: bool, **about: str) -> None:
    """One line in the calls log for model work that doesn't go through `ask`, such as a project
    step Claude Code takes (proxenos.clones.steps): a call's line, where it ran by its model,
    the sizes and tokens nothing here counted left None, and `about` beside them (the runner,
    the project). Never any words."""
    _log(
        {
            "at": _now(),
            "step": step,
            "model": model,
            "where": _where(model),
            "sent_chars": None,
            "images": None,
            "redacted": None,
            "answer_chars": None,
            "tokens_in": None,
            "tokens_out": None,
            "seconds": round(seconds, 1),
            "ok": ok,
            **about,
        }
    )


def _where(model: str) -> str:
    """Where a model runs, as the calls log says it."""
    return where(model)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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
