"""Strava activities from the Strava API v3.

Refreshes an OAuth access token, pages through /athlete/activities and writes monthly JSONL
into the vault. Runs are incremental: they ask only for activities that started after the
latest stored one, less MARGIN, which catches late uploads and refreshes recent kudos and
edits. `--full` re-reads everything, which also picks up edits to old activities. Merging by
id makes both safe to repeat.

Credentials come from STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET and STRAVA_REFRESH_TOKEN. Strava
can rotate the refresh token on any refresh and the old one then stops working, so the latest
is kept in vault/state/strava_token.json and used instead of the env value until that value
changes. To get a refresh token with the activity:read_all scope, open
    https://www.strava.com/oauth/authorize?client_id=<id>&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all
approve, copy `code` from the localhost URL you land on, and POST it to /oauth/token with
client_id, client_secret and grant_type=authorization_code. The reply holds the refresh token.

Map polylines and start/end coordinates are dropped, so the vault keeps no routes and no
home location.
"""

import argparse
import hashlib
import itertools
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ENV_VARS = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
PER_PAGE = 200  # Strava's maximum
# Strava filters `after` on start time, and uploads can trail the activity by days.
MARGIN = timedelta(days=7)

_STATE = Path("state", "strava_token.json")
_HELP = "proxenos/ingest/strava.py explains how to get a refresh token with activity:read_all."

# Takes a request and returns the decoded JSON body, raising HTTPError the way urlopen does.
Fetch = Callable[[urllib.request.Request], Any]


def _fetch_json(request: urllib.request.Request) -> Any:
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def ingest(vault: Path, full: bool = False, fetch: Fetch = _fetch_json) -> dict[str, int]:
    out = vault / "raw" / "strava" / "activities"
    access_token = _access_token(vault / _STATE, fetch)
    latest = None if full else _latest_start(out)
    after = None if latest is None else int((latest - MARGIN).timestamp())
    activities = _activities(access_token, after, fetch)
    return merge_monthly(map(_record, activities), out)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--full", action="store_true", help="re-read every activity, not just recent ones"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, full=args.full)


def _access_token(state_path: Path, fetch: Fetch) -> str:
    client_id, client_secret, env_token = (os.environ.get(name) or None for name in ENV_VARS)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    # The saved token descends from one STRAVA_REFRESH_TOKEN, remembered by its hash. A new
    # env value means the user re-authorized (say, for a wider scope), so it wins.
    seed = _sha256(env_token) if env_token else state.get("env_token_sha256")
    if state.get("refresh_token") and state.get("env_token_sha256") == seed:
        refresh_token = state["refresh_token"]
    else:
        refresh_token = env_token

    values = (client_id, client_secret, refresh_token)
    missing = [name for name, value in zip(ENV_VARS, values) if not value]
    if missing:
        raise SystemExit(f"strava: set {', '.join(missing)} in the repo's .env. {_HELP}")

    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    request = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(form).encode(), method="POST"
    )
    token = _call(fetch, request, {400, 401}, "check the client id, secret and token")
    # Save before anything else can fail: the token just used may already be dead.
    _save_state(state_path, {"refresh_token": token["refresh_token"], "env_token_sha256": seed})
    return token["access_token"]


def _activities(access_token: str, after: int | None, fetch: Fetch) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}
    activities = []
    for page in itertools.count(1):
        params = {"per_page": PER_PAGE, "page": page}
        if after is not None:
            params["after"] = after
        url = f"{ACTIVITIES_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=headers)
        batch = _call(fetch, request, {401}, "the token's scope may be too narrow")
        if not batch:
            return activities
        activities.extend(batch)


def _call(fetch: Fetch, request: urllib.request.Request, refused: set[int], hint: str):
    try:
        return fetch(request)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit(
                "strava: rate limited (HTTP 429), so no activities were written. The limits "
                "reset every 15 minutes and at midnight UTC; run again later."
            ) from None
        if e.code in refused:
            raise SystemExit(
                f"strava: Strava refused us (HTTP {e.code}); {hint}. {_HELP}"
            ) from None
        raise


def _latest_start(directory: Path) -> datetime | None:
    months = sorted(directory.glob("*.jsonl"))
    if not months:
        return None
    with months[-1].open(encoding="utf-8") as f:
        latest = max((json.loads(line)["ts"] for line in f), default=None)
    return datetime.fromisoformat(latest) if latest else None


def _record(activity: dict) -> dict:
    # Only these summary fields are kept; map, start_latlng and end_latlng never reach disk.
    start = datetime.fromisoformat(activity["start_date"]).astimezone(UTC)
    return {
        "id": f"strava:{activity['id']}",
        "ts": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "name": activity.get("name") or None,
        "sport_type": activity.get("sport_type"),
        "distance_m": activity.get("distance"),
        "moving_time_s": activity.get("moving_time"),
        "elapsed_time_s": activity.get("elapsed_time"),
        "total_elevation_gain_m": activity.get("total_elevation_gain"),
        "average_speed": activity.get("average_speed"),  # m/s, as are max_speed
        "max_speed": activity.get("max_speed"),
        "average_heartrate": activity.get("average_heartrate"),
        "max_heartrate": activity.get("max_heartrate"),
        "kudos_count": activity.get("kudos_count"),
        "commute": activity.get("commute"),
        "trainer": activity.get("trainer"),
        "gear_id": activity.get("gear_id"),
        "timezone": activity.get("timezone"),
    }


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)  # the mode above only applies when the file is new
        json.dump(state, f)
    os.replace(tmp, path)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
