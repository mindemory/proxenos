"""What the user tells Proxenos, on a synthetic vault. No network, no model, no real data."""

import json
from datetime import UTC, datetime

from proxenos import told
from proxenos.clones import tasks

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def write(vault, *lines):
    path = vault / "state" / "told.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines) + "{torn\n")


def test_rules_stay_facts_fade_and_removed_ones_go(tmp_path):
    write(
        tmp_path,
        {
            "at": "2026-01-02T09:00:00Z",
            "text": "Never tell  my parents about my health.",
            "always": True,
        },
        {"at": "2026-02-01T09:00:00Z", "text": "Old news.", "always": False},
        {"at": "2026-03-09T09:00:00Z", "text": "Not going to Tuesday's visit.", "always": False},
        {"at": "2026-03-09T10:00:00Z", "text": "A slip.", "always": False},
        {"at": "2026-03-09T10:05:00Z", "forget": "2026-03-09T10:00:00Z"},
    )

    assert [n["text"] for n in told.notes(tmp_path, NOW)] == [
        "Never tell my parents about my health.",  # a rule: still here after two months
        "Not going to Tuesday's visit.",  # a fact from yesterday; last month's has faded
    ]
    text = told.prompt(tmp_path, "Tess", NOW)
    assert "Tess's own rules for everything written for them" in text
    assert "- Never tell my parents about my health." in text
    assert "- 2026-03-09: Not going to Tuesday's visit." in text and "Old news" not in text
    assert told.prompt(tmp_path / "none", "Tess", NOW) == ""


def test_the_tasks_clone_reads_the_facts_as_something_the_user_said(tmp_path):
    write(
        tmp_path,
        {"at": "2026-03-09T09:00:00Z", "text": "Not going to Tuesday's visit.", "always": False},
        {"at": "2026-03-09T09:01:00Z", "text": "A rule, not a fact.", "always": True},
    )

    (said,) = tasks.conversations(tmp_path, "2026-03-01T00:00:00Z")

    assert (said["source"], said["title"]) == ("told", "Told to Proxenos")
    assert said["messages"] == [
        {
            "id": "told/2026-03-09T09:00:00Z",
            "ts": "2026-03-09T09:00:00Z",
            "sender": "me",
            "text": "Not going to Tuesday's visit.",
        }
    ]
    assert tasks.conversations(tmp_path, "2026-03-10T00:00:00Z") == []
