"""Slack messages through the Web API with a user token.

Reads every conversation the token's user is in: public channels they've joined, private
channels, DMs and group DMs. A member who isn't an admin can only reach their DMs with a user
token (xoxp-...). Tokens come from SLACK_USER_TOKEN and any SLACK_USER_TOKEN_<suffix>, one
per workspace. Each workspace gets its own stream under raw/slack/<team>/messages.

Runs are incremental per channel. State keeps the newest ts seen in each one, and the next run
asks conversations.history for what came after it, starting a week early. Replies don't appear
in channel history, so the parents of recent threads have to be seen again to notice that their
latest_reply moved past the watermark. Those threads are re-read with conversations.replies. A
thread that wakes up after more than a week is only caught by --full, which ignores the state
and reads everything. Records merge by id, so the overlap is harmless.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from twin.store import merge_monthly

API_URL = "https://slack.com/api/"
TOKEN_ENV = "SLACK_USER_TOKEN"

# call(method, params) posts one Web API method and returns its JSON body, raising RateLimited
# when Slack says to back off. http_call makes the real one; tests pass a fake.
Call = Callable[[str, dict], dict]

_TYPES = "public_channel,private_channel,mpim,im"
_PAGE_SIZE = 200
_LOOKBACK_SECONDS = 7 * 24 * 3600
# Slack sends Retry-After with every 429, so this is only a fallback.
_DEFAULT_RETRY_AFTER = 30


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class SlackError(RuntimeError):
    pass


def http_call(token: str) -> Call:
    def call(method: str, params: dict) -> dict:
        request = urllib.request.Request(
            API_URL + method,
            data=urllib.parse.urlencode(params).encode(),
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body, headers = json.load(response), response.headers
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            body, headers = {"ok": False, "error": "ratelimited"}, e.headers
        if body.get("error") == "ratelimited":
            raise RateLimited(float(headers.get("Retry-After") or _DEFAULT_RETRY_AFTER))
        return body

    return call


def ingest(
    vault: Path, call: Call, full: bool = False, sleep: Callable[[float], None] = time.sleep
) -> dict[str, int]:
    slack = _Client(call, sleep)
    auth = slack.get("auth.test")
    team = _slug(auth["team"]) or auth["team_id"].lower()
    out = vault / "raw" / "slack" / team / "messages"
    state_path = vault / "state" / f"slack_{team}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    watermarks = state.setdefault("channels", {})

    try:
        users = {u["id"]: _user_name(u) for u in slack.pages("users.list", "members")}
    except SlackError:
        # Without users:read, names stay unresolved but every message still comes in.
        users = {}
    listed = slack.pages("conversations.list", "channels", types=_TYPES, exclude_archived="false")
    channels = [_channel(c, users) for c in listed if _is_mine(c)]

    totals = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    for channel in channels:
        old = watermarks.get(channel["id"])
        messages, newest = _read_channel(slack, channel["id"], None if full else old)
        if messages:
            records = [_record(m, channel, users, auth["user_id"]) for m in messages]
            for key, value in merge_monthly(records, out).items():
                totals[key] += value
        if newest:
            # Saved after each channel is written, so an interrupted backfill resumes there.
            watermarks[channel["id"]] = max(filter(None, [old, newest]), key=Decimal)
            _save_state(state_path, state)
    return totals


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--full", action="store_true", help="ignore saved state, re-read all")
    parser.add_argument("--workspace", help="only the token whose env name ends with this")


def tokens() -> dict[str, str]:
    """Env var name → token, for SLACK_USER_TOKEN and every SLACK_USER_TOKEN_<suffix>."""
    return {
        name: value.strip()
        for name, value in sorted(os.environ.items())
        if (name == TOKEN_ENV or name.startswith(TOKEN_ENV + "_")) and value.strip()
    }


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    found = tokens()
    if args.workspace:
        found = {k: v for k, v in found.items() if k.lower().endswith(args.workspace.lower())}
    if not found:
        raise SystemExit(f"{TOKEN_ENV} is not set. Put a Slack user OAuth token (xoxp-...) in .env")
    totals: dict[str, int] = {"workspaces": 0, "workspaces_failed": 0}
    for name, token in found.items():
        try:
            stats = ingest(vault, http_call(token), full=args.full)
        except (SystemExit, SlackError, OSError) as e:  # one bad token must not stop the rest
            if "missing_scope" in str(e):
                # A token that can't read messages (e.g. an app configuration token): counted,
                # not reported every run; slackdump archives cover those workspaces instead.
                totals["workspaces_without_read_access"] = (
                    totals.get("workspaces_without_read_access", 0) + 1
                )
                continue
            print(f"slack: {name} failed: {e}", file=sys.stderr)
            totals["workspaces_failed"] += 1
            continue
        totals["workspaces"] += 1
        for key, value in stats.items():
            totals[key] = totals.get(key, 0) + value
    return totals


class _Client:
    """Web API calls that wait out rate limits and follow cursors."""

    def __init__(self, call: Call, sleep: Callable[[float], None]):
        self.call, self.sleep = call, sleep

    def get(self, method: str, **params) -> dict:
        while True:
            try:
                body = self.call(method, params)
            except RateLimited as e:
                self.sleep(e.retry_after)
                continue
            if body.get("ok"):
                return body
            needed = f" (needs scope {body['needed']})" if body.get("needed") else ""
            raise SlackError(f"{method}: {body.get('error')}{needed}")

    def pages(self, method: str, key: str, **params) -> Iterator[dict]:
        while True:
            body = self.get(method, limit=_PAGE_SIZE, **params)
            yield from body.get(key, [])
            params["cursor"] = (body.get("response_metadata") or {}).get("next_cursor")
            if not params["cursor"]:
                return


def _read_channel(
    slack: _Client, channel_id: str, watermark: str | None
) -> tuple[list[dict], str | None]:
    params = {"channel": channel_id}
    if watermark:
        params["oldest"] = str(Decimal(watermark) - _LOOKBACK_SECONDS)
    messages = list(slack.pages("conversations.history", "messages", **params))
    # The next watermark comes from history alone (latest_reply included), never from replies
    # fetched afterwards, so a message posted in between can't fall behind it.
    seen = [m["ts"] for m in messages]
    seen += [m["latest_reply"] for m in messages if "latest_reply" in m]

    replies = []
    for parent in messages:
        latest = parent.get("latest_reply", parent["ts"])
        fresh = watermark is None or Decimal(latest) > Decimal(watermark)
        if parent.get("reply_count") and fresh:
            thread = slack.pages(
                "conversations.replies", "messages", channel=channel_id, ts=parent["ts"]
            )
            replies += [m for m in thread if m["ts"] != parent["ts"]]
    return messages + replies, max(seen, key=Decimal, default=None)


def _is_mine(channel: dict) -> bool:
    # A user token lists every public channel in the workspace. Everything else it lists
    # (private channels, DMs, group DMs) the user is already in.
    return bool(
        channel.get("is_im")
        or channel.get("is_mpim")
        or channel.get("is_private")
        or channel.get("is_member")
    )


def _channel(channel: dict, users: dict[str, str | None]) -> dict:
    if channel.get("is_im"):
        return {"id": channel["id"], "name": users.get(channel.get("user")), "type": "dm"}
    if channel.get("is_mpim"):
        kind = "group_dm"
    else:
        kind = "private" if channel.get("is_private") else "channel"
    return {"id": channel["id"], "name": channel.get("name") or None, "type": kind}


def _user_name(user: dict) -> str | None:
    profile = user.get("profile") or {}
    return (
        profile.get("real_name")
        or user.get("real_name")
        or profile.get("display_name")
        or user.get("name")
        or None
    )


def _record(m: dict, channel: dict, users: dict[str, str | None], me: str) -> dict:
    user_id = m.get("user")
    # Slack Connect users aren't in users.list and bots have no user, but messages carry names.
    user_name = (
        users.get(user_id) or (m.get("user_profile") or {}).get("real_name") or m.get("username")
    )
    thread_ts = m.get("thread_ts")
    ts = datetime.fromtimestamp(float(m["ts"]), UTC)
    return {
        "id": f"{channel['id']}/{m['ts']}",
        "ts": ts.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "slack_ts": m["ts"],
        "channel_id": channel["id"],
        "channel_name": channel["name"],
        "channel_type": channel["type"],
        "user_id": user_id,
        "user_name": user_name or None,
        "from_me": user_id == me,
        "text": m.get("text") or None,
        "thread_ts": thread_ts,
        "is_reply": thread_ts is not None and thread_ts != m["ts"],
        "subtype": m.get("subtype"),
        "files": [f["name"] for f in m.get("files", []) if f.get("name")] or None,
    }


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
