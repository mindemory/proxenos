"""`proxenos phone`: open the page to the user's own phone, privately, through Tailscale.

Tailscale Serve gives this Mac a private HTTPS address on the user's tailnet (the devices signed
in to their Tailscale account, and no one else's) and passes requests to it on to the page at
127.0.0.1:4747, saying which Tailscale login is asking. This turns that on and saves the address
as PROXENOS_REMOTE_HOST and the user's login as PROXENOS_REMOTE_USER in .env; the page then lets
in requests to that address from that login, and no others. Nothing is opened to the internet.
"""

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from proxenos import webapp
from proxenos.auth import set_env
from proxenos.config import REPO_ROOT

SERVE_WAIT = 30  # seconds; Serve waits while HTTPS is off for the tailnet, so don't wait for it


def setup(
    env_path: Path = REPO_ROOT / ".env",
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    if not shutil.which("tailscale"):
        raise SystemExit(
            "Install Tailscale on this Mac and on your phone (tailscale.com/download), sign in to "
            "both with the same account, then run this again."
        )
    status = json.loads(
        run(["tailscale", "status", "--json"], capture_output=True, text=True, check=True).stdout
    )
    if status.get("BackendState") != "Running":
        raise SystemExit(
            "Tailscale isn't connected on this Mac: open it, sign in, and run this again."
        )
    me = status["Self"]
    host = me["DNSName"].rstrip(".").lower()
    login = status["User"][str(me["UserID"])]["LoginName"].lower()

    try:
        served = run(
            ["tailscale", "serve", "--bg", f"http://127.0.0.1:{webapp.PORT}"],
            capture_output=True,
            text=True,
            timeout=SERVE_WAIT,
        )
    except subprocess.TimeoutExpired as e:
        said = e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout or ""
        link = re.search(r"https://login\.tailscale\.com/\S+", said)
        where = (
            f"at {link[0]}" if link else "in Tailscale's admin console (DNS, HTTPS Certificates)"
        )
        raise SystemExit(f"Turn on HTTPS for your tailnet {where}, then run this again.") from None
    if served.returncode != 0:
        raise SystemExit(f"tailscale serve failed: {' '.join(served.stderr.split())[:300]}")
    set_env(env_path, "PROXENOS_REMOTE_HOST", host)
    set_env(env_path, "PROXENOS_REMOTE_USER", login)
    return (
        f"On your phone, with Tailscale on and signed in as {login}, open https://{host} and "
        "add it to the home screen."
    )
