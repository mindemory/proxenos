"""A fast model for the light jobs, and a way to measure it: `proxenos model serve-fast` and
`proxenos model bench`; `proxenos model pull` (proxenos.pull) downloads one through Ollama.

A laptop's big model reads about 50 to 250 tokens a second and writes 15 to 30, and the task list,
the network, the notes on each month and the like read tens of thousands of tokens a run. A small
model such as Gemma 4 E4B at 4 bits, served by mlx-lm on Apple silicon, reads about twice as fast
and writes about as fast again, and does these jobs well. PROXENOS_FAST_MODEL names it (see
proxenos.llm: which jobs it takes, and that drafts, Ask, Think, errands and calls never go to it).

`serve-fast` runs mlx-lm's server with it on 127.0.0.1:FAST_PORT until stopped, as `proxenos voice
serve` does the voice model; scripts/install-fast-model.sh keeps it running from login on, as a
launchd job. Setup sets PROXENOS_FAST_MODEL to it (`NAME`) when this is an Apple-silicon Mac with
mlx-lm and the model's weights already in the Hugging Face cache (`found`); "off" there keeps it
unset. The weights are the same ones the voice model trains from, so they come from Hugging Face
once and nothing else leaves the computer.

`bench` times one short prompt (what it writes) and one long one (what it reads) on the main model
and the fast one, built from made-up words, never from the vault, and prints how many tokens a
second each reads and writes. The reading rate is the prompt's tokens over the time to the first
word; the writing rate is the answer's tokens over the time after. The first call to each model
isn't timed, as it only loads the model.
"""

import argparse
import importlib.util
import json
import os
import platform
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path

from proxenos import llm, pull, voicemodel
from proxenos.config import env

# The weights the voice model trains from too: 5 GB at 4 bits; with 16 GB, gemma-4-e2b-it-4bit.
BASE = voicemodel.BASE
NAME = llm.SERVER + BASE
SHORT = "Write about 150 words on why a neighbourhood library is worth keeping open. Plain prose."
LONG_CHARS = 24_000  # about 6,000 tokens, what a run of the light jobs reads
LONG_ASK = "\n\nIn one short sentence, which items above mention the harbour?"
SHORT_TOKENS, LONG_TOKENS = 300, 100
_WORDS = [
    *("harbour", "orchard", "survey", "ledger", "ferry", "meadow", "archive", "lantern", "quarry"),
    *("kiln", "signal", "bridge", "granary", "weaver", "pasture", "station", "canal", "market"),
    *("mill", "tunnel", "garden", "reservoir", "beacon", "depot", "terrace", "vineyard"),
    *("foundry", "lighthouse"),
]


def capable(
    system: Callable[[], str] = platform.system,
    machine: Callable[[], str] = platform.machine,
    spec: Callable[[str], object] = importlib.util.find_spec,
) -> bool:
    """Whether this is an Apple-silicon Mac with mlx-lm, which can serve BASE (downloading it
    the first time). The arguments stand in for the computer in tests."""
    return system() == "Darwin" and machine() == "arm64" and spec("mlx_lm") is not None


def found(cached: Callable[[str], bool] | None = None, **computer: Callable) -> bool:
    """Whether it's capable and BASE's weights are already downloaded, which is when setup takes
    it for the fast model without being asked."""
    return capable(**computer) and (cached or _cached)(BASE)


def _cached(base: str) -> bool:
    """Whether Hugging Face's cache has a download of `base`: where huggingface_hub keeps them,
    HF_HUB_CACHE, else HF_HOME/hub, else ~/.cache/huggingface/hub."""
    hub = os.environ.get("HF_HUB_CACHE") or (
        Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
    )
    snapshots = Path(hub) / f"models--{base.replace('/', '--')}" / "snapshots"
    try:
        return any((snapshot / "config.json").is_file() for snapshot in snapshots.iterdir())
    except OSError:
        return False


def running(url: str | None = None) -> bool:
    """Whether the fast model's server answers, by asking it which models it has."""
    try:
        with llm._direct(f"{llm.fast_url(url)}/models", timeout=2) as response:
            return json.load(response).get("data") is not None
    except (OSError, ValueError, AttributeError, llm.ModelError):
        return False


def serve(port: int = llm.FAST_PORT) -> None:
    """Run mlx-lm's server with BASE on 127.0.0.1:`port`, until stopped. Thinking is off, as for
    the voice model: these jobs don't need it, and it makes each answer several times longer."""
    if importlib.util.find_spec("mlx_lm") is None:
        raise SystemExit("mlx-lm isn't installed here: pip install mlx-lm (Apple silicon only).")
    command = [
        sys.executable,
        "-m",
        "mlx_lm",
        "server",
        "--model",
        BASE,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--chat-template-args",
        json.dumps(voicemodel.NO_THINKING),
    ]
    os.execv(sys.executable, command)


# ── Measuring ────────────────────────────────────────────────────────────────


def synthetic(chars: int = LONG_CHARS, salt: str = "") -> str:
    """About `chars` characters of numbered made-up items, the same for the same `salt`: a long
    prompt to read, with nothing of anyone's in it. A server that keeps the start of the last
    prompt (mlx-lm's does) reads a repeat of it for nothing, so each run starts with a line of
    its own."""
    rng = random.Random(7)
    lines, size = ([f"Run {salt}."] if salt else []), 0
    while size < chars:
        words = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(14, 26)))
        lines.append(f"Item {len(lines) + 1}: {words}.")
        size += len(lines[-1]) + 1
    return "\n".join(lines) + LONG_ASK


def timed(model: str, prompt: str, max_tokens: int, ask: Callable[..., object] = llm.ask) -> dict:
    """One call to `model`: {tokens_in, tokens_out, seconds, read, write} where the model counts
    tokens, with read and write in tokens a second; or {error}."""
    began = time.monotonic()
    try:
        with llm.using(model=model, step="bench"):
            ask(prompt, effort="low", max_tokens=max_tokens)
    except llm.ModelError as e:
        if "cut off" not in str(e):  # an answer that ran to the limit was still timed
            return {"error": " ".join(str(e).split())[:160]}
    seconds = time.monotonic() - began
    call = llm.last_call()
    first, tokens_in, tokens_out = call["first"], call["tokens_in"], call["tokens_out"]
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "seconds": seconds,
        "read": tokens_in / first if tokens_in and first else None,
        "write": tokens_out / (seconds - first)
        if tokens_out and first and seconds > first
        else None,
    }


def bench(
    models: list[str],
    chars: int = LONG_CHARS,
    ask: Callable[..., object] = llm.ask,
    run: Callable[..., dict] = timed,
) -> list[dict]:
    """The short and the long prompt on each model of `models`, in order: a row each, {model,
    prompt, ...timed's}. A model that fails the warm-up fails both rows."""
    long = synthetic(chars, os.urandom(4).hex())  # one for every model, new every run
    prompts = (("short", SHORT, SHORT_TOKENS), ("long", long, LONG_TOKENS))
    rows = []
    for model in models:
        warm = run(model, "Say ok.", 8, ask)  # loads the model; not counted
        for kind, prompt, limit in prompts:
            result = warm if "error" in warm else run(model, prompt, limit, ask)
            rows.append({"model": model, "prompt": kind} | result)
    return rows


def table(rows: list[dict]) -> str:
    """The rows as text: a line each, the rates in tokens a second."""

    def num(value: float | None, fmt: str = "{:.0f}") -> str:
        return "?" if value is None else fmt.format(value)

    head = f"{'model':<44} {'prompt':<6} {'read':>6} {'wrote':>6} {'secs':>6} {'read/s':>7} {'write/s':>8}"
    lines = [head]
    for r in rows:
        name = llm.bare(r["model"])[-44:]
        if "error" in r:
            lines.append(f"{name:<44} {r['prompt']:<6} {r['error']}")
            continue
        lines.append(
            f"{name:<44} {r['prompt']:<6} {num(r['tokens_in']):>6} {num(r['tokens_out']):>6} "
            f"{num(r['seconds'], '{:.1f}'):>6} {num(r['read']):>7} {num(r['write']):>8}"
        )
    return "\n".join(lines)


def models_to_time() -> tuple[list[str], list[str]]:
    """The main model and the fast one, when each is on this computer, and a note for each that
    isn't, with why: a hosted model isn't timed with prompts that cost money for nothing."""
    main = llm._chosen(light=False)
    chosen, notes = [], []
    if main.startswith(llm.LOCAL):
        chosen.append(main)
    else:
        notes.append(f"{main}: not timed; it isn't on this computer.")
    fast = env("FAST_MODEL").strip()
    if fast.startswith(llm.LOCAL):
        chosen.append(fast)
    else:
        notes.append("No fast model set (PROXENOS_FAST_MODEL), so only the main one is timed.")
    return chosen, notes


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["serve-fast", "bench", "pull"])
    parser.add_argument("name", nargs="?", help="pull: the model to download, e.g. gemma4:e4b")
    parser.add_argument(
        "--as",
        dest="use",
        choices=pull.AS,
        help="pull: use it as the main model (the one it replaces keeps the light jobs), or as "
        "the starter; the default is the starter while no model is set",
    )
    parser.add_argument("--port", type=int, default=llm.FAST_PORT, help="where serve-fast answers")
    parser.add_argument(
        "--chars", type=int, default=LONG_CHARS, help="bench: the long prompt's length"
    )


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.action == "serve-fast":
        serve(args.port)
        return
    if args.action == "pull":
        pull.run(args)
        return
    chosen, notes = models_to_time()
    if notes:
        print("\n".join(notes))
    if chosen:
        print(table(bench(chosen, args.chars)))
