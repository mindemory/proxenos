"""`proxenos phone`, against a fake tailscale command. No real tailnet."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from proxenos import config, phone

STATUS = {
    "BackendState": "Running",
    "Self": {"DNSName": "my-mac.tail1234.ts.net.", "UserID": 7},
    "User": {"7": {"LoginName": "Me@Example.org"}},
}


def tailscale(serve):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "status":
            return SimpleNamespace(stdout=json.dumps(STATUS), returncode=0)
        return serve(command, kwargs)

    return run, calls


def test_serves_the_page_and_lets_in_only_the_users_own_login(tmp_path, monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: "/usr/local/bin/tailscale")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("PROXENOS_NAME=Ana\n")  # from source, with an .env
    run, calls = tailscale(lambda c, k: SimpleNamespace(returncode=0, stderr=""))

    said = phone.setup(run)

    assert calls[1] == ["tailscale", "serve", "--bg", "http://127.0.0.1:4747"]
    env = (tmp_path / ".env").read_text().splitlines()
    assert "PROXENOS_REMOTE_HOST=my-mac.tail1234.ts.net" in env
    assert "PROXENOS_REMOTE_USER=me@example.org" in env
    assert "https://my-mac.tail1234.ts.net" in said


def test_without_an_env_the_address_goes_to_the_settings_file(monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: "/usr/local/bin/tailscale")
    run, _ = tailscale(lambda c, k: SimpleNamespace(returncode=0, stderr=""))

    phone.setup(run)

    settings = json.loads(config.SETTINGS_FILE.read_text())
    assert settings == {"remote_host": "my-mac.tail1234.ts.net", "remote_user": "me@example.org"}


def test_https_off_for_the_tailnet_says_where_to_turn_it_on(tmp_path, monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: "/usr/local/bin/tailscale")

    def waits(command, kwargs):
        said = "Serve is not enabled. To enable, visit:\n\n https://login.tailscale.com/f/serve?node=n1\n"
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=said)

    run, _ = tailscale(waits)
    with pytest.raises(SystemExit, match=r"login\.tailscale\.com/f/serve\?node=n1"):
        phone.setup(run)
    assert not config.SETTINGS_FILE.exists()  # nothing is let in until Serve is on


def test_without_tailscale_it_says_how_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="tailscale.com/download"):
        phone.setup(run=None)
