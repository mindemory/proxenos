"""The project clone, with the model faked out. No model, no real data."""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import voice
from proxenos.clones import projects

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"projects": list(items)}))


class Model:
    def __init__(self):
        self.calls = []

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", **kw):
        self.calls.append({"prompt": prompt, "system": system, "effort": effort})
        return {
            "status": "Second draft due **May 1**; two editor comments open.",
            "changed": "Ana sent the new photos.",
            "next": [
                {"step": "Retest the bread recipe", "who": "Joe", "by": "Mar 14"},
                {"step": " ", "who": "", "by": ""},
            ],
            "asks": ["Ask for an extension?"],
            "drafts": [
                {
                    "title": "Note to Ana",
                    "kind": "email",
                    "channel": "email",
                    "to": "Ana Lee",
                    "body": "Hi Ana, thanks.",
                },
                {
                    "title": "Plan",
                    "kind": "plan",
                    "channel": "other",
                    "to": "Ana Lee",
                    "body": "1. Retest.",
                },
                {
                    "title": "Third",
                    "kind": "doc",
                    "channel": "other",
                    "to": "",
                    "body": "Not kept: two at most.",
                },
            ],
        }


def test_no_list_is_no_work(tmp_path):
    assert projects.projects(tmp_path, model=Model())["projects_advanced"] == 0


def test_a_project_gets_its_status_log_and_drafts_and_keeps_moving(tmp_path):
    write_list(
        tmp_path,
        {
            "id": "cookbook",
            "name": "The cookbook",
            "about": "the second draft for the editor",
            "people": ["Ana Lee"],
            "terms": ["cookbook"],
        },
        {"id": "old", "name": "Old one", "paused": True},
        {"id": "../escape", "name": "Bad id"},
    )
    model = Model()

    stats = projects.projects(tmp_path, now=NOW, model=model)

    assert stats == {
        "projects_advanced": 1,
        "projects_failed": 0,
        "drafts_written": 2,
        "projects_paused": 1,
    }
    folder = tmp_path / "clones" / "projects" / "cookbook"
    status = (folder / "status.md").read_text()
    assert (
        "Second draft due **May 1**" in status
        and "- Retest the bread recipe (Joe, Mar 14)" in status
    )
    assert "- Ask for an extension?" in status
    assert "## 2026-03-10" in (folder / "log.md").read_text()
    assert (
        "Nothing new found since 2026-01-09" in model.calls[0]["prompt"]
    )  # a first run looks back
    drafts = tmp_path / "clones" / "drafts"
    email = (drafts / "project-cookbook-20260310-1.md").read_text()
    assert "for: project" in email and '"Ana Lee"' in email and "Hi Ana, thanks." in email
    plan = (drafts / "project-cookbook-20260310-2.md").read_text()
    assert 'to: ""' in plan  # a plan isn't a message to anyone

    # The next night: it reads its last status, looks only since its last run, and its untouched
    # drafts give way to new ones, while one the user approved stays.
    approved = drafts / "project-cookbook-20260310-2.md"
    approved.write_text(approved.read_text().replace("status: draft", "status: approved"))
    later = datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
    projects.projects(tmp_path, now=later, model=model)

    assert "Second draft due **May 1**" in model.calls[1]["prompt"]
    assert "since 2026-03-10" in model.calls[1]["prompt"]
    assert not (drafts / "project-cookbook-20260310-1.md").exists()
    assert approved.exists() and (drafts / "project-cookbook-20260312-1.md").exists()
    assert (folder / "log.md").read_text().count("## 2026-") == 2


def test_one_project_failing_leaves_the_others(tmp_path):
    write_list(tmp_path, {"id": "a", "name": "A"}, {"id": "b", "name": "B"})
    model = Model()
    calls = []

    def flaky(prompt, **kw):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("the local model isn't answering")
        return model(prompt, **kw)

    stats = projects.projects(tmp_path, now=NOW, model=flaky)
    assert stats["projects_advanced"] == 1 and stats["projects_failed"] == 1


def test_drafts_follow_the_rules_and_my_own_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    write_list(tmp_path, {"id": "cookbook", "name": "The cookbook"})
    mail = tmp_path / "raw" / "email" / "joe" / "2026-03.jsonl"
    mail.parent.mkdir(parents=True)
    body = "Ana, the bread is finally right I think, kind of dense still but good. " * 4
    record = {"id": "e1", "ts": "2026-03-01T09:00:00Z", "from_me": True, "to": ["ana@x.org"]}
    mail.write_text(json.dumps(record | {"subject": "Bread", "body_new": body}) + "\n")
    model = Model()

    projects.projects(tmp_path, now=NOW, model=model)

    [call] = model.calls
    assert voice.rules("Joe") in call["system"]
    assert '<example kind="email" date="2026-03-01" title="Bread">' in call["prompt"]
    assert "the bread is finally right I think" in call["prompt"]


def test_the_status_knows_the_work_done_and_what_the_user_made_of_it(tmp_path):
    write_list(tmp_path, {"id": "cookbook", "name": "The cookbook", "repo": "~/cookbook"})
    done = tmp_path / "clones" / "projects" / "cookbook" / "steps"
    done.mkdir(parents=True)
    for when, status, found in [
        ("20260308-020000", "accepted", "Bread rises 20% more at 24 C."),
        ("20260309-020000", "ready", "Rye takes 2 h longer."),
        ("20260309-030000", "working", ""),
    ]:
        step = {"status": status, "step": f"Step of {when}", "found": found}
        (done / f"{when}.json").write_text(json.dumps(step | {"created": f"{when[:4]}-03-0X"}))
    model = Model()

    projects.projects(tmp_path, now=NOW, model=model)

    prompt = model.calls[0]["prompt"]
    assert "Work Proxenos did on it lately:" in prompt
    assert "waiting for the user to accept it: Step of 20260309-020000 It found: Rye" in prompt
    assert "accepted by the user: Step of 20260308-020000 It found: Bread" in prompt
    assert "20260309-030000" not in prompt  # still being taken
    assert projects.listed_projects(tmp_path)[0]["repo"] == "~/cookbook"


def test_the_status_is_told_against_the_group_notes_and_brief(tmp_path):
    write_list(
        tmp_path,
        {
            "id": "pupil",
            "name": "Pupil in the learning task",
            "group": "Postdoc",
            "notes": "Gaze is someone else's; only pupil here.",
        },
        {"id": "plain", "name": "No brief"},
    )
    brief = tmp_path / "clones" / "projects" / "pupil" / "brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text("## The question\nDoes pupil track the learning rate?\n" + "x" * 9000)
    model = Model()

    projects.projects(tmp_path, now=NOW, model=model)

    pupil, plain = (c["prompt"] for c in model.calls)
    assert "Part of: Postdoc" in pupil
    assert "What the user wants known about it: Gaze is someone else's" in pupil
    assert "Does pupil track the learning rate?" in pupil
    assert "x" * (projects.BRIEF_CHARS + 1) not in pupil  # a long brief is cut
    assert "Part of:" not in plain and "What's known" not in plain
    listed = {p["id"]: p for p in projects.listed_projects(tmp_path)}
    assert listed["pupil"]["group"] == "Postdoc" and listed["plain"]["brief"] == ""


def test_a_project_s_status_sees_its_code_on_every_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args, env=None):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "tess@example.org")
    git("config", "user.name", "Tess")
    (repo / "a.py").write_text("x = 1\n")
    git("add", ".")
    # A few seconds before the draft: two commits in one second have no order git keeps to.
    earlier = f"{datetime.now(UTC) - timedelta(seconds=5):%Y-%m-%dT%H:%M:%S}+0000"
    stamps = {"GIT_AUTHOR_DATE": earlier, "GIT_COMMITTER_DATE": earlier}
    git("commit", "-q", "-m", "Start", env={**os.environ, **stamps})
    git("checkout", "-q", "-b", "draft")
    (repo / "paper.md").write_text("# The paper\n")
    git("add", ".")
    git("commit", "-q", "-m", "Write the draft")
    git("checkout", "-q", "main")

    text = projects._code({"repo": str(repo)}, datetime.now(UTC) - timedelta(days=1))

    assert "checked out on main" in text  # the draft is on a branch the checkout isn't on
    assert "draft | Write the draft" in text and "Start" in text
    assert text.endswith("paper.md")
    assert projects._code({"repo": str(tmp_path / "none")}, datetime.now(UTC)) == ""


def test_a_project_with_no_code_folder_has_no_code(tmp_path, monkeypatch):
    """Not the code of whichever repository the clone happens to run in."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no code to read"))

    assert projects._code({"repo": ""}, datetime.now(UTC)) == ""
    assert projects._code({}, datetime.now(UTC)) == ""


def test_work_proxenos_can_do_is_queued_for_it_not_given_to_the_user(tmp_path):
    from proxenos.clones import steps as taken

    write_list(
        tmp_path,
        {"id": "cookbook", "name": "The cookbook", "repo": "~/cookbook"},
        {"id": "notes", "name": "Notes only"},
    )

    class Doer(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            answer["next"] = [
                {"step": "Plot rise against temperature", "who": "Proxenos", "by": ""},
                {"step": "Choose the publisher", "who": "Joe", "by": "Mar 20"},
            ]
            return answer

    model = Doer()
    projects.projects(tmp_path, now=NOW, model=model)
    projects.projects(tmp_path, now=NOW + timedelta(days=1), model=model)  # not queued twice

    cookbook, notes = (c["system"] for c in model.calls[:2])
    assert 'is "Proxenos": it is queued' in cookbook and "isn't on this computer" in notes
    assert "about another project" in cookbook
    assert [q["text"] for q in taken.queued(tmp_path, "cookbook")] == [
        "Plot rise against temperature"
    ]
    # From a status the messages shaped, so it waits for the user to approve it.
    assert [(q["by"], q["approved"]) for q in taken.queued(tmp_path, "cookbook")] == [
        ("proxenos", False)
    ]
    # And no more than QUEUED of its own wait at once, so the user's own always fit.
    ideas = [{"step": f"Idea {n}", "who": "Proxenos"} for n in range(projects.QUEUED + 2)]
    project = next(p for p in projects.listed_projects(tmp_path) if p["id"] == "cookbook")
    projects._queue_own(tmp_path, project, ideas, NOW)
    projects._queue_own(tmp_path, project, ideas, NOW + timedelta(days=1))
    assert len(taken.queued(tmp_path, "cookbook")) == projects.QUEUED
    assert taken.queued(tmp_path, "notes") == []
    status = (tmp_path / "clones" / "projects" / "cookbook" / "status.md").read_text()
    assert "Plot rise against temperature (Proxenos, queued)" in status
    assert "Choose the publisher (Joe, Mar 20)" in status


def test_a_status_is_told_todays_date_and_never_calls_a_future_date_done(tmp_path):
    write_list(tmp_path, {"id": "clinic", "name": "The clinic", "terms": ["clinic"]})

    class Late(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            return answer | {"status": "Consultation completed (30 Mar), intake done 2 Mar."}

    model = Late()

    projects.projects(tmp_path, now=NOW, model=model)

    assert model.calls[0]["prompt"].startswith(f"Today is {NOW.astimezone():%A %Y-%m-%d}.\n")
    assert "scheduled" in model.calls[0]["system"] and "cancelled" in model.calls[0]["system"]
    status = (tmp_path / "clones" / "projects" / "clinic" / "status.md").read_text()
    assert "Consultation scheduled for 30 Mar, intake done 2 Mar." in status
    drafts = tmp_path / "clones" / "drafts"
    assert "Hi Ana, thanks." in (drafts / "project-clinic-20260310-1.md").read_text()


def test_health_stays_out_of_a_project_s_status_and_log(tmp_path):
    write_list(tmp_path, {"id": "atlas", "name": "The atlas paper", "terms": ["atlas"]})
    folder = tmp_path / "clones" / "projects" / "atlas"
    folder.mkdir()
    (folder / "status.md").write_text(
        "# The atlas paper\n\n- Recovering from flu.\n- Figure 2 done.\n"
    )
    (folder / "log.md").write_text(
        "## 2026-03-01\n\nJoe said he'd been sick. Ana sent the map.\n\n"
    )

    class Unwell(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            return answer | {
                "status": (
                    "Second draft due **May 1**. Joe has been dizzy since the fall, so it may "
                    "slip.\n\n"
                    "**Risks**\n"
                    "- **Health**: Recovery from a migraine flare is slow.\n"
                    "  - Resting until the 20th\n"
                    "- **Timeline**: Two editor comments open.\n\n"
                    "### Wellbeing\n"
                    "Sleeping badly; a doctor's appointment on Friday.\n\n"
                    "### Open\n"
                    "- Retest the bread recipe. Joe is unwell, so Ana may take it."
                ),
                "changed": "Ana sent the new photos. Joe shared health updates with Ana.",
                "next": [
                    {"step": "Retest the bread recipe", "who": "Joe", "by": "Mar 14"},
                    {"step": "Rest until the vertigo passes", "who": "Joe", "by": ""},
                ],
                "asks": ["Ask for an extension?", "Tell Ana you're unwell?"],
            }

    model = Unwell()

    projects.projects(tmp_path, now=NOW, model=model)

    assert "Leave health out" in model.calls[0]["system"]
    assert "unavailable for a while" in model.calls[0]["system"]
    # The last status and log go back without it, so it isn't kept as what still holds.
    prompt = model.calls[0]["prompt"]
    assert "Figure 2 done." in prompt and "Ana sent the map." in prompt
    assert "flu" not in prompt and "sick" not in prompt
    assert (folder / "status.md").read_text() == (
        "# The atlas paper\n\n"
        "_Where it stands, 2026-03-10._\n\n"
        "Second draft due **May 1**.\n\n"
        "**Risks**\n"
        "- **Timeline**: Two editor comments open.\n\n"
        "### Open\n"
        "- Retest the bread recipe.\n\n"
        "## Next steps\n\n"
        "- Retest the bread recipe (Joe, Mar 14)\n\n"
        "## Needs you\n\n"
        "- Ask for an extension?\n"
    )
    assert (
        (folder / "log.md")
        .read_text()
        .endswith(
            "## 2026-03-10\n\n"
            "Ana sent the new photos.\n\n"
            "0 new records read.\n\n"
            "Next: Retest the bread recipe (Joe, Mar 14).\n\n"
        )
    )


def test_research_that_sounds_medical_is_left_as_it_was():
    status = (
        "Recruiting patients through the clinic; MRI scans booked for co-registration.\n\n"
        "- Parameter recovery on simulated data holds. It recovers the true sources.\n"
        "- The inverse problem is ill-posed, so Dr. Lee suggested a stronger prior.\n"
        "- NIH (National Institutes of Health) renewal due **Jun 5**.\n\n"
        "| Step | Who |\n|---|---|\n| Therapy arm analysis | Ana |\n"
    )
    assert projects._without_health(status) == status
    assert projects._without_health("Away until **Apr 2**. Drafts wait.") == (
        "Away until **Apr 2**. Drafts wait."
    )
