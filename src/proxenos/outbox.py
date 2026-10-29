"""The outbox: replies that go out on their own, within rules the user sets on the Drafts page.

Off until the user switches it on, and then only per app ("channel"), and only for an app whose
replies have earned it: at least min_measured of them measured (fidelity.py) and, on average,
min_closeness of each draft still in what the user then sent. A reply qualifies only when it is
a draft nobody has touched, for one person (never a group), with no [placeholder] left and
nothing it asks the user, and only while its chat is still waiting on exactly the messages it
answers. A qualifying reply is queued at one sync and goes out at the next, so the user has
until then (about 15 minutes) to cancel it on the page; at most daily_limit go out a day.

How each app sends ("routes"): email through the Mail app (it replies in the thread, from the
account the mail came to, as if the user pressed Reply); Instagram, Messenger, X and LinkedIn,
and WhatsApp when it's added there, through Beeper Desktop's local API. Slack has none yet.

Files in clones/outbox/: rules.json (the page writes it; read as strictly as the page reads it),
cancelled.jsonl (the page appends), state.json (written here each sync: routes, track record,
what has earned sending, the queue) and log.jsonl (every attempt, sent or not). A reply that
goes out is marked sent, as if the user had pressed Sent on the page.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import chats
from proxenos.clones import work
from proxenos.ingest import beeper

CHANNELS = ("email", "whatsapp", "slack", "instagram", "messenger", "x", "linkedin")
_SOURCE_CHANNEL = {"facebook": "messenger", "twitter": "x"}  # a chat source by its channel
WAIT = timedelta(minutes=10)  # queued now, sent at the first sync after this
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,80}\]")
DEFAULT_RULE = {"on": False, "min_closeness": 0.9, "min_measured": 5}

Send = Callable[[dict, str], None]  # (the draft's chat, the text) → sent, or raises


def run(vault: Path, now: datetime | None = None, senders: dict[str, Send] | None = None) -> dict:
    """One sync's turn: send what was queued and is still fine to send, then queue what now
    qualifies, and write the state the page shows."""
    now = now or datetime.now(UTC)
    folder = vault / "clones" / "outbox"
    rules = read_rules(folder / "rules.json")
    routes = _routes()
    closeness = _closeness(vault)
    earned = {
        ch: closeness.get(ch, {}).get("n", 0) >= rule["min_measured"]
        and closeness.get(ch, {}).get("mean", 0) >= rule["min_closeness"]
        for ch, rule in rules["channels"].items()
    }
    allowed = {
        ch
        for ch, rule in rules["channels"].items()
        if rules["enabled"] and rule["on"] and earned[ch] and routes.get(ch)
    }
    cancelled = {e.get("draft_id") for e in _jsonl(folder / "cancelled.jsonl")}
    log = _jsonl(folder / "log.jsonl")
    today = now.date().isoformat()
    sent_today = sum(1 for e in log if e.get("ok") and str(e.get("at", "")).startswith(today))
    previous = _json(folder / "state.json") or {}
    replies = {r["id"]: r for r in _replies(vault, now)}  # the drafts that could go out now

    stats = {"outbox_sent": 0, "outbox_failed": 0}
    queue = []
    for item in previous.get("queue", []):
        draft = replies.get(item.get("draft_id"))
        if item.get("draft_id") in cancelled or not draft or draft["channel"] not in allowed:
            continue  # cancelled, changed, answered, or no longer allowed: it doesn't go
        if item.get("sends_at", "") > _iso(now):
            queue.append(item)
            continue
        if sent_today >= rules["daily_limit"]:
            queue.append(item)  # waits for tomorrow's allowance
            continue
        route = routes[draft["channel"]]
        try:
            ((senders or {}).get(route) or SENDERS[route])(draft["thread"], draft["text"])
        except Exception as e:  # noqa: BLE001 - one failure is logged; it must not stop the sync
            _log(folder, draft, route, now, error=" ".join(str(e).split())[:300])
            stats["outbox_failed"] += 1
            continue
        _log(folder, draft, route, now)
        _mark_sent(draft["path"])
        sent_today += 1
        stats["outbox_sent"] += 1

    waiting = {item["draft_id"] for item in queue}
    for draft in replies.values():
        if draft["channel"] in allowed and draft["id"] not in waiting | cancelled:
            queue.append(
                {
                    "draft_id": draft["id"],
                    "channel": draft["channel"],
                    "to": draft["to"],
                    "queued_at": _iso(now),
                    "sends_at": _iso(now + WAIT),
                }
            )
    state = {
        "generated": _iso(now),
        "routes": routes,
        "closeness": closeness,
        "earned": earned,
        "queue": queue,
        "sent_today": sent_today,
    }
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write(folder / "state.json", json.dumps(state, ensure_ascii=False, indent=1))
    return stats | {"outbox_queued": len(queue)}


def read_rules(path: Path) -> dict:
    """rules.json as the page reads it: a switch is on only when exactly true, and a number
    missing or outside the page's limits is its default, the stricter value."""
    raw = _json(path) or {}
    rules = {"enabled": raw.get("enabled") is True, "daily_limit": 10, "channels": {}}
    if _int(raw.get("daily_limit"), 1, 50):
        rules["daily_limit"] = raw["daily_limit"]
    given = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    for ch in CHANNELS:
        c = given.get(ch) if isinstance(given.get(ch), dict) else {}
        rule = dict(DEFAULT_RULE, on=c.get("on") is True)
        if isinstance(c.get("min_closeness"), int | float) and 0.5 <= c["min_closeness"] <= 1:
            rule["min_closeness"] = float(c["min_closeness"])
        if _int(c.get("min_measured"), 1, 100):
            rule["min_measured"] = c["min_measured"]
        rules["channels"][ch] = rule
    return rules


def _replies(vault: Path, now: datetime) -> list[dict]:
    """The reply drafts that could go out: nobody has touched them, they're for one person,
    nothing is left to fill in or ask, and their chat still waits on what they answer."""
    folder = vault / "clones" / "drafts"
    edited = work._latest(folder / "feedback.jsonl", "draft_id", ("edit",))
    current = {work.reply_key(c): c for c in chats.waiting(vault, now)}
    found = []
    for path in sorted(folder.glob("reply-*.md")):
        text = path.read_text(encoding="utf-8")
        fields, front = work._front(text) or {}, work._FRONT.match(text)
        chat = current.get(path.stem)
        if not front or not chat or fields.get("status") != "draft" or path.stem in edited:
            continue
        body = text[front.end() :].strip()
        if not body or _PLACEHOLDER.search(body) or json.loads(fields.get("asks") or "[]"):
            continue
        if chat["source"] == "slack" and "/" in chat["chat"].split("/", 1)[1]:
            continue  # a channel thread, not a direct message
        found.append(
            {
                "id": path.stem,
                "path": path,
                "channel": _SOURCE_CHANNEL.get(chat["source"], chat["source"]),
                "to": fields.get("to", ""),
                "thread": {"source": chat["source"], "chat": chat["chat"], "last": chat["id"]},
                "text": body,
            }
        )
    return found


def _routes() -> dict[str, str | None]:
    """How each app can send from this Mac now, or None."""
    routes: dict[str, str | None] = dict.fromkeys(CHANNELS)
    if shutil.which("osascript") and Path("/System/Applications/Mail.app").exists():
        routes["email"] = "apple_mail"
    if token := os.environ.get("BEEPER_ACCESS_TOKEN"):
        try:
            networks = {str(a.get("network", "")).lower() for a in _beeper(token)("/v1/accounts")}
        except (SystemExit, OSError, ValueError):
            networks = set()
        for ch, names in _BEEPER_NETWORKS.items():
            if networks & names:
                routes[ch] = "beeper"
    return routes


_BEEPER_NETWORKS = {
    "whatsapp": {"whatsapp"},
    "instagram": {"instagram"},
    "messenger": {"messenger", "facebook messenger", "facebook"},
    "x": {"x", "twitter", "x (twitter)"},
    "linkedin": {"linkedin"},
}


def _closeness(vault: Path) -> dict:
    """The track record per app, from fidelity.json's per-source means."""
    data = _json(vault / "clones" / "drafts" / "fidelity.json") or {}
    return {
        _SOURCE_CHANNEL.get(source, source): s
        for source, s in (data.get("by_source") or {}).items()
    }


# How each route sends.


def _send_mail(thread: dict, text: str) -> None:
    """Reply in the thread with the Mail app: to the message the reply answers, found by its
    Message-ID, so it goes from the account that mail came to. A "Subject:" line is dropped."""
    body = re.sub(r"^\s*subject\s*:.*\n+", "", text, count=1, flags=re.IGNORECASE)
    message_id = thread["last"].strip("<>")
    script = """on run argv
    tell application "Mail"
        set found to (every message of inbox whose message id is (item 1 of argv))
        if found is {} then error "the mail this answers isn't in the Mail inbox"
        set answer to reply (item 1 of found) with opening window false
        set content of answer to (item 2 of argv)
        send answer
    end tell
end run"""
    done = subprocess.run(
        ["osascript", "-e", script, message_id, body],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(f"Mail: {done.stderr.strip()[:200]}")


def send_mail(address: str, subject: str, body: str, attachment: Path | None = None) -> None:
    """A new email with the Mail app, from its default account or PROXENOS_MAIL_FROM, with one
    file attached. Only an errand's Send calls it, for the one message the user pressed it on."""
    script = """on run argv
    set attached to missing value
    if (item 4 of argv) is not "" then set attached to (POSIX file (item 4 of argv)) as alias
    tell application "Mail"
        set m to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv), visible:false}
        tell m
            make new to recipient at end of to recipients with properties {address:(item 1 of argv)}
            if (item 5 of argv) is not "" then set sender to (item 5 of argv)
            if attached is not missing value then
                make new attachment with properties {file name:attached} at after the last paragraph
            end if
        end tell
        delay 3
        send m
    end tell
end run"""
    done = subprocess.run(
        [
            "osascript",
            "-e",
            script,
            address,
            subject,
            body + "\n",
            str(attachment or ""),
            os.environ.get("PROXENOS_MAIL_FROM", ""),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(f"Mail: {done.stderr.strip()[:200]}")


def _send_beeper(thread: dict, text: str) -> None:
    """Send in the chat through Beeper: a chat read through Beeper by its id, a WhatsApp chat by
    the phone number in its id."""
    fetch = _beeper(os.environ.get("BEEPER_ACCESS_TOKEN", ""))
    chat_id = (
        thread["chat"].removeprefix("beeper:") if thread["chat"].startswith("beeper:") else None
    )
    if chat_id is None and thread["source"] == "whatsapp":
        chat_id = _beeper_whatsapp_chat(fetch, thread["chat"])
    if not chat_id:
        raise RuntimeError("no Beeper chat for this conversation")
    beeper_post = _beeper(os.environ.get("BEEPER_ACCESS_TOKEN", ""), method="POST")
    beeper_post(f"/v1/chats/{urllib.parse.quote(chat_id, safe='')}/messages", {"text": text})


def _beeper_whatsapp_chat(fetch: Callable, jid: str) -> str | None:
    """The Beeper chat with the WhatsApp contact whose number is in `jid` (digits@s.whatsapp.net)."""
    digits = jid.split("@")[0]
    if not digits.isdigit():
        return None
    page = fetch("/v1/chats?limit=200")
    for chat in page.get("items") or []:
        if "whatsapp" not in str(chat.get("network", "")).lower() or chat.get("type") != "single":
            continue
        people = (chat.get("participants") or {}).get("items") or []
        if any(re.sub(r"\D", "", str(p.get("phoneNumber") or "")) == digits for p in people):
            return chat["id"]
    return None


def _beeper(token: str, method: str = "GET") -> Callable:
    """A Beeper Desktop API call, as the reader makes them, or a POST with a JSON body."""
    if method == "GET":
        return beeper._fetcher(token)

    def post(path: str, body: dict) -> dict:
        request = urllib.request.Request(
            beeper.BASE + path,
            json.dumps(body).encode(),
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    return post


SENDERS: dict[str, Send] = {"apple_mail": _send_mail, "beeper": _send_beeper}


# Files.


def _mark_sent(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    _write(path, re.sub(r"(?m)^status:.*$", "status: sent", text, count=1))


def _log(folder: Path, draft: dict, route: str, now: datetime, error: str | None = None) -> None:
    entry = {
        "draft_id": draft["id"],
        "channel": draft["channel"],
        "to": draft["to"],
        "at": _iso(now),
        "via": route,
        "ok": error is None,
        "error": error,
    }
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (folder / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    (folder / "log.jsonl").chmod(0o600)


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            found.append(entry)
    return found


def _int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
