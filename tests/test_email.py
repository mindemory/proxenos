"""Email ingester against synthetic mbox files. No real data lives in this repo."""

import argparse
import json

import pytest

from proxenos.ingest import email as email_ingest

# Used when a message doesn't bring its own From_ line.
FROM_LINE = "From sender@example.com Sat Feb  1 00:00:00 2025"

ALTERNATIVE = """\
From: Asha Rao <asha@example.com>
To: Me <me@example.com>, Ravi <RAVI@example.com>
Cc: lab@example.com
Subject: Lunch?
Date: Fri, 31 Jan 2025 18:59:59 -0500
Message-ID: <alt-1@example.com>
X-Gmail-Labels: Inbox,Important,"Lab, misc"
X-GM-THRID: 1790000000000000001
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="b1"

--b1
Content-Type: text/plain; charset=utf-8

Lunch at noon?
--b1
Content-Type: text/html; charset=utf-8

<p>Lunch at <b>noon</b>?</p>
--b1--
"""

HTML_ONLY = """\
From: Ravi <ravi@example.com>
To: me@example.com
Subject: Agenda
Date: Sat, 01 Feb 2025 09:00:00 +0000
Message-ID: <html-1@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b2"

--b2
Content-Type: text/html; charset=utf-8

<html><head><title>x</title><style>p {color: red}</style></head><body>
<p>Agenda for&nbsp;Monday:</p><ul><li>Data &amp; models</li><li>Next
   steps</li></ul>
<p>Thanks,<br/>Ravi</p><script>track()</script>
</body></html>
--b2
Content-Type: application/pdf; name="agenda.pdf"
Content-Disposition: attachment; filename="agenda.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--b2--
"""

# ">From" is how mbox escapes a body line starting "From ". It isn't a quote.
GMAIL_REPLY = """\
From: Me <Me@Example.com>
To: Asha Rao <asha@example.com>
Subject: Re: Lunch?
Date: Sat, 01 Feb 2025 10:00:00 +0000
Message-ID: <reply-1@example.com>
In-Reply-To: <alt-1@example.com>
Content-Type: text/plain; charset=utf-8

> Lunch at noon?
Noon works.
>From the menu, the soup looks good.

On Fri, Jan 31, 2025 at 6:59 PM Asha Rao <asha@example.com>
wrote:
> Lunch at noon?
>
> On Thu, Jan 30, 2025 at 9:00 AM Ravi <ravi@example.com> wrote:
>> Anyone free?
"""

OUTLOOK_REPLY = """\
From: Me <me@example.com>
To: Ravi <ravi@example.com>
Subject: RE: Agenda
Date: Sat, 01 Feb 2025 11:00:00 +0000
Message-ID: <reply-2@example.com>
In-Reply-To: <html-1@example.com> <older@example.com>
Content-Type: text/html; charset=utf-8

<div>Looks good.</div><div><br></div><div>Me</div>
<hr><div><b>From:</b> Ravi &lt;ravi@example.com&gt;<br><b>Sent:</b> Saturday, February 1
<br><b>Subject:</b> Agenda</div><div>Agenda for Monday</div>
"""

# No Message-ID and no Date: the id is a content hash and ts comes from Takeout's From_ line.
NO_ID = """\
From MAILER-DAEMON Wed Mar 12 18:23:45 +0000 2025
From: Asha Rao <asha@example.com>
To: me@example.com
Subject: No id here

Body without an id.
"""

NO_DATE = """\
From nobody
From: Asha Rao <asha@example.com>
Subject: Undatable

Nothing says when this was sent.
"""

ENCODED = """\
From: =?ISO-8859-1?Q?Ren=E9e_Dubois?= <renee@example.com>
To: me@example.com
Subject: =?UTF-8?B?Q2Fmw6kg4piV?= =?UTF-8?Q?_at_noon?=
Date: Sun, 02 Feb 2025 08:00:00 +0100
Message-ID: <enc-1@example.com>
Content-Type: text/plain; charset=utf-8
Content-Transfer-Encoding: quoted-printable

Merci, =C3=A0 bient=C3=B4t
"""

# An unknown charset on the body and in an encoded word, plus a raw Latin-1 byte in a header.
BAD_CHARSET = b"""\
From: Ravi <ravi@example.com>
To: me@example.com
Subject: =?x-no-such-charset?Q?caf=E9?= and a raw \xe9 byte
Date: Sun, 02 Feb 2025 09:00:00 +0000
Message-ID: <bad-1@example.com>
Content-Type: text/plain; charset="x-no-such-charset"
Content-Transfer-Encoding: 8bit

caf\xc3\xa9 au lait
"""

ALL = [ALTERNATIVE, HTML_ONLY, GMAIL_REPLY, OUTLOOK_REPLY, NO_ID, NO_DATE, ENCODED, BAD_CHARSET]


def make_mbox(path, messages):
    with path.open("wb") as f:
        for message in messages:
            raw = message.encode() if isinstance(message, str) else message
            if not raw.startswith(b"From "):
                raw = FROM_LINE.encode() + b"\n" + raw
            f.write(raw + b"\n")
    return path


def by_id(mbox, me=("me@example.com",)):
    return {r["id"]: r for r in email_ingest.read_messages(mbox, "gmail", me) if r}


def test_multipart_alternative_prefers_plain_text_and_keeps_the_headers(tmp_path):
    msg = by_id(make_mbox(tmp_path / "m.mbox", [ALTERNATIVE]))["alt-1@example.com"]

    assert msg["ts"] == "2025-01-31T23:59:59Z"
    assert (msg["from_address"], msg["from_name"], msg["from_me"]) == (
        "asha@example.com",
        "Asha Rao",
        False,
    )
    assert msg["to"] == ["me@example.com", "ravi@example.com"]
    assert msg["cc"] == ["lab@example.com"]
    assert msg["subject"] == "Lunch?"
    assert msg["gmail_labels"] == ["Inbox", "Important", "Lab, misc"]
    assert msg["gmail_thread"] == "1790000000000000001"
    assert (msg["body"], msg["body_new"]) == ("Lunch at noon?", "Lunch at noon?")
    assert (msg["in_reply_to"], msg["attachments"]) == (None, None)


def test_html_only_body_becomes_text_and_attachments_are_named(tmp_path):
    msg = by_id(make_mbox(tmp_path / "m.mbox", [HTML_ONLY]))["html-1@example.com"]

    assert msg["body"] == "Agenda for Monday:\nData & models\nNext steps\nThanks,\nRavi"
    assert msg["attachments"] == ["agenda.pdf"]
    assert msg["gmail_labels"] is None  # not a Takeout export


def test_body_new_drops_quotes_and_the_attribution_onward(tmp_path):
    msgs = by_id(make_mbox(tmp_path / "m.mbox", [GMAIL_REPLY, OUTLOOK_REPLY]))

    gmail = msgs["reply-1@example.com"]
    assert gmail["body"].startswith("> Lunch at noon?\nNoon works.\nFrom the menu")
    assert gmail["body_new"] == "Noon works.\nFrom the menu, the soup looks good."
    assert gmail["in_reply_to"] == "alt-1@example.com"

    outlook = msgs["reply-2@example.com"]
    assert "From: Ravi <ravi@example.com>\nSent: Saturday" in outlook["body"]
    assert outlook["body_new"] == "Looks good.\n\nMe"
    assert outlook["in_reply_to"] == "html-1@example.com"


def test_missing_message_id_or_date_falls_back_and_no_date_at_all_is_skipped(tmp_path):
    mbox = make_mbox(tmp_path / "m.mbox", [NO_ID, NO_DATE])
    records = list(email_ingest.read_messages(mbox, "gmail"))

    assert records[1] is None  # neither a Date header nor a date on the From_ line
    msg = records[0]
    assert msg["ts"] == "2025-03-12T18:23:45Z"
    assert len(msg["id"]) == 64 and int(msg["id"], 16) >= 0  # sha256 hex
    assert [r["id"] for r in email_ingest.read_messages(mbox, "gmail") if r] == [msg["id"]]


def test_encoded_headers_and_bad_charsets_are_decoded_not_fatal(tmp_path):
    vault = tmp_path / "vault"
    stats = email_ingest.ingest(vault, make_mbox(tmp_path / "m.mbox", [ENCODED, BAD_CHARSET]), "x")
    assert (stats["added"], stats["skipped"]) == (2, 0)

    lines = (vault / "raw" / "email" / "x" / "2025-02.jsonl").read_text("utf-8").splitlines()
    msgs = {r["id"]: r for r in map(json.loads, lines)}

    encoded = msgs["enc-1@example.com"]
    assert encoded["ts"] == "2025-02-02T07:00:00Z"
    assert encoded["subject"] == "Café ☕ at noon"
    assert encoded["from_name"] == "Renée Dubois"
    assert encoded["body"] == "Merci, à bientôt"

    bad = msgs["bad-1@example.com"]
    assert bad["body"] == "café au lait"  # unknown charset, read as UTF-8
    assert bad["subject"].endswith("byte") and "�" in bad["subject"]


def test_from_me_matches_my_addresses_and_falls_back_to_proxenos_emails(tmp_path, monkeypatch):
    mbox = make_mbox(tmp_path / "m.mbox", [ALTERNATIVE, GMAIL_REPLY])
    assert by_id(mbox)["reply-1@example.com"]["from_me"] is True  # case-insensitive

    def from_me(me):
        args = argparse.Namespace(account="gmail", mbox=mbox, me=me)
        vault = tmp_path / f"vault{len(me)}"
        email_ingest.run(vault, args)
        out = vault / "raw" / "email" / "gmail"
        lines = [line for path in out.iterdir() for line in path.read_text().splitlines()]
        return {r["id"]: r["from_me"] for r in map(json.loads, lines)}

    monkeypatch.setenv("PROXENOS_EMAILS", "old@example.org, ME@example.com")
    assert from_me([]) == {"alt-1@example.com": False, "reply-1@example.com": True}
    # An explicit --me replaces the env var.
    assert from_me(["old@example.org"]) == {
        "alt-1@example.com": False,
        "reply-1@example.com": False,
    }


def test_reingest_in_batches_is_idempotent_and_merges_changes(tmp_path):
    vault = tmp_path / "vault"
    out = vault / "raw" / "email" / "gmail"
    mbox = make_mbox(tmp_path / "1.mbox", ALL)

    # Batches of 2: [alt, html] [gmail, outlook] [no-id, encoded] [bad]. Stats are summed.
    first = email_ingest.ingest(vault, mbox, "gmail", batch_size=2)
    assert first == {"read": 7, "added": 7, "updated": 0, "months_written": 6, "skipped": 1}
    assert sorted(p.name for p in out.iterdir()) == [
        "2025-01.jsonl",
        "2025-02.jsonl",
        "2025-03.jsonl",
    ]

    again = email_ingest.ingest(vault, mbox, "gmail")
    assert again == {"read": 7, "added": 0, "updated": 0, "months_written": 0, "skipped": 1}

    # A later Takeout: the first message lost its Important label, and one is new.
    relabeled = ALTERNATIVE.replace("Inbox,Important,", "Inbox,")
    new = ENCODED.replace("enc-1@", "enc-2@")
    later = email_ingest.ingest(vault, make_mbox(tmp_path / "2.mbox", [relabeled, new]), "gmail")
    assert later == {"read": 2, "added": 1, "updated": 1, "months_written": 2, "skipped": 0}

    jan = [json.loads(line) for line in (out / "2025-01.jsonl").read_text().splitlines()]
    assert jan[0]["gmail_labels"] == ["Inbox", "Lab, misc"]
    feb = (out / "2025-02.jsonl").read_text().splitlines()
    assert len(feb) == 6  # five from the first run plus enc-2


def test_a_message_the_parser_chokes_on_is_skipped_and_the_rest_still_land(tmp_path, monkeypatch):
    real_body = email_ingest._body

    def body(msg):
        if msg["Subject"] == "Agenda":
            raise RuntimeError("synthetic parser failure")
        return real_body(msg)

    monkeypatch.setattr(email_ingest, "_body", body)
    mbox = make_mbox(tmp_path / "m.mbox", [ALTERNATIVE, HTML_ONLY, ENCODED])
    stats = email_ingest.ingest(tmp_path / "vault", mbox, "gmail")
    assert (stats["added"], stats["skipped"]) == (2, 1)


def test_account_must_be_a_plain_directory_name(tmp_path):
    mbox = make_mbox(tmp_path / "m.mbox", [ALTERNATIVE])
    with pytest.raises(ValueError, match="names a directory"):
        email_ingest.ingest(tmp_path / "vault", mbox, "../gmail")


def test_a_message_id_repeated_in_one_export_is_one_record_and_the_last_copy_wins(tmp_path):
    later_copy = ALTERNATIVE.replace("Lunch at noon?", "Lunch at one?")
    mbox = make_mbox(tmp_path / "m.mbox", [ALTERNATIVE, later_copy])
    stats = email_ingest.ingest(tmp_path / "vault", mbox, "gmail")
    assert (stats["read"], stats["added"]) == (1, 1)

    path = tmp_path / "vault" / "raw" / "email" / "gmail" / "2025-01.jsonl"
    assert json.loads(path.read_text())["body"] == "Lunch at one?"
