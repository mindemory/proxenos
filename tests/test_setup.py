"""`proxenos setup`: the page's first-run setup and Settings. A made-up person, a vault under
tmp_path, conftest's fake Keychain, and Anthropic, Ollama and other model servers faked out."""

import io
import json
import os
import stat
from pathlib import Path

import anthropic
import httpx2
import pytest

from proxenos import cli, config, setup

KEY = "sk-ant-api03-" + "k" * 40
SECRET = "s3cret-value-that-must-never-show"
_real_server_models = setup._server_models  # conftest stands it in for every test; one tests it


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder of its own, so ~ and the iCloud folders are under tmp_path."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture
def anthropic_says(monkeypatch):
    """What Anthropic answers when a key is checked: None for yes, or an error to raise."""
    asked = []
    answer = {"error": None}

    class Models:
        def retrieve(self, model):
            asked.append(model)
            if answer["error"]:
                raise answer["error"]
            return {"id": model}

    class Client:
        def __init__(self, **kwargs):
            asked.append(kwargs)
            self.models = Models()

    monkeypatch.setattr(setup.anthropic, "Anthropic", Client)
    return asked, answer


def apply(request):
    result = setup.apply(request)
    assert SECRET not in json.dumps(result) and KEY not in json.dumps(result)
    return result


def test_a_first_run_is_needed_until_a_name_or_vault_is_set(home):
    status = setup.status()
    assert status["needed"] is True
    # Shown with the platform's separator: ~/proxenos_vault, or ~\\proxenos_vault on Windows.
    assert {**status["vault"], "path": Path(status["vault"]["path"])} == {
        "path": Path("~/proxenos_vault"),
        "exists": False,
        "cloud": None,
    }
    assert status["model"] == {"kind": "none", "name": "claude-opus-5-5", "via": None}
    assert status["saves_to"] == "settings"
    assert {s["name"] for s in status["secrets"]} == set(setup.SECRETS)
    assert not any(s["set"] for s in status["secrets"])

    result = apply({"settings": {"name": "Ana Lee", "vault": "~/Records"}})

    assert result["ok"], result
    assert result["status"]["needed"] is False
    assert result["status"]["settings"]["name"] == {"value": "Ana Lee", "from": "settings"}
    shown = result["status"]["vault"]
    assert {**shown, "path": Path(shown["path"])} == {
        "path": Path("~/Records"),
        "exists": True,
        "cloud": None,
    }
    assert os.name == "nt" or stat.S_IMODE((home / "Records").stat().st_mode) == 0o700
    saved = json.loads(config.SETTINGS_FILE.read_text())
    assert (
        saved["name"] == "Ana Lee" and Path(saved["vault"]) == Path("~/Records") and len(saved) == 2
    )


@pytest.mark.parametrize(
    ("vault", "why"),
    [
        (str(config.REPO_ROOT / "vault"), "public"),
        ("records", "whole path"),
        ("~/notes.txt", "a file"),
    ],
)
def test_a_vault_in_the_repo_relative_or_on_a_file_is_refused(home, vault, why):
    (home / "notes.txt").write_text("x")
    result = apply({"settings": {"vault": vault}})
    assert not result["ok"] and why in result["error"]
    assert not config.SETTINGS_FILE.exists()
    assert not (config.REPO_ROOT / "vault").exists()


def test_folders_icloud_syncs_are_flagged(home):
    assert setup.cloud(home / "Documents" / "vault") == "icloud"
    assert setup.cloud(home / "Desktop") == "icloud"
    assert setup.cloud(home / "Library" / "CloudStorage" / "Dropbox" / "v") == "drive"
    assert setup.cloud(home / "proxenos_vault") is None
    result = apply({"settings": {"vault": "~/Documents/vault"}})
    assert result["status"]["vault"]["cloud"] == "icloud"


def test_folder_settings_are_saved_and_missing_ones_said(home):
    (home / "Health").mkdir()
    result = apply({"settings": {"docs_dirs": "~/Health, ~/Scans", "website_repo": ""}})
    assert result["ok"]
    assert result["message"] == "Saved in your settings. Not there yet: ~/Scans."
    assert config.env("DOCS_DIRS") == "~/Health, ~/Scans"
    # The folder the projects go to, in a cloud drive, is one too (proxenos.clones.folders).
    result = apply({"settings": {"project_folder": "~/Drive/Projects"}})
    assert result["message"] == "Saved in your settings. Not there yet: ~/Drive/Projects."
    assert result["status"]["settings"]["project_folder"]["value"] == "~/Drive/Projects"

    assert "Not a setting" in apply({"settings": {"anthropic_api_key": "x"}})["error"]
    assert "one line" in apply({"settings": {"name": "Ana\nPROXENOS_VAULT=/"}})["error"]


def test_a_voice_model_is_served_here_or_in_ollama(home):
    assert apply({"settings": {"voice_model": "mlx"}})["ok"]
    assert config.env("VOICE_MODEL") == "mlx"
    assert apply({"settings": {"voice_model": "ollama:tess-voice"}})["ok"]
    assert apply({"settings": {"voice_model": "local:tess-voice@q4_k_m"}})["ok"]
    assert "A voice model is" in apply({"settings": {"voice_model": "gpt-9"}})["error"]
    assert apply({"settings": {"voice_model": ""}})["ok"]
    assert config.env("VOICE_MODEL") == ""


def test_a_key_is_checked_with_one_call_then_kept_in_the_keychain(
    home, anthropic_says, fake_keychain
):
    asked, _ = anthropic_says
    config.save_setting("MODEL", "ollama:gemma4:26b")

    result = apply({"key": f"  {KEY}\n"})

    assert result["ok"], result
    assert asked == [
        {"api_key": KEY, "base_url": "https://api.anthropic.com", "max_retries": 0, "timeout": 20},
        "claude-opus-5-5",  # the model it will use: a local model setting is dropped for it
    ]
    assert fake_keychain.items == {"ANTHROPIC_API_KEY": KEY}
    assert result["status"]["model"] == {"kind": "api", "name": "claude-opus-5-5", "via": None}
    key = next(s for s in result["status"]["secrets"] if s["name"] == "ANTHROPIC_API_KEY")
    assert key == {"name": "ANTHROPIC_API_KEY", "set": True, "from": "keychain"}
    assert KEY not in config.SETTINGS_FILE.read_text()


def test_a_key_anthropic_refuses_is_not_saved(home, anthropic_says, fake_keychain):
    _, answer = anthropic_says
    request = httpx2.Request("GET", "https://api.anthropic.com/v1/models/claude-opus-5-5")
    answer["error"] = anthropic.AuthenticationError(
        "invalid x-api-key", response=httpx2.Response(401, request=request), body=None
    )
    result = apply({"key": KEY})
    assert not result["ok"] and "didn't accept that key" in result["error"]

    answer["error"] = anthropic.APIConnectionError(request=request)
    assert "Couldn't reach Anthropic" in apply({"key": KEY})["error"]
    assert "start with sk-ant-" in apply({"key": "hello"})["error"]
    assert not fake_keychain.items and "ANTHROPIC_API_KEY" not in os.environ


GB, GIB = 10**9, 2**30


def test_a_local_model_must_be_running_and_pulled(home, monkeypatch):
    assert "isn't running" in apply({"ollama": "gemma4:26b"})["error"]

    pulled = {"gemma4:26b": 17 * GB, "big:70b": 42 * GB, "qwen3-embedding:0.6b": GB // 2}
    monkeypatch.setattr(setup, "_ollama_models", lambda: pulled)
    monkeypatch.setattr(setup.machine, "memory", lambda: 32 * GIB)
    assert "ollama pull qwen3:8b" in apply({"ollama": "qwen3:8b"})["error"]
    result = apply({"ollama": "gemma4:26b"})

    assert result["ok"] and config.env("MODEL") == "ollama:gemma4:26b"
    status = result["status"]
    assert status["model"] == {"kind": "local", "name": "gemma4:26b", "via": "ollama"}
    assert status["ollama"] == {
        "running": True,
        "models": [  # the embedding model isn't one to write with
            {"name": "big:70b", "bytes": 42 * GB, "fits": False},
            {"name": "gemma4:26b", "bytes": 17 * GB, "fits": True},
        ],
        "suggested": "gemma4:26b",
    }
    assert status["computer"]["memory"] == 32 * GIB
    assert "enough for gemma4:26b" in status["computer"]["advice"]
    assert status["computer"]["get"] == "gemma4:26b"
    assert status["server"]["running"] is False and status["server"]["models"] == []


def test_a_model_on_another_server_here_must_be_served(home, monkeypatch):
    assert config.env("LOCAL_URL") == ""
    status = setup.status()["server"]
    assert status["url"] == "http://127.0.0.1:1234/v1" and status["error"] is None
    assert "Nothing answers at http://127.0.0.1:1234/v1" in apply({"server": "qwen3-8b"})["error"]

    served = {"qwen3-8b@q4_k_m": 5 * GB, "qwen3-30b-a3b": None, "nomic-embed-text": None}
    monkeypatch.setattr(setup, "_server_models", lambda: served)
    monkeypatch.setattr(setup.machine, "memory", lambda: 16 * GIB)
    assert "doesn't have mistral" in apply({"server": "mistral"})["error"]
    result = apply({"server": "qwen3-8b@q4_k_m"})

    assert result["ok"] and config.env("MODEL") == "local:qwen3-8b@q4_k_m"
    status = result["status"]
    assert status["model"] == {"kind": "local", "name": "qwen3-8b@q4_k_m", "via": "server"}
    assert status["server"]["models"] == [
        {"name": "qwen3-30b-a3b", "bytes": None, "fits": None},  # its server didn't say its size
        {"name": "qwen3-8b@q4_k_m", "bytes": 5 * GB, "fits": True},
    ]
    assert status["server"]["suggested"] == "qwen3-8b@q4_k_m"
    assert status["server"]["context"] == 65536
    assert status["computer"]["advice"].startswith("This computer has 16 GB of memory, so get")
    assert status["computer"]["get"] is None  # gemma4:26b doesn't fit 16 GB


def test_the_servers_address_is_saved_only_when_its_this_computers(home, monkeypatch):
    assert apply({"settings": {"local_url": "http://localhost:8080/v1/"}})["ok"]
    assert config.env("LOCAL_URL") == "http://localhost:8080/v1"
    assert setup.status()["server"]["url"] == "http://localhost:8080/v1"

    refused = apply({"settings": {"local_url": "http://127.0.0.1@evil.example/v1"}})
    assert not refused["ok"] and "isn't on this computer" in refused["error"]
    assert config.env("LOCAL_URL") == "http://localhost:8080/v1"

    monkeypatch.setenv("PROXENOS_LOCAL_URL", "http://192.168.1.20:1234/v1")  # set by hand
    server = setup.status()["server"]
    assert (
        server["url"] == "http://192.168.1.20:1234/v1"
        and "isn't on this computer" in (server["error"])
    )
    assert "isn't on this computer" in apply({"server": "qwen3-8b"})["error"]


def test_the_servers_models_are_read_from_its_list_with_sizes_where_it_says(monkeypatch):
    asked = []
    listed = {
        "object": "list",
        "data": [
            {"id": "gemma-3-12b-it-Q4_K_M.gguf", "object": "model", "meta": {"size": 7 * GB}},
            {"id": "qwen3-8b", "object": "model", "owned_by": "organization_owner"},
        ],
    }

    def opened(url, timeout):
        asked.append((url, timeout))
        return io.BytesIO(json.dumps(listed).encode())

    monkeypatch.setattr(setup.llm, "_direct", opened)
    assert _real_server_models() == {"gemma-3-12b-it-Q4_K_M.gguf": 7 * GB, "qwen3-8b": None}
    assert asked == [("http://127.0.0.1:1234/v1/models", 2)]

    monkeypatch.setenv("PROXENOS_LOCAL_URL", "http://example.com/v1")
    assert _real_server_models() is None and len(asked) == 1  # never asked another host


def test_secrets_are_replaced_and_removed_and_never_shown(home, fake_keychain, monkeypatch):
    for name in ("GMAIL_PERSONAL", "SLACK_USER_TOKEN_ACME", "STRAVA_CLIENT_SECRET"):
        monkeypatch.setenv(name, f"x-{SECRET}")

    replaced = apply({"secret": "BEEPER_ACCESS_TOKEN", "value": SECRET})
    assert replaced["ok"] and replaced["message"] == "Saved BEEPER_ACCESS_TOKEN in the Keychain."
    shown = {s["name"]: (s["set"], s["from"]) for s in replaced["status"]["secrets"]}
    assert shown["BEEPER_ACCESS_TOKEN"] == (True, "keychain")
    assert shown["GMAIL_PERSONAL"] == shown["SLACK_USER_TOKEN_ACME"] == (True, "environment")
    assert shown["STRAVA_REFRESH_TOKEN"] == (False, None)

    removed = apply({"forget": "BEEPER_ACCESS_TOKEN"})
    assert removed["ok"] and not fake_keychain.items
    kept = apply({"forget": "GMAIL_PERSONAL"})
    assert "environment" in kept["message"]
    assert not apply({"forget": "PATH"})["ok"]
    assert not apply({"secret": "HOME", "value": "/"})["ok"]


def test_from_source_with_env_changes_go_there(home, tmp_path, monkeypatch, anthropic_says):
    env = tmp_path / ".env"
    env.write_text("PROXENOS_NAME=Ana\n")
    monkeypatch.setattr(config, "ENV_FILE", env)

    assert apply({"settings": {"vault": "~/v"}})["message"] == "Saved in .env."
    assert apply({"key": KEY})["ok"]
    assert (
        env.read_text()
        == f"PROXENOS_NAME=Ana\nPROXENOS_VAULT=~{os.sep}v\nANTHROPIC_API_KEY={KEY}\n"
    )
    assert setup.status()["saves_to"] == ".env"


def test_the_command_reads_one_change_on_stdin_and_prints_json(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"settings": {"name": "Ana Lee"}})))
    cli.main(["setup", "--apply"])
    assert json.loads(capsys.readouterr().out)["status"]["settings"]["name"]["value"] == "Ana Lee"

    cli.main(["setup"])
    assert json.loads(capsys.readouterr().out)["needed"] is False

    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    cli.main(["setup", "--apply"])
    assert json.loads(capsys.readouterr().out) | {"status": None} == {
        "ok": False,
        "error": "Nothing to change.",
        "status": None,
    }
