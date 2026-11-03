"""`proxenos privacy`: what stays on this computer, what went to a model, what's read from
elsewhere and whether notices go to the phone, as JSON for the page's Privacy view.

It's drawn from what the code does rather than from a promise: the vault's folders and their
sizes, the line every model call leaves (llm.calls), the sources connect.py finds set up, the
secrets config.py finds set, and notify.py's settings. So it can be shown, it holds paths,
names, addresses, counts and dates, never a message, a prompt, a token or a key: a call's line
is copied field by field, a source by its names and addresses, a secret by its name, and notices
by the server's host, never the topic.
"""

import math
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import config, connect, keychain, llm, notify, setup

DAYS = 30
NEWEST = 50  # calls listed one by one
HERE, HOSTED = "this computer", "Anthropic"
# The vault's own folders, as the page names them; the rest (its history, the voice model, the
# feed, the inbox) count together as "other".
FOLDERS = ("raw", "memory", "clones", "self", "observations", "state")
# A call's line as it goes out: these fields and no others, numbers only as numbers.
_TEXT = ("at", "step", "model")
# "redacted": the numbers and secrets blanked before a call went to Anthropic (proxenos.redact).
_COUNTS = ("sent_chars", "images", "redacted", "answer_chars", "tokens_in", "tokens_out")
_TEXT_CHARS = 80

# What each part of Proxenos sends a model, in plain words: the README's Privacy list, with the
# steps (as llm's log names them) whose calls each covers, so the page can name a row of the log.
# When what a part sends changes, change it here and in the README together.
SENDS = (
    ("Observers", ("observe",), "Only your side of conversations, never other people's messages."),
    ("Self-model", ("master",), "The observers' notes about you and your reactions on the page."),
    (
        "Feed and advice",
        ("tracker", "advisor"),
        "Your self-model and notes about you, plus public items such as papers and news.",
    ),
    (
        "Tasks",
        ("tasks",),
        (
            "Conversations you're part of, the opening of each draft waiting on you, and what "
            "you've told Proxenos."
        ),
    ),
    (
        "Care",
        ("care",),
        (
            "Only records about getting health care, with people replaced by labels and phone, "
            "account and member numbers blanked."
        ),
    ),
    (
        "Drafts",
        ("work", "research", "voicemodel"),
        (
            "The recent conversation in each chat waiting on your reply, what your memory holds "
            "about that person and the records around those it opens, your rules and notes, and "
            "the coming week's calendar."
        ),
    ),
    (
        "Compare",
        ("compare",),
        (
            "Only to the two models you compare: for each of your recent replies, what its "
            "draft would have been sent just before you replied (the conversation, your own "
            "writing, your rules, notes and calendar), without what memory finds, and never the "
            "reply itself."
        ),
    ),
    (
        "Writing rules",
        ("voice",),
        (
            "Drafts you changed beside what you sent instead, and some of your own sent messages "
            "to check each rule on, never other people's messages."
        ),
    ),
    (
        "Choices",
        ("choices",),
        (
            "Mail and Slack posts that announce an opening, with who sent each, the openings you "
            "kept from Ask, and what your time goes to."
        ),
    ),
    (
        "Projects",
        ("projects", "steps", "agent"),
        (
            "The records that name each project or come from its people, and its code's commit "
            "messages and changed documents. A step gives its code and data to the runner."
        ),
    ),
    (
        "Errands",
        ("errands",),
        "The newest records naming the person to reach, your earlier emails with a CV, and the CV.",
    ),
    ("Ask", ("ask",), "What you type or paste, its screenshots, and the records memory finds."),
    (
        "Think",
        ("think",),
        (
            "What you write in a thread and what it started from (a draft, a project, a day), "
            "your self-model and what you've told Proxenos, the journal's last few briefs, and "
            "the records memory finds."
        ),
    ),
    (
        "Network",
        ("network",),
        (
            "The people you know by name, how you know each and what you share, and your notes' "
            "titles."
        ),
    ),
    ("Watch", ("watch",), "The films you've logged and how you rated them."),
    (
        "Journal",
        ("journal",),
        (
            "The day's lines: tasks' titles, the chats you wrote in, what you told Proxenos, "
            "commit messages, tomorrow's calendar and care's open items."
        ),
    ),
    (
        "Rhythms",
        ("rhythms",),
        "Only the names of the artists you listen to, to label each with a genre and moods.",
    ),
    (
        "Life",
        ("life",),
        (
            "What you marked not true in a month's diary and your own text where you edited it, "
            "what you told Proxenos, its care timeline, the notes about you and its days: "
            "who you wrote to, with the opening of your own words, and who wrote to you, events, "
            "notes' titles, activity (walks and listening only as counts), health records' titles "
            "and the journal's briefs, never other people's messages."
        ),
    ),
    (
        "Forms",
        ("forms",),
        (
            "A form's labels and the records memory finds for them, never an SSN, an account "
            "number or a signature."
        ),
    ),
    (
        "Calls",
        ("calls", "callserver"),
        "On a call you start, what the other side says. The call's audio goes through Twilio.",
    ),
)


def report(vault: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    return {
        "now": _iso(now),
        "here": here(vault),
        "sent": sent(vault, now),
        "fetched": fetched(vault),
        # What leaves for the user's own phone, when they switch it on: counts only.
        "notices": notify.report(),
    }


def here(vault: Path) -> dict:
    """What stays on this computer: the vault, by folder, and the secrets kept, by name."""
    folders = _sizes(vault)
    return {
        "vault": {
            "path": setup._shown(vault),
            "exists": vault.is_dir(),
            "bytes": sum(folders.values()),
            "folders": folders,
            "cloud": setup.cloud(vault),
        },
        "filevault": filevault(),
        "settings_file": setup._shown(config.SETTINGS_FILE),
        "secret_store": keychain.store(),
        "secrets": [{"name": s["name"], "from": s["from"]} for s in setup.secrets() if s["set"]],
    }


def sent(vault: Path, now: datetime) -> dict:
    """What went to a model in the last DAYS days, by where it ran and by step, the newest calls
    one by one, and what each part sends."""
    name = config.env("MODEL", llm.DEFAULT_MODEL)
    local = name.startswith(llm.LOCAL)
    since = _iso(now - timedelta(days=DAYS))
    calls = [_call(line) for line in llm.calls(vault, since)]
    parts = {step: part for part, steps, _ in SENDS for step in steps}
    by_step: dict[str, list[dict]] = {}
    for call in calls:
        by_step.setdefault(call["step"], []).append(call)
    return {
        "model": {
            "name": llm.bare(name),
            "kind": "local" if local else "api" if llm.configured() else "none",
            "voice": config.env("VOICE_MODEL").strip() or None,
        },
        "days": DAYS,
        "since": since,
        "totals": _totals(calls),
        "by_where": {
            where: _totals([c for c in calls if c["where"] == where]) for where in (HERE, HOSTED)
        },
        "by_step": sorted(
            (
                {"step": step, "part": parts.get(step), **_totals(rows)}
                for step, rows in by_step.items()
            ),
            key=lambda row: (-row["calls"], row["step"]),
        ),
        "recent": calls[::-1][:NEWEST],
        "sends": [
            {"part": part, "steps": list(steps), "sends": what} for part, steps, what in SENDS
        ],
    }


def fetched(vault: Path) -> dict:
    """What's read from elsewhere: each connected source with its accounts' names and addresses,
    and whether links in chats are read. They are whenever a model is set up, as replies are then
    drafted, and only from public hosts (links.py)."""
    sources = [
        {
            "id": str(source["id"]),
            "how": str(source["how"]),
            "last_read": source.get("last_read"),
            "accounts": [
                {"name": str(a.get("name", "")), "address": str(a.get("address", ""))}
                for a in source.get("accounts") or []
            ],
            "workspaces": [str(w) for w in source.get("workspaces") or []],
        }
        for source in connect.report(vault)["sources"]
        if source.get("connected")
    ]
    return {"sources": sources, "links": llm.configured()}


def filevault() -> bool | None:
    """Whether FileVault encrypts this Mac's disk; None elsewhere, or when fdesetup can't say."""
    said = _fdesetup()
    if said is None:
        return None
    if "FileVault is On" in said:
        return True
    if "FileVault is Off" in said:
        return False
    return None


def _fdesetup() -> str | None:
    """What `fdesetup status` says, or None off a Mac or when it can't be run."""
    if sys.platform != "darwin":
        return None
    try:
        done = subprocess.run(
            ["fdesetup", "status"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout


def _sizes(vault: Path) -> dict[str, int]:
    """Bytes under each of the vault's folders, and the rest as "other". Links aren't followed."""
    sizes = dict.fromkeys([*FOLDERS, "other"], 0)
    try:
        entries = list(os.scandir(vault))
    except OSError:
        return sizes
    for entry in entries:
        own = entry.name in FOLDERS and entry.is_dir(follow_symlinks=False)
        sizes[entry.name if own else "other"] += _bytes(entry)
    return sizes


def _bytes(entry: os.DirEntry) -> int:
    try:
        if entry.is_dir(follow_symlinks=False):
            with os.scandir(entry.path) as inside:
                return sum(_bytes(e) for e in inside)
        return entry.stat(follow_symlinks=False).st_size
    except OSError:
        return 0


def _call(line: dict) -> dict:
    """One line of the calls log, with only the fields it's meant to have."""
    call = {key: _text(line.get(key)) for key in _TEXT}
    call["step"] = call["step"] or "proxenos"  # as llm names a call from outside a module
    call["where"] = HERE if line.get("where") == HERE else HOSTED  # unsure counts as sent away
    call |= {key: _count(line.get(key)) for key in _COUNTS}
    seconds = line.get("seconds")
    is_number = isinstance(seconds, int | float) and not isinstance(seconds, bool)
    call["seconds"] = round(seconds, 1) if is_number and math.isfinite(seconds) else None
    call["ok"] = line.get("ok") is True
    return call


def _totals(calls: list[dict]) -> dict:
    return {
        "calls": len(calls),
        "failed": sum(not c["ok"] for c in calls),
        "hosted": sum(c["where"] == HOSTED for c in calls),
        **{key: sum(c[key] or 0 for c in calls) for key in _COUNTS},
    }


def _text(value: object) -> str:
    return value[:_TEXT_CHARS] if isinstance(value, str) else ""


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
