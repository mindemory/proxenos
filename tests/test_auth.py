"""Browser sign-in helper, with the browser and Strava faked out."""

import json
import socket
import stat
import threading
import time
import urllib.parse
import urllib.request

import pytest

from twin import auth


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_set_env_replaces_one_line_and_keeps_the_rest(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nSTRAVA_REFRESH_TOKEN=old\n# note\n")
    auth.set_env(env, "STRAVA_REFRESH_TOKEN", "new")
    auth.set_env(env, "B", "2")
    assert env.read_text() == "A=1\nSTRAVA_REFRESH_TOKEN=new\n# note\nB=2\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def browser_that_approves(scope):
    def open_browser(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert query["scope"] == ["activity:read_all"]
        redirect = query["redirect_uri"][0].replace("localhost", "127.0.0.1")

        # The helper is waiting on its server; answer from a thread once it's listening.
        def approve():
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"{redirect}?code=abc&scope={scope}", timeout=2)
                    return
                except OSError:
                    time.sleep(0.05)

        threading.Thread(target=approve, daemon=True).start()

    return open_browser


def test_strava_sign_in_writes_the_refresh_token(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "s")
    env = tmp_path / ".env"
    env.write_text("STRAVA_REFRESH_TOKEN=old\n")
    sent = {}

    def post(url, form):
        sent.update(form)
        return {"refresh_token": "fresh"}

    auth.strava(env, free_port(), browser_that_approves("read,activity:read_all"), post)
    assert sent["code"] == "abc" and sent["grant_type"] == "authorization_code"
    assert env.read_text() == "STRAVA_REFRESH_TOKEN=fresh\n"


def test_strava_sign_in_without_activity_access_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "s")
    with pytest.raises(SystemExit, match="without activity access"):
        auth.strava(tmp_path / ".env", free_port(), browser_that_approves("read"), None)


class FakeSlack:
    """auth.test and apps.manifest.create, keyed by token."""

    def __init__(self, scopes):
        self.scopes = scopes  # token → granted scopes
        self.created = []

    def __call__(self, method, token, form):
        if method == "apps.manifest.create":
            self.created.append(json.loads(form["manifest"]))
            return {"ok": True, "app_id": f"A{len(self.created)}"}, set()
        if token not in self.scopes:
            return {"ok": False, "error": "invalid_auth"}, set()
        return {"ok": True, "team": "Acme Lab"}, self.scopes[token]


CONFIG = {"identify", "app_configurations:read", "app_configurations:write"}


def test_slack_config_tokens_become_reading_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN_acme", "config-token")
    monkeypatch.setenv("SLACK_USER_TOKEN_done", "reader-token")
    env, state = tmp_path / ".env", tmp_path / "state" / "slack_apps.json"
    env.write_text("SLACK_USER_TOKEN_acme=config-token\nSLACK_USER_TOKEN_done=reader-token\n")
    fake = FakeSlack(
        {
            "config-token": CONFIG,
            "reader-token": set(auth.SLACK_SCOPES),
            "new-reader": set(auth.SLACK_SCOPES),
        }
    )
    opened = []

    result = auth.slack(env, state, opened.append, lambda prompt: "new-reader", fake)
    assert result.startswith("slack: 1 reading token(s) saved")
    assert len(fake.created) == 1
    manifest = fake.created[0]
    assert manifest["oauth_config"]["scopes"]["user"] == auth.SLACK_SCOPES
    assert manifest["settings"]["token_rotation_enabled"] is False
    assert opened == ["https://api.slack.com/apps/A1/oauth"]
    assert (
        env.read_text() == "SLACK_USER_TOKEN_acme=new-reader\nSLACK_USER_TOKEN_done=reader-token\n"
    )


def test_slack_reuses_the_app_and_refuses_tokens_that_cannot_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN_acme", "config-token")
    env, state = tmp_path / ".env", tmp_path / "state" / "slack_apps.json"
    env.write_text("SLACK_USER_TOKEN_acme=config-token\n")
    fake = FakeSlack({"config-token": CONFIG, "weak": {"identify"}})

    auth.slack(env, state, lambda url: None, lambda prompt: "", fake)  # skipped at the prompt
    auth.slack(env, state, lambda url: None, lambda prompt: "weak", fake)
    assert len(fake.created) == 1
    assert env.read_text() == "SLACK_USER_TOKEN_acme=config-token\n"
