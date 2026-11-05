"""A draft that says the user did something they never did.

One draft said "I've actually just settled the invoice" when no payment was anywhere in the
records. Sent as it was, it tells someone a thing that isn't true, in the user's name. So the
drafting prompts say never to claim an action (voice.RULES), and this checks the draft too, in
code: each first-person claim of a done action ("I've paid", "I sent", "I submitted", "I've
booked", "I signed", "I called") becomes a question for the user, "Did you already ...?", unless
the user's own messages in the records the draft was given say they did it.

It is conservative on purpose: only "I" with the verb in the past (so "I haven't paid", "will pay"
and "Have I sent" never match), not after "if", "once" and the like, and a claim counts as shown
by any message of the user's that has the verb or its noun in it ("paid", "payment"), whatever it
says of it: a missed claim costs less than a question asked every time.
"""

import re

MAX_ASKS = 2  # of these a draft gets: more is noise
OBJECT_WORDS = 7  # of what was done, repeated in the question

# The verbs: as a claim says it, what to ask with, and the words in the user's own messages that
# show it was done or at least spoken of.
_ACTIONS = {
    "paid": ("pay", r"pay|pays|paid|paying|payment|payments"),
    "settled": ("settle", r"settle|settled|settling|settlement|pay|paid|payment"),
    "sent": ("send", r"send|sends|sent|sending"),
    "submitted": ("submit", r"submit|submits|submitted|submitting|submission"),
    "booked": ("book", r"book|books|booked|booking|bookings"),
    "signed": ("sign", r"sign|signs|signed|signing|signature"),
    "called": ("call", r"call|calls|called|calling|rang|phoned"),
    "transferred": ("transfer", r"transfer|transferred|transferring|wire|wired"),
}
_CLAIM = re.compile(
    r"(?<![\w'’])I(?:['’]ve|\s+have)?\s+(?:(?:just|already|actually|now|also|finally|only)\s+)*"
    rf"(?P<verb>{'|'.join(_ACTIONS)})\b(?P<rest>[^.!?\n;:()]*)",
    re.IGNORECASE,
)
# Said before it, a claim is a condition or a question, not a claim: "once I've paid", "have I sent".
_CONDITION = re.compile(
    r"\b(?:if|once|when|after|before|unless|until|whether|have|had|did|do|can|could|would|should|will)\s+$",
    re.IGNORECASE,
)
_END = re.compile(
    r"\s+(?:and|but|so|because|before|since|yet|as|which|when|while|though|if|then|until)\b.*",
    re.IGNORECASE,
)
_YOURS = {"my": "your", "me": "you", "i": "you", "myself": "yourself", "mine": "yours"}


def unproven(text: str, said: list[str]) -> list[str]:
    """The questions a draft's claims of done actions raise: "Did you already ...?" for each
    that none of `said` (the user's own messages the draft was given) has the verb or its noun
    in."""
    asks: list[str] = []
    for m in _CLAIM.finditer(text):
        if _CONDITION.search(text[max(0, m.start() - 15) : m.start()]):
            continue
        verb, shown = _ACTIONS[m["verb"].lower()]
        if any(re.search(rf"\b(?:{shown})\b", t, re.IGNORECASE) for t in said):
            continue
        asks.append(f"Did you already {verb}{_object(m['rest'])}?")
    return list(dict.fromkeys(asks))[:MAX_ASKS]


def _object(rest: str) -> str:
    """What was done, as the question puts it: the words after the verb up to the next clause,
    from the user's side ("my" to "your"), or "" when there are none to repeat."""
    words = _END.sub("", rest).replace(",", " ").split()[:OBJECT_WORDS]
    if words and words[0].lower() == "you":  # "I sent you the form": to them, not to you
        words[0] = "them"
    words = [_YOURS.get(w.lower(), w) for w in words]
    return " " + " ".join(words) if words else ""
