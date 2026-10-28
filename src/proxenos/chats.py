"""Conversations waiting on the user: direct chats where someone else had the last word.

Reads the message streams in raw/ (WhatsApp and Facebook Messenger chats, LinkedIn
conversations, and the last six months of email threads) and finds each direct chat whose
newest message with text isn't the user's and came within the last `days`. A chat counts only
when the user has written in it before (for an email, in the thread or to that sender at all),
so businesses, newsletters and strangers they never answered stay out (and an email must be
addressed to one of their PROXENOS_EMAILS among a few people), and only when what's
waiting says something: a question, a link or a few words, not a lone "ok" or emoji.

Each one comes with what a reply needs: the messages waiting, the recent conversation around
them, and the user's own last messages in that chat, which show how they write to that person
(case, length, words, emoji) better than any summary of their voice.
"""

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import links
from proxenos.config import env

DAYS = 7
CONTEXT_DAYS = 30  # how far back the conversation shown with a waiting chat goes
CONTEXT_MESSAGES = 20
OWN_MESSAGES = 25  # the user's own messages kept as examples of how they write in a chat
MESSAGE_CHARS = 600
EMAIL_CHARS = 2000  # an email says more than a chat message
EMAIL_MONTHS = 6
OWN_EMAILS = 6  # the user's own emails kept as examples: fewer, since each is longer
MAX_RECIPIENTS = 6  # more than this on To and Cc is an announcement, not a question to answer
_LINKEDIN_FOLDERS = ("INBOX", "ARCHIVE", None)  # not sponsored messages or InMail offers
_ADDRESS = re.compile(r"[^\s<>\"',;]+@[^\s<>\"',;]+")
_BULK_LABELS = {"category promotions", "category social", "category updates", "category forums"}


def waiting(vault: Path, now: datetime, days: float = DAYS) -> list[dict]:
    """Each chat waiting on the user, the newest first, as {source, chat, name, id, since,
    waiting, recent, own}: id is the newest waiting message's, since when the oldest came,
    waiting the messages since the user's last one and recent the conversation before them
    (messages {ts, mine, sender, text}, oldest first), and own the text of the user's own last
    messages in the chat."""
    since = _iso(now - timedelta(days=days))
    start = _iso(now - timedelta(days=CONTEXT_DAYS))
    found = []
    for source, read in _SOURCES.items():
        chats: dict[str, list[dict]] = defaultdict(list)
        for message in _messages(
            sorted((vault / "raw" / source / "messages").glob("*.jsonl")), read
        ):
            chats[message["chat"]].append(message)
        for key, messages in chats.items():
            if chat := _waiting(messages, since, start):
                found.append({"source": source, "chat": key, **chat})

    # Email: a thread counts when the user wrote in it, or has written to its sender anywhere.
    months = sorted({p.name for p in (vault / "raw" / "email").glob("*/*.jsonl")})[-EMAIL_MONTHS:]
    files = [p for p in (vault / "raw" / "email").glob("*/*.jsonl") if p.name in months]
    threads: dict[str, list[dict]] = defaultdict(list)
    sent: dict[str, list[dict]] = defaultdict(list)  # address → the user's emails to it
    me = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
    for message in _messages(sorted(files), lambda r: _email(r, me)):
        threads[message["chat"]].append(message)
        for address in message["peers"] if message["mine"] else ():
            sent[address].append(message)

    def to_sender(m: dict) -> list[str]:
        mail = sorted(sent.get(m["peers"][0], []) if m["peers"] else [], key=lambda x: x["ts"])
        return [x["text"] for x in mail[-OWN_EMAILS:]]

    for key, messages in threads.items():
        if chat := _waiting(messages, since, start, to_sender, OWN_EMAILS):
            found.append({"source": "email", "chat": key, **chat})
    return sorted(found, key=lambda c: c["since"], reverse=True)


def _waiting(
    messages: list[dict],
    since: str,
    start: str,
    elsewhere: Callable[[dict], list[str]] | None = None,
    examples: int = OWN_MESSAGES,
) -> dict | None:
    """The chat as waiting(), or None. `elsewhere` gives the user's own words from outside the
    chat when they haven't written in it (for an email, what they've sent that sender)."""
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    if not said or said[-1]["mine"] or said[-1]["ts"] < since or not said[-1]["direct"]:
        return None
    own = [i for i, m in enumerate(said) if m["mine"]]
    words = [said[i]["text"] for i in own] or (elsewhere(said[-1]) if elsewhere else [])
    if not words:
        return None
    last = own[-1] if own else -1
    waiting, before = said[last + 1 :][-CONTEXT_MESSAGES:], said[: last + 1]
    text = " ".join(m["text"] for m in waiting)
    if "?" not in text and not links.find(text) and len(text.split()) < 3:
        return None
    return {
        "name": said[-1]["name"] or said[-1]["sender"] or "them",
        "id": said[-1]["id"],
        "since": waiting[0]["ts"],
        "waiting": [_shown(m) for m in waiting],
        "recent": [_shown(m) for m in before[-CONTEXT_MESSAGES:] if m["ts"] >= start],
        "own": words[-examples:],
    }


def _shown(message: dict) -> dict:
    return {key: message[key] for key in ("ts", "mine", "sender", "text")}


# Each source's records as one shape: {chat, name, direct, id, ts, mine, sender, text}.


def _whatsapp(r: dict) -> dict | None:
    if not r.get("chat_id"):
        return None
    return _message(
        r, r["chat_id"], r.get("chat_name"), r.get("chat_type") == "direct", r.get("sender_name")
    )


def _facebook(r: dict) -> dict | None:
    if not r.get("chat_id"):
        return None
    return _message(
        r, r["chat_id"], r.get("chat_name"), r.get("chat_type") == "direct", r.get("author")
    )


def _linkedin(r: dict) -> dict | None:
    if not r.get("conversation_id") or r.get("folder") not in _LINKEDIN_FOLDERS:
        return None
    sender = r.get("author")
    name = r.get("conversation_title") or (None if r.get("from_me") else sender)
    return _message(r, r["conversation_id"], name, True, sender)


def _email(r: dict, me: set[str]) -> dict | None:
    """An email as a message. One from someone else is direct only when it's addressed to the
    user by name among a few people, not to a list, and isn't in a bulk-mail category."""
    labels = {str(label).strip("\\").lower() for label in r.get("gmail_labels") or []}
    mine = bool(r.get("from_me"))
    to = [
        a.lower()
        for e in [*(r.get("to") or []), *(r.get("cc") or [])]
        for a in _ADDRESS.findall(str(e))
    ]
    direct = mine or (bool(me & set(to)) and len(to) <= MAX_RECIPIENTS)
    if mine:
        peers = [a.lower() for entry in r.get("to") or [] for a in _ADDRESS.findall(str(entry))]
    else:
        peers = [a.lower() for a in _ADDRESS.findall(str(r.get("from_address") or ""))]
    sender = r.get("from_name") or r.get("from_address")
    message = _message(
        {**r, "text": r.get("body_new") or r.get("body")},
        r.get("gmail_thread") or r.get("in_reply_to") or r.get("id") or "",
        None if mine else sender,
        direct and not labels & _BULK_LABELS,
        sender,
        EMAIL_CHARS,
    )
    return message and {**message, "peers": peers}


_SOURCES: dict[str, Callable[[dict], dict | None]] = {
    "whatsapp": _whatsapp,
    "linkedin": _linkedin,
    "facebook": _facebook,
}


def _message(
    r: dict, chat: str, name: object, direct: bool, sender: object, chars: int = MESSAGE_CHARS
) -> dict | None:
    if not isinstance(r.get("ts"), str) or not chat:
        return None
    # A message's own line breaks become " / ", so each stays one line and still shows its shape.
    lines = (" ".join(line.split()) for line in str(r.get("text") or "").splitlines())
    text = " / ".join(line for line in lines if line)
    return {
        "chat": str(chat),
        "name": str(name) if name else None,
        "direct": direct,
        "id": str(r.get("id") or r["ts"]),
        "ts": r["ts"],
        "mine": bool(r.get("from_me")),
        "sender": None if r.get("from_me") or not sender else str(sender),
        "text": text[:chars],
    }


def _messages(paths: list[Path], read: Callable[[dict], dict | None]) -> Iterator[dict]:
    for path in paths:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and (message := read(record)):
                    yield message


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
