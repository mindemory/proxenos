"""How close the twin's replies came to what the user sent.

Every reply draft records its chat. Once the user has written in that chat after the draft
(within WINDOW), their first messages there (those within BURST of the first) are what they
sent, and closeness is how much of the draft's text survived into it: 1.0 sent as written, near
0.0 rewritten or about something else. Case, spacing and line breaks don't count. It doesn't
matter whether they sent it from the page or typed their own; either way it says how near the
twin got. A draft still waiting when its chat shows the user wrote there after it is marked sent:
they've answered, so it no longer waits on them.

A draft with no chat of its own, such as the message a task or an outreach idea asked for, is
matched by whom it's to, on its channel: the one-to-one chat with someone of that name, or for an
email, the user's mail to that address. Once they've written to that person there, it's handled
the same way, whether or not they used the draft.

Written to clones/drafts/fidelity.json: each measured draft {id, source, to, drafted, sent,
closeness} and, per source, how many and their mean. That's the measure that should decide when a
kind of reply can go out without asking (docs/memory.md). No model; nothing leaves the vault.
"""

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from proxenos import chats
from proxenos.clones import work

WINDOW = timedelta(days=3)
BURST = timedelta(minutes=15)
# A draft's channel as the chat source its messages are read from, where the names differ.
_SOURCE_OF = {channel: source for source, channel in work._CHANNEL_OF.items()}
_CHAT_SOURCES = {"whatsapp", "slack", "linkedin", "facebook", "instagram", "twitter"}


def measure(vault: Path) -> dict[str, int]:
    folder = vault / "clones" / "drafts"
    wanted: dict[tuple[str, str], list[dict]] = defaultdict(list)  # by chat
    named: dict[tuple[str, str], list[dict]] = defaultdict(list)  # by whom it's to
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = work._FRONT.match(text)
        fields = work._front(text) or {}
        thread = _json(fields.get("thread"))
        if not (front and fields.get("created")):
            continue
        draft = fields | {"body": text[front.end() :], "path": path}
        if isinstance(thread, dict):
            wanted[thread.get("source"), thread.get("chat")].append(draft)
        elif who := _recipient(fields):
            named[who].append(draft)

    measured = []
    answered = 0
    seen: set[Path] = set()  # a draft matched by two chats counts once
    for source, key, messages, *_ in chats.conversations(vault):
        drafts = [
            *wanted.get((source, key), []),
            *(d for who in _with(source, key, messages) for d in named.get(who, [])),
        ]
        for draft in drafts:
            if draft["path"] in seen:
                continue
            if sent := _sent(messages, draft["created"]):
                seen.add(draft["path"])
                if draft.get("status") in ("draft", "approved"):
                    _mark_sent(draft["path"])
                    answered += 1
                measured.append(
                    {
                        "id": draft.get("id"),
                        "source": source,
                        "to": _json(draft.get("to")) or draft.get("to"),
                        "drafted": draft["created"],
                        "sent": sent[0]["ts"],
                        "closeness": round(_closeness(draft["body"], sent), 2),
                    }
                )
    measured.sort(key=lambda m: m["sent"], reverse=True)
    by_source: dict[str, list[float]] = defaultdict(list)
    for m in measured:
        by_source[m["source"]].append(m["closeness"])
    summary = {s: {"n": len(v), "mean": round(sum(v) / len(v), 2)} for s, v in by_source.items()}
    out = {"generated": _now(), "by_source": summary, "drafts": measured}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fidelity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return {"drafts_measured": len(measured), "drafts_answered": answered}


def _recipient(fields: dict) -> tuple[str, str] | None:
    """Whom a draft is to, as a chat says it: (source, name), or ("email", address)."""
    channel = fields.get("channel") or ""
    to = str(_json(fields.get("to")) or fields.get("to") or "")
    if channel == "email":
        address = chats._ADDRESS.search(to)
        return ("email", address[0].lower()) if address else None
    source = _SOURCE_OF.get(channel, channel)
    return (source, _name(to)) if source in _CHAT_SOURCES and _name(to) else None


def _with(source: str, key: str, messages: list[dict]) -> set[tuple[str, str]]:
    """Whom a one-to-one chat is with, as _recipient says it; none for a group or a thread."""
    if source == "email":
        return {("email", a) for m in messages if m["mine"] for a in m.get("peers", [])}
    if source == "slack" and key.count("/") != 1:  # a channel thread: <workspace>/<channel>/<ts>
        return set()
    if not all(m["direct"] for m in messages):
        return set()
    names = {m["name"] for m in messages} | {m["sender"] for m in messages}
    return {(source, _name(n)) for n in names if n and _name(n)}


def _name(text: str) -> str:
    return " ".join(text.split()).casefold()


def _mark_sent(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"(?m)^status:.*$", "status: sent", text, count=1), encoding="utf-8")


def _sent(messages: list[dict], drafted: str) -> list[dict]:
    """The user's first messages in the chat after the draft: those within BURST of the first."""
    start = datetime.fromisoformat(drafted)
    after = sorted(
        (m for m in messages if m["mine"] and m["text"] and m["ts"] > drafted),
        key=lambda m: m["ts"],
    )
    after = [m for m in after if datetime.fromisoformat(m["ts"]) <= start + WINDOW]
    if not after:
        return []
    first = datetime.fromisoformat(after[0]["ts"])
    return [m for m in after if datetime.fromisoformat(m["ts"]) <= first + BURST]


def _closeness(draft: str, sent: list[dict]) -> float:
    return SequenceMatcher(None, _plain(draft), _plain(" ".join(m["text"] for m in sent))).ratio()


def _plain(text: str) -> str:
    """Words only, lower case: a line break, a " / " between lines or extra spaces don't count."""
    return " ".join(re.sub(r"\s+/\s+", " ", text).lower().split())


def _json(value: object) -> object:
    try:
        return json.loads(str(value))
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
