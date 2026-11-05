"""Which of the user's mailboxes a thread is on, from synthetic mail. No real data."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import chats, mailbox
from proxenos.clones import errands, work
from proxenos.ingest import gmail, microsoft

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
ME = "me@corp.com,me@example.com,me@gmail.com"


def write_month(vault, account, records):
    path = vault / "raw" / "email" / account / "2026-03.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")


def mail(account, thread, ts, sender, to, text, mine=False, mid=None, **fields):
    return {
        "id": mid or f"<{thread}.{ts}@mail.example>",
        "ts": ts,
        "account": account,
        "from_address": sender,
        "from_name": None if mine else sender.split("@")[0].title(),
        "from_me": mine,
        "to": list(to),
        "cc": None,
        "subject": "Hi",
        "gmail_thread": thread,
        "gmail_labels": ["Inbox"],
        "body_new": text,
    } | fields


@pytest.fixture(autouse=True)
def addresses(monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    monkeypatch.setenv("PROXENOS_NAME", "Me")


def waiting(tmp_path):
    return {c["chat"]: c for c in chats.waiting(tmp_path, NOW)}


def test_an_outlook_thread_is_on_the_address_it_came_to_and_says_outlook(tmp_path):
    write_month(
        tmp_path,
        "work",
        [
            mail("work", "AAQk", "2026-03-09T09:00:00Z", "me@corp.com", ["ana@x.org"], "Hi", True),
            mail(
                "work",
                "AAQk",
                "2026-03-09T10:00:00Z",
                "ana@x.org",
                ["Me <me@corp.com>"],
                "Can you send it?",
                mid="<DM6PR07MB1234.namprd07.prod.outlook.com>",
            ),
        ],
    )

    box = waiting(tmp_path)["AAQk"]["mailbox"]

    assert box == {"account": "work", "address": "me@corp.com", "provider": "outlook"}


def test_a_google_workspace_thread_has_a_numeric_thread_and_a_custom_domain(tmp_path):
    write_month(
        tmp_path,
        "lab",
        [
            mail(
                "lab", "1789", "2026-03-09T09:00:00Z", "me@example.com", ["ana@x.org"], "Hi", True
            ),
            mail("lab", "1789", "2026-03-09T10:00:00Z", "ana@x.org", ["me@example.com"], "Ready?"),
        ],
    )

    box = waiting(tmp_path)["1789"]["mailbox"]

    assert box == {"account": "lab", "address": "me@example.com", "provider": "google-workspace"}


def test_a_gmail_thread_is_on_the_address_that_got_the_latest_mail_not_the_first(tmp_path):
    write_month(
        tmp_path,
        "personal",
        [
            mail(
                "personal", "55", "2026-03-08T09:00:00Z", "me@corp.com", ["ana@x.org"], "Hi", True
            ),
            mail("personal", "55", "2026-03-09T10:00:00Z", "ana@x.org", ["me@gmail.com"], "Ready?"),
        ],
    )

    box = waiting(tmp_path)["55"]["mailbox"]

    assert box == {"account": "personal", "address": "me@gmail.com", "provider": "gmail"}


def test_with_nothing_inbound_to_them_it_is_the_address_their_last_email_went_from():
    thread = [
        {
            "id": "<a>",
            "ts": "2026-03-09T09:00:00Z",
            "mine": True,
            "mail": {"account": "x", "from": "me@corp.com", "to": ["ana@x.org"], "thread": None},
        },
        {
            "id": "<b>",
            "ts": "2026-03-09T10:00:00Z",
            "mine": False,
            "mail": {"account": "x", "from": "ana@x.org", "to": ["list@x.org"], "thread": None},
        },
    ]

    box = mailbox.of(thread, {"me@corp.com"})

    assert box["address"] == "me@corp.com" and box["account"] == "x"
    assert mailbox.of([{"ts": "t", "mine": False}], {"me@corp.com"}) is None


def test_a_signed_in_account_names_its_provider_before_the_records_do(monkeypatch):
    monkeypatch.setattr(microsoft, "accounts", lambda: {"office": ("me@corp.com", "t")})
    monkeypatch.setattr(gmail, "accounts", lambda: {"lab": ("me@example.com", "p")})

    assert mailbox.provider("office", "me@corp.com", ["<a@mail.example>"]) == "outlook"
    assert mailbox.provider("lab", "me@example.com") == "google-workspace"
    assert mailbox.provider("lab", "me@gmail.com") == "gmail"
    assert mailbox.provider("mbox", "me@hotmail.com") == "outlook"
    assert mailbox.provider("mbox", "me@corp.com", ["<a@mail.example>"]) == ""  # not guessed


def test_a_reply_draft_records_its_mailbox_and_one_with_no_chat_has_none(tmp_path):
    write_month(
        tmp_path,
        "work",
        [
            mail("work", "AAQk", "2026-03-08T09:00:00Z", "me@corp.com", ["ana@x.org"], "Hi", True),
            mail("work", "AAQk", "2026-03-09T10:00:00Z", "ana@x.org", ["me@corp.com"], "Ready?"),
        ],
    )
    (chat,) = chats.waiting(tmp_path, NOW)
    job = {"id": "reply-1", "for": "reply", "title": "Reply", "chat": chat}
    answer = {"title": "T", "kind": "reply", "channel": "email", "to": "Ana", "body": "Yes."}

    fields = work._front(work.render(work._draft(job, answer, NOW)))

    assert fields["from_account"] == "work" and fields["from_address"] == "me@corp.com"
    other = work._front(work.render(work._draft({**job, "chat": None}, answer, NOW)))
    assert "from_address" not in other


def test_an_errands_email_says_what_it_will_send_from(tmp_path, monkeypatch):
    write_month(
        tmp_path,
        "lab",
        [mail("lab", "9", "2026-03-09T10:00:00Z", "ana@x.org", ["me@example.com"], "Ready?")],
    )
    message = {"channel": "email", "address": "ana@x.org", "state": "ready"}

    errands.stamp(tmp_path, message)

    assert message["from_address"] == "me@example.com"
    assert message["from_provider"] == "google-workspace"
    monkeypatch.setenv("PROXENOS_MAIL_FROM", "me@corp.com")
    message["address"] = "bo@y.org"
    errands.stamp(tmp_path, message)  # a new address, so it looks again; the override wins
    assert message["from_address"] == "me@corp.com"
    chat_message = {"channel": "linkedin", "address": "", "state": "ready"}
    errands.stamp(tmp_path, chat_message)
    assert "from_address" not in chat_message
