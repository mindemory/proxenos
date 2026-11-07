"""`proxenos privacy`: what stays on this computer, what went to a model, what's read from
elsewhere and whether notices go to the phone, as JSON for the page's Privacy view.

It's drawn from what the code does rather than from a promise: the vault's folders and their
sizes, the line every model call leaves (llm.calls), the sources connect.py finds set up, the
secrets config.py finds set, and notify.py's settings. So it can be shown, it holds paths,
names, addresses, counts and dates, never a message, a prompt, a token or a key: a call's line
is copied field by field, a source by its names and addresses, a secret by its name, notices by
the server's host, never the topic, and the search engine for lookups by its host, never a key.
"""

import math
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import config, connect, keychain, llm, lookup, musicbrainz, notify, setup

DAYS = 30
NEWEST = 50  # calls listed one by one
HERE, HOSTED = "this computer", "Anthropic"
# Where a call may have run, as llm.where says: here, or at the provider whose key is set.
WHERES = (HERE, HOSTED, "OpenAI", "Google")
# The vault's own folders, as the page names them; the rest (its history, the voice model, the
# feed, the inbox) count together as "other".
FOLDERS = ("raw", "memory", "clones", "self", "observations", "state")
# A call's line as it goes out: these fields and no others, numbers only as numbers.
_TEXT = ("at", "step", "model")
# "redacted": the numbers and secrets blanked before a call went to a hosted model (proxenos.redact).
_COUNTS = ("sent_chars", "images", "redacted", "answer_chars", "tokens_in", "tokens_out")
_TEXT_CHARS = 80

# What each part of Proxenos sends a model, in plain words: docs/privacy.md's list, with the
# steps (as llm's log names them) whose calls each covers, so the page can name a row of the log.
# When what a part sends changes, change it here and in docs/privacy.md together.
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
            "about that person and the records around those it opens, your rules and notes, "
            "the coming week's calendar, and, when Care has one, its short summary of your own "
            "health care, marked for use only in a chat that asks about it."
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
        "Jobs",
        ("jobs",),
        (
            "Job leads, recruiters' and founders' messages to you among them, your self-model, "
            "your CVs, the people you know at each company, and your earlier messages with the "
            "person a first step goes to."
        ),
    ),
    (
        "Projects",
        ("projects", "steps", "agent"),
        (
            "The records that name each project or come from its people, its code's commit "
            "messages and changed documents, and its last status and log, without anyone's "
            "health. A step gives its code and data to the runner, and "
            "one you approved from others' comments on the manuscript's copy, those comments."
        ),
    ),
    (
        "Peer review",
        ("review",),
        (
            "Only for a review you start, or one a project you opted in starts: the project's "
            "manuscript and its code and data descriptions from its repository, its name, "
            "description and brief, and your name, to spot it outside the title block, to the "
            "review model, Claude unless you choose another; the "
            "reviews, plan and letter go back to it in later rounds. Never a message from your "
            "vault. The works a reviewer suggests are looked up by title, first author and DOI at "
            "Crossref, DataCite, arXiv and OpenAlex."
        ),
    ),
    (
        "Errands",
        ("errands",),
        (
            "The newest records naming the person to reach (your Slack DMs with them among "
            "them), your earlier emails with a CV, the CV, and your own messages in your chat "
            "with them to write like. One for Slack or WeChat is only written to copy there."
        ),
    ),
    (
        "Offers",
        ("offers",),
        (
            "Only for a comparison you start: what each person or firm wrote you about it, with "
            "what you wrote them, to read their offer; the offers as read, to say what to compare "
            "them on; and, to draft what to ask each, your conversation with them, what they "
            "offered and what's missing, that someone else offers less (never who), your rules "
            "and your own writing."
        ),
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
            "The people you know by name, how you know each and what you share, your notes' "
            "titles, and the ideas it gave before and how you took them."
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
        ("rhythms", "portrait", "mood"),
        (
            "The names of the artists you listen to, to label each with a genre and moods. Only "
            "to a model on this computer, never a hosted one: your own messages and the mail you "
            "sent, a month's days at a time, to name each day's feelings, and a month's numbers "
            "and artists' names, to write its card. Never other people's messages."
        ),
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
    (
        "Google Docs",
        ("gdocs",),
        (
            "Nothing to a model. The manuscript's text goes to your own Google Drive when you "
            "click Open in Google Docs, and comes back when you click Bring back its changes. "
            "Its comments are other people's words: shown on the page, never sent to a model."
        ),
    ),
    (
        "Looking people up",
        ("lookup",),
        (
            "Nothing to a model. When an errand (an offer's reply among them), Ask or Think needs "
            "someone's email address and "
            "your records have none, only that person's name and where they are go to the search "
            "engine, and only that place's own public pages are read. Nothing about you."
        ),
    ),
    (
        "Checking a paper's references",
        ("preprint",),
        (
            "Nothing to a model. Only when you check a paper's references: each one's DOI or "
            "arXiv id, or its title and first author's surname, go to Crossref, DataCite, arXiv "
            "and OpenAlex, and a web page it cites is fetched at its own address. Nothing about "
            "you, and none of the paper's text."
        ),
    ),
    (
        "Project folders",
        ("folders",),
        (
            "Nothing to a model. Only once you set a folder for them in Settings, and only to "
            "that folder, which your cloud drive then uploads: each project's manuscript, where "
            "it stands (which sums up your messages about it), its brief and its open drafts, as "
            "Word files. Proxenos shares none of it and reads nothing else there."
        ),
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
    name = config.env("MODEL") or llm.default()
    local = name.startswith(llm.LOCAL)
    fast = config.env("FAST_MODEL").strip()
    fast = fast if fast.startswith(llm.LOCAL) else ""
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
            # Who answers for it when it isn't on this computer: Anthropic, OpenAI or Google.
            "host": None if local else llm.where(name),
            "voice": config.env("VOICE_MODEL").strip() or None,
            # The model for light jobs, when it's on this computer (llm.fast says so, by step).
            "fast": fast and llm.bare(fast) or None,
        },
        "days": DAYS,
        "since": since,
        "totals": _totals(calls),
        "by_where": {where: _totals([c for c in calls if c["where"] == where]) for where in WHERES},
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
    whether links in chats are read, whether artists' names are looked up at MusicBrainz for
    their genres (musicbrainz.py), with how many have been, and whether people's addresses are
    looked up on the web, through which search engine (lookup.py). Links are read whenever a
    model is set up, as replies are then drafted, and only from public hosts (links.py)."""
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
    return {
        "sources": sources,
        "links": llm.configured(),
        "music": {"on": musicbrainz.on(), "artists": musicbrainz.asked(vault)},
        "lookup": {"on": lookup.on(), "engine": lookup.engine(), "host": lookup.engine_host()},
    }


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
    where = line.get("where")  # one it doesn't know counts as sent away, to Anthropic
    call["where"] = where if where in WHERES else HOSTED
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
        "hosted": sum(c["where"] != HERE for c in calls),
        **{key: sum(c[key] or 0 for c in calls) for key in _COUNTS},
    }


def _text(value: object) -> str:
    return value[:_TEXT_CHARS] if isinstance(value, str) else ""


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
