"""The steps clone, on small git repositories made here, with the runner faked out. No model, no
real data, and no real repository."""

import argparse
import io
import json
import subprocess
from datetime import UTC, datetime

import pytest

from proxenos import agent
from proxenos.clones import projects, steps

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 11, 2, 0, tzinfo=UTC)


def git(where, *args):
    return subprocess.run(
        ["git", "-C", str(where), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A vault, a project's repository on main with one script, its data folder, and somewhere
    for worktrees."""
    monkeypatch.setenv("PROXENOS_WORKTREES", str(tmp_path / "worktrees"))
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Joe")
    git(repo, "config", "user.email", "joe@example.org")
    (repo / "analysis.py").write_text("print('mean')\n")
    (repo / ".gitignore").write_text("")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "First")
    data = tmp_path / "data"
    data.mkdir()
    vault = tmp_path / "vault"
    write_list(vault, {"id": "calls", "name": "Calls", "repo": str(repo), "data": [str(data)]})
    return vault, repo, data


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": list(items)}))


def project(vault, pid="calls"):
    return next(p for p in projects.listed_projects(vault) if p["id"] == pid)


class Runner:
    """Claude Code, faked: it changes the script, makes a figure and a table, leaves a cache
    behind, and reports."""

    name, label = "claude", "Claude Code"

    def __init__(self, change=True):
        self.tasks = []
        self.change = change

    def __call__(self, task):
        self.tasks.append(task)
        if self.change:
            (task.folder / "analysis.py").write_text("print('median')\nprint('n')\n")
            (task.folder / "__pycache__").mkdir()
            (task.folder / "__pycache__" / "analysis.cpython-312.pyc").write_bytes(b"\0")
        out = task.folder / agent.OUT
        out.mkdir(parents=True)
        (out / "medians.png").write_bytes(b"\x89PNG")
        (out / "medians.csv").write_text("species,median\na,1\n")
        (out / "notes.exe").write_bytes(b"MZ")  # not a kind of file a report shows
        return {
            "step": "Use the median, and count the notes",
            "why": "The means were pulled by outliers.",
            "did": "Changed `analysis.py` and ran it.",
            "found": "Median 4.2 kHz (n = 1,204).",
            "figures": [{"file": ".proxenos/out/medians.png", "caption": "Medians by species"}],
            "couldnt": "",
            "next": "Redo the figure with the medians.",
            "commit": "Use the median and count the notes. Then more.",
            "meta": {"turns": 12, "cost_usd": 0.81, "note": "dropped: not a number"},
        }


def test_a_step_is_done_on_a_branch_of_its_own_and_waits_for_the_user(setup):
    vault, repo, data = setup
    head = git(repo, "rev-parse", "HEAD")
    runner = Runner()

    step = steps.take(vault, project(vault), NOW, [runner])

    assert step["status"] == "ready" and step["id"] == "calls/20260310-020000"
    assert step["branch"] == "proxenos/calls-20260310-020000" and step["base"] == "main"
    # The user's own checkout isn't touched: the same commit, the same file, nothing changed.
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / "analysis.py").read_text() == "print('mean')\n"
    assert git(repo, "status", "--porcelain") == ""
    # The branch has one commit, one plain sentence, with the script and nothing else.
    assert (
        git(repo, "log", "-1", "--format=%s", step["branch"])
        == "Use the median and count the notes."
    )
    assert git(repo, "diff", "--name-only", f"{head}..{step['branch']}") == "analysis.py"
    assert step["files"] == [{"path": "analysis.py", "added": 2, "removed": 1}]
    # What it made is kept with the report, the figure first with its caption.
    assert step["made"] == [
        {"name": "medians.png", "caption": "Medians by species"},
        {"name": "medians.csv", "caption": ""},
    ]
    made = vault / "clones" / "projects" / "calls" / "steps" / "20260310-020000"
    assert (made / "medians.png").read_bytes() == b"\x89PNG"
    assert not (made / "notes.exe").exists()
    assert step["found"] == "Median 4.2 kHz (n = 1,204)." and step["runner"] == "claude"
    assert step["meta"] == {"turns": 12, "cost_usd": 0.81}
    assert [t["title"] for t in step["thread"]] == [
        "Made a worktree",
        "Handed it to Claude Code",
        "Done the step",
        "Committed",
        "Waiting on you",
    ]
    assert step["summary"].startswith("Ready for you: Use the median")
    saved = json.loads(made.with_suffix(".json").read_text())
    assert saved["status"] == "ready" and saved["thread"] == step["thread"]

    # The runner worked in the worktree, could read the data, and couldn't read the vault.
    [task] = runner.tasks
    assert task.folder == steps.worktrees() / "calls" / "20260310-020000"
    assert task.data == [data] and vault in task.hidden
    assert "Joe didn't ask for a step: pick the one" in task.brief

    # Accept merges it into main, in the user's checkout, and the branch and worktree go.
    accepted = steps.accept(vault, step["id"], LATER)

    assert accepted["status"] == "accepted" and accepted["decided"] == "2026-03-11T02:00:00Z"
    assert (repo / "analysis.py").read_text() == "print('median')\nprint('n')\n"
    assert git(repo, "branch", "--list", step["branch"]) == ""
    assert not task.folder.exists()
    assert accepted["thread"][-1]["title"] == "You accepted it"
    with pytest.raises(SystemExit, match="accepted, not waiting on you"):
        steps.accept(vault, step["id"])


def test_discard_takes_the_branch_and_worktree_and_leaves_the_checkout(setup):
    vault, repo, _ = setup
    step = steps.take(vault, project(vault), NOW, [Runner()])

    discarded = steps.discard(vault, step["id"], LATER)

    assert discarded["status"] == "discarded"
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert not (steps.worktrees() / "calls" / "20260310-020000").exists()
    assert (repo / "analysis.py").read_text() == "print('mean')\n"
    assert discarded["did"] == "Changed `analysis.py` and ran it."  # the report stays


def test_accept_waits_for_the_checkout_to_be_on_its_branch_and_never_forces_a_merge(setup):
    vault, repo, _ = setup
    step = steps.take(vault, project(vault), NOW, [Runner()])

    git(repo, "checkout", "-q", "-b", "other")
    with pytest.raises(SystemExit, match="is on other, not main"):
        steps.accept(vault, step["id"])

    # Back on main, with a change of the user's own to the same lines, committed: a conflict.
    git(repo, "checkout", "-q", "main")
    (repo / "analysis.py").write_text("print('trimmed mean')\n")
    git(repo, "commit", "-q", "-am", "Mine")
    with pytest.raises(SystemExit, match="conflicts with your changes to analysis.py"):
        steps.accept(vault, step["id"])
    assert git(repo, "status", "--porcelain") == ""  # the merge was undone
    assert (repo / "analysis.py").read_text() == "print('trimmed mean')\n"
    assert steps.load(vault, step["id"])["status"] == "ready"  # still the user's to decide

    # A change of the user's own, not committed, that the merge would overwrite: git refuses.
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "analysis.py").write_text("print('mine, not committed')\n")
    with pytest.raises(SystemExit, match="couldn't merge"):
        steps.accept(vault, step["id"])
    assert (repo / "analysis.py").read_text() == "print('mine, not committed')\n"


def test_a_queued_step_goes_first_and_comes_back_when_the_step_fails(setup):
    vault, repo, _ = setup
    first = steps.queue(vault, "calls", "  Make figure 3 with the medians  ", NOW)
    steps.queue(vault, "calls", "Then draft the methods", NOW)
    with pytest.raises(SystemExit, match="say what the step is"):
        steps.queue(vault, "calls", "   ")
    with pytest.raises(SystemExit, match="no project"):
        steps.queue(vault, "nope", "Something")

    def broken(task):
        (task.folder / "analysis.py").write_text("half done\n")
        raise agent.AgentError("Claude Code stopped: it used its 100 turns before it reported")

    broken.name, broken.label = "claude", "Claude Code"
    with pytest.raises(agent.AgentError):
        steps.take(vault, project(vault), NOW, [broken])

    [failed] = projects.steps_taken(vault, "calls")
    assert failed["status"] == "failed" and failed["asked"] == "Make figure 3 with the medians"
    assert "used its 100 turns" in failed["error"]
    assert "back in the queue" in failed["thread"][-1]["detail"]
    assert "worktree is kept" in failed["thread"][-1]["detail"]  # it changed something
    assert [q["text"] for q in steps.queued(vault, "calls")] == [
        "Make figure 3 with the medians",
        "Then draft the methods",
    ]
    assert steps.discard(vault, failed["id"])["status"] == "discarded"
    assert git(repo, "branch", "--list", "proxenos/*") == ""

    runner = Runner()
    step = steps.take(vault, project(vault), LATER, [runner])
    assert step["asked"] == first["text"]
    assert "The step Joe asked for: Make figure 3 with the medians" in runner.tasks[0].brief
    assert [q["text"] for q in steps.queued(vault, "calls")] == ["Then draft the methods"]
    assert steps.unqueue(vault, "calls", steps.queued(vault, "calls")[0]["id"])
    assert steps.queued(vault, "calls") == []


def test_when_claude_code_cant_start_the_local_model_takes_the_step(setup):
    vault, _, _ = setup

    def out_of_credit(task):
        raise agent.AgentUnavailable("Credit balance is too low")

    out_of_credit.name, out_of_credit.label = "claude", "Claude Code"
    local = Runner()
    local.name, local.label = "local", "the local model"

    step = steps.take(vault, project(vault), NOW, [out_of_credit, local])

    assert step["runner"] == "local" and step["status"] == "ready"
    titles = [t["title"] for t in step["thread"]]
    assert titles[1:4] == [
        "Handed it to Claude Code",
        "Claude Code couldn't start",
        "Handed it to the local model",
    ]
    assert step["thread"][2]["detail"] == "Credit balance is too low"


def test_a_step_that_fails_before_changing_anything_leaves_nothing_behind(setup):
    vault, repo, _ = setup

    def out_of_credit(task):
        raise agent.AgentUnavailable("Credit balance is too low")

    out_of_credit.name, out_of_credit.label = "claude", "Claude Code"
    with pytest.raises(agent.AgentError, match="couldn't start: Credit balance is too low"):
        steps.take(vault, project(vault), NOW, [out_of_credit])

    [failed] = projects.steps_taken(vault, "calls")
    assert failed["status"] == "failed"
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert not (steps.worktrees() / "calls" / "20260310-020000").exists()


def test_a_step_that_changes_no_file_reports_and_has_nothing_to_merge(setup):
    vault, repo, _ = setup
    head = git(repo, "rev-parse", "HEAD")

    step = steps.take(vault, project(vault), NOW, [Runner(change=False)])

    assert step["files"] == [] and step["head"] == head
    assert step["thread"][-2]["title"] == "Changed no file"
    accepted = steps.accept(vault, step["id"])
    assert "nothing to merge" in accepted["thread"][-1]["detail"]
    assert git(repo, "rev-parse", "HEAD") == head


def test_the_night_takes_one_step_where_the_last_is_decided(setup, tmp_path):
    vault, repo, _ = setup
    write_list(
        vault,
        {"id": "calls", "name": "Calls", "repo": str(repo)},
        {"id": "paper", "name": "Paper"},  # no repo: the projects clone looks after it alone
        {"id": "held", "name": "Held", "repo": str(repo), "paused": True},
        {"id": "gone", "name": "Gone", "repo": str(tmp_path / "nowhere")},
    )
    runner = Runner()

    stats = steps.night(vault, NOW, [runner])

    assert stats == {"steps_taken": 1, "steps_failed": 1, "steps_waiting": 0}
    # The next night the step is still waiting on the user, so no other is taken.
    assert steps.night(vault, LATER, [runner])["steps_waiting"] == 1
    assert len(runner.tasks) == 1


def test_the_brief_has_where_the_project_stands_and_the_steps_before(setup):
    vault, repo, _ = setup
    status = vault / "clones" / "projects" / "calls" / "status.md"
    status.parent.mkdir()
    status.write_text("# Calls\n\nFigure 3 still uses means.\n\n## Next steps\n\n- Redo fig 3\n")
    write_list(
        vault,
        {
            "id": "calls",
            "name": "Calls",
            "about": "the birdsong paper",
            "people": ["Ana Lee"],
            "repo": str(repo),
            "data": ["/nowhere/data"],
            "python": "/envs/calls/bin/python",
            "notes": "Figures are F*.py.",
        },
    )
    first = steps.take(vault, project(vault), NOW, [Runner()])
    steps.discard(vault, first["id"])
    runner = Runner()

    second = steps.take(vault, project(vault), LATER, [runner])

    brief = runner.tasks[0].brief
    assert "The project: Calls\nWhat it is: the birdsong paper\nWith: Ana Lee" in brief
    assert "Its data, read-only: /nowhere/data (not on this computer)" in brief
    assert "Joe's notes on the work: Figures are F*.py." in brief
    assert "Figure 3 still uses means." in brief
    assert (
        "- 2026-03-10, discarded: Use the median, and count the notes Next, it said: Redo the "
        "figure with the medians." in brief
    )
    assert second["id"] not in brief
    assert runner.tasks[0].python == "/envs/calls/bin/python"
    assert second["thread"][1] == second["thread"][1] | {"title": "Missing data"}


def test_a_step_waits_for_a_checkout_on_a_branch_and_one_step_at_a_time(setup):
    vault, repo, _ = setup
    git(repo, "checkout", "-q", "--detach")
    with pytest.raises(SystemExit, match="isn't on a branch"):
        steps.take(vault, project(vault), NOW, [Runner()])
    git(repo, "checkout", "-q", "main")

    held = steps.lock.Lock(vault / "state" / "steps-calls.lock")
    assert held.acquire()
    with pytest.raises(SystemExit, match="taking a step already"):
        steps.take(vault, project(vault), NOW, [Runner()])
    held.release()


def test_a_step_left_working_by_a_run_that_died_is_failed_by_the_next(setup):
    vault, _, _ = setup
    step = steps.take(vault, project(vault), NOW, [Runner()])
    path = vault / "clones" / "projects" / "calls" / "steps" / "20260310-020000.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"status": "working"}))

    steps.take(vault, project(vault), LATER, [Runner()])

    assert steps.load(vault, step["id"])["status"] == "failed"


def test_the_page_asks_by_json_on_stdin(setup, monkeypatch):
    vault, _, _ = setup

    def ask(request):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request) + "\n"))
        return steps.run(vault, steps_args("-"))

    assert ask({"queue": "calls", "step": "Draft the methods"}) == {"steps_queued": 1}
    item = steps.queued(vault, "calls")[0]
    assert ask({"unqueue": "calls", "id": item["id"]}) == {"steps_unqueued": 1}
    for bad, why in [
        ({"queue": "calls"}, "say what the step is"),
        ({"accept": 3}, "accept must be text"),
        ({"hello": "x"}, "asks for nothing"),
        (["take"], "isn't an object"),
    ]:
        with pytest.raises(SystemExit, match=why):
            ask(bad)
    with pytest.raises(SystemExit, match="isn't a step's id"):
        ask({"accept": "../../etc/passwd"})


def steps_args(request=None, project=None):
    parser = argparse.ArgumentParser()
    steps.add_arguments(parser)
    return parser.parse_args(
        [a for a in (request,) if a] + (["--project", project] if project else [])
    )


def test_the_runner_never_reads_the_vault_or_secrets(setup, monkeypatch, tmp_path):
    vault, _, _ = setup
    settings = tmp_path / "settings" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{}")
    monkeypatch.setattr(steps, "settings_file", lambda: settings)
    monkeypatch.delenv("PROXENOS_WORKTREES")

    assert steps.hidden(vault)[:2] == [vault, settings]
    assert steps.worktrees() == settings.parent / "worktrees"
