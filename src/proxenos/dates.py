"""Weekdays and dates, so a draft never offers "Thursday, November 6" in a year it's a Friday.

A model writing a message knows today's date from its prompt and the rest of the calendar from
memory, which it gets wrong by a day or a year: "Thursday, November 6th" and "Friday, November 7th"
were offered in 2026, when they fall on Friday and Saturday. Two things here, both in code:

- `today` gives a prompt today's date with a table of the next DAYS days and their weekdays, so
  the model reads a weekday off the table and doesn't work it out;
- `check` finds each weekday written with a date in a draft ("Thursday, November 6", "Thu 6 Nov",
  "Nov 6 (Thu)") and checks the pair against the calendar. The year is the one written, else the
  next occurrence of the date (or the last, if that was within RECENT days and fits: a draft
  that mentions "Monday, March 2" the week after it fell is right). A pair that doesn't fit has two
  readings, the weekday's date nearest the written one, and the written date's own weekday. When
  the first is already past there is only one possible, so the weekday is corrected; otherwise
  the draft is left as it is and the question, naming both, goes to the user.

`scheduled` is the same kind of check for a status: "completed" or "done" beside a date still to
come is rewritten as scheduled for that date, since nothing can be done on a day that hasn't come.
"""

import re
from datetime import date, datetime, timedelta

DAYS = 14  # of the calendar a prompt gets
RECENT = 60  # days back a date with no year may have fallen, and still be taken as that one

_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {
    name: n
    for n, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_WEEKDAY = (
    r"\b(?P<wd>monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thur|thu|friday|fri|"
    r"saturday|sat|sunday|sun)\b\.?"
)
_MONTH = (
    r"\b(?P<mon>january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|"
    r"september|sept|sep|october|oct|november|nov|december|dec)\b\.?"
)
_DAY = r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\b(?!\s*[:.]\d)"  # not an hour or a decimal
_YEAR = r"(?:,?\s+(?P<year>\d{4})\b)?"
_MONTH_DAY = rf"{_MONTH}\s+{_DAY}"
_DAY_MONTH = rf"(?:the\s+)?{_DAY}\s+(?:of\s+)?{_MONTH}"
# "Thursday, November 6th", "Thu 6 Nov", and "Nov 6 (Thu)": the weekday before, or after in brackets.
_PAIRS = [
    re.compile(rf"{_WEEKDAY}\s*,?\s*(?:the\s+)?{part}{_YEAR}", re.IGNORECASE)
    for part in (_MONTH_DAY, _DAY_MONTH)
] + [
    re.compile(rf"{part}{_YEAR}\s*\(\s*{_WEEKDAY}\s*\)", re.IGNORECASE)
    for part in (_MONTH_DAY, _DAY_MONTH)
]
_DATES = [re.compile(rf"{part}{_YEAR}", re.IGNORECASE) for part in (_MONTH_DAY, _DAY_MONTH)]
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})\b")
_DONE = re.compile(r"\b(?:completed|done|finished)\b", re.IGNORECASE)
_BEFORE = re.compile(  # "to be done", "will be completed": said of the future, so left alone
    r"\b(?:to|be|will|get|shall|should|must|when|once|if|until|before|after)\s+(?:\w+\s+)?$",
    re.IGNORECASE,
)
_GAP = re.compile(r"[\s:(,\u2013\u2014-]*(?:(?:on|at)\s+)?")


def local(now: datetime) -> date:
    """The user's calendar day at `now`, as the drafting prompts name it."""
    return now.astimezone().date()


def today(now: datetime) -> str:
    """Today's date and weekday for a prompt, and the next DAYS days with theirs."""
    day = local(now)
    rows = [
        f"- {d:%A %Y-%m-%d}, {d.day} {d:%B}" + (", today" if d == day else "")
        for d in (day + timedelta(days=n) for n in range(DAYS))
    ]
    return (
        f"Today is {day:%A %Y-%m-%d}.\n"
        f"The next {DAYS} days and their weekdays; read a weekday off this, never work it out:\n"
        + "\n".join(rows)
    )


def check(text: str, now: datetime) -> tuple[str, list[str], list[str]]:
    """A draft's text with the weekdays it could only have got wrong corrected, the questions
    for the pairs it could have got wrong either way, and a line for each correction made."""
    day = local(now)
    found: list[tuple[int, int, re.Match]] = []
    for pattern in _PAIRS:
        found += [(m.start(), m.end(), m) for m in pattern.finditer(text)]
    taken = -1
    asks: list[str] = []
    logs: list[str] = []
    fixes: list[tuple[int, int, str]] = []
    for start, end, m in sorted(found, key=lambda f: (f[0], -f[1])):
        if start < taken:
            continue  # inside a pair already read
        taken = end
        said = _NAMES.index(_full(m["wd"]))
        month, number = _MONTHS[m["mon"].lower().rstrip(".")], int(m["day"])
        written = _date(month, number, int(m["year"]) if m["year"] else None, day, said)
        if written is None or written.weekday() == said:
            continue
        right = _NAMES[written.weekday()]
        nearest = written + timedelta(days=((said - written.weekday() + 3) % 7) - 3)
        shown = m[0].strip()
        if nearest < day:  # that weekday's date is gone by: only the weekday can be wrong
            name = _like(m["wd"], right)
            fixes.append((m.start("wd"), m.end("wd"), name))
            logs.append(
                f'corrected "{shown}": {_when(written)} is a {right.capitalize()}, and '
                f"{_when(nearest)}, the {_NAMES[said].capitalize()} nearest, has passed"
            )
        else:
            asks.append(
                f'You wrote "{shown}", but {_when(written)} is a {right.capitalize()}. Did you '
                f"mean {right.capitalize()}, {_when(written)} or {_NAMES[said].capitalize()}, "
                f"{_when(nearest)}?"
            )
    for start, end, name in sorted(fixes, reverse=True):
        text = text[:start] + name + text[end:]
    return text, list(dict.fromkeys(asks)), logs


def scheduled(text: str, now: datetime) -> tuple[str, list[str]]:
    """A status with "completed", "done" or "finished" beside a date after today ("completed (5
    Nov)", "done on 2026-12-01") rewritten as "scheduled for" that date, and a line for each. Only
    a date written with its month and day counts, in the year as written, else this one: a status
    that says "done 2 Nov" in November means the one just gone."""
    day = local(now)
    logs: list[str] = []
    out, at = [], 0
    for m in _DONE.finditer(text):
        if m.start() < at or _BEFORE.search(text[max(0, m.start() - 20) : m.start()]):
            continue
        gap = _GAP.match(text, m.end())
        found = _date_at(text, gap.end(), day)
        if found is None or found[1] <= day:
            continue
        end, when = found
        if "(" in gap[0] and text[end : end + 1] == ")":
            end += 1
        word = "Scheduled for" if m[0][0].isupper() else "scheduled for"
        out += [text[at : m.start()], word + " " + text[gap.end() : found[0]]]
        logs.append(f'"{m[0]}" beside {when:%Y-%m-%d}, which is after today: scheduled instead')
        at = end
    return "".join(out) + text[at:], logs


def _date_at(text: str, pos: int, day: date) -> tuple[int, date] | None:
    """The date written at `pos` as month and day ("5 Nov", "Nov 5th 2026") or ISO, as where it
    ends and what it is (a year it doesn't say is `day`'s), else None."""
    if iso := _ISO.match(text, pos):
        when = _make(int(iso[1]), int(iso[2]), int(iso[3]))
        return (iso.end(), when) if when else None
    for pattern in _DATES:
        if m := pattern.match(text, pos):
            month, number = _MONTHS[m["mon"].lower().rstrip(".")], int(m["day"])
            when = _make(int(m["year"]) if m["year"] else day.year, month, number)
            return (m.end(), when) if when else None
    return None


def _date(month: int, number: int, year: int | None, day: date, weekday: int | None) -> date | None:
    """The date written, in its year, or with none the next time it comes round: or, when a
    weekday is given that fits the last time instead and that was within RECENT days, that one."""
    if year is not None:
        return _make(year, month, number)
    ahead = _make(day.year, month, number)
    if ahead is None:  # February 29th, in a year without
        ahead = next(
            filter(None, (_make(y, month, number) for y in range(day.year, day.year + 9))), None
        )
        if ahead is None:  # no such date at all
            return None
    if ahead < day:
        ahead = next(
            filter(None, (_make(y, month, number) for y in range(day.year + 1, day.year + 9)))
        )
    behind = _make(ahead.year - 1, month, number)
    if weekday is not None and behind and (day - behind).days <= RECENT:
        return behind if behind.weekday() == weekday else ahead
    return ahead


def _make(year: int, month: int, number: int) -> date | None:
    try:
        return date(year, month, number)
    except ValueError:
        return None


def _full(weekday: str) -> str:
    """A weekday as written ("thu", "Thurs.") as its full lower-case name."""
    word = weekday.lower().rstrip(".")
    return next(n for n in _NAMES if n.startswith(word[:3]))


def _like(written: str, name: str) -> str:
    """The weekday `name`, spelled as `written` was: short or full, and its capitals."""
    short = written.rstrip(".").lower() != _full(written)
    out = name[:3] if short else name
    if written.rstrip(".").isupper():
        out = out.upper()
    elif written[:1].isupper():
        out = out.capitalize()
    return out + ("." if written.endswith(".") else "")


def _when(when: date) -> str:
    return f"{when:%B} {when.day}, {when.year}"
