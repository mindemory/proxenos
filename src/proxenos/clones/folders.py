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
  the .bib files beside it, so it goes one way: its changes never come back.
- "<name> - manuscript.pdf": the same version, made in the same checkout, so the two always
  match: LaTeX by tectonic (PROXENOS_TECTONIC, else the one on the PATH), Markdown by pandoc with
  tectonic, else another engine it can use. Only where there's none is the PDF committed beside
  the manuscript copied instead, as "About this folder" says. Both are made again together, only
  when the manuscript or the files beside it changed: a LaTeX build takes tens of seconds, and
  one that failed isn't tried again until they change.
- Supplement/: the tables, figures and data files the manuscript names, copied from git. When
  it names a table or a figure, "Supplementary information.docx" and its PDF show them too:
  each table (.csv, .tsv, and .xlsx where openpyxl is installed) cut to ROWS rows and COLUMNS
  columns, and each figure, under the caption the manuscript gives it, and the data files by
  name. It's made from Markdown, as the notes are.
- "Where it stands", "What's known, and the question", "Drafts" and "About this project": the
  project's status.md and brief.md, its drafts still open, and what projects.json says of it.
- "About this folder": when the manuscript was made, from which branch and commit, what its
  PDF is, and what comes back and what doesn't.
A paused project gets one only when it has something to show, and one marked "cloud": false on
the list (an immigration petition, say) never gets one: what it had there is left as it was.

Comments left on a manuscript's copy, Markdown or LaTeX, come back too: each night the ones not
seen before (not those marked resolved) are queued as one step, each with the passage it is on
and who left it, which makes the changes in the manuscript itself on a branch of its own, for
the user to accept (proxenos.clones.steps). So a LaTeX paper, whose edits go one way, can still
be worked on from Word or Google Docs by commenting.

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

Where Google Drive for desktop syncs the folder, each project's record keeps the web addresses of
its folder, manuscript and PDF (from the id Drive keeps on each file), for the page's links.

Proxenos reads nothing else in the folder and shares nothing: the drive uploads what's there,
and who sees it is the user's choice. No model is used.
"""

import argparse
import csv
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
import zipfile
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

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
# What pandoc reads beside a manuscript: what it includes, cites and shows; and what LaTeX reads
# too, making its PDF (its figures as PDFs, its bibliography's styles and the like).
PAPER = {".md", ".markdown", ".txt", ".tex", ".bib", ".sty", ".cls", ".bst"}
PAPER |= {".png", ".jpg", ".jpeg", ".gif", ".svg"}
PAPER |= {".pdf", ".eps", ".bbl", ".bbx", ".cbx", ".lbx", ".def", ".cfg", ".clo", ".tikz", ".pgf"}
KINDS = {".md": "markdown", ".markdown": "markdown", ".txt": "markdown", ".tex": "latex"}
BASELINE = "baseline.md"
PANDOC_SECONDS = 300
BUILD_SECONDS = 600  # of a PDF: the first LaTeX build fetches what it uses
NO_PANDOC = (
    "pandoc makes the Word files, and it isn't installed: `brew install pandoc` on a Mac, else "
    "pandoc.org/installing (or set PROXENOS_PANDOC to where it is)"
)
NO_ENGINE = "nothing on this computer makes PDFs: `brew install tectonic` on a Mac"
_PANDOC_PLACES = ("/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc")
_TECTONIC_PLACES = ("/opt/homebrew/bin/tectonic", "/usr/local/bin/tectonic")
# The engines pandoc makes a PDF from Markdown with, where there's no tectonic, and where MacTeX
# puts them, which a job's PATH may not have.
_ENGINES = ("xelatex", "lualatex", "pdflatex", "typst")
_TEXBIN = "/Library/TeX/texbin"
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
            record["links"] = _links(root.joinpath(*record["folder"].split("/")))
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
    if paper:
        _queue_comments(vault, project, where / docx, record, paper, now, stats)
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
        FOLDER: _about_folder(project, docx, files),
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


# Comments on the manuscript's copy: each new one becomes part of a step that makes the change in
# the manuscript itself, LaTeX or Markdown, on a branch of its own for the user to accept.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"
_W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
QUOTED = 200  # of the passage a comment is on, in the step
SAID = 600  # of a comment, in the step


def comments(docx: Path) -> list[dict]:
    """The comments in a Word file, in its order, {author, at, text, on}: `on` the passage it's
    anchored to. Resolved ones (marked done) and empty ones are left out; a file that can't be
    read has none."""
    try:
        with zipfile.ZipFile(docx) as z:
            names = set(z.namelist())
            if "word/comments.xml" not in names:
                return []
            said = ElementTree.fromstring(z.read("word/comments.xml"))
            body = ElementTree.fromstring(z.read("word/document.xml"))
            extended = (
                ElementTree.fromstring(z.read("word/commentsExtended.xml"))
                if "word/commentsExtended.xml" in names
                else None
            )
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return []
    done = {
        e.get(f"{_W15}paraId")
        for e in (extended if extended is not None else [])
        if e.get(f"{_W15}done") == "1"
    }
    on: dict[str, list[str]] = {}
    open_ids: set[str] = set()
    for e in body.iter():
        if e.tag == f"{_W}commentRangeStart":
            open_ids.add(e.get(f"{_W}id"))
        elif e.tag == f"{_W}commentRangeEnd":
            open_ids.discard(e.get(f"{_W}id"))
        elif e.tag == f"{_W}t" and e.text:
            for cid in open_ids:
                on.setdefault(cid, []).append(e.text)
    found = []
    for c in said.iter(f"{_W}comment"):
        paragraphs = list(c.iter(f"{_W}p"))
        if any(p.get(f"{_W14}paraId") in done for p in paragraphs):
            continue
        text = " ".join("".join(t.text or "" for t in p.iter(f"{_W}t")) for p in paragraphs)
        if text := " ".join(text.split()):
            found.append(
                {
                    "author": c.get(f"{_W}author") or "",
                    "at": c.get(f"{_W}date") or "",
                    "text": text,
                    "on": " ".join("".join(on.get(c.get(f"{_W}id"), [])).split()),
                }
            )
    return found


def _queue_comments(
    vault: Path,
    project: dict,
    target: Path,
    record: dict,
    paper: dict,
    now: datetime,
    stats: Counter,
) -> None:
    """The comments on the manuscript's copy not queued before, as one step that makes them in
    the manuscript, from its branch; as many as fit a step, the rest next run."""
    if not target.exists():
        return
    seen = set(record.get("comments") or [])
    lines, keys = [], []
    for c in comments(target):
        key = _digest(c["author"], c["at"], c["on"], c["text"])
        if key in seen:
            continue
        who = f" ({c['author']})" if c["author"] else ""
        where = f"On “{_cut(c['on'], QUOTED)}”{who}: " if c["on"] else f"In general{who}: "
        line = f"{len(lines) + 1}. {where}{_cut(c['text'], SAID)}"
        if len(_COMMENTS_STEP) + sum(len(x) + 1 for x in [*lines, line]) > steps.STEP_CHARS:
            break
        lines.append(line)
        keys.append(key)
    if not lines:
        return
    text = _COMMENTS_STEP + "\n".join(lines)
    try:
        steps.queue(
            vault,
            project["id"],
            text,
            now,
            manuscript={"path": paper["path"], "branch": paper["branch"]},
        )
    except SystemExit as e:  # the queue is full, or the step isn't one: they wait for the next run
        print(f"folders: {project['id']}'s comments weren't queued ({e})", file=sys.stderr)
        return
    record["comments"] = [*seen, *keys]
    stats["comments_queued"] += len(lines)


_COMMENTS_STEP = (
    "Make the changes these comments on the manuscript's copy ask for, in the manuscript itself, "
    "keeping its format and everything they don't touch:\n"
)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


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
    """The manuscript at its branch's tip as a Word file, and as a PDF made in the same checkout
    beside it, each when it changed in git. The user's copy of an older version moves to
    Earlier/ first, unless it holds changes still to come back (`how`, from _bring_back): then
    it stays as it is, and so does the PDF, so the two still match."""
    files = record["files"]
    repo, tip, path, kind = paper["repo"], paper["tip"], paper["path"], paper["kind"]
    target = where / f"{where.name} - manuscript.docx"
    pdf = target.with_suffix(".pdf")
    listed = _paper_files(repo, tip, path)
    source = _digest(LOOK, kind, path, *(" ".join(f) for f in listed))
    found = _found(target, files.get(target.name), source)
    held = found == "theirs" and how in ("waiting", "held")
    pdf_source, committed = _pdf_plan(repo, tip, path, kind, source)
    build = not held and not committed and _due(pdf, files, pdf_source)
    if pdf_source is None and not held and pdf.name in files:
        files[pdf.name]["made"] = "none"  # nothing makes this version's: About this folder says
    if held:
        stats["kept_as_edited"] += 1
    elif found != "same" or build:
        with tempfile.TemporaryDirectory() as tmp:
            made, out = Path(tmp) / "made.docx", Path(tmp) / "paper"
            _write_out(repo, tip, listed, out)
            main = out.joinpath(*path.split("/"))
            if found != "same":
                to_docx(main, made, kind)
                baseline = to_markdown(made) if kind == "markdown" else None
                about = {"path": path, "branch": paper["branch"], "commit": tip, "kind": kind}
                _replace(target, target.name, files, source, made.read_bytes(), now, stats, **about)
                if baseline is None:
                    record.pop("pull", None)  # LaTeX goes one way
                else:
                    _save(vault, BASELINE, baseline, project["id"])
                    waiting = (record.get("pull") or {}).get("step")  # one brought back counts
                    record["pull"] = {
                        "from": tip,
                        "path": path,
                        "branch": paper["branch"],
                        "step": waiting,
                        "head": None,
                    }
            if build:  # after the Word file, from the same checkout
                _build(pdf, files, pdf_source, lambda o: to_pdf(main, o, kind), now, stats)
    if not held and committed and _due(pdf, files, pdf_source):
        data = manuscript._blob(repo, tip, committed)
        if data is not None:
            _replace(pdf, pdf.name, files, pdf_source, data, now, stats, made="committed")

    _write_supplement(repo, tip, path, where, files, project["name"], now, stats)


def _pdf_plan(
    repo: Path, tip: str, path: str, kind: str, source: str
) -> tuple[str | None, str | None]:
    """What the manuscript's PDF is made from, as (its source, the PDF committed beside the
    manuscript to copy): made from the same version as the Word file where this computer can
    make one; else that committed PDF, when there is one; else nothing, (None, None)."""
    if pdf_engine(kind):
        return _digest(source, "pdf"), None
    committed = str(PurePosixPath(path).with_suffix(".pdf"))
    blob = manuscript._git(repo, "rev-parse", "-q", "--verify", f"{tip}:{committed}")
    if not blob:
        return None, None
    return _digest(source, "pdf", committed, blob), committed


def _due(target: Path, files: dict, source: str | None) -> bool:
    """Whether a file is to be made from `source`: not when it was, whether the user changed it
    since or not, nor when making it from that failed (a LaTeX build takes a while: it's tried
    again once its source changes)."""
    if source is None:
        return False
    entry = files.get(target.name)
    if entry and entry.get("unmade") == source:
        return False
    return _found(target, entry, source) != "same"


def _build(
    target: Path,
    files: dict,
    source: str,
    make: Callable[[Path], None],
    now: datetime,
    stats: Counter,
) -> None:
    """What `make` makes at the path it's given, put at `target` as _replace does. When it
    can't be made, what was there stays, and the failure is kept, for About this folder and so
    it isn't tried again until its source changes."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"made{target.suffix}"
        try:
            make(out)
            data = out.read_bytes()
        except (ConvertError, OSError) as e:
            why = " ".join(str(e).split())[:200]
            files[target.name] = (files.get(target.name) or {}) | {"unmade": source, "why": why}
            stats["skipped"] += 1
            print(f"folders: {target.name} wasn't made ({why})", file=sys.stderr)
            return
    _replace(target, target.name, files, source, data, now, stats, made="built")


def _replace(
    target: Path,
    key: str,
    files: dict,
    source: str,
    data: bytes,
    now: datetime,
    stats: Counter,
    **about: str,
) -> None:
    """`data`, made from `source`, written at `target`, after the user's copy of an older
    version, if it's theirs, moves to Earlier/ beside it."""
    if _found(target, files.get(key), source) == "theirs":
        _set_aside(target, now)
        stats["moved_to_earlier"] += 1
    files[key] = {"source": source, "written": _put(data, target), "at": steps._iso(now), **about}
    stats["files_written"] += 1


# The files a manuscript names, its tables, figures and data, copied into Supplement/ beside it.
SUPPLEMENT = "Supplement"
SUPPLEMENT_FILES = 80
SUPPLEMENT_BYTES = 200 * 10**6
FILE_BYTES = 25 * 10**6  # one bigger than this stays in the repository
_NAMED = re.compile(
    r"[\w./-]*[\w-]\.(?:csv|tsv|xlsx|xls|json|txt|png|jpe?g|svg|pdf|tiff?|mat|npz|nc)\b",
    re.IGNORECASE,
)


def _write_supplement(
    repo: Path,
    tip: str,
    path: str,
    where: Path,
    files: dict,
    project_name: str,
    now: datetime,
    stats: Counter,
) -> None:
    """The files the manuscript names by name or path (S1_table.csv, figures/fig2.png), found in
    its repository at `tip`, in Supplement/ beside the copy, each when it changed in git and
    never over one the user changed, and its tables and figures in a document of their own. The
    manuscript's own PDF is made on its own."""
    text = (manuscript._blob(repo, tip, path) or b"").decode("utf-8", "replace")
    text = text.replace("\\_", "_")  # S01\_sites.csv, as LaTeX writes it, and Markdown can
    named = {m.group(0).strip("./") for m in _NAMED.finditer(text)}
    own_pdf = str(PurePosixPath(path).with_suffix(".pdf"))
    if not named:
        return
    tree: dict[str, list[tuple[str, int, str]]] = {}
    listed = manuscript._git(repo, "--literal-pathspecs", "ls-tree", "-r", "-l", "-z", tip)
    for line in listed.split("\0"):
        meta, _, name = line.partition("\t")
        fields = meta.split()
        if len(fields) == 4 and fields[1] == "blob" and fields[3].isdigit():
            tree.setdefault(PurePosixPath(name).name.lower(), []).append(
                (name, int(fields[3]), fields[2])
            )
    chosen: dict[str, tuple[str, str, str]] = {}
    total = 0
    for ref in sorted(named):
        found = tree.get(PurePosixPath(ref).name.lower()) or []
        # A path that ends the same way as the one named, else the file of that name.
        exact = [f for f in found if f[0].lower().endswith(ref.lower())] or found[:1]
        if not exact:
            continue
        kept, size, blob = exact[0]
        base = PurePosixPath(kept).name
        if kept == own_pdf or base in chosen or size > FILE_BYTES:
            continue
        if len(chosen) >= SUPPLEMENT_FILES or total + size > SUPPLEMENT_BYTES:
            break
        chosen[base] = (kept, blob, ref)
        total += size
    for base, (kept, blob, _) in chosen.items():
        target = where / SUPPLEMENT / base
        key = f"{SUPPLEMENT}/{base}"
        source = _digest("supplement", kept, blob)
        if _found(target, files.get(key), source) == "same":
            continue
        data = manuscript._blob(repo, tip, kept)
        if data is not None:
            _replace(target, key, files, source, data, now, stats)
    items = _supplementary_items(text, chosen)
    if any(how != "data" for how, *_ in items):
        _write_supplementary(repo, tip, items, where, files, project_name, now, stats)


# The supplement as a document beside the manuscript: its title, then each table and figure the
# manuscript names under the caption it gives it, in the order it names them, each table cut to
# ROWS rows and COLUMNS columns, then the data files by name.
SUPPLEMENTARY = "Supplementary information.docx"
ROWS = 40
COLUMNS = 12
CELL = 80  # characters of a cell
_DELIMITERS = {".csv": ",", ".tsv": "\t"}  # tables; .xlsx too, where openpyxl is installed
_FIGURES = {".png", ".jpg", ".jpeg", ".svg", ".pdf"}
# "Table S4", "Figure 2", "Fig. S1", "Supplementary Data 3": what a caption starts with.
_LABEL = re.compile(
    r"(?:Supplementary\s+|Suppl?\.\s*)?(?:Table|Figure|Fig\.|Fig|Data|Dataset|File)\s+S?\d+[a-z]?",
    re.IGNORECASE,
)
_LISTED = re.compile(r"\s*(?:[-*+]|\d+[.)]|\\item)\s")  # a list's item
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]*)\)")
_FLOAT = re.compile(r"\\(begin|end)\{(?:figure|table)\*?\}")
_LEAD = re.compile(r"^(?:[\s#>|*+-]+|\d+[.)]\s+)+")
_MARKUP = re.compile(r"\\(?:label|ref|cite[a-z]*)\{[^}]*\}|\\[A-Za-z]+\*?|[`{}]|\*\*|__")
_SPECIAL = re.compile(r"([\\`*_\[\]<>|$^~@#])")  # what Markdown would read as more than text
_UNSHOWN = (
    "_An SVG, which this PDF can't show without rsvg-convert (`brew install librsvg` on a Mac): "
    "it's in {file}, and the Word file shows it._"
)


def _supplementary_items(
    text: str, chosen: dict[str, tuple[str, str, str]]
) -> list[tuple[str, str, str, str, str]]:
    """The files chosen for Supplement/, as the document shows them: (how, its name, its path in
    the repository, its blob, its caption), in the order the manuscript names them, `how`
    "table" (.csv, .tsv, and .xlsx where openpyxl is installed), "figure" or "data"."""
    items = []
    for base, (kept, blob, ref) in chosen.items():
        suffix = PurePosixPath(base).suffix.lower()
        if suffix in _DELIMITERS or (suffix == ".xlsx" and _openpyxl()):
            how = "table"
        else:
            how = "figure" if suffix in _FIGURES else "data"
        items.append((text.find(ref), (how, base, kept, blob, _caption(text, ref))))
    return [item for _, item in sorted(items)]


def _caption(text: str, ref: str) -> str:
    """What the manuscript calls the file it names as `ref`, where it first gives it a caption:
    the text of the image it shows it in; in LaTeX, the \\caption of the figure or table it's
    in; else on a line naming it, the text before the parenthesis it's named in, when that
    starts with "Table S4" or the like or is an item in a list, or the "Table S1" just before
    the parenthesis or inside it. "" when it gives none."""
    at = text.find(ref)
    while at >= 0:
        if caption := _caption_at(text, at):
            return caption
        at = text.find(ref, at + len(ref))
    return ""


def _caption_at(text: str, at: int) -> str:
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    line = text[start : len(text) if end < 0 else end]
    i = at - start
    for image in _IMAGE.finditer(line):
        if image.start(2) <= i < image.end(2) and image.group(1).strip():
            return _clean(image.group(1))
    if caption := _float_caption(text, at):
        return caption
    paren = line.rfind("(", 0, i)
    if paren < 0 or ")" in line[paren:i]:
        return ""  # not named in parentheses
    before, inside = line[:paren], line[paren + 1 : i]
    head = _clean(before)
    if head and (_LABEL.match(head) or _LISTED.match(before)):
        return head
    labels = [m for m in _LABEL.finditer(head) if m.end() == len(head)]  # "in Table S1 (...)"
    label = labels[-1] if labels else _LABEL.search(inside)  # "(Table S1, ...)"
    return _clean(label.group(0)) if label else ""


def _float_caption(text: str, at: int) -> str:
    """The \\caption of the LaTeX figure or table `at` is in, or ""."""
    opened = list(_FLOAT.finditer(text, 0, at))
    closed = _FLOAT.search(text, at)
    if not opened or opened[-1].group(1) != "begin" or not closed or closed.group(1) != "end":
        return ""
    body = text[opened[-1].end() : closed.start()]
    start = body.find("\\caption")
    brace = body.find("{", start) if start >= 0 else -1
    if brace < 0:
        return ""
    depth = 0
    for end in range(brace, len(body)):
        depth += {"{": 1, "}": -1}.get(body[end], 0)
        if depth == 0:
            return _clean(body[brace + 1 : end])
    return ""


def _clean(text: str) -> str:
    """A caption as plain text: no LaTeX commands, list markers, bold or code marks."""
    text = _MARKUP.sub(lambda m: " " if m.group(0).startswith("\\") else "", text)
    return _LEAD.sub("", " ".join(text.split())).strip(" -–—:;,(")


def _write_supplementary(
    repo: Path,
    tip: str,
    items: list[tuple[str, str, str, str, str]],
    where: Path,
    files: dict,
    project_name: str,
    now: datetime,
    stats: Counter,
) -> None:
    """The supplement as a Word file and a PDF beside the manuscript, each made again only when
    what it's made from changed, and never over a copy the user changed: that moves to Earlier/
    first. An SVG figure is only named in the PDF where pandoc has nothing to draw it with."""
    title = f"{project_name}: supplementary information"
    source = _digest(LOOK, "supplementary", f"{ROWS} {COLUMNS} {CELL}", title, *map(str, items))
    docx = where / SUPPLEMENTARY
    pdf = docx.with_suffix(".pdf")
    svg = any(how == "figure" and base.lower().endswith(".svg") for how, base, *_ in items)
    shown = not svg or bool(shutil.which("rsvg-convert"))
    pdf_source = _digest(source, "pdf", str(shown)) if pdf_engine("markdown") else None
    make_docx, make_pdf = _due(docx, files, source), _due(pdf, files, pdf_source)
    if not make_docx and not make_pdf:
        return
    with tempfile.TemporaryDirectory() as tmp:
        md = Path(tmp) / "supplementary.md"
        md.write_text(_supplementary(repo, tip, items, title, md.parent), encoding="utf-8")
        if make_docx:
            _build(docx, files, source, lambda o: to_docx(md, o, "markdown"), now, stats)
        if make_pdf:
            if not shown:
                text = _supplementary(repo, tip, items, title, md.parent, svg=False)
                md.write_text(text, encoding="utf-8")
            _build(pdf, files, pdf_source, lambda o: to_pdf(md, o, "markdown"), now, stats)


def _supplementary(
    repo: Path,
    tip: str,
    items: list[tuple[str, str, str, str, str]],
    title: str,
    into: Path,
    svg: bool = True,
) -> str:
    """The supplement's Markdown, its figures written beside it under `into`; without `svg`,
    an SVG figure named, not shown."""
    lines, listed = [f"# {title}", ""], []
    for how, base, kept, _, caption in items:
        data = manuscript._blob(repo, tip, kept) if how != "data" else None
        table = _table(base, data) if how == "table" and data is not None else None
        if data is None or (how == "table" and table is None):
            listed.append(base)  # by name, as a data file
            continue
        lines += [f"## {caption or _escape(base)}", ""]
        if how == "figure" and not svg and base.lower().endswith(".svg"):
            lines += [_UNSHOWN.format(file=f"{SUPPLEMENT}/{_escape(base)}"), ""]
            continue
        if how == "figure":
            figure = into / "figures" / base
            figure.parent.mkdir(exist_ok=True)
            figure.write_bytes(data)
            lines += [f"![](<figures/{base}>)", ""]
            continue
        rows, height, width = table
        cells = [[_escape(_cut(" ".join(c.split()), CELL)) for c in r] for r in rows]
        wide = max(len(r) for r in cells)
        cells = [r + [""] * (wide - len(r)) for r in cells]
        lines += [f"| {' | '.join(cells[0])} |", "|" + "---|" * wide]
        lines += [f"| {' | '.join(r)} |" for r in cells[1:]] + [""]
        cut = [f"{ROWS} of its {height} rows"] if height > ROWS else []
        cut += [f"{COLUMNS} of its {width} columns"] if width > COLUMNS else []
        if cut:
            full = f"the full table is in {SUPPLEMENT}/{_escape(base)}"
            lines += [f"_This is the first {' and '.join(cut)}: {full}._", ""]
    if listed:
        lines += ["## Data files", "", f"In {SUPPLEMENT}/, beside this file:", ""]
        lines += [f"- {_escape(base)}" for base in listed] + [""]
    return "\n".join(lines)


def _table(base: str, data: bytes) -> tuple[list[list[str]], int, int] | None:
    """A table file's header and its first ROWS rows, at most COLUMNS wide, with how many rows
    under the header and columns it has in all; None when it can't be read as one."""
    suffix = PurePosixPath(base).suffix.lower()
    if suffix in _DELIMITERS:
        text = data.decode("utf-8-sig", errors="replace")
        rows = csv.reader(io.StringIO(text, newline=""), delimiter=_DELIMITERS[suffix])
    elif suffix == ".xlsx" and (openpyxl := _openpyxl()):
        try:
            book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = book.worksheets[0].iter_rows(values_only=True)
        except Exception:  # noqa: BLE001 - a workbook it can't read is listed by name
            return None
        rows = (["" if v is None else str(v) for v in row] for row in sheet)
    else:
        return None
    kept, height, width = [], -1, 0
    try:
        for row in rows:
            if not any(cell.strip() for cell in row):
                continue  # a blank line
            height, width = height + 1, max(width, len(row))
            if len(kept) <= ROWS:
                kept.append(row[:COLUMNS])
    except Exception:  # noqa: BLE001 - csv's or openpyxl's, partway through
        return None
    return (kept, height, width) if kept else None


def _openpyxl():
    """openpyxl, which reads .xlsx files, where it's installed; else None."""
    try:
        import openpyxl
    except ImportError:
        return None
    return openpyxl


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", text)


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
    own_pdf = str(PurePosixPath(path).with_suffix(".pdf"))
    for line in listed.split("\0"):
        meta, _, name = line.partition("\t")
        fields = meta.split()
        if len(fields) != 4 or fields[:2] == ["120000", "blob"] or fields[1] != "blob":
            continue  # not a file: a link, a folder or a submodule
        if name == own_pdf:
            continue  # what's made from it, not what it's made from
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
    source = _digest(LOOK, text)
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
_COMMITTED = (
    "**{pdf}** is {committed} as it's committed in git, which may not be the version above: "
    "nothing on this computer makes PDFs. Install tectonic (`brew install tectonic` on a Mac) "
    "and the next run makes it from the same version as the Word file."
)
_NO_PDF = (
    "There's no PDF of this version: nothing on this computer makes PDFs, and none is committed "
    "beside it. Install tectonic (`brew install tectonic` on a Mac) and the next run makes one "
    "from the same version as the Word file."
)
_UNMADE = (
    "**{pdf}** couldn't be made from this version ({why}), so whatever was here stays as it was. "
    "It's tried again when the paper changes."
)
_SUPPLEMENTARY = (
    f"**{SUPPLEMENTARY}**, and its PDF, hold the tables and figures the manuscript names, under "
    "the captions it gives them, and list its data files; a long table is cut short there. The "
    f"files themselves are in {SUPPLEMENT}/, copied from the same version."
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


def _about_folder(project: dict, docx: str, files: dict) -> str:
    """What the folder is, when its manuscript was made and from where, what its PDF is, and
    what comes back."""
    keeps = (
        f"Proxenos keeps this folder for {project['name']}, from your vault and the project's "
        "git, and brings it up to date each night. Git stays the source of truth."
    )
    paper = [_NO_PAPER if project["repo"] else _NO_REPO]
    if made := files.get(docx):
        at = f"{made['path']} at {made['commit'][:7]} on {made['branch']}"
        pdf = str(PurePosixPath(docx).with_suffix(".pdf"))
        paper = [
            f"**{docx}** is {at}, made {made['at'][:10]}.",
            *_about_pdf(pdf, files.get(pdf), made["path"]),
            _COMES_BACK if made["kind"] == "markdown" else _ONE_WAY.format(path=made["path"]),
            _MOVES_ON,
        ]
        if (files.get(SUPPLEMENTARY) or {}).get("written"):
            paper.append(_SUPPLEMENTARY)
    parts = ["# About this folder", keeps, "## The manuscript", *paper]
    return "\n\n".join([*parts, "## The notes", _THE_NOTES, _NOTHING_ELSE]) + "\n"


def _about_pdf(pdf: str, made: dict | None, path: str) -> list[str]:
    """What the manuscript's PDF is: made from the same version as the Word file, copied from
    git, not made this time, or not there."""
    if made and made.get("unmade"):
        return [_UNMADE.format(pdf=pdf, why=made.get("why") or "it failed")]
    if made and made.get("made") == "committed":
        return [_COMMITTED.format(pdf=pdf, committed=str(PurePosixPath(path).with_suffix(".pdf")))]
    if made and made.get("made") == "built":
        return [f"**{pdf}** is made from the same version, so the two match."]
    return [_NO_PDF] if not made or made.get("made") == "none" else []


# Converting, by pandoc and tectonic: the functions tests replace.


def to_docx(source: Path, out: Path, kind: str) -> None:
    """`source`, Markdown or LaTeX (`kind`), as a Word file at `out`, by pandoc run in its
    folder, so what it includes and shows is found. LaTeX's citations and references are written
    out from the .bib files beside it and those it names."""
    args = ["-f", kind, "-t", "docx", "-o", str(out)]
    if reference := _reference():
        args.append(f"--reference-doc={reference}")
    if kind == "latex":
        args.append("--citeproc")
        for bib in sorted(source.parent.glob("*.bib")):
            args += ["--bibliography", bib.name]
    _pandoc(*args, source.name, cwd=source.parent)


def to_pdf(source: Path, out: Path, kind: str) -> None:
    """`source`, Markdown or LaTeX (`kind`), as a PDF at `out`, made in its folder as the Word
    file is: LaTeX typeset by tectonic as it is, with its own bibliography, its shell escape
    off; Markdown by pandoc with tectonic, else another engine it can use, in its serif body
    with Word's one-inch margins."""
    engine = pdf_engine(kind)
    if engine is None:
        raise ConvertError(NO_ENGINE)
    if kind == "markdown":
        args = ["-f", "markdown", "-o", str(out), f"--pdf-engine={engine}"]
        args += ["-V", "geometry:margin=1in", source.name]
        _pandoc(*args, cwd=source.parent, seconds=BUILD_SECONDS)
        return
    with tempfile.TemporaryDirectory() as tmp:
        args = ["-X", "compile", "--untrusted", "--outdir", tmp, source.name]
        _run(engine, *args, cwd=source.parent, seconds=BUILD_SECONDS)
        made = Path(tmp) / f"{source.stem}.pdf"
        if not made.is_file():
            raise ConvertError(f"tectonic made no {made.name}")
        shutil.copyfile(made, out)


def pdf_engine(kind: str) -> str | None:
    """What makes a PDF of a `kind` file: tectonic (PROXENOS_TECTONIC, else the one on the PATH
    or where Homebrew puts it); for Markdown, else XeLaTeX, LuaLaTeX, pdfLaTeX or Typst, through
    pandoc. None when there's none."""
    for place in (env("TECTONIC"), shutil.which("tectonic"), *_TECTONIC_PLACES):
        if place and os.access(path := os.path.expanduser(place), os.X_OK):
            return path
    if kind != "markdown":
        return None
    for name in _ENGINES:
        for place in (shutil.which(name), os.path.join(_TEXBIN, name)):
            if place and os.access(place, os.X_OK):
                return place
    return None


# The Word files' look: FONT throughout, which Word, Google Docs and Drive's viewer all have
# (pandoc's own template uses Aptos, which Drive shows as another font), headings in black, and
# tables ruled in a thin grid (pandoc's draws only a line under the header).
# Bump LOOK when it changes, and each file still as Proxenos wrote it is written again.
FONT = "Arial"
LOOK = "arial-black-grid-1"
_BORDERS = "".join(
    f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
    for side in ("top", "left", "bottom", "right", "insideH", "insideV")
)
_TABLE = re.compile(r'(w:styleId="Table">.*?<w:tblPr>)', re.DOTALL)
_COLOURED = re.compile(r'(<w:color w:val=")(0F4761|365F91|4F81BD|1F3763|2F5496)(")')


def _reference() -> Path | None:
    """pandoc's own Word template in FONT with black headings, made once and kept beside the
    system's temporary files (it holds no one's data). None when it can't be made: pandoc's
    own look then."""
    made = Path(tempfile.gettempdir()) / f"proxenos-reference-{LOOK}.docx"
    if made.exists():
        return made
    command = pandoc()
    if not command:
        return None
    try:
        original = subprocess.run(
            [command, "--print-default-data-file", "reference.docx"],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as src, zipfile.ZipFile(out, "w") as dst:
            for item in src.infolist():
                data = src.read(item.filename)
                if item.filename == "word/theme/theme1.xml":
                    data = re.sub(
                        rb'<a:latin typeface="[^"]*"', f'<a:latin typeface="{FONT}"'.encode(), data
                    )
                elif item.filename == "word/styles.xml":
                    styles = _COLOURED.sub(r"\g<1>000000\g<3>", data.decode("utf-8"))
                    styles = _TABLE.sub(rf"\g<1><w:tblBorders>{_BORDERS}</w:tblBorders>", styles, 1)
                    data = styles.encode("utf-8")
                dst.writestr(item, data)
        part = made.with_suffix(".part")
        part.write_bytes(out.getvalue())
        part.replace(made)
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile, UnicodeDecodeError):
        return None
    return made


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


def _pandoc(*args: str, cwd: Path, seconds: int = PANDOC_SECONDS) -> str:
    command = pandoc()
    if command is None:
        raise ConvertError(NO_PANDOC)
    return _run(command, *args, cwd=cwd, seconds=seconds)


def _run(command: str, *args: str, cwd: Path, seconds: int) -> str:
    """What `command` printed; ConvertError with what it said went wrong when it failed."""
    what = Path(command).name
    try:
        done = subprocess.run(
            [command, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ConvertError(f"{what} didn't run: {e}") from None
    if done.returncode:
        raise ConvertError(f"{what}: {_why(done.stderr) or done.returncode}"[:300])
    return done.stdout


_GENERIC = re.compile(r"something bad happened|its output follows|halted on potentially")


def _why(said: str) -> str:
    """What went wrong, from what a command said: TeX's first error (a line starting "!" or
    "error:"), with the cause tectonic gives under it, else its last line."""
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    lines = [line for line in lines if not _GENERIC.search(line)]
    for n, line in enumerate(lines):
        if line.startswith(("!", "error:")):
            cause = lines[n + 1] if n + 1 < len(lines) else ""
            if cause.startswith("caused by:"):
                return f"{line} ({cause.removeprefix('caused by:').strip()})"
            return line
    return lines[-1] if lines else ""


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


_DRIVE_ID = "com.google.drivefs.item-id#S"  # the id Google Drive for desktop keeps on a file
_ITEM = re.compile(r"[A-Za-z0-9_-]{10,200}")


def _links(where: Path) -> dict[str, str]:
    """The project's folder, manuscript and PDF on drive.google.com, for the page to open, where
    Google Drive for desktop has synced them; "" for each it hasn't yet, or in another drive. A
    run fills in those it missed."""
    name = f"{where.name} - manuscript"
    return {
        "folder": _drive_link(where, folder=True),
        "manuscript": _drive_link(where / f"{name}.docx"),
        "pdf": _drive_link(where / f"{name}.pdf"),
    }


def _drive_link(path: Path, folder: bool = False) -> str:
    if sys.platform != "darwin" or not path.exists():
        return ""
    try:
        said = subprocess.run(
            ["/usr/bin/xattr", "-p", _DRIVE_ID, str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    item = said.stdout.strip()
    if said.returncode or not _ITEM.fullmatch(item):
        return ""
    if folder:
        return f"https://drive.google.com/drive/folders/{item}"
    return f"https://drive.google.com/file/d/{item}/view"


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
