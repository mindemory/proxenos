"""The vault's history read as of a time, on a synthetic vault whose git history is made here.
No real data."""

import os
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

from proxenos import history
from proxenos.clones import work

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def commit(vault, when, files):
    """Write `files` into the vault and commit them as the master would, at `when`."""
    if not (vault / ".git").exists():
        vault.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(vault), "init", "-q"], check=True)
    for rel, text in files.items():
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(text)
    dated = os.environ | {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-C", str(vault), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(vault), "-c", "user.name=T", "-c", "user.email=t@example.org"]
        + ["commit", "-q", "-m", f"consolidate {when[:10]}"],
        check=True,
        env=dated,
    )


def test_a_file_is_read_as_the_last_commit_before_a_time_left_it(tmp_path):
    vault = tmp_path / "vault"
    commit(vault, "2026-02-01T09:00:00Z", {"self/identity.md": "a student"})
    commit(vault, "2026-03-05T09:00:00Z", {"self/identity.md": "a researcher"})

    def at(when):
        return history.at(vault, "self/identity.md", datetime.fromisoformat(when))

    assert at("2026-01-01T00:00:00Z") == ""  # not there yet
    assert at("2026-03-01T10:00:00Z") == "a student"
    assert at("2026-03-06T10:00:00Z") == "a researcher"
    assert history.at(vault, "self/voice.md", datetime(2026, 3, 6, tzinfo=UTC)) == ""


def test_a_draft_as_of_an_earlier_time_gets_the_self_model_then_and_never_todays(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    vault = tmp_path / "vault"
    commit(vault, "2026-02-01T09:00:00Z", {"self/identity.md": "EARLY SELF"})
    commit(vault, "2026-03-05T09:00:00Z", {"self/identity.md": "LATE SELF"})
    then = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    assert "EARLY SELF" in work._system(vault / "self", then, past=True)
    assert "LATE SELF" not in work._system(vault / "self", then, past=True)
    assert "LATE SELF" in work._system(vault / "self", then)  # a draft written now

    # With no history to tell what it said then, it says nothing, rather than what it says now.
    bare = tmp_path / "bare"
    (bare / "self").mkdir(parents=True)
    (bare / "self" / "identity.md").write_text("TODAY SELF")
    assert "TODAY SELF" not in work._system(bare / "self", then, past=True)
