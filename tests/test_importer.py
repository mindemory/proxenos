"""Drop-folder imports with synthetic zips; the ingesters themselves are faked out."""

import time
import zipfile

from twin import importer


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def run(vault, paths=None):
    calls = []
    stats = importer.run(vault, paths, ingest=lambda v, source, argv: calls.append((source, argv)))
    return stats, calls


MBOX = b"From x@y Thu Jan  1 00:00:00 2025\nDelivered-To: Me@Example.com\nSubject: hi\n\nbody\n"


def test_inbox_zips_are_recognized_unpacked_and_moved_aside(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    make_zip(inbox / "twitter-2026-10-27.zip", {"data/manifest.js": "x", "data/tweets.js": "y"})
    make_zip(inbox / "takeout-20261027T1Z-001.zip", {"Takeout/Mail/All mail.mbox": MBOX})
    make_zip(inbox / "takeout-20261027T1Z-002.zip", {"Takeout/Chrome/History.json": "{}"})
    make_zip(inbox / "mystery.zip", {"notes.txt": "?"})

    stats, calls = run(vault)
    assert stats == {"twitter_imported": 1, "email_imported": 1, "unrecognized": 1}
    sources = {source: argv for source, argv in calls}
    assert sources["twitter"] == ["--export", str(vault / "exports" / "twitter-2026-10-27")]
    assert sources["email"][:2] == ["--account", "me-example-com"]
    # Both Takeout parts land in one folder.
    takeout = vault / "exports" / "takeout-20261027T1Z" / "Takeout"
    assert (takeout / "Mail").is_dir() and (takeout / "Chrome").is_dir()

    left = sorted(p.name for p in inbox.iterdir())
    assert left == ["imported", "mystery.zip"]


def test_folders_and_other_exports_are_recognized(tmp_path):
    vault = tmp_path / "vault"
    export = tmp_path / "instagram-me"
    (export / "your_instagram_activity" / "messages").mkdir(parents=True)
    linkedin = tmp_path / "Basic_LinkedInDataExport"
    linkedin.mkdir()
    (linkedin / "Connections.csv").write_text("First Name\n")
    spotify = tmp_path / "my_spotify_data"
    (spotify / "Spotify Extended Streaming History").mkdir(parents=True)
    (
        spotify / "Spotify Extended Streaming History" / "Streaming_History_Audio_2025.json"
    ).write_text("[]")

    stats, calls = run(vault, [export, linkedin, spotify])
    assert [source for source, _ in calls] == ["instagram", "linkedin", "spotify"]
    assert stats == {"instagram_imported": 1, "linkedin_imported": 1, "spotify_imported": 1}


def test_a_failing_ingester_is_reported_and_the_rest_continue(tmp_path, capsys):
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    make_zip(vault / "inbox" / "a.zip", {"data/manifest.js": "x"})
    make_zip(vault / "inbox" / "b.zip", {"Connections.csv": "x"})

    def ingest(v, source, argv):
        if source == "twitter":
            raise SystemExit("bad archive")

    stats = importer.run(vault, ingest=ingest)
    assert stats == {"failed": 1, "linkedin_imported": 1}
    assert "bad archive" in capsys.readouterr().err


def test_an_export_is_unpacked_once_and_keeps_its_file_times(tmp_path):
    archive = tmp_path / "notes.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(zipfile.ZipInfo("vault/a.md", date_time=(2024, 3, 5, 12, 30, 0)), "# A\n")
        z.writestr("vault/b.md", "# B\n")
    dest = tmp_path / "exports" / "notes"

    importer._unpack(archive, dest)
    assert (dest / ".unpacked-notes.zip").exists()
    stamp = (dest / "vault" / "a.md").stat().st_mtime
    assert time.localtime(stamp)[:6] == (2024, 3, 5, 12, 30, 0)

    # The next sync pass finds the marker and leaves dest alone.
    (dest / "vault" / "b.md").unlink()
    importer._unpack(archive, dest)
    assert not (dest / "vault" / "b.md").exists()

    folder = tmp_path / "export-folder"
    folder.mkdir()
    (folder / "x.csv").write_text("a\n")
    importer._unpack(folder, dest)
    (dest / "x.csv").unlink()
    importer._unpack(folder, dest)
    assert not (dest / "x.csv").exists()
