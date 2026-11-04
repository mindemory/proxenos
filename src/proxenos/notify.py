"""Notices on the user's phone: one short push when something new waits on them, through ntfy.

ntfy (https://ntfy.sh, open source) hands a message posted to a topic to every phone subscribed
to it, in its app for Android and iOS. It's off unless NTFY_TOPIC is set. The topic is kept as a
secret, like a key, since on ntfy.sh anyone who knows a topic can read what's sent to it: it
should be long and random. NTFY_TOKEN, a secret too, is for a server with access control, and
PROXENOS_NTFY_SERVER names the user's own server (default https://ntfy.sh).

A notice says how many things wait and nothing else ("3 things wait for you."): never a name,
a message's words, a subject or a health detail, since the server is a third party and a notice
shows on a lock screen, where even "1 care item" says something about the user's health. With
PROXENOS_NOTICE_KINDS on, it says how many of each kind ("2 drafts to send and 1 care item wait
on you."). The kinds are what the page's Home asks the user about, counted as it counts them:
drafts to send, care items that are the user's move, project steps waiting for review, and open
tasks overdue or due within SOON_DAYS days. The page suggests a topic of TOPIC_CHARS random
letters and digits after "proxenos-", and setup takes none shorter than MIN_TOPIC.

`proxenos sync` and `proxenos night` call `run` as they finish. A run sends at most one notice,
and only when a count went up since the last one: state/notified.json keeps the counts as of
that notice, lowered as items are dealt with, so the next new one is news again. During quiet
hours (PROXENOS_QUIET_HOURS, default 22:00-08:00 local time, or off) the notice waits, and goes
out on the first run after them if something new still waits. A notice that fails is logged and
tried again on the next run; it never fails the run. `proxenos notify test` sends a test notice.
"""

import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from datetime import time as daytime
from pathlib import Path

from proxenos import config, outbox
from proxenos.clones import projects, work

SERVER = "https://ntfy.sh"
QUIET = "22:00-08:00"
STATE = Path("state", "notified.json")
TITLE = "Proxenos"
TIMEOUT = 15  # seconds to reach the server
SOON_DAYS = 3  # a task due this soon asks for the user, as on Home (web/src/lib/tasks.ts)
STALE_DAYS = 3  # a draft unchanged this long is folded away (web/src/lib/drafts.ts)
STEPS = 20  # of each project's newest steps, looked through for one waiting on the user
MAX_DRAFT_BYTES = 256 * 1024  # a draft file bigger than this isn't one the page reads
# The kinds, in the order a notice names them, each as one and as many.
KINDS = {
    "drafts": ("draft to send", "drafts to send"),
    "care": ("care item", "care items"),
    "steps": ("step to review", "steps to review"),
    "tasks": ("task due soon", "tasks due soon"),
}
# What a notice carries, for docs/privacy.md and the page's Privacy view.
SENDS = (
    "How many things wait on you, and nothing else; with the kinds switched on, how many drafts, "
    "care items, project steps and tasks due soon. Never a name, a message's words, a subject or "
    "a health detail. The server gets the topic and, as with any request, this computer's "
    "internet address."
)
TOPIC = re.compile(r"[A-Za-z0-9_-]{1,64}")  # the names ntfy takes
MIN_TOPIC = 20  # on ntfy.sh anyone who knows a topic reads it: one this short is guessed
TOPIC_CHARS = 24  # of a topic the page makes up (web/src/components/views/Settings.tsx)
_QUIET = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})")
_SETTLED = ("discarded", "sent", "overtaken")  # a draft's statuses once it's dealt with
_NOTES = ("doc", "checklist", "plan", "note")  # kept for the user when addressed to no one
_CARE_ACTIONS = ("done", "waiting", "not_relevant")
_TASK_ACTIONS = ("done", "not_mine", "dismiss")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class Failed(Exception):
    """A notice that didn't go through, with why in words that never hold the topic or token."""


def configured() -> bool:
    """Whether notices are on: a topic is set."""
    config.load()
    return bool(os.environ.get("NTFY_TOPIC", "").strip())


def run(vault: Path, now: datetime | None = None) -> dict[str, int]:
    """Send one notice when something new waits on the user, unless it's quiet hours. Never
    raises: a failure is logged, counted and tried again next run. {} when notices are off."""
    if not configured() or outbox.is_demo(vault):
        return {}
    try:
        return _run(vault, now or datetime.now(UTC))
    except (Exception, SystemExit) as e:  # noqa: BLE001 - a notice is extra, never the run
        _log(f"failed ({_said(e)})")
        return {"notices_sent": 0, "notify_failed": 1}


def _run(vault: Path, now: datetime) -> dict[str, int]:
    path = vault / STATE
    state = _json(path)
    heard = state.get("counts")
    last = {k: v for k, v in heard.items() if _count(v)} if isinstance(heard, dict) else {}
    current = counts(vault, now)
    risen = any(n > last.get(kind, 0) for kind, n in current.items())
    stats = {"notices_sent": 0}
    sent = False
    if risen and quiet(now):
        stats["notices_held"] = 1
    elif risen:
        try:
            send(message(current) or "Something new waits on you.")
            sent = True
            stats["notices_sent"] = 1
        except Failed as e:
            _log(str(e))
            stats["notify_failed"] = 1
    # Sent: these counts are what the user has heard. Not sent: each count only comes down, so
    # what rose stays news until it goes out, and what was dealt with makes room for the next.
    kept = last | {k: n if sent else min(last.get(k, 0), n) for k, n in current.items()}
    if kept != last or sent:
        when = _iso(now) if sent else state.get("sent")
        work._write(path, json.dumps({"counts": kept, "sent": when}, indent=2) + "\n")
    return stats


def counts(vault: Path, now: datetime | None = None) -> dict[str, int]:
    """How many of each kind wait on the user, as the page's Home counts them. A kind whose files
    can't be read is left out, so a broken file is never news."""
    now = now or datetime.now(UTC)
    counters: dict[str, Callable[[], int]] = {
        "drafts": lambda: _drafts(vault, now),
        "care": lambda: _care(vault),
        "steps": lambda: _steps(vault),
        "tasks": lambda: _tasks(vault, now),
    }
    found = {}
    for kind, count in counters.items():
        try:
            found[kind] = count()
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one kind must not stop the rest
            _log(f"couldn't count the {kind} ({_said(e)})")
    return found


def message(counts: dict[str, int], kinds: bool | None = None) -> str | None:
    """The notice's words, a count only: "3 things wait for you." With `kinds` (by default, the
    user's PROXENOS_NOTICE_KINDS), counts by kind: "2 drafts to send and 1 care item wait on
    you." None when nothing waits."""
    waiting = {kind: n for kind in KINDS if (n := counts.get(kind, 0)) > 0}
    if not waiting:
        return None
    if not (kinds_on() if kinds is None else kinds):
        total = sum(waiting.values())
        return f"{total} {'thing waits' if total == 1 else 'things wait'} for you."
    parts = [f"{n} {KINDS[kind][n != 1]}" for kind, n in waiting.items()]
    listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"{listed} {'waits' if sum(waiting.values()) == 1 else 'wait'} on you."


def kinds_on() -> bool:
    """Whether the user turned on saying what kinds wait (PROXENOS_NOTICE_KINDS=on)."""
    return config.env("NOTICE_KINDS").strip().casefold() == "on"


def quiet(now: datetime) -> bool:
    """Whether it's quiet hours where the user is."""
    hours = quiet_hours()
    if hours is None:
        return False
    start, end = hours
    at = now.astimezone().time()
    return start <= at < end if start < end else at >= start or at < end


def quiet_hours() -> tuple[daytime, daytime] | None:
    """The quiet hours, from PROXENOS_QUIET_HOURS (default QUIET); None when they're off. One that
    can't be read is said in the log, and the default holds."""
    text = config.env("QUIET_HOURS").strip() or QUIET
    try:
        return parse_quiet(text)
    except ValueError as e:
        _log(f"{e}; using {QUIET}")
        return parse_quiet(QUIET)


def parse_quiet(text: str) -> tuple[daytime, daytime] | None:
    """Quiet hours as (start, end) in local time, from "22:00-08:00"; None for "off", or for a
    start that's its own end."""
    text = text.strip().lower()
    if text == "off":
        return None
    found = _QUIET.fullmatch(text.replace(" ", ""))
    hour, minute, end_hour, end_minute = map(int, found.groups()) if found else (99,) * 4
    if max(hour, end_hour) > 23 or max(minute, end_minute) > 59:
        raise ValueError(f"quiet hours {text!r}? Give them as 22:00-08:00, or off")
    start, end = daytime(hour, minute), daytime(end_hour, end_minute)
    return None if start == end else (start, end)


def send(text: str) -> str:
    """Post one notice to the topic. The server's host it went to, or Failed saying why."""
    config.load()
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    token = os.environ.get("NTFY_TOKEN", "").strip()
    if not topic:
        raise Failed("no topic is set (NTFY_TOPIC)")
    if not TOPIC.fullmatch(topic):
        raise Failed("the topic can have only letters, digits, - and _, up to 64 of them")
    server = server_address(config.env("NTFY_SERVER"))
    host = urllib.parse.urlsplit(server).netloc
    request = urllib.request.Request(
        f"{server}/{topic}", data=text.encode("utf-8"), method="POST", headers={"Title": TITLE}
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read(4096)
    except urllib.error.HTTPError as e:
        why = {401: "it wants a token", 403: "the token isn't allowed to post there"}
        said = f" ({why[e.code]})" if e.code in why else ""
        raise Failed(f"{host} answered {e.code}{said}") from None
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise Failed(f"couldn't reach {host} ({_said(e, topic, token)})") from None
    return host


def server_address(value: str) -> str:
    """The server as notices go to it: PROXENOS_NTFY_SERVER without a trailing /, else SERVER.
    Only a web address (http or https, with a host) is one."""
    server = value.strip().rstrip("/") or SERVER
    parts = urllib.parse.urlsplit(server)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise Failed(f"the ntfy server {server!r} isn't a web address like {SERVER}")
    return server


def test() -> tuple[bool, str]:
    """Send a test notice: whether it got through, and what to tell the user."""
    if not configured():
        return False, (
            "No topic is set. Save one in Settings (NTFY_TOPIC), and subscribe to it in the "
            "ntfy app."
        )
    try:
        host = send("A test from Proxenos: notices reach this phone.")
    except Failed as e:
        return False, f"The test didn't go through: {e}."
    return True, f"Sent a test through {host}. It should be on your phone now."


def report() -> dict:
    """Whether notices are on, through which server and when they wait, and what one carries,
    for the page's Privacy view. Never the topic or the token."""
    try:
        server = urllib.parse.urlsplit(server_address(config.env("NTFY_SERVER"))).netloc
    except Failed:
        server = ""
    try:
        hours = parse_quiet(config.env("QUIET_HOURS").strip() or QUIET)
    except ValueError:
        hours = parse_quiet(QUIET)
    quiet_said = f"{hours[0]:%H:%M}-{hours[1]:%H:%M}" if hours else None
    return {"on": configured(), "server": server, "quiet": quiet_said, "sends": SENDS}


# ── Counting what waits, as the page does ───────────────────────────────────


def _drafts(vault: Path, now: datetime) -> int:
    """Drafts to send (web/src/lib/drafts.ts isToSend): not sent, discarded or overtaken, not a
    note kept for the user, and changed in the last STALE_DAYS days. Newest file first per id."""
    folder = vault / "clones" / "drafts"
    try:
        entries = [e for e in os.scandir(folder) if e.name.lower().endswith(".md")]
    except OSError:
        return 0
    files = []
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        plain = entry.is_file(follow_symlinks=False) and not entry.name.startswith(".")
        if plain and info.st_size <= MAX_DRAFT_BYTES:
            files.append((info.st_mtime, entry))
    seen, waiting = set(), 0
    for mtime, entry in sorted(files, key=lambda f: (-f[0], f[1].name)):
        try:
            fields = work._front(Path(entry.path).read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError):
            continue
        key = fields.get("id") or entry.name[:-3]
        if key in seen:
            continue
        seen.add(key)
        status = (fields.get("status") or "").strip().lower() or "draft"
        kind, to = (fields.get("kind") or "").strip().lower(), (fields.get("to") or "").strip()
        note = kind in _NOTES and not to
        changed = max(mtime, _stamp(fields.get("created")))
        fresh = now.timestamp() - changed <= STALE_DAYS * 24 * 3600
        waiting += status not in _SETTLED and not note and fresh
    return waiting


def _care(vault: Path) -> int:
    """Care's open items that are the user's move and that they haven't marked on the page."""
    folder = vault / "clones" / "care"
    acted = _acted(folder / "feedback.jsonl", "item_id", _CARE_ACTIONS)
    items = _json(folder / "care.json").get("open_items")
    yours = 0
    for item in _unique(items):
        mine = (item.get("waiting_on") or "me") == "me" and (item.get("status") or "open") == "open"
        yours += mine and item["id"] not in acted
    return yours


def _steps(vault: Path) -> int:
    """Steps on projects that aren't paused, done and waiting for the user to accept or discard."""
    return sum(
        step.get("status") == "ready"
        for project in projects.listed_projects(vault)
        if not project["paused"]
        for step in projects.steps_taken(vault, project["id"], STEPS)
    )


def _tasks(vault: Path, now: datetime) -> int:
    """Open tasks the user hasn't marked, overdue or due within SOON_DAYS days of today."""
    folder = vault / "clones" / "tasks"
    acted = _acted(folder / "feedback.jsonl", "task_id", _TASK_ACTIONS)
    today = now.astimezone().date()
    due = 0
    for task in _unique(_json(folder / "tasks.json").get("tasks")):
        when = task.get("due")
        if (task.get("status") or "open") != "open" or task["id"] in acted:
            continue
        if isinstance(when, str) and _DAY.fullmatch(when):
            try:
                due += (date.fromisoformat(when) - today).days <= SOON_DAYS
            except ValueError:
                continue
    return due


def _unique(items: object) -> list[dict]:
    """The items with an id and a title, the first of each id, as the page reads them."""
    found, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        title = item.get("title")
        if item["id"] in seen or not isinstance(title, str) or not title.strip():
            continue
        seen.add(item["id"])
        found.append(item)
    return found


def _acted(path: Path, key: str, actions: tuple[str, ...]) -> set[str]:
    """The ids the user marked on the page with one of these actions."""
    return {
        entry[key]
        for entry in outbox._jsonl(path)
        if isinstance(entry.get(key), str) and entry.get("action") in actions
    }


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _stamp(text: object) -> float:
    """A draft's "created" as seconds since the epoch, 0 when it has none."""
    if not isinstance(text, str) or not text.strip():
        return 0
    try:
        return datetime.fromisoformat(text.strip()).timestamp()
    except ValueError:
        return 0


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _said(e: BaseException, *hidden: str) -> str:
    """Why, on one line, with anything secret blanked."""
    reason = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
    for secret in hidden:
        if secret:
            reason = reason.replace(secret, "[hidden]")
    return " ".join(reason.split())[:200]


def _log(text: str) -> None:
    print(f"notify: {text}", file=sys.stderr, flush=True)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
