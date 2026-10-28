"""Memories for today: what the vault remembers that bears on what is coming up. No model.

Recall starts from the present, with no query typed. For each trigger it searches the memory
index (`proxenos index`) and keeps the best few past records, so a meeting, a task, a feed item or a
person comes with the earlier conversations, mail and notes about it.

Triggers:

- events: calendar events starting in the next 48 hours, repeating ones included (raw/calendar);
- tasks: the open ones in clones/tasks/tasks.json, minus any I closed on the page since;
- feed: the ten best items of the newest batch in tracker/items, minus ones I marked not me;
- people: the 30 people in clones/network/people.json who count most, by interactions and
  recency, found by name among the people in a record.

A trigger's query is the content words of its title plus its people (an event's guests, a
task's person, a paper's authors), any of which may match. A memory has to score at or below
MIN_SCORE (bm25: more negative is a better match) and, so one long chat doesn't fill the list,
at most one comes from the same chat or day. Browsing history is never a memory, and an event
doesn't recall other calendar entries. A person has no query to rank by, so their memories are
the newest records they're in, spread over sources. A trigger nothing clears the bar for is
left out: no memory is better than a poor one.

Writes clones/recall/today.json ({"generated", "triggers": [{"kind", "id", "title", "when",
"memories"}]}, at most 5 memories each) and clones/recall/people.json (person id to up to 8
memories). A memory is a search hit: id, source, stream, ts, who, where_, title, snippet (the
matched words between \\x02 and \\x03), score and from_me.

An event's repeat rule is read for DAILY, WEEKLY, MONTHLY and YEARLY with INTERVAL, BYDAY,
BYMONTHDAY, UNTIL and COUNT. Exceptions to a rule aren't kept in the vault, and its times are
taken as the original start's time of day in UTC, so an event that moved is a rough guess.
"""

import argparse
import calendar
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import memory
from proxenos.config import env

WINDOW = timedelta(hours=48)  # how far ahead events count
FEED_ITEMS = 10
PEOPLE = 30
PER_TRIGGER = 5
PER_PERSON = 8
CANDIDATES = 40  # hits fetched per trigger before the bar and the spread cut them down
# A hit must score at most this (bm25, lower is better): about one specific word in a title, or
# two or three in the text. Matching only common words never gets there.
MIN_SCORE = -15.0
# A word in more rows than this says nothing about what a record is about, so it isn't searched.
MAX_DOCS = 2000
MAX_WORDS = 10
MAX_GUESTS = 5
HALF_LIFE_DAYS = 365  # as in the network clone: how fast an old contact stops counting

_MONTH = re.compile(r"\d{4}-\d{2}\.jsonl")
_WORD = re.compile(r"[^\W_]+")
_CLOSING = ("done", "not_mine", "dismiss")
_STOP = frozenset(
    [
        "about",
        "above",
        "after",
        "again",
        "all",
        "also",
        "and",
        "any",
        "are",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "can",
        "could",
        "did",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "her",
        "here",
        "him",
        "his",
        "how",
        "into",
        "its",
        "just",
        "more",
        "most",
        "not",
        "now",
        "off",
        "once",
        "only",
        "other",
        "our",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "too",
        "under",
        "until",
        "very",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)
_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--people", type=int, default=PEOPLE, help="how many of the top people to recall for"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return recall(vault, people=args.people)


def recall(vault: Path, now: datetime | None = None, people: int = PEOPLE) -> dict[str, int]:
    if not memory.exists(vault):
        raise SystemExit("recall: there is no memory index yet. Run `proxenos index` first.")
    now = now or datetime.now(UTC)
    events = _events(vault, now)
    triggers = [
        *(("event", *e[:5]) for e in events),
        *(("task", *t) for t in _tasks(vault)),
        *(("feed", *t) for t in _feed(vault)),
    ]
    today = []
    for kind, id_, title, when, words, names in triggers:
        found = _memories(vault, _query(vault, words, names), exclude=_ignored(kind))
        if found:
            today.append({"kind": kind, "id": id_, "title": title, "when": when, "memories": found})

    by_person: dict[str, list[dict]] = {}
    top = _top_people(vault, now, people)
    for person in top:
        found = _recent(vault, person["name"], PER_PERSON)
        if found:
            by_person[person["id"]] = found
            when = person.get("last_seen")
            today.append(
                {
                    "kind": "person",
                    "id": person["id"],
                    "title": person["name"],
                    "when": when,
                    "memories": found[:PER_TRIGGER],
                }
            )

    out = vault / "clones" / "recall"
    # Every event in the window, with memories or without, for the page's agenda.
    agenda = [{"title": e[1], "when": e[2], "all_day": e[5]} for e in events]
    _write(out / "today.json", {"generated": _iso(now), "events": agenda, "triggers": today})
    _write(out / "people.json", by_person)
    return {
        "triggers": len(triggers) + len(top),
        "triggers_with_memories": len(today),
        "memories": sum(len(t["memories"]) for t in today),
        "people": len(by_person),
    }


# Finding memories


def _ignored(kind: str) -> tuple[str, ...]:
    return ("calendar", "chrome") if kind == "event" else ("chrome",)


def _query(vault: Path, words: list[str], names: list[str]) -> str:
    """The words and names worth searching for: any of them may match."""
    terms = [*words, *(f'"{n}"' for n in names)]
    counts = memory.frequencies(terms, vault)
    return " ".join(t for t in terms if 0 < counts[t] <= MAX_DOCS)


def _memories(vault: Path, query: str, exclude: tuple[str, ...]) -> list[dict]:
    """The best past records for a query: good enough, and at most one per chat and day."""
    if not query:
        return []
    hits = memory.search(query, limit=CANDIDATES, match="any", exclude_sources=exclude, vault=vault)
    good = [h for h in hits if h["score"] <= MIN_SCORE]
    return _spread(good, PER_TRIGGER, per_source=PER_TRIGGER)


def _recent(vault: Path, name: str, count: int) -> list[dict]:
    """The newest records a person is in, no more than half of them from one source."""
    hits = memory.search("", who=name, limit=200, exclude_sources=("chrome",), vault=vault)
    return _spread(hits, count, per_source=max(2, count // 2))


def _spread(hits: list[dict], count: int, per_source: int) -> list[dict]:
    chosen: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    sources: Counter = Counter()
    for hit in hits:
        key = (hit["stream"], hit["where_"], hit["ts"][:10])
        if key in seen or sources[hit["source"]] >= per_source:
            continue
        seen.add(key)
        sources[hit["source"]] += 1
        chosen.append(hit)
        if len(chosen) == count:
            break
    return chosen


def _words(text: str) -> list[str]:
    """The distinct words of a title that could say what it's about."""
    found = {w: None for w in _WORD.findall(text.casefold()) if len(w) >= 3 and w not in _STOP}
    return [w for w in found if not w.isdigit()][:MAX_WORDS]


# Triggers: (id, title, when, query words, names); events add whether they last all day.


def _events(vault: Path, now: datetime) -> list[tuple]:
    end = now + WINDOW
    today = now.astimezone().date()
    found: dict[tuple[str, str], tuple] = {}
    for path in sorted((vault / "raw" / "calendar").glob("*/*.jsonl")):
        if not _MONTH.fullmatch(path.name):
            continue
        for record in _lines(path):
            title = " ".join(str(record.get("summary") or "").split())
            if not title or str(record.get("status") or "").upper() == "CANCELLED":
                continue
            start = _when(record.get("ts"))
            if start is None:
                continue
            if record.get("rrule"):
                starts = _repeats(
                    record["rrule"], start, now, end, today, bool(record.get("all_day"))
                )
            elif _within(start, now, end, today, bool(record.get("all_day"))):
                starts = [start]
            else:
                starts = []
            guests = [
                g["name"]
                for g in record.get("guests") or []
                if isinstance(g, dict) and g.get("name")
            ][:MAX_GUESTS]
            all_day = bool(record.get("all_day"))
            for when in starts:
                found.setdefault(
                    (title.casefold(), _iso(when)),
                    (str(record["id"]), title, _iso(when), _words(title), guests, all_day),
                )
    return sorted(found.values(), key=lambda e: e[2])


def _tasks(vault: Path) -> list[tuple]:
    data = _json(vault / "clones" / "tasks" / "tasks.json")
    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    closed = set()
    feedback = vault / "clones" / "tasks" / "feedback.jsonl"
    for event in _lines(feedback):
        if event.get("action") in _CLOSING:
            closed.add(event.get("task_id"))
    found = []
    for task in tasks:
        if (
            not isinstance(task, dict)
            or task.get("status") != "open"
            or not task.get("id")
            or task["id"] in closed
        ):
            continue
        title = " ".join(str(task.get("title") or "").split())
        person = " ".join(str(task.get("with") or "").split())
        if title:
            found.append(
                (
                    str(task["id"]),
                    title,
                    task.get("due") or None,
                    _words(title),
                    [person] if person else [],
                )
            )
    return found


def _feed(vault: Path) -> list[tuple]:
    rejected = set()
    for event in _lines(vault / "tracker" / "feedback.jsonl"):
        if event.get("action") == "not_me":
            rejected.add(event.get("item_id"))
        elif event.get("item_id") in rejected and event.get("action") != "open":
            rejected.discard(event["item_id"])
    items: dict[str, dict] = {}
    for path in sorted((vault / "tracker" / "items").glob("*.jsonl"), reverse=True):
        if not _MONTH.fullmatch(path.name):
            continue
        for item in _lines(path):
            if item.get("id") and item.get("title") and item["id"] not in rejected:
                items.setdefault(item["id"], item)
        if items:
            break  # the newest month holds the newest batch
    if not items:
        return []
    newest = max(items.values(), key=lambda i: str(i.get("ts") or ""))
    batch = [i for i in items.values() if i.get("batch") == newest.get("batch")]
    batch.sort(key=lambda i: -float(i.get("score") or 0))
    found = []
    for item in batch[:FEED_ITEMS]:
        authors = [a for a in item.get("authors") or [] if isinstance(a, str)][:3]
        title = " ".join(str(item["title"]).split())
        found.append(
            (
                str(item["id"]),
                title,
                item.get("published") or item.get("ts"),
                _words(title),
                authors,
            )
        )
    return found


def _top_people(vault: Path, now: datetime, count: int) -> list[dict]:
    """The people who count most: more interactions, and more recent, rank higher."""
    data = _json(vault / "clones" / "network" / "people.json")
    people = data.get("people", []) if isinstance(data, dict) else []
    me = {n.casefold() for n in (env("NAME"), env("FULL_NAME")) if n}

    def score(person: dict) -> float:
        last = _when(person.get("last_seen"))
        age = max((now - last).days, 0) if last else 10 * 365
        return math.log2(2 + int(person.get("interactions") or 0)) * 0.5 ** (age / HALF_LIFE_DAYS)

    named = [
        p
        for p in people
        if isinstance(p, dict)
        and p.get("id")
        and str(p.get("name") or "").strip()
        and str(p["name"]).casefold() not in me
    ]
    return sorted(named, key=score, reverse=True)[:count]


# Repeating events


def _within(start: datetime, now: datetime, end: datetime, today: date, all_day: bool) -> bool:
    if all_day:
        return today <= start.date() <= today + WINDOW
    return now <= start <= end


def _repeats(
    rule: str, start: datetime, now: datetime, end: datetime, today: date, all_day: bool
) -> list[datetime]:
    """The times a repeating event starts within the window."""
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    try:
        interval = max(int(parts.get("INTERVAL") or 1), 1)
        count = int(parts["COUNT"]) if "COUNT" in parts else None
    except ValueError:
        return []
    until = _when(parts.get("UNTIL"))
    if until and len(parts["UNTIL"]) == 8:  # a date: the whole of that day counts
        until += timedelta(days=1) - timedelta(seconds=1)
    first = start.date()
    found = []
    day = (today if all_day else now.date()) - timedelta(days=1)
    last = (today + WINDOW if all_day else end.date()) + timedelta(days=1)
    while day <= last:
        when = datetime.combine(day, start.timetz())
        if (
            day >= first
            and (until is None or when <= until)
            and _within(when, now, end, today, all_day)
            and _on(parts, interval, first, day)
            and (count is None or _nth(parts, interval, first, day) <= count)
        ):
            found.append(when)
        day += timedelta(days=1)
    return found


def _nth(parts: dict[str, str], interval: int, first: date, day: date) -> int:
    """Which occurrence of the rule `day` is, counting the first as 1."""
    return sum(
        _on(parts, interval, first, first + timedelta(days=n))
        for n in range((day - first).days + 1)
    )


def _on(parts: dict[str, str], interval: int, first: date, day: date) -> bool:
    """Whether a rule that starts on `first` falls on `day`."""
    if day == first:
        return True
    weekdays = {_DAYS.index(d[-2:]) for d in parts.get("BYDAY", "").split(",") if d[-2:] in _DAYS}
    match parts.get("FREQ"):
        case "DAILY":
            return (day - first).days % interval == 0
        case "WEEKLY":
            weeks = (_monday(day) - _monday(first)).days // 7
            return weeks % interval == 0 and day.weekday() in (weekdays or {first.weekday()})
        case "MONTHLY":
            months = (day.year - first.year) * 12 + day.month - first.month
            return months % interval == 0 and _monthly(parts, first, day, weekdays)
        case "YEARLY":
            same = (day.month, day.day) == (first.month, first.day)
            return same and (day.year - first.year) % interval == 0
    return False


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _monthly(parts: dict[str, str], first: date, day: date, weekdays: set[int]) -> bool:
    length = calendar.monthrange(day.year, day.month)[1]
    if "BYMONTHDAY" in parts:
        wanted = {int(n) for n in re.findall(r"-?\d+", parts["BYMONTHDAY"])}
        return day.day in wanted or day.day - length - 1 in wanted
    if weekdays:
        if day.weekday() not in weekdays:
            return False
        ordinals = {
            int(m.group(1))
            for d in parts["BYDAY"].split(",")
            if (m := re.match(r"([+-]?\d+)[A-Z]{2}$", d))
        }
        return (
            not ordinals
            or (day.day - 1) // 7 + 1 in ordinals
            or -((length - day.day) // 7 + 1) in ordinals
        )
    return day.day == first.day


# Files


def _lines(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _when(value: object) -> datetime | None:
    """An ISO date or time as UTC; a bare date or an iCalendar basic one (20260301) too."""
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}(T\d{6}Z?)?", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}" + (
            f"T{text[9:11]}:{text[11:13]}:{text[13:15]}" if len(text) > 8 else ""
        )
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
