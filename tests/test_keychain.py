"""Each platform's secure store: `security` on a Mac, keyring's Windows Credential Manager and
Secret Service elsewhere. Every store here is a fake: conftest's FakeSecurity and FakeKeyring, or
stand-ins for keyring's modules. Nothing touches a real keychain or credential store."""

import json
import sys
import threading
import types

import pytest

from proxenos import config, keychain

# conftest fakes these for every test; the tests of them take the real ones back.
AVAILABLE, KEYRING = keychain.available, keychain._keyring
ELSEWHERE = [("win32", "Credential Manager"), ("linux", "Secret Service")]


@pytest.fixture
def real_available(monkeypatch):
    monkeypatch.setattr(keychain, "available", AVAILABLE)


def on(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)


def test_on_a_mac_only_security_is_used(monkeypatch, real_available, fake_keychain, fake_keyring):
    on(monkeypatch, "darwin")

    def no_keyring():
        raise AssertionError("keyring on a Mac")

    monkeypatch.setattr(keychain, "_keyring", no_keyring)
    monkeypatch.setattr(keychain.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert keychain.available() and keychain.store() == "Keychain"

    keychain.put("ANTHROPIC_API_KEY", "sk-ant-x")
    assert keychain.get("ANTHROPIC_API_KEY") == "sk-ant-x"
    assert keychain.delete("ANTHROPIC_API_KEY") and not keychain.delete("ANTHROPIC_API_KEY")
    assert fake_keychain.commands and not fake_keyring.items

    monkeypatch.setattr(keychain.shutil, "which", lambda name: None)
    assert not keychain.available()


@pytest.mark.parametrize(("platform", "store"), ELSEWHERE)
def test_elsewhere_keyring_keeps_each_secret_under_proxenos(
    monkeypatch, real_available, fake_keychain, fake_keyring, platform, store
):
    on(monkeypatch, platform)
    assert keychain.available() and keychain.store() == store

    assert keychain.get("BEEPER_ACCESS_TOKEN") is None
    keychain.put("BEEPER_ACCESS_TOKEN", "tok-1")
    keychain.put("BEEPER_ACCESS_TOKEN", "tok-2")
    assert fake_keyring.items == {("Proxenos", "BEEPER_ACCESS_TOKEN"): "tok-2"}
    assert keychain.get("BEEPER_ACCESS_TOKEN") == "tok-2"
    assert keychain.delete("BEEPER_ACCESS_TOKEN")
    assert not keychain.delete("BEEPER_ACCESS_TOKEN")
    assert not fake_keyring.items and not fake_keychain.commands  # `security` never ran

    with pytest.raises(keychain.KeychainError, match="isn't a variable's name"):
        keychain.get("-a evil")
    with pytest.raises(keychain.KeychainError, match="nothing to save"):
        keychain.put("BEEPER_ACCESS_TOKEN", "")


@pytest.mark.parametrize(("platform", "store"), ELSEWHERE)
def test_with_no_store_it_says_so_as_a_mac_without_security_does(
    monkeypatch, real_available, tmp_path, platform, store
):
    on(monkeypatch, platform)
    monkeypatch.setattr(keychain, "_keyring", lambda: None)
    assert not keychain.available()
    with pytest.raises(keychain.KeychainError, match=f"the {store} didn't give .*reached"):
        keychain.get("ANTHROPIC_API_KEY")

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)  # from source: .env instead
    assert config.save_secret("STRAVA_REFRESH_TOKEN", "r1") == ".env"
    assert env_file.read_text() == "STRAVA_REFRESH_TOKEN=r1\n"
    monkeypatch.setattr(config, "ENV_FILE", None)  # installed: nowhere to keep it
    with pytest.raises(SystemExit, match=f"There's no {store} here"):
        config.save_secret("STRAVA_REFRESH_TOKEN", "r2")


def test_on_windows_config_keeps_secrets_in_credential_manager(
    monkeypatch, real_available, fake_keyring
):
    on(monkeypatch, "win32")
    assert config.save_secret("ANTHROPIC_API_KEY", "sk-ant-0123") == "the Credential Manager"
    assert fake_keyring.items == {("Proxenos", "ANTHROPIC_API_KEY"): "sk-ant-0123"}
    settings = config.SETTINGS_FILE.read_text()
    assert json.loads(settings) == {"keychain": ["ANTHROPIC_API_KEY"]}

    monkeypatch.setattr(config, "_loaded", False)  # as a new process starts
    monkeypatch.setattr(config, "_origin", {})
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert config.secrets() == ["ANTHROPIC_API_KEY"]
    assert config.origin("ANTHROPIC_API_KEY") == "keychain"
    assert config.forget_secret("ANTHROPIC_API_KEY") and not fake_keyring.items


class Failing:
    """A store that turns everything down, the way a locked or broken one does."""

    def get_password(self, service, username):
        raise RuntimeError("Failed to unlock the collection!")

    def set_password(self, service, username, password):
        raise RuntimeError(f"rejected {password}")

    delete_password = get_password


def test_a_store_that_fails_is_a_keychain_error_that_never_shows_the_value(monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setattr(keychain, "_keyring", lambda: Failing())
    with pytest.raises(keychain.KeychainError, match="Secret Service didn't give X: Failed to"):
        keychain.get("X")
    with pytest.raises(keychain.KeychainError, match="didn't remove X") as removed:
        keychain.delete("X")
    with pytest.raises(keychain.KeychainError, match="didn't save X") as saved:
        keychain.put("X", "tok-secret")
    assert "tok-secret" not in str(saved.value) and "[hidden]" in str(saved.value)
    assert "Failed to unlock" in str(removed.value)


def test_a_store_that_drops_what_it_is_given_is_caught(monkeypatch, fake_keyring):
    on(monkeypatch, "win32")
    monkeypatch.setattr(fake_keyring, "set_password", lambda service, username, password: None)
    with pytest.raises(keychain.KeychainError, match="Credential Manager didn't save X"):
        keychain.put("X", "tok-1")


def test_a_store_waiting_on_a_person_gives_up_in_time(monkeypatch, fake_keyring):
    on(monkeypatch, "linux")
    monkeypatch.setattr(keychain, "_TIMEOUT", 0.05)
    unlocked = threading.Event()
    monkeypatch.setattr(fake_keyring, "get_password", lambda service, username: unlocked.wait())
    try:
        with pytest.raises(keychain.KeychainError, match="didn't give X: it took too long"):
            keychain.get("X")
    finally:
        unlocked.set()  # let the call left waiting finish


def backend(viable):
    return type("Backend", (), {"viable": viable})


@pytest.mark.parametrize(
    ("platform", "module", "name"),
    [
        ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
        ("linux", "keyring.backends.SecretService", "Keyring"),
        ("freebsd", "keyring.backends.SecretService", "Keyring"),
    ],
)
def test_keyrings_backend_is_named_never_its_own_pick(monkeypatch, platform, module, name):
    on(monkeypatch, platform)
    usable = backend(True)
    for each in (
        "keyring",
        "keyring.backends",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
    ):
        monkeypatch.setitem(sys.modules, each, None)  # no real keyring, nor another platform's
    monkeypatch.setitem(sys.modules, module, types.SimpleNamespace(**{name: usable}))
    assert isinstance(KEYRING(), usable)

    monkeypatch.setitem(sys.modules, module, types.SimpleNamespace(**{name: backend(False)}))
    assert KEYRING() is None  # installed, but its store doesn't answer
    monkeypatch.setitem(sys.modules, module, None)
    assert KEYRING() is None  # not installed
