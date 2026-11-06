"""The fast model: finding it, serving it, and timing it. No model, no network, no vault."""

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


def mac(system="Darwin", machine="arm64", mlx=True, release="15.3"):
    return {
        "system": lambda: system,
        "machine": lambda: machine,
        "spec": lambda name: object() if mlx and name == "mlx_lm" else None,
        "release": lambda: release,
    }


def test_the_fast_model_is_found_on_apple_silicon_with_mlx_and_the_weights_downloaded(monkeypatch):
    monkeypatch.setattr(fastmodel, "capable", _real_capable)
    assert fastmodel.NAME == FAST
    assert _real_capable(**mac())
    assert not _real_capable(**mac(machine="x86_64"))
    assert not _real_capable(**mac(system="Linux"))
    assert not _real_capable(**mac(mlx=False))
    assert not _real_capable(**mac(release="13.6"))  # MLX needs macOS 14
    assert _real_capable(**mac(release="26.1"))
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


def test_the_long_prompt_is_made_up_the_same_every_time_and_as_long_as_asked():
    one, again = fastmodel.synthetic(6000), fastmodel.synthetic(6000)
    assert one == again and 6000 <= len(one) < 6400
    assert one.startswith("Item 1: ") and one.endswith(fastmodel.LONG_ASK)
    assert fastmodel.synthetic(12_000) != one
    salted = fastmodel.synthetic(6000, "ab12")  # a run of its own, so no server has it cached
    assert salted.startswith("Run ab12.\nItem 2: ") and salted != fastmodel.synthetic(6000, "cd34")
    words = set(" ".join(one.splitlines()[:-1]).replace(".", "").split())
    assert words <= {*fastmodel._WORDS, "Item", *(f"{n}:" for n in range(1, 200))}


class Machine:
    """llm.ask standing in for models, and the clock they take their time by: each call moves it
    on by the seconds its model takes, and leaves the call's tokens and time to the first word
    where llm.last_call reads them. `speeds` is, by model, (tokens in, seconds to the first word,
    tokens out, seconds writing)."""

    def __init__(self, speeds, monkeypatch):
        self.speeds, self.log, self.now = speeds, [], 0.0
        monkeypatch.setattr(
            fastmodel, "time", type("Clock", (), {"monotonic": lambda _: self.now})()
        )

    def __call__(self, prompt, *, effort, max_tokens):
        model = llm.current()
        self.log.append((model, len(prompt), max_tokens))
        if model not in self.speeds:
            raise llm.Unreachable("the local model isn't answering")
        tokens_in, first, tokens_out, wrote = self.speeds[model]
        llm._usage.tokens, llm._usage.first = (tokens_in, tokens_out), first
        self.now += first + wrote
        return "ok"


def test_bench_times_a_short_and_a_long_prompt_on_each_model_and_reads_the_rates(monkeypatch):
    ask = Machine({"ollama:big": (6000, 40.0, 100, 4.0), FAST: (6000, 12.0, 100, 2.0)}, monkeypatch)
    rows = fastmodel.bench(["ollama:big", FAST], 3000, ask)

    assert [(r["model"], r["prompt"]) for r in rows] == [
        ("ollama:big", "short"),
        ("ollama:big", "long"),
        (FAST, "short"),
        (FAST, "long"),
    ]
    # One warm-up each, not counted, then the short prompt, which writes up to 300 tokens, and the
    # long one, which is asked for a sentence.
    assert [(m, limit) for m, _, limit in ask.log] == [
        ("ollama:big", 8),
        ("ollama:big", fastmodel.SHORT_TOKENS),
        ("ollama:big", fastmodel.LONG_TOKENS),
        (FAST, 8),
        (FAST, fastmodel.SHORT_TOKENS),
        (FAST, fastmodel.LONG_TOKENS),
    ]
    assert ask.log[2][1] > 3000 > ask.log[1][1]
    big, fast = rows[1], rows[3]
    assert big["seconds"] == 44.0 and big["read"] == 6000 / 40.0 and big["write"] == 100 / 4.0
    assert fast["read"] == 6000 / 12.0 and fast["write"] == 100 / 2.0


def test_a_model_that_isnt_answering_fails_its_rows_and_not_the_rest(monkeypatch):
    ask = Machine({FAST: (100, 1.0, 50, 2.0)}, monkeypatch)
    rows = fastmodel.bench(["ollama:big", FAST], 2000, ask)
    assert [("error" in r) for r in rows] == [True, True, False, False]
    assert "isn't answering" in rows[0]["error"]
    assert [m for m, *_ in ask.log].count("ollama:big") == 1  # the warm-up said so: no more tries


def test_the_table_has_a_line_a_prompt_with_rates_where_they_are_known():
    text = fastmodel.table(
        [
            {
                "model": "ollama:gemma4:26b",
                "prompt": "long",
                "tokens_in": 6000,
                "tokens_out": 20,
                "seconds": 41.5,
                "read": 150.0,
                "write": 25.2,
            },
            {
                "model": FAST,
                "prompt": "short",
                "tokens_in": None,
                "tokens_out": None,
                "seconds": 3.0,
            }
            | {"read": None, "write": None},
            {"model": FAST, "prompt": "long", "error": "no server"},
        ]
    )
    head, big, small, down = text.splitlines()
    assert "read/s" in head and "write/s" in head
    assert big.split() == ["gemma4:26b", "long", "6000", "20", "41.5", "150", "25"]
    assert small.split() == [
        "mlx-community/gemma-4-e4b-it-4bit",
        "short",
        "?",
        "?",
        "3.0",
        "?",
        "?",
    ]
    assert down.endswith("no server")


def test_it_times_the_main_model_and_the_fast_one_when_they_are_on_this_computer(monkeypatch):
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    assert fastmodel.models_to_time() == (
        ["ollama:gemma4:26b"],
        ["No fast model set (PROXENOS_FAST_MODEL), so only the main one is timed."],
    )
    monkeypatch.setenv("PROXENOS_FAST_MODEL", FAST)
    assert fastmodel.models_to_time() == (["ollama:gemma4:26b", FAST], [])
    monkeypatch.setenv("PROXENOS_MODEL", "claude-opus-5-5")
    chosen, notes = fastmodel.models_to_time()
    assert chosen == [FAST] and "not timed" in notes[0]


def test_the_command_takes_serve_fast_and_bench(monkeypatch, capsys):
    parser = argparse.ArgumentParser()
    fastmodel.add_arguments(parser)
    args = parser.parse_args(["bench", "--chars", "5000"])
    assert (args.action, args.chars, args.port) == ("bench", 5000, llm.FAST_PORT)
    assert parser.parse_args(["serve-fast", "--port", "9000"]).port == 9000

    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    monkeypatch.setattr(
        fastmodel, "bench", lambda models, chars: [{"seen": models, "chars": chars}]
    )
    monkeypatch.setattr(fastmodel, "table", lambda rows: f"table of {rows}")
    fastmodel.run(None, args)
    out = capsys.readouterr().out
    assert (
        "No fast model set" in out
        and "table of [{'seen': ['ollama:gemma4:26b'], 'chars': 5000}]" in out
    )

    ran = []
    monkeypatch.setattr(fastmodel, "serve", ran.append)
    fastmodel.run(None, parser.parse_args(["serve-fast", "--port", "9000"]))
    assert ran == [9000]


def test_model_is_a_command(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.fastmodel, "run", lambda vault, args: seen.append(args.action))
    cli.main(["model", "serve-fast"])
    assert seen == ["serve-fast"]
