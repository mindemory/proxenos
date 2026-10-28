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
    assert stats == {
        "twitter_imported": 1,
        "email_imported": 1,
        "chrome_imported": 1,
        "unrecognized": 1,
    }
    sources = {source: argv for source, argv in calls}
    assert sources["twitter"] == ["--export", str(vault / "exports" / "twitter-2026-10-27")]
    assert sources["email"][:2] == ["--account", "me-example-com"]
    # Both Takeout parts land in one folder.
    takeout = vault / "exports" / "takeout-20261027T1Z" / "Takeout"
    assert (takeout / "Mail").is_dir() and (takeout / "Chrome").is_dir()
    assert sources["chrome"] == ["--export", str(takeout / "Chrome")]

    left = sorted(p.name for p in inbox.iterdir())
    assert left == ["mystery.zip"]
    downloads = vault / "downloads"
    assert (downloads / "twitter" / "twitter-2026-10-27.zip").exists()
    assert sorted(p.name for p in (downloads / "google").iterdir()) == [
        "takeout-20261027T1Z-001.zip",
        "takeout-20261027T1Z-002.zip",
    ]


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


HEX = "0123456789abcdef0123456789abcdef"


def test_new_export_types_are_routed_by_their_distinctive_files(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    make_zip(
        inbox / "takeout-20261028T1Z-3-001.zip",
        {
            "Takeout/YouTube and YouTube Music/history/watch-history.html": "<html></html>",
            "Takeout/YouTube and YouTube Music/playlists/playlists.csv": "x",
            "Takeout/Chrome/History.json": "{}",
            "Takeout/Calendar/me@example.com.ics": "BEGIN:VCALENDAR",
            # Takeout's Drive can hold anything; it goes to the drive reader, not to notes.
            "Takeout/Drive/Old notes/Page " + HEX + ".md": "# Page",
        },
    )
    make_zip(
        inbox / "me@example.com.ical.zip",
        {"me@example.com.ics": "x", "Birthdays_me@example.com.ics": "x", "sub/other.ics": "x"},
    )
    make_zip(inbox / "letterboxd-me-2026.zip", {"diary.csv": "x", "watched.csv": "x"})
    make_zip(
        inbox / "facebook-me-2026.zip",
        {"your_facebook_activity/messages/inbox/a_1/message_1.json": "{}"},
    )
    make_zip(inbox / "threads-me-2026.zip", {"threads/threads_and_replies.json": "{}"})
    make_zip(
        inbox / "ExportBlock-1.zip",
        {f"Readings {HEX}.pdf": "x", f"Readings/Papers {HEX}.csv": "x"},
    )
    make_zip(inbox / "obsidian.zip", {"vault/.obsidian/app.json": "{}", "vault/Note.md": "x"})
    make_zip(inbox / "markdown.zip", {f"notes/n{i}.md": "x" for i in range(10)})
    make_zip(inbox / "few-notes.zip", {"a.md": "x", "orphaned/diary.csv": "x"})

    stats, calls = run(vault)
    exports = vault / "exports"
    takeout = exports / "takeout-20261028T1Z-3" / "Takeout"
    assert sorted(calls) == sorted(
        [
            ("youtube", ["--export", str(takeout / "YouTube and YouTube Music")]),
            ("chrome", ["--export", str(takeout / "Chrome")]),
            ("drive", ["--export", str(takeout / "Drive")]),
            ("calendar", ["--export", str(takeout / "Calendar")]),
            ("calendar", ["--export", str(exports / "me@example.com.ical")]),
            ("letterboxd", ["--export", str(exports / "letterboxd-me-2026")]),
            ("facebook", ["--export", str(exports / "facebook-me-2026")]),
            ("threads", ["--export", str(exports / "threads-me-2026")]),
            (
                "notes",
                [
                    "--export",
                    str(exports / "ExportBlock-1"),
                    "--pdf-dir",
                    str(exports / "ExportBlock-1"),
                ],
            ),
            ("notes", ["--export", str(exports / "obsidian")]),
            ("notes", ["--export", str(exports / "markdown")]),
        ]
    )
    assert stats["unrecognized"] == 1  # few-notes.zip
    assert stats["calendar_imported"] == 2 and stats["notes_imported"] == 3


def test_takeouts_drive_photos_keep_and_tasks_go_to_their_own_readers(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    make_zip(
        inbox / "takeout-20261028T2Z-001.zip",
        {
            "Takeout/Drive/Thesis.docx": "x",
            "Takeout/Drive/Notes/ideas.md": "# Ideas",
            "Takeout/Google Photos/Album/metadata.json": "{}",
            "Takeout/Google Photos/Photos from 2024/a.jpg.json": "{}",
            "Takeout/Keep/Note.json": "{}",
            "Takeout/Keep/Note.html": "x",
            "Takeout/Tasks/Tasks.json": "{}",
        },
    )
    # Another part of the same Takeout unpacks into the same folder, and another Takeout is its own.
    make_zip(inbox / "takeout-20261028T2Z-002.zip", {"Takeout/Mail/All mail.mbox": MBOX})
    make_zip(inbox / "takeout-20261028T3Z-001.zip", {"Takeout/Keep/Other.json": "{}"})
    # Folders with these names outside a Takeout are not Google's exports.
    make_zip(
        inbox / "stray.zip", {"Drive/a.docx": "x", "Keep/b.json": "x", "Tasks/Tasks.json": "x"}
    )

    stats, calls = run(vault)
    takeout = vault / "exports" / "takeout-20261028T2Z" / "Takeout"
    other = vault / "exports" / "takeout-20261028T3Z" / "Takeout"
    assert sorted(calls) == sorted(
        [
            ("drive", ["--export", str(takeout / "Drive")]),
            ("photos", ["--export", str(takeout / "Google Photos")]),
            ("keep", ["--export", str(takeout / "Keep")]),
            ("gtasks", ["--export", str(takeout / "Tasks")]),
            (
                "email",
                ["--account", "me-example-com", "--mbox", str(takeout / "Mail" / "All mail.mbox")],
            ),
            ("keep", ["--export", str(other / "Keep")]),
        ]
    )
    assert stats["unrecognized"] == 1  # stray.zip
    assert stats["drive_imported"] == stats["photos_imported"] == stats["gtasks_imported"] == 1
    assert stats["keep_imported"] == 2


def test_jobs_for_only_routes_folders_inside_a_takeout(tmp_path):
    export = tmp_path / "export"
    for name in ("Drive", "Google Photos", "Keep", "Tasks"):
        (export / "Takeout" / name).mkdir(parents=True)
    (export / "Takeout" / "Keep" / "Note.json").write_text("{}")
    (export / "Takeout" / "Drive2").mkdir()
    # Files with those names are not folders to read.
    (export / "Takeout" / "Profile").mkdir()
    (export / "Takeout" / "Profile" / "Drive").write_text("x")
    (export / "Drive").mkdir()

    jobs = importer.jobs_for(export)
    assert jobs == [
        ("drive", ["--export", str(export / "Takeout" / "Drive")]),
        ("photos", ["--export", str(export / "Takeout" / "Google Photos")]),
        ("keep", ["--export", str(export / "Takeout" / "Keep")]),
        ("gtasks", ["--export", str(export / "Takeout" / "Tasks")]),
    ]


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


def test_loose_pdfs_become_notes_and_are_filed_away(tmp_path):
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    (vault / "inbox" / "Plan.pdf").write_bytes(b"%PDF-1.4")
    (vault / "inbox" / "partial.pdf.crdownload").write_bytes(b"...")

    stats, calls = run(vault)
    folder = vault / "downloads" / "notes" / "pdfs"
    assert calls == [("notes", ["--pdf-dir", str(folder)])]
    assert stats == {"notes_imported": 1}
    assert (folder / "Plan.pdf").exists()
    assert [p.name for p in (vault / "inbox").iterdir()] == ["partial.pdf.crdownload"]


def test_a_file_that_cannot_be_unpacked_is_skipped_not_fatal(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "inbox").mkdir(parents=True)
    make_zip(vault / "inbox" / "a.zip", {"data/manifest.js": "x", "data/" + "n" * 300: "x"})
    stats, calls = run(vault)
    assert [source for source, _ in calls] == ["twitter"]
    assert stats == {"twitter_imported": 1}


def test_takeout_unpacks_everything_but_photo_and_video_files(tmp_path):
    archive = make_zip(
        tmp_path / "takeout-x-001.zip",
        {
            "Takeout/Mail/All mail.mbox": "x",
            "Takeout/Drive/huge.mov": "x",
            "Takeout/Drive/Thesis.docx": "x",
            "Takeout/Google Photos/a.jpg": "x",
            "Takeout/Google Photos/a.jpg.json": "{}",
            "Takeout/YouTube and YouTube Music/history/watch-history.html": "x",
        },
    )
    dest = tmp_path / "exports" / "takeout-x"
    importer._unpack(archive, dest)
    kept = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
    assert [k for k in kept if not k.startswith(".")] == [
        "Takeout/Drive/Thesis.docx",
        "Takeout/Google Photos/a.jpg.json",
        "Takeout/Mail/All mail.mbox",
        "Takeout/YouTube and YouTube Music/history/watch-history.html",
    ]
