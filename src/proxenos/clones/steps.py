"""Steps: a project's work done a step at a time, and brought back for the user to accept.

The projects clone says where each project stands and what's next, from the user's messages,
mail and notes. This one does the next thing. A project on clones/projects/projects.json with a
"repo", the folder of its code (a git repository on this computer), takes one step each night
when its last one has been accepted or discarded, and one more whenever the user presses "Do a
step" on the page. A step:

1. is the one the user queued on the page, oldest first, else one the runner picks from where
   the project stands (its status and next steps) and the steps before: run an analysis, fix a
   script, make a figure, draft a section as markdown;
2. gets a worktree of its own: a new branch, proxenos/<project>-<when>, from the branch the
   user's checkout is on, in a folder beside Proxenos's settings. The user's own checkout is
   never touched;
3. is done by a runner (proxenos.agent): Claude Code where it's installed, which runs the code
   in a sandbox that can't write outside the worktree, else the local model, which can only
   write;
4. ends in a commit on its branch of what it changed, its figures and tables kept in the vault,
   and a report: what it did, what it found, the files changed, what it couldn't do and what's
   next. Each is clones/projects/<id>/steps/<when>.json, with what it made in the folder beside
   it, and an account of every part of the run in its thread.

Then it waits for the user. The page's Projects view shows the report with Accept, which merges
the branch into the branch it came from in the user's checkout, and Discard, which deletes the
branch and the worktree. Nothing is pushed, and no one is contacted.
"""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from proxenos import agent, lock
from proxenos.clones import projects, work
from proxenos.config import FROM_SOURCE, REPO_ROOT, env, settings_file

STEP_ID = re.compile(r"([a-z0-9][a-z0-9-]{0,39})/(\d{8}-\d{6})")
STATUS_CHARS = 6000  # of the project's status the runner reads
EARLIER = 5  # steps before this one the runner reads
QUEUE_MAX = 20
STEP_CHARS = 2000  # of a step the user queues
MADE_FILES = 30  # of what a step made, kept with its report
MADE_BYTES = 20 * 1024 * 1024
COMMIT_BYTES = 10 * 1024 * 1024  # a file bigger than this stays out of the commit
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".svg"}
MADE = IMAGES | {".pdf", ".csv", ".tsv", ".txt", ".md", ".json", ".html"}
_JUNK = ("**/__pycache__/**", "**/*.pyc", "**/.DS_Store", "**/.ipynb_checkpoints/**")
# What a step's runner may not read: the vault, Proxenos's own settings and secrets, and keys.
_HIDDEN = ("~/.ssh", "~/.gnupg", "~/.aws", "~/Library/Keychains", "~/Library/Mail")
_HIDDEN += ("~/Library/Messages",)


class GitError(RuntimeError):
    pass


# Taking a step.


def take(
    vault: Path,
    project: dict,
    now: datetime | None = None,
    tried: list | None = None,
) -> dict:
    """One step on the project, from its worktree to its report. The step as saved."""
    now = now or datetime.now(UTC)
    repo = _repo(project)
    gate = lock.Lock(vault / "state" / f"steps-{project['id']}.lock")
    if not gate.acquire():
        raise SystemExit(f"steps: {project['id']} is taking a step already")
    try:
        _settle(vault, project["id"])
        return _take(vault, project, repo, now, tried)
    finally:
        gate.release()


def _take(vault: Path, project: dict, repo: Path, now: datetime, tried: list | None) -> dict:
    base = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if not base:
        raise SystemExit(f"steps: {_home(repo)} isn't on a branch, so nothing could merge into it")
    asked = _pop_queue(vault, project["id"])
    when = f"{now:%Y%m%d-%H%M%S}"
    step = {
        "id": f"{project['id']}/{when}",
        "project": project["id"],
        "created": _iso(now),
        "status": "working",
        "asked": asked["text"] if asked else "",
        "repo": str(repo),
        "base": base,
        "base_commit": _git(repo, "rev-parse", "HEAD"),
        "branch": f"proxenos/{project['id']}-{when}",
        "worktree": str(worktrees() / project["id"] / when),
        "thread": [],
    }
    _save(vault, step)
    try:
        _carry(vault, project, step, tried if tried is not None else agent.runners())
    except BaseException as e:  # the step says how it failed, for the page, and the run fails
        step["status"] = "failed"
        step["error"] = " ".join(str(e).split())[:300] or type(e).__name__
        if asked:
            _requeue(vault, project["id"], asked)
        kept = _tidy_failed(step)
        _note(
            vault,
            step,
            "Stopped",
            f"It failed: {step['error']}"
            + (" What you asked for is back in the queue." if asked else "")
            + (" Its worktree is kept as it was, for you to look at or discard." if kept else ""),
        )
        raise
    return step


def _carry(vault: Path, project: dict, step: dict, tried: list) -> None:
    repo, worktree = Path(step["repo"]), Path(step["worktree"])
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-q", "-b", step["branch"], str(worktree), step["base_commit"])
    _note(
        vault,
        step,
        "Made a worktree",
        f"Branch {step['branch']}, from {step['base']} at {step['base_commit'][:7]}, in "
        f"{_home(worktree)}. Your own checkout isn't touched.",
    )
    person = env("NAME", "the person")
    data = [Path(d).expanduser() for d in project["data"]]
    missing = [_home(d) for d in data if not d.is_dir()]
    if missing:
        _note(vault, step, "Missing data", f"Not on this computer: {', '.join(missing)}.")
    task = agent.Task(
        person=person,
        brief=brief(vault, project, step, person),
        folder=worktree,
        data=[d for d in data if d.is_dir()],
        hidden=hidden(vault),
        python=project["python"],
        matlab=project["matlab"],
    )
    report, reasons = None, []
    for runner in tried:
        _note(
            vault,
            step,
            f"Handed it to {runner.label}",
            f"To do: {step['asked']}"
            if step["asked"]
            else "To pick the next step from where the project stands, and do it.",
        )
        try:
            report = runner(task)
        except agent.AgentUnavailable as e:
            if _changed(worktree):
                raise
            _note(vault, step, f"{runner.label} couldn't start", str(e))
            reasons.append(str(e))
            continue
        step["runner"] = runner.name
        break
    if report is None:
        raise agent.AgentError("; ".join(reasons) or "no runner could take the step")
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    step |= {
        "step": _text(report.get("step")),
        "why": _text(report.get("why")),
        "did": str(report.get("did") or "").strip(),
        "found": str(report.get("found") or "").strip(),
        "couldnt": str(report.get("couldnt") or "").strip(),
        "next": _text(report.get("next")),
        "meta": {k: v for k, v in meta.items() if isinstance(v, int | float)},
    }
    _note(vault, step, "Done the step", step["step"])
    step["made"] = _keep_made(vault, step, report.get("figures"))
    files, left_out = _commit(worktree, _message(report.get("commit"), step["step"]))
    step["files"] = _changed_files(worktree, step["base_commit"])
    step["head"] = _git(worktree, "rev-parse", "HEAD")
    if left_out:
        step["couldnt"] = (
            step["couldnt"] + f"\n\nLeft out of the commit as too big: {', '.join(left_out)}."
        ).strip()
    _note(vault, step, "Committed" if files else "Changed no file", _committed(step, files))
    step["status"] = "ready"
    _note(vault, step, "Waiting on you", summary(step))


def brief(vault: Path, project: dict, step: dict, person: str) -> str:
    """What the runner reads: the project, its folders, the step asked for or how to pick one,
    where the project stands and the steps before."""
    lines = [f"The project: {project['name']}"]
    if project["about"]:
        lines.append(f"What it is: {project['about']}")
    if project["people"]:
        lines.append(f"With: {', '.join(project['people'])}")
    parts = ["\n".join(lines)]
    code = _home(Path(step["repo"]))
    folders = [
        f"Its code: this folder, a worktree of {code} on the branch {step['branch']}, made "
        + f"from {step['base']} at {step['base_commit'][:7]}."
    ]
    data = [Path(d).expanduser() for d in project["data"]]
    if data:
        folders.append(
            "Its data, read-only: "
            + "; ".join(_home(d) + ("" if d.is_dir() else " (not on this computer)") for d in data)
        )
    if project["notes"]:
        folders.append(f"{person}'s notes on the work: {project['notes']}")
    parts.append("\n".join(folders))
    parts.append(
        f"The step {person} asked for: {step['asked']}"
        if step["asked"]
        else f"{person} didn't ask for a step: pick the one that helps most from where the "
        "project stands and the steps before, and that you can finish here and now."
    )
    status = projects._read(vault / "clones" / "projects" / project["id"] / "status.md")
    if status:
        parts.append(
            "Where it stands, from Proxenos's notes on their messages, mail and notes (it may "
            "be out of date, or mix in another project):\n" + status[:STATUS_CHARS]
        )
    earlier = projects.steps_taken(vault, project["id"], EARLIER + 1)
    lines = []
    for s in [s for s in earlier if s.get("id") != step["id"]][:EARLIER]:
        if not _text(s.get("step")):
            continue
        line = f"- {str(s.get('created'))[:10]}, {s.get('status')}: {_text(s['step'])}"
        if _text(s.get("next")):
            line += f" Next, it said: {_text(s['next'])}"
        lines.append(line)
    if lines:
        parts.append("The steps taken before, newest first:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def hidden(vault: Path) -> list[Path]:
    """What a step's runner may not read."""
    found = [vault, settings_file(), *(Path(p).expanduser() for p in _HIDDEN)]
    if FROM_SOURCE:
        found.append(REPO_ROOT / ".env")
    return [p for p in found if p.exists()]


def worktrees() -> Path:
    """Where steps' worktrees go: PROXENOS_WORKTREES, else beside Proxenos's settings."""
    named = env("WORKTREES").strip()
    return Path(named).expanduser() if named else settings_file().parent / "worktrees"


def _keep_made(vault: Path, step: dict, figures: object) -> list[dict]:
    """What the step made for its report, moved from the worktree into the vault: its figures,
    each with its caption, then its tables and other files. [{name, caption}]."""
    out = Path(step["worktree"]) / agent.OUT
    captions = {}
    for f in figures if isinstance(figures, list) else []:
        if isinstance(f, dict) and str(f.get("file") or "").strip():
            captions.setdefault(Path(str(f["file"])).name, _text(f.get("caption")))
    files = sorted(
        (p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in MADE),
        key=lambda p: (p.name not in captions, p.suffix.lower() not in IMAGES, p.name),
    )
    folder = made_folder(vault, step["id"])
    made, size = [], 0
    for path in files[:MADE_FILES]:
        size += path.stat().st_size
        if size > MADE_BYTES:
            break
        name = _free_name(folder, path.name)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, folder / name)
        made.append({"name": name, "caption": captions.get(path.name, "")})
    shutil.rmtree(Path(step["worktree"]) / agent.OUT.parent, ignore_errors=True)
    return made


def _commit(worktree: Path, message: str) -> tuple[list[str], list[str]]:
    """Commit what the runner changed, as the user's git names them, leaving out caches and any
    file over COMMIT_BYTES. (the files committed, those left out)."""
    if not _changed(worktree):
        return [], []
    _git(worktree, "add", "-A", "--", ".", *(f":(exclude,glob){j}" for j in _JUNK))
    staged = _git(worktree, "diff", "--cached", "--name-only", "--diff-filter=AM").splitlines()
    big = [
        f
        for f in staged
        if (worktree / f).is_file() and (worktree / f).stat().st_size > COMMIT_BYTES
    ]
    for f in big:
        _git(worktree, "rm", "--cached", "-q", "--", f)
    files = _git(worktree, "diff", "--cached", "--name-only").splitlines()
    if not files:
        return [], big
    who = []
    if not _git(worktree, "config", "user.email", check=False):
        who = ["-c", f"user.name={env('NAME', 'Proxenos')}", "-c", "user.email=proxenos@localhost"]
    _git(worktree, *who, "commit", "-q", "--no-verify", "-m", message)
    return files, big


def _changed_files(worktree: Path, base: str) -> list[dict]:
    """The files the step's branch changed, with lines added and removed."""
    found = []
    for line in _git(worktree, "diff", "--numstat", f"{base}..HEAD").splitlines():
        added, removed, path = (line.split("\t", 2) + ["", "", ""])[:3]
        if path:
            found.append({"path": path, "added": _int(added), "removed": _int(removed)})
    return found


def _changed(worktree: Path) -> bool:
    """Whether anything in the worktree is changed, besides what the runner made for its report."""
    status = _git(worktree, "status", "--porcelain", "--untracked-files=all", check=False)
    return any(not line[3:].startswith(".proxenos/") for line in status.splitlines() if line)


def _tidy_failed(step: dict) -> bool:
    """After a failed step, its worktree and branch go unless the runner changed or committed
    something, which stays for the user to look at. Whether it was kept."""
    repo, worktree = Path(step["repo"]), Path(step["worktree"])
    ahead = _git(
        repo, "rev-list", "--count", f"{step['base_commit']}..{step['branch']}", check=False
    )
    if (worktree.exists() and _changed(worktree)) or ahead not in ("", "0"):
        return True
    _remove(repo, step)
    return False


def _settle(vault: Path, project_id: str) -> None:
    """A step still "working" when no one holds its project's lock ended without saying so."""
    for step in projects.steps_taken(vault, project_id, limit=10):
        if step.get("status") == "working" and STEP_ID.fullmatch(str(step.get("id"))):
            step["status"] = "failed"
            step["error"] = "It stopped before it finished."
            step.setdefault("thread", [])
            _note(vault, step, "Stopped", "It stopped before it finished.")


# Deciding: only when the user presses Accept or Discard.


def accept(vault: Path, step_id: str, now: datetime | None = None) -> dict:
    """Merge the step's branch into the branch it came from, in the user's checkout, which must
    be on that branch. The step as saved."""
    now = now or datetime.now(UTC)
    step = load(vault, step_id)
    if step.get("status") != "ready":
        raise SystemExit(f"steps: {step_id} is {step.get('status')}, not waiting on you")
    repo = Path(step["repo"])
    on = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if on != step["base"]:
        raise SystemExit(
            f"steps: your checkout of {_home(repo)} is on {on or 'no branch'}, not "
            f"{step['base']}: switch to {step['base']} first, or merge {step['branch']} yourself"
        )
    if _git(repo, "rev-list", "--count", f"{step['base_commit']}..{step['branch']}") == "0":
        detail = "It changed no file, so there was nothing to merge."
    else:
        done = _git_run(repo, "merge", "--no-edit", step["branch"])
        if done.returncode != 0:
            conflicted = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
            if conflicted:
                _git(repo, "merge", "--abort", check=False)
            why = (
                f"it conflicts with your changes to {', '.join(conflicted.splitlines())}"
                if conflicted
                else _last(done.stderr) or _last(done.stdout) or "git refused"
            )
            raise SystemExit(f"steps: couldn't merge {step['branch']} into {step['base']}: {why}")
        detail = f"Merged {step['branch']} into {step['base']}: it's at {_git(repo, 'rev-parse', '--short', 'HEAD')}."
    _remove(repo, step)
    step |= {"status": "accepted", "decided": _iso(now)}
    _note(vault, step, "You accepted it", detail + " The branch and its worktree are gone.")
    return step


def discard(vault: Path, step_id: str, now: datetime | None = None) -> dict:
    """Delete the step's branch and worktree; its report stays. The step as saved."""
    now = now or datetime.now(UTC)
    step = load(vault, step_id)
    if step.get("status") not in ("ready", "failed"):
        raise SystemExit(f"steps: {step_id} is {step.get('status')}; nothing to discard")
    _remove(Path(step["repo"]), step)
    step |= {"status": "discarded", "decided": _iso(now)}
    _note(vault, step, "You discarded it", f"{step['branch']} and its worktree are gone.")
    return step


def _remove(repo: Path, step: dict) -> None:
    """The step's worktree and branch, gone. Only those Proxenos made: the branch is named for
    the step, and the worktree is its own."""
    worktree = Path(step["worktree"])
    if worktree.exists():
        _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        if worktree.exists() and worktree.is_relative_to(worktrees()):
            shutil.rmtree(worktree, ignore_errors=True)
    _git(repo, "worktree", "prune", check=False)
    _drop_branch(repo, step["branch"])


def _drop_branch(repo: Path, branch: str) -> None:
    if branch.startswith("proxenos/") and _git(repo, "branch", "--list", branch, check=False):
        _git(repo, "branch", "-D", "-q", branch)


# The queue: steps the user asked for on the page.


def queued(vault: Path, project_id: str) -> list[dict]:
    try:
        data = json.loads(_queue_path(vault, project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("steps") if isinstance(data, dict) else None
    return [q for q in items or [] if isinstance(q, dict) and _text(q.get("text"))]


def queue(vault: Path, project_id: str, text: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    _project(vault, project_id)
    text = text.strip()
    if not text:
        raise SystemExit("steps: say what the step is")
    if len(text) > STEP_CHARS:
        raise SystemExit(f"steps: keep a step to {STEP_CHARS} characters")
    items = queued(vault, project_id)
    if len(items) >= QUEUE_MAX:
        raise SystemExit(f"steps: {project_id} has {QUEUE_MAX} steps queued already")
    item = {"id": f"q-{secrets.token_hex(6)}", "text": text, "added": _iso(now)}
    _write_queue(vault, project_id, [*items, item])
    return item


def unqueue(vault: Path, project_id: str, item_id: str) -> bool:
    items = queued(vault, project_id)
    left = [q for q in items if q.get("id") != item_id]
    _write_queue(vault, project_id, left)
    return len(left) < len(items)


def _pop_queue(vault: Path, project_id: str) -> dict | None:
    items = queued(vault, project_id)
    if not items:
        return None
    _write_queue(vault, project_id, items[1:])
    return items[0]


def _requeue(vault: Path, project_id: str, item: dict) -> None:
    items = [q for q in queued(vault, project_id) if q.get("id") != item.get("id")]
    _write_queue(vault, project_id, [item, *items])


def _queue_path(vault: Path, project_id: str) -> Path:
    return vault / "clones" / "projects" / project_id / "queue.json"


def _write_queue(vault: Path, project_id: str, items: list[dict]) -> None:
    work._write(_queue_path(vault, project_id), json.dumps({"steps": items}, indent=1))


# The thread and the files.


def summary(step: dict) -> str:
    """Where the step stands, in a sentence or two."""
    status = step.get("status")
    if status == "working":
        return "Working on it."
    if status == "failed":
        return f"It failed: {step.get('error') or 'it stopped before it finished.'}"
    files = len(step.get("files") or [])
    made = [Path(m.get("name", "")).suffix.lower() for m in step.get("made") or []]
    figures = sum(m in IMAGES for m in made)
    counts = ", ".join(
        part
        for part in (
            f"{files} file{'s' * (files != 1)} changed" if files else "no file changed",
            f"{figures} figure{'s' * (figures != 1)}" if figures else "",
            f"{len(made) - figures} other file{'s' * (len(made) - figures != 1)}"
            if len(made) > figures
            else "",
        )
        if part
    )
    if status == "ready":
        return (
            f"Ready for you: {step.get('step')} ({counts}). Accept merges it into {step['base']}."
        )
    return f"{str(status).capitalize()}: {step.get('step')} ({counts})."


def _committed(step: dict, files: list[str]) -> str:
    if not files:
        return "It changed no file in the code, so there's nothing to merge."
    shown = ", ".join(files[:8]) + (f" and {len(files) - 8} more" if len(files) > 8 else "")
    return f"On {step['branch']}: {shown}."


def _note(vault: Path, step: dict, title: str, detail: str) -> None:
    step["thread"].append({"at": _iso(datetime.now(UTC)), "title": title, "detail": detail})
    _save(vault, step)


def load(vault: Path, step_id: str) -> dict:
    match = STEP_ID.fullmatch(step_id or "")
    if not match:
        raise SystemExit(f"steps: {step_id!r} isn't a step's id")
    path = vault / "clones" / "projects" / match[1] / "steps" / f"{match[2]}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(f"steps: no step {step_id}") from None


def made_folder(vault: Path, step_id: str) -> Path:
    project_id, when = step_id.split("/")
    return vault / "clones" / "projects" / project_id / "steps" / when


def _save(vault: Path, step: dict) -> None:
    step["updated"] = _iso(datetime.now(UTC))
    step["summary"] = summary(step)
    work._write(
        made_folder(vault, step["id"]).with_suffix(".json"),
        json.dumps(step, ensure_ascii=False, indent=1),
    )


def _free_name(folder: Path, name: str) -> str:
    """The file's name, or one with a number in it when that's taken; safe as a file name."""
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "file"
    candidate, n = f"{stem}{suffix}", 1
    while (folder / candidate).exists():
        n += 1
        candidate = f"{stem}-{n}{suffix}"
    return candidate


# git.


def _git(where: Path, *args: str, check: bool = True) -> str:
    done = _git_run(where, *args)
    if check and done.returncode != 0:
        why = _last(done.stderr) or _last(done.stdout) or f"exit status {done.returncode}"
        raise GitError(f"git {' '.join(args[:2])} in {_home(where)}: {why}")
    return done.stdout.strip() if done.returncode == 0 else ""


def _git_run(where: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(where), *args],
        capture_output=True,
        text=True,
        check=False,
        env=_git_env(),
    )


def _git_env() -> dict[str, str]:
    """git's environment: it never stops to ask anything."""
    return dict(os.environ) | {"GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true"}


def _repo(project: dict) -> Path:
    """The project's code folder: the top of a git repository."""
    if not project["repo"]:
        raise SystemExit(f"steps: {project['id']} has no repo in projects.json")
    repo = Path(project["repo"]).expanduser()
    if not repo.is_dir():
        raise SystemExit(
            f"steps: {project['id']}'s repo isn't on this computer ({project['repo']})"
        )
    top = _git(repo, "rev-parse", "--show-toplevel", check=False)
    if not top or Path(top).resolve() != repo.resolve():
        raise SystemExit(f"steps: {project['repo']} isn't the top of a git repository")
    return repo.resolve()


def _project(vault: Path, project_id: str) -> dict:
    for p in projects.listed_projects(vault):
        if p["id"] == project_id:
            return p
    raise SystemExit(f"steps: no project {project_id!r} in clones/projects/projects.json")


# Small helpers.


def _message(commit: object, step: str) -> str:
    """A commit message: one plain sentence."""
    text = _text(commit) or step or "A step of the project's work"
    text = text.split(". ")[0].rstrip(".")
    return work._clip(text, 200) + "."


def _home(path: Path) -> str:
    return str(path).replace(str(Path.home()), "~", 1)


def _last(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _int(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "request",
        nargs="?",
        help='"-" reads {take}, {queue, step}, {unqueue, id}, {accept} or {discard} as JSON from '
        "stdin. With none, each project with a repo whose last step is decided takes one",
    )
    parser.add_argument("--project", help="take a step on this project now, by its id")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    if args.request == "-":
        return _answer(vault, _request(sys.stdin.readline()))
    if args.request:
        raise SystemExit('steps: give "-" and a request on stdin, or --project')
    if args.project:
        step = take(vault, _project(vault, args.project))
        print(step["summary"], file=sys.stderr)
        return {"steps_taken": 1, "files_changed": len(step.get("files") or [])}
    return night(vault)


def night(vault: Path, now: datetime | None = None, tried: list | None = None) -> dict[str, int]:
    """One step on each project with a repo that isn't paused and has no step waiting on the
    user."""
    stats: Counter = Counter(steps_taken=0, steps_failed=0, steps_waiting=0)
    for project in projects.listed_projects(vault):
        if project["paused"] or not project["repo"]:
            continue
        if any(s.get("status") == "ready" for s in projects.steps_taken(vault, project["id"], 20)):
            stats["steps_waiting"] += 1
            continue
        try:
            take(vault, project, now, tried)
            stats["steps_taken"] += 1
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one project must not stop the rest
            stats["steps_failed"] += 1
            reason = " ".join(str(e).split())[:200]
            print(f"steps: {project['id']} failed ({reason})", file=sys.stderr)
    return dict(stats)


def _answer(vault: Path, request: dict) -> dict[str, int]:
    if "take" in request:
        step = take(vault, _project(vault, request["take"]))
        return {"steps_taken": 1, "files_changed": len(step.get("files") or [])}
    if "queue" in request:
        queue(vault, request["queue"], request["step"])
        return {"steps_queued": 1}
    if "unqueue" in request:
        return {"steps_unqueued": int(unqueue(vault, request["unqueue"], request["id"]))}
    if "accept" in request:
        accept(vault, request["accept"])
        return {"steps_accepted": 1}
    discard(vault, request["discard"])
    return {"steps_discarded": 1}


def _request(line: str) -> dict:
    """The page's request, checked: {take: project}, {queue: project, step}, {unqueue: project,
    id}, {accept: step} or {discard: step}."""
    try:
        request = json.loads(line)
    except ValueError:
        raise SystemExit("steps: the request isn't JSON") from None
    if not isinstance(request, dict):
        raise SystemExit("steps: the request isn't an object")
    for key in ("take", "queue", "unqueue", "accept", "discard"):
        if key in request:
            if not isinstance(request[key], str):
                raise SystemExit(f"steps: {key} must be text")
            if key == "queue" and not isinstance(request.get("step"), str):
                raise SystemExit("steps: say what the step is")
            if key == "unqueue" and not isinstance(request.get("id"), str):
                raise SystemExit("steps: unqueue needs the queued step's id")
            return request
    raise SystemExit("steps: the request asks for nothing")
