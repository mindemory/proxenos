"""What I could do better: specific changes, from evidence, judged by my own goals.

Each run gives the model the whole self-model, the last three months of observer notes, the
task list, and summaries of my Strava training and Spotify listening worked out here, and
asks for five to eight changes to how I spend time, work, train, sleep, handle tasks, decide
and communicate. Each one names the pattern it starts from and cites its evidence. A run
lands in clones/advisor/<date>.json, and a second run on the same day replaces it.

The page marks suggestions useful, not me, or doing in clones/advisor/feedback.jsonl. Later
runs never bring back what I marked not me, and follow up on what I said I'm doing.
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import llm
from proxenos.config import env

MONTHS = 3
TOP_SHOWN = 15  # artists and shows listed
LONGEST_SHOWN = 3  # longest sessions listed

AREAS = (
    "time",
    "work",
    "tasks",
    "health",
    "training",
    "sleep",
    "communication",
    "learning",
    "relationships",
    "money",
)
CONFIDENCE = ("high", "medium", "low")
_REACTIONS = ("useful", "not_me", "doing")
_MONTH = re.compile(r"\d{4}-\d{2}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_SYSTEM = """\
You advise {person} on what they could do better: more rationally, by their own goals, than \
they already do it. Their digital twin keeps a model of them built from their own messages, \
mail, listening and training. You get that self-model, notes observed over the last few \
months, their task list, summaries of their training and listening, and how they took \
earlier advice.

Find specific, evidence-based improvements to how {person} spends time, works, trains, \
sleeps, handles tasks, decides and communicates. For each:
- area: the one it is mostly about.
- pattern: what they do now, specifically, and the evidence for it: dates, counts, what the \
notes say.
- suggestion: one concrete, small change they could try this week, and how they'd tell \
whether it worked.
- why: why it's more rational than what they do now, in terms of their own goals as the \
self-model states them. Name the goal.
- confidence: high when the evidence is direct and repeated, medium when it's suggestive, \
low when it rests on one note or an inference.
- evidence: what it rests on, from the sources offered: a note's path, "tasks", "strava" or \
"spotify". At least one.

Rules:
- Five to eight suggestions, strongest first. Fewer when the evidence is thin; never pad.
- Nothing generic. A suggestion that would fit almost anyone ("sleep more", "keep a to-do \
list") gets dropped or made specific to them.
- No moralizing. Work within their goals and values; don't judge them or swap in your own.
- Nothing medical. Where something may be a health matter (an injury, sleep that stays bad, \
a low mood that lasts), the most you suggest is seeing a professional.
- Their reactions come first. Never repeat or reword a suggestion they marked not_me. Follow \
up on the ones they're doing: say whether the data shows it working and what comes next.
- Refer to them as {person} and don't assume pronouns. Nothing sensitive about other people."""


def advise(vault: Path, months: int = MONTHS, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=round(months * 365.25 / 12))
    out = vault / "clones" / "advisor"
    profile = read_self(vault / "self")

    notes = observations(vault, since)
    sources = [path for path, _ in notes]
    parts = [
        (
            f"Today is {_local(now):%A %Y-%m-%d}. The window is the last {months} months, "
            f"from {_local(since):%Y-%m-%d}."
        ),
        f"# Self-model\n\n{profile}",
        "# Observer notes, oldest first\n\n"
        + (
            "\n\n".join(f'<note path="{path}">\n{text}\n</note>' for path, text in notes)
            or "None for this window."
        ),
    ]
    sections = [
        ("tasks", "Task list, kept up to date from their recent messages", _tasks_text(vault)),
        ("strava", "Strava, worked out from their activities", strava_summary(vault, since, now)),
        ("spotify", "Spotify, worked out from their plays", spotify_summary(vault, since, now)),
    ]
    for name, title, text in sections:
        if text:
            sources.append(name)
            parts.append(f'# {title} (cite as "{name}")\n\n{text}')
        else:
            parts.append(f"# {title}\n\nNone on record for this window.")
    if not sources:
        raise SystemExit(
            f"advisor: nothing to go on from the last {months} months: no observer notes, "
            "tasks, Strava or Spotify. `proxenos master` writes the notes."
        )
    history, not_me = _history(out, since)
    parts.append(f"# Earlier advice and how they took it\n\n{history}")

    answer = llm.ask(
        "\n\n".join(parts),
        system=_SYSTEM.format(person=env("NAME", "the person")),
        schema=_schema(sources),
        effort="high",
    )
    suggestions = {}
    for item in answer["suggestions"]:
        text = " ".join(item["suggestion"].split())
        key = suggestion_id(item["area"], text)
        evidence = [e for e in dict.fromkeys(item["evidence"]) if e in sources]
        if not text or not evidence or key in not_me or key in suggestions:
            continue
        suggestions[key] = {
            "id": key,
            "area": item["area"],
            "pattern": item["pattern"].strip(),
            "suggestion": text,
            "why": item["why"].strip(),
            "confidence": item["confidence"],
            "evidence": evidence,
        }
    run = {"generated": _iso(now), "suggestions": list(suggestions.values())}
    _write_json(out / f"{_local(now):%Y-%m-%d}.json", run)
    return {"suggestions": len(suggestions)}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--months", type=int, default=MONTHS, help="how many months of evidence to weigh"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return advise(vault, months=args.months)


def suggestion_id(area: str, suggestion: str) -> str:
    return hashlib.sha1(f"{area}{suggestion}".encode()).hexdigest()[:12]


def read_self(self_dir: Path) -> str:
    """Every file of the self-model, identity first. The changelog is history, not the model."""
    paths = sorted(self_dir.glob("*.md"), key=lambda p: (p.stem != "identity", p.stem))
    texts = [(p.stem, p.read_text(encoding="utf-8").strip()) for p in paths]
    texts = [(name, text) for name, text in texts if text and name != "CHANGELOG"]
    if not texts:
        raise SystemExit(
            f"advisor: there's no self-model yet ({self_dir} is empty). "
            "`proxenos master` builds it; run that first."
        )
    return "\n\n".join(f"<{name}>\n{text}\n</{name}>" for name, text in texts)


def observations(vault: Path, since: datetime) -> list[tuple[str, str]]:
    """Notes on every month the window touches, oldest first, as (path in the vault, text)."""
    first = _iso(since)[:7]
    paths = [
        p
        for p in (vault / "observations").glob("**/*.md")
        if _MONTH.fullmatch(p.stem) and p.stem >= first
    ]
    paths.sort(key=lambda p: (p.stem, p.as_posix()))
    return [(p.relative_to(vault).as_posix(), p.read_text(encoding="utf-8").strip()) for p in paths]


def strava_summary(vault: Path, since: datetime, now: datetime) -> str:
    acts = _records(vault / "raw" / "strava" / "activities", since, now)
    if not acts:
        return ""
    hours = sum(a.get("moving_time_s") or 0 for a in acts) / 3600
    km = sum(a.get("distance_m") or 0 for a in acts) / 1000
    lines = [f"{len(acts)} activities: {hours:.1f} h moving, {km:.0f} km."]

    by_sport: dict[str, list[dict]] = defaultdict(list)
    for a in acts:
        by_sport[a.get("sport_type") or "Other"].append(a)
    sports = []
    for sport, group in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        heart = [a["average_heartrate"] for a in group if a.get("average_heartrate")]
        hr = f", average HR {sum(heart) / len(heart):.0f}" if heart else ""
        sport_km = sum(a.get("distance_m") or 0 for a in group) / 1000
        sport_h = sum(a.get("moving_time_s") or 0 for a in group) / 3600
        sports.append(f"{sport} {len(group)} ({sport_km:.0f} km, {sport_h:.1f} h{hr})")
    lines.append("By sport: " + "; ".join(sports) + ".")

    count, moving = Counter(), Counter()
    for a in acts:
        count[_monday(a["ts"])] += 1
        moving[_monday(a["ts"])] += (a.get("moving_time_s") or 0) / 3600
    weeks = _mondays(since, now)
    lines.append(
        "Per week, by the Monday it starts (first and last are partial): "
        + ", ".join(f"{m:%m-%d} {count[m]} ({moving[m]:.1f} h)" for m in weeks)
        + "."
    )
    starts = Counter(_local(a["ts"]).hour for a in acts)
    lines.append(
        "Start times, local: " + ", ".join(f"{h:02d}h {starts[h]}" for h in sorted(starts)) + "."
    )
    weekdays = Counter(_local(a["ts"]).weekday() for a in acts)
    lines.append(
        "By weekday: " + ", ".join(f"{d} {weekdays[n]}" for n, d in enumerate(_WEEKDAYS)) + "."
    )

    days = sorted({_local(a["ts"]).date() for a in acts})
    gap, start, end = max(((b - a).days, a, b) for a, b in zip([days[0], *days], days))
    if gap > 1:
        lines.append(f"Longest gap between activities: {gap} days, {start:%m-%d} to {end:%m-%d}.")
    lines.append(f"Last activity {(_local(now).date() - days[-1]).days} day(s) ago.")
    longest = sorted(acts, key=lambda a: a.get("moving_time_s") or 0, reverse=True)
    lines.append("Longest sessions: " + "; ".join(map(_session, longest[:LONGEST_SHOWN])) + ".")
    return "\n".join(lines)


def _session(a: dict) -> str:
    km = (a.get("distance_m") or 0) / 1000
    minutes = (a.get("moving_time_s") or 0) / 60
    name = f" '{a['name']}'" if a.get("name") else ""
    return f"{_local(a['ts']):%m-%d} {a.get('sport_type')}{name}, {km:.1f} km in {minutes:.0f} min"


def spotify_summary(vault: Path, since: datetime, now: datetime) -> str:
    plays = [
        p
        for p in _records(vault / "raw" / "spotify" / "plays", since, now)
        if p.get("ms_played") and not p.get("incognito")
    ]
    if not plays:
        return ""
    minutes = [p["ms_played"] / 60000 for p in plays]
    total = sum(minutes)
    skipped = sum(bool(p.get("skipped")) for p in plays) / len(plays)
    talk = sum(m for p, m in zip(plays, minutes) if p.get("kind") in ("episode", "audiobook"))
    lines = [
        (
            f"{len(plays)} plays, {total / 60:.1f} h, {skipped:.0%} skipped; "
            f"{talk / total:.0%} of the time podcasts and audiobooks."
        )
    ]

    week, hour, weekday, who = Counter(), Counter(), Counter(), Counter()
    for p, m in zip(plays, minutes):
        when = _local(p["ts"])
        week[_monday(p["ts"])] += m / 60
        hour[when.hour] += m
        weekday[when.weekday()] += m / 60
        if p.get("kind") == "track":
            who[f"{p.get('artist')} (artist)"] += m
        else:
            who[f"{p.get('show')} ({p.get('kind')})"] += m
    weeks = _mondays(since, now)
    lines.append(
        "Hours per week, by the Monday it starts (first and last are partial): "
        + ", ".join(f"{m:%m-%d} {week[m]:.1f}" for m in weeks)
        + "."
    )
    lines.append(
        "Listening by hour of day, local (minutes): "
        + ", ".join(f"{h:02d}h {hour[h]:.0f}" for h in range(24))
        + "."
    )
    night = sum(hour[h] for h in range(5)) / total
    lines.append(f"Between midnight and 5am: {night:.0%} of listening.")
    lines.append(
        "By weekday (hours): "
        + ", ".join(f"{d} {weekday[n]:.1f}" for n, d in enumerate(_WEEKDAYS))
        + "."
    )
    lines.append("Top artists and shows by minutes:")
    lines += [f"  {name}: {m:.0f}" for name, m in who.most_common(TOP_SHOWN)]
    return "\n".join(lines)


def _tasks_text(vault: Path) -> str:
    path = vault / "clones" / "tasks" / "tasks.json"
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))["tasks"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    if not tasks:
        return ""
    status = Counter(t.get("status") for t in tasks)
    lines = [f"{status['open']} open, {status['waiting']} waiting, {status['done']} done lately."]
    for t in tasks:
        state = ", ".join(filter(None, [t.get("status"), t.get("priority"), _due(t)]))
        origin = ", ".join(filter(None, [t.get("source"), _with(t), _asked(t)]))
        detail = f" {t['detail']}" if t.get("detail") else ""
        lines.append(f"- [{state}] {t.get('title')}.{detail} ({origin})")
    return "\n".join(lines)


def _due(task: dict) -> str | None:
    return f"due {task['due']}" if task.get("due") else None


def _with(task: dict) -> str | None:
    return f"with {task['with']}" if task.get("with") else None


def _asked(task: dict) -> str | None:
    return f"asked {_local(task['asked_at']):%Y-%m-%d}" if task.get("asked_at") else None


def _history(out: Path, since: datetime) -> tuple[str, set[str]]:
    """Earlier advice and my reactions to it as prompt text, and the ids I marked not_me.
    What I'm doing or rejected comes back however old; the rest only from the window."""
    given: dict[str, tuple[str, dict]] = {}
    for path in sorted(out.glob("*.json")):
        if not _DAY.fullmatch(path.stem):
            continue
        try:
            suggestions = json.loads(path.read_text(encoding="utf-8"))["suggestions"]
        except (ValueError, KeyError, TypeError):
            continue
        for s in suggestions:
            given[s["id"]] = (path.stem, s)
    reactions = _feedback(out / "feedback.jsonl")

    first = f"{_local(since):%Y-%m-%d}"
    groups: dict[str | None, list[str]] = defaultdict(list)
    for key, (day, s) in sorted(given.items(), key=lambda kv: kv[1][0]):
        action = reactions.get(key)
        if action in ("doing", "not_me") or day >= first:
            groups[action].append(f"- [{s['area']}] {s['suggestion']} (given {day})")
    heads = {
        "doing": "They're doing these. Follow up on each: does the evidence show it working, "
        "and what's the next step?",
        "not_me": "They marked these not them. Don't suggest them again, reworded or not:",
        "useful": "They found these useful:",
        None: "No reaction yet. Don't repeat one unless new evidence makes it stronger:",
    }
    text = "\n\n".join(
        "\n".join([head, *groups[action]]) for action, head in heads.items() if groups[action]
    )
    not_me = {key for key, action in reactions.items() if action == "not_me"}
    return text or "No earlier advice yet.", not_me


def _feedback(path: Path) -> dict[str, str]:
    """My latest reaction to each suggestion: {suggestion_id: action}."""
    if not path.exists():
        return {}
    latest: dict[str, tuple[datetime, str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                key, action, when = event["suggestion_id"], event["action"], _when(event["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # the page writes this file, and one bad line shouldn't stop a run
            if action not in _REACTIONS or when is None or not isinstance(key, str):
                continue
            if key not in latest or when >= latest[key][0]:
                latest[key] = (when, action)
    return {key: action for key, (_, action) in latest.items()}


def _schema(sources: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "enum": list(AREAS)},
                        "pattern": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "why": {"type": "string"},
                        "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string", "enum": sources},
                        },
                    },
                    "required": ["area", "pattern", "suggestion", "why", "confidence", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["suggestions"],
        "additionalProperties": False,
    }


def _records(directory: Path, since: datetime, now: datetime) -> list[dict]:
    start, end = _iso(since), _iso(now)
    found = []
    for path in sorted(directory.glob("*.jsonl")):
        if start[:7] <= path.stem <= end[:7]:
            with path.open(encoding="utf-8") as f:
                found += [r for r in map(json.loads, f) if start <= r["ts"] <= end]
    return found


def _mondays(since: datetime, now: datetime) -> list[date]:
    monday = _local(since).date()
    monday -= timedelta(days=monday.weekday())
    weeks = []
    while monday <= _local(now).date():
        weeks.append(monday)
        monday += timedelta(days=7)
    return weeks


def _monday(ts: str) -> date:
    day = _local(ts).date()
    return day - timedelta(days=day.weekday())


def _local(when: str | datetime) -> datetime:
    """A UTC timestamp in this machine's time zone, where the hours of my day make sense."""
    return (datetime.fromisoformat(when) if isinstance(when, str) else when).astimezone()


def _when(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
