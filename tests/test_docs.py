"""Folders of documents read every sync, with notes.py's reader faked out. No real files."""

import os

import pytest

from proxenos.ingest import docs


def test_a_folder_is_read_again_only_when_something_in_it_changed(tmp_path, monkeypatch):
    folder = tmp_path / "health"
    folder.mkdir()
    note = folder / "visit.md"
    note.write_text("# Visit")
    read = []
    monkeypatch.setattr(
        docs.notes, "ingest", lambda vault, export, pdfs: read.append(pdfs) or {"added": 1}
    )

    assert docs.ingest(tmp_path / "vault", [folder]) == {
        "folders_read": 1,
        "folders_unchanged": 0,
        "added": 1,
    }
    assert docs.ingest(tmp_path / "vault", [folder])["folders_unchanged"] == 1
    os.utime(note, (note.stat().st_mtime + 60,) * 2)
    assert docs.ingest(tmp_path / "vault", [folder])["folders_read"] == 1
    assert read == [folder, folder]


def test_folders_come_from_the_setting_and_a_missing_one_is_said(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_DOCS_DIRS", f"{tmp_path}/a, ,{tmp_path}/b")
    assert docs.folders() == [tmp_path / "a", tmp_path / "b"]
    with pytest.raises(SystemExit, match="no folder"):
        docs.ingest(tmp_path / "vault", [tmp_path / "a"])
