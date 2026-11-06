"""A model the app runs itself: downloading it, setting it, serving it. No model, no network."""

import threading

import pytest

from proxenos import config, fastmodel, llm, localmodel, setup

SMALL, BIG = localmodel.SMALL, localmodel.BIG


def put(repo, incomplete=False):
    """A download of `repo` in the (test's own) Hugging Face cache."""
    folder = fastmodel.cache_folder(repo)
    (folder / "blobs").mkdir(parents=True, exist_ok=True)
    snapshot = folder / "snapshots" / "abc"
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "config.json").write_text("{}")
    if incomplete:
        (folder / "blobs" / "aaa.incomplete").write_text("part")


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(fastmodel, "capable", lambda *a, **k: True)


def test_the_catalog_and_the_ports_name_the_same_models():
    assert set(localmodel.CATALOG) == set(llm.HERE_PORTS)
    assert SMALL == fastmodel.BASE and llm.HERE_PORTS[SMALL] == llm.FAST_PORT
    assert llm.HERE_PORTS[BIG] not in (llm.FAST_PORT, llm.VOICE_PORT)


def test_a_download_says_how_far_along_it_is_and_is_done_when_the_weights_are_whole(
    mac, monkeypatch
):
    state = {"done": 0}
    said, seen40 = [], threading.Event()
    monkeypatch.setattr(localmodel, "_downloaded", lambda repo: state["done"])

    def fetch(repo, progress):
        assert repo == SMALL
        state["done"] = 2_100_000_000
        assert seen40.wait(5)
        state["done"] = 5_200_000_000
        put(SMALL)

    def say(line):
        said.append(line)
        if line == "Downloading Gemma 4 E4B: 2.1 of 5.2 GB (40%)":
            seen40.set()

    localmodel.get(SMALL, say, fetch, every=0.01)
    assert "Downloading Gemma 4 E4B: 2.1 of 5.2 GB (40%)" in said
    assert said[-1] == "Downloaded Gemma 4 E4B."


def test_a_download_that_fails_or_stops_short_is_said_in_a_sentence(mac, monkeypatch):
    monkeypatch.setattr(localmodel, "_downloaded", lambda repo: 0)

    def breaks(repo, progress):
        raise OSError("no route to host")

    with pytest.raises(SystemExit, match="Couldn't download Gemma 4 E4B: no route to host"):
        localmodel.get(SMALL, lambda line: None, breaks, every=0.01)

    def partial(repo, progress):
        put(repo, incomplete=True)

    with pytest.raises(SystemExit, match="stopped before it finished"):
        localmodel.get(SMALL, lambda line: None, partial, every=0.01)


def test_only_the_catalogs_models_on_a_mac_with_mlx_are_downloaded(monkeypatch):
    with pytest.raises(SystemExit, match="serves"):
        localmodel.get("someone/else", lambda line: None)
    with pytest.raises(SystemExit, match="Apple silicon"):
        localmodel.get(SMALL, lambda line: None)  # conftest: not capable


def test_the_starter_is_the_main_and_the_fast_model_served_here(monkeypatch):
    said = []
    localmodel.use(SMALL, None, said.append)
    assert config.env("MODEL") == llm.SERVER + SMALL == config.env("FAST_MODEL")
    assert llm.served_here() == [SMALL]
    assert said == ["Using Gemma 4 E4B as the main model."]
    assert llm._url_for(llm.SERVER + SMALL) == "http://127.0.0.1:8898/v1"

    localmodel.use(BIG, None, said.append)  # a model is set, and no --as: nothing changes
    assert config.env("MODEL") == llm.SERVER + SMALL
    with pytest.raises(SystemExit, match="small model"):
        localmodel.use(BIG, "starter", said.append)


def test_the_big_one_is_the_main_and_the_small_one_keeps_the_light_jobs(monkeypatch):
    put(SMALL)
    localmodel.use(BIG, "main", lambda line: None)
    assert config.env("MODEL") == llm.SERVER + BIG
    assert config.env("FAST_MODEL") == llm.SERVER + SMALL
    assert llm.served_here() == [BIG, SMALL]
    assert llm._url_for(llm.SERVER + BIG) == f"http://127.0.0.1:{llm.HERE_PORTS[BIG]}/v1"
    assert config.read_settings()["served_here"] == f"{BIG},{SMALL}"

    # Without the small one downloaded, the light jobs stay as they were.
    config.save_setting("FAST_MODEL", "ollama:gemma4:e4b")
    config.save_setting("SERVED_HERE", "")
    for name in (SMALL,):
        for path in fastmodel.cache_folder(name).rglob("config.json"):
            path.unlink()
    localmodel.use(BIG, "main", lambda line: None)
    assert config.env("FAST_MODEL") == "ollama:gemma4:e4b"
    assert llm.served_here() == [BIG]


def test_another_servers_models_and_unknown_repos_never_get_the_apps_ports(monkeypatch):
    monkeypatch.setenv("PROXENOS_SERVED_HERE", f"someone/else, {SMALL}")
    assert llm.served_here() == [SMALL]
    monkeypatch.setenv("PROXENOS_MODEL", "local:qwen3-8b")
    assert llm._url_for("local:qwen3-8b") is None  # LM Studio's, at PROXENOS_LOCAL_URL


def test_the_models_to_serve_are_those_named_whose_weights_are_whole(mac, monkeypatch):
    config.save_setting("SERVED_HERE", f"{BIG},{SMALL},someone/else")
    put(SMALL)
    put(BIG, incomplete=True)
    assert localmodel.wanted() == [SMALL]
    for blob in (fastmodel.cache_folder(BIG) / "blobs").iterdir():
        blob.unlink()
    put(BIG)
    assert localmodel.wanted() == [BIG, SMALL]  # read afresh, in the order named


class Child:
    def __init__(self, command, env):
        self.command, self.env, self.returncode = command, env, None
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped, self.returncode = True, 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.terminate()


class Ticks(threading.Event):
    """An event whose waits are the loop's turns: `then` runs after each, and the n-th stops it."""

    def __init__(self, turns):
        super().__init__()
        self.turns, self.count = turns, 0

    def wait(self, timeout=None):
        self.count += 1
        if self.count in self.turns:
            self.turns[self.count]()
        if self.count >= max(self.turns):
            self.set()
        return self.is_set()


def test_a_server_runs_for_each_model_named_follows_changes_and_stops_with_the_app(
    mac, monkeypatch
):
    put(SMALL)
    put(BIG)
    config.save_setting("SERVED_HERE", f"{BIG},{SMALL}")
    started, now = [], {"t": 0.0}

    def popen(command, env):
        child = Child(command, env)
        started.append(child)
        return child

    turns = {
        1: lambda: config.save_setting("SERVED_HERE", SMALL),  # the big one is dropped
        2: lambda: setattr(started[1], "returncode", 1),  # the small one's server dies...
        3: lambda: now.update(t=100.0),  # ...and is started again after a wait
        4: lambda: None,
    }
    localmodel.serve_app(Ticks(turns), popen, poll=0, restart=30, clock=lambda: now["t"])

    big, small, again = started
    assert big.stopped  # dropped from the settings
    assert big.command[big.command.index("--model") + 1] == BIG
    assert big.command[big.command.index("--port") + 1] == str(llm.HERE_PORTS[BIG])
    assert big.command[big.command.index("--host") + 1] == "127.0.0.1"
    assert big.env["HF_HUB_OFFLINE"] == "1"
    assert small.command[small.command.index("--port") + 1] == "8898"
    assert again.command == small.command and again.stopped  # stopped at the end


def test_nothing_is_served_where_this_cant_run_it(capsys):
    localmodel.serve_app(Ticks({1: lambda: None}), lambda *a, **k: pytest.fail("started"))
    assert "nothing to serve" in capsys.readouterr().out


def test_setup_says_what_the_app_can_run_and_that_the_model_is_served_here(mac, monkeypatch):
    monkeypatch.setattr(setup.machine, "memory", lambda: 32 * 2**30)
    put(SMALL)
    localmodel.use(SMALL, "starter", lambda line: None)
    status = setup.status()
    assert status["model"]["via"] == "app"
    # People read the friendly name; the id stays in `name`.
    assert status["model"]["name"] == SMALL and status["model"]["label"] == "Gemma 4 E4B"
    assert status["fast"]["suggested_label"] == "Gemma 4 E4B"
    here = status["here"]
    assert here["capable"] is True
    assert here["small"] | {"bytes": 0} == {
        "repo": SMALL,
        "name": "Gemma 4 E4B",
        "bytes": 0,
        "ready": True,
        "serving": True,
    }
    assert here["big"]["fits"] is True and here["big"]["ready"] is False
    monkeypatch.setattr(setup.machine, "memory", lambda: 16 * 2**30)
    assert setup.status()["here"]["big"]["fits"] is False


def test_get_and_serve_app_are_model_actions(monkeypatch):
    import argparse

    parser = argparse.ArgumentParser()
    fastmodel.add_arguments(parser)
    seen = []
    monkeypatch.setattr(localmodel, "get", lambda repo, *a, **k: seen.append(("get", repo)))
    monkeypatch.setattr(localmodel, "use", lambda repo, how, *a: seen.append(("use", repo, how)))
    monkeypatch.setattr(localmodel, "serve_app", lambda: seen.append("serve"))
    args = parser.parse_args(["get", f"local:{SMALL}", "--as", "starter"])
    fastmodel.run(None, args)
    fastmodel.run(None, parser.parse_args(["serve-app"]))
    assert seen == [("get", SMALL), ("use", SMALL, "starter"), "serve"]
