"""Conversations waiting on the user: direct chats where someone else had the last word.

Reads the message streams in raw/ (WhatsApp, Messenger, Instagram and X chats, LinkedIn
conversations, Slack, and the last six months of email threads) and finds each direct chat whose
newest message with text isn't the user's and came within the last `days`. A chat counts only
when the user has written in it before (for an email, in the thread or to that sender at all),
so businesses, newsletters and strangers they never answered stay out (and an email must be
addressed to one of their PROXENOS_EMAILS among a few people), and only when what's
waiting says something: a question, a link or a few words, not a lone "ok" or emoji.

One email from someone new counts too: their first, written to the user as one person (from no
role address like info@, with no unsubscribe or copyright line), calling them by name and asking
something, by someone who hasn't written to them in any other thread. So a founder's or a
student's first note gets a reply, and a pitch sent again and again doesn't. Having no words of
the user's to that person, its reply is written from their emails to others (see
proxenos.voice).

In Slack, a direct message counts, and so does a channel thread that mentions the user or that
they've written in; a thread that only mentions them is answered in their way of writing in that
workspace.

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
# Senders no one answers: the part of the address before the @.
_AUTOMATED = re.compile(
    r"(no-?reply|do-?not-?reply|notifications?|mailer-daemon|postmaster|bounces?)"
)
_SET_ASIDE = {"spam", "junk", "trash"}  # labels of mail no one answers, as Takeout keeps them
# Addresses that are a role, not a person: the part before the @, whole.
_ROLE = re.compile(
    r"(info|hello|hi|team|contact|support|help|sales|marketing|news(letters?)?|updates?|digest|"
    r"events?|admin|office|billing|accounts?|careers|jobs|hr|recruiting|community|partners?|"
    r"partnerships|press|media|feedback|(customer)?[-._]?(service|care)|members(hip)?|invites?|"
    r"alerts?|security|system|scheduling|appointments?|reminders?|orders?|receipts?|verify)"
)
# What mail sent in bulk or by a company says, whatever its headers: a way out of the next one,
# which the law asks commercial mail for, or a copyright line.
_BULK_TEXT = re.compile(
    r"unsubscribe|opt[ -]?out|(email|mailing|subscription) preferences|"
    r"(no longer|don'?t|do not) (wish|want) to (receive|hear)|remove (you|yourself) from|"
    r"view (this|it) in (a|your) browser|©|all rights reserved",
    re.IGNORECASE,
)
# Asking without a question mark: "let me know", "would love to", "open to a call".
_REQUEST = re.compile(
    r"\blet me know\b|\bwould love to\b|\b(open|available|free) (to|for) (a )?"
    r"(chat|call|talk|meet|connect)",
    re.IGNORECASE,
)
_REPLY_PREFIX = re.compile(r"^\s*((re|fwd?|aw|wg)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_MENTION = re.compile(r"<@(\w+)(?:\|[^>]*)?>")  # Slack's <@U123> or <@U123|name>
_WORD = re.compile(r"\w+")


def waiting(vault: Path, now: datetime, days: float = DAYS) -> list[dict]:
    """Each chat waiting on the user, the newest first, as {source, chat, name, id, since,
    waiting, recent, own, first}: id is the newest waiting message's, since when the oldest
    came, waiting the messages since the user's last one and recent the conversation before
    them (messages {ts, mine, sender, text}, oldest first), own the text of the user's own last
    messages in the chat, and first whether it's someone new's first email, which has no own."""
    since = _iso(now - timedelta(days=days))
    start = _iso(now - timedelta(days=CONTEXT_DAYS))
    found = []
    for source, key, messages, elsewhere, examples in conversations(vault):
        if chat := _waiting(messages, since, start, elsewhere, examples):
            found.append({"source": source, "chat": key, **chat})
    return sorted(found, key=lambda c: c["since"], reverse=True)


def conversations(
    vault: Path, months: int | None = None, email: bool = True, email_months: int = EMAIL_MONTHS
) -> Iterator[tuple]:
    """Every conversation, as (source, chat key, messages, elsewhere, examples): the messages
    as one shape (see below), and for _waiting where the user's own words come from when they
    haven't written in it, and how many to keep. `months` reads only each chat stream's newest
    month files, and email=False leaves email out. Email is its last `email_months`, or all of
    it with 0."""
    for source, (stream, read) in _SOURCES.items():
        chats: dict[str, list[dict]] = defaultdict(list)
        paths = sorted((vault / "raw" / source / stream).glob("*.jsonl"))
        for message in _messages(paths[-months:] if months else paths, read):
            chats[message["chat"]].append(message)
        for key, messages in chats.items():
            yield source, key, messages, None, OWN_MESSAGES

    # Slack, one workspace at a time: who the user is differs between workspaces.
    for folder in sorted((vault / "raw" / "slack").glob("*/messages")):
        paths = sorted(folder.glob("*.jsonl"))
        yield from _slack(folder.parent.name, paths[-months:] if months else paths)

    if not email:
        return
    # Email: a thread counts when the user wrote in it, or has written to its sender anywhere,
    # or when it's someone new's first email worth answering (see _first).
    months = sorted({p.name for p in (vault / "raw" / "email").glob("*/*.jsonl")})[-email_months:]
    files = [p for p in (vault / "raw" / "email").glob("*/*.jsonl") if p.name in months]
    threads: dict[str, list[dict]] = defaultdict(list)
    sent: dict[str, list[dict]] = defaultdict(list)  # address → the user's emails to it
    heard: dict[str, set[str]] = defaultdict(set)  # address → the threads it wrote to them in
    me = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
    for message in _messages(sorted(files), lambda r: _email(r, me)):
        threads[message["chat"]].append(message)
        for address in message["peers"] if message["mine"] else ():
            sent[address].append(message)
        if not message["mine"] and message["peers"]:
            heard[message["peers"][0]].add(message["chat"])

    def to_sender(m: dict) -> list[str]:
        mail = sorted(sent.get(m["peers"][0], []) if m["peers"] else [], key=lambda x: x["ts"])
        return [x["text"] for x in mail[-OWN_EMAILS:]]

    names = {w for w in _WORD.findall(env("NAME").casefold()) if len(w) > 2}  # the user's
    for key, messages in threads.items():
        if _first(key, messages, sent, heard, names):
            messages = [{**m, "first": True} for m in messages]
        yield "email", key, messages, to_sender, OWN_EMAILS


def _waiting(
    messages: list[dict],
    since: str,
    start: str,
    elsewhere: Callable[[dict], list[str]] | None = None,
    examples: int = OWN_MESSAGES,
) -> dict | None:
    """The chat as waiting(), or None. `elsewhere` gives the user's own words from outside the
    chat when they haven't written in it (for an email, what they've sent that sender). Someone
    new's first email (marked first) needs none, but waits only while all of it is new: a
    follow-up to one the user let sit doesn't count."""
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    if not said or said[-1]["mine"] or said[-1]["ts"] < since or not said[-1]["direct"]:
        return None
    own = [i for i, m in enumerate(said) if m["mine"]]
    words = [said[i]["text"] for i in own] or (elsewhere(said[-1]) if elsewhere else [])
    first = bool(said[-1].get("first"))
    if (not words and not first) or (first and said[0]["ts"] < since):
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
        "first": first,
    }


def _first(
    key: str,
    messages: list[dict],
    sent: dict[str, list],
    heard: dict[str, set[str]],
    names: set[str],
) -> bool:
    """Whether an email thread is someone new's first email worth answering: the user hasn't
    written in it or ever to its sender, who has written to them in no other thread and answers
    no email outside it (a reply to mail of the user's that isn't here is no first email); its
    newest email is personal (see _email); and what that sender wrote in it calls the user by
    one of their `names` and asks something."""
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    if not said or any(m["mine"] for m in said) or not said[-1]["personal"]:
        return False
    sender = said[-1]["peers"][0]
    if sent.get(sender) or heard.get(sender) != {key}:
        return False
    theirs = [m for m in said if m["peers"][:1] == [sender]]
    ids = {m["id"] for m in messages}
    if any(m["in_reply_to"] and m["in_reply_to"] not in ids for m in theirs):
        return False
    text = " ".join(m["text"] for m in theirs)
    return bool(names & set(_WORD.findall(text.casefold()))) and _asks(text)


def _asks(text: str) -> bool:
    """Whether a text asks something: a question mark outside its links, or a request."""
    for link in links.find(text):
        text = text.replace(link, " ")
    return "?" in text or bool(_REQUEST.search(text))


def _slack(workspace: str, paths: list[Path]) -> Iterator[tuple]:
    """A workspace's conversations, as conversations() gives them: each direct message, and each
    channel thread, whose messages count as to the user where they mention the user or the user
    has written in the thread. A thread that only mentions them is answered in their way of
    writing in that workspace."""
    records = [r for r in _records(paths) if r.get("channel_id")]
    me = {r["user_id"] for r in records if r.get("from_me") and r.get("user_id")}
    names = {
        r["user_id"]: r["user_name"] for r in records if r.get("user_id") and r.get("user_name")
    }

    def readable(text: object) -> str:
        return _MENTION.sub(lambda m: "@" + names.get(m[1], "someone"), str(text or ""))

    chats: dict[str, list[dict]] = defaultdict(list)
    threads = set()
    for r in records:
        dm = r.get("channel_type") == "dm"
        key = (
            r["channel_id"]
            if dm
            else f"{r['channel_id']}/{r.get('thread_ts') or r.get('slack_ts')}"
        )
        name = r.get("channel_name") if dm else f"#{r.get('channel_name') or 'a channel'}"
        message = _message(
            {**r, "text": readable(r.get("text"))}, key, name, dm, r.get("user_name")
        )
        if message:
            mentioned = bool(me & set(_MENTION.findall(str(r.get("text") or ""))))
            chats[key].append({**message, "direct": dm or mentioned})
            if not dm:
                threads.add(key)

    mine = sorted(
        (m for ms in chats.values() for m in ms if m["mine"] and m["text"]), key=lambda m: m["ts"]
    )
    for key, messages in chats.items():
        if key in threads and any(m["mine"] for m in messages):
            messages = [{**m, "direct": True} for m in messages]
        examples = (lambda _: [m["text"] for m in mine]) if key in threads else None
        yield "slack", f"{workspace}/{key}", messages, examples, OWN_MESSAGES


def _shown(message: dict) -> dict:
    return {key: message[key] for key in ("ts", "mine", "sender", "text")}


# Each source's records as one shape: {chat, name, direct, id, ts, mine, sender, text}.


def _whatsapp(r: dict) -> dict | None:
    if not r.get("chat_id"):
        return None
    return _message(
        r, r["chat_id"], r.get("chat_name"), r.get("chat_type") == "direct", r.get("sender_name")
    )


def _meta(r: dict) -> dict | None:
    """A Messenger or Instagram message: the two exports share a shape."""
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
    user by name among a few people, not to a list, isn't bulk mail (by its headers or Gmail's
    category) and isn't from an address no one answers; and personal when it's also from no
    role address, not in spam or trash and has no unsubscribe or copyright line, so reads as one
    person writing to them. Its thread is Gmail's when the record has one; otherwise (Mail's
    files carry none) the subject without Re: and Fwd:, with everyone on it but the user."""
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
    automated = any(_AUTOMATED.search(a.split("@")[0]) for a in peers) and not mine
    everyone = {*to, *(a.lower() for a in _ADDRESS.findall(str(r.get("from_address") or "")))}
    subject = " ".join(_REPLY_PREFIX.sub("", str(r.get("subject") or "")).lower().split())
    thread = r.get("gmail_thread") or (
        f"{subject}|{','.join(sorted(everyone - me))}" if subject else r.get("id") or ""
    )
    direct = direct and not automated and not r.get("bulk") and not labels & _BULK_LABELS
    personal = (
        direct
        and not mine
        and bool(peers)
        and not _ROLE.fullmatch(peers[0].split("@")[0])
        and not labels & _SET_ASIDE
        and not _BULK_TEXT.search(str(r.get("body") or r.get("body_new") or ""))
    )
    message = _message(
        {**r, "text": r.get("body_new") or r.get("body")},
        thread,
        None if mine else sender,
        direct,
        sender,
        EMAIL_CHARS,
    )
    return message and {
        **message,
        "peers": peers,
        "personal": personal,
        "in_reply_to": r.get("in_reply_to"),
    }


def _twitter(r: dict) -> dict | None:
    if not r.get("conversation_id"):
        return None
    sender = r.get("sender_name") or r.get("sender_id")
    name = r.get("conversation_title") or (None if r.get("from_me") else sender)
    direct = r.get("conversation_type") != "group"
    return _message(r, r["conversation_id"], name, direct, sender)


# Each chat source: the stream under raw/<source>/ its messages are in, and how to read one.
_SOURCES: dict[str, tuple[str, Callable[[dict], dict | None]]] = {
    "whatsapp": ("messages", _whatsapp),
    "linkedin": ("messages", _linkedin),
    "facebook": ("messages", _meta),
    "instagram": ("messages", _meta),
    "twitter": ("dms", _twitter),
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
    return (message for record in _records(paths) if (message := read(record)))


def _records(paths: list[Path]) -> Iterator[dict]:
    for path in paths:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
