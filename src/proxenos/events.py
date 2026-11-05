"""Booked events from the mail, for the calendar, without a model.

The tasks clone reads the last day or two of messages and needs a model, so a ticket order that
arrives two days before the show can slip past it. This reads the raw mail of the last DAYS
for confirmations (an order, tickets, a reservation, a booking, a registration, an itinerary, an
RSVP) and takes the events in them in plain code: a schema.org event or reservation, an inline
VEVENT, or a line that is a full date and time ("Thursday, November 5, 2026 7:00 PM"). Lines that
say when the order or email was made ("Order Date:", "Sent:") are not the event, and neither is a
time already past. Each comes back in the shape `plans.write` takes, so it is put beside the
tasks, kept off the calendar when the user's own already has it, and pushed the same way. The
sync runs it with no model and no network.
"""

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DAYS = 30  # of mail looked at
_CONFIRMING = re.compile(
    r"\b(orders?|tickets?|reservations?|bookings?|booked|registrations?|registered"
    r"|your info for|confirmation|itinerary|see you on|rsvp)\b",
    re.IGNORECASE,
)
_HEAD_LINES = 5  # of the body, besides the subject, where the confirming words may be
# A line about when the order or email was made, not about the event.
_MADE = re.compile(
    r"^\W*(order(ed)?\s*(date|placed|time)?|purchased?(\s+(on|date))?|purchase date|sent|date"
    r"|placed(\s+on)?|booked on|booking date|received|created|updated)\s*[:\-]",
    re.IGNORECASE,
)
_NAMES = "jan feb mar apr may jun jul aug sep oct nov dec"
_MONTHS = {m: i for i, m in enumerate(_NAMES.split(), 1)}
_WEEKDAYS = {d: i for i, d in enumerate("mon tue wed thu fri sat sun".split())}  # noqa: SIM905
_MONTH = r"(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_WEEKDAY = r"(?:(?P<wd>mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
_TIME = r"(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)?(?![\w:])"  # :mm or am/pm
_SEP = r"(?:\s*(?:,|·|•|\||@|-|–|—|at)\s*|\s+)"
_LINES = [
    # Thursday, November 5, 2026 7:00 PM / Thu, Nov 5 at 7pm / November 5 · 7:00 PM
    re.compile(
        rf"{_WEEKDAY}{_MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{{4}}))?"
        rf"{_SEP}{_TIME}",
        re.IGNORECASE,
    ),
    # Thursday 5 November 2026, 19:00
    re.compile(
        rf"{_WEEKDAY}(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+(?P<y>\d{{4}}))?"
        rf"{_SEP}{_TIME}",
        re.IGNORECASE,
    ),
    # 11/05/2026 19:00 (month first)
    re.compile(rf"(?P<mon>\d{{1,2}})/(?P<d>\d{{1,2}})/(?P<y>\d{{4}}){_SEP}{_TIME}"),
    # 2026-11-05 19:00
    re.compile(rf"(?P<y>\d{{4}})-(?P<mon>\d{{2}})-(?P<d>\d{{2}})[T ]{_TIME}"),
]
_DATEISH = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d"
    r"|\d\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|\d{1,2}/\d{1,2}/\d{4}",
    re.IGNORECASE,
)
_VEVENT = re.compile(r"BEGIN:VEVENT(.*?)END:VEVENT", re.DOTALL | re.IGNORECASE)
_ICS_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?$", re.IGNORECASE)
_KINDS = {
    "Event",
    "EventReservation",
    "FoodEstablishmentReservation",
    "LodgingReservation",
    "FlightReservation",
}
_START = ("startDate", "checkinTime", "checkinDate", "departureTime")
# A line that isn't an event's name: a label, a price, a link, order boilerplate.
_NOT_A_NAME = re.compile(
    r"https?://|@|\$|€|£|^[\W_]*(thank|your|order|total|subtotal|qty|quantity|price|seat|view"
    r"|download|print|manage|confirmation|receipt|tickets?|booking|date|time|when|where|venue)\b"
    r"|\b(order|confirmation|receipt|total|subtotal)\b.*[#:]|^[^:]{1,25}:\s",
    re.IGNORECASE,
)
_BOILER = re.compile(
    r"^\W*(thank you for (your|the) (order|purchase|booking|reservation|registration)"
    r"( (from|at|with)\b[^:–—-]*)?|your .{0,40}(confirmation|order|booking|reservation|tickets?))"
    r"\W*",
    re.IGNORECASE,
)


def find(vault: Path, now: datetime | None = None) -> list[dict]:
    """The future events in the last DAYS of confirmation mail, as plan dicts (id, title,
    detail, source, with, status, at, place, event, asked_at), earliest first."""
    now = now or datetime.now(UTC)
    local = now.astimezone().replace(tzinfo=None)
    since = (now - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    months = {f"{now - timedelta(days=d):%Y-%m}.jsonl" for d in range(DAYS + 1)}
    found: dict[str, dict] = {}
    for path in sorted((vault / "raw" / "email").glob("*/*.jsonl")):
        if path.name not in months:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or str(record.get("ts") or "") < since:
                continue
            if record.get("from_me") or not _confirming(record):
                continue
            for plan in _events(record, local):
                found.setdefault(plan["id"], plan)
    return sorted(found.values(), key=lambda p: (p["at"], p["id"]))


def _confirming(record: dict) -> bool:
    """Whether the subject or the first lines of the body have a confirming word."""
    head = [str(record.get("subject") or ""), *_lines(_body(record))[:_HEAD_LINES]]
    return any(_CONFIRMING.search(h) for h in head)


def _body(record: dict) -> str:
    return str(record.get("body") or record.get("body_new") or "")


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _events(record: dict, now: datetime) -> list[dict]:
    """One message's future events: from its schema.org data, its VEVENTs, its date lines, the
    first of them for a time kept."""
    body, subject = _body(record), _subject_name(record)
    out, seen = [], set()
    for when, name in [*_jsonld(body), *_vevents(body), *_date_lines(body, _sent(record), subject)]:
        if when <= now or when in seen:
            continue
        seen.add(when)
        out.append(_plan(record, when, name or subject))
    return out


def _plan(record: dict, when: datetime, name: str) -> dict:
    sender = " ".join(str(record.get("from_name") or "").split())
    title = f"{name} ({sender})" if sender else name
    key = hashlib.sha1(f"{record.get('id')}|{when:%Y-%m-%dT%H:%M}".encode()).hexdigest()[:12]
    subject = " ".join(str(record.get("subject") or "").split())
    return {
        "id": f"evt-{key}",
        "title": title[:120],
        "detail": f"Email: {subject}"[:200] if subject else "",
        "source": "email",
        "with": None,
        "status": "open",
        "at": f"{when:%Y-%m-%dT%H:%M}",
        "place": None,
        "event": True,
        "asked_at": record.get("ts"),
    }


def _sent(record: dict) -> date:
    try:
        return datetime.fromisoformat(str(record["ts"])).astimezone().date()
    except (KeyError, ValueError):
        return datetime.now().date()


def _subject_name(record: dict) -> str:
    """The subject without the order boilerplate ("Thank you for your order from the Hop")."""
    subject = " ".join(str(record.get("subject") or "").split())
    subject = re.sub(r"^(re|fwd?):\s*", "", subject, flags=re.IGNORECASE)
    rest = _BOILER.sub("", subject).strip(" -–—:|")
    return rest or str(record.get("from_name") or "").strip() or "Booked event"


def _date_lines(body: str, sent: date, fallback: str) -> list[tuple[datetime, str]]:
    lines = _lines(body)
    found = []
    for i, line in enumerate(lines):
        when = None if _MADE.match(line) else _parse(line, sent)
        if when is not None:
            found.append((when, _nearest(lines, i) or fallback))
    return found


def _nearest(lines: list[str], i: int) -> str:
    """The line just before or after line `i` that reads as an event's name, else ''."""
    for j in (i - 1, i + 1):
        if 0 <= j < len(lines):
            line = lines[j].strip(" -–—*#|")
            if 3 <= len(line) <= 100 and not _NOT_A_NAME.search(line) and not _DATEISH.search(line):
                return line
    return ""


def _parse(line: str, sent: date) -> datetime | None:
    """The first full date and time in a line, local and naive. A date without a year is in the
    sent year or the next: the one that fits its weekday, else the first not before the email."""
    for pattern in _LINES:
        match = pattern.search(line)
        if not match:
            continue
        g = match.groupdict()
        mon = g["mon"]
        month = int(mon) if mon.isdigit() else _MONTHS[mon[:3].lower()]
        hour, minute = int(g["h"]), int(g["m"] or 0)
        ap = (g["ap"] or "").lower().replace(".", "")
        if not g["m"] and not ap:
            continue
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        try:
            day = _day(g["y"], month, int(g["d"]), (g.get("wd") or "").lower(), sent)
            return datetime(day.year, day.month, day.day, hour, minute) if day else None
        except ValueError:
            return None
    return None


def _day(year: str | None, month: int, d: int, weekday: str, sent: date) -> date | None:
    if year:
        return date(int(year), month, d)
    for y in (sent.year, sent.year + 1):
        try:
            day = date(y, month, d)
        except ValueError:
            continue
        if weekday in _WEEKDAYS and day.weekday() == _WEEKDAYS[weekday]:
            return day
        if weekday not in _WEEKDAYS and day >= sent - timedelta(days=1):
            return day
    return None


def _vevents(body: str) -> list[tuple[datetime, str]]:
    """DTSTART and SUMMARY of each VEVENT in the text, in local time."""
    out = []
    for block in _VEVENT.findall(body):
        text = re.sub(r"\r?\n[ \t]", "", block)  # unfold
        start = summary = ""
        for line in text.splitlines():
            key, _, value = line.partition(":")
            key = key.split(";")[0].strip().upper()
            if key == "DTSTART":
                start = value.strip()
            elif key == "SUMMARY":
                summary = re.sub(r"\\([,;nN\\])", lambda m: " " if m[1] in "nN" else m[1], value)
        when = _ics(start)
        if when:
            out.append((when, " ".join(summary.split())))
    return out


def _ics(text: str) -> datetime | None:
    """An iCalendar date-time as local naive (a UTC one converted); None for an all-day date,
    which has no time to put on a calendar here."""
    match = _ICS_TIME.match(text)
    if not match or match[4] is None:
        return None
    y, mo, d, h, mi, s, z = match.groups()
    try:
        when = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    return when.replace(tzinfo=UTC).astimezone().replace(tzinfo=None) if z else when


def _jsonld(body: str) -> list[tuple[datetime, str]]:
    """startDate and name of each schema.org event or reservation in the text's JSON objects."""
    out: list[tuple[datetime, str]] = []
    decoder, pos = json.JSONDecoder(), 0
    while (pos := body.find("{", pos)) != -1:
        try:
            value, end = decoder.raw_decode(body, pos)
        except ValueError:
            pos += 1
            continue
        pos = end
        _walk(value, out)
    return out


def _walk(node: object, out: list[tuple[datetime, str]]) -> None:
    if isinstance(node, list):
        for item in node:
            _walk(item, out)
    elif isinstance(node, dict):
        kind = node.get("@type")
        if _KINDS & set(map(str, kind if isinstance(kind, list) else [kind])):
            thing = node.get("reservationFor")
            thing = thing if isinstance(thing, dict) else {}
            start = next((v for k in _START if (v := node.get(k) or thing.get(k))), "")
            when = _iso(start)
            if when:
                name = str(node.get("name") or thing.get("name") or "")
                out.append((when, " ".join(name.split())))
        for key, child in node.items():
            if isinstance(child, dict | list) and key != "reservationFor":
                _walk(child, out)


def _iso(text: object) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return when.astimezone().replace(tzinfo=None) if when.tzinfo else when
