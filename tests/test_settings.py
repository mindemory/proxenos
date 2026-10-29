"""Where settings and secrets are read from and saved to: the environment, .env, the settings
file and the Keychain. The Keychain is conftest's fake; nothing here touches the real one."""

import json
import os
import stat
import sys
from pathlib import Path

import dotenv
import pytest

from proxenos import config, keychain


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """A checkout's .env, read for real (conftest stubs the reader out)."""
    path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", path)
    monkeypatch.setattr(config, "load_dotenv", dotenv.load_dotenv)
    return path


def restart(monkeypatch, *names):
    """As a new process would start: nothing loaded yet, and none of `names` in its environment."""
    monkeypatch.setattr(config, "_loaded", False)
    monkeypatch.setattr(config, "_origin", {})
    for name in names:
        monkeypatch.delenv(name, raising=False)


def write_settings(settings):
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text(json.dumps(settings))


def test_the_environment_then_env_then_settings_then_the_keychain(
    env_file, monkeypatch, fake_keychain
):
    env_file.write_text("PROXENOS_NAME=From Env File\nANTHROPIC_API_KEY=sk-ant-from-env-file\n")
    write_settings(
        {"name": "From Settings", "model": "ollama:gemma4:26b", "keychain": ["ANTHROPIC_API_KEY"]}
    )
    fake_keychain.items["ANTHROPIC_API_KEY"] = "sk-ant-from-keychain"
    monkeypatch.setenv("PROXENOS_NAME", "From Shell")

    assert config.env("NAME") == "From Shell"
    assert config.origin("PROXENOS_NAME") == "environment"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-from-env-file"
    assert config.env("MODEL") == "ollama:gemma4:26b"
    assert config.origin("PROXENOS_MODEL") == "settings"
    assert fake_keychain.commands == []  # .env had the key, so the Keychain wasn't asked

    restart(monkeypatch, "PROXENOS_NAME", "ANTHROPIC_API_KEY", "PROXENOS_MODEL")
    assert config.env("NAME") == "From Env File"
    assert config.origin("PROXENOS_NAME") == ".env"

    restart(monkeypatch, "PROXENOS_NAME", "ANTHROPIC_API_KEY", "PROXENOS_MODEL")
    env_file.unlink()
    assert config.env("NAME") == "From Settings"
    assert config.origin("PROXENOS_NAME") == "settings"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-from-keychain"
    assert config.origin("ANTHROPIC_API_KEY") == "keychain"


def test_an_old_name_in_env_still_wins_over_the_settings_file(env_file):
    env_file.write_text("TWIN_NAME=Old Name\n")
    write_settings({"name": "From Settings"})
    assert config.env("NAME") == "Old Name"


def test_installed_it_never_reads_an_env_file(env_file, monkeypatch):
    env_file.write_text("PROXENOS_NAME=From Env File\n")
    monkeypatch.setattr(config, "ENV_FILE", None)  # as an installed package has it
    write_settings({"name": "From Settings"})
    assert config.env("NAME") == "From Settings"


def test_only_the_secrets_the_settings_file_lists_are_read_from_the_keychain(fake_keychain):
    fake_keychain.items |= {"BEEPER_ACCESS_TOKEN": "listed", "STRAVA_REFRESH_TOKEN": "not listed"}
    write_settings({"keychain": ["BEEPER_ACCESS_TOKEN", "PATH"]})  # never anything but a secret
    config.load()
    assert os.environ["BEEPER_ACCESS_TOKEN"] == "listed"
    assert "STRAVA_REFRESH_TOKEN" not in os.environ
    assert [c[4] for c in fake_keychain.commands] == ["BEEPER_ACCESS_TOKEN"]


def test_a_keychain_that_wont_answer_is_said_and_the_rest_still_loads(monkeypatch, capsys):
    write_settings({"name": "Ana Lee", "keychain": ["BEEPER_ACCESS_TOKEN"]})

    def locked(args, stdin=None):
        return keychain.subprocess.CompletedProcess(
            args, 51, "", "User interaction is not allowed."
        )

    monkeypatch.setattr(keychain, "_security", locked)
    assert config.env("NAME") == "Ana Lee"
    assert "BEEPER_ACCESS_TOKEN" not in os.environ
    assert "User interaction is not allowed" in capsys.readouterr().err


def test_without_env_a_secret_goes_to_the_keychain_and_only_its_name_to_settings(
    monkeypatch, fake_keychain
):
    secret = "tok-0123456789abcdef"
    assert config.save_secret("BEEPER_ACCESS_TOKEN", secret) == "the Keychain"

    assert fake_keychain.items == {"BEEPER_ACCESS_TOKEN": secret}
    settings = config.SETTINGS_FILE.read_text()
    assert json.loads(settings) == {"keychain": ["BEEPER_ACCESS_TOKEN"]}
    assert stat.S_IMODE(config.SETTINGS_FILE.stat().st_mode) == 0o600
    assert stat.S_IMODE(config.SETTINGS_FILE.parent.stat().st_mode) == 0o700
    assert os.environ["BEEPER_ACCESS_TOKEN"] == secret
    # Never on a command line: written through `security -i`'s stdin, as hex.
    for command in fake_keychain.commands:
        assert secret not in " ".join(command) and secret.encode().hex() not in " ".join(command)

    restart(monkeypatch, "BEEPER_ACCESS_TOKEN")
    config.load()
    assert os.environ["BEEPER_ACCESS_TOKEN"] == secret


def test_from_source_with_env_a_secret_goes_there(env_file, fake_keychain):
    env_file.write_text("PROXENOS_NAME=Ana\n")
    assert config.save_secret("GMAIL_WORK", "ana@acme.example:oauth:r1") == ".env"
    assert env_file.read_text() == "PROXENOS_NAME=Ana\nGMAIL_WORK=ana@acme.example:oauth:r1\n"
    assert not fake_keychain.items and not config.SETTINGS_FILE.exists()


def test_with_no_keychain_from_source_makes_env_and_installed_refuses(env_file, monkeypatch):
    monkeypatch.setattr(keychain, "available", lambda: False)
    assert config.save_secret("STRAVA_REFRESH_TOKEN", "r1") == ".env"
    assert env_file.read_text() == "STRAVA_REFRESH_TOKEN=r1\n"

    monkeypatch.setattr(config, "ENV_FILE", None)
    with pytest.raises(SystemExit, match="no Keychain"):
        config.save_secret("STRAVA_REFRESH_TOKEN", "r2")


@pytest.mark.parametrize(
    ("name", "value"),
    [("PATH", "/bin"), ("PROXENOS_NAME", "x"), ("ANTHROPIC_API_KEY", "a\nB=1"), ("GMAIL_X", "")],
)
def test_only_secrets_and_one_line_values_are_saved(name, value, fake_keychain):
    with pytest.raises(ValueError):
        config.save_secret(name, value)
    assert not fake_keychain.items


def test_forgetting_a_secret_removes_it_from_the_keychain_and_env(env_file, fake_keychain):
    config.save_secret("BEEPER_ACCESS_TOKEN", "tok-1")  # no .env yet: the Keychain
    env_file.write_text("A=1\nBEEPER_ACCESS_TOKEN=tok-2\n")

    assert config.forget_secret("BEEPER_ACCESS_TOKEN")
    assert not fake_keychain.items
    assert json.loads(config.SETTINGS_FILE.read_text()) == {"keychain": []}
    assert env_file.read_text() == "A=1\n"
    assert "BEEPER_ACCESS_TOKEN" not in os.environ
    assert not config.forget_secret("BEEPER_ACCESS_TOKEN")


def test_a_secret_from_the_environment_stays(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-the-shell")
    assert not config.forget_secret("ANTHROPIC_API_KEY")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-from-the-shell"


def test_settings_go_to_the_settings_file_or_env_and_empty_removes_them(env_file, monkeypatch):
    assert config.save_setting("NAME", "Ana Lee") == "settings"
    assert config.save_setting("DOCS_DIRS", "~/Health, ~/Scans") == "settings"
    assert json.loads(config.SETTINGS_FILE.read_text()) == {
        "name": "Ana Lee",
        "docs_dirs": "~/Health, ~/Scans",
    }
    assert config.env("NAME") == "Ana Lee"
    config.save_setting("DOCS_DIRS", "")
    assert json.loads(config.SETTINGS_FILE.read_text()) == {"name": "Ana Lee"}
    assert config.env("DOCS_DIRS") == ""

    env_file.write_text("TWIN_VAULT=~/old\n")
    assert config.save_setting("VAULT", "~/Notes #2") == ".env"
    assert dotenv.dotenv_values(env_file)["PROXENOS_VAULT"] == "~/Notes #2"
    config.save_setting("VAULT", "")
    assert env_file.read_text() == ""
    assert config.env("VAULT", "default") == "default"


def test_keychain_items_are_read_back_after_saving(fake_keychain, monkeypatch):
    def forgets(args, stdin=None):
        return keychain.subprocess.CompletedProcess(args, 0 if args == ["-i"] else 44, "", "")

    monkeypatch.setattr(keychain, "_security", forgets)
    with pytest.raises(keychain.KeychainError, match="didn't save"):
        keychain.put("ANTHROPIC_API_KEY", "sk-ant-x")
    with pytest.raises(keychain.KeychainError, match="isn't a variable's name"):
        keychain.get("-a evil")


def test_on_a_mac_settings_are_in_application_support(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    expected = Path.home() / "Library" / "Application Support" / "Proxenos" / "settings.json"
    assert config.settings_file() == expected


def test_on_windows_settings_are_in_appdata(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\Ana Lee\AppData\Roaming")
    expected = Path(r"C:\Users\Ana Lee\AppData\Roaming") / "Proxenos" / "settings.json"
    assert config.settings_file() == expected
    monkeypatch.delenv("APPDATA")
    expected = Path.home() / "AppData" / "Roaming" / "Proxenos" / "settings.json"
    assert config.settings_file() == expected


def test_on_linux_settings_follow_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert config.settings_file() == tmp_path / "config" / "proxenos" / "settings.json"
    default = Path.home() / ".config" / "proxenos" / "settings.json"
    for unusable in ("", "relative/config"):  # the spec says to ignore both
        monkeypatch.setenv("XDG_CONFIG_HOME", unusable)
        assert config.settings_file() == default
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config.settings_file() == default


def test_on_windows_the_folder_keeps_files_private_and_nothing_is_chmodded(monkeypatch, env_file):
    def chmod(*args, **kwargs):
        raise AssertionError("a mode on Windows is only the read-only flag")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "chmod", chmod)
    assert config.save_setting("NAME", "Ana Lee") == "settings"
    assert json.loads(config.SETTINGS_FILE.read_text()) == {"name": "Ana Lee"}
    env_file.write_text("A=1\n")
    config.save_setting("NAME", "Ana")
    assert env_file.read_text() == "A=1\nPROXENOS_NAME=Ana\n"
