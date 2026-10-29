"""Apple Mail ingester against a synthetic Mail folder. No real mail lives in this repo."""

import argparse
import json
import os
import sys
import time

import pytest

from proxenos import cli, master
from proxenos.ingest import applemail
from proxenos.ingest import email as email_ingest

DAY = 86400
PLIST = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
    b"<key>flags</key><integer>8590195713</integer></dict></plist>\n"
)
# Mail names a mailbox folder after the mailbox, with .mbox on the end, and nests them.
UUID_A = "11111111-AAAA-4BBB-8CCC-000000000001"
UUID_B = "22222222-AAAA-4BBB-8CCC-000000000002"
UUID_C = "33333333-AAAA-4BBB-8CCC-000000000003"
ME = "me@example.org"


def message(msgid, sender, to, subject="Plan", date="Fri, 31 Jan 2025 10:00:00 +0000", cc=None):
    cc_line = f"Cc: {cc}\n" if cc else ""
    return (
        f"From: {sender}\nTo: {to}\n{cc_line}Subject: {subject}\nMessage-ID: <{msgid}>\n"
        f"Date: {date}\nContent-Type: text/plain; charset=utf-8\n\nSee you then.\n"
    )


# What Mail keeps for a message whose attachment hasn't been downloaded.
STRIPPED = """\
From: Ann <ann@example.org>
To: me@example.org
Subject: Notes
Message-ID: <partial-1@example.org>
Date: Sat, 01 Feb 2025 09:00:00 +0000
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: text/plain; charset=utf-8

The notes are attached.
--b1
Content-Type: application/pdf; name="notes.pdf"
Content-Disposition: attachment; filename="notes.pdf"

--b1--
"""


def put(root, account, mailbox, name, text, partial=False, mtime=None, version="V10"):
    """Write one .emlx (or .partial.emlx): the byte count, the message, then a flags plist."""
    folder = root / version / account
    for part in mailbox.split("/"):
        folder = folder / f"{part}.mbox"
    folder = folder / "5B2C9A10-0000-4000-8000-000000000000" / "Data" / "1" / "2" / "Messages"
    folder.mkdir(parents=True, exist_ok=True)
    raw = text.replace("\n", "\r\n").encode() if isinstance(text, str) else text
    path = folder / f"{name}{'.partial' if partial else ''}.emlx"
    path.write_bytes(str(len(raw)).encode() + b"\n" + raw + PLIST)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def read(vault, root, *flags):
    parser = argparse.ArgumentParser()
    applemail.add_arguments(parser)
    return applemail.run(vault, parser.parse_args(["--root", str(root), *flags]))


def stored(vault, stream="me-example-org"):
    out = vault / "raw" / "email" / stream
    return {
        r["id"]: r for f in out.glob("*.jsonl") for r in map(json.loads, f.read_text().splitlines())
    }


@pytest.fixture
def mail(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    return tmp_path / "Mail"


def test_reads_emlx_and_partial_emlx_from_the_newest_store(tmp_path, mail):
    put(mail, UUID_A, "INBOX", "1", message("m1", "Ann <ann@example.org>", ME))
    put(mail, UUID_A, "INBOX", "2", STRIPPED, partial=True)
    put(mail, UUID_A, "INBOX", "3", message("old-store", "ann@example.org", ME), version="V9")

    stats = read(tmp_path / "vault", mail)

    assert (stats["read"], stats["added"], stats["skipped"]) == (2, 2, 0)
    got = stored(tmp_path / "vault")
    assert set(got) == {"m1", "partial-1@example.org"}
    assert got["m1"]["ts"] == "2025-01-31T10:00:00Z"
    assert (got["m1"]["from_address"], got["m1"]["from_name"]) == ("ann@example.org", "Ann")
    assert got["m1"]["to"] == [ME] and got["m1"]["account"] == "me-example-org"
    assert got["m1"]["gmail_labels"] == ["INBOX"] and got["m1"]["body"] == "See you then."
    assert got["partial-1@example.org"]["attachments"] == ["notes.pdf"]
    assert (tmp_path / "vault" / "raw" / "email" / "me-example-org" / "2025-01.jsonl").exists()


def test_each_account_is_the_address_of_yours_it_mostly_mails_with(tmp_path, mail, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", f"{ME}, Work@Example.net ,alias@example.org")
    for n, to in enumerate([ME, ME, "alias@example.org"]):
        put(mail, UUID_A, "INBOX", n, message(f"a{n}", "ann@example.org", to))
    for n, to in enumerate(["work@example.net", "work@example.net", ME]):
        put(mail, UUID_B, "INBOX", n, message(f"b{n}", "ann@example.org", to))
    put(mail, UUID_B, "Sent Items", "9", message("b-sent", "Work@Example.net", "ann@example.org"))
    # An account where none of mine appears is skipped and counted.
    put(mail, UUID_C, "INBOX", "1", message("c1", "ann@example.org", "stranger@example.com"))

    stats = read(tmp_path / "vault", mail)

    assert stats["accounts_skipped"] == 1 and stats["added"] == 7
    assert set(stored(tmp_path / "vault")) == {"a0", "a1", "a2"}
    assert set(stored(tmp_path / "vault", "work-example-net")) == {"b0", "b1", "b2", "b-sent"}
    sent = stored(tmp_path / "vault", "work-example-net")["b-sent"]
    assert sent["from_me"] is True and sent["gmail_labels"] == ["Sent Items"]
    assert stored(tmp_path / "vault")["a0"]["from_me"] is False
    assert sorted(p.name for p in (tmp_path / "vault" / "raw" / "email").iterdir()) == [
        "me-example-org",
        "work-example-net",
    ]

    # Once the address is listed, --full reads the account that was skipped.
    monkeypatch.setenv("PROXENOS_EMAILS", f"{ME},work@example.net,stranger@example.com")
    assert read(tmp_path / "vault", mail)["read"] == 0
    assert read(tmp_path / "vault", mail, "--full")["accounts_skipped"] == 0
    assert set(stored(tmp_path / "vault", "stranger-example-com")) == {"c1"}


def test_mailbox_paths_become_labels_and_junk_spam_and_trash_stay_out(tmp_path, mail):
    kept = ["INBOX", "[Gmail]/Sent Mail", "Archive/2024"]
    left_out = ["Junk", "Junk Email", "[Gmail]/Spam", "[Gmail]/Trash", "Deleted Items"]
    for n, mailbox in enumerate([*kept, *left_out]):
        put(mail, UUID_A, mailbox, "1", message(f"m{n}", "ann@example.org", ME))

    assert read(tmp_path / "vault", mail)["added"] == 3
    got = stored(tmp_path / "vault")
    assert {r["gmail_labels"][0] for r in got.values()} == set(kept)


def test_a_second_run_reads_nothing_new_and_a_newer_file_is_read(tmp_path, mail):
    vault = tmp_path / "vault"
    now = time.time()
    put(mail, UUID_A, "INBOX", "1", message("m1", "ann@example.org", ME), mtime=now - 3 * DAY)
    put(mail, UUID_A, "INBOX", "2", message("m2", "ann@example.org", ME), mtime=now - 2 * DAY)
    put(  # past the first run's 180 days
        mail,
        UUID_A,
        "INBOX",
        "3",
        message("m3", "ann@example.org", ME, date="Mon, 30 Dec 2024 10:00:00 +0000"),
        mtime=now - 400 * DAY,
    )

    assert read(vault, mail)["added"] == 2
    assert set(stored(vault)) == {"m1", "m2"}
    assert (vault / "state" / "applemail.json").exists()
    before = {p.name: p.read_bytes() for p in (vault / "raw" / "email").rglob("*.jsonl")}

    assert read(vault, mail)["read"] == 0
    assert {p.name: p.read_bytes() for p in (vault / "raw" / "email").rglob("*.jsonl")} == before

    # Mail from a list names none of mine, but the account is already known.
    put(
        mail,
        UUID_A,
        "INBOX",
        "4",
        message("m4", "list@example.com", "list@example.com"),
        mtime=now - DAY,
    )
    stats = read(vault, mail)
    assert (stats["read"], stats["added"]) == (1, 1) and "m4" in stored(vault)

    assert read(vault, mail, "--full")["read"] == 4
    assert "m3" in stored(vault)


def test_the_same_message_in_an_mbox_and_in_mail_is_one_record(tmp_path, mail):
    vault = tmp_path / "vault"
    mbox = tmp_path / "takeout.mbox"
    text = message("shared-1", "Ann <ann@example.org>", ME)
    mbox.write_text(
        f"From ann@example.org Fri Jan 31 10:00:00 2025\n{text}\n"
        + "From ann@example.org Fri Jan 31 11:00:00 2025\n"
        + message("only-takeout", "ann@example.org", ME, date="Fri, 31 Jan 2025 11:00:00 +0000")
        + "\n"
    )
    email_ingest.ingest(vault, mbox, "me-example-org", [ME])
    from_mbox = stored(vault)["shared-1"]

    put(mail, UUID_A, "INBOX", "1", text)
    stats = read(vault, mail)

    assert stats["read"] == 1 and stats["added"] == 0
    got = stored(vault)
    assert set(got) == {"shared-1", "only-takeout"}
    assert set(got["shared-1"]) == set(from_mbox)
    assert {k: v for k, v in got["shared-1"].items() if k != "gmail_labels"} == {
        k: v for k, v in from_mbox.items() if k != "gmail_labels"
    }
    assert got["shared-1"]["gmail_labels"] == ["INBOX"]


def test_files_that_cannot_be_parsed_are_skipped_and_the_rest_land(tmp_path, mail):
    put(mail, UUID_A, "INBOX", "1", message("ok", "ann@example.org", ME))
    put(mail, UUID_A, "INBOX", "2", "x").write_bytes(b"not a byte count\nFrom: x\n")
    put(mail, UUID_A, "INBOX", "3", "From: ann@example.org\nSubject: Undatable\n\nNo date.\n")
    cut = put(mail, UUID_A, "INBOX", "4", "x")
    cut.write_bytes(b"9999\nFrom: ann@example.org\n")  # a count longer than the file
    put(mail, UUID_A, "INBOX", "5", b"")

    stats = read(tmp_path / "vault", mail)

    assert (stats["added"], stats["skipped"]) == (1, 4)
    assert set(stored(tmp_path / "vault")) == {"ok"}


def test_available_only_when_mails_folder_can_be_listed(tmp_path, mail):
    assert not applemail.available(mail)  # no Mail folder
    mail.mkdir()
    assert not applemail.available(mail)  # no account yet
    put(mail, UUID_A, "INBOX", "1", message("m1", "ann@example.org", ME))
    assert applemail.available(mail)

    with pytest.raises(SystemExit, match="no Mail store"):
        read(tmp_path / "vault", tmp_path / "nowhere")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any folder")
def test_a_folder_macos_blocks_says_to_give_full_disk_access(tmp_path, mail):
    put(mail, UUID_A, "INBOX", "1", message("m1", "ann@example.org", ME))
    mail.chmod(0)
    try:
        assert not applemail.available(mail)
        with pytest.raises(SystemExit) as stopped:
            read(tmp_path / "vault", mail)
    finally:
        mail.chmod(0o700)

    reason = str(stopped.value)
    assert "\n" not in reason and sys.executable in reason
    assert "Full Disk Access" in reason and "Privacy & Security" in reason
    assert not (tmp_path / "vault" / "raw").exists()


def test_without_proxenos_emails_it_says_so_instead_of_skipping_everything(
    tmp_path, mail, monkeypatch
):
    put(mail, UUID_A, "INBOX", "1", message("m1", "ann@example.org", ME))
    monkeypatch.delenv("PROXENOS_EMAILS")

    with pytest.raises(SystemExit, match="PROXENOS_EMAILS"):
        read(tmp_path / "vault", mail)


def test_proxenos_ingest_applemail_runs_and_sync_checks_it_is_available(
    tmp_path, mail, monkeypatch, capsys
):
    put(mail, UUID_A, "INBOX", "1", message("m1", "ann@example.org", ME))
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))

    cli.main(["ingest", "applemail", "--root", str(mail)])

    assert capsys.readouterr().out.startswith("applemail: 1 read, 1 added")
    assert (applemail, applemail.available) in master._UNATTENDED
