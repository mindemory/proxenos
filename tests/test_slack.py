"""Slack ingester against a fake Web API. The workspace, ids, names and messages are made up."""

import argparse
import copy
import email.message
import io
import json
import stat
import urllib.error
import urllib.request

import pytest

from twin.ingest import slack

ME = "U0001"
USERS = [
    {"id": ME, "name": "kai", "profile": {"real_name": "Kai"}},
    {"id": "U0002", "name": "asha", "profile": {"real_name": "Asha", "display_name": "ash"}},
    {"id": "U0003", "name": "ravi", "profile": {}},
    {"id": "U0004", "name": "meera", "real_name": "Meera"},
]
CHANNELS = [
    {"id": "C0100", "name": "general", "is_channel": True, "is_private": False, "is_member": True},
    {"id": "C0200", "name": "random", "is_channel": True, "is_private": False, "is_member": False},
    {"id": "G0300", "name": "lab", "is_channel": True, "is_private": True, "is_member": True},
    {"id": "D0400", "is_im": True, "user": "U0002"},
    {"id": "G0500", "name": "mpdm-kai--asha--ravi-1", "is_mpim": True, "is_private": True},
]

JAN_31 = "1738367999.000100"  # 2025-01-31T23:59:59Z
FEB_1 = "1738368000.000200"  # 2025-02-01T00:00:00Z, a thread parent
LAST_REPLY = "1738368100.000400"


def msg(ts, user, text, **extra):
    return {"type": "message", "ts": ts, "user": user, "text": text, **extra}


HISTORY = {
    "C0100": [
        msg(JAN_31, "U0002", "hi all"),
        msg(FEB_1, ME, "standup moved", thread_ts=FEB_1, reply_count=2, latest_reply=LAST_REPLY),
        msg("1738368050.000300", "U0003", "", files=[{"name": "plot.png"}, {"mode": "tombstone"}]),
    ],
    "C0200": [msg("1738368060.000100", "U0004", "not joined")],
    "G0300": [msg("1738368200.000100", "U0004", "lab only")],
    "D0400": [msg("1738368300.000100", "U0002", "lunch?"), msg("1738368400.000100", ME, "yes")],
    "G0500": [msg("1738368500.000100", "U0003", "", subtype="channel_join")],
}
REPLIES = {
    ("C0100", FEB_1): [
        msg("1738368060.000350", "U0002", "ok", thread_ts=FEB_1),
        msg(LAST_REPLY, ME, "thanks", thread_ts=FEB_1),
    ],
}


class FakeSlack:
    """Answers Web API calls from the data above, two items per page."""

    def __init__(self):
        self.history = copy.deepcopy(HISTORY)
        self.replies = copy.deepcopy(REPLIES)
        self.calls = []

    def __call__(self, method, params):
        self.calls.append((method, dict(params)))
        if method == "auth.test":
            return {"ok": True, "user_id": ME, "team": "Acme Lab", "team_id": "T0001"}
        if method == "users.list":
            return self.page(params, "members", USERS)
        if method == "conversations.list":
            return self.page(params, "channels", CHANNELS)
        if method == "conversations.history":
            oldest = float(params.get("oldest", 0))
            found = [m for m in self.history[params["channel"]] if float(m["ts"]) > oldest]
            return self.page(params, "messages", sorted(found, key=lambda m: m["ts"])[::-1])
        if method == "conversations.replies":
            channel, ts = params["channel"], params["ts"]
            parent = next(m for m in self.history[channel] if m["ts"] == ts)
            return self.page(params, "messages", [parent] + self.replies[channel, ts])
        raise AssertionError(f"unexpected call to {method}")

    def page(self, params, key, items):
        start = int(params.get("cursor") or 0)
        cursor = str(start + 2) if start + 2 < len(items) else ""
        return {
            "ok": True,
            key: items[start : start + 2],
            "response_metadata": {"next_cursor": cursor},
        }

    def made(self, method):
        return [params for name, params in self.calls if name == method]


def read_vault(vault):
    out = vault / "raw" / "slack" / "acme-lab" / "messages"
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["id"]: r for r in map(json.loads, lines)}


def test_conversations_are_named_and_typed_and_unjoined_channels_skipped(tmp_path):
    stats = slack.ingest(tmp_path, api := FakeSlack())
    assert (stats["read"], stats["added"]) == (9, 9)
    msgs = read_vault(tmp_path)

    assert msgs["C0100/1738368050.000300"] == {
        "id": "C0100/1738368050.000300",
        "ts": "2025-02-01T00:00:50Z",
        "slack_ts": "1738368050.000300",
        "channel_id": "C0100",
        "channel_name": "general",
        "channel_type": "channel",
        "user_id": "U0003",
        "user_name": "ravi",  # no real name, so the handle
        "from_me": False,
        "text": None,
        "thread_ts": None,
        "is_reply": False,
        "subtype": None,
        "files": ["plot.png"],
    }
    assert msgs["C0100/" + JAN_31]["ts"] == "2025-01-31T23:59:59Z"

    dm = msgs["D0400/1738368300.000100"]
    assert (dm["channel_name"], dm["channel_type"]) == ("Asha", "dm")
    assert (dm["user_name"], dm["from_me"]) == ("Asha", False)
    assert msgs["D0400/1738368400.000100"]["from_me"] is True

    lab = msgs["G0300/1738368200.000100"]
    assert (lab["channel_type"], lab["user_name"]) == ("private", "Meera")
    group = msgs["G0500/1738368500.000100"]
    assert (group["channel_type"], group["subtype"]) == ("group_dm", "channel_join")

    assert not any(r["channel_id"] == "C0200" for r in msgs.values())
    assert "C0200" not in {p["channel"] for p in api.made("conversations.history")}


def test_every_list_follows_the_cursor(tmp_path):
    slack.ingest(tmp_path, api := FakeSlack())

    assert [p.get("cursor") for p in api.made("users.list")] == [None, "2"]
    conversations = api.made("conversations.list")
    assert [p.get("cursor") for p in conversations] == [None, "2", "4"]
    assert conversations[0]["types"] == "public_channel,private_channel,mpim,im"
    assert conversations[0]["exclude_archived"] == "false"
    general = [p for p in api.made("conversations.history") if p["channel"] == "C0100"]
    assert [p.get("cursor") for p in general] == [None, "2"]
    # The oldest message only comes back on the second page.
    assert "C0100/" + JAN_31 in read_vault(tmp_path)


def test_thread_replies_come_from_conversations_replies(tmp_path):
    slack.ingest(tmp_path, api := FakeSlack())
    msgs = read_vault(tmp_path)

    # Parent plus two replies is two pages.
    threads = [(p["channel"], p["ts"], p.get("cursor")) for p in api.made("conversations.replies")]
    assert threads == [("C0100", FEB_1, None), ("C0100", FEB_1, "2")]
    parent = msgs["C0100/" + FEB_1]
    assert (parent["thread_ts"], parent["is_reply"]) == (FEB_1, False)
    reply = msgs["C0100/1738368060.000350"]
    assert (reply["thread_ts"], reply["is_reply"], reply["user_name"]) == (FEB_1, True, "Asha")
    assert msgs["C0100/" + LAST_REPLY]["from_me"] is True


def test_incremental_runs_start_from_the_watermark(tmp_path):
    slack.ingest(tmp_path, api := FakeSlack())
    state_path = tmp_path / "state" / "slack_acme-lab.json"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    # The newest ts seen in the channel, which is the thread's latest reply.
    assert json.loads(state_path.read_text())["channels"]["C0100"] == LAST_REPLY

    # Nothing new: a week before the watermark is re-read, nothing changes, no thread refetched.
    api.calls.clear()
    again = slack.ingest(tmp_path, api)
    assert (again["added"], again["updated"]) == (0, 0)
    general = next(p for p in api.made("conversations.history") if p["channel"] == "C0100")
    assert general["oldest"] == "1737763300.000400"  # LAST_REPLY minus seven days
    assert api.made("conversations.replies") == []

    # A new message, and a new reply under the old parent.
    late = "1738400000.000500"
    api.history["C0100"][1].update(reply_count=3, latest_reply=late)
    api.replies["C0100", FEB_1].append(msg(late, "U0002", "late reply", thread_ts=FEB_1))
    api.history["C0100"].append(msg("1738400100.000600", ME, "new"))
    api.calls.clear()
    later = slack.ingest(tmp_path, api)
    assert (later["added"], later["updated"]) == (2, 0)
    assert {p["ts"] for p in api.made("conversations.replies")} == {FEB_1}
    assert json.loads(state_path.read_text())["channels"]["C0100"] == "1738400100.000600"
    assert read_vault(tmp_path)["C0100/" + late]["is_reply"] is True

    api.calls.clear()
    slack.ingest(tmp_path, api, full=True)
    assert all("oldest" not in p for p in api.made("conversations.history"))
    assert {p["ts"] for p in api.made("conversations.replies")} == {FEB_1}


def test_rate_limits_wait_for_retry_after_then_retry(tmp_path):
    api = FakeSlack()
    limits = iter([slack.RateLimited(7), slack.RateLimited(3)])

    def call(method, params):
        if method == "conversations.history" and (limit := next(limits, None)):
            raise limit
        return api(method, params)

    sleeps = []
    slack.ingest(tmp_path, call, sleep=sleeps.append)
    assert sleeps == [7, 3]
    assert len(read_vault(tmp_path)) == 9


class FakeResponse(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(body)
        self.headers = headers


@pytest.mark.parametrize("how", ["http 429", "ok=false body"])
def test_the_http_transport_turns_rate_limits_into_retry_after(monkeypatch, how):
    headers = email.message.Message()
    headers["Retry-After"] = "12"
    body = b'{"ok": false, "error": "ratelimited"}'
    requests = []

    def urlopen(request, timeout):
        requests.append(request)
        if how == "http 429":
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many", headers, io.BytesIO(body)
            )
        return FakeResponse(body, headers)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(slack.RateLimited) as limited:
        slack.http_call("xoxp-fake")("conversations.history", {"channel": "C0100"})
    assert limited.value.retry_after == 12
    assert requests[0].full_url == "https://slack.com/api/conversations.history"
    assert requests[0].get_header("Authorization") == "Bearer xoxp-fake"


def test_a_missing_token_fails_with_a_clear_message(monkeypatch, tmp_path):
    monkeypatch.delenv("SLACK_USER_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="SLACK_USER_TOKEN is not set"):
        slack.run(tmp_path, argparse.Namespace(full=False))
