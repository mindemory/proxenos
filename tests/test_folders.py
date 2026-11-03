"""Each project as a folder in a cloud drive, against a folder and a small git repository made
here and a fake pandoc. No network, no model, no pandoc, no real document and no real drive."""

import json
import os
import stat
import subprocess
from datetime import UTC, datetime

import pytest

from proxenos import cli, manuscript
from proxenos.clones import folders, projects, steps, work

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 11, 2, 0, tzinfo=UTC)
LATEST = datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
FOLDER = "PhD/Calls the paper"  # "Calls: the paper?", made safe
DOCX = "Calls the paper - manuscript.docx"

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
    """pandoc as these tests see it. A Word file it makes is a line naming what it was made from,
    then the text; read back, emphasis and lists come in Word's reading of them (_x_, * x), so
    the Markdown that comes back differs from the manuscript's own, as pandoc's does, and lines
    that are comments in Word ("COMMENT: ...") aren't text. It keeps what each conversion was
    given, with the files beside it."""

    def __init__(self):
        self.made = []

    def to_docx(self, source, out, kind):
        beside = sorted(
            p.relative_to(source.parent).as_posix() for p in source.parent.rglob("*") if p.is_file()
        )
        self.made.append({"name": source.name, "kind": kind, "beside": beside})
        out.write_bytes(f"DOCX from {kind}\n".encode() + source.read_bytes())

    def to_markdown(self, docx):
        head, _, body = docx.read_bytes().decode().partition("\n")
        assert head.startswith("DOCX from ")
        body = "".join(line for line in body.splitlines(True) if not line.startswith("COMMENT:"))
        return body.replace("*loudly*", "_loudly_").replace("- ", "* ")


def text_of(path):
    """What a Word file the fake made says, without its first line."""
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
    """A drive's folder, a fake pandoc, a vault, and a project's repository checked out on main
    with its paper, a figure and a PDF of it on a side branch."""
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
    monkeypatch.setattr(folders, "pandoc", lambda: "/usr/local/bin/pandoc")
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
    )
    note(vault, "resting", "status.md", "# Resting\n\nOn hold until June.\n")
    before = checkout_of(repo)

    stats = run(vault, NOW)

    assert stats == {
        "folders_written": 3,
        "files_written": 6 + 3 + 3,
        "kept_as_edited": 0,
        "manuscripts_brought_back": 0,
        "steps_made": 0,
        "skipped": 1,
    }
    where = drive / "PhD" / "Calls the paper"
    assert sorted(p.name for p in where.iterdir()) == sorted(
        [
            DOCX,
            "Calls the paper - manuscript.pdf",
            "Where it stands.docx",
            "What's known, and the question.docx",
            "Drafts.docx",
            "About this project.docx",
            "About this folder.docx",
        ]
    )
    # The manuscript at its branch's tip, converted where the files beside it are, and nothing
    # else of the repository; its PDF as committed.
    assert text_of(where / DOCX) == PAPER
    made = next(m for m in fake.made if m["name"] == "paper.md")
    assert made["kind"] == "markdown" and made["beside"] == ["fig.png", "paper.md"]
    assert (where / "Calls the paper - manuscript.pdf").read_bytes() == b"%PDF-1.7 the paper"
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
    assert "comes back to the project's git as a step" in folder

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

    # Again with nothing changed: nothing written.
    again = run(vault, LATER)
    assert again["files_written"] == 0 and again["folders_written"] == 0
    assert len(fake.made) == 11  # the 12 files the first time, but for the PDF, copied as it is


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
    # Converted from its folder as git has it, with what it includes and the .bib beside it.
    assert made["beside"] == ["main.tex", "refs.bib", "sections/methods.tex"]
    assert text_of(where / DOCX) == LATEX
    assert (where / "Calls the paper - manuscript.pdf").read_bytes() == b"%PDF-1.7 typeset"
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
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"paper/sections/methods.tex": "We listened twice.\n"}, "Listen again", 4)
    git(repo, "checkout", "-q", "main")
    stats = run(vault, LATEST)
    assert stats["moved_to_earlier"] == 1 and stats["steps_made"] == 0
    assert (where / "Earlier" / "Calls the paper - manuscript 2026-03-12.docx").read_bytes() == mine
    assert text_of(where / DOCX) == LATEX


def test_an_edit_says_where_its_text_came_from(setup):
    vault, _, _, _ = setup
    project = projects.listed_projects(vault)[0]
    request = {"path": "docs/paper/paper.md", "branch": "paper-storyline", "text": "New.\n"}
    with pytest.raises(ValueError, match="no edit comes from"):
        manuscript.edit(vault, project, request, NOW, source="email")
