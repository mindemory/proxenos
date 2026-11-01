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

Then what they changed. A draft they rewrote says more about how they write than any example:
fidelity keeps each measured draft beside what they sent instead (clones/drafts/fidelity.json),
the page keeps each draft they edited there beside their version (an edit's before and after
in clones/drafts/feedback.jsonl), and every draft gets those whose closeness was under CHANGED,
newest first, to the same person first, then on the same channel, CORRECTION_CHARS in all, to
write like what was sent and never like what was drafted. So a change counts from the next draft
on, without training anything.

Ahead of those pairs go the writing rules the user kept (RULES_FILE, RULES_CHARS of them): short
rules learned from the same changes, the PROSE way (arXiv 2505.23815, which improved on CIPHER,
arXiv 2404.15269). Each night `lessons` reads the changed drafts it hasn't read yet, and once
there are NEW_PAIRS of them, has the model infer rules from each batch of pairs: how the user
writes, to a person or on a channel where the evidence is that specific. A rule is kept only if
it holds on at least HOLDS of the user's own sent messages outside the pairs it read, as one
more call per batch of rules judges them; a rule about health, or quoting more than a few words,
never is. The rules kept are proposed, not used: how the user writes is a slow part of the
self-model, which changes only through proposals they accept, so the rules go in self/proposals/
as the master's slow files do, and reach a draft only once the user accepts them (`proxenos
master accept`). That needs nothing new, where keeping rules on the page would: accept already
moves every proposal into self/, and the page already shows self/'s files. The accepted file is
theirs to edit; each line starting with "- " is a rule. A proposal starts from it as it stands.
"""

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import cached_property
from pathlib import Path

from proxenos import chats, llm
from proxenos.config import env

MONTHS = 3  # of each chat stream, the newest month files read for examples
MIN_WORDS = 2
MESSAGE_CHARS = 2500  # of examples for a message in a chat
LONG_CHARS = 5000  # for an email, a post or a doc
LONG_MIN = 200  # characters a text needs to count as longer writing
EXAMPLE_CHARS = 1500  # of one piece of longer writing
CORRECTION_CHARS = 2000  # of drafts the user changed, with what they sent instead
CHANGED = 0.85  # closeness under this: they changed enough of a draft to learn from
RULES_FILE = Path("self", "voice_rules.md")  # the writing rules the user kept
PROPOSED = Path("self", "proposals", "voice_rules.md")  # rules waiting on them
LESSONS = Path("state", "voice_lessons.json")  # when lessons last ran, and the pairs it read
RULES_CHARS = 1500  # of kept rules in a draft's prompt
RULE_CHARS = 200  # of one rule
MAX_RULES = 30  # a proposal adds none past this many
NEW_PAIRS = 5  # changed drafts not read yet, before lessons asks the model anything
PAIRS = 24  # the most of them one run reads, newest first; the rest wait for the next
PAIR_BATCH = 8  # pairs per call that infers rules
PAIR_CHARS = 1200  # of a draft and of what was sent, as fidelity keeps them
RULE_BATCH = 6  # rules per call that checks them
SAMPLE = 8  # of the user's own sent messages a rule is checked on
SAMPLE_CHARS = 600  # of one: its start and its end, where greetings and sign-offs are
HOLDS = 3  # of those a rule must hold on, and on more than it breaks on, to be kept
QUOTE_WORDS = 4  # the longest quote a rule may carry: a greeting, a sign-off, a filler
LEARNED = 2000  # pairs remembered as read
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
# What makes a rule about health, which a writing rule never is.
_HEALTH = re.compile(
    r"health|\bmedic|\bdoctors?\b|\bdentists?\b|\bclinics?\b|\bhospital|\bnurs(e|es|ing)\b|"
    r"\btherap|\bdiagnos|\bsymptom|\bill(ness)?\b|\bsick|\bunwell\b|\bpains?\b|\binjur|"
    r"\bdiseases?\b|\bprescri|\bpharmac|\bsurg(ery|eon)|\bmental|\banxi|\bdepress|\bpregnan|"
    r"\bmeds\b",
    re.IGNORECASE,
)
_QUOTE = re.compile(r"\"([^\"]*)\"|“([^”]*)”|‘([^’]*)’|(?<!\w)'([^']*)'(?!\w)")
_BULLET = re.compile(r"\s*[-*]\s+(.*\S)")

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
    def corrections(self) -> list[dict]:
        """Drafts they changed before sending, newest sent first, as fidelity measured them:
        {source, to, draft_text, sent_text}."""
        folder = self.vault / "clones" / "drafts"
        try:
            measured = json.loads((folder / "fidelity.json").read_text(encoding="utf-8"))["drafts"]
        except (OSError, ValueError, KeyError, TypeError):
            measured = []
        measured = [*_edits(folder / "feedback.jsonl"), *(m for m in measured or [] if m)]
        return [
            m
            for m in sorted(
                (m for m in measured if isinstance(m, dict)),
                key=lambda m: str(m.get("sent") or m.get("ts") or ""),
                reverse=True,
            )
            if isinstance(m, dict)
            and isinstance(m.get("closeness"), int | float)
            and m["closeness"] < CHANGED
            and _tidy(m.get("draft_text"))
            and _enough(_tidy(m.get("sent_text")))
        ]

    @cached_property
    def rules(self) -> list[str]:
        """The writing rules they kept (RULES_FILE), in their order."""
        return kept(self.vault)

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
    changed = corrections(written, source, name)
    if source in NAMES:
        return _join(messages(written, source, chat=chat, name=name, here=here), changed)
    if source is None:  # not known yet: how they write in chats, and at length
        return _join(messages(written, None, name=name), longer(written, first), changed)
    mine = messages(written, source, here=here) if here else ""
    return _join(mine, longer(written, first), changed)


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


def _edits(path: Path) -> list[dict]:
    """The drafts the user rewrote on the page, as fidelity lists a draft and what was sent."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not (isinstance(event, dict) and event.get("action") == "edit"):
            continue
        before, after = _tidy(event.get("before")), _tidy(event.get("after"))
        if before and after and before != after:
            channel = str(event.get("channel") or "")
            found.append(
                {
                    "source": _SOURCE_OF.get(channel, channel),
                    "to": event.get("to") or "",
                    "ts": str(event.get("ts") or ""),
                    "closeness": round(SequenceMatcher(None, before, after).ratio(), 2),
                    "draft_text": before,
                    "sent_text": after,
                }
            )
    return found


def corrections(written: Writing, source: str | None, name: object = "") -> str:
    """The writing rules the user kept, RULES_CHARS of them, then the drafts they changed before
    sending, each beside what they sent: to `name` first, then the rest on `source` (any source
    when None), newest first, CORRECTION_CHARS in all."""
    return _join(_kept_rules(written.rules), _changed(written, source, name))


def _kept_rules(rules: list[str]) -> str:
    """The rules, in order, as many as fit in RULES_CHARS. Each says where it applies."""
    shown, room = [], RULES_CHARS
    for rule in rules:
        if len(rule) <= room:
            shown.append(f"- {rule}")
            room -= len(rule)
    if not shown:
        return ""
    person = env("NAME", "the person")
    head = (
        f"How {person} writes, in rules learned from drafts they changed, checked against their "
        f"own messages and kept by them. Follow each one where it applies:"
    )
    return "\n".join([head, *shown])


def _changed(written: Writing, source: str | None, name: object) -> str:
    pool = [m for m in written.corrections if source in (None, m.get("source"))]
    to = _fold(name)
    pool.sort(key=lambda m: not (to and _fold(m.get("to")) == to))  # stable: newest stays first
    shown, room = [], CORRECTION_CHARS
    for m in pool:
        drafted, sent = _tidy(m["draft_text"]), _tidy(m["sent_text"])
        if len(drafted) + len(sent) > room:
            continue
        room -= len(drafted) + len(sent)
        shown.append(f"<drafted>\n{drafted}\n</drafted>\n<sent>\n{sent}\n</sent>")
    if not shown:
        return ""
    person = env("NAME", "the person")
    head = (
        f"Drafts written for {person} that they changed before sending, newest first, each "
        f"beside what they sent instead. Write like what they sent, never like the draft. "
        f"{_COPY}"
    )
    return "\n".join([head, *shown])


# Rules learned from the drafts the user changed

_INFER = """\
You learn how {person} writes from drafts written for them that they changed before sending. \
Each pair is a draft and what {person} sent instead, with the channel it went on and whom it \
was to.

Write the rules the changes show: what {person} does that the drafts didn't, as instructions \
a writer could follow.
- One habit per rule, under 25 words, about how they write: length, greeting, sign-off, the \
languages they mix, case, punctuation, emoji, tone, what comes first, what they leave out.
- Say where it applies, in the rule and in channel and to: to one person ("To Mom, in \
Marathi-English mix, no sign-off") or on one channel ("Emails to editors: two short \
paragraphs, thanks first") where the pairs that show it are all to that person or on that \
channel. to is that person's name as a pair gives it, else "". channel "any" and to "" only \
when pairs on several channels or to several people agree.
- Only habits the pairs show plainly. A change of facts (a date, a name, a plan) says nothing \
about how they write.
- Never about health, illness or anyone's body or mind, and never about what a message said.
- Never quote a sentence. A rule may quote a greeting, a sign-off or a filler of a few words \
that {person} wrote, never anyone else's words.
- Leave out any rule already in their rules so far, however it's worded.
Return no rules when the changes show nothing about how they write."""

_CHECK = """\
You check rules about how {person} writes against messages {person} sent. Each rule names the \
messages to check it on. For each of those, say whether the rule holds (the message does what \
the rule says) or breaks (the message is the kind the rule is about and doesn't do it), and \
leave a message out of both when the rule isn't about that kind of message. Judge only how a \
message is written, never what it says. Give a verdict for every rule."""

_HEAD = """\
# How {person} writes

Rules learned from drafts written for {person} that they changed before sending, each checked \
against their own sent messages. Every draft written for them follows each line below that \
starts with "- ". Change or delete any line, or add your own."""


def lessons(vault: Path, now: datetime | None = None) -> dict[str, int]:
    """Rules learned from the changed drafts not read yet, checked against the user's own sent
    messages, and proposed for RULES_FILE. While fewer than NEW_PAIRS are new it does nothing,
    and asks the model nothing. LESSONS keeps when it last ran, the pairs it read, and the rules
    it proposed, so a rule the user deleted or turned down isn't proposed again."""
    now = now or datetime.now(UTC)
    state = _state(vault)
    written = Writing(vault)
    new, seen = {}, set(state["read"])
    for m in written.corrections:  # newest first, each pair once
        if (key := _pair_key(m)) not in seen:
            seen.add(key)
            new[key] = m
    if len(new) < NEW_PAIRS:
        return {"new_changed_drafts": len(new)}
    reading = list(new)[:PAIRS]
    pairs = [new[key] for key in reading]
    person = env("NAME", "the person")
    have = [*kept(vault), *_rules_in(_text(vault / PROPOSED))]
    inferred: list[dict] = []
    for start in range(0, len(pairs), PAIR_BATCH):
        inferred += _infer(pairs[start : start + PAIR_BATCH], have, person)
    known = {_fold(rule) for rule in [*have, *state["proposed"]]}
    fresh, refused = [], 0
    for rule in inferred:
        if _fold(rule["rule"]) in known:
            continue
        known.add(_fold(rule["rule"]))
        if _allowed(rule["rule"]):
            fresh.append(rule)
        else:
            refused += 1
    held = _check(written, fresh, pairs, person)
    proposed = _propose(vault, held, person)
    state = {
        "ran": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "read": [*reading, *state["read"]][:LEARNED],
        "proposed": [*proposed, *state["proposed"]][:LEARNED],
    }
    _write_private(vault / LESSONS, json.dumps(state, ensure_ascii=False, indent=1))
    return {
        "new_changed_drafts": len(new),
        "rules_inferred": len(fresh) + refused,
        "rules_refused": refused,
        "rules_held": len(held),
        "rules_proposed": len(proposed),
    }


def kept(vault: Path) -> list[str]:
    """The writing rules in RULES_FILE as the user keeps it, in order, each cut to RULE_CHARS."""
    return _rules_in(_text(vault / RULES_FILE))


def _infer(pairs: list[dict], have: list[str], person: str) -> list[dict]:
    """One call: the rules a batch of changed drafts shows, as {rule, channel, to}."""
    shown = []
    for n, m in enumerate(pairs, 1):
        about = f'n="{n}" channel="{_channel(m.get("source"))}"'
        if to := _one_line(m.get("to")).replace('"', "'"):
            about += f' to="{to}"'
        shown.append(
            f"<pair {about}>\n<drafted>\n{_cut(m['draft_text'])}\n</drafted>\n"
            f"<sent>\n{_cut(m['sent_text'])}\n</sent>\n</pair>"
        )
    parts = []
    if have:
        parts.append(f"{person}'s rules so far:\n" + "\n".join(f"- {rule}" for rule in have))
    parts.append(
        f"Drafts written for {person} that they changed before sending, newest first:\n"
        + "\n".join(shown)
    )
    answer = llm.ask(
        "\n\n".join(parts),
        system=_INFER.format(person=person),
        schema=_INFER_SCHEMA,
        effort="medium",
    )
    found = []
    for rule in answer.get("rules") or []:
        text = _one_line(rule.get("rule")) if isinstance(rule, dict) else ""
        if text and len(text) <= RULE_CHARS:
            channel = rule.get("channel") if rule.get("channel") in _RULE_CHANNELS else "any"
            found.append({"rule": text, "channel": channel, "to": _one_line(rule.get("to"))})
    return found


def _allowed(rule: str) -> bool:
    """A rule never about health, and quoting no more than a few words."""
    quoted = (next(q for q in m.groups() if q is not None) for m in _QUOTE.finditer(rule))
    return not _HEALTH.search(rule) and all(len(_WORD.findall(q)) <= QUOTE_WORDS for q in quoted)


def _check(written: Writing, rules: list[dict], pairs: list[dict], person: str) -> list[str]:
    """The rules that hold on at least HOLDS of the user's own sent messages, and on more of
    them than they break on, with none of what was sent in `pairs` among them: one call for
    each RULE_BATCH rules. A rule with fewer than HOLDS messages to check isn't asked about."""
    sent = [_tidy(m["sent_text"]) for m in pairs]
    skip = {_key(text) for whole in sent for text in [whole, *whole.splitlines()]}
    asked = [(rule, _sample(written, rule, skip)) for rule in rules]
    asked = [(rule, sample) for rule, sample in asked if len(sample) >= HOLDS]
    held = []
    for start in range(0, len(asked), RULE_BATCH):
        batch = asked[start : start + RULE_BATCH]
        numbers: dict[str, int] = {}  # each message once, by its key
        shown, lines, ids = [], [], []
        for n, (rule, sample) in enumerate(batch, 1):
            mine = []
            for m in sample:
                if _key(m["text"]) not in numbers:
                    numbers[_key(m["text"])] = len(numbers) + 1
                    shown.append(_message(len(numbers), m))
                mine.append(numbers[_key(m["text"])])
            ids.append(set(mine))
            which = ", ".join(map(str, mine))
            lines.append(f'<rule n="{n}" messages="{which}">{rule["rule"]}</rule>')
        prompt = (
            f"Messages {person} sent, newest first:\n"
            + "\n".join(shown)
            + "\n\nThe rules, each with the messages to check it on:\n"
            + "\n".join(lines)
        )
        answer = llm.ask(
            prompt, system=_CHECK.format(person=person), schema=_CHECK_SCHEMA, effort="medium"
        )
        verdicts = {v.get("rule"): v for v in answer.get("verdicts") or [] if isinstance(v, dict)}
        for n, ((rule, _), mine) in enumerate(zip(batch, ids, strict=True), 1):
            verdict = verdicts.get(n) or {}
            holds = _numbers(verdict.get("holds")) & mine
            breaks = (_numbers(verdict.get("breaks")) & mine) - holds
            if len(holds) >= HOLDS and len(holds) > len(breaks):
                held.append(rule["rule"])
    return held


def _sample(written: Writing, rule: dict, skip: set[str]) -> list[dict]:
    """The user's own sent messages a rule is checked on, newest first, SAMPLE at most and none
    in `skip`: on its channel, and in chats, only those to the person it names."""
    channel = rule["channel"]
    mine = [
        {"channel": m["source"], "to": m["name"], "ts": m["ts"], "text": m["text"]}
        for m in written.messages
        if channel in ("any", m["source"])
    ]
    if channel in ("any", "email"):  # an email's recipients aren't kept: its greeting says
        mine += [
            {"channel": "email", "to": "", "ts": t["ts"], "text": t["text"]}
            for t in written.long
            if t["kind"] == "email"
        ]
    mine.sort(key=lambda m: m["ts"], reverse=True)
    mine = [m for m in mine if _key(m["text"]) not in skip]
    if (to := _fold(rule["to"])) and channel != "email":
        mine = [m for m in mine if _fold(m["to"]) == to]
    return mine[:SAMPLE]


def _message(n: int, m: dict) -> str:
    about = f'n="{n}" channel="{m["channel"]}"'
    if to := _one_line(m["to"]).replace('"', "'"):
        about += f' to="{to}"'
    text = m["text"]
    if len(text) > SAMPLE_CHARS:  # its start and its end
        half = SAMPLE_CHARS // 2
        text = f"{text[:half].rstrip()} … {text[-half:].lstrip()}"
    return f"<message {about}>\n{text}\n</message>"


def _propose(vault: Path, rules: list[str], person: str) -> list[str]:
    """Add `rules` to the proposal for RULES_FILE: the file as the user keeps it, then the rules
    already waiting in the proposal, then these, MAX_RULES in all. The rules added."""
    text = _text(vault / RULES_FILE)
    current = _rules_in(text)
    known = {_fold(rule) for rule in current}
    waiting = [rule for rule in _rules_in(_text(vault / PROPOSED)) if _fold(rule) not in known]
    known |= {_fold(rule) for rule in waiting}
    new = []
    for rule in rules:
        if _fold(rule) not in known and len(current) + len(waiting) + len(new) < MAX_RULES:
            known.add(_fold(rule))
            new.append(rule)
    if not new:
        return []
    head = text.rstrip() or _HEAD.format(person=person)
    between = "\n" if _BULLET.fullmatch(head.splitlines()[-1]) else "\n\n"
    lines = "\n".join(f"- {rule}" for rule in [*waiting, *new])
    _write_private(vault / PROPOSED, f"{head}{between}{lines}\n")
    return new


def _rules_in(text: str) -> list[str]:
    """Each item of the list in a rules file ("- " or "* "), as one line, cut to RULE_CHARS."""
    rules = []
    for line in text.splitlines():
        if (bullet := _BULLET.fullmatch(line)) and (rule := _one_line(bullet[1])):
            if len(rule) > RULE_CHARS:  # up to the last whole word that fits
                rule = rule[: RULE_CHARS - 1].rsplit(" ", 1)[0].rstrip() + "…"
            rules.append(rule)
    return rules


def _state(vault: Path) -> dict[str, list[str]]:
    try:
        state = json.loads((vault / LESSONS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state = state if isinstance(state, dict) else {}
    return {
        key: [x for x in state.get(key) or [] if isinstance(x, str)] for key in ("read", "proposed")
    }


def _pair_key(m: dict) -> str:
    pair = f"{_tidy(m.get('draft_text'))}\0{_tidy(m.get('sent_text'))}"
    return hashlib.sha1(pair.encode()).hexdigest()[:16]


def _channel(source: object) -> str:
    """A pair's channel as a rule names it: "email", a chat source, or "other"."""
    return str(source) if source in _RULE_CHANNELS and source != "any" else "other"


def _numbers(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    return {n for n in value if isinstance(n, int) and not isinstance(n, bool)}


def _cut(text: object) -> str:
    text = _tidy(text)
    return text if len(text) <= PAIR_CHARS else text[: PAIR_CHARS - 1].rstrip() + "…"


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _write_private(path: Path, text: str) -> None:
    """Swap the file in whole, private to the user."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


_RULE_CHANNELS = ("any", "email", *NAMES)
_INFER_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string"},
                    "channel": {"type": "string", "enum": list(_RULE_CHANNELS)},
                    "to": {"type": "string"},
                },
                "required": ["rule", "channel", "to"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}
_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "integer"},
                    "holds": {"type": "array", "items": {"type": "integer"}},
                    "breaks": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["rule", "holds", "breaks"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


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
