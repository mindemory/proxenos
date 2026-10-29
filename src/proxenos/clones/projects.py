"""Projects that keep moving: long-running pieces of the user's work (a paper, say), looked after
every night.

The projects are the user's own list, clones/projects/projects.json, which only they write:

    {"projects": [{"id": "cookbook", "name": "The cookbook",
                   "about": "the second draft for the editor: her comments, retested recipes",
                   "people": ["Ana Lee"], "terms": ["cookbook", "recipes"], "paused": false}]}

For each project that isn't paused, a run:
- gathers what the vault holds on it: what's new since the last run naming one of its terms or
  from one of its people, so nothing new is missed, then the records nearest its name, what it's
  about and each term, in meaning and in words (research._search);
- gives the model that, with who the user is in short, the project's last status and the end of
  its log, and asks where it stands now: the status (where it is, deadlines, what's done and
  what's open), what changed since the last run, the next steps (what, who, by when), what only
  the user can decide, and up to two drafts that move it on: a message to a collaborator, a plan
  for the next analysis, a checklist;
- writes clones/projects/<id>/status.md, the status now, adds a dated entry to log.md, what
  changed and the next steps, and puts the drafts in clones/drafts/ (for: project), where the
  page shows them with their actions. The project's drafts from earlier runs that the user
  hasn't touched go, so Drafts holds its newest; any they edited, approved, sent or discarded
  stay.

It only writes notes and drafts; nothing is sent.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import llm, memory, research
from proxenos.clones import work
from proxenos.config import env

HITS = 30  # records a run reads for a project
NEW_HITS = 8  # newest records kept from each term's and each person's search
NEAR_HITS = 4  # nearest records kept from each meaning-and-words search
FIRST_DAYS = 60  # what counts as new on a project's first run
STATUS_CHARS = 6000  # of the last status the model reads
LOG_CHARS = 3000  # of the end of the log
DRAFTS = 2
_PROJECT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")

_SYSTEM = """\
You look after one of {person}'s long-running projects, as their digital twin, so it keeps \
moving while they're busy or unwell. Each night you get what their messages, mail and notes \
hold on it, newest first, with where you said it stood last time. Work out where it stands \
now and what would move it forward, the way {person} would, and write for {person} to read \
in the morning.

Return:
- status: where the project stands now, in markdown: what it is, its deadlines and dates, what's \
done, what's open or waiting on whom, and any risk. Keep what still holds from last time; \
change what the records show has changed. No title: the file has one. Facts, dates and \
names only from the records or the last status; never invent any, nor spell out an \
abbreviation the records don't. Say plainly what isn't known.
- changed: what's new since the last status, in a few sentences, or "" if nothing is.
- next: the next steps, most useful first, three to six: each with who does it ({person}, or a \
collaborator by name) and by when ("" when there's no date).
- asks: what only {person} can decide or knows, as short questions.
- drafts: up to {drafts} things written for {person} that would move it on now: a message to a \
collaborator in {person}'s voice, a plan for the next analysis, a checklist, a short doc. Each \
with a title under 12 words, kind, channel ("other" when it isn't a message), to ("" when it \
isn't a message) and body, ready to use. None when nothing is worth drafting now."""


def _schema() -> dict:
    step = {
        "type": "object",
        "properties": {
            "step": {"type": "string"},
            "who": {"type": "string"},
            "by": {"type": "string"},
        },
        "required": ["step", "who", "by"],
        "additionalProperties": False,
    }
    draft = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": [k for k in work.KINDS if k != "reply"]},
            "channel": {"type": "string", "enum": list(work.CHANNELS)},
            "to": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["title", "kind", "channel", "to", "body"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "changed": {"type": "string"},
            "next": {"type": "array", "items": step},
            "asks": {"type": "array", "items": {"type": "string"}},
            "drafts": {"type": "array", "items": draft},
        },
        "required": ["status", "changed", "next", "asks", "drafts"],
        "additionalProperties": False,
    }


def projects(
    vault: Path,
    only: str | None = None,
    now: datetime | None = None,
    model: Callable[..., object] = llm.ask,
) -> dict[str, int]:
    """Each project on the list advanced in turn, or only the one with id `only`."""
    now = now or datetime.now(UTC)
    stats: Counter = Counter(projects_advanced=0, projects_failed=0, drafts_written=0)
    listed = listed_projects(vault)
    if only and not any(p["id"] == only for p in listed):
        raise SystemExit(f"projects: no project {only!r} in clones/projects/projects.json")
    for project in listed:
        if only and project["id"] != only:
            continue
        if project.get("paused"):
            stats["projects_paused"] += 1
            continue
        try:
            stats["drafts_written"] += advance(vault, project, now, model)
            stats["projects_advanced"] += 1
        except Exception as e:  # noqa: BLE001 - one project that fails must not stop the rest
            stats["projects_failed"] += 1
            reason = " ".join(str(e).split())[:200]
            print(f"projects: {project['id']} failed ({reason})", file=sys.stderr)
    return dict(stats)


def listed_projects(vault: Path) -> list[dict]:
    """The user's projects, each with an id the files can be named by and a name; none when
    there's no list yet."""
    path = vault / "clones" / "projects" / "projects.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise SystemExit(f"projects: can't read {path} ({e})") from None
    found, seen = [], set()
    for p in data.get("projects", []) if isinstance(data, dict) else []:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"].strip():
            continue
        pid = str(p.get("id") or "")
        if not _PROJECT_ID.fullmatch(pid) or pid in seen:
            continue
        seen.add(pid)
        found.append(
            {
                "id": pid,
                "name": p["name"].strip(),
                "about": str(p.get("about") or "").strip(),
                "people": _strings(p.get("people")),
                "terms": _strings(p.get("terms")),
                "paused": p.get("paused") is True,
            }
        )
    return found


def advance(vault: Path, project: dict, now: datetime, model: Callable[..., object]) -> int:
    """One project's run: its status and log brought up to date, and its drafts. The drafts
    written."""
    person = env("NAME", "the person")
    folder = vault / "clones" / "projects" / project["id"]
    status_path, log_path = folder / "status.md", folder / "log.md"
    last = _read(status_path)
    since = _last_run(log_path) or (now - timedelta(days=FIRST_DAYS))
    new, near = gather(vault, project, since)
    prompt = "\n\n".join(
        part
        for part in (
            _about(project),
            f"Where you said it stood last time:\n{last[:STATUS_CHARS]}" if last else "",
            f"The end of its log:\n{_read(log_path)[-LOG_CHARS:]}" if log_path.exists() else "",
            f"New since {since:%Y-%m-%d}:\n" + "\n".join(research._line(h, person) for h in new)
            if new
            else f"Nothing new found since {since:%Y-%m-%d}.",
            "What else the records hold on it:\n"
            + "\n".join(research._line(h, person) for h in near)
            if near
            else "",
        )
        if part
    )
    answer = model(
        prompt,
        system=_SYSTEM.format(person=person, drafts=DRAFTS) + "\n\n" + work.short_self(vault, now),
        schema=_schema(),
        effort="medium",
    )
    status = str(answer.get("status") or "").strip()
    if not status:
        raise ValueError("the model wrote no status")
    steps = [s for s in answer.get("next") or [] if isinstance(s, dict) and _text(s.get("step"))]
    asks = [_text(a) for a in answer.get("asks") or [] if _text(a)]
    work._write(status_path, _status_file(project, status, steps, asks, now))
    _append(log_path, _log_entry(_text(answer.get("changed")), steps, len(new), now))
    return _drafts(vault, project, answer.get("drafts") or [], asks, now)


def gather(vault: Path, project: dict, since: datetime) -> tuple[list[dict], list[dict]]:
    """(new, near): what's new since `since` naming a term or from one of the project's people,
    newest first, then the records nearest it in meaning and words; HITS in all, each once."""
    after = since.date().isoformat()
    new: dict[str, dict] = {}
    for term in project["terms"] or [project["name"]]:
        for h in memory.search(term, since=after, limit=NEW_HITS, match="any", vault=vault):
            new.setdefault(h["id"], h)
    for name in project["people"]:
        for h in memory.search("", who=name, since=after, limit=NEW_HITS, vault=vault):
            new.setdefault(h["id"], h)
    fresh = sorted(new.values(), key=lambda h: h["ts"], reverse=True)[: HITS // 2]
    seen = {h["id"] for h in fresh}
    near: list[dict] = []
    queries = [f"{project['name']}: {project['about']}".strip(": "), *project["terms"]]
    for query in queries:
        for h in research._search(vault, query, None)[: NEAR_HITS * 2]:
            if h["id"] not in seen:
                seen.add(h["id"])
                near.append(h)
    return fresh, near[: HITS - len(fresh)]


def _drafts(vault: Path, project: dict, drafted: list, asks: list[str], now: datetime) -> int:
    """The run's drafts in clones/drafts/, after the project's earlier ones the user hasn't
    touched are gone."""
    out = vault / "clones" / "drafts"
    ours = re.compile(rf"project-{re.escape(project['id'])}-\d{{8}}-\d")
    edited = work._latest(out / "feedback.jsonl", "draft_id", ("edit",))
    for key, (path, status) in work._existing(out).items():
        if ours.fullmatch(key) and status == "draft" and key not in edited:
            path.unlink(missing_ok=True)
    written = 0
    for i, d in enumerate([d for d in drafted if isinstance(d, dict)][:DRAFTS], start=1):
        body = str(d.get("body") or "").strip()
        if not body:
            continue
        draft_id = f"project-{project['id']}-{now:%Y%m%d}-{i}"
        message = d.get("kind") not in ("doc", "plan", "checklist", "blocked")
        work._write(
            out / f"{draft_id}.md",
            work.render(
                {
                    "id": draft_id,
                    "title": work._clip(_text(d.get("title")) or project["name"], work.TITLE_CHARS),
                    "kind": d["kind"] if d.get("kind") in work.KINDS else "doc",
                    "for": "project",
                    "channel": d["channel"] if d.get("channel") in work.CHANNELS else "other",
                    "to": _text(d.get("to")) if message else "",
                    "created": _iso(now),
                    "status": "draft",
                    "found": work._clip(
                        f"From the {project['name']} project's status.", work.FOUND_CHARS
                    ),
                    "asks": [work._clip(a, work.ASK_CHARS) for a in asks[: work.ASKS]],
                    "body": body,
                }
            ),
        )
        written += 1
    return written


def _about(project: dict) -> str:
    lines = [f"The project: {project['name']}"]
    if project["about"]:
        lines.append(f"What it is: {project['about']}")
    if project["people"]:
        lines.append(f"With: {', '.join(project['people'])}")
    return "\n".join(lines)


def _status_file(
    project: dict, status: str, steps: list[dict], asks: list[str], now: datetime
) -> str:
    lines = [f"# {project['name']}", "", f"_Where it stands, {now:%Y-%m-%d}._", "", status, ""]
    if steps:
        lines += ["## Next steps", ""] + [f"- {_step(s)}" for s in steps] + [""]
    if asks:
        lines += ["## Needs you", ""] + [f"- {a}" for a in asks] + [""]
    return "\n".join(lines)


def _log_entry(changed: str, steps: list[dict], new: int, now: datetime) -> str:
    lines = [f"## {now:%Y-%m-%d}", "", changed or "Nothing new since the last run.", ""]
    lines.append(f"{new} new records read.")
    if steps:
        lines += ["", "Next: " + "; ".join(_step(s) for s in steps[:3]) + "."]
    return "\n".join(lines) + "\n\n"


def _step(step: dict) -> str:
    extra = ", ".join(x for x in (_text(step.get("who")), _text(step.get("by"))) if x)
    return _text(step["step"]) + (f" ({extra})" if extra else "")


def _last_run(log: Path) -> datetime | None:
    """The date of the log's newest entry."""
    dates = re.findall(r"^## (\d{4}-\d{2}-\d{2})$", _read(log), flags=re.MULTILINE)
    return datetime.fromisoformat(max(dates)).replace(tzinfo=UTC) if dates else None


def _append(path: Path, text: str) -> None:
    work._write(path, _read(path) + text)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _strings(value: object) -> list[str]:
    return (
        [s.strip() for s in value if isinstance(s, str) and s.strip()]
        if isinstance(value, list)
        else []
    )


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", help="only this project, by its id")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return projects(vault, only=args.project)
