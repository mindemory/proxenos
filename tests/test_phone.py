"""`proxenos phone`, against a fake tailscale command. No real tailnet."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from proxenos import phone

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
    run, calls = tailscale(lambda c, k: SimpleNamespace(returncode=0, stderr=""))

    said = phone.setup(tmp_path / ".env", run)

    assert calls[1] == ["tailscale", "serve", "--bg", "http://127.0.0.1:4747"]
    env = (tmp_path / ".env").read_text().splitlines()
    assert "PROXENOS_REMOTE_HOST=my-mac.tail1234.ts.net" in env
    assert "PROXENOS_REMOTE_USER=me@example.org" in env
    assert "https://my-mac.tail1234.ts.net" in said


def test_https_off_for_the_tailnet_says_where_to_turn_it_on(tmp_path, monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: "/usr/local/bin/tailscale")

    def waits(command, kwargs):
        said = "Serve is not enabled. To enable, visit:\n\n https://login.tailscale.com/f/serve?node=n1\n"
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=said)

    run, _ = tailscale(waits)
    with pytest.raises(SystemExit, match=r"login\.tailscale\.com/f/serve\?node=n1"):
        phone.setup(tmp_path / ".env", run)
    assert not (tmp_path / ".env").exists()  # nothing is let in until Serve is on


def test_without_tailscale_it_says_how_to_get_it(tmp_path, monkeypatch):
    monkeypatch.setattr(phone.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="tailscale.com/download"):
        phone.setup(tmp_path / ".env", run=None)
