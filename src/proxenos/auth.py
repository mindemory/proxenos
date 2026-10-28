"""One-time browser sign-ins that put a token straight into .env, with nothing shown on screen.

`proxenos auth strava` opens Strava's approval page, catches the redirect on localhost, swaps the
code for a refresh token and writes it to .env. The Strava ingester notices the new value
and switches to it.

`proxenos auth gmail NAME ADDRESS` does the same with Google for a Gmail account that can't make
app passwords: it needs a Google Cloud "Desktop app" OAuth client (GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET in .env), asks for mail access (IMAP needs the full mail scope; Proxenos
only ever reads, and selects mail read-only), and saves GMAIL_<NAME>=address:oauth:<refresh token>.

`proxenos auth slack` turns Slack app configuration tokens (SLACK_USER_TOKEN_<workspace>, from
api.slack.com/apps) into reading tokens: it creates a read-only "Proxenos reader" app in each
workspace from a manifest, opens the app's install page, and takes the user token the page
shows through a hidden prompt, replacing the configuration token in .env.
"""

import base64
import getpass
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from proxenos.config import REPO_ROOT

PORT = 8723
_STRAVA_AUTHORIZE = "https://www.strava.com/oauth/authorize"
_STRAVA_TOKEN = "https://www.strava.com/oauth/token"
_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://mail.google.com/"
_SLACK_API = "https://slack.com/api/"
SLACK_SCOPES = [
    "channels:read",
    "groups:read",
    "im:read",
    "mpim:read",
    "channels:history",
    "groups:history",
    "im:history",
    "mpim:history",
    "users:read",
]
_SLACK_MANIFEST = {
    "display_information": {
        "name": "Proxenos reader",
        "description": "Read-only access to your own conversations, for Proxenos.",
    },
    "oauth_config": {"scopes": {"user": SLACK_SCOPES}},
    "settings": {
        "org_deploy_enabled": False,
        "socket_mode_enabled": False,
        "token_rotation_enabled": False,
    },
}
# body, granted scopes
SlackCall = Callable[[str, str, dict], tuple[dict, set[str]]]


def strava(
    env_path: Path = REPO_ROOT / ".env",
    port: int = PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    post: Callable[[str, dict], dict] | None = None,
) -> str:
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit("Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env first.")

    redirect = f"http://localhost:{port}/"
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect,
            "approval_prompt": "force",
            "scope": "activity:read_all",
        }
    )
    print(
        "Opening Strava in your browser. Approve, and keep the private-activities box ticked.\n"
        "If Strava says the redirect is invalid, set the app's Authorization Callback Domain "
        "to localhost at strava.com/settings/api."
    )
    open_browser(f"{_STRAVA_AUTHORIZE}?{query}")
    answer = _wait_for_redirect(port)
    if "code" not in answer:
        raise SystemExit(f"Strava didn't approve: {answer.get('error', 'no answer')}")
    if "activity:read_all" not in answer.get("scope", ""):
        raise SystemExit("Approved without activity access. Run again and keep the box ticked.")

    token = (post or _post)(
        _STRAVA_TOKEN,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": answer["code"],
            "grant_type": "authorization_code",
        },
    )
    set_env(env_path, "STRAVA_REFRESH_TOKEN", token["refresh_token"])
    return "saved a new STRAVA_REFRESH_TOKEN in .env; now run `proxenos ingest strava --full`"


def gmail(
    name: str,
    address: str,
    env_path: Path = REPO_ROOT / ".env",
    port: int = PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    post: Callable[[str, dict], dict] | None = None,
) -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first: a Google Cloud OAuth "
            "client of type Desktop app, with the Gmail API on (see docs/data_sources.md)."
        )
    key = "".join(c for c in name.upper() if c.isalnum() or c == "_")
    if not key:
        raise SystemExit("Name the account with letters, digits or _, e.g. personal.")

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    redirect = f"http://127.0.0.1:{port}/"
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect,
            "scope": GMAIL_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "login_hint": address,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
        }
    )
    print(f"Opening Google in your browser. Sign in as {address} and allow access to your mail.")
    open_browser(f"{_GOOGLE_AUTHORIZE}?{query}")
    answer = _wait_for_redirect(port)
    if "code" not in answer:
        raise SystemExit(f"Google didn't approve: {answer.get('error', 'no answer')}")

    token = (post or _post)(
        _GOOGLE_TOKEN,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": answer["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
    )
    if "refresh_token" not in token:
        raise SystemExit("Google gave no refresh token. Run again and approve on the consent page.")
    set_env(env_path, f"GMAIL_{key}", f"{address}:oauth:{token['refresh_token']}")
    return f"saved GMAIL_{key} in .env; `proxenos sync` now reads {address} every run"


def set_env(env_path: Path, name: str, value: str) -> None:
    """Set one variable in .env, keeping every other line, and keep the file private."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    entry = f"{name}={value}"
    for i, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[i] = entry
            break
    else:
        lines.append(entry)
    tmp = env_path.with_name(env_path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, env_path)
    os.environ[name] = value


def _wait_for_redirect(port: int, timeout: float = 300) -> dict[str, str]:
    answer: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in query or "error" in query:
                answer.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab.")

        def log_message(self, *args: object) -> None:
            pass

    deadline = time.monotonic() + timeout
    with HTTPServer(("127.0.0.1", port), Handler) as server:
        server.timeout = 1
        while not answer and time.monotonic() < deadline:
            server.handle_request()
    if not answer:
        raise SystemExit("No answer from the browser within 5 minutes.")
    return answer


def _post(url: str, form: dict) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def slack(
    env_path: Path,
    state_path: Path,
    open_browser: Callable[[str], object] = webbrowser.open,
    ask: Callable[[str], str] = getpass.getpass,
    call: SlackCall | None = None,
) -> str:
    from proxenos.ingest.slack import tokens

    call = call or _slack_call
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    saved = skipped = 0
    for name, token in tokens().items():
        body, scopes = call("auth.test", token, {})
        team = body.get("team") or name
        if not body.get("ok"):
            print(f"{name}: Slack rejected this token ({body.get('error')}). Make a new one.")
            skipped += 1
            continue
        if set(SLACK_SCOPES) <= scopes:
            continue  # already a reading token
        if "app_configurations:write" not in scopes:
            print(f"{team}: this token can neither read nor create apps; skipped.")
            skipped += 1
            continue

        if name not in state:
            created, _ = call(
                "apps.manifest.create", token, {"manifest": json.dumps(_SLACK_MANIFEST)}
            )
            if not created.get("ok"):
                print(f"{team}: couldn't create the app ({created.get('error')}); skipped.")
                skipped += 1
                continue
            state[name] = {"app_id": created["app_id"], "team": team}
            state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=1))

        print(
            f"\n{team}: opening the reader app. Click 'Install to {team}', then Allow, "
            "then copy the User OAuth Token (xoxp-...)."
        )
        open_browser(f"https://api.slack.com/apps/{state[name]['app_id']}/oauth")
        pasted = ask(f"{team} user token (hidden; Enter to skip): ").strip()
        if not pasted:
            skipped += 1
            continue
        body, granted = call("auth.test", pasted, {})
        if not body.get("ok") or not set(SLACK_SCOPES) <= granted:
            print(f"{team}: that token can't read messages; nothing saved.")
            skipped += 1
            continue
        set_env(env_path, name, pasted)
        saved += 1
    return f"slack: {saved} reading token(s) saved, {skipped} workspace(s) skipped"


def _slack_call(method: str, token: str, form: dict) -> tuple[dict, set[str]]:
    request = urllib.request.Request(
        _SLACK_API + method,
        data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        scopes = response.headers.get("x-oauth-scopes", "")
        return json.loads(response.read()), {s for s in scopes.split(",") if s}
