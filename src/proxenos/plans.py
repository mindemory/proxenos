"""The plans on the user's task list, as a calendar they subscribe to.

A task with a set time (a meeting, a call, a visit: "at" on clones/tasks/tasks.json, which the
tasks clone reads from their messages) becomes an event in clones/tasks/plans.ics, unless it's
done or already on one of their own calendars. The page serves the file at /api/plans.ics, so
Calendar on the Mac (File, New Calendar Subscription) or a phone over Tailscale subscribes to it
once, and then shows each plan the sync finds, moved when the plan moves and gone once it's done.
Nothing is written to the user's own calendars, and no one is invited.

Times are floating, local wherever the calendar is read, as the messages say them ("at 12"). An
event lasts MINUTES; a plan with a day and no time is an all-day event. A plan is on their
calendar already when an event in raw/calendar/ is on the same day, within NEAR of its time when
both have one, and shares a word with it (its title's or the other person's), so the visit they
put in themselves isn't shown twice. Subscribed calendars aren't read back in (maccalendar leaves
them out), so this one never counts as theirs.
"""

import json
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

MINUTES = 60
NEAR = timedelta(hours=2)
PAST_DAYS = 2  # plans this long gone stay, so today's don't vanish the moment they start
NAME = "Proxenos"
_AT = re.compile(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2}))?")
_WORD = re.compile(r"[^\W\d_]{3,}")
# Words a plan and an event share without being about the same thing.
_COMMON = {
    *("about", "and", "appointment", "attend", "call", "check", "coffee", "dinner", "for"),
    *("from", "have", "join", "lunch", "meet", "meeting", "the", "video", "visit", "with", "zoom"),
}
_SOURCES = {"whatsapp": "WhatsApp", "slack": "Slack", "email": "email"}


def write(vault: Path, tasks: Iterable[dict], now: datetime | None = None) -> int:
    """Write clones/tasks/plans.ics from the tasks, and say how many events it holds."""
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    theirs = list(_calendar(vault, today - timedelta(days=PAST_DAYS)))
    events = []
    for task in tasks:
        when = at(task.get("at"))
        if task.get("status") == "done" or when is None:
            continue
        day = when if isinstance(when, date) and not isinstance(when, datetime) else when.date()
        if day < today - timedelta(days=PAST_DAYS) or any(_same(task, when, e) for e in theirs):
            continue
        events.append((task, when))
    path = vault / "clones" / "tasks" / "plans.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(ics(events, now), encoding="utf-8", newline="")
    tmp.replace(path)
    return len(events)


def at(text: object) -> datetime | date | None:
    """A task's "at": a local time ("2026-11-01T12:00") as a naive datetime, a day as a date."""
    match = _AT.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match:
        return None
    try:
        day = date.fromisoformat(match[1])
        if match[2] is None:
            return day
        return datetime(day.year, day.month, day.day, int(match[2]), int(match[3]))
    except ValueError:
        return None


def ics(events: list[tuple[dict, datetime | date]], now: datetime) -> str:
    """The events as an iCalendar file: one VEVENT a task, its UID the task's id."""
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Proxenos//Plans//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{NAME}",
        "X-WR-CALDESC:Plans Proxenos found in your messages",
        "REFRESH-INTERVAL;VALUE=DURATION:PT15M",
        "X-PUBLISHED-TTL:PT15M",
    ]
    for task, when in sorted(events, key=lambda e: (str(e[1]), e[0]["id"])):
        if isinstance(when, datetime):
            span = [
                f"DTSTART:{when:%Y%m%dT%H%M%S}",
                f"DTEND:{when + timedelta(minutes=MINUTES):%Y%m%dT%H%M%S}",
            ]
        else:
            span = [
                f"DTSTART;VALUE=DATE:{when:%Y%m%d}",
                f"DTEND;VALUE=DATE:{when + timedelta(days=1):%Y%m%d}",
            ]
        where = f"From {_SOURCES.get(task.get('source'), 'your messages')}"
        if task.get("with"):
            where += f", with {task['with']}"
        about = "\n\n".join(p for p in (task.get("detail") or "", where + ".") if p)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{task['id']}@proxenos",
            f"DTSTAMP:{stamp}",
            *span,
            f"SUMMARY:{_text(task['title'])}",
            *([f"LOCATION:{_text(task['place'])}"] if task.get("place") else []),
            f"DESCRIPTION:{_text(about)}",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _calendar(vault: Path, since: date) -> Iterator[dict]:
    """The user's own events from `since` on, as {day, time (None all day), words}."""
    first = f"{since:%Y-%m}.jsonl"
    for path in sorted((vault / "raw" / "calendar").glob("*/*.jsonl")):
        if path.name < first or path.parent.name.startswith("birthdays"):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                start = str(event["start"])
            except (ValueError, KeyError, TypeError):
                continue
            if event.get("all_day") or len(start) == 10:
                when, time = _day(start), None
            else:
                try:
                    time = datetime.fromisoformat(start).astimezone().replace(tzinfo=None)
                except ValueError:
                    continue
                when = time.date()
            if when is not None and when >= since:
                yield {"day": when, "time": time, "words": _words(event.get("summary"))}


def _same(task: dict, when: datetime | date, event: dict) -> bool:
    """Whether one of the user's own events is this plan."""
    day = when.date() if isinstance(when, datetime) else when
    if event["day"] != day:
        return False
    if isinstance(when, datetime) and event["time"] and abs(event["time"] - when) > NEAR:
        return False
    return bool(event["words"] & (_words(task.get("title")) | _words(task.get("with"))))


def _words(text: object) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").casefold()) if w not in _COMMON}


def _day(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _text(value: str) -> str:
    """A value as iCalendar text: backslashes, commas, semicolons and line breaks escaped."""
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return re.sub(r"\r?\n", "\\\\n", value)


def _fold(line: str) -> str:
    """A content line folded at 75 bytes, never inside a character."""
    out, part = [], ""
    for char in line:
        limit = 75 if not out else 74  # a continuation line starts with a space
        if len((part + char).encode()) > limit:
            out.append(part)
            part = ""
        part += char
    out.append(part)
    return "\r\n ".join(out)
