"""`proxenos speech`: Listen's natural voice, or the user's own, made on this computer.

The page's Listen reads with the browser's voices unless the user picks one of these in
Settings, Listening. Both run with mlx-audio, on a Mac with Apple silicon only, and only once the
optional extra is installed (`pip install -e ".[speech]"`); anywhere else, or if one fails, Listen
reads with the device's voices as before. Health text is read aloud too, so nothing here sends
anything anywhere: the models' weights come from Hugging Face once, when the user asks for them
(`get`), and after that the server runs with Hugging Face switched off (HF_HUB_OFFLINE).

- **natural:** Kokoro-82M (Apache-2.0), a small model with a few dozen voices, of which VOICES
  are offered. About ten times faster than real time on an M1 Pro, so a sentence is ready
  before the one before it ends.
- **own:** Qwen3-TTS 0.6B Base (Apache-2.0), which speaks in the voice of a short reference
  clip, given what the clip says. The user records CLIP_PASSAGE on the page (or picks a
  recording and says what's in it), and the clip is kept in the vault, at state/speech/clip.wav,
  readable only by them, until they delete it. It's never sent anywhere, and only the user's
  own voice is meant to be copied: the page asks them to record themselves.

`serve` keeps the models loaded in a small HTTP server on 127.0.0.1 only, at a port the system
picks, and writes where it is, with a random token, to state/speech/server.json; the page's
route reads that and sends each sentence there, and the server answers only requests to a
loopback host, with no Origin (so not a browser on another site) and with that token. It stops
itself after IDLE seconds with nothing to say. Deleting the clip stops it too, so nothing made
from the clip stays in memory.
"""

import argparse
import base64
import binascii
import hmac
import importlib.util
import io
import json
import os
import platform
import re
import secrets
import signal
import sys
import threading
import time
import urllib.request
import wave
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol

import numpy as np

from proxenos import lock

HOST = "127.0.0.1"  # never anything else: what's read aloud stays on this computer
RATE = 24000  # both models speak at 24 kHz, and a clip is kept at it
IDLE = 900  # seconds with nothing to say before the server stops itself
MAX_TEXT = 1200  # characters in one request; the page sends a sentence or two at a time
MAX_BODY = 16 * 1024
CLIP_MIN, CLIP_MAX = 5.0, 30.0  # seconds
CLIP_BYTES = 4 * 1024 * 1024
TOKEN_HEADER = "X-Proxenos-Speech"
# What the user reads for their clip: about 15 seconds of everyday words, nothing personal. The
# cloning model is told the clip says exactly this, and works through it again for every
# sentence, so a longer clip is slower: with this one, about 1.3 times faster than real time on an
# M1 Pro, against about 1 with a 20-second clip.
CLIP_PASSAGE = (
    "I'm reading this so Proxenos can learn how my voice sounds. On a quiet morning I like to "
    "open the window, make a cup of tea and look over the day ahead. Some days are busy; others "
    "are slow, and that's fine too."
)


class Model:
    def __init__(self, repo: str, kind: str, files: tuple[str, ...], size: str):
        self.repo = repo
        self.kind = kind  # mlx-audio's name for it, which a snapshot's folder doesn't carry
        self.files = files  # what to download; the rest of the repo (samples, a README) isn't
        self.size = size  # roughly, for the page


# Kokoro's voices the page offers: its best-rated English ones, American and British.
VOICES = (
    ("af_heart", "Heart", "American"),
    ("af_bella", "Bella", "American"),
    ("am_michael", "Michael", "American"),
    ("am_fenrir", "Fenrir", "American"),
    ("bf_emma", "Emma", "British"),
    ("bm_george", "George", "British"),
)
DEFAULT_VOICE = VOICES[0][0]
MODELS = {
    "natural": Model(
        "mlx-community/Kokoro-82M-bf16",
        "kokoro",
        (
            "config.json",
            "kokoro-v1_0.safetensors",
            *(f"voices/{v}.safetensors" for v, *_ in VOICES),
        ),
        "about 330 MB",
    ),
    "own": Model(
        "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
        "qwen3_tts",
        (
            "*.json",
            "*.safetensors",
            "merges.txt",
            "vocab.json",
            "speech_tokenizer/*",
        ),
        "about 2 GB",
    ),
}
ENGINES = tuple(MODELS)
# What the extra installs, by the module each is imported as.
NEEDS = ("mlx_audio", "misaki", "spacy", "en_core_web_sm", "phonemizer", "espeakng_loader")


def supported() -> bool:
    """A Mac with Apple silicon: what MLX runs on."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def missing() -> list[str]:
    """What the extra would install that isn't installed."""
    return [name for name in NEEDS if importlib.util.find_spec(name) is None]


def install_command() -> str:
    """The one line that installs the extra, with this Python's own pip, from the repo."""
    return f'"{sys.executable}" -m pip install -e ".[speech]"'


# ── Where things are kept ────────────────────────────────────────────────────


def folder(vault: Path) -> Path:
    return vault / "state" / "speech"


def _private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def _write(path: Path, data: bytes) -> None:
    """Swap a file in whole, readable only by the user."""
    _private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if os.name != "nt":
        tmp.chmod(0o600)  # the mode above only applies when the file is new
    os.replace(tmp, path)


def _write_json(path: Path, doc: dict) -> None:
    _write(path, (json.dumps(doc, ensure_ascii=False) + "\n").encode())


def _read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _alive(pid: object) -> bool:
    return isinstance(pid, int) and not isinstance(pid, bool) and lock.alive(pid)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── The clip ─────────────────────────────────────────────────────────────────


def clip_path(vault: Path) -> Path:
    return folder(vault) / "clip.wav"


def clip(vault: Path) -> dict | None:
    """The clip kept, without its sound: how long it is, when it was saved and what it says."""
    about = _read_json(folder(vault) / "clip.json")
    if about is None or not clip_path(vault).is_file():
        return None
    return {
        "seconds": about.get("seconds"),
        "at": about.get("at"),
        "text": about.get("text") if isinstance(about.get("text"), str) else None,
    }


class ClipError(ValueError):
    pass


def save_clip(vault: Path, data: bytes, text: str | None) -> dict:
    """Keep `data`, a WAV of the user reading, as the clip, with what it says. The page sends it
    as 16-bit mono at RATE, between CLIP_MIN and CLIP_MAX seconds; anything else is refused."""
    if len(data) > CLIP_BYTES:
        raise ClipError("That recording is too large.")
    try:
        with wave.open(io.BytesIO(data)) as w:
            shape = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            frames = w.getnframes()
            w.readframes(frames)
    except (wave.Error, EOFError):
        raise ClipError("That isn't a WAV recording.") from None
    if shape != (1, 2, RATE):
        raise ClipError(f"The clip must be 16-bit mono at {RATE} Hz.")
    seconds = round(frames / RATE, 1)
    if not CLIP_MIN <= seconds <= CLIP_MAX:
        raise ClipError(
            f"The clip is {seconds:g} seconds; it needs {CLIP_MIN:g} to {CLIP_MAX:g} seconds."
        )
    said = " ".join((text or "").split())[:2000] or None
    _write(clip_path(vault), data)
    _write_json(folder(vault) / "clip.json", {"seconds": seconds, "at": _now(), "text": said})
    return {"seconds": seconds, "at": clip(vault)["at"], "text": said}


def delete_clip(vault: Path) -> bool:
    """Delete the clip and what's kept about it, and stop the server, which may hold what it
    made of it in memory. Whether there was one."""
    had = False
    for path in (clip_path(vault), folder(vault) / "clip.json"):
        try:
            path.unlink()
            had = True
        except FileNotFoundError:
            pass
    stop_server(vault)
    return had


# ── The models ───────────────────────────────────────────────────────────────


def cached(engine: str) -> Path | None:
    """Where the engine's model is on this computer, or None while it isn't all there. Never
    reaches the network."""
    from huggingface_hub import snapshot_download  # slow to import, so only here

    model = MODELS[engine]
    try:
        path = Path(
            snapshot_download(model.repo, allow_patterns=list(model.files), local_files_only=True)
        )
    except Exception:  # noqa: BLE001 - not downloaded, or half: either way, not ready
        return None
    needed = [f for f in model.files if "*" not in f]
    if not all((path / f).is_file() for f in needed) or not any(path.glob("*.safetensors")):
        return None
    return path


class Engine(Protocol):
    def say(self, text: str, voice: str | None) -> np.ndarray:
        """`text` spoken, as float samples at RATE."""
        ...


def _load(engine: str, path: Path):
    from mlx_audio.tts.utils import load_model  # only on a Mac, with the extra

    return load_model(str(path), model_type=MODELS[engine].kind)


class _Kokoro:
    def __init__(self, path: Path):
        self.model = _load("natural", path)

    def say(self, text: str, voice: str | None) -> np.ndarray:
        voice = voice if voice in {v for v, *_ in VOICES} else DEFAULT_VOICE
        parts = self.model.generate(text=text, voice=voice, speed=1.0, lang_code=voice[0])
        return _joined(r.audio for r in parts)


class _Own:
    def __init__(self, path: Path, vault: Path):
        self.model = _load("own", path)
        self.vault = vault

    def say(self, text: str, voice: str | None) -> np.ndarray:
        kept = clip(self.vault)
        if kept is None:
            raise NotReady("There's no clip of your voice. Record one in Settings, Listening.")
        parts = self.model.generate(
            text=text, ref_audio=str(clip_path(self.vault)), ref_text=kept["text"]
        )
        return _joined(r.audio for r in parts)


def _joined(parts: Iterator) -> np.ndarray:
    arrays = [np.asarray(p, dtype=np.float32).reshape(-1) for p in parts if p is not None]
    return np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.float32)


class NotReady(RuntimeError):
    """The engine can't speak yet: not installed, not downloaded, or no clip."""


def load_engine(engine: str, vault: Path) -> Engine:
    """The engine, loaded from its model on this computer (raises NotReady)."""
    if not supported():
        raise NotReady("A natural voice needs a Mac with Apple silicon.")
    if gaps := missing():
        raise NotReady(f"Not installed ({', '.join(gaps)}): {install_command()}")
    path = cached(engine)
    if path is None:
        raise NotReady("Its model isn't downloaded yet. Get it in Settings, Listening.")
    if engine == "own":
        if clip(vault) is None:
            raise NotReady("There's no clip of your voice. Record one in Settings, Listening.")
        return _Own(path, vault)
    return _Kokoro(path)


def wav(samples: np.ndarray, rate: int = RATE) -> bytes:
    """Float samples in -1..1 as a 16-bit mono WAV."""
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return out.getvalue()


# ── Getting a model ──────────────────────────────────────────────────────────


def download_state(vault: Path) -> dict | None:
    """The last download asked for: its engine, how far it got, and whether it's still going."""
    doc = _read_json(folder(vault) / "download.json")
    if doc is None:
        return None
    if doc.get("state") == "running" and not _alive(doc.get("pid")):
        doc |= {"state": "failed", "message": "The download stopped before it finished."}
    return {k: doc.get(k) for k in ("engine", "state", "done", "total", "message", "at")}


def get(vault: Path, engine: str, fetch: Callable | None = None) -> str:
    """Download the engine's model into Hugging Face's cache on this computer, noting how far it
    got in state/speech/download.json for the page as it goes, then load it once to check it
    speaks. What's downloaded is the model, from Hugging Face; nothing goes the other way."""
    if not supported():
        raise SystemExit("A natural voice needs a Mac with Apple silicon.")
    if gaps := missing():
        raise SystemExit(
            f"Install the speech extra first ({', '.join(gaps)}):\n{install_command()}"
        )
    path = folder(vault) / "download.json"
    running = download_state(vault)
    if running and running["state"] == "running":
        raise SystemExit(f"A download is already going ({running['engine']}).")
    note = {"engine": engine, "pid": os.getpid(), "at": _now(), "done": 0, "total": None}
    _write_json(path, note | {"state": "running", "message": None})
    progress = _Progress(
        lambda done, total: _write_json(
            path, note | {"state": "running", "message": None, "done": done, "total": total}
        )
    )
    try:
        (fetch or _fetch)(MODELS[engine], progress)
        if engine == "natural":  # loads the model and the text-to-sound rules, as Listen will
            load_engine(engine, vault).say("Ready.", DEFAULT_VOICE)
    except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001 - said on the page, then raised
        _write_json(path, note | {"state": "failed", "message": _why(e), **progress.counts()})
        raise SystemExit(f"speech: {engine} didn't download: {_why(e)}") from None
    _write_json(path, note | {"state": "done", "message": None, **progress.counts()})
    return f"speech: {engine} is ready ({MODELS[engine].repo})"


def _why(e: BaseException) -> str:
    return " ".join(str(e).split())[:300] or type(e).__name__


class _Progress:
    """Bytes downloaded so far and in all, from the progress bars huggingface_hub keeps, passed
    on at most every half second."""

    def __init__(self, report: Callable[[int, int | None], None], every: float = 0.5):
        self.report = report
        self.every = every
        self.bars: list = []
        self.last = 0.0

    def counts(self) -> dict:
        sized = [b for b in self.bars if b.unit == "B"]
        total = max((int(b.total or 0) for b in sized), default=0) or None
        done = max((int(b.n) for b in sized), default=0)
        return {"done": min(done, total) if total else done, "total": total}

    def tick(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last >= self.every:
            self.last = now
            self.report(**self.counts())

    def bar(self):
        """A tqdm class that shows nothing and tells this how far it got."""
        from tqdm.auto import tqdm  # comes with huggingface_hub

        watcher = self

        class Bar(tqdm):
            def __init__(self, *args, **kwargs):
                kwargs.pop("name", None)
                super().__init__(*args, **{**kwargs, "disable": True})
                self.unit = kwargs.get("unit", "it")
                self.n = kwargs.get("initial", 0) or 0
                watcher.bars.append(self)

            def update(self, n=1):
                self.n += n or 0
                watcher.tick()

            def refresh(self, *args, **kwargs):
                watcher.tick()

        return Bar


def _fetch(model: Model, progress: _Progress) -> None:
    from huggingface_hub import snapshot_download  # slow to import, so only here

    snapshot_download(model.repo, allow_patterns=list(model.files), tqdm_class=progress.bar())
    progress.tick(force=True)


# ── The server ───────────────────────────────────────────────────────────────


def server_state(vault: Path) -> dict | None:
    """Where the server is listening, with its token, while it runs."""
    doc = _read_json(folder(vault) / "server.json")
    return doc if doc and _alive(doc.get("pid")) else None


def stop_server(vault: Path) -> bool:
    """Ask the server to stop, as the page asks it to speak: at its port, with its token, and
    through no proxy. Whether it said it would."""
    doc = server_state(vault)
    if doc is None:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(
            f"http://{HOST}:{int(doc['port'])}/stop",
            method="POST",
            headers={TOKEN_HEADER: str(doc.get("token", ""))},
        )
        with opener.open(request, timeout=5) as answer:
            return answer.status == 200
    except (OSError, ValueError, TypeError, KeyError):
        return False


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, vault: Path, port: int, load: Callable[[str, Path], Engine]):
        super().__init__((HOST, port), _Handler)
        self.vault = vault
        self.load = load
        self.token = secrets.token_hex(16)
        self.engines: dict[str, Engine] = {}
        self.lock = threading.Lock()  # one sentence at a time: MLX isn't made for more
        self.last = time.monotonic()

    def speak(self, engine: str, text: str, voice: str | None) -> bytes:
        with self.lock:
            self.last = time.monotonic()
            if engine not in self.engines:
                self.engines[engine] = self.load(engine, self.vault)
            audio = self.engines[engine].say(text, voice)
            self.last = time.monotonic()
        return wav(audio)

    def warm(self, engine: str, voice: str | None = None) -> None:
        """Load the engine and say a word, unheard, so the first sentence Listen asks for comes
        quickly: the page asks for this when a view with Listen opens. An engine that can't (not
        installed, not downloaded, no clip) leaves a server with nothing loaded no reason to
        stay, so it stops."""
        try:
            self.speak(engine, "Ready.", voice)
        except NotReady:
            if not self.engines:
                self.shutdown()
        except Exception:  # noqa: BLE001, S110 - a sentence asked for later says what's wrong
            pass


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # what's read aloud isn't logged
        pass

    def _answer(self, status: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._answer(status, json.dumps({"error": message}).encode())

    def _allowed(self) -> bool:
        """Only the page's own route: a loopback host (no DNS rebinding), no Origin (no browser
        on another site) and the token from server.json."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        token = self.headers.get(TOKEN_HEADER) or ""
        return (
            host in ("127.0.0.1", "localhost")
            and self.headers.get("Origin") is None
            and hmac.compare_digest(token, self.server.token)
        )

    def do_GET(self):
        if not self._allowed():
            return self._error(403, "forbidden")
        if self.path != "/ping":
            return self._error(404, "not found")
        self._answer(200, json.dumps({"ok": True, "loaded": sorted(self.server.engines)}).encode())

    def do_POST(self):
        if not self._allowed():
            return self._error(403, "forbidden")
        if self.path == "/stop":
            self._answer(200, b'{"ok": true}')
            return threading.Thread(target=self.server.shutdown).start()
        if self.path not in ("/speak", "/warm"):
            return self._error(404, "not found")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._error(415, "expected application/json")
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = -1
        if not 0 < size <= MAX_BODY:
            return self._error(413, "too large")
        try:
            body = json.loads(self.rfile.read(size))
        except ValueError:
            return self._error(400, "invalid JSON")
        text = body.get("text") if isinstance(body, dict) else None
        engine = body.get("engine") if isinstance(body, dict) else None
        voice = body.get("voice") if isinstance(body, dict) else None
        if engine not in ENGINES:
            return self._error(400, f"engine must be one of {', '.join(ENGINES)}")
        if voice is not None and not (
            isinstance(voice, str) and re.fullmatch(r"[a-z_]{1,30}", voice)
        ):
            return self._error(400, "unknown voice")
        if self.path == "/warm":
            self._answer(202, b'{"ok": true}')
            warming = threading.Thread(target=self.server.warm, args=(engine, voice), daemon=True)
            return warming.start()
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            return self._error(400, f"text must be 1 to {MAX_TEXT} characters")
        try:
            audio = self.server.speak(engine, " ".join(text.split()), voice)
        except NotReady as e:
            return self._error(409, str(e))
        except Exception as e:  # noqa: BLE001 - the page falls back to the device's voice
            return self._error(500, f"{engine} couldn't speak: {_why(e)}")
        self._answer(200, audio, "audio/wav")


def serve(
    vault: Path,
    port: int = 0,
    idle: float = IDLE,
    load: Callable[[str, Path], Engine] | None = None,
    started: Callable[[_Server], None] | None = None,
) -> None:
    """Serve on 127.0.0.1 until IDLE seconds pass with nothing to say, or a signal stops it."""
    # Hugging Face stays off from here on: the models are already on this computer.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if running := server_state(vault):
        raise SystemExit(f"The speech server is already running (process {running['pid']}).")
    server = _Server(vault, port, load or load_engine)
    state = folder(vault) / "server.json"
    _write_json(
        state,
        {"pid": os.getpid(), "port": server.server_address[1], "token": server.token, "at": _now()},
    )

    done = threading.Event()

    def watch() -> None:
        while not done.wait(min(5.0, idle / 4)):
            if time.monotonic() - server.last >= idle:
                server.shutdown()
                return

    threading.Thread(target=watch, daemon=True).start()
    # A signal (a logout, the page restarting it) stops it too; only the main thread gets one.
    main = threading.current_thread() is threading.main_thread()
    if main:
        previous = signal.signal(
            signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start()
        )
    try:
        if started:
            started(server)
        server.serve_forever()
    finally:
        done.set()
        if main:
            signal.signal(signal.SIGTERM, previous)
        server.server_close()
        if (_read_json(state) or {}).get("pid") == os.getpid():
            state.unlink(missing_ok=True)


# ── Status and the command ───────────────────────────────────────────────────


def status(vault: Path) -> dict:
    """Everything Settings, Listening shows, as JSON: whether this computer can run the
    engines, what's missing, each model's state, the voices, the clip (never its sound) and the
    download going, if any."""
    can = supported()
    gaps = missing() if can else []
    return {
        "supported": can,
        "installed": can and not gaps,
        "missing": gaps,
        "install": install_command(),
        "engines": {
            name: {
                "downloaded": can and not gaps and cached(name) is not None,
                "size": model.size,
                "model": model.repo,
            }
            for name, model in MODELS.items()
        },
        "voices": [{"id": v, "name": n, "accent": a} for v, n, a in VOICES],
        "default_voice": DEFAULT_VOICE,
        "clip": clip(vault),
        "passage": CLIP_PASSAGE,
        "download": download_state(vault),
        "running": server_state(vault) is not None,
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="what's installed and downloaded, and the clip, as JSON")
    fetching = actions.add_parser("get", help="download an engine's model, once")
    fetching.add_argument("engine", choices=ENGINES)
    saying = actions.add_parser("say", help="speak TEXT into a WAV file, to try an engine")
    saying.add_argument("text")
    saying.add_argument("--engine", choices=ENGINES, default="natural")
    saying.add_argument("--voice", help=f"a natural voice (default {DEFAULT_VOICE})")
    saying.add_argument("-o", "--out", type=Path, required=True, help="the WAV file to write")
    serving = actions.add_parser("serve", help="keep the engines loaded for the page, on 127.0.0.1")
    serving.add_argument("--port", type=int, default=0, help="default: one the system picks")
    serving.add_argument("--idle", type=float, default=IDLE, help="seconds before it stops itself")
    clipping = actions.add_parser("clip", help="keep or delete the clip of your voice")
    clipping.add_argument(
        "change", choices=["save", "delete"], help='save: {"wav": base64, "text": ...} on stdin'
    )


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.action == "status":
        print(json.dumps(status(vault), ensure_ascii=False))
    elif args.action == "get":
        print(get(vault, args.engine))
    elif args.action == "say":
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            audio = load_engine(args.engine, vault).say(args.text, args.voice)
        except NotReady as e:
            raise SystemExit(str(e)) from None
        args.out.write_bytes(wav(audio))
        print(f"speech: {len(audio) / RATE:.1f} seconds in {args.out}")
    elif args.action == "serve":
        serve(vault, args.port, args.idle)
    elif args.change == "delete":
        print(json.dumps({"ok": True, "deleted": delete_clip(vault)}))
    else:
        print(json.dumps(_save_from(vault, sys.stdin.read())))


def _save_from(vault: Path, line: str) -> dict:
    """Save the clip the page sent as {"wav": base64, "text": what it says}."""
    try:
        doc = json.loads(line or "{}")
        data = base64.b64decode(doc.get("wav") or "", validate=True)
    except (ValueError, AttributeError, binascii.Error):
        return {"ok": False, "error": "That isn't a recording this can read."}
    text = doc.get("text") if isinstance(doc.get("text"), str) else None
    try:
        return {"ok": True, "clip": save_clip(vault, data, text)}
    except ClipError as e:
        return {"ok": False, "error": str(e)}
