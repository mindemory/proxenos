"""`proxenos night` with the master and every clone faked out. No network, no model, no real data."""

import json
import re

import pytest

from proxenos import cli, llm, master, voice, voicemodel
from proxenos.clones import (
    advisor,
    care,
    choices,
    errands,
    journal,
    life,
    network,
    projects,
    recall,
    rhythms,
    steps,
    tasks,
    tracker,
    watch,
    work,
)


@pytest.fixture
def calls(tmp_path, monkeypatch):
    """Fakes every step to record its call and return one count; returns the call log."""
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    calls = []

    def fake_master(vault, since=None):
        calls.append(("master", vault.name, since))
        return {"sources_synced": 2, "self_files_written": 1}

    monkeypatch.setattr(master, "run", fake_master)
    for module in (
        tracker,
        tasks,
        care,
        advisor,
        network,
        choices,
        watch,
        recall,
        projects,
        errands,
        work,
        steps,
        journal,
        life,
        rhythms,
    ):
        name = module.__name__.rsplit(".", 1)[1]

        def fake_run(vault, args, name=name):
            calls.append((name, vault.name, vars(args)))
            return {"done": 1}

        monkeypatch.setattr(module, "run", fake_run)

    def fake_refresh(vault):
        calls.append(("voice", vault.name, {}))
        return {"new_answers": 3}

    monkeypatch.setattr(voicemodel, "refresh", fake_refresh)

    def fake_lessons(vault):
        calls.append(("lessons", vault.name, {}))
        return {"new_changed_drafts": 2}

    monkeypatch.setattr(voice, "lessons", fake_lessons)
    return calls


LESSONS = voice.lessons  # the real one, which the fixture fakes


def untimed(lines):
    """The night's lines without the time each step took, after checking each has one."""
    assert all(re.search(r" \[\d+s\]$", line) for line in lines)
    return [re.sub(r" \[\d+s\]$", "", line) for line in lines]


def test_each_step_s_time_reads_at_a_glance():
    assert [cli._took(s) for s in (4.4, 59.6, 252, 3780)] == ["4s", "1m 00s", "4m 12s", "1h 03m"]


def test_night_runs_the_master_then_every_clone_in_order(calls, capsys):
    cli.main(["night"])

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("night: started ")
    assert untimed(lines[1:]) == [
        "master: 2 sources synced, 1 self files written",
        "tracker: 1 done",
        "tasks: 1 done",
        "care: 1 done",
        "advisor: 1 done",
        "network: 1 done",
        "choices: 1 done",
        "watch: 1 done",
        "recall: 1 done",
        "projects: 1 done",
        "errands: 1 done",
        "work: 1 done",
        "steps: 1 done",
        "journal: 1 done",
        "life: 1 done",
        "rhythms: 1 done",
        "voice: 3 new answers",  # trained again only when it's due
        "lessons: 2 new changed drafts",  # rules learned only once enough are new
    ]
    assert [name for name, *_ in calls] == ["master", *cli.NIGHT_CLONES, "voice", "lessons"]
    assert cli.NIGHT_CLONES.index("recall") < cli.NIGHT_CLONES.index("work")
    # The week's choices read the tasks and ideas, and their drafts are the work clone's.
    assert cli.NIGHT_CLONES.index("network") < cli.NIGHT_CLONES.index("choices")
    assert cli.NIGHT_CLONES.index("choices") < cli.NIGHT_CLONES.index("work")
    # The month's story reads the journal of the day that just ended.
    assert cli.NIGHT_CLONES.index("journal") < cli.NIGHT_CLONES.index("life")
    assert all(vault == "vault" for _, vault, _ in calls)
    args = {name: a for name, _, a in calls}
    assert args["network"] == {"people_only": False}  # the full run, ideas too
    assert args["work"] == {"max": work.MAX_DRAFTS, "replies": False}  # the full run
    assert args["tasks"] == {"days": tasks.DAYS}
    assert args["care"] == {"days": care.DAYS, "dry_run": False}
    assert args["recall"] == {"people": recall.PEOPLE}
    assert args["errands"] == {"goal": None}  # no new errand: the waiting ones look again
    assert args["choices"] == args["watch"] == {"force": False}  # once a week
    assert args["steps"] == {"request": None, "project": None}  # each project with a repo
    assert args["rhythms"] == {"weeks": None, "label": rhythms.LABEL, "json": False}


def test_a_failed_step_is_reported_and_the_rest_still_run(calls, monkeypatch, capsys):
    def broken(vault, since=None):
        raise SystemExit("ANTHROPIC_API_KEY is not set.\nPut a key in .env")

    def crash(vault, args):
        raise KeyError("tasks")

    monkeypatch.setattr(master, "run", broken)
    monkeypatch.setattr(advisor, "run", crash)

    with pytest.raises(SystemExit) as exit_:
        cli.main(["night"])

    assert exit_.value.code == 1
    lines = untimed(capsys.readouterr().out.splitlines()[1:])
    assert lines == [
        "master: failed (ANTHROPIC_API_KEY is not set. Put a key in .env)",
        "tracker: 1 done",
        "tasks: 1 done",
        "care: 1 done",
        "advisor: failed (KeyError: 'tasks')",
        "network: 1 done",
        "choices: 1 done",
        "watch: 1 done",
        "recall: 1 done",
        "projects: 1 done",
        "errands: 1 done",
        "work: 1 done",
        "steps: 1 done",
        "journal: 1 done",
        "life: 1 done",
        "rhythms: 1 done",
        "voice: 3 new answers",
        "lessons: 2 new changed drafts",
    ]
    assert [name for name, *_ in calls] == [
        "tracker",
        "tasks",
        "care",
        "network",
        "choices",
        "watch",
        "recall",
        "projects",
        "errands",
        "work",
        "steps",
        "journal",
        "life",
        "rhythms",
        "voice",
        "lessons",
    ]


def test_too_few_new_changed_drafts_ask_no_model(calls, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(voice, "lessons", LESSONS)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a model call"))
    measured = [
        {"source": "whatsapp", "to": "Ana", "closeness": 0.2, "sent": f"2026-03-0{n}T09:00:00Z",
         "draft_text": f"Dear Ana, note {n}.", "sent_text": f"hey ana, note {n}"}
        for n in range(1, voice.NEW_PAIRS)
    ]  # fmt: skip
    folder = tmp_path / "vault" / "clones" / "drafts"
    folder.mkdir(parents=True)
    (folder / "fidelity.json").write_text(json.dumps({"drafts": measured}))

    cli.main(["night"])

    lines = untimed(capsys.readouterr().out.splitlines()[1:])
    assert lines[-1] == f"lessons: {voice.NEW_PAIRS - 1} new changed drafts"
    assert not (tmp_path / "vault" / voice.LESSONS).exists()  # it didn't run
