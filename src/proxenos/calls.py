"""Phone calls placed for the user: whom to call and why, and what the assistant does on the line.

A call sheet, clones/calls/<id>.md, says whom to call and why, in front matter: title, to (who
answers), number, digits (the phone menu's keys, as Twilio plays them; w waits half a second),
about (what the call is about, as said to whoever answers), asks (what to ask for, in order),
facts (what the assistant may tell them, by name: the user's name, a date of birth, an account
number; it knows nothing else), and talk (true or false). The body is notes for the user. The
page lists the sheets; the user starts each call there or with `proxenos call start ID`
(callserver.py), and nothing calls on its own.

On the line, the assistant says nothing while the call is on hold. Twilio's speech recognition
hears each stretch of speech: one that sounds like the hold's own messages ("your call is
important to us") or repeats one heard before is the hold, and one that sounds like a person
picking up ("thanks for holding, this is ...") is someone answering; when neither is clear, the
model decides. To a person, the assistant first says what it is: "I'm an automated assistant
calling for <name>, and this call is transcribed." That's all it is: Twilio's speech recognition
hears it for the transcript, and nothing records it (twilio.Client.call). It never says it's
the user, and it has no voice of theirs.

Before a call, its number is checked against the vault (`doubt`): one that's in just one
message someone sent the user, and in nothing of theirs, may be a scam's, and the call waits
until the user says to call it anyway.

Then, by default, it rings the user's phone, and they press 1 to be put through (so voicemail
never is). With talk: true, or when the user doesn't come to the phone and there are asks, it
asks them itself, a turn at a time: the model reads the call so far and answers with what to say
next. Code checks each reply first. A reply that agrees to pay, settle or a payment plan is
replaced; a number that's neither in facts nor something they said puts the user through
instead, as does a request for a Social Security, card or bank number, a person who won't talk
to an assistant or wants the patient, and a model that doesn't answer in time. The person's
name, a reference number and anything they offer are noted.

While a call goes, clones/calls/<id>/live.json says where it is, for the page; after it, the
model reads the transcript for what came of each ask, and <id>/<started>.json keeps it all,
readable only by the user.
"""

import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as Late
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from proxenos import llm, twilio
from proxenos.clones import work

FOLDER = ("clones", "calls")
LIVE = "live.json"
ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
ON_HOLD = 30  # seconds Twilio listens on hold for speech before asking what to do again
TALKING = 8  # seconds it waits for the person to speak after the assistant has
RING = 25  # seconds the user's phone rings
THINK = 8  # seconds a turn waits on the model before "one moment"; Twilio gives up at 15
REPEAT = 0.6  # this alike, by words, to something heard before: the hold's message again
TURNS = 30  # turns the assistant talks before putting the user through
QUIET = 2  # turns without a word before it asks whether they're there
SILENT_HOLD = 6  # turns without a word before it takes it to be on hold again
CONTEXT = 6000  # characters of the call so far the model reads, its newest

# The hold's own messages and phone menus, in the words they always use.
_RECORDING = re.compile(
    r"your call is (very )?important|estimated (wait|hold)|wait time|in the order (it was|they "
    r"were|calls are) received|(stay|remain) on the line|continue to hold|please hold|next "
    r"available|all (of )?our (representatives|agents|associates|staff)|\bpress\b|say or enter|"
    r"\benter (your|the)\b|para espa|visit (us|our)|(may|will) be (recorded|monitored)|for "
    r"quality|business hours|(is|are) (now )?closed|thank you for calling|listen carefully|"
    r"options have changed",
    re.IGNORECASE,
)
# How a person picking up talks.
_PERSON = re.compile(
    r"\b(this is|my name is|you'?re speaking (with|to)|speaking|how (can|may|might) i (help|"
    r"assist)|what can i (do|help)|thanks? (you )?for (holding|waiting|your patience)|who am i "
    r"speaking|who'?s calling|can i (get|have) (your|the)|hello|hi|good (morning|afternoon|"
    r"evening))\b",
    re.IGNORECASE,
)
# What the user has to answer themself: someone who won't go on with an assistant, wants the
# patient, or asks for a number the assistant never has.
_HAND_OVER = re.compile(
    r"(don'?t|do not|doesn'?t|does not) consent|not (comfortable|okay|ok|allowed)|(can'?t|cannot|"
    r"won'?t|unable to) (speak|talk|discuss|proceed|go on)|(speak|talk) (to|with) the (patient|"
    r"account holder|guarantor)|(is|are) the (patient|account holder) (available|there|on the "
    r"line)|\bsocial\b|\bssn\b|card number|credit card|debit card|bank account|routing number",
    re.IGNORECASE,
)
_PAY = r"pay|payment|settle|settlement|installment|autopay|charge (it|the|my|a|your) card"
_NOT = re.compile(r"\b(can'?t|cannot|won'?t|not|unable|no)\b", re.IGNORECASE)
_YES = re.compile(
    rf"^\W*(yes|yeah|sure|ok(ay)?|deal|that works|sounds good)\b[^.?!]*\b({_PAY})", re.IGNORECASE
)

_SYSTEM = """\
You are an automated assistant on a phone call, calling for {name}. You are not {name}; if \
anyone asks, you say you're an automated assistant. Refer to {name} by name, never as he or she. \
Speak plainly and politely, one or two short sentences at a time, as people talk on the phone.

You may tell them these facts and nothing else about {name}: {facts}. You never agree to pay, to \
settle, to a payment plan or to anything else on {name}'s behalf, and you never give a card, \
bank or Social Security number: if they offer something, ask them to note it on the account and \
say you'll pass it on. Ask for what's listed, one thing at a time, and list an ask as done once \
they've answered it, yes or no. Note the name they give and any reference or confirmation number.

Set connect when they need something you don't have, want {name} on the line, or won't go on \
with an assistant. Set hold when they put you on hold or transfer you. When everything is asked \
or they've said all they can, ask for a reference number if you haven't one, thank them, and set \
end."""
_TURN = {
    "type": "object",
    "properties": {
        "say": {"type": "string"},
        "done": {"type": "array", "items": {"type": "integer"}},
        "connect": {"type": "boolean"},
        "hold": {"type": "boolean"},
        "end": {"type": "boolean"},
        "rep_name": {"type": "string"},
        "reference": {"type": "string"},
        "offered": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["say", "done", "connect", "hold", "end", "rep_name", "reference", "offered"],
    "additionalProperties": False,
}
_LIVE_SYSTEM = "You tell a person on the phone from a recording."
_LIVE = {
    "type": "object",
    "properties": {"live": {"type": "boolean"}},
    "required": ["live"],
    "additionalProperties": False,
}
_OUTCOME_SYSTEM = (
    "You read the transcript of a phone call an automated assistant made for someone, and say "
    "plainly, for them, what came of it."
)
_OUTCOME = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "asks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ask": {"type": "string"}, "result": {"type": "string"}},
                "required": ["ask", "result"],
                "additionalProperties": False,
            },
        },
        "rep_name": {"type": "string"},
        "reference": {"type": "string"},
        "offered": {"type": "array", "items": {"type": "string"}},
        "next": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "asks", "rep_name", "reference", "offered", "next"],
    "additionalProperties": False,
}

# (prompt, system, schema, keep=facts) → the model's answer
Think = Callable[..., dict]


@dataclass(frozen=True)
class Sheet:
    id: str
    title: str
    to: str
    number: str
    about: str
    asks: tuple[str, ...] = ()
    facts: Mapping[str, str] = field(default_factory=dict)
    digits: str = ""
    talk: bool = False
    notes: str = ""


def folder(vault: Path) -> Path:
    return vault.joinpath(*FOLDER)


def read_sheet(path: Path) -> Sheet:
    """A call sheet, or ValueError saying what's wrong with it."""
    text = path.read_text(encoding="utf-8").removeprefix("﻿")
    fields, front = work._front(text), work._FRONT.match(text)
    if fields is None or front is None:
        raise ValueError("it has no front matter")
    sheet_id = path.stem  # the page and the command know a sheet by its file
    if not ID.fullmatch(sheet_id):
        raise ValueError(f"id {sheet_id!r} isn't letters, digits, - and _")
    number = fields.get("number", "").replace(" ", "").replace("-", "")
    if not twilio.NUMBER.fullmatch(number):
        raise ValueError("number must be the whole number with its country code, like +16035550100")
    digits = fields.get("digits", "")
    if not twilio.DIGITS.fullmatch(digits):
        raise ValueError("digits may only be 0-9, *, # and w (a half-second wait)")
    asks, facts = _json(fields.get("asks"), list), _json(fields.get("facts"), dict)
    if asks is None or not all(isinstance(a, str) and a.strip() for a in asks):
        raise ValueError('asks must be a list of what to ask for, like ["An itemized bill"]')
    if facts is None or not all(isinstance(v, str) for v in facts.values()):
        raise ValueError('facts must be what it may tell them, like {"name": "Sam Lee"}')
    about = fields.get("about", "").strip()
    if not about:
        raise ValueError("about must say what the call is about")
    return Sheet(
        id=sheet_id,
        title=fields.get("title", "").strip() or sheet_id,
        to=fields.get("to", "").strip() or number,
        number=number,
        about=about,
        asks=tuple(a.strip() for a in asks),
        facts={str(k): v.strip() for k, v in facts.items()},
        digits=digits,
        talk=fields.get("talk", "").strip().lower() in ("true", "yes"),
        notes=text[front.end() :].strip(),
    )


def load(vault: Path, sheet_id: str) -> Sheet:
    path = folder(vault) / f"{sheet_id}.md"
    if not ID.fullmatch(sheet_id) or not path.is_file():
        raise SystemExit(f"no call sheet {sheet_id}: write one at {path}")
    try:
        return read_sheet(path)
    except (OSError, ValueError) as e:
        raise SystemExit(f"call sheet {sheet_id} can't be used: {e}") from None


def sheets(vault: Path) -> list[tuple[str, Sheet | str]]:
    """Every call sheet by id: the sheet, or what's wrong with it."""
    found: list[tuple[str, Sheet | str]] = []
    for path in sorted(folder(vault).glob("*.md")):
        try:
            found.append((path.stem, read_sheet(path)))
        except (OSError, ValueError) as e:
            found.append((path.stem, str(e)))
    return found


# ── Whether the number is the organization's own ────────────────────────────

NUMBER_FILE = "number.json"  # in <id>/: what the last check of the sheet's number found
# The user's own records, beside what they sent: what they wrote down or put in a calendar.
_OWN_SOURCES = frozenset({"notes", "keep", "calendar", "gcalendar", "maccalendar", "gtasks"})
_PHONE = re.compile(r"\+?\(?\d[\d ().-]{5,}\d")  # a phone number, with what's inside one
_SAME = 9  # the last digits two numbers share to be one: an area code and the rest


def doubt(vault: Path, sheet: Sheet) -> str | None:
    """Why the sheet's number may not be the one to call, or None. A number that turns up in just
    one message someone sent the user, and in nothing of theirs (what they sent, their notes and
    calendar) nor in any other mail or chat, came from that message alone: a phishing email
    gives one so, with an urgent bill to pay. A number found nowhere was put on the sheet from
    elsewhere, as from a bill or a website, and isn't doubted here."""
    theirs, mine = _mentions(vault, sheet.number)
    if len(theirs) != 1 or mine:
        return None
    return (
        f"{sheet.number} is in just one message sent to you, and in nothing you've sent or kept: "
        "it may not be theirs, as a scam's email gives a number. Check it on their own website "
        "or a bill before you call."
    )


def check(vault: Path, sheet: Sheet) -> str | None:
    """`doubt`, kept in <id>/number.json with the number it's about, for the page to show on the
    sheet until the number changes."""
    found = doubt(vault, sheet)
    _write(
        folder(vault) / sheet.id / NUMBER_FILE,
        {"number": sheet.number, "doubt": found, "checked": _iso(_now())},
    )
    return found


def _mentions(vault: Path, number: str) -> tuple[set[str], set[str]]:
    """The records under raw/ that have `number` in them: (those from others, the user's own).
    Only lines with its last four digits are read whole, so a big vault reads fast. An email's
    new text stands for it, so a quote of what it answers doesn't count as the user's."""
    digits = re.sub(r"\D", "", number)
    theirs: set[str] = set()
    mine: set[str] = set()
    for path in sorted((vault / "raw").glob("*/**/*.jsonl")):
        source = path.relative_to(vault / "raw").parts[0]
        with path.open(encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f):
                if digits[-4:] not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or not _has(record, digits):
                    continue
                key = f"{source}/{record.get('id') or f'{path.name}:{n}'}"
                own = record.get("from_me") is True or source in _OWN_SOURCES
                (mine if own else theirs).add(key)
    return theirs, mine


def _has(record: dict, digits: str) -> bool:
    """Whether a record's text, or a chat's id (WhatsApp keys one by its number), has the number:
    the same last _SAME digits, however it's written."""
    if record.get("body_new"):
        record = {k: v for k, v in record.items() if k != "body"}
    texts = [v for v in record.values() if isinstance(v, str)]
    texts += [x for v in record.values() if isinstance(v, list) for x in v if isinstance(x, str)]
    same = min(_SAME, len(digits))
    for text in texts:
        for found in _PHONE.findall(text):
            seen = re.sub(r"\D", "", found)
            if len(seen) >= same and seen[-same:] == digits[-same:]:
                return True
    return False


def _json(value: str | None, kind: type) -> list | dict | None:
    if not value:
        return kind()
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, kind) else None


# ── Telling a person from the hold ──────────────────────────────────────────


def classify(text: str, earlier: Iterable[str] = ()) -> str:
    """What a stretch of speech heard on hold is: "empty", "recording" (the hold's own messages,
    one heard before, or a word or two of noise), "person" (someone picking up) or "unsure"."""
    words = _words(text)
    if not words:
        return "empty"
    if _RECORDING.search(text) or any(_alike(words, _words(e)) for e in earlier):
        return "recording"
    if _PERSON.search(text):
        return "person"
    return "recording" if len(words) <= 2 else "unsure"


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _alike(a: set[str], b: set[str]) -> bool:
    return len(a) >= 3 and len(b) >= 3 and len(a & b) / len(a | b) >= REPEAT


# ── What the assistant may say ──────────────────────────────────────────────


def guard(text: str, name: str, allowed: Iterable[str]) -> tuple[str, str]:
    """`text`, if the assistant may say it, and why not if it may not: "commits" when it agrees
    to pay or settle for the user, "number" when it has a number found in none of `allowed`
    (the facts, the sheet, what the person said)."""
    if commits(text, name):
        return "", "commits"
    known = [re.sub(r"\D", "", a) for a in allowed]
    for number in _numbers(text):
        if len(number) >= 3 and not any(number in k for k in known):
            return "", "number"
    return text, ""


def commits(text: str, name: str) -> bool:
    """Whether `text` agrees to pay, settle or a payment plan on the user's behalf."""
    who = "|".join(["i", "we", "he", "she", "they", "the patient", *map(re.escape, name.split())])
    agrees = re.compile(
        rf"\b({who})\b[^.?!]*?(\bwill\b|'ll\b|\bcan\b|\bagrees?\b|\baccepts?\b|\bauthori[sz]es?\b|"
        rf"\bconfirms?\b|\bwants? to\b|\bwould like to\b)[^.?!]*\b({_PAY})",
        re.IGNORECASE,
    )
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        if not _NOT.search(sentence) and (agrees.search(sentence) or _YES.search(sentence)):
            return True
    return False


def _numbers(text: str) -> list[str]:
    return [re.sub(r"\D", "", n) for n in re.findall(r"\d[\d /.,-]*\d|\d", text)]


# ── The call ────────────────────────────────────────────────────────────────


def _think(prompt: str, system: str, schema: dict, keep: Iterable[str] = ()) -> dict:
    """The model's answer. The sheet's facts are kept from llm's blanking (proxenos.redact): an
    account number among them is there to be said, and guard checks every number said."""
    answer = llm.ask(prompt, system=system, schema=schema, effort="low", max_tokens=600, keep=keep)
    if not isinstance(answer, dict):
        raise llm.ModelError("the model didn't answer with JSON")
    return answer


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class Call:
    """One call as it goes. Each method answers one of Twilio's requests with the TwiML for what
    to do next, and keeps the transcript. Not for two threads at once: the server asks in turn."""

    def __init__(
        self,
        sheet: Sheet,
        *,
        name: str,
        phone: str,
        ring_from: str,
        base: str,
        think: Think = _think,
        budget: float = THINK,
        now: Callable[[], datetime] = _now,
    ):
        self.sheet, self.name, self.phone, self.ring_from = sheet, name, phone, ring_from
        self.base, self.think, self.budget, self.now = base, think, budget, now
        self.system = _SYSTEM.format(
            name=name, facts="; ".join(f"{k}: {v}" for k, v in sheet.facts.items()) or "none"
        )
        self.mode = "talk" if sheet.talk else "ring"
        self.phase = "dialing"
        self.status = ""
        self.sid = ""
        self.started = now()
        self.transcript: list[dict] = []
        self.recordings: list[str] = []
        self.done: set[int] = set()
        self.notes: dict = {"rep_name": "", "reference": "", "offered": []}
        self.introduced = self.handed = self.joined = False
        self.turns = self.quiet = 0
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._pending: Future | None = None
        self._waited = False

    # Twilio's requests, in about the order they come.

    def answer(self) -> str:
        """The number picked up: press the menu's keys, then listen."""
        self.phase = "menu" if self.sheet.digits else "waiting"
        self._log("note", "The call was answered.")
        return twilio.response(twilio.play_digits(self.sheet.digits), self._on_hold())

    def heard(self, speech: str) -> str:
        text = " ".join(speech.split())
        if self.phase in ("dialing", "menu", "waiting"):
            self.phase = "waiting"
            kind = classify(text, self.recordings)
            if kind == "unsure":
                kind = "person" if self._live(text) else "recording"
            if kind == "empty":
                return twilio.response(self._on_hold())
            if kind == "recording":
                self.recordings.append(text)
                self._log("line", text)
                return twilio.response(self._on_hold())
            self._log("them", text)
            return self._picked_up()
        if self.phase != "talking":
            return twilio.response()
        if not text:
            self.quiet += 1
            if self.quiet >= SILENT_HOLD:
                self.phase = "waiting"
                return twilio.response(self._on_hold())
            ask = "Hello, are you still there?" if self.quiet == QUIET else ""
            return twilio.response(self._hear(ask))
        self.quiet = 0
        self._log("them", text)
        if _HAND_OVER.search(text):
            return self._connect(f"Of course. One moment while I connect {self.name}.")
        return self._turn()

    def pending(self) -> str:
        """Back for the answer the model was still writing."""
        if self._pending is None:
            return twilio.response(self._hear())
        return self._await()

    def whisper(self) -> str:
        """What the user hears on picking up, before they're put through."""
        prompt = (
            f"{self.sheet.to} is on the line about {self.sheet.about}. Press 1 to talk to them."
        )
        return twilio.response(
            twilio.keypress(self._url("accept"), twilio.say(prompt), timeout=10), twilio.hangup()
        )

    def accept(self, digits: str) -> str:
        if digits != "1":
            return twilio.response(twilio.hangup())
        self.joined, self.phase = True, "connected"
        self._log("note", "You were put through.")
        return twilio.response()

    def dialed(self, status: str) -> str:
        """The user's phone was rung: they've talked and hung up, or never came."""
        if self.joined:
            self.phase = "done"
            return twilio.response(twilio.hangup())
        self._log("note", f"You didn't come to the phone ({status or 'no answer'}).")
        if self.sheet.asks and not self.handed and self.turns < TURNS:
            self.mode, self.phase = "talk", "talking"
            text = (
                f"Sorry, {self.name} can't come to the phone right now, but I can ask a few "
                f"things on {self.name}'s behalf."
            )
            self._log("assistant", text)
            return twilio.response(self._hear(text))
        text = (
            f"I'm sorry, {self.name} can't come to the phone right now and will call back. "
            "Thank you for your help."
        )
        self._log("assistant", text)
        self.phase = "done"
        return twilio.response(twilio.say(text), twilio.hangup())

    def ended(self, status: str) -> None:
        self.status, self.phase = status, "done"
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._log("note", f"The call ended ({status or 'hung up'}).")

    # What the assistant does.

    def _picked_up(self) -> str:
        if self.introduced:  # back from hold
            if self.mode == "talk" and not self.handed:
                self.phase = "talking"
                return self._turn()
            return self._ring(f"Thanks. One moment while I connect {self.name}.")
        self.introduced = True
        hello = (
            f"Hi, I'm an automated assistant calling for {self.name}, and this call is transcribed."
        )
        if self.mode == "ring":
            return self._ring(f"{hello} One moment while I connect {self.name}.")
        self.phase = "talking"
        text = f"{hello} I'm calling about {self.sheet.about}."
        self._log("assistant", text)
        return twilio.response(self._hear(text))

    def _turn(self) -> str:
        facts = list(self.sheet.facts.values())
        self._pending = self._pool.submit(
            self.think, self._prompt(), self.system, _TURN, keep=facts
        )
        self._waited = False
        return self._await()

    def _await(self) -> str:
        assert self._pending is not None
        try:
            answer = self._pending.result(timeout=self.budget)
        except Late:
            if self._waited:
                self._pending = None
                return self._connect(f"Sorry, one moment while I connect {self.name}.")
            self._waited = True
            return twilio.response(
                twilio.say("One moment, please."), twilio.redirect(self._url("pending"))
            )
        except Exception:  # noqa: BLE001 - whatever the model's trouble, the user takes over
            self._pending = None
            return self._connect(f"Sorry, one moment while I connect {self.name}.")
        self._pending = None
        return self._act(answer)

    def _act(self, answer: dict) -> str:
        self.turns += 1
        self._note(answer)
        text, problem = guard(str(answer.get("say") or "").strip(), self.name, self._allowed())
        if problem == "commits":
            text = f"I can't agree to any payment for {self.name}, but I'll pass that on."
        elif problem == "number":
            return self._connect(f"I don't have that, so one moment while I connect {self.name}.")
        if answer.get("connect") or self.turns >= TURNS:
            return self._connect(text or f"One moment while I connect {self.name}.")
        if answer.get("end") and problem != "commits":
            self._log("assistant", text)
            self.phase = "done"
            return twilio.response(twilio.say(text), twilio.hangup())
        if answer.get("hold") and problem != "commits":
            self._log("assistant", text)
            self.phase = "waiting"
            return twilio.response(twilio.say(text), self._on_hold())
        self._log("assistant", text)
        return twilio.response(self._hear(text))

    def _connect(self, text: str) -> str:
        self.handed = True
        return self._ring(text)

    def _ring(self, text: str) -> str:
        self.phase = "connecting"
        self._log("assistant", text)
        return twilio.response(
            twilio.say(text),
            twilio.dial(
                self.phone, self.ring_from, self._url("dialed"), self._url("whisper"), timeout=RING
            ),
        )

    def _live(self, text: str) -> bool:
        """The model's call on speech that's neither clearly the hold nor clearly a person; the
        hold, if it can't say in time."""
        prompt = (
            f'On hold, this was just heard on the line: "{text}"\n\nIs it a live person who has '
            "just picked up and is talking to the caller? Not a recording, hold music, song lyrics "
            "or an automated menu."
        )
        try:
            answer = self._pool.submit(self.think, prompt, _LIVE_SYSTEM, _LIVE)
            return answer.result(timeout=self.budget).get("live") is True
        except Exception:  # noqa: BLE001 - not sure is the hold
            return False

    def _on_hold(self) -> str:
        return twilio.listen(self._url("heard"), timeout=ON_HOLD)

    def _hear(self, text: str = "") -> str:
        return twilio.listen(self._url("heard"), twilio.say(text), timeout=TALKING, barge_in=True)

    def _note(self, answer: dict) -> None:
        for key in ("rep_name", "reference"):
            if value := str(answer.get(key) or "").strip():
                self.notes[key] = value[:200]
        for offer in answer.get("offered") or []:
            if (offer := str(offer).strip()) and offer not in self.notes["offered"]:
                self.notes["offered"].append(offer[:300])
        for n in answer.get("done") or []:
            if isinstance(n, int) and 1 <= n <= len(self.sheet.asks):
                self.done.add(n)

    def _allowed(self) -> list[str]:
        heard = (t["text"] for t in self.transcript if t["who"] == "them")
        return [*self.sheet.facts.values(), self.sheet.about, *self.sheet.asks, *heard]

    def _prompt(self) -> str:
        asks = "\n".join(
            f"{i}. {a}" + (" (done)" if i in self.done else "")
            for i, a in enumerate(self.sheet.asks, 1)
        )
        return (
            f"Calling: {self.sheet.to}\nAbout: {self.sheet.about}\n\n"
            f"What to ask for, in order:\n{asks or '(nothing listed)'}\n\n"
            f"The call so far:\n{self._said()}\n\nWhat do you say next?"
        )

    def _said(self) -> str:
        who = {"them": "Them", "assistant": "You"}
        lines = [f"{who[t['who']]}: {t['text']}" for t in self.transcript if t["who"] in who]
        return "\n".join(lines)[-CONTEXT:]

    def _log(self, who: str, text: str) -> None:
        if text:
            self.transcript.append({"at": _iso(self.now()), "who": who, "text": text})

    def _url(self, step: str) -> str:
        return f"{self.base}/{step}"

    def warm(self) -> None:
        """Have the model answer once, so a local one is loaded before anyone picks up."""
        with suppress(Exception):  # a turn that finds it cold just waits longer
            self.think('Heard on the line: "hello"', _LIVE_SYSTEM, _LIVE)

    # After the call.

    def outcome(self) -> dict | None:
        """What came of each ask, as the model reads the transcript; None when no one answered or
        the model couldn't say."""
        if not any(t["who"] == "them" for t in self.transcript):
            return None
        asks = "\n".join(f"{i}. {a}" for i, a in enumerate(self.sheet.asks, 1))
        prompt = (
            f"Calling: {self.sheet.to}\nAbout: {self.sheet.about}\n"
            f"What it was to ask for:\n{asks or '(nothing listed)'}\n\n"
            f"Transcript:\n{self._said()}\n\n"
            "For each ask, what they said, or that it wasn't asked. Then the name of the person "
            f"who answered, any reference number, anything they offered, and what {self.name} "
            "should do next."
        )
        try:
            return self.think(prompt, _OUTCOME_SYSTEM, _OUTCOME)
        except Exception:  # noqa: BLE001 - the transcript is kept either way
            return None

    def state(self) -> dict:
        return {
            "id": self.sheet.id,
            "title": self.sheet.title,
            "to": self.sheet.to,
            "mode": self.mode,
            "phase": self.phase,
            "status": self.status,
            "started": _iso(self.started),
            "updated": _iso(self.now()),
            "asks": list(self.sheet.asks),
            "done": sorted(self.done),
            "notes": self.notes,
            "transcript": self.transcript,
        }


# ── Files ───────────────────────────────────────────────────────────────────


def live_path(vault: Path, sheet_id: str) -> Path:
    return folder(vault) / sheet_id / LIVE


def read_live(vault: Path, sheet_id: str) -> dict:
    """Where the call from this sheet is, as its process last wrote it; {} when none is going."""
    try:
        live = json.loads(live_path(vault, sheet_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return live if isinstance(live, dict) else {}


def write_live(vault: Path, call: Call) -> None:
    _write(live_path(vault, call.sheet.id), call.state() | {"pid": os.getpid(), "sid": call.sid})


def finish(vault: Path, call: Call) -> Path:
    """Keep the call: its transcript, notes and outcome, in <id>/<started>.json; and it's no
    longer live."""
    record = call.state() | {"sid": call.sid, "ended": _iso(call.now()), "outcome": call.outcome()}
    path = folder(vault) / call.sheet.id / f"{call.started:%Y%m%dT%H%M%SZ}.json"
    _write(path, record)
    live_path(vault, call.sheet.id).unlink(missing_ok=True)
    return path


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")  # one a writer
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.chmod(0o600)  # the mode above only applies when the file is new
    os.replace(tmp, path)
