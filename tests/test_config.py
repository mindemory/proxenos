"""Settings are read as PROXENOS_<NAME>, with the older TWIN_<NAME> as a fallback."""

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
    assert config.vault_path() == (tmp_path / "proxenos_vault").resolve()
    monkeypatch.setenv("TWIN_VAULT", str(tmp_path / "old"))
    assert config.vault_path() == (tmp_path / "old").resolve()
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "new"))
    assert config.vault_path() == (tmp_path / "new").resolve()
