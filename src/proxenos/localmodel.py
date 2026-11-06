"""A model that runs inside the app, with no Ollama: `proxenos model get` and `serve-app`.

Someone who got the desktop app and never opens a terminal needs a model without installing
anything. mlx-lm comes with the app (the `local` extra) on a Mac with Apple silicon, so the app can
download the weights from Hugging Face and serve them itself:

- `proxenos model get REPO [--as starter|main]` downloads REPO's weights into Hugging Face's cache
  and prints one line about once a second, flushed so the page sees it as it comes:
  `Downloading Gemma 4 E4B: 2.1 of 5.2 GB (40%)`. A download stopped partway carries on from where
  it was when run again. When it's done it sets the settings, as `proxenos model pull` does for
  Ollama's: `starter` (the default while no model is set) makes the small model, `CATALOG`'s first,
  both the main model and the fast one; `main` makes REPO the main model and leaves the small one,
  when it's downloaded, the fast model, so it goes on doing the light background jobs while the
  big one writes. Either way PROXENOS_SERVED_HERE names the repos the app serves, which is how
  llm.py knows where to ask them (llm.HERE_PORTS) and apart from PROXENOS_LOCAL_URL, which stays
  for another app's server, LM Studio's say.
- `proxenos model serve-app` keeps an mlx-lm server running for each repo PROXENOS_SERVED_HERE names
  whose weights are all downloaded, each on its port on 127.0.0.1, until stopped (SIGTERM stops its
  servers first). It reads the settings again every few seconds, so a model picked on the page
  starts without restarting the app, and one that stops is started again. The servers run with
  Hugging Face's cache offline: only `get` ever reaches Hugging Face, and only for the weights.

The desktop app (desktop/main.js) runs serve-app while it's open; from source, `proxenos model
serve-fast` and scripts/install-fast-model.sh serve the small model as before.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from proxenos import config, fastmodel, llm, machine, speech, voicemodel

_EVERY = 1.0  # seconds between progress lines
_POLL = 3.0  # seconds between looks at the settings and the servers
_RESTART = 30.0  # seconds before a server that stopped is started again
_STOP_GRACE = 10.0  # seconds a server gets to stop before it's killed
HOST = "127.0.0.1"
SERVED = "SERVED_HERE"
_STOPPED = "The download of {} stopped before it finished. Try again and it carries on."


@dataclass(frozen=True)
class Here:
    """A model the app can serve: its name for people, and its size on Hugging Face in bytes."""

    name: str
    bytes: int


# Sizes as Hugging Face lists them; the small one first. Both repos are llm.HERE_PORTS' too.
SMALL = fastmodel.BASE
BIG = "mlx-community/gemma-4-26b-a4b-it-4bit"
CATALOG = {
    SMALL: Here("Gemma 4 E4B", 5_200_000_000),
    BIG: Here("Gemma 4 26B", 15_400_000_000),
}


def big_fits(memory: int | None) -> bool:
    """Whether the bigger model fits in `memory`, by machine's rule. The small one stays loaded
    beside it, for the light jobs: about 5 GB the rule's share of memory leaves room for."""
    return machine.fits(CATALOG[BIG].bytes, memory) is True


def complete(repo: str) -> bool:
    """Whether all of `repo`'s weights are downloaded: a snapshot with a config, and nothing in
    the cache still being written (huggingface_hub names a part-downloaded file .incomplete)."""
    return fastmodel._cached(repo) and not any(_blobs(repo, ".incomplete"))


def _blobs(repo: str, suffix: str = "") -> list[Path]:
    try:
        return [
            p for p in (fastmodel.cache_folder(repo) / "blobs").iterdir() if p.name.endswith(suffix)
        ]
    except OSError:
        return []


def _downloaded(repo: str) -> int:
    """Bytes of `repo` in the cache, finished and part-way: how far a download is, wherever
    huggingface_hub counts it from."""
    total = 0
    for blob in _blobs(repo):
        try:
            total += blob.stat().st_size
        except OSError:
            pass
    return total


class _Counted(speech._Progress):
    """speech's progress, with the cache folder as the count: its progress bars say how far each
    file is, but not every huggingface_hub version makes them, and a download that carries on
    starts with some bytes already there. The size is the catalog's until a download passes it."""

    def __init__(self, repo: str, report: Callable[[int, int | None], None], every: float):
        super().__init__(report, every)
        self.repo = repo

    def counts(self) -> dict:
        bars = super().counts()
        done = max(bars["done"], _downloaded(self.repo))
        return {"done": done, "total": max(CATALOG[self.repo].bytes, bars["total"] or 0, done)}


def _gb(size: float) -> str:
    return f"{size / 10**9:.1f}"


def _fetch(repo: str, progress: speech._Progress) -> None:
    from huggingface_hub import snapshot_download  # slow to import, so only here

    snapshot_download(repo, tqdm_class=progress.bar())


def get(
    repo: str,
    say: Callable[[str], None] | None = None,
    fetch: Callable[[str, speech._Progress], None] | None = None,
    every: float = _EVERY,
) -> None:
    """Download `repo`'s weights, saying how far along it is about once a second. SystemExit, with
    a sentence, when this can't run it, it isn't one of the models Proxenos serves, or the
    download stops."""
    say = say or _print
    if repo not in CATALOG:
        raise SystemExit(
            "Proxenos serves " + " and ".join(f"{r} ({m.name})" for r, m in CATALOG.items()) + "."
        )
    if not fastmodel.capable():
        raise SystemExit(
            "Running a model inside Proxenos needs a Mac with Apple silicon and mlx-lm, which "
            "this copy doesn't have. Use Ollama, LM Studio or an API key instead."
        )
    name = CATALOG[repo].name
    progress = _Counted(
        repo,
        lambda done, total: say(
            f"Downloading {name}: {_gb(done)} of {_gb(total or 0)} GB ({100 * done // (total or 1)}%)"
        ),
        every,
    )
    failure: list[BaseException] = []

    def work() -> None:
        try:
            (fetch or _fetch)(repo, progress)
        except BaseException as e:  # noqa: BLE001 - said below, in a sentence, from the main thread
            failure.append(e)

    # The cache folder is looked at from here, once a second, as bars may not report at all.
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(every)
        progress.tick(force=True)
    if failure:
        raise SystemExit(_why(failure[0], name))
    if not complete(repo):
        raise SystemExit(_STOPPED.format(name))
    say(f"Downloaded {name}.")


def _why(error: BaseException, name: str) -> str:
    said = " ".join(str(error).split())[:200]
    return f"Couldn't download {name}: {said or type(error).__name__}. Try again and it carries on."


def use(repo: str, how: str | None, say: Callable[[str], None] | None = None) -> None:
    """Use the downloaded model as `how` says (see the module's notes); `how` None is "starter"
    while no model is set, else nothing."""
    say = say or _print
    how = how or ("" if config.env("MODEL") else "starter")
    if not how:
        return
    name = CATALOG[repo].name
    if how == "starter" and repo != SMALL:
        raise SystemExit(f"The starter is the small model, {CATALOG[SMALL].name}.")
    served = [repo]
    fast = llm.SERVER + repo
    if how == "main" and repo != SMALL and complete(SMALL):
        served.append(SMALL)
        fast = llm.SERVER + SMALL
    elif how == "main" and repo != SMALL and config.env("FAST_MODEL").strip():
        fast = config.env(
            "FAST_MODEL"
        ).strip()  # no small one here: the light jobs stay as they were
    config.save_setting("MODEL", llm.SERVER + repo)
    config.save_setting("FAST_MODEL", fast)
    config.save_setting(SERVED, ",".join(served))
    say(f"Using {name} as the main model.")
    if fast != llm.SERVER + repo:
        say(f"{CATALOG[SMALL].name} keeps doing the light jobs.")


def wanted() -> list[str]:
    """The repos to serve now: those PROXENOS_SERVED_HERE names, read afresh (the environment
    this process started with, else .env or the settings file as they are now) whose weights are
    all downloaded. A repo that isn't one of the catalog's is never served."""
    if config.origin(config.PREFIX + SERVED) == "environment":
        raw = os.environ.get(config.PREFIX + SERVED, "")
    elif config.saves_to() == ".env":
        from dotenv import dotenv_values

        assert config.ENV_FILE is not None
        raw = dotenv_values(config.ENV_FILE).get(config.PREFIX + SERVED) or ""
    else:
        raw = config.read_settings().get(SERVED.lower())
        raw = raw if isinstance(raw, str) else ""
    names = [r.strip() for r in raw.split(",")]
    return [r for r in dict.fromkeys(names) if r in CATALOG and complete(r)]


def command(repo: str) -> list[str]:
    """mlx-lm's server for `repo` on its port, with thinking off as for the fast model."""
    return [
        sys.executable,
        "-m",
        "mlx_lm",
        "server",
        "--model",
        repo,
        "--host",
        HOST,
        "--port",
        str(llm.HERE_PORTS[repo]),
        "--chat-template-args",
        json.dumps(voicemodel.NO_THINKING),
    ]


def serve_app(
    stop: threading.Event | None = None,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    poll: float = _POLL,
    restart: float = _RESTART,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Keep a server running for each model `wanted` names, until `stop` is set (SIGTERM and
    SIGINT set it), then stop them. Their output goes to this process's, which the app logs."""
    if not fastmodel.capable():
        print("serve-app: this needs a Mac with Apple silicon and mlx-lm; nothing to serve here.")
        return
    if stop is None:  # the command itself, not a test or a caller with an event of its own
        stop = threading.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
    # Offline: loading a model reads the cache and never goes to Hugging Face.
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}
    running: dict[str, subprocess.Popen] = {}
    began: dict[str, float] = {}
    try:
        while not stop.is_set():
            want = wanted()
            for repo, child in list(running.items()):
                if repo not in want:
                    _stop(running.pop(repo))
                elif child.poll() is not None:
                    print(f"serve-app: {CATALOG[repo].name}'s server stopped ({child.returncode})")
                    del running[repo]
            for repo in want:
                if repo not in running and clock() - began.get(repo, -restart) >= restart:
                    began[repo] = clock()
                    print(
                        f"serve-app: starting {CATALOG[repo].name} on port {llm.HERE_PORTS[repo]}"
                    )
                    running[repo] = popen(command(repo), env=env)
            stop.wait(poll)
    finally:
        for child in running.values():
            _stop(child)


def _stop(child: subprocess.Popen) -> None:
    """Ask a server to stop, and end it if it hasn't after a few seconds."""
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(_STOP_GRACE)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def run(args) -> None:
    if args.action == "serve-app":
        serve_app()
        return
    repo = (args.name or "").strip().removeprefix(llm.SERVER)
    get(repo)
    use(repo, args.use)


def _print(text: str) -> None:
    print(text, file=sys.stdout, flush=True)
