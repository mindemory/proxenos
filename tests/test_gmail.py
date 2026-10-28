"""Gmail IMAP ingester against a fake server. No network, no real mail."""

import imaplib
import json

import pytest

from twin.ingest import gmail


def message(msgid, sender, to, subject, date="Fri, 31 Jan 2025 10:00:00 +0000"):
    return (
        f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\nMessage-ID: <{msgid}>\r\n"
        f"Date: {date}\r\nContent-Type: text/plain\r\n\r\nSee you then.\r\n"
    ).encode()


class FakeImap:
    def __init__(self, mail, validity=7, password="right"):
        self.mail, self.validity, self.password = mail, validity, password
        self.selected = None
        self.fetched = []

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error("bad credentials")

    def list(self):
        return "OK", [
            b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
            b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
        ]

    def select(self, box, readonly):
        self.selected = (box, readonly)
        return "OK", [str(len(self.mail)).encode()]

    def response(self, code):
        return code, [str(self.validity).encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            # Like a real server, n:* always includes the highest UID even when it's below n.
            hits = [u for u in self.mail if u >= low] or [max(self.mail)]
            return "OK", [" ".join(map(str, hits)).encode()]
        uids = [int(u) for u in args[0].split(",")]
        self.fetched += uids
        data = []
        for u in uids:
            meta = f'{u} (X-GM-THRID 99{u} X-GM-LABELS (\\Inbox "\\\\Sent" "My label") UID {u} BODY[]<0> {{1}}'
            data += [(meta.encode(), self.mail[u]), b")"]
        return "OK", data

    def logout(self):
        pass


def stored(vault, name="personal"):
    out = vault / "raw" / "email" / name
    return {
        r["id"]: r for f in out.glob("*.jsonl") for r in map(json.loads, f.read_text().splitlines())
    }


MAIL = {
    1: message("m1", "ann@example.org", "me@example.com", "plan"),
    2: message("m2", "me@example.com", "ann@example.org", "Re: plan"),
}


def test_backfill_reads_all_mail_with_labels_and_marks_my_mail(tmp_path):
    fake = FakeImap(dict(MAIL))
    stats = gmail.ingest(tmp_path, "personal", "me@example.com", "right", connect=lambda: fake)
    assert stats["added"] == 2 and fake.selected == ('"[Gmail]/All Mail"', True)

    got = stored(tmp_path)
    assert got["m2"]["from_me"] and not got["m1"]["from_me"]
    assert got["m1"]["gmail_thread"] == "991"
    assert got["m1"]["gmail_labels"] == ["\\Inbox", "\\Sent", "My label"]


def test_later_runs_fetch_only_new_uids(tmp_path):
    fake = FakeImap(dict(MAIL))
    gmail.ingest(tmp_path, "personal", "me@example.com", "right", connect=lambda: fake)
    fake.fetched.clear()
    again = gmail.ingest(tmp_path, "personal", "me@example.com", "right", connect=lambda: fake)
    assert again["added"] == 0
    assert fake.fetched == []

    fake.mail[3] = message("m3", "bob@example.org", "me@example.com", "lunch")
    stats = gmail.ingest(tmp_path, "personal", "me@example.com", "right", connect=lambda: fake)
    assert stats["added"] == 1 and fake.fetched == [3]


def test_a_new_uidvalidity_starts_over(tmp_path):
    gmail.ingest(
        tmp_path, "personal", "me@example.com", "right", connect=lambda: FakeImap(dict(MAIL))
    )
    fresh = FakeImap(dict(MAIL), validity=8)
    gmail.ingest(tmp_path, "personal", "me@example.com", "right", connect=lambda: fresh)
    assert fresh.fetched == [1, 2]


def test_a_wrong_app_password_says_where_to_fix_it(tmp_path):
    with pytest.raises(SystemExit, match="app password"):
        gmail.ingest(
            tmp_path, "personal", "me@example.com", "wrong", connect=lambda: FakeImap(MAIL)
        )


def test_accounts_come_from_env_lines(monkeypatch):
    monkeypatch.setenv("GMAIL_PERSONAL", "me@example.com:abcd efgh ijkl mnop")
    monkeypatch.setenv("GMAIL_BROKEN", "no-password-here")
    assert gmail.accounts() == {"personal": ("me@example.com", "abcd efgh ijkl mnop")}
