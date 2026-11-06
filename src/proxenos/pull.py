"""`proxenos model pull NAME`: download a model through Ollama, for the page's Download button.

Someone who never opens a terminal gets their model here: the page runs this in the background and
shows its last line. It streams Ollama's POST /api/pull (JSON lines with a status, and for each
layer its digest, total and completed bytes) and prints one line about once a second, flushed so
the page sees it as it comes: `Downloading gemma4:e4b: 2.1 of 6.6 GB (32%)`. The model comes from
Ollama's registry, through Ollama; Proxenos sends it nothing but the name. A download stopped
partway carries on from where it was when run again.

When it's done it uses the model, as setup's `_use_ollama` does:
- `--as starter` (the default while no model is set; with one set and no `--as`, it only
  downloads) makes it the main model: the small one to get going with.
- `--as main` makes it the main model too, and when no fast model is set, makes the one that was
  the main model the fast one if it was one of Ollama's, so the small model goes on doing the
  light background jobs (llm.FAST_STEPS) while the big one writes.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from proxenos import config, llm

_NAME = re.compile(r"[\w.:/@+-]{1,200}")
_EVERY = 1.0  # seconds between progress lines
_TIMEOUT = 120  # seconds without a word from Ollama (a stalled download, not a slow one)
AS = ("main", "starter")
_STOPPED = "The download of {} stopped before it finished. Try again and it carries on."


def _gb(size: float) -> str:
    return f"{size / 10**9:.1f}"


def _line(name: str, layers: dict[str, tuple[int, int]], status: str) -> str:
    """One progress line: bytes done of all the layers seen so far, else Ollama's own status."""
    total = sum(t for t, _ in layers.values())
    if not total:
        return f"Downloading {name}: {status}"
    done = sum(min(c, t) for t, c in layers.values())
    return f"Downloading {name}: {_gb(done)} of {_gb(total)} GB ({100 * done // total}%)"


def pull(
    name: str,
    opener: Callable | None = None,
    say: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Download `name` through Ollama, saying how far along it is about once a second. SystemExit,
    with a sentence, when Ollama isn't running, doesn't have it, or stops."""
    say = say or _print
    request = urllib.request.Request(
        f"{llm._OLLAMA}/api/pull",
        json.dumps({"model": name, "stream": True}).encode(),
        {"Content-Type": "application/json"},
    )
    layers: dict[str, tuple[int, int]] = {}
    last, finished = None, False
    try:
        with (opener or urllib.request.urlopen)(request, timeout=_TIMEOUT) as response:
            for raw in response:
                if not raw.strip():
                    continue
                event = json.loads(raw)
                if event.get("error"):
                    raise SystemExit(f"Ollama couldn't download {name}: {event['error']}")
                status = str(event.get("status") or "")
                if status == "success":
                    finished = True
                    break
                if event.get("digest") and isinstance(event.get("total"), int):
                    done = event["completed"] if isinstance(event.get("completed"), int) else 0
                    layers[event["digest"]] = (event["total"], done)
                now = clock()
                if last is None or now - last >= _EVERY:
                    last = now
                    say(_line(name, layers, status or "starting"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Ollama couldn't download {name}: {_why(e)}") from None
    except urllib.error.URLError:
        raise SystemExit(
            "Ollama isn't running. Open the Ollama app (ollama.com), then try again."
        ) from None
    except (OSError, ValueError):
        raise SystemExit(_STOPPED.format(name)) from None
    if not finished:
        raise SystemExit(_STOPPED.format(name))
    say(f"Downloaded {name}.")


def _why(error: urllib.error.HTTPError) -> str:
    """What Ollama said was wrong, from its {"error": ...} body, else the HTTP status."""
    try:
        said = json.load(error).get("error")
    except (OSError, ValueError, AttributeError):
        said = None
    return str(said or f"it answered with an error ({error.code})").rstrip(".") + "."


def use(name: str, how: str | None, say: Callable[[str], None] | None = None) -> None:
    """Use the downloaded model as `how` says (see the module's notes); `how` None is "starter"
    while no model is set, else nothing."""
    say = say or _print
    before = config.env("MODEL") or llm.default()
    how = how or ("" if config.env("MODEL") else "starter")
    if not how:
        return
    config.save_setting("MODEL", llm.OLLAMA + name)
    say(f"Using {name} as the main model.")
    light = how == "main" and not config.env("FAST_MODEL").strip()
    if light and before.startswith(llm.OLLAMA) and before != llm.OLLAMA + name:
        config.save_setting("FAST_MODEL", before)
        say(f"{llm.bare(before)} keeps doing the light jobs.")


def run(args) -> None:
    name = (args.name or "").strip().removeprefix(llm.OLLAMA)
    if not _NAME.fullmatch(name):
        raise SystemExit("Name the model to download, e.g. proxenos model pull gemma4:e4b.")
    pull(name)
    use(name, args.use)


def _print(text: str) -> None:
    print(text, file=sys.stdout, flush=True)
