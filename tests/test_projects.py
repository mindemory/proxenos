"""The project clone, with the model faked out. No model, no real data."""

import json
from datetime import UTC, datetime

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
            "status": "Revision due **May 1**; two reviewer comments open.",
            "changed": "Ana sent the new figure.",
            "next": [
                {"step": "Rerun the source model", "who": "Tess", "by": "Mar 14"},
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
                    "body": "1. Rerun.",
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
            "id": "meg-paper",
            "name": "The MEG paper",
            "about": "the revision",
            "people": ["Ana Lee"],
            "terms": ["MEG"],
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
    folder = tmp_path / "clones" / "projects" / "meg-paper"
    status = (folder / "status.md").read_text()
    assert (
        "Revision due **May 1**" in status and "- Rerun the source model (Tess, Mar 14)" in status
    )
    assert "- Ask for an extension?" in status
    assert "## 2026-03-10" in (folder / "log.md").read_text()
    assert (
        "Nothing new found since 2026-01-09" in model.calls[0]["prompt"]
    )  # a first run looks back
    drafts = tmp_path / "clones" / "drafts"
    email = (drafts / "project-meg-paper-20260310-1.md").read_text()
    assert "for: project" in email and '"Ana Lee"' in email and "Hi Ana, thanks." in email
    plan = (drafts / "project-meg-paper-20260310-2.md").read_text()
    assert 'to: ""' in plan  # a plan isn't a message to anyone

    # The next night: it reads its last status, looks only since its last run, and its untouched
    # drafts give way to new ones, while one the user approved stays.
    approved = drafts / "project-meg-paper-20260310-2.md"
    approved.write_text(approved.read_text().replace("status: draft", "status: approved"))
    later = datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
    projects.projects(tmp_path, now=later, model=model)

    assert "Revision due **May 1**" in model.calls[1]["prompt"]
    assert "since 2026-03-10" in model.calls[1]["prompt"]
    assert not (drafts / "project-meg-paper-20260310-1.md").exists()
    assert approved.exists() and (drafts / "project-meg-paper-20260312-1.md").exists()
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
