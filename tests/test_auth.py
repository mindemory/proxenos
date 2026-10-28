"""Browser sign-in helper, with the browser and Strava faked out."""

import base64
import hashlib
import json
import socket
import stat
import threading
import time
import urllib.parse
import urllib.request

import pytest

from proxenos import auth


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


def test_gmail_sign_in_saves_the_account_with_its_refresh_token(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    env = tmp_path / ".env"
    env.write_text("GMAIL_PERSONAL=\n")
    asked, sent = {}, {}

    def open_browser(url):
        asked.update(
            {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        )

        def approve():
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"{asked['redirect_uri']}?code=abc", timeout=2)
                    return
                except OSError:
                    time.sleep(0.05)

        threading.Thread(target=approve, daemon=True).start()

    def post(url, form):
        sent.update(form)
        return {"refresh_token": "r1", "access_token": "a1"}

    auth.gmail("personal", "me@example.com", env, free_port(), open_browser, post)

    assert asked["scope"] == auth.GMAIL_SCOPE and asked["login_hint"] == "me@example.com"
    assert asked["access_type"] == "offline" and asked["code_challenge_method"] == "S256"
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == asked["code_challenge"]
    assert sent["code"] == "abc" and sent["redirect_uri"] == asked["redirect_uri"]
    assert env.read_text() == "GMAIL_PERSONAL=me@example.com:oauth:r1\n"


def test_gmail_sign_in_needs_a_google_client(tmp_path):
    with pytest.raises(SystemExit, match="GOOGLE_CLIENT_ID"):
        auth.gmail("personal", "me@example.com", tmp_path / ".env", free_port(), print, None)


def test_slackdump_sign_in_saves_a_first_archive_only_for_a_new_workspace(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from proxenos.ingest import slackdump

    monkeypatch.setattr(auth.shutil, "which", lambda name: "/bin/slackdump")
    monkeypatch.setattr(slackdump, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("PROXENOS_SLACKDUMP_DIR", raising=False)
    calls = []

    def run(command):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    said = auth.slackdump("https://clayspace.slack.com", tmp_path / "data", run, now)

    login, archive = calls
    assert login == ["slackdump", "workspace", "new", "clayspace"]
    assert archive[:6] == [
        "slackdump",
        "archive",
        "-workspace",
        "clayspace",
        "-files=false",
        "-member-only",
    ]
    assert archive[archive.index("-time-from") + 1] == "2026-02-08T12:00:00"  # 30 days, in UTC
    assert archive[-1].startswith(str(tmp_path / "data" / "slackdump_2026"))
    assert "saved its last 30 days" in said

    monkeypatch.setattr(slackdump, "archives", lambda: [tmp_path / "a" / "slackdump.sqlite"])
    monkeypatch.setattr(slackdump, "_team", lambda db: "Clayspace")
    calls.clear()
    assert "fetches its new messages" in auth.slackdump("clayspace", tmp_path / "data", run, now)
    assert len(calls) == 1  # signed in again; its archive is already there
