"""The raw layer's month files, and that what Proxenos writes into the vault is the user's alone:
files 0600 in folders 0700, checked where the platform keeps modes. Synthetic records only."""

import os
import stat
import zipfile

from proxenos import importer, store

NO_MODES = os.name == "nt"  # Windows keeps no Unix modes


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_month_files_merge_by_id_and_are_private_in_private_folders(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    out = vault / "raw" / "spotify" / "plays"
    one = {"id": "a", "ts": "2026-03-01T10:00:00Z", "track": "x"}

    stats = store.merge_monthly([one], out)
    again = store.merge_monthly([one], out)

    assert stats["added"] == 1 and again["months_written"] == 0  # a re-run changes nothing
    if not NO_MODES:
        assert mode(out / "2026-03.jsonl") == 0o600
        assert [mode(p) for p in (vault / "raw", out.parent, out)] == [0o700] * 3
    # A folder and a file written before, open to anyone, are made private when written again.
    if not NO_MODES:
        out.chmod(0o755)
        (out / "2026-03.jsonl").chmod(0o644)
    store.merge_monthly([one | {"track": "y"}], out)
    store.merge_snapshot([{"id": "g", "members": 3}], out)
    if not NO_MODES:
        assert mode(out) == 0o700
        assert mode(out / "2026-03.jsonl") == mode(out / store.SNAPSHOT) == 0o600


def test_a_state_file_or_note_is_written_whole_and_private(tmp_path):
    note = tmp_path / "vault" / "observations" / "whatsapp" / "2026-03.md"
    store.write_private(note, "# whatsapp, 2026-03\n")
    store.write_private(note, "# whatsapp, 2026-03\n\nAgain.\n")
    assert note.read_text() == "# whatsapp, 2026-03\n\nAgain.\n"
    assert [p.name for p in note.parent.iterdir()] == ["2026-03.md"]  # no temporary left
    if not NO_MODES:
        assert mode(note) == 0o600
        assert mode(note.parent) == mode(note.parent.parent) == 0o700


def test_an_unpacked_export_and_a_filed_download_are_private(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    download = inbox / "twitter-2026-10-27.zip"
    with zipfile.ZipFile(download, "w") as z:
        for name in ("data/manifest.js", "data/tweets.js"):
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o644 << 16  # as anyone may read it
            z.writestr(info, "x")
    if not NO_MODES:
        download.chmod(0o644)  # as a browser leaves a download

    importer.run(vault, ingest=lambda v, source, argv: None)

    export = vault / "exports" / "twitter-2026-10-27"
    filed = vault / "downloads" / "twitter" / "twitter-2026-10-27.zip"
    assert (export / "data" / "tweets.js").read_text() == "x" and filed.exists()
    if NO_MODES:
        return
    assert mode(export / "data" / "tweets.js") == mode(filed) == 0o600
    for folder in (vault / "exports", export, export / "data", vault / "downloads", filed.parent):
        assert mode(folder) == 0o700, folder
