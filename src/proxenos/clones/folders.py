"""Each project's manuscript and notes as Word files, in a folder your cloud drive syncs.

A folder in a cloud drive the user already syncs on this computer (Google Drive for desktop,
Dropbox, OneDrive, iCloud Drive: any folder), so they can read, edit, comment on and share a
project's manuscript and Proxenos's notes on it in Word or Google Docs, as they already work,
with git still the source of truth.

PROXENOS_PROJECT_FOLDER names the folder (~ allowed); unset, nothing is done. Each night, after
the projects and steps clones, each project on clones/projects/projects.json gets
<folder>/<its group, or Other>/<its name>/, the names made safe for every OS, holding Word files
pandoc makes (PROXENOS_PANDOC, else the one on the PATH):
- "<name> - manuscript.docx": the manuscript (proxenos.manuscript.find) at its branch's tip,
  read from git, never the user's checkout, with the files beside it that it includes and shows.
  Markdown converts as it is. LaTeX converts with its citations and references written out from
  the .bib files beside it, so it goes one way: its changes never come back. A PDF of the same
  name committed beside it comes too.
- "Where it stands", "What's known, and the question", "Drafts" and "About this project": the
  project's status.md and brief.md, its drafts still open, and what projects.json says of it.
- "About this folder": when the manuscript was made, from which branch and commit, and what
  comes back and what doesn't.
A paused project gets one only when it has something to show, and one marked "cloud": false on
the list (an immigration petition, say) never gets one: what it had there is left as it was.

Nothing the user does there is lost. For each file written, clones/folders/state.json keeps the
SHA-256 of what it was made from and of the bytes written. A note whose source changed is
written again only while its file is still exactly what Proxenos wrote; one the user edited or
commented on stays as they left it. A manuscript the user changed is brought back first: a
Markdown one is converted back to Markdown and rebuilt with its Google Doc's paragraph merge
(manuscript.rebuild), against the Markdown of the .docx Proxenos wrote, kept when it was written
(clones/folders/<id>/baseline.md), so only the paragraphs changed there change in git. That
waits on the user as a step from the commit the copy was made from (manuscript.edit): Accept
merges it, Discard deletes it. While it waits, newer changes wait in the copy, which is left as
it is. Then, once git's branch has moved on, the newer version is written, after the user's copy
moves to Earlier/ with the date, so their changes and comments stay.

Proxenos reads nothing else in the folder and shares nothing: the drive uploads what's there,
and who sees it is the user's choice. No model is used.
"""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from proxenos import manuscript
from proxenos.clones import projects, steps, work
from proxenos.config import env

STATUS = "Where it stands.docx"
BRIEF = "What's known, and the question.docx"
DRAFTS = "Drafts.docx"
PROJECT = "About this project.docx"
FOLDER = "About this folder.docx"
EARLIER = "Earlier"  # where the user's copies of older versions go
OTHER = "Other"  # the group of a project with none
NAME_CHARS = 60  # of a group's or project's name, so paths stay short enough for Windows
PAPER_FILES = 200  # beside the manuscript, written out of git with it
PAPER_BYTES = 100 * 1024 * 1024
# What pandoc reads beside a manuscript: what it includes, cites and shows.
PAPER = {".md", ".markdown", ".txt", ".tex", ".bib", ".sty", ".cls", ".bst"}
PAPER |= {".png", ".jpg", ".jpeg", ".gif", ".svg"}
KINDS = {".md": "markdown", ".markdown": "markdown", ".txt": "markdown", ".tex": "latex"}
BASELINE = "baseline.md"
PANDOC_SECONDS = 300
NO_PANDOC = (
    "pandoc makes the Word files, and it isn't installed: `brew install pandoc` on a Mac, else "
    "pandoc.org/installing (or set PROXENOS_PANDOC to where it is)"
)
_PANDOC_PLACES = ("/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{n}" for d in ("COM", "LPT") for n in range(10)}
_ESCAPED_CITE = re.compile(r"\\\[(-?@[^\]\n]*?)\\\]")  # [@key] as pandoc reads it from Word


class ConvertError(Exception):
    """pandoc, or git writing the manuscript out, couldn't make a file."""


def folders(
    vault: Path, only: str | None = None, pull_only: bool = False, now: datetime | None = None
) -> dict[str, int]:
    """Each project's folder brought up to date, or only the one with id `only`; with
    `pull_only`, only the user's changes to the manuscripts brought back."""
    now = now or datetime.now(UTC)
    named = env("PROJECT_FOLDER").strip()
    if not named:
        print(
            "folders: PROXENOS_PROJECT_FOLDER isn't set, so there's nothing to do. Set it, in "
            "Settings, to a folder your cloud drive syncs.",
            file=sys.stderr,
        )
        return {"folder_not_set": 1}
    root = Path(named).expanduser().resolve()
    if not root.is_dir():
        print(
            f"folders: {named} isn't a folder on this computer; nothing written.", file=sys.stderr
        )
        return {"folder_missing": 1}
    if pandoc() is None:
        print(f"folders: {NO_PANDOC}. Nothing written.", file=sys.stderr)
        return {"pandoc_missing": 1}
    listed = projects.listed_projects(vault)
    if only and not any(p["id"] == only for p in listed):
        raise SystemExit(f"folders: no project {only!r} in clones/projects/projects.json")
    stats: Counter = Counter(
        folders_written=0,
        files_written=0,
        kept_as_edited=0,
        manuscripts_brought_back=0,
        steps_made=0,
        skipped=0,
        kept_out=0,
    )
    state = _state(vault, root)
    places = _places(listed)
    for project in listed:
        if only and project["id"] != only:
            continue
        if not project["cloud"]:
            stats["kept_out"] += 1
            continue
        record = state["projects"].setdefault(project["id"], {})
        if record.get("folder") != places[project["id"]]:
            # A new place: what was written in the old one stays there, untouched.
            record |= {"folder": places[project["id"]], "files": {}}
        try:
            stats.update(refresh(vault, root, project, record, now, pull_only))
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one project must not stop the rest
            stats["failed"] += 1
            reason = " ".join(str(e).split())[:200]
            print(f"folders: {project['id']} failed ({reason})", file=sys.stderr)
        finally:
            _keep_state(vault, state)  # what was written is known, even when the rest failed
    return dict(stats)


def refresh(
    vault: Path, root: Path, project: dict, record: dict, now: datetime, pull_only: bool = False
) -> Counter:
    """One project's folder: the user's changes to its manuscript brought back first, then what
    changed written, never over what the user changed. Its counts."""
    stats: Counter = Counter()
    where = root.joinpath(*record["folder"].split("/"))
    files = record.setdefault("files", {})
    kept = vault / "clones" / "projects" / project["id"]
    status = projects._read(kept / "status.md").strip()
    brief = projects._read(kept / "brief.md").strip()
    drafts = _drafts(vault, project["id"])
    paper = _paper(project)
    if project["paused"] and not (status or brief or drafts or paper or files):
        stats["skipped"] += 1
        return stats
    docx = f"{where.name} - manuscript.docx"
    try:
        how = _bring_back(vault, project, where / docx, record, now, stats)
    except (ConvertError, SystemExit, steps.GitError) as e:
        how = "held"
        stats["skipped"] += 1
        reason = " ".join(str(e).split())[:200]
        print(
            f"folders: what changed in {project['id']}'s manuscript wasn't brought back "
            f"({reason}); its copy stays as it is",
            file=sys.stderr,
        )
    if pull_only:
        return stats

    if paper:
        try:
            _write_paper(vault, project, where, record, paper, how, now, stats)
        except ConvertError as e:
            stats["skipped"] += 1
            print(f"folders: {project['id']}'s manuscript wasn't made ({e})", file=sys.stderr)
    notes = {
        STATUS: status or None,
        BRIEF: brief or None,
        DRAFTS: _drafts_note(project, drafts, DRAFTS in files),
        PROJECT: _about_project(project),
        FOLDER: _about_folder(project, docx, files.get(docx)),
    }
    for name, text in notes.items():
        if text is not None:
            _write_note(where / name, files, text, now, stats)
    if stats["files_written"]:
        stats["folders_written"] += 1
    return stats


# The manuscript.


def _paper(project: dict) -> dict | None:
    """The manuscript, {repo, path, branch, tip, kind}, when the project has one this can
    convert; None when it has none, or its code isn't on this computer."""
    if not project["repo"]:
        return None
    try:
        found = manuscript.find(project)
    except SystemExit as e:
        print(f"folders: {project['id']}: {e}; its manuscript is left as it was", file=sys.stderr)
        return None
    if found is None:
        return None
    kind = KINDS.get(PurePosixPath(found["path"]).suffix.lower())
    if kind is None:
        print(
            f"folders: {found['path']} isn't Markdown or LaTeX, so it isn't copied", file=sys.stderr
        )
        return None
    repo = steps._repo(project)
    return found | {"repo": repo, "tip": manuscript._tip(repo, found["branch"]), "kind": kind}


def _bring_back(
    vault: Path, project: dict, target: Path, record: dict, now: datetime, stats: Counter
) -> str:
    """The user's changes to the manuscript's copy, brought back as a step waiting on them. How
    it stands: "none" (nothing new in it), "one-way" (LaTeX, or nothing to bring it back
    against), "waiting" (the step brought back last time still waits, so this waits too) or
    "back". refresh makes it "held" when bringing it back failed."""
    entry = record["files"].get(target.name)
    digest = _sha(target)
    if entry is None or digest is None or digest in (entry.get("written"), entry.get("seen")):
        return "none"
    pull, baseline = record.get("pull"), _read(_kept(vault, project["id"]) / BASELINE)
    if entry.get("kind") != "markdown" or not pull or baseline is None:
        return "one-way"
    repo = steps._repo(project)
    start = manuscript.pull_start(vault, repo, pull)
    if start is None:
        stats["waiting_on_you"] += 1
        return "waiting"
    now_text = to_markdown(target)
    stats["manuscripts_brought_back"] += 1
    original = manuscript.text_at(repo, start, pull["path"])
    text = manuscript.rebuild(original, baseline, now_text) if now_text != baseline else original
    if original.endswith("\n") and not text.endswith("\n"):
        text += "\n"  # as an edit would end it
    if text != original:
        request = {"path": pull["path"], "branch": pull["branch"], "from": start, "text": text}
        step = manuscript.edit(vault, project, request, now, source="folder")
        _save(vault, BASELINE, now_text, project["id"])
        pull |= {"step": step["id"], "head": step["head"]}
        stats["steps_made"] += 1
    entry["seen"] = digest  # brought back: its changes aren't new any more
    return "back"


def _write_paper(
    vault: Path,
    project: dict,
    where: Path,
    record: dict,
    paper: dict,
    how: str,
    now: datetime,
    stats: Counter,
) -> None:
    """The manuscript at its branch's tip as a Word file, and its PDF beside it, when either
    changed in git. The user's copy of an older version moves to Earlier/ first, unless it
    holds changes still to come back (`how`, from _bring_back): then it stays as it is."""
    files = record["files"]
    repo, tip, path, kind = paper["repo"], paper["tip"], paper["path"], paper["kind"]
    target = where / f"{where.name} - manuscript.docx"
    listed = _paper_files(repo, tip, path)
    source = _digest(kind, path, *(" ".join(f) for f in listed))
    found = _found(target, files.get(target.name), source)
    if found == "theirs" and how in ("waiting", "held"):
        stats["kept_as_edited"] += 1
    elif found != "same":
        with tempfile.TemporaryDirectory() as tmp:
            made, out = Path(tmp) / "made.docx", Path(tmp) / "paper"
            _write_out(repo, tip, listed, out)
            to_docx(out.joinpath(*path.split("/")), made, kind)
            baseline = to_markdown(made) if kind == "markdown" else None
            if found == "theirs":
                _set_aside(target, now)
                stats["moved_to_earlier"] += 1
            files[target.name] = {
                "source": source,
                "written": _put(made.read_bytes(), target),
                "at": steps._iso(now),
                "path": path,
                "branch": paper["branch"],
                "commit": tip,
                "kind": kind,
            }
        stats["files_written"] += 1
        if baseline is None:
            record.pop("pull", None)  # LaTeX goes one way
        else:
            _save(vault, BASELINE, baseline, project["id"])
            waiting = (record.get("pull") or {}).get("step")  # a step brought back still counts
            record["pull"] = {
                "from": tip,
                "path": path,
                "branch": paper["branch"],
                "step": waiting,
                "head": None,
            }

    pdf = str(PurePosixPath(path).with_suffix(".pdf"))
    blob = manuscript._git(repo, "rev-parse", "-q", "--verify", f"{tip}:{pdf}")
    if not blob:
        return
    target = target.with_suffix(".pdf")
    source = _digest("pdf", pdf, blob)
    found = _found(target, files.get(target.name), source)
    if found == "same":
        return
    data = manuscript._blob(repo, tip, pdf)
    if data is None:
        return
    if found == "theirs":
        _set_aside(target, now)
        stats["moved_to_earlier"] += 1
    files[target.name] = {"source": source, "written": _put(data, target), "at": steps._iso(now)}
    stats["files_written"] += 1


def _paper_files(repo: Path, tip: str, path: str) -> list[tuple[str, str]]:
    """The manuscript and the files beside it pandoc may read (what it includes, cites and
    shows), as (path, blob id) at `tip`: the manuscript first, then at most PAPER_FILES others,
    PAPER_BYTES in all."""
    folder = str(PurePosixPath(path).parent)
    under = [] if folder == "." else [f"{folder}/"]
    listed = manuscript._git(
        repo, "--literal-pathspecs", "ls-tree", "-r", "-l", "-z", tip, "--", *under
    )
    first, rest, total = None, [], 0
    for line in listed.split("\0"):
        meta, _, name = line.partition("\t")
        fields = meta.split()
        if len(fields) != 4 or fields[:2] == ["120000", "blob"] or fields[1] != "blob":
            continue  # not a file: a link, a folder or a submodule
        size = int(fields[3]) if fields[3].isdigit() else PAPER_BYTES
        if name == path:
            first = (name, fields[2])
            continue
        fits = len(rest) < PAPER_FILES and total + size <= PAPER_BYTES
        if fits and PurePosixPath(name).suffix.lower() in PAPER:
            rest.append((name, fields[2]))
            total += size
    if first is None:
        raise ConvertError(f"{path} isn't on its branch")
    return [first, *rest]


def _write_out(repo: Path, tip: str, listed: list[tuple[str, str]], into: Path) -> None:
    """Those files as they are at `tip`, written under `into` by git archive: never the user's
    checkout."""
    done = subprocess.run(
        ["git", "-C", str(repo), "--literal-pathspecs", "archive", "--format=tar", tip, "--"]
        + [name for name, _ in listed],
        capture_output=True,
        check=False,
        env=steps._git_env(),
    )
    if done.returncode:
        why = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise ConvertError(f"git archive: {why[-1] if why else done.returncode}")
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        tar.extractall(into, filter="data")


def _set_aside(target: Path, now: datetime) -> Path:
    """The user's copy of an older version, moved to Earlier/ beside it with the date, so their
    changes and comments stay."""
    earlier = target.parent / EARLIER
    earlier.mkdir(exist_ok=True)
    day = f"{now:%Y-%m-%d}"
    moved, n = earlier / f"{target.stem} {day}{target.suffix}", 1
    while moved.exists():
        n += 1
        moved = earlier / f"{target.stem} {day} ({n}){target.suffix}"
    os.replace(target, moved)
    return moved


# The notes.


def _write_note(target: Path, files: dict, text: str, now: datetime, stats: Counter) -> None:
    """One of Proxenos's notes as a Word file, written again when what it comes from changed,
    unless the user changed it: then it stays as they left it."""
    source = _digest(text)
    found = _found(target, files.get(target.name), source)
    if found == "theirs":
        stats["kept_as_edited"] += 1
    if found != "stale":
        return
    with tempfile.TemporaryDirectory() as tmp:
        note, made = Path(tmp) / "note.md", Path(tmp) / "note.docx"
        note.write_text(text, encoding="utf-8")
        to_docx(note, made, "markdown")
        files[target.name] = {
            "source": source,
            "written": _put(made.read_bytes(), target),
            "at": steps._iso(now),
        }
    stats["files_written"] += 1


def _drafts(vault: Path, project_id: str) -> list[tuple[str, str]]:
    """The project's drafts still open (a draft, or approved and not yet sent), oldest first, as
    (title, body)."""
    ours = re.compile(rf"project-{re.escape(project_id)}-\d{{8}}-\d")
    found = []
    for key, (path, status) in sorted(work._existing(vault / "clones" / "drafts").items()):
        if not ours.fullmatch(key) or status not in ("draft", "approved"):
            continue
        try:
            text = path.read_text(encoding="utf-8").removeprefix("﻿")
        except (OSError, UnicodeDecodeError):
            continue
        front = work._FRONT.match(text)
        title = (work._front(text) or {}).get("title") or key
        found.append((title, text[front.end() :].strip() if front else text.strip()))
    return found


def _drafts_note(project: dict, drafts: list[tuple[str, str]], had: bool) -> str | None:
    """The drafts as one note; one saying there are none once there were some, else None."""
    if not drafts and not had:
        return None
    lines = [f"# Drafts for {project['name']}", ""]
    if not drafts:
        return "\n".join([*lines, "None are open now.", ""])
    lines += ["Proxenos's drafts for it still open: send, change or discard them on the page.", ""]
    for title, body in drafts:
        lines += [f"## {title}", "", body, ""]
    return "\n".join(lines)


def _about_project(project: dict) -> str:
    lines = [f"# {project['name']}", ""]
    if project["about"]:
        lines += [project["about"], ""]
    if project["group"]:
        lines += [f"**Part of:** {project['group']}", ""]
    if project["people"]:
        lines += [f"**With:** {', '.join(project['people'])}", ""]
    if project["notes"]:
        lines += [f"**What you want known about it:** {project['notes']}", ""]
    if project["paused"]:
        lines += ["**Paused:** the night doesn't look after it until you take it up again.", ""]
    lines.append(
        "_From your list of projects in the vault (clones/projects/projects.json). Change it "
        "there: this copy isn't read back._"
    )
    return "\n".join(lines) + "\n"


# What About this folder says, besides where the manuscript came from.
_NO_PAPER = (
    "There's no manuscript here: Proxenos found none in the project's git (a paper.md, "
    "manuscript.md or main.tex, or the one projects.json names)."
)
_NO_REPO = (
    "There's no manuscript here: the project has no code folder (repo) in projects.json to find "
    "one in."
)
_COMES_BACK = (
    "Change it here, in Word or Google Docs, and comment as you like. Each night what you changed "
    "comes back to the project's git as a step on a branch of its own, from the version it was "
    "made from, for you to accept or discard on the page: only the paragraphs you changed change, "
    "and the rest keeps its Markdown to the byte. Tracked changes count as accepted, and comments "
    "stay here, in the file. In Google Docs, edit the .docx itself: a copy saved as a Google Doc "
    "isn't read. While what came back last time waits on you, newer changes wait here."
)
_ONE_WAY = (
    "It's made from the LaTeX, with its citations and references written out as text, so it goes "
    "one way: what you change here doesn't come back. Change {path} itself, and keep your "
    "comments here to work from."
)
_MOVES_ON = (
    "When the paper moves on in git, a newer copy takes this one's place. If you'd changed this "
    f"one, it moves to {EARLIER}/ first, with the date, so your changes and comments stay."
)
_THE_NOTES = (
    "Where it stands, What's known and the question, Drafts and the two About files are "
    "Proxenos's own, written again when what they come from changes. Change one and it's left as "
    "you made it (delete it to have Proxenos's again); none of them comes back."
)
_NOTHING_ELSE = (
    "Proxenos reads nothing else in this folder and shares nothing: who sees it is up to you and "
    "your drive."
)


def _about_folder(project: dict, docx: str, made: dict | None) -> str:
    """What the folder is, when its manuscript was made and from where, and what comes back."""
    keeps = (
        f"Proxenos keeps this folder for {project['name']}, from your vault and the project's "
        "git, and brings it up to date each night. Git stays the source of truth."
    )
    paper = [_NO_PAPER if project["repo"] else _NO_REPO]
    if made:
        at = f"{made['path']} at {made['commit'][:7]} on {made['branch']}"
        paper = [
            f"**{docx}** is {at}, made {made['at'][:10]}.",
            _COMES_BACK if made["kind"] == "markdown" else _ONE_WAY.format(path=made["path"]),
            _MOVES_ON,
        ]
    parts = ["# About this folder", keeps, "## The manuscript", *paper]
    return "\n\n".join([*parts, "## The notes", _THE_NOTES, _NOTHING_ELSE]) + "\n"


# Converting, by pandoc: the two functions tests replace.


def to_docx(source: Path, out: Path, kind: str) -> None:
    """`source`, Markdown or LaTeX (`kind`), as a Word file at `out`, by pandoc run in its
    folder, so what it includes and shows is found. LaTeX's citations and references are written
    out from the .bib files beside it and those it names."""
    args = ["-f", kind, "-t", "docx", "-o", str(out)]
    if kind == "latex":
        args.append("--citeproc")
        for bib in sorted(source.parent.glob("*.bib")):
            args += ["--bibliography", bib.name]
    _pandoc(*args, source.name, cwd=source.parent)


def to_markdown(docx: Path) -> str:
    """A Word file as Markdown, by pandoc: tracked changes accepted, comments left out, the
    title and authors as the front matter they came from, each paragraph on one line, tables as
    pipe tables (no blank lines inside to split them into paragraphs), and citations, which
    pandoc escapes when it reads them as Word's text, as citations again."""
    text = _pandoc(
        "-f",
        "docx",
        "-t",
        "markdown-simple_tables-multiline_tables-grid_tables",
        "--standalone",
        "--wrap=none",
        "--track-changes=accept",
        docx.name,
        cwd=docx.parent,
    )
    return _ESCAPED_CITE.sub(r"[\1]", text.replace("\\@", "@"))


def pandoc() -> str | None:
    """pandoc's command: PROXENOS_PANDOC, else the one on the PATH or where Homebrew puts it."""
    for place in (env("PANDOC"), shutil.which("pandoc"), *_PANDOC_PLACES):
        if place and os.access(path := os.path.expanduser(place), os.X_OK):
            return path
    return None


def _pandoc(*args: str, cwd: Path) -> str:
    command = pandoc()
    if command is None:
        raise ConvertError(NO_PANDOC)
    try:
        done = subprocess.run(
            [command, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=PANDOC_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ConvertError(f"pandoc didn't run: {e}") from None
    if done.returncode:
        said = [line for line in done.stderr.splitlines() if line.strip()]
        raise ConvertError(f"pandoc: {said[-1][:300] if said else done.returncode}")
    return done.stdout


# What's kept.


def _found(target: Path, entry: dict | None, source: str) -> str:
    """How a file in the folder stands against what it'd be made from now: "same" (made from
    this, whether as Proxenos wrote it or as the user changed it), "stale" (not there, or as
    Proxenos wrote it from something older) or "theirs" (changed by the user since Proxenos
    wrote it from something older, or not written by Proxenos at all)."""
    digest = _sha(target)
    if digest is None:
        return "stale"
    if entry and entry.get("source") == source:
        return "same"
    return "stale" if entry and digest == entry.get("written") else "theirs"


def _put(data: bytes, target: Path) -> str:
    """Swapped in whole, so the drive never uploads half of it. The SHA-256 of what was
    written."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return hashlib.sha256(data).hexdigest()


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _places(listed: list[dict]) -> dict[str, str]:
    """Each project's folder under the chosen one, "<group>/<name>", by its id: a second project
    of the same name in a group gets its id after the name."""
    taken: set[tuple[str, str]] = set()
    places = {}
    for project in listed:
        group = safe_name(project["group"], OTHER)
        name = safe_name(project["name"], project["id"])
        if (group.casefold(), name.casefold()) in taken:
            name = f"{name} ({project['id']})"
        taken.add((group.casefold(), name.casefold()))
        places[project["id"]] = f"{group}/{name}"
    return places


def safe_name(name: str, fallback: str) -> str:
    """A file or folder name every OS and drive takes: none of / \\ : * ? " < > | nor control
    characters, no dot or space at either end, at most NAME_CHARS long, and not one Windows
    reserves (CON, NUL, COM1, ...); `fallback` when nothing's left."""
    name = " ".join(_UNSAFE.sub(" ", name).split())[:NAME_CHARS].strip(" .")
    if not name or name.split(".")[0].strip().upper() in _RESERVED:
        return fallback
    return name


def _state(vault: Path, root: Path) -> dict:
    """What was written where, as kept. Another folder than last time starts afresh: only a
    step brought back that may still wait on the user carries over."""
    state = work._load_json(_kept(vault) / "state.json")
    kept = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    kept = {pid: r for pid, r in kept.items() if isinstance(r, dict)}
    if state.get("root") != str(root):
        kept = {pid: {"pull": r["pull"]} for pid, r in kept.items() if r.get("pull")}
    return {"root": str(root), "projects": kept}


def _keep_state(vault: Path, state: dict) -> None:
    _save(vault, "state.json", json.dumps(state, ensure_ascii=False, indent=1))


def _save(vault: Path, name: str, text: str, project_id: str = "") -> None:
    """Swapped in whole, 0600 in 0700 folders."""
    _kept(vault).mkdir(mode=0o700, parents=True, exist_ok=True)
    work._write(_kept(vault, project_id) / name, text)


def _kept(vault: Path, project_id: str = "") -> Path:
    where = vault / "clones" / "folders"
    return where / project_id if project_id else where


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", help="only this project, by its id")
    parser.add_argument(
        "--pull-only",
        action="store_true",
        help="only bring back what you changed in the manuscripts, writing nothing to the folders",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return folders(vault, only=args.project, pull_only=args.pull_only)
