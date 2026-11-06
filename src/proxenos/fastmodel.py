"""A fast model for the light jobs: `proxenos model serve-fast`.

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
"""

import argparse
import importlib.util
import json
import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path

from proxenos import llm, voicemodel

# The weights the voice model trains from too: 5 GB at 4 bits; with 16 GB, gemma-4-e2b-it-4bit.
BASE = voicemodel.BASE
NAME = llm.SERVER + BASE


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


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["serve-fast"])
    parser.add_argument("--port", type=int, default=llm.FAST_PORT, help="where serve-fast answers")


def run(vault: Path, args: argparse.Namespace) -> None:
    serve(args.port)
