"""`proxenos setup`: the page's first-run setup and Settings. A made-up person, a vault under
tmp_path, conftest's fake Keychain, and Anthropic and Ollama faked out."""

import io
import json
import os
import stat

import anthropic
import httpx2
import pytest

from proxenos import cli, config, setup

KEY = "sk-ant-api03-" + "k" * 40
SECRET = "s3cret-value-that-must-never-show"


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
    assert status["vault"] == {"path": "~/proxenos_vault", "exists": False, "cloud": None}
    assert status["model"] == {"kind": "none", "name": "claude-opus-5-5"}
    assert status["saves_to"] == "settings"
    assert {s["name"] for s in status["secrets"]} == set(setup.SECRETS)
    assert not any(s["set"] for s in status["secrets"])

    result = apply({"settings": {"name": "Ana Lee", "vault": "~/Records"}})

    assert result["ok"], result
    assert result["status"]["needed"] is False
    assert result["status"]["settings"]["name"] == {"value": "Ana Lee", "from": "settings"}
    assert result["status"]["vault"] == {"path": "~/Records", "exists": True, "cloud": None}
    assert os.name == "nt" or stat.S_IMODE((home / "Records").stat().st_mode) == 0o700
    assert json.loads(config.SETTINGS_FILE.read_text()) == {"name": "Ana Lee", "vault": "~/Records"}


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

    assert "Not a setting" in apply({"settings": {"anthropic_api_key": "x"}})["error"]
    assert "one line" in apply({"settings": {"name": "Ana\nPROXENOS_VAULT=/"}})["error"]


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
    assert result["status"]["model"] == {"kind": "api", "name": "claude-opus-5-5"}
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


def test_a_local_model_must_be_running_and_pulled(home, monkeypatch):
    assert "isn't running" in apply({"ollama": "gemma4:26b"})["error"]

    monkeypatch.setattr(setup, "_ollama_models", lambda: ["gemma4:26b", "qwen3-embedding:0.6b"])
    assert "ollama pull qwen3:8b" in apply({"ollama": "qwen3:8b"})["error"]
    result = apply({"ollama": "gemma4:26b"})

    assert result["ok"] and config.env("MODEL") == "ollama:gemma4:26b"
    assert result["status"]["model"] == {"kind": "local", "name": "gemma4:26b"}
    assert result["status"]["ollama"] == {"running": True, "models": ["gemma4:26b"]}


def test_secrets_are_replaced_and_removed_and_never_shown(home, fake_keychain, monkeypatch):
    for name in ("GMAIL_PERSONAL", "SLACK_USER_TOKEN_acme", "STRAVA_CLIENT_SECRET"):
        monkeypatch.setenv(name, f"x-{SECRET}")

    replaced = apply({"secret": "BEEPER_ACCESS_TOKEN", "value": SECRET})
    assert replaced["ok"] and replaced["message"] == "Saved BEEPER_ACCESS_TOKEN in the Keychain."
    shown = {s["name"]: (s["set"], s["from"]) for s in replaced["status"]["secrets"]}
    assert shown["BEEPER_ACCESS_TOKEN"] == (True, "keychain")
    assert shown["GMAIL_PERSONAL"] == shown["SLACK_USER_TOKEN_acme"] == (True, "environment")
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
    assert env.read_text() == f"PROXENOS_NAME=Ana\nPROXENOS_VAULT=~/v\nANTHROPIC_API_KEY={KEY}\n"
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
