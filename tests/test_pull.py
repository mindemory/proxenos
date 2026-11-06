"""`proxenos model pull`: a download through Ollama, with a fake stream. No model, no network."""

import argparse
import io
import json
import urllib.error

import pytest

from proxenos import cli, config, fastmodel, llm, pull

GB = 10**9


def stream(*events):
    """What Ollama sends: a JSON line each, as a response a `with` can read line by line."""
    return io.BytesIO(b"".join(json.dumps(e).encode() + b"\n" for e in events))


def opened(*events, seen=None):
    def opener(request, timeout):
        if seen is not None:
            seen.append((request.full_url, json.loads(request.data), timeout))
        return stream(*events)

    return opener


def layer(done, total=6 * GB, digest="sha256:aaa"):
    return {"status": f"pulling {digest[:12]}", "digest": digest, "total": total, "completed": done}


def test_it_asks_ollama_to_pull_by_name_and_says_how_far_along_it_is_about_once_a_second():
    said, seen = [], []
    ticks = iter([0.0, 0.2, 1.1, 1.3, 2.4, 2.5, 3.5])
    events = [
        {"status": "pulling manifest"},
        layer(0),
        layer(GB, digest="sha256:aaa"),
        layer(3 * GB),
        {"status": "pulling bbb", "digest": "sha256:bbb", "total": GB, "completed": 0},
        layer(6 * GB),
        {"status": "verifying sha256 digest"},
        {"status": "success"},
    ]
    pull.pull("gemma4:e4b", opened(*events, seen=seen), said.append, lambda: next(ticks))

    assert seen == [
        ("http://127.0.0.1:11434/api/pull", {"model": "gemma4:e4b", "stream": True}, 120)
    ]
    assert said == [
        "Downloading gemma4:e4b: pulling manifest",  # nothing sized yet
        "Downloading gemma4:e4b: 1.0 of 6.0 GB (16%)",  # at 1.1 s; the line at 0.2 s, skipped
        "Downloading gemma4:e4b: 3.0 of 7.0 GB (42%)",  # at 2.4 s, with a second layer
        "Downloading gemma4:e4b: 6.0 of 7.0 GB (85%)",  # at 3.5 s
        "Downloaded gemma4:e4b.",
    ]


def test_ollama_not_running_is_said_in_a_sentence():
    def down(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError())

    with pytest.raises(SystemExit, match="Ollama isn't running. Open the Ollama app"):
        pull.pull("gemma4:e4b", down, lambda text: None)


def test_a_model_ollama_hasnt_heard_of_says_so():
    def missing(request, timeout):
        body = io.BytesIO(b'{"error":"pull model manifest: file does not exist"}')
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, body)

    with pytest.raises(SystemExit) as stopped:
        pull.pull("nope:1b", missing, lambda text: None)
    assert str(stopped.value) == (
        "Ollama couldn't download nope:1b: pull model manifest: file does not exist."
    )


def test_an_error_in_the_stream_or_a_stream_that_ends_early_ends_the_download():
    with pytest.raises(SystemExit, match="couldn't download gemma4:e4b: no space left"):
        pull.pull("gemma4:e4b", opened(layer(GB), {"error": "no space left on device"}), print)
    with pytest.raises(SystemExit, match="stopped before it finished"):
        pull.pull("gemma4:e4b", opened(layer(GB)), lambda text: None)


def test_the_first_model_becomes_the_main_one_as_the_starter(monkeypatch):
    said = []
    assert config.env("MODEL") == ""
    pull.use("gemma4:e4b", None, said.append)
    assert config.env("MODEL") == "ollama:gemma4:e4b"
    assert config.env("FAST_MODEL") == ""  # the starter has no smaller one to hand the jobs to
    assert said == ["Using gemma4:e4b as the main model."]


def test_with_a_model_set_and_no_choice_it_only_downloads():
    config.save_setting("MODEL", "ollama:gemma4:e4b")
    pull.use("gemma4:26b", None)
    assert config.env("MODEL") == "ollama:gemma4:e4b"


def test_as_main_the_small_model_it_replaces_keeps_the_light_jobs():
    config.save_setting("MODEL", "ollama:gemma4:e4b")
    said = []
    pull.use("gemma4:26b", "main", said.append)
    assert config.env("MODEL") == "ollama:gemma4:26b"
    assert config.env("FAST_MODEL") == "ollama:gemma4:e4b"
    assert said[-1] == "gemma4:e4b keeps doing the light jobs."


def test_as_main_leaves_a_fast_model_already_chosen_and_one_that_isnt_ollamas():
    config.save_setting("MODEL", "ollama:gemma4:e4b")
    config.save_setting("FAST_MODEL", "off")
    pull.use("gemma4:26b", "main")
    assert config.env("FAST_MODEL") == "off"

    config.save_setting("FAST_MODEL", "")
    config.save_setting("MODEL", "local:qwen3-8b")
    pull.use("gemma4:26b", "main")
    assert config.env("MODEL") == "ollama:gemma4:26b" and config.env("FAST_MODEL") == ""


def test_the_model_in_use_by_default_counts_as_the_one_replaced(monkeypatch):
    monkeypatch.setattr(llm, "default", lambda: "ollama:gemma4:e4b")  # none set, one pulled
    pull.use("gemma4:26b", "main")
    assert config.env("FAST_MODEL") == "ollama:gemma4:e4b"


def test_the_command_pulls_then_uses_the_model_and_takes_options_before_a_double_dash(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    monkeypatch.setattr(pull.urllib.request, "urlopen", opened({"status": "success"}))
    config.save_setting("MODEL", "ollama:gemma4:e4b")
    cli.main(["model", "pull", "--as", "main", "--", "ollama:gemma4:26b"])
    assert config.env("MODEL") == "ollama:gemma4:26b"
    assert config.env("FAST_MODEL") == "ollama:gemma4:e4b"
    assert capsys.readouterr().out.splitlines()[0] == "Downloaded gemma4:26b."


@pytest.mark.parametrize("name", [None, "", "two words", "x;rm", "a" * 201])
def test_a_name_that_isnt_a_models_is_refused_before_anything_is_asked(name, monkeypatch):
    monkeypatch.setattr(pull, "pull", lambda *a, **k: pytest.fail("asked Ollama"))
    with pytest.raises(SystemExit, match="Name the model"):
        pull.run(argparse.Namespace(name=name, use=None))


def test_pull_is_one_of_the_model_commands():
    parser = argparse.ArgumentParser()
    fastmodel.add_arguments(parser)
    args = parser.parse_args(["pull", "gemma4:e4b", "--as", "starter"])
    assert (args.action, args.name, args.use) == ("pull", "gemma4:e4b", "starter")
