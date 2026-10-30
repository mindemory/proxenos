"""The user's own writing, as examples for a draft, and the rules every draft follows.

A description of how someone writes doesn't make a model write like them; examples do. So
every prompt that writes as the user gets some of their own words, picked here in code, newest
first, and its system prompt gets RULES: copy those examples, and leave out the habits that
make text read as a model's.

What a draft is shown depends on where it goes (`examples`):

- a message in a chat: the user's own messages in that chat (the one being answered, or their
  chat with the person by name), then their messages to others on the same channel (in Slack,
  the same workspace), MESSAGE_CHARS in all;
- an email, a post or a doc: their longer writing, LONG_CHARS in all, each piece cut to
  EXAMPLE_CHARS: the emails they sent and their own posts, emails first, or posts first for a
  doc. A reply in an email thread gets their own emails in that thread first;
- where that isn't known yet (an Ask): both.

Only what the user wrote themselves, read as proxenos.chats reads it:
- chat messages marked as theirs, from each stream's newest MONTHS month files, in chats where
  someone else wrote too, so notes to self stay out;
- email they sent to someone besides themselves, from the months of mail chats reads, and of
  it only what they wrote (body_new), not what they quoted or forwarded;
- posts marked as theirs, or, in a stream that is only theirs (Bluesky, their website), the
  posts and replies, not reposts or pages.
A message of fewer than MIN_WORDS words ("ok", an emoji) shows little of how they write and is
skipped, a text under LONG_MIN characters isn't longer writing, and no text is shown twice.
"""

import re
from functools import cached_property
from pathlib import Path

from proxenos import chats
from proxenos.config import env

MONTHS = 3  # of each chat stream, the newest month files read for examples
MIN_WORDS = 2
MESSAGE_CHARS = 2500  # of examples for a message in a chat
LONG_CHARS = 5000  # for an email, a post or a doc
LONG_MIN = 200  # characters a text needs to count as longer writing
EXAMPLE_CHARS = 1500  # of one piece of longer writing
# Where the user's own posts are, under raw/.
POSTS = (
    "bluesky/posts",
    "facebook/posts",
    "instagram/posts",
    "linkedin/posts",
    "threads/posts",
    "twitter/posts",
    "website/pages",
)
NAMES = {  # each chat source, as the user knows it
    "whatsapp": "WhatsApp",
    "slack": "Slack",
    "linkedin": "LinkedIn",
    "facebook": "Messenger",
    "instagram": "Instagram",
    "twitter": "X",
}
_SOURCE_OF = {"messenger": "facebook", "x": "twitter"}  # chat sources by a draft's channel names
_MONTH = re.compile(r"\d{4}-\d{2}\.jsonl")
_WORD = re.compile(r"\w+")
_COPY = "Copy how they write, never what they say."

RULES = """\
Write as {person} writes, not as an AI writes. Where their own writing is given as examples, \
it shows how they write, never what to say: take no facts, names, numbers or plans from it.
- Copy the examples: their length, punctuation, capitalization, greetings, sign-offs and \
fillers. If they write "I think", "kind of", in lower case or in run-on sentences, that is \
their voice; keep it.
- Use their own phrasings where they fit.
- No em dashes.
- No "It's not X, it's Y" contrasts.
- No lists of three for rhythm.
- No tidy summing up, closing line or moral at the end. Stop where they would.
- No headings or bold in a message.
- No stock openers or closers ("I hope this finds you well", "Happy to help", "Let me know \
if...") unless their examples use them.
- Never more polished or more organized than they are."""


def rules(person: str) -> str:
    return RULES.format(person=person)


class Writing:
    """The user's own writing in a vault, newest first. Each part is read the first time it's
    asked for, so a run reads only what its drafts need, and only once."""

    def __init__(self, vault: Path) -> None:
        self.vault = vault

    @cached_property
    def messages(self) -> list[dict]:
        """What they wrote in chats, as {source, chat, name, ts, text}."""
        found = []
        for source, key, said, *_ in chats.conversations(self.vault, months=MONTHS, email=False):
            if all(m["mine"] for m in said):
                continue  # notes to self, or a chat no one else wrote in
            name = next((m["name"] for m in said if m["name"] and not m["mine"]), "")
            found += [
                {"source": source, "chat": key, "name": name, "ts": m["ts"], "text": m["text"]}
                for m in said
                if m["mine"] and _enough(m["text"])
            ]
        return sorted(found, key=lambda m: m["ts"], reverse=True)

    @cached_property
    def long(self) -> list[dict]:
        """Their sent emails and own posts, as {kind, on, ts, title, text}."""
        return sorted([*self._emails(), *self._posts()], key=lambda t: t["ts"], reverse=True)

    def _emails(self) -> list[dict]:
        """Newest month first, until there's enough."""
        me = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
        files = sorted((self.vault / "raw" / "email").glob("*/*.jsonl"))
        months = sorted({p.name for p in files if _MONTH.fullmatch(p.name)})
        found: list[dict] = []
        for month in reversed(months[-chats.EMAIL_MONTHS :]):
            if sum(len(t["text"]) for t in found) >= LONG_CHARS:
                break
            for r in chats._records([p for p in files if p.name == month]):
                if r.get("from_me") is not True or not isinstance(r.get("ts"), str):
                    continue
                to = {
                    a.lower()
                    for e in [*(r.get("to") or []), *(r.get("cc") or [])]
                    for a in chats._ADDRESS.findall(str(e))
                }
                text = _tidy(r.get("body_new"))
                if to - me and len(text) >= LONG_MIN:
                    found.append(_piece("email", "", r, r.get("subject"), text))
        return found

    def _posts(self) -> list[dict]:
        """Each stream's newest month first, until there's enough of it."""
        found = []
        for stream in POSTS:
            mine: list[dict] = []
            for path in sorted((self.vault / "raw" / stream).glob("*.jsonl"), reverse=True):
                if sum(len(t["text"]) for t in mine) >= LONG_CHARS:
                    break
                if not _MONTH.fullmatch(path.name):
                    continue
                for r in chats._records([path]):
                    text = _tidy(r.get("text"))
                    if _own(r) and isinstance(r.get("ts"), str) and len(text) >= LONG_MIN:
                        mine.append(_piece("post", stream.split("/")[0], r, r.get("title"), text))
            found += mine
        return found


def examples(
    written: Writing,
    channel: str | None,
    *,
    name: object = "",
    chat: tuple[str, str] | None = None,
    here: list[str] | None = None,
    first: str = "email",
) -> str:
    """The user's own writing for a draft going to `channel` (a draft's channel, "email",
    "other", or a chat source; None when it isn't known yet), as a part of its prompt, or ""
    when there's none. In a chat, `here` is their own messages in it, oldest first, as
    proxenos.chats gives them; without it, the chat `chat` (source, key), or the one with the
    person `name`. `first` is the longer writing shown first: "email" or "post"."""
    source = _SOURCE_OF.get(channel, channel) if channel else None
    if source in NAMES:
        return messages(written, source, chat=chat, name=name, here=here)
    if source is None:  # not known yet: how they write in chats, and at length
        return _join(messages(written, None, name=name), longer(written, first))
    return _join(messages(written, source, here=here) if here else "", longer(written, first))


def messages(
    written: Writing,
    source: str | None,
    *,
    chat: tuple[str, str] | None = None,
    name: object = "",
    here: list[str] | None = None,
) -> str:
    """Their own messages in the chat, then to others on the same channel, newest first."""
    pool = written.messages if source is None or source in NAMES else []
    pool = [m for m in pool if source in (None, m["source"])]
    key, label = chat, "In this conversation:"
    found = [m for m in pool if _fold(name) and _fold(m["name"]) == _fold(name)]
    if here is None and key is None and found:  # their chat with the person, by name
        key = (found[0]["source"], found[0]["chat"])
        label = f"In their chat with {found[0]['name']}:"
    if key:
        source = key[0]
        within = key[1].split("/", 1)[0] + "/" if source == "slack" else ""  # the workspace
        pool = [m for m in pool if m["source"] == source and m["chat"].startswith(within)]
    if here is None:
        mine = [m["text"] for m in pool if key and (m["source"], m["chat"]) == key]
    else:
        mine = [text for text in reversed(here) if _enough(text)]
    others = [m["text"] for m in pool if not key or (m["source"], m["chat"]) != key]
    seen: set[str] = set()
    mine = _pick(mine, MESSAGE_CHARS, seen)
    others = _pick(others, MESSAGE_CHARS - sum(map(len, mine)), seen)
    if not (mine or others):
        return ""
    person = env("NAME", "the person")
    lines = [f"How {person} writes, their own messages, newest first. {_COPY}"]
    if mine:
        lines += [label, *(f"- {text}" for text in mine)]
    if others:
        if source not in NAMES:
            lines.append("In their chats:")
        else:
            lines.append(f"To others on {NAMES[source]}:" if mine else f"On {NAMES[source]}:")
        lines += [f"- {text}" for text in others]
    return "\n".join(lines)


def longer(written: Writing, first: str = "email") -> str:
    """Their longer writing, `first` of the kinds first, each kind newest first."""
    pieces = sorted(written.long, key=lambda t: t["kind"] != first)
    shown, seen, room = [], set(), LONG_CHARS
    for piece in pieces:
        if len(piece["text"]) > room or _key(piece["text"]) in seen:
            continue
        seen.add(_key(piece["text"]))
        room -= len(piece["text"])
        about = f'kind="{piece["kind"]}" date="{piece["ts"][:10]}"'
        if piece["on"]:
            about += f' on="{piece["on"]}"'
        if title := piece["title"].replace('"', "'"):
            about += f' title="{title}"'
        shown.append(f"<example {about}>\n{piece['text']}\n</example>")
    if not shown:
        return ""
    person = env("NAME", "the person")
    head = f"How {person} writes at length, their own emails and posts, newest first. {_COPY}"
    return "\n".join([head, *shown])


def _pick(texts: list[str], room: int, seen: set[str]) -> list[str]:
    """In order, each text that still fits in `room` characters and isn't in `seen`."""
    picked = []
    for text in texts:
        if len(text) > room or _key(text) in seen:
            continue
        seen.add(_key(text))
        picked.append(text)
        room -= len(text)
    return picked


def _piece(kind: str, on: str, r: dict, title: object, text: str) -> dict:
    if len(text) > EXAMPLE_CHARS:  # up to the last whole word that fits
        text = text[: EXAMPLE_CHARS - 1].rsplit(" ", 1)[0].rstrip() + "…"
    return {"kind": kind, "on": on, "ts": r["ts"], "title": _one_line(title), "text": text}


def _own(r: dict) -> bool:
    """A post the user wrote: marked as theirs, or, in a stream with no mark because it's only
    theirs, a post or a reply rather than a repost or a page."""
    if r.get("from_me") is None:
        return r.get("kind") in ("post", "reply")
    return r["from_me"] is True


def _enough(text: str) -> bool:
    return len(_WORD.findall(text)) >= MIN_WORDS


def _tidy(text: object) -> str:
    """A text with its own line breaks, each line's spacing evened, no run of blank lines."""
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _key(text: str) -> str:
    """A text as compared for repeats: one line, as proxenos.chats shows a message, or not."""
    return " ".join(text.split()).replace(" / ", " ").casefold()[:200]


def _fold(name: object) -> str:
    return " ".join(str(name or "").casefold().split())


def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _join(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)
