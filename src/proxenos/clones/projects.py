"""Projects that keep moving: long-running pieces of the user's work (a paper, say), looked after
every night.

The projects are the user's own list, clones/projects/projects.json, which only they write:

    {"projects": [{"id": "cookbook", "name": "The cookbook",
                   "about": "the second draft for the editor: her comments, retested recipes",
                   "people": ["Ana Lee"], "terms": ["cookbook", "recipes"], "paused": false,
                   "repo": "~/Documents/cookbook", "data": ["~/Documents/cookbook-data"]}]}

A "group" says which part of the user's work it belongs to ("PhD", "Postdoc"), and the page
lists the projects under their groups. clones/projects/<id>/brief.md, when there is one, is
what's known around it: what others have done, the question to focus on, the first analyses.
A run reads it, with "notes", so where the project stands is told against it.

A project with a "repo", the folder of its code (a git repository on this computer), also gets
its work done, a step at a time, by the steps clone (proxenos.clones.steps), which reads its data
folders ("data") but never writes them, runs Python with "python" and MATLAB with "matlab" when
they're given, and reads "notes", what the user wants it to know about the work. Its
"manuscript", {"path": "docs/paper.md", "branch": "paper"}, names the paper the page shows with
its changes (proxenos.manuscript), which is otherwise found in the code's history. Its steps run
only when the user asked for them or approved them on the page; "autostep": true lets the night
also take one it picks from where the project stands. Its manuscript is peer-reviewed when the
user asks (proxenos.review); "autoreview": true lets the night start one once it has changed.

For each project that isn't paused, a run:
- gathers what the vault holds on it: what's new since the last run naming one of its terms or
  from one of its people, so nothing new is missed, then the records nearest its name, what it's
  about and each term, in meaning and in words (research._search);
- gives the model that, with who the user is in short, the project's last status, the end of
  its log and the steps of its work taken lately (and whether the user accepted them), and, for
  the drafts, the rules for writing as the user and their own longer writing
  as examples (proxenos.voice), and asks where it stands now: the status (where it is,
  deadlines, what's done and what's open), what changed since the last run, the next steps
  (what, who, by when), what only the user can decide, and up to two drafts that move it on: a
  message to a collaborator, a plan for the next analysis, a checklist;
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
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import dates, llm, memory, research, voice
from proxenos.clones import work
from proxenos.config import env

HITS = 30  # records a run reads for a project
NEW_HITS = 8  # newest records kept from each term's and each person's search
NEAR_HITS = 4  # nearest records kept from each meaning-and-words search
FIRST_DAYS = 60  # what counts as new on a project's first run
STATUS_CHARS = 6000  # of the last status the model reads
BRIEF_CHARS = 5000  # of the project's brief
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
abbreviation the records don't. Say plainly what isn't known. \
A date after today is still to come: whatever is on it is scheduled, never completed or done, and \
a meeting that was booked and then cancelled did not happen. Take today's date from the top of what \
you're given.
- changed: what's new since the last status, in a few sentences, or "" if nothing is.
- next: the next steps, most useful first, three to six: each with who does it and by when ("" \
when there's no date). {doer} Give {person} only what needs them: a decision, their judgment, \
their access, or a person to talk to; a collaborator by name for what's theirs.
- asks: what only {person} can decide or knows, as short questions about this project, never \
what you could find out or do yourself.

The records come from all of {person}'s life and work, so some will be about another project or \
another paper: use only what is about this one, and leave out the rest.
- drafts: up to {drafts} things written for {person} that would move it on now: a message to a \
collaborator in {person}'s voice, a plan for the next analysis, a checklist, a short doc. Each \
with a title under 12 words, kind, channel ("other" when it isn't a message), to ("" when it \
isn't a message) and body, ready to use. None when nothing is worth drafting now."""


# Who a step is for, by whether Proxenos can take steps on the project's code (proxenos.clones.steps).
_CAN_DO = (
    "Work you can do yourself on its code and data on this computer, an analysis, a figure, a "
    'fix to the code, a search of the literature, a section drafted, is "Proxenos": it is queued '
    "and done as a step on a branch of its own, for them to accept."
)
_CANT_DO = (
    "Its code isn't on this computer, so steps on it are its people's; drafting text for them "
    "is yours, in drafts."
)
PROXENOS = "proxenos"  # a step's who, when it's Proxenos's to take
QUEUED = 3  # steps of Proxenos's a run queues at most


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
                "group": str(p.get("group") or "").strip(),
                "brief": _read(vault / "clones" / "projects" / pid / "brief.md")[:BRIEF_CHARS],
                "people": _strings(p.get("people")),
                "terms": _strings(p.get("terms")),
                "paused": p.get("paused") is True,
                # False keeps it out of the folder a cloud drive syncs (clones/folders).
                "cloud": p.get("cloud") is not False,
                # Where its work is, for the steps clone (proxenos.clones.steps).
                "repo": str(p.get("repo") or "").strip(),
                "data": _strings(p.get("data")),
                "python": str(p.get("python") or "").strip(),
                "matlab": str(p.get("matlab") or "").strip(),
                "notes": str(p.get("notes") or "").strip(),
                # True lets the night take a step nobody asked for, picked from its status.
                "autostep": p.get("autostep") is True,
                # True lets the night review its manuscript once it changed (proxenos.review).
                "autoreview": p.get("autoreview") is True,
                # The paper, when the user names it (proxenos.manuscript finds it otherwise).
                "manuscript": _manuscript(p.get("manuscript")),
            }
        )
    return found


def _manuscript(value: object) -> dict | None:
    """{path, branch} from "manuscript": a path, or {"path", "branch"}; branch "" when unsaid."""
    if isinstance(value, str):
        value = {"path": value}
    if not isinstance(value, dict) or not str(value.get("path") or "").strip():
        return None
    return {"path": str(value["path"]).strip(), "branch": str(value.get("branch") or "").strip()}


def steps_taken(vault: Path, project_id: str, limit: int = 5) -> list[dict]:
    """The steps the steps clone took on the project, newest first."""
    found = []
    folder = vault / "clones" / "projects" / project_id / "steps"
    for path in sorted(folder.glob("*.json"), reverse=True)[:limit]:
        try:
            step = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(step, dict):
            found.append(step)
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
            dates.today(now),
            _about(project),
            f"Where you said it stood last time:\n{last[:STATUS_CHARS]}" if last else "",
            f"The end of its log:\n{_read(log_path)[-LOG_CHARS:]}" if log_path.exists() else "",
            _work_done(vault, project["id"]),
            _code(project, since),
            f"New since {since:%Y-%m-%d}:\n" + "\n".join(research._line(h, person) for h in new)
            if new
            else f"Nothing new found since {since:%Y-%m-%d}.",
            "What else the records hold on it:\n"
            + "\n".join(research._line(h, person) for h in near)
            if near
            else "",
            voice.examples(voice.Writing(vault), "other"),  # how the drafts should read
        )
        if part
    )
    doer = _CAN_DO if project["repo"] else _CANT_DO
    system = _SYSTEM.format(person=person, drafts=DRAFTS, doer=doer) + "\n\n" + voice.rules(person)
    answer = model(
        prompt,
        system=system + "\n\n" + work.short_self(vault, now),
        schema=_schema(),
        effort="medium",
    )
    status = str(answer.get("status") or "").strip()
    if not status:
        raise ValueError("the model wrote no status")
    status, fixed = dates.scheduled(status, now)
    for line in fixed:
        print(f"projects: {project['id']}: {line}", file=sys.stderr)
    steps = [s for s in answer.get("next") or [] if isinstance(s, dict) and _text(s.get("step"))]
    asks = [_text(a) for a in answer.get("asks") or [] if _text(a)]
    if project["repo"]:
        _queue_own(vault, project, steps, now)
    work._write(status_path, _status_file(project, status, steps, asks, now))
    _append(log_path, _log_entry(_text(answer.get("changed")), steps, len(new), now))
    return _drafts(vault, project, answer.get("drafts") or [], asks, now)


def _queue_own(vault: Path, project: dict, steps: list[dict], now: datetime) -> None:
    """The next steps that are Proxenos's to take, queued for the steps clone (up to QUEUED a
    run, none twice), each marked so the status says it's queued. They come from the status,
    which comes from others' messages, so each waits for the user to approve it on the page,
    and no more than QUEUED wait at once, so the user's own always fit in the queue."""
    from proxenos.clones import steps as taken  # steps imports this module

    queued = taken.queued(vault, project["id"])
    waiting = {_text(q.get("text")).casefold() for q in queued}
    added = sum(1 for q in queued if q.get("by") == "proxenos" and q.get("approved") is not True)
    for step in steps:
        if _text(step.get("who")).casefold() != PROXENOS:
            continue
        text = _text(step["step"])
        if text.casefold() in waiting:
            step["who"] = "Proxenos, queued"
            continue
        if added >= QUEUED:
            continue
        try:
            taken.queue(vault, project["id"], text, now, by="proxenos")
        except SystemExit:  # the queue is full: it waits for the next run
            return
        waiting.add(text.casefold())
        step["who"] = "Proxenos, queued"
        added += 1


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
        body, checked = work.vet(body, now, draft_id)
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
                    "asks": [work._clip(a, work.ASK_CHARS) for a in [*checked, *asks[: work.ASKS]]],
                    "body": body,
                }
            ),
        )
        written += 1
    return written


_STEP_STATES = {
    "ready": "waiting for the user to accept it",
    "accepted": "accepted by the user",
    "discarded": "discarded by the user",
    "failed": "failed",
}


def _work_done(vault: Path, project_id: str) -> str:
    """The steps of its work Proxenos took lately, and what the user made of each."""
    lines = []
    for s in steps_taken(vault, project_id):
        if s.get("status") not in _STEP_STATES or not _text(s.get("step")):
            continue
        line = f"- {str(s.get('created'))[:10]}, {_STEP_STATES[s['status']]}: {_text(s['step'])}"
        if s["status"] != "failed" and _text(s.get("found")):
            line += f" It found: {_text(s['found'])[:400]}"
        lines.append(line)
    return "Work Proxenos did on it lately:\n" + "\n".join(lines) if lines else ""


def _code(project: dict, since: datetime) -> str:
    """What happened in the project's code since `since`, on any branch: the commits, the branch
    the user's checkout is on, and the documents changed (a draft on a branch the checkout isn't
    on is easy to lose), so the status says where the work is. "" without a repo."""
    named = str(project.get("repo") or "").strip()
    repo = Path(named).expanduser()
    # "" would be the folder this runs in, and its code isn't the project's.
    if not named or not (repo / ".git").exists():
        return ""

    def git(*args: str) -> str:
        try:
            done = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    # The exact moment, with its offset: git reads a bare date as that day at the current time of
    # day, local, which in an evening west of UTC leaves almost no window at all.
    after = f"--since={since.astimezone(UTC):%Y-%m-%d %H:%M:%S} +0000"
    commits = git("log", "--all", after, "--format=%h %ad %D | %s", "--date=short", "-n", "30")
    if not commits:
        return ""
    files = git("log", "--all", after, "--name-only", "--format=", "-n", "30").splitlines()
    papers = sorted({f for f in files if f.lower().endswith((".md", ".docx", ".tex"))})
    branch = git("branch", "--show-current") or "(no branch)"
    lines = [
        f"Its code ({repo}), checked out on {branch}. Commits since {since:%Y-%m-%d}, newest first:"
    ]
    lines.append(commits)
    if papers:
        lines.append(
            "Documents changed in them (say which branch holds each draft): "
            + ", ".join(papers[:20])
        )
    return "\n".join(lines)


def _about(project: dict) -> str:
    lines = [f"The project: {project['name']}"]
    if project["about"]:
        lines.append(f"What it is: {project['about']}")
    if project.get("group"):
        lines.append(f"Part of: {project['group']}")
    if project["people"]:
        lines.append(f"With: {', '.join(project['people'])}")
    if project.get("notes"):
        lines.append(f"What the user wants known about it: {project['notes']}")
    if project.get("brief"):
        lines.append(
            f"\nWhat's known around it, the question and first analyses:\n{project['brief']}"
        )
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
