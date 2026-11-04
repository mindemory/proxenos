"""Each project as a folder in a cloud drive, against a folder and a small git repository made
here and a fake pandoc and tectonic. No network, no model, no pandoc, no tectonic, no real
document and no real drive."""

import json
import os
import stat
import subprocess
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from proxenos import cli, manuscript
from proxenos.clones import folders, projects, steps, work

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 11, 2, 0, tzinfo=UTC)
LATEST = datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
FOLDER = "PhD/Calls the paper"  # "Calls: the paper?", made safe
DOCX = "Calls the paper - manuscript.docx"
PDF = "Calls the paper - manuscript.pdf"
SUPPLEMENTARY = "Supplementary information.docx"

PAPER = (
    "# Birdsong at dawn\n\n"
    "Birds sing *loudly* at dawn [@smith2020].\n\n"
    "- wrens\n- robins\n\n"
    "![The dawn chorus](fig.png)\n\n"
    "Methods follow.\n\n"
    "Thanks to the lab.\n"
)
LATEX = (
    "\\documentclass{article}\n\\begin{document}\n"
    "Birds sing at dawn \\citep{smith2020}.\n\n\\input{sections/methods}\n"
    "\\bibliography{refs}\n\\end{document}\n"
)


class FakePandoc:
    """pandoc, and tectonic, as these tests see them. A Word file or PDF it makes is a line
    naming what it was made from, then the text; read back, emphasis and lists come in Word's
    reading of them (_x_, * x), so the Markdown that comes back differs from the manuscript's
    own, as pandoc's does, and lines that are comments in Word ("COMMENT: ...") aren't text. It
    keeps what each conversion was given, with the folder it was made in and the files there:
    Word files in `made`, PDFs in `pdfs`. `fails`, when set, is why a PDF can't be made."""

    def __init__(self):
        self.made = []
        self.pdfs = []
        self.fails = ""

    @staticmethod
    def _given(source, kind):
        beside = sorted(
            p.relative_to(source.parent).as_posix() for p in source.parent.rglob("*") if p.is_file()
        )
        return {"name": source.name, "kind": kind, "beside": beside, "in": str(source.parent)}

    def to_docx(self, source, out, kind):
        self.made.append(self._given(source, kind))
        out.write_bytes(f"DOCX from {kind}\n".encode() + source.read_bytes())

    def to_pdf(self, source, out, kind):
        self.pdfs.append(self._given(source, kind))
        if self.fails:
            raise folders.ConvertError(self.fails)
        out.write_bytes(f"PDF from {kind}\n".encode() + source.read_bytes())

    def to_markdown(self, docx):
        head, _, body = docx.read_bytes().decode().partition("\n")
        assert head.startswith("DOCX from ")
        body = "".join(line for line in body.splitlines(True) if not line.startswith("COMMENT:"))
        return body.replace("*loudly*", "_loudly_").replace("- ", "* ")


def text_of(path):
    """What a Word file or PDF the fake made says, without its first line."""
    return path.read_bytes().decode().partition("\n")[2]


def edit(path, old, new):
    """The owner changing a Word file, in Word or Google Docs."""
    data = path.read_bytes().decode()
    assert old in data
    path.write_bytes(data.replace(old, new).encode())


def git(where, *args):
    return subprocess.run(
        ["git", "-C", str(where), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo, files, message, day):
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
    git(repo, "add", "-A")
    stamp = f"2026-03-0{day}T12:00:00+00:00"
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        env=dict(os.environ) | {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    return git(repo, "rev-parse", "HEAD")


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": list(items)}))


def note(vault, project_id, name, text):
    path = vault / "clones" / "projects" / project_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def draft(vault, draft_id, title, body, status):
    work._write(
        vault / "clones" / "drafts" / f"{draft_id}.md",
        work.render(
            {
                "id": draft_id,
                "title": title,
                "kind": "email",
                "for": "project",
                "channel": "email",
                "to": "Ana Lee",
                "created": "2026-03-09T02:00:00Z",
                "status": status,
                "body": body,
            }
        ),
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A drive's folder, a fake pandoc and tectonic, a vault, and a project's repository checked
    out on main with its paper, a figure and a PDF of it on a side branch."""
    monkeypatch.setenv("PROXENOS_WORKTREES", str(tmp_path / "worktrees"))
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    vault = tmp_path / "vault"
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))  # the command's vault too
    drive = tmp_path / "Drive"
    drive.mkdir()
    monkeypatch.setenv("PROXENOS_PROJECT_FOLDER", str(drive))
    fake = FakePandoc()
    monkeypatch.setattr(folders, "to_docx", fake.to_docx)
    monkeypatch.setattr(folders, "to_markdown", fake.to_markdown)
    monkeypatch.setattr(folders, "to_pdf", fake.to_pdf)
    monkeypatch.setattr(folders, "pandoc", lambda: "/usr/local/bin/pandoc")
    monkeypatch.setattr(folders, "pdf_engine", lambda kind: "/usr/local/bin/tectonic")
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Joe")
    git(repo, "config", "user.email", "joe@example.org")
    git(repo, "config", "core.autocrlf", "false")  # keep line ends as written, as on a Mac
    commit(repo, {"analysis.py": "print('mean')\n", "data/big.png": b"\x89PNG data"}, "Start", 1)
    git(repo, "checkout", "-q", "-b", "paper-storyline")
    paper = {
        "docs/paper/paper.md": PAPER,
        "docs/paper/fig.png": b"\x89PNG dawn",
        "docs/paper/paper.pdf": b"%PDF-1.7 the paper",
    }
    commit(repo, paper, "Draft the paper", 2)
    git(repo, "checkout", "-q", "main")
    write_list(
        vault,
        {
            "id": "calls",
            "name": "Calls: the paper?",
            "group": "PhD",
            "about": "When birds sing",
            "people": ["Ana Lee"],
            "notes": "F*.py make the figures.",
            "repo": str(repo),
        },
    )
    return vault, repo, drive, fake


def run(vault, now, **kwargs):
    return folders.folders(vault, now=now, **kwargs)


def state(vault):
    return json.loads((vault / "clones" / "folders" / "state.json").read_text())


def checkout_of(repo):
    return (
        git(repo, "branch", "--show-current"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "status", "--porcelain"),
    )


# Where it writes, and when it doesn't.


def test_without_the_setting_or_pandoc_nothing_is_done_and_it_says_why(setup, monkeypatch, capsys):
    vault, _, drive, fake = setup
    monkeypatch.delenv("PROXENOS_PROJECT_FOLDER")
    assert run(vault, NOW) == {"folder_not_set": 1}
    assert "PROXENOS_PROJECT_FOLDER isn't set" in capsys.readouterr().err

    monkeypatch.setenv("PROXENOS_PROJECT_FOLDER", str(drive / "not-mounted"))
    assert run(vault, NOW) == {"folder_missing": 1}
    assert not (drive / "not-mounted").exists()  # a drive that isn't there isn't made up

    monkeypatch.setenv("PROXENOS_PROJECT_FOLDER", str(drive))
    monkeypatch.setattr(folders, "pandoc", lambda: None)
    assert run(vault, NOW) == {"pandoc_missing": 1}
    assert "brew install pandoc" in capsys.readouterr().err

    assert fake.made == [] and list(drive.iterdir()) == []
    assert not (vault / "clones" / "folders").exists()


def test_names_are_safe_on_every_computer():
    assert folders.safe_name("Calls: the paper?", "calls") == "Calls the paper"
    assert folders.safe_name('a/b\\c*d<e>f|g"h', "x") == "a b c d e f g h"
    assert folders.safe_name("  .hidden thing. ", "x") == "hidden thing"
    assert folders.safe_name("CON", "fallback") == "fallback"
    assert folders.safe_name("nul.txt", "fallback") == "fallback"
    assert folders.safe_name("Con artists", "x") == "Con artists"
    assert folders.safe_name("tab\there\x00", "x") == "tab here"
    assert folders.safe_name("...", "fallback") == "fallback"
    assert len(folders.safe_name("long " * 40, "x")) <= folders.NAME_CHARS


def test_each_project_gets_a_folder_of_its_manuscript_and_notes(setup):
    vault, repo, drive, fake = setup
    tip = git(repo, "rev-parse", "paper-storyline")
    note(vault, "calls", "status.md", "# Calls\n\n_Where it stands._\n\nThe draft is out.\n")
    note(vault, "calls", "brief.md", "What's known: birds sing.\n")
    draft(vault, "project-calls-20260309-1", "Ask Ana for the data", "Hi Ana, the data?", "draft")
    draft(vault, "project-calls-20260308-1", "Plan the methods", "1. Count wrens.", "approved")
    draft(vault, "project-calls-20260307-1", "Already sent", "Gone.", "sent")
    draft(vault, "project-other-20260309-1", "Not this project's", "No.", "draft")
    write_list(
        vault,
        json.loads((vault / "clones" / "projects" / "projects.json").read_text())["projects"][0],
        {"id": "hobby", "name": "Birdhouses"},  # no group, no code
        {"id": "old", "name": "Old thing", "paused": True},  # paused, nothing to show
        {"id": "resting", "name": "Resting", "paused": True},  # paused, with a status
        {"id": "petition", "name": "The petition", "group": "Life", "cloud": False},  # kept out
    )
    note(vault, "petition", "status.md", "# The petition\n\nFiled.\n")
    note(vault, "resting", "status.md", "# Resting\n\nOn hold until June.\n")
    before = checkout_of(repo)

    stats = run(vault, NOW)

    assert stats == {
        "folders_written": 3,
        # The paper's folder: the manuscript and its PDF, the five notes, the figure it names
        # and the supplement it makes, as a Word file and a PDF.
        "files_written": 10 + 2 + 3,
        "kept_as_edited": 0,
        "manuscripts_brought_back": 0,
        "steps_made": 0,
        "skipped": 1,
        "kept_out": 1,
    }
    assert not (drive / "Life").exists()
    where = drive / "PhD" / "Calls the paper"
    assert sorted(p.name for p in where.iterdir()) == sorted(
        [
            DOCX,
            PDF,
            "Where it stands.docx",
            "What's known, and the question.docx",
            "Drafts.docx",
            "About this project.docx",
            "About this folder.docx",
            "Supplement",
            SUPPLEMENTARY,
            "Supplementary information.pdf",
        ]
    )
    assert [p.name for p in (where / "Supplement").iterdir()] == ["fig.png"]
    # The manuscript at its branch's tip, converted where the files beside it are, and nothing
    # else of the repository, not even the PDF committed beside it; its PDF made there too.
    assert text_of(where / DOCX) == text_of(where / PDF) == PAPER
    made = next(m for m in fake.made if m["name"] == "paper.md")
    assert made["kind"] == "markdown" and made["beside"] == ["fig.png", "paper.md"]
    [pdf, _] = fake.pdfs
    assert pdf == made  # the same checkout, at the same commit
    assert "The draft is out." in text_of(where / "Where it stands.docx")
    assert text_of(where / "What's known, and the question.docx") == "What's known: birds sing."
    drafts = text_of(where / "Drafts.docx")
    assert "## Plan the methods" in drafts and "## Ask Ana for the data" in drafts
    assert "Hi Ana, the data?" in drafts
    assert "Already sent" not in drafts and "Not this project's" not in drafts
    about = text_of(where / "About this project.docx")
    assert "When birds sing" in about and "Ana Lee" in about and "F*.py" in about
    folder = text_of(where / "About this folder.docx")
    assert f"docs/paper/paper.md at {tip[:7]} on paper-storyline, made 2026-03-10" in folder
    assert f"**{PDF}** is made from the same version, so the two match." in folder
    assert "comes back to the project's git as a step" in folder
    assert f"**{SUPPLEMENTARY}**, and its PDF, hold the tables and figures" in folder

    # A project with no group goes under Other; with no code, it has no manuscript.
    hobby = drive / "Other" / "Birdhouses"
    assert sorted(p.name for p in hobby.iterdir()) == [
        "About this folder.docx",
        "About this project.docx",
    ]
    assert "no code folder" in text_of(hobby / "About this folder.docx")
    # A paused one only when it has something to show.
    assert not (drive / "Other" / "Old thing").exists()
    assert (drive / "Other" / "Resting" / "Where it stands.docx").exists()
    assert "**Paused:**" in text_of(drive / "Other" / "Resting" / "About this project.docx")

    # The state: what each file came from and what was written, private to the user.
    kept = state(vault)
    assert kept["root"] == str(drive.resolve())
    files = kept["projects"]["calls"]["files"]
    assert files[DOCX]["commit"] == tip and files[DOCX]["kind"] == "markdown"
    assert all(len(f["source"]) == len(f["written"]) == 64 for f in files.values())
    assert kept["projects"]["calls"]["pull"] == {
        "from": tip,
        "path": "docs/paper/paper.md",
        "branch": "paper-storyline",
        "step": None,
        "head": None,
    }
    # The baseline is the Markdown of the .docx written, not the manuscript.
    baseline = (vault / "clones" / "folders" / "calls" / "baseline.md").read_text()
    assert baseline == FakePandoc().to_markdown(where / DOCX) != PAPER
    kept_here = vault / "clones" / "folders"
    for path in (kept_here / "state.json", kept_here / "calls" / "baseline.md"):
        assert os.name == "nt" or stat.S_IMODE(path.stat().st_mode) == 0o600
        assert os.name == "nt" or stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert checkout_of(repo) == before

    # Again with nothing changed: nothing written, nothing converted, nothing typeset.
    made, pdfs = len(fake.made), len(fake.pdfs)
    again = run(vault, LATER)
    assert again["files_written"] == 0 and again["folders_written"] == 0
    assert (made, pdfs) == (12, 2) and (len(fake.made), len(fake.pdfs)) == (made, pdfs)


def test_the_command_runs_one_project(setup, capsys):
    vault, _, drive, _ = setup
    write_list(
        vault,
        json.loads((vault / "clones" / "projects" / "projects.json").read_text())["projects"][0],
        {"id": "hobby", "name": "Birdhouses"},
    )
    cli.main(["clone", "folders", "--project", "hobby"])
    assert capsys.readouterr().out.startswith("folders: 1 folders written, 2 files written")
    assert (drive / "Other" / "Birdhouses").is_dir() and not (drive / "PhD").exists()
    with pytest.raises(SystemExit, match="no project 'nope'"):
        cli.main(["clone", "folders", "--project", "nope"])


# Never over what the owner changed.


def test_a_note_the_owner_changed_is_kept_and_an_untouched_one_written_again(setup):
    vault, _, drive, _ = setup
    note(vault, "calls", "status.md", "# Calls\n\nThe draft is out.\n")
    note(vault, "calls", "brief.md", "What's known: birds sing.\n")
    run(vault, NOW)
    where = drive / FOLDER
    edit(where / "Where it stands.docx", "The draft is out.", "The draft is out. (Ana agrees.)")
    mine = (where / "Where it stands.docx").read_bytes()

    note(vault, "calls", "status.md", "# Calls\n\nThe draft is back with comments.\n")
    note(vault, "calls", "brief.md", "What's known: birds sing, and owls.\n")
    stats = run(vault, LATER)

    assert stats["kept_as_edited"] == 1 and stats["files_written"] == 1
    assert (where / "Where it stands.docx").read_bytes() == mine
    assert text_of(where / "What's known, and the question.docx") == (
        "What's known: birds sing, and owls."
    )
    # A note the owner deleted is written again, as Proxenos's.
    (where / "Where it stands.docx").unlink()
    run(vault, LATEST)
    assert "back with comments" in text_of(where / "Where it stands.docx")


def test_a_file_proxenos_never_wrote_is_never_written_over(setup):
    vault, _, drive, _ = setup
    where = drive / FOLDER
    where.mkdir(parents=True)
    (where / "About this project.docx").write_bytes(b"the owner's own")
    (where / DOCX).write_bytes(b"the owner's own paper")

    stats = run(vault, NOW)

    assert stats["kept_as_edited"] == 1 and stats["moved_to_earlier"] == 1
    assert (where / "About this project.docx").read_bytes() == b"the owner's own"
    assert (where / "Earlier" / "Calls the paper - manuscript 2026-03-10.docx").read_bytes() == (
        b"the owner's own paper"
    )
    assert text_of(where / DOCX) == PAPER


# The manuscript, brought back.


def test_the_owners_changes_come_back_as_a_step_with_the_rest_as_it_was(setup):
    vault, repo, drive, _ = setup
    run(vault, NOW)
    written = git(repo, "rev-parse", "paper-storyline")
    # Meanwhile the paper moves on in git, in a paragraph no one touches in the folder.
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": PAPER.replace("Thanks", "Our thanks")}, "Thank", 3)
    git(repo, "checkout", "-q", "main")
    before = checkout_of(repo)
    where = drive / FOLDER
    edit(where / DOCX, "Methods follow.", "Methods follow, in short.")

    stats = run(vault, LATER, pull_only=True)

    assert stats["manuscripts_brought_back"] == 1 and stats["steps_made"] == 1
    assert stats["files_written"] == 0  # pull only
    [step] = projects.steps_taken(vault, "calls")
    assert step["id"] == "calls/20260311-020000" and step["status"] == "ready"
    assert step["base"] == "paper-storyline" and step["base_commit"] == written
    assert step["step"] == "What changed in your Drive folder, for docs/paper/paper.md"
    assert step["did"].startswith(
        "Brought back what changed in docs/paper/paper.md's copy in your Drive folder"
    )
    # Only that paragraph changed: the rest keeps its own Markdown, *loudly* and its list, to the
    # byte, though Word's reading of them differs.
    on_branch = git(repo, "show", f"{step['branch']}:docs/paper/paper.md") + "\n"
    assert on_branch == PAPER.replace("Methods follow.", "Methods follow, in short.")
    assert git(repo, "log", "-1", "--format=%s", step["branch"]) == (
        "Bring in what changed in your Drive folder to docs/paper/paper.md."
    )
    assert checkout_of(repo) == before
    kept = state(vault)["projects"]["calls"]
    assert kept["pull"]["step"] == step["id"] and kept["pull"]["head"] == step["head"]
    assert kept["files"][DOCX]["seen"] == folders._sha(where / DOCX)
    baseline = (vault / "clones" / "folders" / "calls" / "baseline.md").read_text()
    assert "Methods follow, in short." in baseline

    # Brought back once: the next run makes no other step. Git moved on, so the newer version
    # is written, and the owner's copy moves to Earlier/ first.
    mine = (where / DOCX).read_bytes()
    stats = run(vault, LATER)
    assert stats["steps_made"] == 0 and stats["moved_to_earlier"] == 1
    assert (where / "Earlier" / "Calls the paper - manuscript 2026-03-11.docx").read_bytes() == mine
    assert text_of(where / DOCX) == PAPER.replace("Thanks", "Our thanks")

    # While the step waits, newer changes wait in the copy, which stays even when git moves on.
    edit(where / DOCX, "# Birdsong at dawn", "# Birdsong at first light")
    mine = (where / DOCX).read_bytes()
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": PAPER.replace("Thanks", "All our thanks")}, "More", 4)
    stats = run(vault, LATEST)
    assert stats["waiting_on_you"] == 1 and stats["kept_as_edited"] == 1
    assert stats["steps_made"] == 0 and "moved_to_earlier" not in stats
    assert (where / DOCX).read_bytes() == mine
    assert text_of(where / PDF) == PAPER.replace("Thanks", "Our thanks")  # it waits with it
    assert len(projects.steps_taken(vault, "calls")) == 1

    # Accepted, it merges; the next run brings the waiting change back from where it was made.
    steps.accept(vault, step["id"], LATEST)
    stats = run(vault, LATEST.replace(hour=3))
    assert stats["steps_made"] == 1 and stats["moved_to_earlier"] == 1
    later = projects.steps_taken(vault, "calls")[0]
    shown = git(repo, "show", f"{later['branch']}:docs/paper/paper.md") + "\n"
    assert shown == PAPER.replace("Thanks", "Our thanks").replace(
        "# Birdsong at dawn", "# Birdsong at first light"
    )


def test_nothing_comes_back_when_the_text_is_the_same(setup):
    vault, repo, drive, _ = setup
    run(vault, NOW)
    where = drive / FOLDER
    # A comment only: the file changed, its text didn't.
    path = where / DOCX
    path.write_bytes(path.read_bytes() + b"COMMENT: lovely\n")

    stats = run(vault, LATER)

    assert stats["manuscripts_brought_back"] == 1 and stats["steps_made"] == 0
    assert projects.steps_taken(vault, "calls") == []
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert b"COMMENT: lovely" in path.read_bytes()  # git didn't move, so the copy stays
    assert state(vault)["projects"]["calls"]["files"][DOCX]["seen"] == folders._sha(path)

    # Changes that come back to the manuscript as it is bring nothing back either.
    edit(path, "Methods follow.\n", "Methods follow.   \n")
    stats = run(vault, LATEST)
    assert stats["manuscripts_brought_back"] == 1 and stats["steps_made"] == 0
    assert projects.steps_taken(vault, "calls") == []


def test_latex_goes_one_way_with_its_citations_from_the_bib_beside_it(setup):
    vault, repo, drive, fake = setup
    git(repo, "checkout", "-q", "paper-storyline")
    commit(
        repo,
        {
            "docs/paper/paper.md": b"",
            "paper/main.tex": LATEX,
            "paper/refs.bib": "@article{smith2020, title={Dawn}}\n",
            "paper/sections/methods.tex": "We listened.\n",
            "paper/main.pdf": b"%PDF-1.7 typeset",
        },
        "Move to LaTeX",
        3,
    )
    git(repo, "rm", "-q", "docs/paper/paper.md")
    git(repo, "commit", "-q", "-m", "Drop the Markdown")
    git(repo, "checkout", "-q", "main")

    run(vault, NOW)

    where = drive / FOLDER
    made = next(m for m in fake.made if m["name"] == "main.tex")
    assert made["kind"] == "latex"
    # Converted from its folder as git has it, with what it includes and the .bib beside it,
    # and typeset there, from the same commit: not the PDF committed beside it.
    assert made["beside"] == ["main.tex", "refs.bib", "sections/methods.tex"]
    assert fake.pdfs == [made]
    assert text_of(where / DOCX) == text_of(where / PDF) == LATEX
    assert state(vault)["projects"]["calls"]["files"][PDF]["made"] == "built"
    assert not (where / SUPPLEMENTARY).exists()  # it names no table or figure
    folder = text_of(where / "About this folder.docx")
    assert "goes one way" in folder and "Change paper/main.tex itself" in folder
    assert "pull" not in state(vault)["projects"]["calls"]
    assert not (vault / "clones" / "folders" / "calls" / "baseline.md").exists()

    # The owner's changes never come back; once the paper moves on, their copy goes to Earlier/.
    edit(where / DOCX, "Birds sing at dawn", "Birds sing loudly at dawn")
    mine = (where / DOCX).read_bytes()
    stats = run(vault, LATER)
    assert stats["manuscripts_brought_back"] == 0 and projects.steps_taken(vault, "calls") == []
    assert (where / DOCX).read_bytes() == mine
    assert len(fake.pdfs) == 1  # nothing changed: nothing typeset
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"paper/sections/methods.tex": "We listened twice.\n"}, "Listen again", 4)
    git(repo, "checkout", "-q", "main")
    stats = run(vault, LATEST)
    assert stats["moved_to_earlier"] == 1 and stats["steps_made"] == 0
    assert (where / "Earlier" / "Calls the paper - manuscript 2026-03-12.docx").read_bytes() == mine
    assert text_of(where / DOCX) == LATEX
    # Typeset again with it, from the same checkout.
    [*_, made] = [m for m in fake.made if m["name"] == "main.tex"]
    assert len(fake.pdfs) == 2 and fake.pdfs[-1] == made != fake.pdfs[0]
    assert text_of(where / PDF) == LATEX


def test_the_pdf_moves_on_with_the_word_file_never_over_the_owners_copy(setup):
    vault, repo, drive, fake = setup
    run(vault, NOW)
    where = drive / FOLDER
    (where / PDF).write_bytes(b"%PDF the owner's annotated copy")

    # Nothing changed: their copy stays, and nothing is typeset.
    stats = run(vault, LATER)
    assert stats["files_written"] == 0 and len(fake.pdfs) == 2
    assert (where / PDF).read_bytes() == b"%PDF the owner's annotated copy"

    # The paper moves on: both are made again from the new commit, in one checkout, and their
    # copy of the PDF moves to Earlier/ first.
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": PAPER.replace("Thanks", "Our thanks")}, "Thank", 3)
    git(repo, "checkout", "-q", "main")
    stats = run(vault, LATEST)
    assert stats["moved_to_earlier"] == 1
    assert text_of(where / DOCX) == text_of(where / PDF) == PAPER.replace("Thanks", "Our thanks")
    [*_, made] = [m for m in fake.made if m["name"] == "paper.md"]
    assert fake.pdfs[-1] == made
    assert (where / "Earlier" / "Calls the paper - manuscript 2026-03-12.pdf").read_bytes() == (
        b"%PDF the owner's annotated copy"
    )
    files = state(vault)["projects"]["calls"]["files"]
    assert files[PDF]["source"] == folders._digest(files[DOCX]["source"], "pdf")


def test_with_nothing_to_make_pdfs_the_committed_one_comes_and_the_folder_says_so(
    setup, monkeypatch
):
    vault, repo, drive, fake = setup
    engine = None
    monkeypatch.setattr(folders, "pdf_engine", lambda kind: engine)

    run(vault, NOW)

    where = drive / FOLDER
    assert fake.pdfs == []
    assert (where / PDF).read_bytes() == b"%PDF-1.7 the paper"
    assert not (where / "Supplementary information.pdf").exists()  # none is committed
    assert (where / SUPPLEMENTARY).exists()
    folder = text_of(where / "About this folder.docx")
    assert f"**{PDF}** is docs/paper/paper.pdf as it's committed in git" in folder
    assert "brew install tectonic" in folder
    assert run(vault, LATER)["files_written"] == 0

    # tectonic installed: the PDF is made from the Word file's version, which isn't made again.
    engine = "/opt/homebrew/bin/tectonic"
    made = len(fake.made)
    stats = run(vault, LATEST)
    assert text_of(where / PDF) == PAPER and len(fake.pdfs) == 2  # and the supplement's
    assert len(fake.made) == made + 1  # only the About this folder note, which says so
    assert stats["files_written"] == 3 and "moved_to_earlier" not in stats
    assert "so the two match" in text_of(where / "About this folder.docx")

    # Neither a way to make one nor one committed: none, and the folder says why.
    engine = None
    git(repo, "checkout", "-q", "paper-storyline")
    git(repo, "rm", "-q", "docs/paper/paper.pdf")
    git(repo, "commit", "-q", "-m", "No PDF")
    git(repo, "checkout", "-q", "main")
    (where / PDF).unlink()
    run(vault, LATEST.replace(hour=3))
    assert not (where / PDF).exists()
    assert "There's no PDF of this version" in text_of(where / "About this folder.docx")


def test_a_pdf_that_cant_be_made_isnt_tried_again_until_the_paper_changes(setup, capsys):
    vault, repo, drive, fake = setup
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"paper/main.tex": LATEX, "paper/refs.bib": "@article{a, title={A}}\n"}, "Tex", 3)
    git(repo, "rm", "-q", "docs/paper/paper.md")
    git(repo, "commit", "-q", "-m", "Drop the Markdown")
    git(repo, "checkout", "-q", "main")
    fake.fails = "tectonic: error: main.tex:3: Undefined control sequence"

    stats = run(vault, NOW)

    where = drive / FOLDER
    assert stats["skipped"] == 1 and len(fake.pdfs) == 1
    assert text_of(where / DOCX) == LATEX and not (where / PDF).exists()
    assert "manuscript.pdf wasn't made (tectonic: error: main.tex:3" in capsys.readouterr().err
    folder = text_of(where / "About this folder.docx")
    assert f"**{PDF}** couldn't be made from this version (tectonic: error: main.tex:3" in folder

    # A LaTeX build takes a while: not again for the same version.
    stats = run(vault, LATER)
    assert len(fake.pdfs) == 1 and stats["skipped"] == 0 and stats["files_written"] == 0

    # Once the paper changes, it's tried again, and made.
    fake.fails = ""
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"paper/main.tex": LATEX.replace("dawn", "dusk")}, "Dusk", 4)
    git(repo, "checkout", "-q", "main")
    run(vault, LATEST)
    assert len(fake.pdfs) == 2 and text_of(where / PDF) == LATEX.replace("dawn", "dusk")
    entry = state(vault)["projects"]["calls"]["files"][PDF]
    assert entry["made"] == "built" and "unmade" not in entry


def test_an_edit_says_where_its_text_came_from(setup):
    vault, _, _, _ = setup
    project = projects.listed_projects(vault)[0]
    request = {"path": "docs/paper/paper.md", "branch": "paper-storyline", "text": "New.\n"}
    with pytest.raises(ValueError, match="no edit comes from"):
        manuscript.edit(vault, project, request, NOW, source="email")


def test_links_are_drive_addresses_only_once_drive_has_synced_the_files(tmp_path, monkeypatch):
    where = tmp_path / "PhD" / "Calls"
    where.mkdir(parents=True)
    (where / "Calls - manuscript.docx").write_bytes(b"x")
    assert folders._links(where) == {"folder": "", "manuscript": "", "pdf": ""}  # not synced

    def synced(cmd, **kw):
        item = "1AbC_d-EfGhIjKlMnOp" if cmd[-1].endswith((".docx", "Calls")) else ""
        return subprocess.CompletedProcess(cmd, 0 if item else 1, stdout=item, stderr="")

    monkeypatch.setattr(folders.sys, "platform", "darwin")
    monkeypatch.setattr(folders.subprocess, "run", synced)
    assert folders._links(where) == {
        "folder": "https://drive.google.com/drive/folders/1AbC_d-EfGhIjKlMnOp",
        "manuscript": "https://drive.google.com/file/d/1AbC_d-EfGhIjKlMnOp/view",
        "pdf": "",  # none written
    }


def test_the_word_files_are_in_arial_with_black_headings(tmp_path, monkeypatch):
    import io
    import zipfile

    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as z:
        z.writestr(
            "word/theme/theme1.xml",
            '<a:latin typeface="Aptos Display"/><a:latin typeface="Aptos"/>',
        )
        z.writestr(
            "word/styles.xml",
            '<w:color w:val="0F4761"/><w:color w:val="595959"/>'
            '<w:style w:styleId="Table"><w:tblPr><w:tblInd/></w:tblPr></w:style>',
        )
        z.writestr("word/document.xml", "<w:document/>")
    asked = []

    def run(cmd, **kw):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=made.getvalue(), stderr=b"")

    monkeypatch.setattr(folders, "pandoc", lambda: "pandoc")
    monkeypatch.setattr(folders.subprocess, "run", run)
    monkeypatch.setattr(folders.tempfile, "gettempdir", lambda: str(tmp_path))
    reference = folders._reference()
    with zipfile.ZipFile(reference) as z:
        assert z.read("word/theme/theme1.xml").decode().count('typeface="Arial"') == 2
        assert (
            z.read("word/styles.xml").decode().split("<w:style ")[0]
            == '<w:color w:val="000000"/><w:color w:val="595959"/>'
        )
        table = z.read("word/styles.xml").decode().split("<w:style ")[1]
        assert '<w:tblPr><w:tblBorders><w:top w:val="single"' in table and "insideV" in table
        assert z.read("word/document.xml") == b"<w:document/>"
    assert folders._reference() == reference and len(asked) == 1  # made once


def word_with_comments(path):
    """A Word file as Word or Google Docs saves one with comments: one on a passage, one in
    general, and one resolved."""
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    w14 = 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
    w15 = 'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"'
    document = (
        f"<w:document {w}><w:body><w:p><w:r><w:t>Birds sing at </w:t></w:r>"
        '<w:commentRangeStart w:id="0"/><w:r><w:t>dawn and </w:t></w:r><w:r><w:t>dusk</w:t></w:r>'
        '<w:commentRangeEnd w:id="0"/><w:commentRangeStart w:id="2"/><w:r><w:t>.</w:t></w:r>'
        '<w:commentRangeEnd w:id="2"/></w:p></w:body></w:document>'
    )
    said = (
        f"<w:comments {w} {w14}>"
        '<w:comment w:id="0" w:author="Ana Lee" w:date="2026-03-11T09:00:00Z">'
        '<w:p w14:paraId="A1"><w:r><w:t>Say which species.</w:t></w:r></w:p></w:comment>'
        '<w:comment w:id="1" w:author="Joe" w:date="2026-03-11T09:05:00Z">'
        '<w:p w14:paraId="B2"><w:r><w:t>Shorten the abstract.</w:t></w:r></w:p></w:comment>'
        '<w:comment w:id="2" w:author="Ana Lee" w:date="2026-03-11T09:10:00Z">'
        '<w:p w14:paraId="C3"><w:r><w:t>Typo, fixed.</w:t></w:r></w:p></w:comment>'
        "</w:comments>"
    )
    extended = (
        f'<w15:commentsEx {w15}><w15:commentEx w15:paraId="C3" w15:done="1"/></w15:commentsEx>'
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/comments.xml", said)
        z.writestr("word/commentsExtended.xml", extended)


def test_comments_on_a_manuscript_become_a_step_once(setup):
    from proxenos.clones import steps

    vault, repo, drive, _ = setup
    git(repo, "checkout", "-q", "paper-storyline")
    commit(
        repo, {"paper/main.tex": LATEX, "paper/refs.bib": "@article{a, title={A}}\n"}, "LaTeX", 3
    )
    git(repo, "checkout", "-q", "main")
    run(vault, NOW)
    copy = drive / FOLDER / DOCX
    word_with_comments(copy)

    assert [c["text"] for c in folders.comments(copy)] == [
        "Say which species.",
        "Shorten the abstract.",
    ]
    assert folders.comments(copy)[0]["on"] == "dawn and dusk"
    stats = run(vault, NOW + timedelta(days=1))
    assert stats["comments_queued"] == 2
    (queued,) = steps.queued(vault, "calls")
    assert queued["manuscript"] == {"path": "paper/main.tex", "branch": "paper-storyline"}
    assert "1. On “dawn and dusk” (Ana Lee): Say which species." in queued["text"]
    assert "2. In general (Joe): Shorten the abstract." in queued["text"]
    assert "Typo" not in queued["text"]  # resolved
    assert "comments_queued" not in run(vault, NOW + timedelta(days=2))  # each once
    assert len(steps.queued(vault, "calls")) == 1
    assert folders.comments(drive / "not a word file.docx") == []


def test_the_files_a_manuscript_names_go_to_its_supplement(setup):
    vault, repo, drive, _ = setup
    git(repo, "checkout", "-q", "paper-storyline")
    paper = (
        "# Calls\n\nBirds sing at dawn (Table S1, `results/S01_tableS1_sites.csv`).\n\n"
        "![Calls by hour](figures/fig2.png)\n\nSee also notes.txt, which isn't there.\n"
    )
    commit(
        repo,
        {
            "docs/paper/paper.md": paper,
            "results/S01_tableS1_sites.csv": "site,n\nA,3\n",
            "results/S99_unnamed.csv": "not named in the paper\n",
            "figures/fig2.png": b"\x89PNG fake",
        },
        "Tables and a figure",
        3,
    )
    git(repo, "checkout", "-q", "main")

    run(vault, NOW)

    supplement = drive / FOLDER / "Supplement"
    assert sorted(p.name for p in supplement.iterdir()) == ["S01_tableS1_sites.csv", "fig2.png"]
    assert (supplement / "S01_tableS1_sites.csv").read_text() == "site,n\nA,3\n"
    # One the user changed is never written over; an unchanged one isn't written again.
    (supplement / "fig2.png").write_bytes(b"their annotated figure")
    stats = run(vault, NOW + timedelta(days=1))
    assert (supplement / "fig2.png").read_bytes() == b"their annotated figure"
    assert stats.get("files_written", 0) == 0


SUPPLEMENTED = (
    "# Calls\n\n"
    "Birds sing at dawn (Table S1, `results/S01_tableS1_sites.csv`), as counted in\n"
    "data/counts.json.\n\n"
    "![Calls by hour](figures/fig2.png)\n\n"
    "Wrens and robins differ (S02_tableS4_note_types_by_species.csv).\n\n"
    "## Supplementary material\n\n"
    "**Table S4.** Note types by species (S02_tableS4_note_types_by_species.csv)\n\n"
    "- The workbook (results/S03_book.xlsx)\n"
)


def wide(rows, columns):
    head = ",".join(f"c{j}" for j in range(columns))
    body = "".join(",".join(f"r{i}c{j}" for j in range(columns)) + "\n" for i in range(rows))
    return f"{head}\n{body}"


def test_the_supplement_is_a_document_of_its_tables_and_figures_under_their_captions(
    setup, monkeypatch
):
    vault, repo, drive, fake = setup
    monkeypatch.setitem(sys.modules, "openpyxl", None)  # not installed: .xlsx is listed by name
    git(repo, "checkout", "-q", "paper-storyline")
    files = {
        "docs/paper/paper.md": SUPPLEMENTED,
        "results/S01_tableS1_sites.csv": "site,n\nA,3\nB|C,*4*\n",
        "results/S02_tableS4_note_types_by_species.csv": wide(50, 15),
        "results/S03_book.xlsx": b"PK not read",
        "figures/fig2.png": b"\x89PNG fake",
        "data/counts.json": "{}\n",
    }
    commit(repo, files, "Tables, a figure and data", 3)
    git(repo, "checkout", "-q", "main")

    run(vault, NOW)

    where = drive / FOLDER
    assert sorted(p.name for p in (where / "Supplement").iterdir()) == [
        "S01_tableS1_sites.csv",
        "S02_tableS4_note_types_by_species.csv",
        "S03_book.xlsx",
        "counts.json",
        "fig2.png",
    ]
    text = text_of(where / SUPPLEMENTARY)
    assert text == text_of(where / "Supplementary information.pdf")
    [made] = [m for m in fake.made if m["name"] == "supplementary.md"]
    assert made["beside"] == ["figures/fig2.png", "supplementary.md"]
    assert fake.pdfs[-1] == made  # the same Markdown, figures beside it
    head, s1, figure, s4, data = text.split("\n## ")
    assert head == "# Calls: the paper?: supplementary information\n"
    # Each table under the caption the manuscript gives it, in the order it names them: the
    # "Table S1" it's named with, or the line that names it, from its label.
    assert s1 == "Table S1\n\n| site | n |\n|---|---|\n| A | 3 |\n| B\\|C | \\*4\\* |\n"
    assert figure == "Calls by hour\n\n![](<figures/fig2.png>)\n"
    caption, _, table = s4.partition("\n\n")
    assert caption == "Table S4. Note types by species"
    rows = table.strip().split("\n")
    assert rows[0] == "| " + " | ".join(f"c{j}" for j in range(12)) + " |"
    assert len(rows) == 2 + 40 + 2 and rows[-3].startswith("| r39c0 | ") and rows[-2] == ""
    assert rows[-1] == (
        "_This is the first 40 of its 50 rows and 12 of its 15 columns: the full table is in "
        "Supplement/S02\\_tableS4\\_note\\_types\\_by\\_species.csv._"
    )
    # The data files, and a workbook with nothing here to read it, by name.
    assert data == (
        "Data files\n\nIn Supplement/, beside this file:\n\n- counts.json\n- S03\\_book.xlsx\n"
    )

    # Nothing changed: nothing made again.
    made, pdfs = len(fake.made), len(fake.pdfs)
    assert run(vault, LATER)["files_written"] == 0
    assert (len(fake.made), len(fake.pdfs)) == (made, pdfs)

    # One the owner changed stays as they left it while nothing changes, and moves to Earlier/
    # once a table it shows does.
    edit(where / SUPPLEMENTARY, "Table S1", "Table S1 (checked)")
    mine = (where / SUPPLEMENTARY).read_bytes()
    stats = run(vault, LATEST)
    assert stats["files_written"] == 0 and (where / SUPPLEMENTARY).read_bytes() == mine
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"results/S01_tableS1_sites.csv": "site,n\nA,5\n"}, "Recount", 4)
    git(repo, "checkout", "-q", "main")
    stats = run(vault, LATEST.replace(hour=3))
    assert stats["moved_to_earlier"] == 1
    earlier = where / "Earlier" / "Supplementary information 2026-03-12.docx"
    assert earlier.read_bytes() == mine
    assert "| A | 5 |" in text_of(where / SUPPLEMENTARY)
    assert "| A | 5 |" in text_of(where / "Supplementary information.pdf")


def test_an_svg_figure_is_named_in_the_pdf_until_pandoc_can_draw_it(setup, monkeypatch):
    vault, repo, drive, fake = setup
    rsvg = None
    monkeypatch.setattr(folders.shutil, "which", lambda name: rsvg)
    git(repo, "checkout", "-q", "paper-storyline")
    paper = "# Calls\n\n![Calls by hour](figures/fig2.svg)\n"
    commit(repo, {"docs/paper/paper.md": paper, "figures/fig2.svg": "<svg/>"}, "SVG", 3)
    git(repo, "checkout", "-q", "main")

    run(vault, NOW)

    where = drive / FOLDER
    assert "## Calls by hour\n\n![](<figures/fig2.svg>)\n" in text_of(where / SUPPLEMENTARY)
    pdf = text_of(where / "Supplementary information.pdf")
    assert "![](" not in pdf and "it's in Supplement/fig2.svg, and the Word file shows it" in pdf

    # rsvg-convert installed: the PDF is made again, showing it; the Word file isn't.
    rsvg = "/opt/homebrew/bin/rsvg-convert"
    made = len(fake.made)
    run(vault, LATER)
    assert "![](<figures/fig2.svg>)" in text_of(where / "Supplementary information.pdf")
    assert len(fake.made) == made


def test_a_paper_naming_only_data_gets_no_supplement_document(setup):
    vault, repo, drive, _ = setup
    git(repo, "checkout", "-q", "paper-storyline")
    commit(
        repo, {"docs/paper/paper.md": "# Calls\n\nIn counts.json.\n", "counts.json": "{}"}, "D", 3
    )
    git(repo, "checkout", "-q", "main")
    run(vault, NOW)
    assert (drive / FOLDER / "Supplement" / "counts.json").exists()
    assert not (drive / FOLDER / SUPPLEMENTARY).exists()


def test_a_latex_paper_names_its_files_as_latex_writes_them(setup):
    vault, repo, drive, _ = setup
    git(repo, "checkout", "-q", "paper-storyline")
    latex = (
        "\\documentclass{article}\n\\begin{document}\nBirds sing at dawn.\n"
        "\\begin{table}\n\\caption{Sites and counts.}\n"
        "\\csvautotabular{results/S01\\_sites.csv}\n\\end{table}\n\\end{document}\n"
    )
    commit(repo, {"paper/main.tex": latex, "results/S01_sites.csv": "site,n\nA,3\n"}, "Tex", 3)
    git(repo, "rm", "-q", "docs/paper/paper.md")
    git(repo, "commit", "-q", "-m", "Drop the Markdown")
    git(repo, "checkout", "-q", "main")
    run(vault, NOW)
    where = drive / FOLDER
    assert (where / "Supplement" / "S01_sites.csv").read_text() == "site,n\nA,3\n"
    assert "## Sites and counts.\n\n| site | n |" in text_of(where / SUPPLEMENTARY)


def test_what_went_wrong_is_the_line_that_says_so():
    tex = (
        "error: main.tex:3: Missing $ inserted\n"
        "error: something bad happened inside XeTeX; its output follows:\n\n===\n"
        "! Missing $ inserted.\n===\n"
        "error: the XeTeX engine had an unrecoverable error\n"
        "caused by: halted on potentially-recoverable error as specified\n"
    )
    assert folders._why(tex) == "error: main.tex:3: Missing $ inserted"
    image = (
        "warning: 8-byte read failed\ncaused by: failed to fill whole buffer\n"
        "error: something bad happened inside xdvipdfmx; its output follows:\n===\n"
        "error: the xdvipdfmx engine had an unrecoverable error\n"
        "caused by: error reading PNG\nError producing PDF.\n"
    )
    assert folders._why(image) == (
        "error: the xdvipdfmx engine had an unrecoverable error (error reading PNG)"
    )
    assert folders._why("[WARNING] slow\npandoc: paper.md: does not exist\n") == (
        "pandoc: paper.md: does not exist"
    )
    assert folders._why("") == ""


def test_captions_come_from_where_the_manuscript_names_the_file():
    latex = (
        "Calls rise at dawn (Fig.~\\ref{fig:3}).\n"
        "\\begin{figure}\n\\includegraphics[width=\\linewidth]{figures/fig3.pdf}\n"
        "\\caption[Short]{Calls by \\emph{hour}, at three sites.\\label{fig:3}}\n\\end{figure}\n"
        "\\begin{itemize}\n\\item Site coordinates (sites.tsv)\n\\end{itemize}\n"
    )
    assert folders._caption(latex, "figures/fig3.pdf") == "Calls by hour, at three sites."
    assert folders._caption(latex, "sites.tsv") == "Site coordinates"
    prose = (
        "We counted wrens (counts.csv), as before.\n\n"
        "As Table S2 shows, robins sing later (robins.csv).\n\n"
        "Supplementary Table S3: Robins by hour (robins.csv)\n"
    )
    assert folders._caption(prose, "counts.csv") == ""  # its name stands in
    # A label in the middle of a sentence doesn't make it a caption; a later line that is one does.
    assert folders._caption(prose, "robins.csv") == "Supplementary Table S3: Robins by hour"
    assert folders._caption(prose, "missing.csv") == ""
    cited = "Birds sing \\cite{a}. The counts are in Table S1 (\\texttt{results/S01_sites.csv}).\n"
    assert folders._caption(cited, "results/S01_sites.csv") == "Table S1"


def test_a_workbook_is_a_table_where_openpyxl_is_installed(monkeypatch):
    sheet = [("site", "n", None), ("A", 3, 0.5), (None, None, None), ("B", 4, None)]
    book = SimpleNamespace(worksheets=[SimpleNamespace(iter_rows=lambda values_only: iter(sheet))])
    fake = SimpleNamespace(load_workbook=lambda data, read_only, data_only: book)
    monkeypatch.setattr(folders, "_openpyxl", lambda: fake)
    assert folders._table("book.xlsx", b"PK") == (
        [["site", "n", ""], ["A", "3", "0.5"], ["B", "4", ""]],
        2,
        3,
    )
    assert folders._table("notes.json", b"{}") is None


def test_a_markdown_pdf_goes_again_with_sub_and_superscript_marks_read_as_written(
    tmp_path, monkeypatch
):
    readers = []

    def pandoc(*args, cwd, seconds):
        readers.append(args[args.index("-f") + 1])
        if args[args.index("-f") + 1] == "markdown":
            raise folders.ConvertError("Argument of \\textsubscript has an extra }")

    monkeypatch.setattr(folders, "pdf_engine", lambda kind: "tectonic")
    monkeypatch.setattr(folders, "_pandoc", pandoc)
    folders.to_pdf(tmp_path / "paper.md", tmp_path / "paper.pdf", "markdown")
    assert readers == ["markdown", "markdown-subscript-superscript"]

    def broken(*args, cwd, seconds):
        readers.append("again")
        raise folders.ConvertError(f"failed with {args[args.index('-f') + 1]}")

    monkeypatch.setattr(folders, "_pandoc", broken)
    with pytest.raises(folders.ConvertError, match="failed with markdown$"):  # the first error
        folders.to_pdf(tmp_path / "paper.md", tmp_path / "paper.pdf", "markdown")


def test_tracked_changes_in_markdown_are_taken_for_the_copies():
    revised = folders.accept_marks(
        "We {~~think~>show~~} that {++beta ++}synchrony {--clearly --}rises{>>check<<} "
        "{==here==}.\n\nLegend: `{~~old~>new~~}` is a replacement.\n"
    )
    assert (
        revised
        == "We show that beta synchrony rises here.\n\nLegend: `{~~old~>new~~}` is a replacement.\n"
    )
    assert folders.accept_marks("No marks at all.") == "No marks at all."
