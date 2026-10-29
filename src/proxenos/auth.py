"""One-time browser sign-ins that save a token where Proxenos keeps secrets, with nothing shown.

Each token goes through `config.save_secret`: into .env when running from source with one, else
into the secure store (the macOS Keychain, or Windows Credential Manager or the Secret Service).

`proxenos auth strava` opens Strava's approval page, catches the redirect on localhost, swaps the
code for a refresh token and saves it. The Strava ingester notices the new value and switches
to it.

`proxenos auth gmail NAME ADDRESS` does the same with Google for a Gmail account that can't make
app passwords: it needs a Google Cloud "Desktop app" OAuth client (GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET, in .env or the page's Settings), asks for mail access (IMAP needs the full
mail scope; Proxenos only ever reads, and selects mail read-only), and saves
GMAIL_<NAME>=address:oauth:<refresh token>.

`proxenos auth gcalendar NAME ADDRESS` is the same with the same Google client, asking only for
calendar.readonly, and saves GCALENDAR_<NAME>=address:oauth:<refresh token>. It's its own
sign-in, not an extra scope on Gmail's, so a calendar can be connected without mail access.

`proxenos auth microsoft NAME ADDRESS` does it with Microsoft's sign-in for a Microsoft 365 or
Outlook.com account: the person's own app registration (MICROSOFT_CLIENT_ID, a public client with
no secret, so PKCE is what keeps a stolen code useless), read-only mail and calendar scopes, the
answer caught on localhost (the redirect Microsoft lets a desktop app register once for any
port). It checks with Graph that the account that signed in is ADDRESS, then saves
MICROSOFT_<NAME>=address:oauth:<refresh token>.

`proxenos auth slack` turns Slack app configuration tokens (SLACK_USER_TOKEN_<workspace>, from
api.slack.com/apps) into reading tokens: it creates a read-only "Proxenos reader" app in each
workspace from a manifest, opens the app's install page, and takes the user token the page
shows through a hidden prompt, replacing the configuration token.

`proxenos auth beeper` saves a Beeper Desktop API token (created in Beeper: Settings,
Integrations) as BEEPER_ACCESS_TOKEN, once Beeper has taken it. It reads the token from a hidden
prompt, or from stdin when the page passes it on, never from the command line.

`proxenos auth slackdump NAME` signs in to a Slack workspace through slackdump (which keeps the
sign-in itself) and, the first time, saves its last 30 days into data/, without attachments.
From then on every sync fetches its new messages.
"""

import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from proxenos.config import REPO_ROOT, save_secret
from proxenos.ingest import beeper as beeper_api
from proxenos.ingest import gcalendar as gcalendar_api
from proxenos.ingest import microsoft as microsoft_api
from proxenos.ingest import slack as slack_api
from proxenos.ingest import slackdump as slack_archives

PORT = 8723
SLACK_FIRST_DAYS = 30  # how far back a workspace's first archive goes
_STRAVA_AUTHORIZE = "https://www.strava.com/oauth/authorize"
_STRAVA_TOKEN = "https://www.strava.com/oauth/token"
_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GMAIL_SCOPE = "https://mail.google.com/"
GCALENDAR_SCOPE = gcalendar_api.SCOPE
MICROSOFT_SCOPES = microsoft_api.SCOPES
# One address on one line. No ":" either: it's kept as address:oauth:<token>.
_ADDRESS = re.compile(r"[^\s@:]+@[^\s@:]+\.[^\s@:]+")
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
    where = save_secret("STRAVA_REFRESH_TOKEN", token["refresh_token"])
    return f"saved a new STRAVA_REFRESH_TOKEN in {where}; now run `proxenos ingest strava --full`"


def gmail(
    name: str,
    address: str,
    port: int = PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    post: Callable[[str, dict], dict] | None = None,
) -> str:
    variable, where = _google(
        "GMAIL", name, address, GMAIL_SCOPE, "the Gmail API", "your mail", port, open_browser, post
    )
    return f"saved {variable} in {where}; `proxenos sync` now reads {address} every run"


def gcalendar(
    name: str,
    address: str,
    port: int = PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    post: Callable[[str, dict], dict] | None = None,
) -> str:
    variable, where = _google(
        "GCALENDAR",
        name,
        address,
        GCALENDAR_SCOPE,
        "the Google Calendar API",
        "your calendar, read-only",
        port,
        open_browser,
        post,
    )
    return f"saved {variable} in {where}; `proxenos sync` now reads {address}'s calendar every run"


def microsoft(
    name: str,
    address: str,
    port: int = PORT,
    open_browser: Callable[[str], object] = webbrowser.open,
    post: Callable[[str, dict], dict] | None = None,
    profile: Callable[[str], dict] | None = None,
) -> str:
    client_id = os.environ.get(microsoft_api.CLIENT)
    if not client_id:
        raise SystemExit(
            "Set MICROSOFT_CLIENT_ID first: the Application (client) ID of your own app "
            "registration in Microsoft Entra, with http://localhost as a Mobile and desktop "
            "redirect (see docs/data_sources.md)."
        )
    key = _account_key(name)
    if f"MICROSOFT_{key}" == microsoft_api.CLIENT:
        raise SystemExit("Name the account something other than client_id, e.g. work.")
    _check_address(address)

    redirect = f"http://localhost:{port}/"
    print(
        f"Opening Microsoft in your browser. Sign in as {address} and allow Proxenos to read "
        "your mail and calendar."
    )
    code, verifier = _consent(
        microsoft_api.AUTHORITY + "authorize",
        {
            "client_id": client_id,
            "response_type": "code",
            "response_mode": "query",
            "scope": MICROSOFT_SCOPES,
            "login_hint": address,
        },
        redirect,
        port,
        open_browser,
        "Microsoft",
    )
    form = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect,
        "scope": MICROSOFT_SCOPES,
    }
    try:
        token = (post or _post)(microsoft_api.AUTHORITY + "token", form)
    except urllib.error.HTTPError as e:
        why = microsoft_api.refused(e).why or f"HTTP {e.code}"
        raise SystemExit(
            f"Microsoft refused the sign-in: {why}. Check that the app registration has "
            "http://localhost under Mobile and desktop applications."
        ) from None
    if not token.get("refresh_token") or not token.get("access_token"):
        raise SystemExit("Microsoft gave no refresh token. Run again and accept on its page.")

    try:
        who = (profile or microsoft_api.profile)(token["access_token"])
    except microsoft_api.Refused as e:
        raise SystemExit(f"Microsoft Graph didn't say who signed in ({e}).") from None
    signed_in = {str(who.get(k) or "").strip().lower() for k in ("mail", "userPrincipalName")}
    if address.lower() not in signed_in:
        shown = who.get("mail") or who.get("userPrincipalName") or "another account"
        raise SystemExit(
            f"Microsoft signed in {shown}, not {address}. Run again and sign in as {address}, "
            f"or name {shown} instead. Nothing was saved."
        )
    variable = f"MICROSOFT_{key}"
    where = save_secret(variable, f"{address}:oauth:{token['refresh_token']}")
    return (
        f"saved {variable} in {where}; `proxenos sync` now reads {address}'s mail and calendar "
        "every run"
    )


def _google(
    prefix: str,
    name: str,
    address: str,
    scope: str,
    api: str,
    access: str,
    port: int,
    open_browser: Callable[[str], object],
    post: Callable[[str, dict], dict] | None,
) -> tuple[str, str]:
    """A Google sign-in with the Desktop app client, saved as <prefix>_<NAME>. The variable and
    where it went."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit(
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first: a Google Cloud OAuth "
            f"client of type Desktop app, with {api} on (see docs/data_sources.md)."
        )
    key = _account_key(name)
    _check_address(address)

    redirect = f"http://127.0.0.1:{port}/"
    print(f"Opening Google in your browser. Sign in as {address} and allow access to {access}.")
    code, verifier = _consent(
        _GOOGLE_AUTHORIZE,
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",
            "prompt": "consent",
            "login_hint": address,
        },
        redirect,
        port,
        open_browser,
        "Google",
    )
    token = (post or _post)(
        _GOOGLE_TOKEN,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
    )
    if "refresh_token" not in token:
        raise SystemExit("Google gave no refresh token. Run again and approve on the consent page.")
    variable = f"{prefix}_{key}"
    return variable, save_secret(variable, f"{address}:oauth:{token['refresh_token']}")


def _consent(
    authorize: str,
    params: dict,
    redirect: str,
    port: int,
    open_browser: Callable[[str], object],
    who: str,
) -> tuple[str, str]:
    """Open a consent page with a PKCE challenge and wait for its answer on this computer. The
    code it sends back, and the verifier that alone can redeem it."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = urllib.parse.urlencode(
        {
            **params,
            "redirect_uri": redirect,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
        }
    )
    open_browser(f"{authorize}?{query}")
    answer = _wait_for_redirect(port)
    if "code" not in answer:
        raise SystemExit(f"{who} didn't approve: {answer.get('error', 'no answer')}")
    return answer["code"], verifier


def _account_key(name: str) -> str:
    key = "".join(c for c in name.upper() if c.isalnum() or c == "_")
    if not key:
        raise SystemExit("Name the account with letters, digits or _, e.g. personal.")
    return key


def _check_address(address: str) -> None:
    # It's kept as address:oauth:<token> on one line, so one address and nothing else.
    if not _ADDRESS.fullmatch(address) or len(address) > 254:
        raise SystemExit(f"{address!r} isn't an email address.")


def slackdump(
    name: str,
    data: Path = REPO_ROOT / "data",
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    now: datetime | None = None,
) -> str:
    if not shutil.which("slackdump"):
        raise SystemExit("Install slackdump first: brew install slackdump")
    # "acme", "acme.slack.com" or its address: slackdump knows it by "acme".
    workspace = re.sub(r"^https?://", "", name.strip()).split(".")[0].strip("/")
    if not workspace:
        raise SystemExit("Name the workspace as in its address, e.g. acme for acme.slack.com.")
    if run(["slackdump", "workspace", "new", workspace]).returncode != 0:
        raise SystemExit(f"slackdump didn't sign in to {workspace}")
    saved = {slack_api._slug(slack_archives._team(db) or "") for db in slack_archives.archives()}
    if slack_api._slug(workspace) in saved:
        return f"signed in to {workspace}; `proxenos sync` now fetches its new messages every run"

    now = (now or datetime.now()).astimezone()
    since = now - timedelta(days=SLACK_FIRST_DAYS)
    print(f"Saving the last {SLACK_FIRST_DAYS} days of {workspace}, without attachments.")
    command = ["slackdump", "archive", "-workspace", workspace, "-files=false", "-member-only"]
    command += ["-time-from", f"{since.astimezone(UTC):%Y-%m-%dT%H:%M:%S}"]  # it reads UTC
    command += ["-o", str(data / f"slackdump_{now:%Y%m%d_%H%M%S}")]
    if run(command).returncode != 0:
        raise SystemExit(f"slackdump couldn't save {workspace}; run the same command again")
    return (
        f"signed in to {workspace} and saved its last {SLACK_FIRST_DAYS} days; "
        "`proxenos sync` reads it and fetches new messages every run"
    )


def beeper(
    token: str | None = None,
    fetch: Callable[[str], object] | None = None,
) -> str:
    if token is None:
        token = getpass.getpass("Beeper token: ") if sys.stdin.isatty() else sys.stdin.readline()
    token = token.strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise SystemExit("That isn't a Beeper token: copy it again from Beeper's Integrations.")
    accounts = (fetch or beeper_api._fetcher(token))("/v1/accounts")
    if not isinstance(accounts, list):
        raise SystemExit("Beeper answered oddly; is it Beeper Desktop on this Mac?")
    save_secret("BEEPER_ACCESS_TOKEN", token)
    networks = sorted(
        {str(a.get("network") or "an account") for a in accounts if isinstance(a, dict)}
    )
    return f"saved; Beeper has {len(accounts)} accounts: {', '.join(networks) or 'none yet'}"


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
        save_secret(name, pasted)
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
