"""Settings are read as PROXENOS_<NAME>, with the older TWIN_<NAME> as a fallback."""

import json
import os

import pytest

from proxenos import config


def test_the_new_name_wins_over_the_old_one(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("TWIN_NAME", "Old")
    assert config.env("NAME") == "Tess"
    assert config.env_key("NAME") == "PROXENOS_NAME"


def test_the_old_name_is_read_until_the_new_one_is_set(monkeypatch):
    monkeypatch.setenv("TWIN_NAME", "Old")
    assert config.env("NAME") == "Old"
    assert config.env_key("NAME") == "TWIN_NAME"


def test_neither_set_gives_the_default_and_the_new_name(monkeypatch):
    assert config.env("NAME", "the person") == "the person"
    assert config.env_key("NAME") == "PROXENOS_NAME"


def test_an_empty_new_value_still_counts_as_set(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "")
    monkeypatch.setenv("TWIN_NAME", "Old")
    assert config.env("NAME", "the person") == ""


def test_the_vault_defaults_to_proxenos_vault_and_reads_either_name(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("PROXENOS_VAULT")  # conftest's, so none is set
    assert config.vault_path() == (tmp_path / "proxenos_vault").resolve()
    monkeypatch.setenv("TWIN_VAULT", str(tmp_path / "old"))
    assert config.vault_path() == (tmp_path / "old").resolve()
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "new"))
    assert config.vault_path() == (tmp_path / "new").resolve()


def _client_file(tmp_path, client_id="shipped-id", client_secret="shipped-secret"):
    path = tmp_path / "google.json"
    path.write_text(
        json.dumps({"installed": {"client_id": client_id, "client_secret": client_secret}})
    )
    return path


def test_the_apps_google_client_is_the_last_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("PROXENOS_GOOGLE_CLIENT", str(_client_file(tmp_path)))
    assert config.origin("GOOGLE_CLIENT_ID") == "app"
    assert os.environ["GOOGLE_CLIENT_ID"] == "shipped-id"
    assert os.environ["GOOGLE_CLIENT_SECRET"] == "shipped-secret"
    assert config.origin("GOOGLE_CLIENT_SECRET") == "app"


def test_a_client_of_the_users_own_wins_over_the_apps(monkeypatch, tmp_path, fake_keychain):
    monkeypatch.setenv("PROXENOS_GOOGLE_CLIENT", str(_client_file(tmp_path)))
    config.save_secret("GOOGLE_CLIENT_ID", "mine")
    config.save_secret("GOOGLE_CLIENT_SECRET", "mine-too")
    monkeypatch.setattr("proxenos.config._loaded", False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    config.load()
    assert os.environ["GOOGLE_CLIENT_ID"] == "mine"
    assert config.origin("GOOGLE_CLIENT_SECRET") == "keychain"


def test_half_a_set_client_is_never_completed_from_the_apps(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "mine")
    monkeypatch.setenv("PROXENOS_GOOGLE_CLIENT", str(_client_file(tmp_path)))
    assert config.origin("GOOGLE_CLIENT_ID") == "environment"
    assert "GOOGLE_CLIENT_SECRET" not in os.environ


# A Web application client's file is refused too: its sign-in would fail at Google.
WEB = '{"web": {"client_id": "x", "client_secret": "y"}}'


@pytest.mark.parametrize("body", ["not json", '{"installed": {"client_id": "x"}}', "[]", WEB])
def test_a_client_file_that_isnt_one_is_ignored(monkeypatch, tmp_path, body):
    path = tmp_path / "bad.json"
    path.write_text(body)
    monkeypatch.setenv("PROXENOS_GOOGLE_CLIENT", str(path))
    assert config.origin("GOOGLE_CLIENT_ID") is None
    monkeypatch.setenv("PROXENOS_GOOGLE_CLIENT", str(tmp_path / "missing.json"))
    monkeypatch.setattr("proxenos.config._loaded", False)
    assert config.origin("GOOGLE_CLIENT_ID") is None
