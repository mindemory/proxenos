"""A project's manuscript, its versions and their changes, and the user's edits to it, on small
git repositories made here. No model, no real data, and no real repository."""

import argparse
import io
import json
import os
import subprocess
from datetime import UTC, datetime

import pytest

from proxenos import agent, cli, manuscript
from proxenos.clones import projects, steps

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 11, 2, 0, tzinfo=UTC)

FIRST = "# Birdsong at dawn\n\nThe birds sang at dawn.\n\nMethods follow.\n"
SECOND = "# Birdsong at dawn\n\nThe birds sang loudly at dawn.\n\nMethods follow, in short.\n"


def git(where, *args):
    return subprocess.run(
        ["git", "-C", str(where), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo, files, message, when):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    stamp = f"2026-03-0{when}T12:00:00+00:00"
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        env=dict(os.environ) | {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A vault, and a project's repository checked out on main, with its paper on a side branch
    in two versions and a decoy note on main."""
    monkeypatch.setenv("PROXENOS_WORKTREES", str(tmp_path / "worktrees"))
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Joe")
    git(repo, "config", "user.email", "joe@example.org")
    commit(repo, {"analysis.py": "print('mean')\n", "notes/todo.md": "- read\n"}, "Start", 1)
    git(repo, "checkout", "-q", "-b", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": FIRST}, "Draft the paper", 2)
    commit(repo, {"docs/paper/paper.md": SECOND}, "Tighten the opening", 3)
    git(repo, "checkout", "-q", "main")
    commit(repo, {"notes/todo.md": "- read\n- write\n"}, "More to do", 4)
    vault = tmp_path / "vault"
    write_list(vault, {"id": "calls", "name": "Calls", "repo": str(repo)})
    return vault, repo


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": list(items)}))


def project(vault):
    return projects.listed_projects(vault)[0]


def checkout_of(repo):
    """What the user's own checkout holds: its branch, commit, status and files."""
    files = {
        p.name: p.read_text()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }
    return (
        git(repo, "branch", "--show-current"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "status", "--porcelain"),
        files,
    )


def rebuilt(ops):
    """(old, new) from the ops."""
    old = "".join(o["text"] for o in ops if o["op"] != "add")
    new = "".join(o["text"] for o in ops if o["op"] != "del")
    return old, new


def test_the_paper_is_found_on_a_branch_the_checkout_isnt_on(setup):
    vault, repo = setup
    before = checkout_of(repo)

    found = manuscript.find(project(vault))

    assert found == {"path": "docs/paper/paper.md", "branch": "paper-storyline", "named": False}
    assert checkout_of(repo) == before

    # Named in projects.json, it's taken as named, its branch found when it isn't given.
    write_list(
        vault, {"id": "calls", "name": "Calls", "repo": str(repo), "manuscript": "notes/todo.md"}
    )
    assert manuscript.find(project(vault)) == {
        "path": "notes/todo.md",
        "branch": "main",
        "named": True,
    }
    write_list(
        vault,
        {
            "id": "calls",
            "name": "Calls",
            "repo": str(repo),
            "manuscript": {"path": "docs/paper/paper.md", "branch": "paper-storyline"},
        },
    )
    assert manuscript.find(project(vault))["named"] is True


def test_a_repository_with_no_paper_says_so(tmp_path, monkeypatch):
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Joe")
    git(repo, "config", "user.email", "joe@example.org")
    commit(repo, {"README.md": "# Code\n", "paper/figures.py": "pass\n"}, "Start", 1)
    vault = tmp_path / "vault"
    write_list(vault, {"id": "calls", "name": "Calls", "repo": str(repo)})
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert manuscript.find(project(vault)) is None
    answer = manuscript.run(vault, args("calls"))
    assert answer["manuscript"] is None and "Name it in projects.json" in answer["why"]


def test_its_versions_and_their_changes_word_by_word(setup):
    vault, _ = setup
    p = project(vault)
    found = manuscript.find(p)

    listed = manuscript.versions(p, found)

    assert [v["subject"] for v in listed] == ["Tighten the opening", "Draft the paper"]
    assert listed[0] | {"commit": "", "short": ""} == {
        "commit": "",
        "short": "",
        "date": "2026-03-03T12:00:00Z",
        "author": "Joe",
        "subject": "Tighten the opening",
        "branch": "paper-storyline",
        "proxenos": False,
        "edit": False,
        "step": None,
        "path": "docs/paper/paper.md",
    }

    # By default, the newest against the one before it.
    shown = manuscript.compare(p, found)
    assert (shown["base"], shown["head"]) == (listed[1]["commit"], listed[0]["commit"])
    assert shown["text"] == SECOND and shown["editable"] and shown["kind"] == "prose"
    assert rebuilt(shown["ops"]) == (FIRST, SECOND)
    assert [o["text"].strip() for o in shown["ops"] if o["op"] == "add"] == ["loudly", ", in short"]
    assert [o for o in shown["ops"] if o["op"] == "del"] == []
    assert (shown["added"], shown["removed"]) == (3, 0)
    # The paragraphs that didn't change come through whole.
    assert shown["ops"][0] == {"op": "same", "text": "# Birdsong at dawn\n\nThe birds sang"}

    # Any two versions, either way round; an older head can't be edited.
    back = manuscript.compare(p, found, base=listed[0]["commit"], head=listed[1]["short"])
    assert rebuilt(back["ops"]) == (SECOND, FIRST) and back["removed"] == 3
    assert not back["editable"]
    with pytest.raises(SystemExit, match="no version"):
        manuscript.compare(p, found, base="--output=/tmp/x")


def test_the_diff_keeps_paragraphs_and_reads_whole_changes():
    old = "One two three.\n\nFour five six.\n\nSeven.\n"
    new = "One two three.\n\nFour nine ten six.\n\nA new one.\n\nSeven.\n"
    ops = manuscript.diff(old, new)
    assert rebuilt(ops) == (old, new)
    assert ops == [
        {"op": "same", "text": "One two three.\n\nFour "},
        {"op": "del", "text": "five"},
        {"op": "add", "text": "nine ten"},
        {"op": "same", "text": " six.\n\n"},
        {"op": "add", "text": "A new one.\n\n"},
        {"op": "same", "text": "Seven.\n"},
    ]
    code = manuscript.diff("a = 1\nb = 2\nc = 3\n", "a = 1\nb = 20\nc = 3\n", prose=False)
    assert code == [
        {"op": "same", "text": "a = 1\n"},
        {"op": "del", "text": "b = 2\n"},
        {"op": "add", "text": "b = 20\n"},
        {"op": "same", "text": "c = 3\n"},
    ]
    assert manuscript.diff("", "") == []


class Runner:
    """A step's runner, faked: it rewrites a sentence of the paper and changes the script."""

    name, label = "claude", "Claude Code"

    def __init__(self, sentence="The birds sang softly at dawn."):
        self.tasks = []
        self.sentence = sentence

    def __call__(self, task):
        self.tasks.append(task)
        paper = task.folder / "docs" / "paper" / "paper.md"
        if paper.exists():
            text = paper.read_text().replace("The birds sang loudly at dawn.", self.sentence)
            paper.write_text(text)
        (task.folder / "analysis.py").write_text("print('median')\n")
        return {
            "step": "Soften the opening",
            "why": "",
            "did": "Changed a sentence.",
            "found": "",
            "figures": [],
            "couldnt": "",
            "next": "",
            "commit": "Soften the opening",
        }


def test_a_change_asked_for_starts_from_the_manuscripts_branch(setup):
    vault, repo = setup
    p = project(vault)
    paper = {"path": "docs/paper/paper.md", "branch": "paper-storyline"}
    tip = git(repo, "rev-parse", "paper-storyline")
    with pytest.raises(SystemExit, match="no branch 'nope'"):
        steps.queue(vault, "calls", "Soften it", NOW, base="nope")
    item = steps.queue(vault, "calls", "Soften the opening", NOW, "paper-storyline", paper)
    assert item["base"] == "paper-storyline" and item["manuscript"] == paper
    before = checkout_of(repo)
    runner = Runner()

    step = steps.take(vault, p, NOW, [runner])

    # Its worktree started from the manuscript's branch, and Accept merges back into it.
    assert step["base"] == "paper-storyline" and step["base_commit"] == tip
    assert step["manuscript"] == paper and "from" not in step
    assert (
        "a worktree of" in runner.tasks[0].brief
        and f"made from paper-storyline at {tip[:7]}" in runner.tasks[0].brief
    )
    assert "It's a change to the manuscript, docs/paper/paper.md" in runner.tasks[0].brief
    assert checkout_of(repo) == before
    assert steps.queued(vault, "calls") == []

    # Its version is one of the manuscript's, and its changes are against where it started.
    found = manuscript.find(p)
    listed = manuscript.versions(p, found)
    assert listed[0]["proxenos"] and listed[0]["step"] == step["id"] and not listed[0]["edit"]
    shown = manuscript.compare(p, found, head=listed[0]["commit"])
    assert shown["base"] == tip and not shown["editable"]
    assert [(o["op"], o["text"]) for o in shown["ops"] if o["op"] != "same"] == [
        ("del", "loudly"),
        ("add", "softly"),
    ]

    # Every file the step changed: prose word by word, code line by line.
    changes = manuscript.step_changes(p, steps.load(vault, step["id"]))
    by_path = {f["path"]: f for f in changes["files"]}
    assert set(by_path) == {"analysis.py", "docs/paper/paper.md"}
    assert by_path["docs/paper/paper.md"]["unit"] == "words"
    assert (by_path["docs/paper/paper.md"]["added"], by_path["docs/paper/paper.md"]["removed"]) == (
        1,
        1,
    )
    assert by_path["analysis.py"] | {"ops": []} == {
        "path": "analysis.py",
        "kind": "code",
        "unit": "lines",
        "text": "print('median')\n",
        "ops": [],
        "added": 1,
        "removed": 1,
        "binary": False,
        "truncated": False,
    }

    # Accept waits for the checkout to be on the manuscript's branch, then merges there.
    with pytest.raises(SystemExit, match="is on main, not paper-storyline"):
        steps.accept(vault, step["id"])
    git(repo, "checkout", "-q", "paper-storyline")
    assert steps.accept(vault, step["id"])["status"] == "accepted"
    assert "softly" in (repo / "docs" / "paper" / "paper.md").read_text()
    assert git(repo, "rev-parse", "main") == before[1]


def test_revise_a_step_builds_on_it_and_accept_takes_both(setup):
    vault, repo = setup
    git(repo, "checkout", "-q", "paper-storyline")
    p = project(vault)
    first = steps.take(vault, p, NOW, [Runner()])
    asked = steps.asked_for(vault, "calls", "Say quietly, not softly", LATER, first["branch"])
    runner = Runner()
    runner.sentence = "The birds sang quietly at dawn."

    def revise(task):
        paper = task.folder / "docs" / "paper" / "paper.md"
        assert "softly" in paper.read_text()  # it starts from the first step's work
        paper.write_text(paper.read_text().replace("softly", "quietly"))
        return runner(task) | {"step": "Say quietly"}

    revise.name, revise.label = "claude", "Claude Code"
    second = steps.take(vault, p, LATER, [revise], asked=asked)

    assert second["from"] == first["branch"] and second["builds_on"] == first["id"]
    assert second["base"] == "paper-storyline" and second["base_commit"] == first["head"]
    assert second["files"] == [{"path": "docs/paper/paper.md", "added": 1, "removed": 1}]
    assert "It builds on a step still waiting on Joe" in runner.tasks[0].brief
    assert "What that step did:\nChanged a sentence." in runner.tasks[0].brief

    steps.accept(vault, second["id"])

    assert "quietly" in (repo / "docs" / "paper" / "paper.md").read_text()
    assert (repo / "analysis.py").read_text() == "print('median')\n"  # the first step's change
    earlier = steps.load(vault, first["id"])
    assert earlier["status"] == "accepted" and "built on it" in earlier["thread"][-1]["detail"]
    assert git(repo, "branch", "--list", "proxenos/*") == ""


def test_a_queued_steps_branch_that_is_gone_falls_back_to_the_checkout(setup):
    vault, repo = setup
    asked = steps.asked_for(vault, "calls", "Soften it", NOW, "paper-storyline")
    git(repo, "branch", "-D", "paper-storyline")

    step = steps.take(vault, project(vault), NOW, [Runner(sentence="x")], asked=asked)

    assert step["base"] == "main" and step["thread"][0]["title"] == "Started from your branch"
    assert "paper-storyline is gone" in step["thread"][0]["detail"]


def test_an_edit_by_hand_is_a_branch_and_a_step_and_never_touches_the_checkout(setup):
    vault, repo = setup
    p = project(vault)
    found = manuscript.find(p)
    shown = manuscript.compare(p, found)
    before = checkout_of(repo)
    paper_tip = git(repo, "rev-parse", "paper-storyline")
    text = shown["text"].replace("Methods follow, in short.", "Methods follow, in brief.")
    request = {"path": found["path"], "branch": found["branch"], "from": shown["tip"]}

    step = manuscript.edit(vault, p, request | {"text": text.rstrip("\n")}, NOW)

    # A branch with one commit, of that file alone, and a step waiting on the user.
    assert step["id"] == "calls/20260310-020000" and step["status"] == "ready"
    assert step["branch"] == "proxenos/calls-edit-20260310-020000" and step["kind"] == "edit"
    assert step["base"] == "paper-storyline" and step["base_commit"] == paper_tip
    assert step["files"] == [{"path": "docs/paper/paper.md", "added": 1, "removed": 1}]
    assert step["did"] == "You edited docs/paper/paper.md on the page: 1 words in, 1 out."
    assert "worktree" not in step
    assert git(repo, "show", f"{step['branch']}:docs/paper/paper.md") == text.rstrip("\n")
    assert git(repo, "log", "-1", "--format=%s", step["branch"]) == "Edit docs/paper/paper.md."
    assert git(repo, "diff", "--name-only", f"{paper_tip}..{step['branch']}") == found["path"]
    assert [t["title"] for t in step["thread"]] == ["Made a branch", "Committed", "Waiting on you"]
    assert step["summary"].endswith("Accept merges it into paper-storyline.")
    saved = projects.steps_taken(vault, "calls")[0]
    assert saved["id"] == step["id"] and saved["status"] == "ready"
    # The user's checkout, its branch, commit and files, and the manuscript's branch, as they were.
    assert checkout_of(repo) == before
    assert git(repo, "rev-parse", "paper-storyline") == paper_tip
    assert not (steps.worktrees() / "calls" / "edit-20260310-020000").exists()
    assert "edit-" not in git(repo, "worktree", "list")

    # It's a version of the manuscript, marked as the user's edit.
    listed = manuscript.versions(p, found)
    assert listed[0]["edit"] and listed[0]["step"] == step["id"]

    # Discard deletes the branch; the step stays, discarded.
    assert steps.discard(vault, step["id"], LATER)["status"] == "discarded"
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert checkout_of(repo) == before


def test_an_edit_is_refused_when_nothing_changed_or_it_reaches_outside(setup):
    vault, repo = setup
    p = project(vault)
    found = manuscript.find(p)
    shown = manuscript.compare(p, found)
    request = {"path": found["path"], "branch": found["branch"], "from": shown["tip"]}
    with pytest.raises(SystemExit, match="nothing to save"):
        manuscript.edit(vault, p, request | {"text": shown["text"]}, NOW)
    for bad, why in [
        ({"path": "../outside.md"}, "which file and branch"),
        ({"path": ".git/config"}, "which file and branch"),
        ({"branch": "proxenos/calls-20260301-000000"}, "not a step's"),
        ({"branch": "nope"}, "no branch nope"),
        ({"from": git(repo, "rev-parse", "main")}, "isn't a version on paper-storyline"),
        ({"path": "docs/paper/missing.md"}, "isn't a text file"),
    ]:
        with pytest.raises(SystemExit, match=why):
            manuscript.edit(vault, p, request | {"text": "new"} | bad, NOW)
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert projects.steps_taken(vault, "calls") == []


def test_accepting_an_edit_merges_it_into_the_manuscripts_branch(setup):
    vault, repo = setup
    p = project(vault)
    found = manuscript.find(p)
    shown = manuscript.compare(p, found)
    request = {"path": found["path"], "branch": found["branch"], "from": shown["tip"]}
    step = manuscript.edit(vault, p, request | {"text": shown["text"] + "\nThanks.\n"}, NOW)

    git(repo, "checkout", "-q", "paper-storyline")
    accepted = steps.accept(vault, step["id"], LATER)

    assert accepted["status"] == "accepted"
    assert (repo / "docs" / "paper" / "paper.md").read_text().endswith("Thanks.\n")
    assert git(repo, "branch", "--list", "proxenos/*") == ""


def test_the_command_prints_json_for_the_page(setup, monkeypatch, capsys):
    vault, _ = setup
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))

    cli.main(["project", "manuscript", "calls"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["manuscript"]["path"] == "docs/paper/paper.md" and shown["text"] == SECOND

    edit = {"path": "docs/paper/paper.md", "branch": "paper-storyline", "from": shown["tip"]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(edit | {"text": "New.\n"}) + "\n"))
    cli.main(["project", "manuscript", "calls", "--edit"])
    saved = json.loads(capsys.readouterr().out)
    assert saved["branch"].startswith("proxenos/calls-edit-")

    cli.main(["project", "manuscript", "calls", "--step", saved["step"]])
    changes = json.loads(capsys.readouterr().out)
    [paper] = changes["files"]
    assert paper["path"] == "docs/paper/paper.md" and paper["text"] == "New.\n"

    with pytest.raises(SystemExit, match="no project"):
        cli.main(["project", "manuscript", "nope"])


def test_the_page_asks_for_a_change_on_a_branch_by_json(setup, monkeypatch):
    vault, _ = setup

    def ask(request):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request) + "\n"))
        parser = argparse.ArgumentParser()
        steps.add_arguments(parser)
        return steps.run(vault, parser.parse_args(["-"]))

    paper = {"path": "docs/paper/paper.md", "branch": "paper-storyline"}
    assert ask(
        {"queue": "calls", "step": "Soften it", "base": "paper-storyline", "manuscript": paper}
    ) == {"steps_queued": 1}
    [item] = steps.queued(vault, "calls")
    assert item["base"] == "paper-storyline" and item["manuscript"] == paper
    for bad, why in [
        ({"queue": "calls", "step": "x", "base": 3}, "base must be a branch"),
        ({"queue": "calls", "step": "x", "manuscript": "paper.md"}, "manuscript must be"),
        (
            {"queue": "calls", "step": "x", "manuscript": {"path": "../x"}},
            "a path in the repository",
        ),
        ({"take": "calls", "step": 3}, "say what the step is"),
    ]:
        with pytest.raises(SystemExit, match=why):
            ask(bad)
    monkeypatch.setattr(agent, "runners", lambda: [Runner()])
    assert ask({"take": "calls", "step": "Now", "base": "paper-storyline"})["steps_taken"] == 1
    newest = projects.steps_taken(vault, "calls")[0]
    assert newest["asked"] == "Now" and newest["base"] == "paper-storyline"
    assert len(steps.queued(vault, "calls")) == 1  # what was queued is still there


def args(project_id, **kw):
    parser = argparse.ArgumentParser()
    manuscript.add_arguments(parser)
    extra = [x for k, v in kw.items() for x in (f"--{k}", v)]
    return parser.parse_args([project_id, *extra])
