"""A project's manuscript and what changed in it: the old version, the new one and the changes
between them, for the user to read on the page and change there. Git only, no model.

The manuscript is the file "manuscript" names in clones/projects/projects.json ({"path":
"docs/paper/paper.md", "branch": "paper-storyline"}, the branch optional), else the one the
code's history says is the paper: the newest committed paper.md, manuscript.md or main.tex, or a
.tex file under a paper/ or manuscript/ folder, on any local branch, since a draft often lives on
a branch the checkout isn't on. Its versions are the commits that changed it on that branch, and
on the branches of the project's steps still waiting on the user. Two versions compare word by
word, a paragraph at a time; a step's changes compare the same way, and code line by line.

The user changes it from the page in two ways, both kept off their checkout. They ask for a
change, which queues a step that starts from the manuscript's branch (proxenos.clones.steps).
Or they edit the text, which is committed on a new branch, proxenos/<project>-edit-<when>, made
from the manuscript's branch in a worktree that's removed again, and waits on them as a step:
Accept merges it, Discard deletes it. What co-authors change in its Google Doc comes back the
same way (proxenos.paperdoc), as does what the user changes in its copy in their Drive folder
(proxenos.clones.folders), each with only the paragraphs changed there changed (`rebuild`).
Every version is read from git at its commit, so the user's checkout, its index and its working
tree are never read or touched, and nothing is pushed.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

from proxenos import agent
from proxenos.clones import projects, steps

MAX_CHARS = 400_000  # of a version compared; a longer one is shown cut, and not edited
WORD_TOKENS = 6000  # a changed stretch longer than this, in words, shows as replaced whole
VERSIONS = 200
SCANNED = 3000  # commits read looking for the manuscript
BRANCHES = 40
STEP_FILES = 40
STEP_CHARS = 1_500_000  # of all a step's files compared
PROSE = {".md", ".markdown", ".tex", ".txt"}
_NAMES = {"paper.md", "manuscript.md", "main.tex", "paper.tex", "manuscript.tex"}
_FOLDERS = {"paper", "manuscript"}
_WORDS = re.compile(r"\w+|\s+|[^\w\s]")
_BREAK = re.compile(r"(\n[ \t]*\n\s*)")  # between paragraphs
_ENDS_PARAGRAPH = re.compile(r"\n[ \t]*\n\s*\Z")
# Where an edit's text was brought back from, when not the page: as its step and commit name the
# place, and as its report names the manuscript's copy there.
BROUGHT_FROM = {
    "gdocs": ("its Google Doc", "{path}'s Google Doc"),
    "folder": ("your Drive folder", "{path}'s copy in your Drive folder"),
}
_REV = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
_FORMAT = "%x00%H%x01%ct%x01%an%x01%s"  # not whitespace, which output is stripped of


# Finding it.


def find(project: dict) -> dict | None:
    """The project's manuscript, {path, branch, named}: the one projects.json names, else the
    paper the code's history holds. None when there's none."""
    repo = steps._repo(project)
    named = project.get("manuscript") or {}
    checkout = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if named.get("path"):
        path = str(named["path"]).strip("/")
        if not steps.in_repo(path):
            raise SystemExit(f"manuscript: {named['path']!r} isn't a path in the repository")
        branch = named.get("branch") or _branch_for(repo, path, checkout)
        if not branch or not _tip(repo, branch):
            raise SystemExit(f"manuscript: no branch has {path}")
        return {"path": path, "branch": branch, "named": True}
    newest: dict[str, int] = {}
    for version in _log(repo, "--exclude=proxenos/*", "--branches", "-n", str(SCANNED)):
        for path in version["paths"]:
            if _paperish(path) and version["time"] > newest.get(path, 0):
                newest[path] = version["time"]
    for path in sorted(newest, key=lambda p: (_paperish(p), newest[p]), reverse=True)[:5]:
        if branch := _branch_for(repo, path, checkout):
            return {"path": path, "branch": branch, "named": False}
    return None


def _paperish(path: str) -> int:
    """How surely the file is the paper, from its name and folder: 0 when it isn't."""
    p = PurePosixPath(path)
    in_folder = any(part.lower() in _FOLDERS for part in p.parts[:-1])
    named = p.name.lower() in _NAMES
    return 2 * named + (in_folder and p.suffix.lower() == ".tex")


def _branch_for(repo: Path, path: str, checkout: str) -> str:
    """The local branch holding the newest version of the file, the checkout's on a tie; ""."""
    best: tuple[tuple[int, bool], str] | None = None
    for branch in _branches(repo):
        when = _git(repo, "log", "-1", "--format=%ct", f"refs/heads/{branch}", "--", path)
        if not when.isdigit() or _blob(repo, f"refs/heads/{branch}", path) is None:
            continue
        key = (int(when), branch == checkout)
        if best is None or key > best[0]:
            best = (key, branch)
    return best[1] if best else ""


def _branches(repo: Path) -> list[str]:
    """The user's local branches, newest first; not the steps'."""
    refs = _git(repo, "for-each-ref", "--sort=-committerdate", "--format=%(refname)", "refs/heads/")
    names = [r.removeprefix("refs/heads/") for r in refs.splitlines()]
    return [n for n in names if n and not n.startswith("proxenos/")][:BRANCHES]


# Its versions.


def versions(project: dict, found: dict) -> list[dict]:
    """The manuscript's versions, newest first: the commits that changed it on its branch, then
    those on the branches of the project's steps still waiting on the user (proxenos: true), a
    hand edit's among them (edit: true), each with the step's id."""
    repo = steps._repo(project)
    listed = [
        v | {"branch": found["branch"], "proxenos": False, "edit": False, "step": None}
        for v in _log(
            repo,
            "--follow",
            "-n",
            str(VERSIONS),
            f"refs/heads/{found['branch']}",
            "--",
            found["path"],
        )
    ]
    seen = {v["commit"] for v in listed}
    ours = re.compile(rf"proxenos/{re.escape(project['id'])}-(edit-)?(\d{{8}}-\d{{6}})")
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/proxenos/")
    for ref in sorted(refs.splitlines()):
        branch = ref.removeprefix("refs/heads/")
        match = ours.fullmatch(branch)
        if not match:
            continue
        only_there = [ref, "--not", "--exclude=proxenos/*", "--branches", "--", found["path"]]
        for v in _log(repo, "-n", str(VERSIONS), *only_there):
            if v["commit"] not in seen:
                seen.add(v["commit"])
                step = f"{project['id']}/{match[2]}"
                listed.append(
                    v | {"branch": branch, "proxenos": True, "edit": bool(match[1]), "step": step}
                )
    listed.sort(key=lambda v: v["time"], reverse=True)
    return [
        {k: v[k] for k in v if k not in ("time", "paths")} | {"path": _path_of(v, found)}
        for v in listed
    ]


def _path_of(version: dict, found: dict) -> str:
    """Where the manuscript was in this version: renames are followed."""
    return version["paths"][-1] if version["paths"] else found["path"]


# Its changes.


def compare(project: dict, found: dict, base: str = "", head: str = "") -> dict:
    """The manuscript at `head` and its changes since `base`. By default, the newest version on
    its branch against the one before it; a version on a step's branch against where that step
    started."""
    repo = steps._repo(project)
    listed = versions(project, found)
    own = [v for v in listed if not v["proxenos"]]
    tip = _tip(repo, found["branch"])
    head_commit = _commit(repo, head) if head else (own[0]["commit"] if own else tip)
    on_step = any(v["commit"] == head_commit and v["proxenos"] for v in listed)
    if base:
        base_commit = _commit(repo, base)
    elif on_step:
        base_commit = _git(repo, "merge-base", head_commit, tip) or head_commit
    else:
        at = next((i for i, v in enumerate(own) if v["commit"] == head_commit), None)
        base_commit = own[at + 1]["commit"] if at is not None and at + 1 < len(own) else head_commit

    def path_at(commit: str) -> str:
        return next((v["path"] for v in listed if v["commit"] == commit), found["path"])

    changes = _changes(
        _blob(repo, base_commit, path_at(base_commit)),
        _blob(repo, head_commit, path_at(head_commit)),
        found["path"],
    )
    newest = own[0]["commit"] if own else ""
    return {
        "project": project["id"],
        "manuscript": found,
        "versions": listed,
        "tip": tip,
        "base": base_commit,
        "head": head_commit,
        "editable": head_commit == newest and not changes["truncated"] and not changes["binary"],
    } | changes


def step_changes(project: dict, step: dict) -> dict:
    """Every file a step changed, from where it started to its branch: prose word by word, code
    line by line."""
    repo = steps._repo(project)
    head = _tip(repo, step.get("branch") or "") or _commit_or_none(
        repo, str(step.get("head") or "")
    )
    if not head:
        raise SystemExit(f"manuscript: {step.get('branch')} is gone, and its changes with it")
    base = str(step.get("base_commit") or "")
    raw = _git(repo, "diff", "--numstat", "--no-renames", "-z", base, head)
    paths = [line.split("\t", 2)[2] for line in raw.split("\0") if line.count("\t") >= 2]
    files, left = [], STEP_CHARS
    for path in paths[:STEP_FILES]:
        old, new = _blob(repo, base, path), _blob(repo, head, path)
        size = len(old or b"") + len(new or b"")
        if size > left:
            files.append({"path": path, **_changes(None, None, path), "truncated": True})
            continue
        left -= size
        files.append({"path": path, **_changes(old, new, path)})
    return {
        "project": project["id"],
        "step": step["id"],
        "branch": step.get("branch") or "",
        "base": step.get("base") or "",
        "files": files,
        "truncated": len(paths) > STEP_FILES,
    }


def _changes(old: bytes | None, new: bytes | None, path: str) -> dict:
    """{text, kind, unit, ops, added, removed, binary, truncated} from one version to the next."""
    prose = PurePosixPath(path).suffix.lower() in PROSE
    kind = {"kind": "prose" if prose else "code", "unit": "words" if prose else "lines"}
    none = {"text": "", "ops": [], "added": 0, "removed": 0, "binary": False, "truncated": False}
    if b"\0" in (old or b"") or b"\0" in (new or b""):
        return kind | none | {"binary": True}
    was, now = _text(old), _text(new)
    if len(was) > MAX_CHARS or len(now) > MAX_CHARS:
        text = now[:MAX_CHARS]
        return (
            kind | none | {"text": text, "ops": [{"op": "same", "text": text}], "truncated": True}
        )
    ops = diff(was, now, prose)
    added, removed = _count(ops, "add", prose), _count(ops, "del", prose)
    return kind | none | {"text": now, "ops": ops, "added": added, "removed": removed}


def diff(old: str, new: str, prose: bool = True) -> list[dict]:
    """The changes from old to new as ops, [{op: same | add | del, text}]: the same and add texts
    make new, the same and del texts make old. Prose a paragraph at a time, then word by word
    within the paragraphs that changed; code a line at a time."""
    if prose:
        a, b = _paragraphs(old), _paragraphs(new)
    else:
        a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    ops: list[tuple[str, str]] = []
    matcher = SequenceMatcher(None, a, b, autojunk=not prose)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        was, now = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag == "equal":
            ops.append(("same", was))
        elif prose and tag == "replace":
            ops += _words(was, now)
        else:
            ops += [("del", was), ("add", now)]
    return _tidy(ops)


def _paragraphs(text: str) -> list[str]:
    """The text's paragraphs, each with the blank lines after it."""
    parts = _BREAK.split(text)
    chunks = [
        parts[i] + (parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2)
    ]
    return [c for c in chunks if c]


def _words(was: str, now: str) -> list[tuple[str, str]]:
    x, y = _WORDS.findall(was), _WORDS.findall(now)
    if len(x) > WORD_TOKENS or len(y) > WORD_TOKENS:
        return [("del", was), ("add", now)]
    ops = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
        if tag == "equal":
            ops.append(("same", "".join(x[i1:i2])))
        else:
            ops += [("del", "".join(x[i1:i2])), ("add", "".join(y[j1:j2]))]
    return ops


def _tidy(ops: list[tuple[str, str]]) -> list[dict]:
    """Ops as they read best: each run of changes as what went, then what came, with a space
    between two changes read as part of them, and nothing empty."""
    ops = [(op, text) for op, text in ops if text]
    out: list[dict] = []
    gone: list[str] = []
    came: list[str] = []

    def flush() -> None:
        if gone:
            out.append({"op": "del", "text": "".join(gone)})
        if came:
            out.append({"op": "add", "text": "".join(came)})
        gone.clear()
        came.clear()

    for i, (op, text) in enumerate(ops):
        between = 0 < i < len(ops) - 1 and "same" not in (ops[i - 1][0], ops[i + 1][0])
        if op == "same" and between and not text.strip():
            gone.append(text)
            came.append(text)
        elif op == "same":
            flush()
            if out and out[-1]["op"] == "same":
                out[-1]["text"] += text
            else:
                out.append({"op": "same", "text": text})
        else:
            (gone if op == "del" else came).append(text)
    flush()
    return out


def _count(ops: list[dict], op: str, prose: bool) -> int:
    texts = [o["text"] for o in ops if o["op"] == op]
    if prose:
        return sum(len(re.findall(r"\w+", t)) for t in texts)
    return sum(t.count("\n") + (not t.endswith("\n")) for t in texts)


# Editing it by hand.


def edit(
    vault: Path, project: dict, request: dict, now: datetime | None = None, source: str = ""
) -> dict:
    """The user's own text for the manuscript, {path, branch, from, text}, committed on a new
    branch from `from` (the version they edited, on the manuscript's branch) in a worktree
    that's removed again, and saved as a step waiting on them. With a `source` (BROUGHT_FROM),
    the text is what changed in its Google Doc ("gdocs") or in its copy in the user's Drive
    folder ("folder"), and the step says so. The step."""
    now = now or datetime.now(UTC)
    if source and source not in BROUGHT_FROM:
        raise ValueError(f"manuscript: no edit comes from {source!r}")
    came = BROUGHT_FROM.get(source)
    path, branch = str(request.get("path") or ""), str(request.get("branch") or "")
    text = request.get("text")
    if not steps.in_repo(path) or not steps.BRANCH.fullmatch(branch):
        raise SystemExit("manuscript: say which file and branch")
    if branch.startswith("proxenos/"):
        raise SystemExit("manuscript: edit the manuscript's own branch, not a step's")
    if not isinstance(text, str) or len(text) > MAX_CHARS:
        raise SystemExit(f"manuscript: send the text, up to {MAX_CHARS:,} characters")
    repo = steps._repo(project)
    tip = _tip(repo, branch)
    if not tip:
        raise SystemExit(f"manuscript: there's no branch {branch}")
    start = _commit(repo, str(request.get("from") or tip))
    if start != tip and steps._git_run(repo, "merge-base", "--is-ancestor", start, tip).returncode:
        raise SystemExit(f"manuscript: {start[:7]} isn't a version on {branch}")
    old = _blob(repo, start, path)
    if old is None or b"\0" in old:
        raise SystemExit(f"manuscript: {path} isn't a text file on {branch}")
    try:
        was = old.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(f"manuscript: {path} isn't UTF-8, so it can't be edited here") from None
    new = text.replace("\r\n", "\n")
    if was.endswith("\n") and not new.endswith("\n"):
        new += "\n"
    if "\r\n" in was:
        new = new.replace("\n", "\r\n")
    if new == was:
        raise SystemExit("manuscript: the text is as it was, so there's nothing to save")

    when = f"{now:%Y%m%d-%H%M%S}"
    step_id = f"{project['id']}/{when}"
    if steps.made_folder(vault, step_id).with_suffix(".json").exists():
        raise SystemExit("manuscript: a step was made this second; save again")
    branched = f"proxenos/{project['id']}-edit-{when}"
    worktree = steps.worktrees() / project["id"] / f"edit-{when}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    steps._git(repo, "worktree", "add", "-q", "-b", branched, str(worktree), start)
    try:
        target = agent.inside(worktree, path)
        if target is None or not target.is_file():
            raise SystemExit(f"manuscript: {path} isn't a file in the repository")
        target.write_bytes(new.encode("utf-8"))
        steps._git(worktree, "add", "--", path)
        said = f"Bring in what changed in {came[0]} to {path}." if came else f"Edit {path}."
        steps._git(worktree, *steps.who(worktree), "commit", "-q", "--no-verify", "-m", said)
        files = steps._changed_files(worktree, start)
        head = steps._git(worktree, "rev-parse", "HEAD")
    except BaseException:
        steps.remove_worktree(repo, worktree)
        steps._drop_branch(repo, branched)
        raise
    steps.remove_worktree(repo, worktree)

    ops = diff(was.replace("\r\n", "\n"), new.replace("\r\n", "\n"), _is_prose(path))
    unit = "words" if _is_prose(path) else "lines"
    prose = unit == "words"
    counts = f"{_count(ops, 'add', prose)} {unit} in, {_count(ops, 'del', prose)} out"
    step = {
        "id": step_id,
        "project": project["id"],
        "kind": "edit",
        "created": steps._iso(now),
        "status": "ready",
        "asked": "",
        "repo": str(repo),
        "base": branch,
        "base_commit": start,
        "branch": branched,
        "head": head,
        "manuscript": {"path": path, "branch": branch},
        "step": f"What changed in {came[0]}, for {path}" if came else f"Your edit to {path}",
        "why": "",
        "did": f"Brought back what changed in {came[1].format(path=path)}: {counts}."
        if came
        else f"You edited {path} on the page: {counts}.",
        "found": "",
        "couldnt": "",
        "next": "",
        "made": [],
        "files": files,
        "thread": [],
    }
    steps._note(
        vault,
        step,
        "Made a branch",
        f"{branched}, from {branch} at {start[:7]}, in a worktree of its own that's gone again. "
        "Your own checkout isn't touched.",
    )
    steps._note(vault, step, "Committed", f"On {branched}: {path}.")
    steps._note(vault, step, "Waiting on you", steps.summary(step))
    return step


# Bringing back what changed in a copy of it elsewhere: its Google Doc (proxenos.paperdoc), or
# the Word file in the user's Drive folder (proxenos.clones.folders).


def rebuild(original: str, baseline: str, now: str) -> str:
    """The manuscript with only the paragraphs changed in its copy changed: `original` is its
    text, `baseline` the copy's text as first read back, before anyone changed it, `now` the
    copy's text as it is. Paragraphs that stayed keep the original's bytes; the rest are the
    copy's. When the original and the baseline don't split into as many paragraphs, the
    conversion changed the text's shape and there's no pairing to trust, so `now` whole."""
    mine = _paragraphs(original)
    was = _paragraphs(baseline)
    if len(mine) != len(was):
        return now
    came = _paragraphs(now)
    pieces: list[str] = []
    keys = [p.strip() for p in was], [p.strip() for p in came]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, *keys, autojunk=False).get_opcodes():
        pieces += mine[i1:i2] if tag == "equal" else came[j1:j2]
    return _join(pieces, original[len(original.rstrip()) :])


def _join(pieces: list[str], ending: str) -> str:
    """Paragraphs as one text: each but the last ending with a blank line, so two never run
    together where one moved, and the last ending as the manuscript did."""
    out = []
    for i, piece in enumerate(pieces):
        if i == len(pieces) - 1:
            piece = piece.rstrip() + ending
        elif not _ENDS_PARAGRAPH.search(piece):
            piece = piece.rstrip("\n") + "\n\n"
        out.append(piece)
    return "".join(out)


def pull_start(vault: Path, repo: Path, record: dict) -> str | None:
    """Where a pull from a copy starts in git: the commit its baseline's text was read from
    (the record's "from"). The last pull's step (its "step", and that step's "head"), once it's
    been decided, is let go of, and moves the start on to its head when it was accepted and
    merged. None while it still waits on the user, when there's nothing to pull onto yet."""
    if record.get("step"):
        try:
            step = steps.load(vault, record["step"])
        except SystemExit:
            step = {}
        if step.get("status") in ("ready", "working"):
            return None
        head, tip = str(record.get("head") or ""), _tip(repo, record["branch"])
        if step.get("status") == "accepted" and head and tip and _merged(repo, head, tip):
            record["from"] = head
        record |= {"step": None, "head": None}
    return record["from"]


def _merged(repo: Path, commit: str, tip: str) -> bool:
    return steps._git_run(repo, "merge-base", "--is-ancestor", commit, tip).returncode == 0


def text_at(repo: Path, commit: str, path: str) -> str:
    """The manuscript's text at that commit, with Windows line ends as \\n."""
    data = _blob(repo, commit, path) if commit else None
    if data is None or b"\0" in data:
        raise SystemExit(f"manuscript: {path} isn't a text file at {commit[:7] or 'its branch'}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(f"manuscript: {path} isn't UTF-8, so it can't be read here") from None
    if len(text) > MAX_CHARS:
        raise SystemExit(f"manuscript: {path} is too long to bring changes back to here")
    return text.replace("\r\n", "\n")


# git, read only.


def _git(repo: Path, *args: str) -> str:
    return steps._git(repo, "-c", "core.quotepath=off", *args, check=False)


def _log(repo: Path, *args: str) -> list[dict]:
    """Commits as git log lists them, each {commit, short, date, time, author, subject, paths}."""
    found = []
    for record in _git(repo, "log", f"--format={_FORMAT}", "--name-only", *args).split("\0")[1:]:
        head, _, names = record.partition("\n")
        fields = head.split("\x01")
        if len(fields) != 4 or not fields[1].isdigit():
            continue
        time = int(fields[1])
        found.append(
            {
                "commit": fields[0],
                "short": fields[0][:7],
                "date": steps._iso(datetime.fromtimestamp(time, UTC)),
                "time": time,
                "author": fields[2],
                "subject": fields[3],
                "paths": [n for n in names.splitlines() if n and not n.startswith('"')],
            }
        )
    return found


def _blob(repo: Path, rev: str, path: str) -> bytes | None:
    """The file's bytes at that version, or None when it isn't there."""
    done = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True,
        check=False,
        env=steps._git_env(),
    )
    return done.stdout if done.returncode == 0 else None


def _tip(repo: Path, branch: str) -> str:
    if not branch or not steps.BRANCH.fullmatch(branch):
        return ""
    return _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")


def _commit(repo: Path, rev: str) -> str:
    """The commit `rev` names, in full."""
    found = _commit_or_none(repo, rev)
    if not found:
        raise SystemExit(f"manuscript: there's no version {rev!r}")
    return found


def _commit_or_none(repo: Path, rev: str) -> str:
    if not _REV.fullmatch(rev or ""):
        return ""
    return _git(repo, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}")


def _text(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")


def _is_prose(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in PROSE


# The command.


def listed(vault: Path, project_id: str) -> dict:
    """The project with this id in clones/projects/projects.json."""
    project = next((p for p in projects.listed_projects(vault) if p["id"] == project_id), None)
    if project is None:
        raise SystemExit(f"manuscript: no project {project_id!r} in clones/projects/projects.json")
    return project


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", help="the project's id, as in clones/projects/projects.json")
    parser.add_argument("--base", metavar="REV", help="the older version: a commit or branch")
    parser.add_argument("--head", metavar="REV", help="the newer version: a commit or branch")
    parser.add_argument("--step", metavar="STEP_ID", help="every file this step changed instead")
    parser.add_argument(
        "--edit",
        action="store_true",
        help="save the text, read as JSON from stdin ({path, branch, from, text}), on a branch of "
        "its own, as a step waiting on you",
    )


def run(vault: Path, args: argparse.Namespace) -> dict:
    """What the page shows, as JSON: the manuscript and its changes, or a step's changes; or,
    with --edit, the step the user's edit made."""
    project = listed(vault, args.id)
    if args.edit:
        try:
            request = json.loads(sys.stdin.readline())
        except ValueError:
            raise SystemExit("manuscript: the edit isn't JSON") from None
        if not isinstance(request, dict):
            raise SystemExit("manuscript: the edit isn't an object")
        step = edit(vault, project, request)
        return {"step": step["id"], "branch": step["branch"], "summary": step["summary"]}
    if args.step:
        step = steps.load(vault, args.step)
        if step.get("project") != project["id"]:
            raise SystemExit(f"manuscript: {args.step} isn't one of {project['id']}'s steps")
        return step_changes(project, step)
    found = find(project)
    if found is None:
        return {
            "project": project["id"],
            "manuscript": None,
            "why": "No paper.md, manuscript.md or main.tex, nor a .tex under paper/ or "
            'manuscript/, on any branch. Name it in projects.json: "manuscript": {"path": '
            '"...", "branch": "..."}.',
        }
    return compare(project, found, args.base or "", args.head or "")
