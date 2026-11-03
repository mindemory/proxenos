"""Listen's voices made on this computer (proxenos.speech), with a fake engine: no model is
downloaded or loaded, nothing reaches the network, and every clip is made up in the test."""

import base64
import http.client
import io
import json
import os
import socket
import sys
import threading
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from proxenos import cli, speech


@pytest.fixture(autouse=True)
def no_engines_here(monkeypatch):
    """As on a Mac with everything installed and no model downloaded, whatever this computer has."""
    monkeypatch.setattr(speech, "supported", lambda: True)
    monkeypatch.setattr(speech, "missing", list)
    monkeypatch.setattr(speech, "cached", lambda engine: None)


def _clip(seconds: float = 8.0, rate: int = speech.RATE, channels: int = 1) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    tone = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(tone, channels).tobytes())
    return out.getvalue()


class FakeEngine:
    """Speaks a tenth of a second of quiet for each word, and keeps what it was asked."""

    def __init__(self):
        self.said: list[tuple[str, str | None]] = []

    def say(self, text, voice):
        self.said.append((text, voice))
        return np.zeros(len(text.split()) * speech.RATE // 10, dtype=np.float32)


class Running:
    """`speech.serve` in a thread, with the loader given, until the test ends."""

    def __init__(self, vault: Path, load):
        self.vault = vault
        ready = threading.Event()
        self.server = None

        def started(server):
            self.server = server
            ready.set()

        self.thread = threading.Thread(
            target=speech.serve, args=(vault,), kwargs={"load": load, "started": started}
        )
        self.thread.start()
        assert ready.wait(5)
        self.state = json.loads((speech.folder(vault) / "server.json").read_text())

    def request(self, method, path, body=None, headers=None, host=None):
        connection = http.client.HTTPConnection(speech.HOST, self.state["port"], timeout=5)
        sent = {"Content-Type": "application/json", speech.TOKEN_HEADER: self.state["token"]}
        sent |= headers or {}
        if host:
            connection.putrequest(method, path, skip_host=True)
            connection.putheader("Host", host)
            payload = json.dumps(body).encode() if body is not None else b""
            for k, v in (sent | {"Content-Length": str(len(payload))}).items():
                if v is not None:
                    connection.putheader(k, v)
            connection.endheaders(payload)
        else:
            payload = json.dumps(body) if body is not None else None
            connection.request(method, path, payload, {k: v for k, v in sent.items() if v})
        answer = connection.getresponse()
        return answer.status, answer.getheader("Content-Type"), answer.read()

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.thread.join(5)


@pytest.fixture
def running(tmp_path):
    servers = []

    def start(load):
        servers.append(Running(tmp_path, load))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def test_server_listens_only_on_loopback(tmp_path, running):
    fake = FakeEngine()
    server = running(lambda engine, vault: fake)
    assert server.server.server_address[0] == "127.0.0.1"
    assert speech.HOST == "127.0.0.1"
    # Not reachable on this computer's other addresses: only loopback was bound.
    try:
        found = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:  # a machine whose name doesn't resolve has no other address to try
        found = []
    others = {a[4][0] for a in found if not a[4][0].startswith("127.")}
    for address in others:
        with socket.socket() as s:
            s.settimeout(1)
            assert s.connect_ex((address, server.state["port"])) != 0
    # Where it is, with its token, is readable only by the user.
    state = speech.folder(tmp_path) / "server.json"
    assert os.name == "nt" or state.stat().st_mode & 0o777 == 0o600
    assert server.state["pid"] == os.getpid()


def test_server_answers_only_the_page(running):
    server = running(lambda engine, vault: FakeEngine())
    speak = {"text": "Hello there.", "engine": "natural"}
    assert server.request("POST", "/speak", speak, {speech.TOKEN_HEADER: "wrong"})[0] == 403
    assert server.request("POST", "/speak", speak, {speech.TOKEN_HEADER: None})[0] == 403
    # A browser on another site sends an Origin; a rebound name sends its own Host.
    assert server.request("POST", "/speak", speak, {"Origin": "https://example.com"})[0] == 403
    assert server.request("POST", "/speak", speak, host="attacker.example:80")[0] == 403
    assert server.request("GET", "/ping")[0] == 200


def test_text_in_audio_out(running):
    fake = FakeEngine()
    loaded = []

    def load(engine, vault):
        loaded.append(engine)
        return fake

    server = running(load)
    status, kind, body = server.request(
        "POST",
        "/speak",
        {"text": "Your  visit is\non Thursday.", "engine": "natural", "voice": "bf_emma"},
    )
    assert status == 200 and kind == "audio/wav"
    with wave.open(io.BytesIO(body)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, speech.RATE)
        assert w.getnframes() == 5 * speech.RATE // 10  # five words
    assert fake.said == [("Your visit is on Thursday.", "bf_emma")]
    server.request("POST", "/speak", {"text": "Again.", "engine": "natural"})
    assert loaded == ["natural"]  # loaded once, kept for the next sentence
    assert server.request("POST", "/speak", {"text": "", "engine": "natural"})[0] == 400
    assert server.request("POST", "/speak", {"text": "x" * 2000, "engine": "natural"})[0] == 400
    assert server.request("POST", "/speak", {"text": "Hi.", "engine": "cloud"})[0] == 400
    assert (
        server.request("POST", "/speak", {"text": "Hi.", "engine": "own", "voice": "../x"})[0]
        == 400
    )


def test_warm_loads_the_engine_before_listen_asks(running):
    fake = FakeEngine()
    server = running(lambda engine, vault: fake)
    assert server.request("POST", "/warm", {"engine": "natural"})[0] == 202
    for _ in range(50):
        if fake.said:
            break
        threading.Event().wait(0.1)
    assert fake.said == [("Ready.", None)]
    assert server.request("POST", "/warm", {"engine": "cloud"})[0] == 400


def test_warm_with_nothing_to_load_stops_the_server(tmp_path, running):
    server = running(speech.load_engine)  # nothing downloaded here
    assert server.request("POST", "/warm", {"engine": "natural"})[0] == 202
    server.thread.join(5)
    assert not server.thread.is_alive()
    assert speech.server_state(tmp_path) is None


def test_stop_server_asks_it_to_stop(tmp_path, running):
    server = running(lambda engine, vault: FakeEngine())
    assert speech.server_state(tmp_path)["port"] == server.state["port"]
    assert speech.stop_server(tmp_path)
    server.thread.join(5)
    assert not server.thread.is_alive()
    assert not (speech.folder(tmp_path) / "server.json").exists()
    assert speech.server_state(tmp_path) is None
    assert not speech.stop_server(tmp_path)


def test_not_installed_says_how_and_the_page_falls_back(tmp_path, running, monkeypatch):
    monkeypatch.setattr(speech, "missing", lambda: ["mlx_audio", "misaki"])
    with pytest.raises(speech.NotReady, match=r"pip install -e \"\.\[speech\]\""):
        speech.load_engine("natural", tmp_path)
    report = speech.status(tmp_path)
    assert report["supported"] and not report["installed"]
    assert report["missing"] == ["mlx_audio", "misaki"]
    assert not report["engines"]["natural"]["downloaded"]
    with pytest.raises(SystemExit, match="Install the speech extra"):
        speech.get(tmp_path, "natural", fetch=lambda model, progress: pytest.fail("fetched"))
    # The server says why, with 409, which has Listen read with the device's voice instead.
    server = running(speech.load_engine)
    status, _, body = server.request("POST", "/speak", {"text": "Hello.", "engine": "natural"})
    assert status == 409 and "Not installed" in json.loads(body)["error"]


def test_not_on_apple_silicon(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, "supported", lambda: False)
    report = speech.status(tmp_path)
    assert not report["supported"] and not report["installed"]
    with pytest.raises(speech.NotReady, match="Apple silicon"):
        speech.load_engine("natural", tmp_path)


def test_not_downloaded_and_no_clip(tmp_path, monkeypatch, running):
    with pytest.raises(speech.NotReady, match="isn't downloaded"):
        speech.load_engine("natural", tmp_path)
    monkeypatch.setattr(speech, "cached", lambda engine: tmp_path / "model")
    with pytest.raises(speech.NotReady, match="no clip"):
        speech.load_engine("own", tmp_path)
    # An engine that fails is a 500, which the page also falls back from.
    server = running(lambda engine, vault: (_ for _ in ()).throw(RuntimeError("Metal ran out")))
    status, _, body = server.request("POST", "/speak", {"text": "Hello.", "engine": "natural"})
    assert status == 500 and "Metal ran out" in json.loads(body)["error"]


def test_clip_is_kept_private_and_deleted_on_request(tmp_path, monkeypatch):
    stopped = []
    monkeypatch.setattr(speech, "stop_server", lambda vault: stopped.append(vault) or True)
    kept = speech.save_clip(tmp_path, _clip(8.0), "  I'm reading\nthis.  ")
    assert kept["seconds"] == 8.0 and kept["text"] == "I'm reading this."
    folder = speech.folder(tmp_path)
    assert speech.clip_path(tmp_path).read_bytes() == _clip(8.0)
    assert os.name == "nt" or (
        folder.stat().st_mode & 0o777 == 0o700
        and speech.clip_path(tmp_path).stat().st_mode & 0o777 == 0o600
        and (folder / "clip.json").stat().st_mode & 0o777 == 0o600
    )
    # The status says how long and when, never the sound.
    about = speech.status(tmp_path)["clip"]
    assert about["seconds"] == 8.0 and about["text"] == "I'm reading this."
    assert "wav" not in json.dumps(about)

    assert speech.delete_clip(tmp_path)
    assert not speech.clip_path(tmp_path).exists() and not (folder / "clip.json").exists()
    assert speech.clip(tmp_path) is None
    assert stopped == [tmp_path]  # nothing made from it stays in the server's memory
    assert not speech.delete_clip(tmp_path)


@pytest.mark.parametrize(
    "data, why",
    [
        (_clip(2.0), "needs 5 to 30 seconds"),
        (_clip(31.0), "needs 5 to 30 seconds"),
        (_clip(8.0, rate=44100), "16-bit mono"),
        (_clip(8.0, channels=2), "16-bit mono"),
        (b"RIFF nonsense", "isn't a WAV"),
    ],
)
def test_clip_refused(tmp_path, data, why):
    with pytest.raises(speech.ClipError, match=why):
        speech.save_clip(tmp_path, data, None)
    assert not speech.clip_path(tmp_path).exists()


def test_clip_from_the_page_through_the_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(speech, "stop_server", lambda vault: False)
    line = json.dumps({"wav": base64.b64encode(_clip(6.0)).decode(), "text": speech.CLIP_PASSAGE})
    monkeypatch.setattr("sys.stdin", io.StringIO(line))
    cli.main(["speech", "clip", "save"])
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] and answer["clip"]["text"] == speech.CLIP_PASSAGE
    monkeypatch.setattr("sys.stdin", io.StringIO('{"wav": "not base64!"}'))
    cli.main(["speech", "clip", "save"])
    assert not json.loads(capsys.readouterr().out)["ok"]
    cli.main(["speech", "status"])
    status = json.loads(capsys.readouterr().out)
    assert status["clip"]["seconds"] == 6.0 and status["passage"] == speech.CLIP_PASSAGE
    assert status["voices"][0]["id"] == status["default_voice"]
    cli.main(["speech", "clip", "delete"])
    assert json.loads(capsys.readouterr().out) == {"ok": True, "deleted": True}
    assert speech.clip(tmp_path) is None


class _Tqdm:
    """tqdm as far as the progress bars use it, where the speech extra isn't installed."""

    def __init__(self, *args, total=None, **kwargs):
        self.total = total


def test_download_notes_how_far_it_got(tmp_path, monkeypatch):
    try:
        import tqdm.auto  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "tqdm", types.ModuleType("tqdm"))
        monkeypatch.setitem(sys.modules, "tqdm.auto", types.SimpleNamespace(tqdm=_Tqdm))

    def fetch(model, progress):
        assert model is speech.MODELS["own"]
        bar = progress.bar()(total=0, initial=0, unit="B", desc="Downloading")
        bar.total = 2000
        for _ in range(4):
            bar.update(500)
        progress.tick(force=True)
        seen.append(json.loads((speech.folder(tmp_path) / "download.json").read_text()))

    seen = []
    assert "ready" in speech.get(tmp_path, "own", fetch=fetch)
    assert seen[0]["state"] == "running" and seen[0]["done"] == 2000 and seen[0]["total"] == 2000
    done = speech.download_state(tmp_path)
    assert done["state"] == "done" and done["engine"] == "own" and done["total"] == 2000

    def broken(model, progress):
        raise OSError("no route to host")

    with pytest.raises(SystemExit, match="no route to host"):
        speech.get(tmp_path, "own", fetch=broken)
    failed = speech.download_state(tmp_path)
    assert failed["state"] == "failed" and "no route" in failed["message"]


def test_a_download_that_died_shows_as_stopped(tmp_path):
    speech._write_json(
        speech.folder(tmp_path) / "download.json",
        {"engine": "natural", "state": "running", "pid": 2**22 + 12345, "done": 5, "total": 10},
    )
    assert speech.download_state(tmp_path)["state"] == "failed"


def test_wav_is_16_bit_mono():
    data = speech.wav(np.array([0.0, 2.0, -2.0, 0.5], dtype=np.float32))
    with wave.open(io.BytesIO(data)) as w:
        frames = np.frombuffer(w.readframes(4), dtype="<i2")
    assert frames.tolist() == [0, 32767, -32767, 16383]
