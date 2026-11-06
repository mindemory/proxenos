"""The fast model: finding it and serving it. No model, no network, no vault."""

import argparse
import json

import pytest

from proxenos import cli, fastmodel, llm

FAST = "local:mlx-community/gemma-4-e4b-it-4bit"
_real_found, _real_capable, _real_running = (
    fastmodel.found,
    fastmodel.capable,
    fastmodel.running,
)  # conftest stands them in for every test; these test them


def mac(system="Darwin", machine="arm64", mlx=True):
    return {
        "system": lambda: system,
        "machine": lambda: machine,
        "spec": lambda name: object() if mlx and name == "mlx_lm" else None,
    }


def test_the_fast_model_is_found_on_apple_silicon_with_mlx_and_the_weights_downloaded(monkeypatch):
    monkeypatch.setattr(fastmodel, "capable", _real_capable)
    assert fastmodel.NAME == FAST
    assert _real_capable(**mac())
    assert not _real_capable(**mac(machine="x86_64"))
    assert not _real_capable(**mac(system="Linux"))
    assert not _real_capable(**mac(mlx=False))
    assert _real_found(cached=lambda base: base == fastmodel.BASE, **mac())
    assert not _real_found(cached=lambda base: False, **mac())
    assert not _real_found(cached=lambda base: True, **mac(mlx=False))


def test_the_weights_are_in_hugging_faces_cache_when_a_snapshot_has_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not fastmodel._cached(fastmodel.BASE)
    snapshot = tmp_path / "models--mlx-community--gemma-4-e4b-it-4bit" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    assert not fastmodel._cached(fastmodel.BASE)  # a download that never finished
    (snapshot / "config.json").write_text("{}")
    assert fastmodel._cached(fastmodel.BASE)

    monkeypatch.delenv("HF_HUB_CACHE")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))  # beside it: HF_HOME/hub
    assert not fastmodel._cached(fastmodel.BASE)


def test_serve_runs_mlx_lms_server_on_this_computer_at_its_own_port(monkeypatch):
    ran = []
    monkeypatch.setattr(fastmodel.os, "execv", lambda exe, command: ran.append(command))
    monkeypatch.setattr(fastmodel.importlib.util, "find_spec", lambda name: object())
    fastmodel.serve()
    (command,) = ran
    assert command[1:4] == ["-m", "mlx_lm", "server"]
    assert command[command.index("--model") + 1] == "mlx-community/gemma-4-e4b-it-4bit"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == str(llm.FAST_PORT) == "8898"
    assert json.loads(command[command.index("--chat-template-args") + 1]) == {
        "enable_thinking": False
    }

    monkeypatch.setattr(fastmodel.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SystemExit, match="mlx-lm"):
        fastmodel.serve()


def test_its_server_is_running_when_it_lists_models(monkeypatch):
    class Listing:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, *_):
            return b'{"object": "list", "data": []}'

    asked = []

    def opened(url, timeout):
        asked.append(url)
        return Listing()

    monkeypatch.setattr(llm, "_direct", opened)
    assert _real_running() and asked == ["http://127.0.0.1:8898/v1/models"]

    def down(url, timeout):
        raise llm.urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm, "_direct", down)
    assert not _real_running()
    assert not _real_running("https://example.com/v1")  # not this computer's: never asked


def test_the_command_takes_serve_fast_and_a_port(monkeypatch):
    parser = argparse.ArgumentParser()
    fastmodel.add_arguments(parser)
    assert parser.parse_args(["serve-fast"]).port == llm.FAST_PORT
    args = parser.parse_args(["serve-fast", "--port", "9000"])
    ran = []
    monkeypatch.setattr(fastmodel, "serve", ran.append)
    fastmodel.run(None, args)
    assert ran == [9000]


def test_model_is_a_command(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.fastmodel, "run", lambda vault, args: seen.append(args.action))
    cli.main(["model", "serve-fast"])
    assert seen == ["serve-fast"]
