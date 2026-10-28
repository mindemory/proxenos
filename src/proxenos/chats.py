"""Conversations waiting on the user: direct chats where someone else had the last word.

Reads the message streams in raw/ (WhatsApp and Facebook Messenger chats, LinkedIn
conversations) and finds each direct chat whose newest message with text isn't the user's and
came within the last `days`. A chat counts only when the user has written in it before, so
businesses, broadcasts and strangers they never answered stay out, and only when what's waiting
says something: a question, a link or a few words, not a lone "ok" or emoji.

Each one comes with what a reply needs: the messages waiting, the recent conversation around
them, and the user's own last messages in that chat, which show how they write to that person
(case, length, words, emoji) better than any summary of their voice.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import links

DAYS = 7
CONTEXT_DAYS = 30  # how far back the conversation shown with a waiting chat goes
CONTEXT_MESSAGES = 20
OWN_MESSAGES = 25  # the user's own messages kept as examples of how they write in a chat
MESSAGE_CHARS = 600
_LINKEDIN_FOLDERS = ("INBOX", "ARCHIVE", None)  # not sponsored messages or InMail offers


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
        for message in _messages(vault / "raw" / source / "messages", read):
            chats[message["chat"]].append(message)
        for key, messages in chats.items():
            if chat := _waiting(messages, since, start):
                found.append({"source": source, "chat": key, **chat})
    return sorted(found, key=lambda c: c["since"], reverse=True)


def _waiting(messages: list[dict], since: str, start: str) -> dict | None:
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    if not said or said[-1]["mine"] or said[-1]["ts"] < since or not said[-1]["direct"]:
        return None
    own = [i for i, m in enumerate(said) if m["mine"]]
    if not own:
        return None
    waiting, before = said[own[-1] + 1 :], said[: own[-1] + 1]
    text = " ".join(m["text"] for m in waiting)
    if "?" not in text and not links.find(text) and len(text.split()) < 3:
        return None
    return {
        "name": said[-1]["name"] or said[-1]["sender"] or "them",
        "id": said[-1]["id"],
        "since": waiting[0]["ts"],
        "waiting": [_shown(m) for m in waiting],
        "recent": [_shown(m) for m in before[-CONTEXT_MESSAGES:] if m["ts"] >= start],
        "own": [said[i]["text"] for i in own[-OWN_MESSAGES:]],
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


_SOURCES: dict[str, Callable[[dict], dict | None]] = {
    "whatsapp": _whatsapp,
    "linkedin": _linkedin,
    "facebook": _facebook,
}


def _message(r: dict, chat: str, name: object, direct: bool, sender: object) -> dict | None:
    if not isinstance(r.get("ts"), str):
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
        "text": text[:MESSAGE_CHARS],
    }


def _messages(directory: Path, read: Callable[[dict], dict | None]) -> Iterator[dict]:
    for path in sorted(directory.glob("*.jsonl")):
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
