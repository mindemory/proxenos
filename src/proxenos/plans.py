"""The plans on the user's task list, on their calendar.

A task that is a meeting, a call, a visit or an appointment at a set time ("event" and "at" on
clones/tasks/tasks.json, which the tasks clone reads from their messages) becomes an event in clones/tasks/plans.ics, unless it's
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

A subscription only reaches the Calendar apps that subscribe, and Google Calendar can't fetch a
file on this Mac. So with PROXENOS_PLANS_CALENDAR naming one of the user's calendars in the Mac's
Calendar app (their Google one, say "me@gmail.com"), the same events also go there (`push`),
through the Calendar app, which syncs them to the account like any event they add. Each plan's
event is made once, made again when the plan moves, and deleted once it's done or gone. Only the
events it made are ever changed or deleted: their ids are kept in clones/tasks/pushed.json, and
when the calendar is read back in, those don't count as the user's own. An event is found by
its id (`event id`), never by searching the calendar for it, which takes Calendar over half a
minute on a calendar years long. Off until it's set, and
only on a Mac; macOS asks once whether Proxenos may use Calendar. Never from a made-up vault
(`proxenos demo`), which the page may run with the user's own settings.
"""

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos.config import env

MINUTES = 60
NEAR = timedelta(hours=2)
SAME_PERSON_DAYS = 2  # their own event with the plan's person this close is the plan
PAST_DAYS = 2  # plans this long gone stay, so today's don't vanish the moment they start
NAME = "Proxenos"
_AT = re.compile(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}):(\d{2}))?")
_WORD = re.compile(r"[^\W\d_]{3,}")
_TOKEN = re.compile(r"[^\W\d_]+")
# Words a plan and an event share without being about the same thing.
_COMMON = {
    *("about", "and", "appointment", "attend", "call", "check", "coffee", "dinner", "for"),
    *("from", "have", "join", "lunch", "meet", "meeting", "the", "video", "visit", "with", "zoom"),
}
# A title that starts with one of these is something to do, not something that happens at a time.
_ACTION = re.compile(
    r"\s*(reschedule|follow[ -]?up|email|reply|send|ask|confirm|book|check|find|write|draft|pay"
    r"|call back)\b",
    re.IGNORECASE,
)
_SOURCES = {"whatsapp": "WhatsApp", "slack": "Slack", "email": "email"}
WEEK_DAYS = 7  # of the user's calendar a draft sees, to suggest a time that's free
PUSHED = "pushed.json"  # in clones/tasks/: each plan's event on the user's calendar, by task id
OSA_SECONDS = 120  # for one change to the Calendar app, which can be slow while it syncs
# One change to the Calendar app: delete the event with the given uid, if any, then, unless the
# action is "delete", make the new one and say its uid. Dates come as "YYYY MM DD HH MM".
_SCRIPT = """\
on run argv
  set {action, calName, oldUid} to {item 1 of argv, item 2 of argv, item 3 of argv}
  tell application "Calendar"
    set cal to first calendar whose name is calName
    if oldUid is not "" then
      try
        delete (event id oldUid of cal)
      end try
    end if
    if action is "delete" then return ""
    set props to {summary:item 4 of argv, location:item 5 of argv, description:item 6 of argv}
    set props to props & {start date:my stamp(item 8 of argv), end date:my stamp(item 9 of argv)}
    if item 7 of argv is "1" then set props to props & {allday event:true}
    set made to make new event at end of events of cal with properties props
    return uid of made
  end tell
end run

on stamp(text_)
  set {y, m, d, hh, mm} to words of text_
  set t to current date
  set day of t to 1
  set year of t to (y as integer)
  set month of t to (m as integer)
  set day of t to (d as integer)
  set hours of t to (hh as integer)
  set minutes of t to (mm as integer)
  set seconds of t to 0
  return t
end stamp
"""


def write(
    vault: Path,
    tasks: Iterable[dict],
    now: datetime | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Write clones/tasks/plans.ics from the tasks, put the same events on the calendar
    PROXENOS_PLANS_CALENDAR names, and say how many events there are."""
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    made = {p["uid"] for p in _pushed(vault).values()}  # Proxenos's own, not the user's
    theirs = list(_calendar(vault, today - timedelta(days=PAST_DAYS), made))
    events = []
    for task in tasks:
        when = at(task.get("at"))
        if task.get("status") in ("done", "cancelled") or when is None or not is_event(task):
            continue
        day = when if isinstance(when, date) and not isinstance(when, datetime) else when.date()
        if day < today - timedelta(days=PAST_DAYS) or any(_same(task, when, e) for e in theirs):
            continue
        events.append((task, when))
    events = _once(events)
    path = vault / "clones" / "tasks" / "plans.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(ics(events, now), encoding="utf-8", newline="")
    tmp.replace(path)
    from proxenos import outbox  # it reads the work clone, which reads this module

    # A made-up vault's plans never reach the user's own calendar, whatever the settings say.
    calendar = "" if outbox.is_demo(vault) else env("PLANS_CALENDAR").strip()
    if calendar and sys.platform == "darwin":
        try:
            push(vault, events, calendar, run)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            print(f"plans: couldn't update {calendar} ({' '.join(str(e).split())[:200]})")
    return len(events)


def is_event(task: dict) -> bool:
    """Whether a task is something that happens at a time (a meeting, call, visit, appointment,
    booking) and so belongs on a calendar: the tasks clone says so in "event". Whatever it says,
    a title that starts with an action ("Reschedule ...", "Follow up ...") is a task about a
    meeting, not the meeting, and older tasks without the field are judged by that alone."""
    if _ACTION.match(str(task.get("title") or "")):
        return False
    return task.get("event") is not False


def _once(events: list[tuple[dict, datetime | date]]) -> list[tuple[dict, datetime | date]]:
    """One event a plan: of tasks on the same day, within NEAR of each other, about the same
    person or sharing title words, the earliest made is kept, since the model sometimes writes
    one meeting as two tasks."""
    kept: list[tuple[dict, datetime | date]] = []
    for task, when in sorted(events, key=lambda e: (e[0].get("asked_at") or "~", e[0]["id"])):
        if not any(_alike(task, when, k, w) for k, w in kept):
            kept.append((task, when))
    return [e for e in events if any(e[0] is k for k, _ in kept)]


def _alike(task: dict, when: datetime | date, other: dict, then: datetime | date) -> bool:
    """Whether two tasks are one plan: same day, close in time, the same person or title words."""
    if (when.date() if isinstance(when, datetime) else when) != (
        then.date() if isinstance(then, datetime) else then
    ):
        return False
    if isinstance(when, datetime) and isinstance(then, datetime) and abs(when - then) > NEAR:
        return False
    ours = _words(task.get("with")) | _words(task.get("title"))
    return bool(ours & (_words(other.get("with")) | _words(other.get("title"))))


def week(
    vault: Path, now: datetime | None = None, days: int = WEEK_DAYS, before: datetime | None = None
) -> str:
    """The user's own events from today for `days` days, one line each in local time, for a
    draft that suggests a time; "" when there are none. An event on two calendars shows once.
    With `before`, only events that began before it: for a draft as of an earlier time, since
    raw/calendar doesn't say when an event was made, and one made after could give it away."""
    now = now or datetime.now(UTC)
    today = now.astimezone().date()
    end = today + timedelta(days=days)
    lines = {}
    for event in _calendar(vault, today):
        if event["day"] >= end:
            continue
        if before is not None and not _began(event, before):
            continue
        when = (
            f"{event['time']:%a %b %d %H:%M}"
            if event["time"]
            else f"{event['day']:%a %b %d}, all day"
        )
        lines[(event["day"], event["time"] or datetime.min, event["title"])] = (
            f"- {when}: {event['title']}"
        )
    return "\n".join(line for _, line in sorted(lines.items(), key=lambda kv: (kv[0][0], kv[0][1])))


def push(
    vault: Path,
    events: list[tuple[dict, datetime | date]],
    calendar: str,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, int]:
    """Bring `calendar` in the Calendar app up to date with the events: each new or changed plan
    made there (a changed one deleted and made again), and each event made for a plan that's
    gone deleted. What it did, by count."""
    path = vault / "clones" / "tasks" / PUSHED
    pushed = _pushed(vault)
    done = {"added": 0, "moved": 0, "removed": 0}
    for task, when in events:
        fields = _fields(task, when)
        mark = hashlib.sha1(json.dumps([calendar, *fields]).encode()).hexdigest()[:12]
        old = pushed.get(task["id"])
        if old and old["mark"] == mark:
            continue
        stale = old["uid"] if old and old["calendar"] == calendar else ""
        if old and not stale:  # the setting names another calendar now: leave none behind
            _osa(run, "delete", old["calendar"], old["uid"])
        uid = _osa(run, "make", calendar, stale, *fields)
        if not uid:
            raise ValueError(f"the Calendar app made no event for {task['title']!r}")
        pushed[task["id"]] = {"uid": uid, "calendar": calendar, "mark": mark}
        done["moved" if old else "added"] += 1
        _save(path, pushed)  # after each, so an interrupted run never forgets an event it made
    current = {task["id"] for task, _ in events}
    for key in [k for k in pushed if k not in current]:
        _osa(run, "delete", pushed[key]["calendar"], pushed[key]["uid"])
        del pushed[key]
        done["removed"] += 1
        _save(path, pushed)
    return done


def _fields(task: dict, when: datetime | date) -> list[str]:
    """An event as the script takes it: title, place, notes, all day, start and end."""
    if isinstance(when, datetime):
        start, end, whole = when, when + timedelta(minutes=MINUTES), "0"
    else:
        start = datetime(when.year, when.month, when.day)
        end, whole = start + timedelta(days=1), "1"
    where = f"From {_SOURCES.get(task.get('source'), 'your messages')}"
    if task.get("with"):
        where += f", with {task['with']}"
    notes = "\n\n".join(p for p in (task.get("detail") or "", f"{where}. Added by Proxenos.") if p)
    stamp = "%Y %m %d %H %M"
    return [
        task["title"],
        task.get("place") or "",
        notes,
        whole,
        f"{start:{stamp}}",
        f"{end:{stamp}}",
    ]


def _osa(run: Callable[..., subprocess.CompletedProcess], *args: str) -> str:
    done = run(
        ["osascript", "-", *args],
        input=_SCRIPT,
        capture_output=True,
        text=True,
        timeout=OSA_SECONDS,
        check=False,
    )
    if done.returncode:
        raise ValueError(done.stderr.strip() or f"osascript exited {done.returncode}")
    return done.stdout.strip()


def _pushed(vault: Path) -> dict[str, dict]:
    try:
        found = json.loads((vault / "clones" / "tasks" / PUSHED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _save(path: Path, pushed: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(pushed, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


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


def _calendar(vault: Path, since: date, made: set[str] = frozenset()) -> Iterator[dict]:
    """The user's own events from `since` on, as {day, time (None all day), words}: not those
    whose ids are in `made`, the events push made."""
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
            mine = "Added by Proxenos." in str(event.get("description") or "")
            if mine or str(event.get("id", "")).split("/")[0] in made:
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
                title = " ".join(str(event.get("summary") or "busy").split())[:80]
                yield {
                    "day": when,
                    "time": time,
                    "words": _words(title),
                    "title": title,
                    "tokens": {t.casefold() for t in _TOKEN.findall(title)},
                    "people": _people(event),
                }


def _began(event: dict, when: datetime) -> bool:
    """Whether one of the user's own events began before `when`: by its time in local time, or
    for an all-day one, by its day's start."""
    local = when.astimezone()
    if event["time"] is None:
        return event["day"] <= local.date()
    return event["time"] < local.replace(tzinfo=None)


def _same(task: dict, when: datetime | date, event: dict) -> bool:
    """Whether one of the user's own events is this plan: with its person within
    SAME_PERSON_DAYS, or on its day, near its time, sharing a word with it."""
    day = when.date() if isinstance(when, datetime) else when
    if abs((event["day"] - day).days) <= SAME_PERSON_DAYS and _theirs_with(task, event):
        return True  # their calendar knows the real time better than a model reading messages
    if event["day"] != day:
        return False
    if isinstance(when, datetime) and event["time"] and abs(event["time"] - when) > NEAR:
        return False
    return bool(event["words"] & (_words(task.get("title")) | _words(task.get("with"))))


def _people(event: dict) -> set[str]:
    """The words of the names and addresses an event carries for its guests and organizer: a
    name's parts, an address's name before the @ split at dots, dashes and underscores."""
    found = set()
    guests = event.get("guests")
    for guest in [g for g in guests if isinstance(g, dict)] if isinstance(guests, list) else []:
        found |= _words(guest.get("name")) | _words(str(guest.get("email") or "").split("@")[0])
    return found | _words(str(event.get("organizer") or "").split("@")[0])


def _initials(name: object) -> str:
    """A name's initials ("Hsing-Hao Lee" is "hhl"); "" for fewer than three, which would
    be anyone's, the user's own among them."""
    letters = "".join(p[0] for p in _TOKEN.findall(str(name or "").casefold()))
    return letters if len(letters) >= 3 else ""


def _theirs_with(task: dict, event: dict) -> bool:
    """Whether one of the user's own events is with the plan's person: their name in its title,
    guests or organizer, or their initials as its title writes them ("MD HHL", with the user's
    own alongside)."""
    who = task.get("with")
    if _words(who) & (event["words"] | event["people"]):
        return True
    mark = _initials(who)
    return bool(mark) and any(
        t == mark or (len(t) <= len(mark) + 3 and (t.startswith(mark) or t.endswith(mark)))
        for t in event["tokens"]
    )


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
