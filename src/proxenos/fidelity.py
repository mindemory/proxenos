"""How close the twin's replies came to what the user sent.

Every reply draft records its chat. Once the user has written in that chat after the draft
(within WINDOW), their first messages there (those within BURST of the first) are what they
sent, and closeness is how much of the draft's text survived into it: 1.0 sent as written, near
0.0 rewritten or about something else. Case, spacing and line breaks don't count. It doesn't
matter whether they sent it from the page or typed their own; either way it says how near the
twin got. A draft still waiting when its chat shows the user wrote there after it is marked sent:
they've answered, so it no longer waits on them.

The draft's text is the model's, as it last wrote it before the user acted on it (_model_text):
an edit on the page writes the user's own text over the draft's file, and scoring that would
score the user against themselves, so the text each edit replaced, which feedback.jsonl keeps
with it, is scored instead; a rewrite by Think is the model's writing too. A draft edited
before the page kept what an edit replaced has no closeness (None): it's left out of the means,
not scored by the user's edit. Each run measures every draft again from the drafts and the
chats, so fidelity.json always holds the measure as it is now.

A draft with no chat of its own, such as the message a task or an outreach idea asked for, is
matched by whom it's to, on its channel: the one-to-one chat with someone of that name, or for an
email, the user's mail to that address. Once they've written to that person there, it's handled
the same way, whether or not they used the draft.

Written to clones/drafts/fidelity.json: each measured draft {id, source, to, drafted, sent,
closeness, draft_text, sent_text} and, per source, how many have a closeness and their mean.
The two texts, each cut to TEXT_CHARS, are what proxenos.voice shows the drafting model of a
draft the user changed before sending, beside what they sent instead, so the next draft starts
from the change, and what proxenos.voice.lessons learns writing rules from; the voice model
learns it when it's trained again (proxenos.voicemodel.refresh). That's the measure that
should decide when a kind of reply can go out without asking (docs/memory.md). No model;
nothing leaves the vault.

A draft sent nearly unchanged (closeness NEARLY or more) comes back through the sources as the
user's own message, but its words are the model's. So the messages it was sent as, by (source,
message id), go to proxenos.chats.DRAFTED, which proxenos.chats marks them by and nothing that
learns how the user writes reads as theirs: the voice examples and the evidence for writing
rules (proxenos.voice), the voice model's training set (proxenos.voicemodel) and the observers
(proxenos.observe). Each run decides again for the messages it measures and keeps what earlier
runs found for the rest, so mail that's fallen out of the months chats reads stays marked. A
draft the user changed more before sending stays theirs: what they sent is their writing, and
the draft beside it is already what proxenos.voice learns their changes from.
"""

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from proxenos import chats, voice
from proxenos.clones import work

WINDOW = timedelta(days=3)
TEXT_CHARS = 1200  # of a draft and of what was sent, kept for the drafting model
BURST = timedelta(minutes=15)
NEARLY = 0.9  # closeness from which a draft counts as sent nearly unchanged: the model's words
# A draft's channel as the chat source its messages are read from, where the names differ.
_SOURCE_OF = {channel: source for source, channel in work._CHANNEL_OF.items()}
_CHAT_SOURCES = {"whatsapp", "slack", "linkedin", "facebook", "instagram", "twitter"}


def measure(vault: Path) -> dict[str, int]:
    folder = vault / "clones" / "drafts"
    wanted, named = _drafts(folder)
    measured = []
    answered = 0
    seen: set[Path] = set()  # a draft matched by two chats counts once
    looked: set[tuple[str, str]] = set()  # the user's messages measured against a draft
    nearly: set[tuple[str, str]] = set()  # and those of them that were one, sent nearly as is
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
                theirs = draft["text"]  # the model's, or None when that's gone
                closeness = None if theirs is None else round(_closeness(theirs, sent), 2)
                looked |= {(source, m["id"]) for m in sent}
                if closeness is not None and closeness >= NEARLY:
                    nearly |= {(source, m["id"]) for m in sent}
                measured.append(
                    {
                        "id": draft.get("id"),
                        "source": source,
                        "to": _json(draft.get("to")) or draft.get("to"),
                        "drafted": draft["created"],
                        "sent": sent[0]["ts"],
                        "closeness": closeness,
                        "draft_text": None if theirs is None else _clip(theirs),
                        "sent_text": _clip("\n".join(m["text"] for m in sent)),
                    }
                )
    drafted = (chats.drafted(vault) - looked) | nearly
    work._write(
        vault / chats.DRAFTED,
        json.dumps({"generated": _now(), "messages": sorted(map(list, drafted))}, indent=1),
    )
    measured.sort(key=lambda m: m["sent"], reverse=True)
    by_source: dict[str, list[float]] = defaultdict(list)
    for m in measured:
        if m["closeness"] is not None:
            by_source[m["source"]].append(m["closeness"])
    summary = {s: {"n": len(v), "mean": round(sum(v) / len(v), 2)} for s, v in by_source.items()}
    out = {"generated": _now(), "by_source": summary, "drafts": measured}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fidelity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return {"drafts_measured": len(measured), "drafts_answered": answered}


def written(vault: Path) -> tuple[dict, dict]:
    """Each draft Proxenos wrote, as (when, the model's text), by the chat it answers and by
    whom it's to, for `from_draft` and `drafted_before`. A draft whose model text is gone (see
    _model_text) has "", which no answer comes close to, but it was still made."""
    return tuple(
        {key: [(d["created"], d["text"] or "") for d in ds] for key, ds in found.items()}
        for found in _drafts(vault / "clones" / "drafts")
    )


def from_draft(
    drafts: tuple[dict, dict], source: str, key: str, messages: list[dict], ts: str, text: str
) -> bool:
    """Whether `text`, which the user sent at `ts` in a conversation (source, key and its
    messages, as proxenos.chats gives them), was a draft of Proxenos's made for it before then,
    sent nearly unchanged (NEARLY): the model's words, which a reply held out to judge a model
    by must never be. `drafts` is what `written` gives."""
    return any(
        when < ts and draft and round(_closeness(draft, [{"text": text}]), 2) >= NEARLY
        for when, draft in _made(drafts, source, key, messages)
    )


def drafted_before(
    drafts: tuple[dict, dict],
    source: str,
    key: str,
    messages: list[dict],
    ts: str,
    since: str = "",
) -> bool:
    """Whether a draft of Proxenos's for a conversation (as `from_draft` takes it) was waiting
    when the user wrote there at `ts`, however close it came: made before then, and after
    `since`, their own message there before, which answered whatever an earlier draft was for
    ("" when there's none, or it isn't known: any draft before counts). They may have read it
    first, so what they wrote may lean on it, and a reply held out as written without a draft
    mustn't have had one."""
    return any(since < when < ts for when, _ in _made(drafts, source, key, messages))


def _made(
    drafts: tuple[dict, dict], source: str, key: str, messages: list[dict]
) -> list[tuple[str, str]]:
    """The drafts made for a conversation: for its chat, and to whom it's with."""
    by_chat, by_name = drafts
    return [
        *by_chat.get((source, key), []),
        *(d for who in _with(source, key, messages) for d in by_name.get(who, [])),
    ]


def _drafts(folder: Path) -> tuple[dict, dict]:
    """Each draft with front matter and when it was written, with "text", what the model last
    wrote of it (_model_text), by the chat it answers (source, chat key) and, for one with no
    chat, by whom it's to (_recipient)."""
    edits = _edits(folder / "feedback.jsonl")
    wanted: dict[tuple[str, str], list[dict]] = defaultdict(list)  # by chat
    named: dict[tuple[str, str], list[dict]] = defaultdict(list)  # by whom it's to
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = work._FRONT.match(text)
        fields = work._front(text) or {}
        thread = _json(fields.get("thread"))
        if not (front and fields.get("created")):
            continue
        body = text[front.end() :]
        mine = edits.get(str(fields.get("id") or path.stem), [])
        draft = fields | {"body": body, "path": path, "text": _model_text(body, mine)}
        if isinstance(thread, dict):
            wanted[thread.get("source"), thread.get("chat")].append(draft)
        elif who := _recipient(fields):
            named[who].append(draft)
    return wanted, named


def _model_text(body: str, edits: list[dict]) -> str | None:
    """The draft as the model last wrote it before the user acted on it. An edit on the page
    writes the user's text over the draft's file and keeps what it replaced ("before"), so from
    the text there now, each of the user's edits since a model last wrote it is undone back to
    the first; a model's rewrite (proxenos.voice.MODEL_EDITS: Think's) is the model's text. None
    when an edit of the user's kept nothing of what it replaced, as the page's didn't before it
    logged it: the model's text is gone, and scoring the edit instead would score the user."""
    text = body
    for edit in reversed(edits):
        if edit.get("via") in voice.MODEL_EDITS:
            break
        if not isinstance(edit.get("before"), str):
            return None
        text = edit["before"]
    return text


def _edits(path: Path) -> dict[str, list[dict]]:
    """Each draft's edits in feedback.jsonl, the page's and a model's, by draft id, in order."""
    found: dict[str, list[dict]] = defaultdict(list)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("action") == "edit" and event.get("draft_id"):
            found[str(event["draft_id"])].append(event)
    return found


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
    """How much of the draft survived into what was sent: difflib's ratio (Ratcliff/Obershelp),
    the draft first and what was sent second. Without autojunk, which in a text of 200 or more
    characters takes every character making up more than about 1% of it for junk, so long
    replies and emails would be scored by another rule than short chats."""
    sent_text = _plain(" ".join(m["text"] for m in sent))
    return SequenceMatcher(None, _plain(draft), sent_text, autojunk=False).ratio()


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= TEXT_CHARS else text[: TEXT_CHARS - 1].rstrip() + "…"


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
