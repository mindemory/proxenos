"""`proxenos night` with the master and every clone faked out. No network, no model, no real data."""

import pytest

from proxenos import cli, llm, master
from proxenos.clones import (
    advisor,
    care,
    errands,
    network,
    projects,
    recall,
    tasks,
    tracker,
    work,
)


@pytest.fixture
def steps(tmp_path, monkeypatch):
    """Fakes every step to record its call and return one count; returns the call log."""
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    calls = []

    def fake_master(vault, since=None):
        calls.append(("master", vault.name, since))
        return {"sources_synced": 2, "self_files_written": 1}

    monkeypatch.setattr(master, "run", fake_master)
    for module in (tracker, tasks, care, advisor, network, recall, projects, errands, work):
        name = module.__name__.rsplit(".", 1)[1]

        def fake_run(vault, args, name=name):
            calls.append((name, vault.name, vars(args)))
            return {"done": 1}

        monkeypatch.setattr(module, "run", fake_run)
    return calls


def test_night_runs_the_master_then_every_clone_in_order(steps, capsys):
    cli.main(["night"])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("night: started ")
    assert lines[1:] == [
        "master: 2 sources synced, 1 self files written",
        "tracker: 1 done",
        "tasks: 1 done",
        "care: 1 done",
        "advisor: 1 done",
        "network: 1 done",
        "recall: 1 done",
        "projects: 1 done",
        "errands: 1 done",
        "work: 1 done",
    ]
    assert [name for name, *_ in steps] == ["master", *cli.NIGHT_CLONES]
    assert cli.NIGHT_CLONES.index("recall") < cli.NIGHT_CLONES.index("work")
    assert all(vault == "vault" for _, vault, _ in steps)
    args = {name: a for name, _, a in steps}
    assert args["network"] == {"people_only": False}  # the full run, ideas too
    assert args["work"] == {"max": work.MAX_DRAFTS, "replies": False}  # the full run
    assert args["tasks"] == {"days": tasks.DAYS}
    assert args["care"] == {"days": care.DAYS, "dry_run": False}
    assert args["recall"] == {"people": recall.PEOPLE}
    assert args["errands"] == {"goal": None}  # no new errand: the waiting ones look again


def test_a_failed_step_is_reported_and_the_rest_still_run(steps, monkeypatch, capsys):
    def broken(vault, since=None):
        raise SystemExit("ANTHROPIC_API_KEY is not set.\nPut a key in .env")

    def crash(vault, args):
        raise KeyError("tasks")

    monkeypatch.setattr(master, "run", broken)
    monkeypatch.setattr(advisor, "run", crash)

    with pytest.raises(SystemExit) as exit_:
        cli.main(["night"])

    assert exit_.value.code == 1
    lines = capsys.readouterr().out.splitlines()[1:]
    assert lines == [
        "master: failed (ANTHROPIC_API_KEY is not set. Put a key in .env)",
        "tracker: 1 done",
        "tasks: 1 done",
        "care: 1 done",
        "advisor: failed (KeyError: 'tasks')",
        "network: 1 done",
        "recall: 1 done",
        "projects: 1 done",
        "errands: 1 done",
        "work: 1 done",
    ]
    assert [name for name, *_ in steps] == [
        "tracker",
        "tasks",
        "care",
        "network",
        "recall",
        "projects",
        "errands",
        "work",
    ]
