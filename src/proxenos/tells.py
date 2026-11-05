"""The tells of a model's writing, taken out of a draft after the model, unless they're the user's.

Recipients have noticed that drafts sound like an AI: the em dashes, "I hope this email finds you
well", "I wanted to reach out", a stack of closers, "delve" and "seamless", "I'd be more than
happy to", exclamation marks by the handful, and a "Best," with a full name and title block under
a chat message. The writing rules (voice.RULES) already ask the model not to; this is the check
in code on every draft, so the ones that slip through don't reach anyone.

Each tell is either dropped (a whole opener or closer sentence) or rewritten in the plainest
equivalent ("leverage" to "use"), so what a draft says never changes. Nothing here guesses: a
sentence is dropped only when it is the tell and nothing else, and a figurative "navigate" only
when it navigates a process.

A tell the user really writes stays. `used` counts, in the user's own sent messages and emails
(proxenos.voice.Writing, which leaves out any draft of Proxenos's they sent nearly unchanged),
how many use each one, and a tell in at least MIN_TEXTS of them, and in at least MIN_SHARE of all,
is theirs and left alone. `frequencies` gives the same counts for any texts, so a draft's rate
can be set beside theirs.
"""

import re
from collections.abc import Iterable

MIN_TEXTS = 2  # of the user's own texts that must use a tell for it to be theirs
MIN_SHARE = 0.02  # and this share of all of them, so a stray use in a thousand doesn't count

CHATS = frozenset({"whatsapp", "slack", "linkedin", "instagram", "messenger", "x", "twitter"})

# What the writing rules tell the model never to write, in the same words as the checks below.
NEVER = (
    'em dashes; "I hope this email finds you well", "I hope you are doing well", "I trust this", '
    '"I wanted to reach out" and "Just following up"; "Please don\'t hesitate to reach out", and '
    '"Looking forward to hearing from you" after another closer; "I\'d be more than happy to"; '
    '"Thank you so much for" twice; the words delve, seamless, leverage, robust, crucial, '
    "pivotal, tapestry, and navigate for a process or a problem; more than one exclamation mark; "
    'and, in a chat, a "Best," with a full name and title block under it'
)


def _sentence(core: str) -> re.Pattern:
    """A whole sentence that is `core` and nothing else, with its end and line break, so dropping
    it takes nothing else with it. It may start a line or a sentence, or follow a greeting's
    comma ("Hi Ana, I hope...")."""
    start = r"(?:(?<=\n)|^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=, ))"
    return re.compile(
        rf"{start}[ \t]*(?:{core})(?=[.!]|[ \t]*(?:\n|$))[.!]*[ \t]*\n?", re.IGNORECASE
    )


_EM = re.compile(r"\s*(?:—|(?<=\s)–|--)\s*")
_OPENER_DROP = [
    _sentence(
        r"I hope (?:this|that this) (?:email|e-mail|message|note) finds you(?: [^.!?\n]{0,30})?"
    ),
    _sentence(
        r"I hope (?:you(?:'re| are)(?: all)?(?: doing)?|this finds you|all is)(?: very)? well"
        r"(?: (?:and \w+|today|this week|these days|at the moment))?"
    ),
    _sentence(r"I trust (?:this|that this) (?:email|e-mail|message|note)[^.!?\n]{0,40}"),
    _sentence(r"Just following up"),
]
_REACH_OUT = re.compile(
    r"\bI wanted to reach out(?: to you)?(?: (?:to|and|about|regarding)\b)?", re.IGNORECASE
)
_FOLLOWING = re.compile(r"\bJust (following up|checking in|circling back)\b", re.IGNORECASE)
_HESITATE = _sentence(
    r"(?:(?:Please|Do|Pls) )?(?:don'?t|do not) hesitate to (?:reach out|contact me|get in touch|ask)"
    r"(?: [^.!?\n]{0,60})?|(?:Please )?feel free to (?:reach out|contact me|get in touch)"
    r"(?: [^.!?\n]{0,60})?"
)
_LOOKING = _sentence(
    r"(?:I(?:'m| am) )?looking forward to (?:hearing from you|your (?:reply|response)|hearing back)"
    r"(?: [^.!?\n]{0,30})?"
)
_OTHER_CLOSERS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"let me know if you have any (?:questions|other)",
        r"thank you (?:so much )?for your (?:time|consideration)",
        r"thanks again",
        r"I look forward to",
        r"looking forward to (?:seeing|connecting|speaking|talking)",
    )
]
_MORE_THAN_HAPPY = re.compile(r"\bI(?:'d| would) be more than happy to\b", re.IGNORECASE)
_THANKS = re.compile(r"\bThank you so much for\b")
_SWAPS = [  # (the tell, its plain equivalent): case is kept as the tell was written
    (r"\bseamlessly\b", "smoothly"),
    (r"\bseamless\b", "smooth"),
    (r"\bleveraging\b", "using"),
    (r"\bleveraged\b", "used"),
    (r"\bleverages\b", "uses"),
    (r"\bleverage\b", "use"),
    (r"\brobust\b", "solid"),
    (r"\bcrucial\b", "important"),
    (r"\bpivotal\b", "key"),
    (r"\btapestry\b", "mix"),
    (r"\bdelves into\b", "looks into"),
    (r"\bdelved into\b", "looked into"),
    (r"\bdelving into\b", "looking into"),
    (r"\bdelve into\b", "look into"),
    (r"\bdelves\b", "digs"),
    (r"\bdelved\b", "dug"),
    (r"\bdelving\b", "digging"),
    (r"\bdelve\b", "dig"),
]
# "Navigate" is only a tell for a process or a problem, never for a page or a route.
_PROCESS = (
    r"(?=\s+(?:the|these|this|those|through)\s+(?:process|processes|challenges?|complexit(?:y|ies)|"
    r"system|landscape|situation|paperwork|requirements?|transition|bureaucracy|rules)\b)"
)
_SWAPS += [
    (rf"\bnavigates\b{_PROCESS}", "works through"),
    (rf"\bnavigated\b{_PROCESS}", "worked through"),
    (rf"\bnavigating\b{_PROCESS}", "working through"),
    (rf"\bnavigate\b{_PROCESS}", "work through"),
]
_SWAP = [(re.compile(p, re.IGNORECASE), plain) for p, plain in _SWAPS]
_SIGN_OFF = re.compile(
    r"(?:best|best wishes|best regards|kind regards|regards|warm regards|thanks|thank you|cheers|"
    r"warmly|sincerely|yours sincerely),?",
    re.IGNORECASE,
)

# Every tell by name, with how to see it in a text, for `used` and `frequencies`.
_SEEN: dict[str, re.Pattern] = {
    "em dash": re.compile(r"—"),
    "opener": re.compile(
        r"I hope (?:this|that this|you(?:'re| are)|all is)[^.!?\n]*(?:well|finds you)|"
        r"I trust (?:this|that you)|I wanted to reach out|Just following up",
        re.IGNORECASE,
    ),
    "closer": re.compile(
        r"(?:don'?t|do not) hesitate to|looking forward to hearing from you", re.IGNORECASE
    ),
    "happy": _MORE_THAN_HAPPY,
    "thanks": re.compile(r"Thank you so much for"),
    "words": re.compile(
        r"\b(?:delv(?:e|es|ed|ing)|seamless(?:ly)?|leverag(?:e|es|ed|ing)|robust|crucial|"
        r"pivotal|tapestry)\b",
        re.IGNORECASE,
    ),
    "exclamations": re.compile(r"!.*!", re.DOTALL),
    "signature": re.compile(r"\n\s*(?:best|kind regards|regards|sincerely),?\s*\n", re.IGNORECASE),
}


def frequencies(texts: Iterable[str]) -> dict[str, float]:
    """The share of `texts` each tell is in, by name: how often the user writes it, or a batch of
    drafts does."""
    texts = list(texts)
    if not texts:
        return dict.fromkeys(_SEEN, 0.0)
    return {name: sum(bool(p.search(t)) for t in texts) / len(texts) for name, p in _SEEN.items()}


def used(texts: Iterable[str]) -> frozenset[str]:
    """The tells the user writes, by name, from their own sent `texts`: each in MIN_TEXTS or more
    of them and in MIN_SHARE of all."""
    texts = list(texts)
    share = frequencies(texts)
    return frozenset(
        name
        for name, p in _SEEN.items()
        if sum(bool(p.search(t)) for t in texts) >= MIN_TEXTS and share[name] >= MIN_SHARE
    )


def clean(body: str, theirs: frozenset[str] = frozenset(), chat: bool = False) -> str:
    """`body` without the tells that aren't `theirs` (see `used`). In a `chat`, no signature."""
    if "opener" not in theirs:
        for pattern in _OPENER_DROP:
            body = pattern.sub("", body)
        body = _REACH_OUT.sub(_reach_out, body)
        body = _FOLLOWING.sub(lambda m: _same_case(m[1][0].upper() + m[1][1:], m[0]), body)
    if "closer" not in theirs:
        body = _closers(body)
    if "happy" not in theirs:
        body = _MORE_THAN_HAPPY.sub(lambda m: _same_case("I'm glad to", m[0]), body)
    if "thanks" not in theirs:
        body = _later(body, _THANKS, "Thanks for")
    if "words" not in theirs:
        for pattern, plain in _SWAP:
            body = pattern.sub(lambda m, plain=plain: _same_case(plain, m[0]), body)
    if "em dash" not in theirs:
        body = _dashes(body)
    if "exclamations" not in theirs:
        body = _exclaim(body)
    if chat and "signature" not in theirs:
        body = _signature(body)
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", body)).strip()


def _reach_out(m: re.Match) -> str:
    """ "I wanted to reach out to ask" as "I'm writing to ask"; "I wanted to reach out about" as
    "I'm writing about"."""
    tail = m[0].lower().split("reach out", 1)[1].strip()
    tail = tail.removeprefix("to you").strip()
    return "I'm writing" + (
        f" {tail}" if tail in ("about", "regarding", "to") else " to" * bool(tail)
    )


def _same_case(plain: str, written: str) -> str:
    """`plain` capitalised as `written` was."""
    if written.isupper() and len(written) > 1:
        return plain.upper()
    return plain[:1].upper() + plain[1:] if written[:1].isupper() else plain


def _closers(body: str) -> str:
    """Hesitate-to-reach-out sentences always go; "looking forward to hearing from you" goes
    when another closer stands, so one closer is left."""
    stacked = len(_HESITATE.findall(body)) + sum(len(p.findall(body)) for p in _OTHER_CLOSERS)
    body = _HESITATE.sub("", body)
    return _LOOKING.sub("", body) if stacked else body


def _later(body: str, pattern: re.Pattern, plain: str) -> str:
    """The second and later `pattern` as `plain`: said once, it's thanks; said twice, a habit."""
    seen = 0

    def swap(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        return m[0] if seen == 1 else plain

    return pattern.sub(swap, body)


def _dashes(body: str) -> str:
    """Em dashes (and a spaced en dash or "--") as what the sentence allows: a pair around an
    aside as parentheses, a lone one as a comma, or a full stop when a new sentence follows."""
    out = []
    for line in body.split("\n"):
        parts = _EM.split(line)
        if len(parts) == 1:
            out.append(line)
            continue
        if len(parts) == 3:  # one aside: "X — Y — Z"
            line = f"{parts[0]} ({parts[1].strip()})" + (
                parts[2] if parts[2][:1] in ".,;:!?)" else " " + parts[2]
            )
            out.append(line.rstrip())
            continue
        text = parts[0]
        for part in parts[1:]:
            new_sentence = part[:1].isupper() and part[:2] != "I " and not part.startswith("I'")
            text += (". " if new_sentence else ", ") + part
        out.append(re.sub(r"([.,]) ?[.,]", r"\1", text).rstrip(", "))
    return "\n".join(out)


def _exclaim(body: str) -> str:
    """The first exclamation mark stays; each later one is a full stop."""
    seen = 0

    def swap(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        return "." if seen > 1 else "!"

    return re.sub(r"!+", swap, body)


def _signature(body: str) -> str:
    """A chat message without a closing word and the name and titles under it: a sign-off line
    in the last few lines, then only short lines to the end."""
    lines = body.rstrip().split("\n")
    for i in range(max(len(lines) - 6, 1), len(lines)):
        first = lines[i].strip()
        inline = re.match(rf"({_SIGN_OFF.pattern})\s+\S+(?:\s+\S+){{0,3}}$", first, re.IGNORECASE)
        if (_SIGN_OFF.fullmatch(first) or inline) and all(
            len(line.split()) <= 8 and not re.search(r"[.?!]$", line.strip())
            for line in lines[i + 1 :]
        ):
            return "\n".join(lines[:i]).rstrip()
    return body
