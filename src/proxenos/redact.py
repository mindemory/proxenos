"""Numbers and secrets blanked from a prompt before it goes to a hosted model.

A prompt is built from the vault, and the vault keeps what came in by mail and chat: a bank's
one-time code, a card number someone sent, a key pasted into a note. No draft needs them, and
once sent they're out of the user's hands, so llm._ask blanks them in whatever goes to Anthropic
(a local model sees them, as nothing leaves the computer). Each becomes what it was, in brackets
("[card number]", "[code]"), so the model still reads a sentence that makes sense.

It's regular expressions, fast on a long prompt and conservative: a number is blanked only where
its shape or the words around it say what it is (a card number that passes the Luhn check, an IBAN
that passes its own, "your code is 123456", "password: ..."), so dates, times, prices, phone and
street numbers, order numbers and the like stay, as drafts need them. A call checks the numbers
it says itself (calls.guard), and care.py blanks more in health records than this does.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable
from typing import NamedTuple

# Shapes forms.py and clones/care.py blank wherever they are; here a card-shaped number must also
# be one (`_card`).
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[A-Za-z0-9+/=\s]*(?:-----END [A-Z ]*PRIVATE KEY-----)?"
)
# Keys and tokens by the prefixes their makers give them.
_KEY = re.compile(
    r"(?<![\w-])(?:"
    r"sk-(?:ant-|proj-|svcacct-|or-)?(?=[\w-]*\d)[\w-]{20,}"  # Anthropic, OpenAI, OpenRouter
    r"|[rsp]k_(?:live|test)_[0-9A-Za-z]{16,}|whsec_[0-9A-Za-z]{16,}"  # Stripe
    r"|gh[pousr]_[0-9A-Za-z]{30,}|github_pat_\w{30,}|glpat-[\w-]{20,}"  # GitHub, GitLab
    r"|xox[abposr]-[0-9A-Za-z-]{10,}|xapp-[0-9A-Za-z-]{10,}"  # Slack
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}"  # AWS
    r"|AIza[\w-]{35}|ya29\.[\w-]{20,}"  # Google
    r"|hf_[0-9A-Za-z]{30,}|npm_[0-9A-Za-z]{36}|pypi-[\w-]{50,}|SG\.[\w-]{16,}\.[\w-]{16,}"
    r"|eyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{10,}"  # a JSON web token
    r")(?![\w-])"
)
_LABELLED = re.compile(
    r"\b(?:(?:api|secret|access|private|client)[_ -]?(?:key|secret|token)"
    r"|(?:auth|refresh|session|id)[_ -]?token|token|secret)\b[\"']?\s*(?:[:=]|\bis\b)\s*[\"']?"
    r"(?!\[)(?P<v>[\w.~+/=-]{12,})",
    re.IGNORECASE,
)
_BEARER = re.compile(r"\bbearer\s+(?P<v>[\w.~+/-]{16,}=*)", re.IGNORECASE)
# A long run of letters and digits, judged by `_random`; not a link's path, a file's name or an
# email address, whose names are ids a draft may need.
_RUN = re.compile(r"(?<![\w/\\.@%+-])[\w-]{32,}(?![\w/\\@%+-]|\.\w)", re.ASCII)
_WORDY = re.compile(r"[A-Z]?[a-z]{3,}|[A-Z]{4,}|\d{4,}")

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_SSN_SAID = re.compile(
    r"\b(?:ssn|social security(?: number| no\b\.?| #)?)\s*(?:is\b|[:#])?\s*[:#]?\s*"
    r"(?P<v>\d{3}[ -]?\d{2}[ -]?\d{4})(?![\d-])",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"\b(?:(?:account|acct|a/c)\.?\s*(?:number|num|no\b\.?|#)|acct\b\.?)"
    r"\s*(?:is\b|[:#-])?\s*[:#]?\s*(?P<v>\d(?:[ -]?\d){4,33})(?!\d)",
    re.IGNORECASE,
)

# One-time codes, in the phrasings that carry them. Words that make "code" something else (a
# zip code, a promo code, a booking's confirmation code) never do.
_NOT_SECRET = (
    r"(?!(?:zip|postal|area|country|promo|discount|coupon|referral|gift|access|door|gate|"
    r"confirmation|booking|reference|tracking|order|error|status|dress|source|tax|bar|qr|"
    r"invite|invitation|voucher|redemption)\b)"
)
_CODE_VALUE = (
    r"(?P<v>(?:[a-z]-)?\d{4,8}|\d{3}[ -]\d{3}"
    r"|(?-i:(?=[A-Z]*\d)(?=\d*[A-Z])[A-Z\d]{6,8}))(?![\w-])"
)
_CODE = re.compile(
    r"\b(?:(?:verification|security|login|log-?in|sign-?in|authentication|auth|one[- ]time|2fa|"
    r"two[- ]factor|mfa|otp)\s+(?:code|pin|passcode|password)"
    rf"|one[- ]time\s+pass(?:word|code)?|passcode|otp|your\s+(?:{_NOT_SECRET}(?-i:[A-Z])"
    r"[\w.-]*\s+){0,2}(?:code|otp|pin))(?:\s+for\s+\S+)?(?:\s*(?:is|was)\b\s*:?|\s*[:=#-])?\s*"
    + _CODE_VALUE,
    re.IGNORECASE,
)
_CODE_FIRST = re.compile(
    r"(?<![\w-])(?P<v>(?:[a-z]-)?\d{4,8}|\d{3}[ -]\d{3})\s+is\s+your\s+"
    rf"(?:{_NOT_SECRET}[\w.-]+\s+){{0,3}}?(?:code|otp|pin|passcode|password)\b",
    re.IGNORECASE,
)
_CODE_USE = re.compile(
    r"\b(?:use|enter)\s+(?:code\s+)?(?P<v>(?:[a-z]-)?\d{4,8}|\d{3}[ -]\d{3})\s+(?:to\s+"
    r"(?:verify|sign|log|confirm|complete|reset|authenticate|continue)\b|as\s+your\b)",
    re.IGNORECASE,
)
_PIN = re.compile(
    r"\b(?:pin(?:\s+(?:code|number))?\s*(?:(?:is|was)\b\s*:?|[:=#])"
    r"|(?:cvv2?|cvc2?|csc)\b\s*(?:(?:is|was)\b\s*:?|[:=#])?)\s*(?P<v>\d{3,8})(?![\w-])",
    re.IGNORECASE,
)
_PASSWORD = re.compile(
    r"\b(?:password|passwd|passphrase|pwd|pw)\b[\"']?\s*(?:(?P<is>is|was)\b\s*:?|[:=])\s*"
    r"[\"'“‘]?(?!\[)(?P<v>[^\s\"'“”‘’]{4,}?)(?:[\"'”’]|(?=[.,;)]?(?:\s|$)))",
    re.IGNORECASE,
)
# What follows "password:" or "password =" in code or a form rather than a password: a value
# like None, a call, an attribute (args.password) or a name in snake case (user_password).
_NOT_PASSWORDS = {"none", "null", "true", "false", "undefined", "required", "optional", "string"}
_CODE_NAME = re.compile(r".*[()\[\]{}<>].*|[A-Za-z_]+(?:\.[A-Za-z_]+)+|[a-z]+(?:_[a-z]+)+")

Span = tuple[int, int]


class _Rule(NamedTuple):
    kind: str  # what's counted
    label: str  # what's put in its place
    pattern: re.Pattern
    find: Callable[[re.Match], Span | None]  # the part to blank, or None to leave it


def redact(text: str, keep: Iterable[str] = ()) -> tuple[str, dict[str, int]]:
    """`text` with each number or secret no draft needs replaced by what it was, in brackets,
    and how many were, by kind. A value in `keep` stays wherever it is: what the caller means
    the model to have, such as the facts a call may tell."""
    kept = {b for v in keep if (b := _bare(v))}
    counts: Counter[str] = Counter()

    def blank(rule: _Rule, m: re.Match) -> str:
        span = rule.find(m)
        if span is None or _bare(m.string[span[0] : span[1]]) in kept:
            return m[0]
        counts[rule.kind] += 1
        return m.string[m.start() : span[0]] + rule.label + m.string[span[1] : m.end()]

    for rule in _RULES:
        text = rule.pattern.sub(lambda m, rule=rule: blank(rule, m), text)
    return text, dict(counts)


def _luhn(digits: str) -> bool:
    """Whether a card number's last digit checks out, as every card number's does."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _value(m: re.Match) -> Span:
    return m.span("v") if "v" in m.re.groupindex else m.span()


def _card(m: re.Match) -> Span | None:
    """The card number in a run of digits: groups of four or more (but the last) that start like
    a card's, add up to 13 to 19 digits and pass the Luhn check. A run holding more, like a
    phone number before a card or its expiry after, is searched for one."""
    groups = [g.span() for g in re.finditer(r"\d+", m[0])]
    for size in range(len(groups), 0, -1):
        for i in range(len(groups) - size + 1):
            run = groups[i : i + size]
            if any(end - start < 4 for start, end in run[:-1]):
                continue
            span = (m.start() + run[0][0], m.start() + run[-1][1])
            digits = re.sub(r"\D", "", m.string[span[0] : span[1]])
            if 13 <= len(digits) <= 19 and _is_card(digits) and _alone(m.string, *span):
                return span
    return None


def _is_card(digits: str) -> bool:
    if len(set(digits)) == 1 or not _luhn(digits):
        return False
    if digits[0] == "2":  # Mastercard's newer numbers; other numbers starting with 2 aren't cards
        return len(digits) == 16 and 2221 <= int(digits[:4]) <= 2720
    return digits[0] in "3456"


def _ssn(m: re.Match) -> Span | None:
    """A Social Security number, unless it can't be one (a part all zeros, area 666)."""
    span = _value(m)
    digits = re.sub(r"\D", "", m.string[span[0] : span[1]])
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in ("000", "666") or group == "00" or serial == "0000":
        return None
    return span if _alone(m.string, *span) else None


def _iban(m: re.Match) -> Span | None:
    """An IBAN that passes its check (mod 97), with any word the pattern took after it left."""
    found = m[0]
    while len(compact := found.replace(" ", "")) >= 15:
        if len(compact) <= 34 and _mod97(compact):
            return m.start(), m.start() + len(found)
        found = found[:-1].rstrip()
    return None


def _mod97(iban: str) -> bool:
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def _labelled(m: re.Match) -> Span | None:
    """A value labelled a key, token or secret, when it has letters and a digit like one."""
    value = m["v"]
    letters = sum(c.isalpha() for c in value)
    return m.span("v") if letters >= 2 and any(c.isdigit() for c in value) else None


def _password(m: re.Match) -> Span | None:
    """The password said, unless it's shown masked, it's "password is" and a plain word ("the
    password is incorrect"), or it's code that names one rather than says it."""
    value = m["v"]
    if set(value) <= set("*•●·xX") or (m["is"] and value.isalpha()):
        return None
    if value.lower() in _NOT_PASSWORDS or _CODE_NAME.fullmatch(value):
        return None
    return m.span("v")


def _random(m: re.Match) -> Span | None:
    """A run that reads as random: capitals, small letters and digits, mixed with no words in
    it, as a key or token is. Words joined (an identifier, a file's name) or a single case (a
    hash, an id in hex) stay."""
    found = m[0]
    core = found.replace("-", "").replace("_", "")
    if len(found) - len(core) > len(found) // 8:
        return None
    if not (re.search(r"[A-Z]", core) and re.search(r"[a-z]", core) and re.search(r"\d", core)):
        return None
    wordy = sum(len(w) for w in _WORDY.findall(core))
    return m.span() if wordy <= len(core) / 2 else None


def _alone(text: str, start: int, end: int) -> bool:
    """Whether text[start:end] isn't part of a longer run of digits joined by - . or /, nor a
    link's path, whose long numbers are ids."""
    before, after = text[max(0, start - 2) : start], text[end : end + 2]
    if before.endswith("/") or re.fullmatch(r"\d[-.]", before):
        return False
    return not re.fullmatch(r"[-./]\d", after)


def _bare(value: str) -> str:
    return re.sub(r"[\s-]", "", value)


# In order: a key first, so "password: sk-..." is one blank, not two.
_RULES = (
    _Rule("key", "[private key]", _PRIVATE_KEY, _value),
    _Rule("key", "[key]", _KEY, _value),
    _Rule("key", "[key]", _LABELLED, _labelled),
    _Rule("key", "[key]", _BEARER, _value),
    _Rule("iban", "[IBAN]", _IBAN, _iban),
    _Rule("card", "[card number]", CARD, _card),
    _Rule("ssn", "[SSN]", SSN, _ssn),
    _Rule("ssn", "[SSN]", _SSN_SAID, _ssn),
    _Rule("account", "[account number]", _ACCOUNT, _value),
    _Rule("code", "[code]", _CODE, _value),
    _Rule("code", "[code]", _CODE_FIRST, _value),
    _Rule("code", "[code]", _CODE_USE, _value),
    _Rule("code", "[code]", _PIN, _value),
    _Rule("password", "[password]", _PASSWORD, _password),
    _Rule("key", "[key]", _RUN, _random),
)
