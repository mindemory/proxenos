"""The day, written down: what got done, what was said, what's waiting and what's next, one entry
a day, so the user never has to narrate it.

A run writes clones/journal/<date>.json for one local day from what the other clones and the
sources already hold, reading nothing new:
- done: tasks closed that day (the tasks clone's closed.json), drafts sent (the page's marks and
  what fidelity saw go out), steps of a project's work accepted, forms filled;
- said: the chats the user wrote in that day, with how many messages (WhatsApp, Slack and email,
  as the tasks clone reads them), what they told Proxenos (proxenos.told) and their right-now note;
- moved: each project's commits that day, on any branch;
- waiting: tasks waiting on someone else;
- next: the next day's calendar, open tasks due within two days or marked high, the drafts
  waiting to be sent, and care's open items.
Then one model call writes the brief, a few sentences on how the day went and what matters next,
and the three things to do next, from those lines alone. Without a model, or when the call
fails, the entry keeps its lists and has no brief.

The night job (01:30) writes the day that just ended: a run before DAY_STARTS is yesterday's.
The page's Journal view writes today's on demand (`--date today`). The lines name the people the
user wrote to and the titles of their tasks and drafts, which go to the model with the prompt.
"""

import argparse
import json
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from proxenos import llm, plans, told
from proxenos.clones import tasks
from proxenos.config import env

DAY_STARTS = 6  # local hour: a run before it writes the day before
SAID = 12  # chats listed under said
NEXT_TASKS = 6
NEXT_DRAFTS = 3
SECTIONS = ("done", "said", "moved", "waiting", "next")

_SYSTEM = """\
You keep {person}'s journal. From the lines given about one day, write:
- brief: three to five plain sentences in the second person ("You sent...", "Tomorrow you..."): \
what got done and said, what's still open, and what matters most next. Only what the lines say; \
no praise, no advice beyond what they show, no headings.
- next_up: the three most important things to do next, each a short imperative, taken from the \
lines (an overdue task, a plan tomorrow, a draft waiting). Fewer when fewer matter.
Refer to people by name as given, and don't assume pronouns."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "brief": {"type": "string"},
        "next_up": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["brief", "next_up"],
    "additionalProperties": False,
}


def write(vault: Path, day: date | None = None, now: datetime | None = None) -> dict[str, int]:
    """Write the entry for `day` (the day that just ended, before DAY_STARTS), and count it."""
    now = now or datetime.now(UTC)
    day = day or (now.astimezone() - timedelta(hours=DAY_STARTS)).date()
    start = datetime.combine(day, time.min).astimezone()
    end = start + timedelta(days=1)
    sections = {
        "done": _done(vault, start, end),
        "said": _said(vault, start, end),
        "moved": _moved(vault, start, end),
        "waiting": _waiting(vault),
        "next": _next(vault, day, end),
    }
    entry = {"date": day.isoformat(), "generated": _iso(now), "brief": "", "next_up": []}
    if any(sections.values()) and llm.configured():
        person = env("NAME", "the person")
        lines = "\n\n".join(
            f"## {name}\n" + "\n".join(f"- {line}" for line in items)
            for name, items in sections.items()
            if items
        )
        try:
            answer = llm.ask(
                f"The day: {day:%A %Y-%m-%d}.\n\n{lines}",
                system=_SYSTEM.format(person=person),
                schema=_SCHEMA,
            )
            entry["brief"] = " ".join(str(answer.get("brief") or "").split())
            entry["next_up"] = [" ".join(str(n).split()) for n in answer.get("next_up") or []][:3]
        except llm.ModelError as e:
            print(f"journal: no brief ({' '.join(str(e).split())[:200]})")
    entry["sections"] = sections
    out = vault / "clones" / "journal"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f"{day.isoformat()}.json.tmp"
    tmp.write_text(json.dumps(entry, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out / f"{day.isoformat()}.json")
    return {f"{name} lines": len(items) for name, items in sections.items()} | {
        "briefs": int(bool(entry["brief"]))
    }


# What the day held


def _done(vault: Path, start: datetime, end: datetime) -> list[str]:
    found = []
    closed = _json(vault / "clones" / "tasks" / "closed.json")
    for entry in closed.values() if isinstance(closed, dict) else []:
        if _within(entry.get("closed_at"), start, end) and entry.get("action") in (None, "done"):
            found.append(f"Done: {entry.get('title')}")
    drafts = _drafts(vault)
    sent: dict[str, None] = {}
    for event in _jsonl(vault / "clones" / "drafts" / "feedback.jsonl"):
        if event.get("action") == "sent" and _within(event.get("ts"), start, end):
            sent[str(event.get("draft_id"))] = None
    fidelity = _json(vault / "clones" / "drafts" / "fidelity.json")
    for measured in fidelity.get("drafts", []) if isinstance(fidelity, dict) else []:
        if isinstance(measured, dict) and _within(measured.get("sent"), start, end):
            sent[str(measured.get("id"))] = None
    for key in sent:
        draft = drafts.get(key, {})
        to = f" to {draft['to']}" if draft.get("to") else ""
        found.append(f"Sent: {draft.get('title') or key}{to}")
    for path in sorted((vault / "clones" / "projects").glob("*/steps/*.json")):
        step = _json(path)
        if step.get("status") == "accepted" and _within(step.get("updated"), start, end):
            found.append(f"Accepted a step on {path.parent.parent.name}: {step.get('step')}")
    for path in sorted((vault / "clones" / "forms").glob("*.json")):
        form = _json(path)
        if _within(form.get("at"), start, end):
            left = len(form.get("left") or [])
            found.append(
                f"Filled {path.stem}: {len(form.get('filled') or [])} answers, {left} left"
            )
    return found


def _said(vault: Path, start: datetime, end: datetime) -> list[str]:
    counts = []
    for convo in tasks.conversations(vault, _iso(start)):
        if convo["source"] == "told":
            continue
        mine = [
            m for m in convo["messages"] if m["sender"] == "me" and _within(m["ts"], start, end)
        ]
        if mine:
            counts.append((len(mine), convo["title"]))
    lines = [
        f"Wrote in {title}: {n} message{'s' * (n > 1)}" for n, title in sorted(counts, reverse=True)
    ]
    lines = lines[:SAID]
    for note in told.notes(vault, end):
        if _within(note["at"], start, end):
            lines.append(f"Told Proxenos{' (a rule)' if note['always'] else ''}: {note['text']}")
    for note in _jsonl(vault / "state" / "now.jsonl"):
        if _within(note.get("at"), start, end) and note.get("text"):
            lines.append(f"Right now: {' '.join(str(note['text']).split())}")
    return lines


def _moved(vault: Path, start: datetime, end: datetime) -> list[str]:
    listed = _json(vault / "clones" / "projects" / "projects.json")
    found = []
    for project in listed.get("projects", []) if isinstance(listed, dict) else []:
        repo = Path(str(project.get("repo") or "")).expanduser()
        if not (repo / ".git").exists():
            continue
        log = _git(
            repo,
            "log",
            "--all",
            f"--since={start.isoformat()}",
            f"--until={end.isoformat()}",
            "--format=%s",
        )
        commits = [line for line in log.splitlines() if line.strip()]
        if commits:
            name = project.get("name") or project.get("id")
            found.append(f"{name}: {len(commits)} commits, the newest: {commits[0]}")
    return found


def _waiting(vault: Path) -> list[str]:
    found = []
    for task in _tasks(vault):
        if task.get("status") == "waiting":
            who = f" (with {task['with']})" if task.get("with") else ""
            found.append(f"Waiting: {task.get('title')}{who}")
    return found


def _next(vault: Path, day: date, end: datetime) -> list[str]:
    found = [f"Calendar {line[2:]}" for line in plans.week(vault, end, days=1).splitlines()]
    soon = (day + timedelta(days=2)).isoformat()
    open_tasks = [t for t in _tasks(vault) if t.get("status") == "open"]
    urgent = [
        t for t in open_tasks if (t.get("due") or "9999") <= soon or t.get("priority") == "high"
    ]
    for task in urgent[:NEXT_TASKS]:
        due = f" (due {task['due']})" if task.get("due") else ""
        found.append(f"Task: {task.get('title')}{due}")
    waiting = [
        d for d in _drafts(vault).values() if d["status"] in ("draft", "approved") and d["to"]
    ]
    if waiting:
        newest = sorted(waiting, key=lambda d: d["created"], reverse=True)[:NEXT_DRAFTS]
        names = "; ".join(d["title"] for d in newest)
        found.append(f"Drafts to send: {len(waiting)}, the newest: {names}")
    care = _json(vault / "clones" / "care" / "care.json")
    for item in (care.get("open_items") or [])[:3] if isinstance(care, dict) else []:
        if isinstance(item, dict) and item.get("title"):
            found.append(f"Care: {item['title']}")
    return found


# Reading


def _tasks(vault: Path) -> list[dict]:
    listed = _json(vault / "clones" / "tasks" / "tasks.json")
    return (
        [t for t in listed.get("tasks", []) if isinstance(t, dict)]
        if isinstance(listed, dict)
        else []
    )


def _drafts(vault: Path) -> dict[str, dict]:
    """Each draft by id: {title, to, status, created}."""
    found = {}
    for path in sorted((vault / "clones" / "drafts").glob("*.md")):
        fields: dict[str, str] = {}
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        for line in text.split("\n---", 1)[0].splitlines()[1:]:
            key, _, value = line.partition(":")
            value = value.strip()
            if value.startswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            fields.setdefault(key.strip(), str(value))
        key = fields.get("id") or path.stem
        found[key] = {
            "title": fields.get("title", ""),
            "to": fields.get("to", ""),
            "status": (fields.get("status") or "draft").lower(),
            "created": fields.get("created", ""),
        }
    return found


def _git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _json(path: Path) -> dict:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue  # a torn line from a write in progress
        if isinstance(item, dict):
            found.append(item)
    return found


def _within(ts: object, start: datetime, end: datetime) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return False
    when = when.replace(tzinfo=when.tzinfo or UTC)
    return start <= when < end


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# The command


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--date",
        help="the day to write, YYYY-MM-DD or today (default: the day that just ended)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    day = None
    if args.date == "today":
        day = datetime.now().astimezone().date()
    elif args.date:
        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(
                f"journal: --date takes YYYY-MM-DD or today, not {args.date!r}"
            ) from None
    return write(vault, day)
