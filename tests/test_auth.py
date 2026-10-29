"""Browser sign-in helper, with the browser, Strava, Google and Microsoft faked out."""

import base64
import hashlib
import io
import json
import os
import socket
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from proxenos import auth, config


@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    """A .env for the checkout: once it's there, secrets are saved in it."""
    env = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env)
    return env


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_secret_replaces_its_line_in_env_and_keeps_the_rest(dotenv, fake_keychain):
    dotenv.write_text("A=1\nSTRAVA_REFRESH_TOKEN=old\n# note\n")
    assert config.save_secret("STRAVA_REFRESH_TOKEN", "new") == ".env"
    assert config.save_secret("BEEPER_ACCESS_TOKEN", "2") == ".env"
    assert dotenv.read_text() == "A=1\nSTRAVA_REFRESH_TOKEN=new\n# note\nBEEPER_ACCESS_TOKEN=2\n"
    assert os.name == "nt" or stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    assert not fake_keychain.items


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


def test_strava_sign_in_writes_the_refresh_token(dotenv, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "s")
    dotenv.write_text("STRAVA_REFRESH_TOKEN=old\n")
    sent = {}

    def post(url, form):
        sent.update(form)
        return {"refresh_token": "fresh"}

    said = auth.strava(free_port(), browser_that_approves("read,activity:read_all"), post)
    assert sent["code"] == "abc" and sent["grant_type"] == "authorization_code"
    assert dotenv.read_text() == "STRAVA_REFRESH_TOKEN=fresh\n"
    assert said.startswith("saved a new STRAVA_REFRESH_TOKEN in .env")


def test_strava_sign_in_without_activity_access_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "s")
    with pytest.raises(SystemExit, match="without activity access"):
        auth.strava(free_port(), browser_that_approves("read"), None)


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


def test_slack_config_tokens_become_reading_tokens(tmp_path, dotenv, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN_acme", "config-token")
    monkeypatch.setenv("SLACK_USER_TOKEN_done", "reader-token")
    state = tmp_path / "state" / "slack_apps.json"
    dotenv.write_text("SLACK_USER_TOKEN_acme=config-token\nSLACK_USER_TOKEN_done=reader-token\n")
    fake = FakeSlack(
        {
            "config-token": CONFIG,
            "reader-token": set(auth.SLACK_SCOPES),
            "new-reader": set(auth.SLACK_SCOPES),
        }
    )
    opened = []

    result = auth.slack(state, opened.append, lambda prompt: "new-reader", fake)
    assert result.startswith("slack: 1 reading token(s) saved")
    assert len(fake.created) == 1
    manifest = fake.created[0]
    assert manifest["oauth_config"]["scopes"]["user"] == auth.SLACK_SCOPES
    assert manifest["settings"]["token_rotation_enabled"] is False
    assert opened == ["https://api.slack.com/apps/A1/oauth"]
    assert (
        dotenv.read_text()
        == "SLACK_USER_TOKEN_acme=new-reader\nSLACK_USER_TOKEN_done=reader-token\n"
    )


def test_slack_reuses_the_app_and_refuses_tokens_that_cannot_read(tmp_path, dotenv, monkeypatch):
    monkeypatch.setenv("SLACK_USER_TOKEN_acme", "config-token")
    state = tmp_path / "state" / "slack_apps.json"
    dotenv.write_text("SLACK_USER_TOKEN_acme=config-token\n")
    fake = FakeSlack({"config-token": CONFIG, "weak": {"identify"}})

    auth.slack(state, lambda url: None, lambda prompt: "", fake)  # skipped at the prompt
    auth.slack(state, lambda url: None, lambda prompt: "weak", fake)
    assert len(fake.created) == 1
    assert dotenv.read_text() == "SLACK_USER_TOKEN_acme=config-token\n"


def test_gmail_sign_in_saves_the_account_with_its_refresh_token(dotenv, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    dotenv.write_text("GMAIL_PERSONAL=\n")
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

    auth.gmail("personal", "me@example.com", free_port(), open_browser, post)

    assert asked["scope"] == auth.GMAIL_SCOPE and asked["login_hint"] == "me@example.com"
    assert asked["access_type"] == "offline" and asked["code_challenge_method"] == "S256"
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == asked["code_challenge"]
    assert sent["code"] == "abc" and sent["redirect_uri"] == asked["redirect_uri"]
    assert dotenv.read_text() == "GMAIL_PERSONAL=me@example.com:oauth:r1\n"


def test_gmail_sign_in_needs_a_google_client():
    with pytest.raises(SystemExit, match="GOOGLE_CLIENT_ID"):
        auth.gmail("personal", "me@example.com", free_port(), print, None)


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
    said = auth.slackdump("https://acme.slack.com", tmp_path / "data", run, now)

    login, archive = calls
    assert login == ["slackdump", "workspace", "new", "acme"]
    assert archive[:6] == [
        "slackdump",
        "archive",
        "-workspace",
        "acme",
        "-files=false",
        "-member-only",
    ]
    assert archive[archive.index("-time-from") + 1] == "2026-02-08T12:00:00"  # 30 days, in UTC
    assert archive[-1].startswith(str(tmp_path / "data" / "slackdump_2026"))
    assert "saved its last 30 days" in said

    monkeypatch.setattr(slackdump, "archives", lambda: [tmp_path / "a" / "slackdump.sqlite"])
    monkeypatch.setattr(slackdump, "_team", lambda db: "Acme")
    calls.clear()
    assert "fetches its new messages" in auth.slackdump("acme", tmp_path / "data", run, now)
    assert len(calls) == 1  # signed in again; its archive is already there


@pytest.mark.parametrize(
    "address", ["me@example.com\nANTHROPIC_API_KEY=x", "me:oauth@example.com", "me", "a b@c.com"]
)
def test_gmail_sign_in_refuses_what_isnt_one_address(dotenv, fake_keychain, monkeypatch, address):
    # The address goes into .env as GMAIL_<NAME>=address:oauth:<token>, one line.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    opened = []
    with pytest.raises(SystemExit, match="isn't an email address"):
        auth.gmail("personal", address, free_port(), opened.append, None)
    assert not opened and not dotenv.exists() and not fake_keychain.items


def test_beeper_token_is_saved_only_once_beeper_takes_it(fake_keychain):
    asked = []

    def fetch(path):
        asked.append(path)
        return [{"accountID": "a1", "network": "Instagram"}, {"accountID": "a2", "network": "X"}]

    said = auth.beeper(" tok-123\n", fetch)

    assert asked == ["/v1/accounts"]
    # No .env here, as in the app: it goes to the Keychain, and only its name to the settings.
    assert fake_keychain.items == {"BEEPER_ACCESS_TOKEN": "tok-123"}
    assert "tok-123" not in config.SETTINGS_FILE.read_text()
    assert said == "saved; Beeper has 2 accounts: Instagram, X"


def test_beeper_refuses_what_isnt_a_token_and_keeps_a_refused_one_out(fake_keychain):
    with pytest.raises(SystemExit, match="isn't a Beeper token"):
        auth.beeper("two words", lambda path: [])

    def refused(path):
        raise SystemExit("Beeper refused the token")

    with pytest.raises(SystemExit, match="refused"):
        auth.beeper("tok-123", refused)
    assert not fake_keychain.items and not config.SETTINGS_FILE.exists()


def browser(asked, code="abc"):
    """A browser that notes what the consent page was asked and approves it, sending `code`."""

    def open_browser(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        asked.update({k: v[0] for k, v in query.items()}, url=url)
        redirect = asked["redirect_uri"].replace("localhost", "127.0.0.1")

        def approve():
            for _ in range(50):
                try:
                    urllib.request.urlopen(f"{redirect}?code={code}", timeout=2)
                    return
                except OSError:
                    time.sleep(0.05)

        threading.Thread(target=approve, daemon=True).start()

    return open_browser


def test_google_calendar_sign_in_asks_only_to_read_the_calendar(dotenv, monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    dotenv.write_text("")  # from source with an .env: saved there
    asked, sent = {}, {}

    def post(url, form):
        sent.update(form, url=url)
        return {"refresh_token": "1//calendar-refresh", "access_token": "ya29.a"}

    said = auth.gcalendar("personal", "joe@home.example", free_port(), browser(asked), post)

    assert asked["scope"] == "https://www.googleapis.com/auth/calendar.readonly"
    assert asked["access_type"] == "offline" and asked["login_hint"] == "joe@home.example"
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == asked["code_challenge"]
    assert sent["url"] == "https://oauth2.googleapis.com/token" and sent["code"] == "abc"
    assert dotenv.read_text() == "GCALENDAR_PERSONAL=joe@home.example:oauth:1//calendar-refresh\n"
    shown = said + capsys.readouterr().out
    assert said.startswith("saved GCALENDAR_PERSONAL in .env") and "calendar-refresh" not in shown


def test_google_calendar_sign_in_needs_the_google_client():
    with pytest.raises(SystemExit, match="Google Calendar API"):
        auth.gcalendar("personal", "joe@home.example", free_port(), print, None)


def microsoft_token(url, form):
    return {"refresh_token": "M.C5-ms-refresh", "access_token": "eyJ.ms-access", "expires_in": 3600}


def test_microsoft_sign_in_uses_pkce_with_no_secret_and_saves_the_account(
    dotenv, monkeypatch, capsys
):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    dotenv.write_text("")
    asked, sent, profiled = {}, {}, []

    def post(url, form):
        sent.update(form, url=url)
        return microsoft_token(url, form)

    def profile(token):
        profiled.append(token)
        return {"mail": None, "userPrincipalName": "Joe@Work.example"}

    said = auth.microsoft("work", "joe@work.example", free_port(), browser(asked), post, profile)

    authorize = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
    assert asked["url"].startswith(authorize)
    assert asked["scope"] == "offline_access User.Read Mail.Read Calendars.Read"
    assert asked["redirect_uri"].startswith("http://localhost:")
    assert asked["code_challenge_method"] == "S256" and asked["login_hint"] == "joe@work.example"
    digest = hashlib.sha256(sent["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == asked["code_challenge"]
    assert sent["url"] == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    assert sent["grant_type"] == "authorization_code" and sent["code"] == "abc"
    assert sent["redirect_uri"] == asked["redirect_uri"] and "client_secret" not in sent
    assert profiled == ["eyJ.ms-access"]
    assert dotenv.read_text() == "MICROSOFT_WORK=joe@work.example:oauth:M.C5-ms-refresh\n"
    shown = said + capsys.readouterr().out
    assert said.startswith("saved MICROSOFT_WORK in .env")
    assert "ms-refresh" not in shown and "ms-access" not in shown and "abc" not in shown


def test_microsoft_sign_in_as_another_account_saves_nothing(dotenv, fake_keychain, monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client")

    def profile(token):
        return {"mail": "someone@else.example", "userPrincipalName": "someone@else.example"}

    with pytest.raises(SystemExit, match="signed in someone@else.example, not joe@work.example"):
        auth.microsoft(
            "work", "joe@work.example", free_port(), browser({}), microsoft_token, profile
        )
    assert not dotenv.exists() and not fake_keychain.items


def test_microsoft_sign_in_says_why_it_was_refused(dotenv, monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client")
    body = {
        "error": "invalid_client",
        "error_description": "AADSTS7000218: The request body must contain client_secret.\r\n"
        "Trace ID: 0000",
    }

    def post(url, form):
        raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(json.dumps(body).encode()))

    with pytest.raises(SystemExit) as stopped:
        auth.microsoft("work", "joe@work.example", free_port(), browser({}), post, None)
    said = str(stopped.value)
    assert said.startswith("Microsoft refused the sign-in: AADSTS7000218")
    assert "Mobile and desktop" in said and "Trace ID" not in said
    assert not dotenv.exists()


def test_microsoft_sign_in_needs_its_client_and_a_fair_name(monkeypatch):
    opened = []
    with pytest.raises(SystemExit, match="MICROSOFT_CLIENT_ID"):
        auth.microsoft("work", "joe@work.example", free_port(), opened.append, None)
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "client")
    with pytest.raises(SystemExit, match="other than client_id"):
        auth.microsoft("client_id", "joe@work.example", free_port(), opened.append, None)
    with pytest.raises(SystemExit, match="isn't an email address"):
        auth.microsoft("work", "joe@work.example\nX=1", free_port(), opened.append, None)
    assert not opened
