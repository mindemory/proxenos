"""WhatsApp ingester against a synthetic ChatStorage.sqlite. No real data lives in this repo."""

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from twin import config
from twin.ingest import whatsapp

SCHEMA = """
create table ZWACHATSESSION (Z_PK integer primary key, ZCONTACTJID text, ZPARTNERNAME text,
                             ZSESSIONTYPE integer);
create table ZWAGROUPMEMBER (Z_PK integer primary key, ZMEMBERJID text, ZCONTACTNAME text,
                             ZFIRSTNAME text);
create table ZWAPROFILEPUSHNAME (Z_PK integer primary key, ZJID text, ZPUSHNAME text);
create table ZWAMEDIAITEM (Z_PK integer primary key, ZTITLE text);
create table ZWAMESSAGE (Z_PK integer primary key, ZCHATSESSION integer, ZGROUPMEMBER integer,
                         ZMEDIAITEM integer, ZISFROMME integer, ZMESSAGEDATE real,
                         ZMESSAGETYPE integer, ZSTANZAID text, ZTEXT text);
"""


def core_data(*args):
    return datetime(*args, tzinfo=UTC).timestamp() - 978307200


JAN_31 = core_data(2025, 1, 31, 23, 59, 59)
FEB_1 = core_data(2025, 2, 1)

# pk, chat, group member, media item, from_me, date, type, stanza, text
BASE = [
    (1, 1, None, None, 0, JAN_31, 0, "A1", "hi"),
    (2, 1, None, None, 1, FEB_1, 0, "A2", "hey"),
    (3, 2, 1, None, 0, FEB_1, 0, "G1", "meeting moved"),
    (4, 2, 2, 1, 0, FEB_1, 1, "G2", None),
]


def make_db(path, messages):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "insert into ZWACHATSESSION values (?, ?, ?, ?)",
        [(1, "111@s.whatsapp.net", "Asha", 0), (2, "999@g.us", "Lab group", 1)],
    )
    con.executemany(
        "insert into ZWAGROUPMEMBER values (?, ?, ?, ?)",
        [(1, "222@s.whatsapp.net", None, None), (2, "333@lid", "Ravi", "Ravi")],
    )
    con.execute("insert into ZWAPROFILEPUSHNAME values (1, '222@s.whatsapp.net', 'Meera')")
    con.execute("insert into ZWAMEDIAITEM values (1, 'look at this')")
    con.executemany("insert into ZWAMESSAGE values (?, ?, ?, ?, ?, ?, ?, ?, ?)", messages)
    con.commit()
    con.close()
    return path


def by_id(db):
    return {r["id"]: r for r in whatsapp.read_messages(db)}


def test_senders_come_from_the_chat_or_the_group_member(tmp_path):
    msgs = by_id(make_db(tmp_path / "c.sqlite", BASE))

    direct = msgs["111@s.whatsapp.net/A1"]
    assert direct["ts"] == "2025-01-31T23:59:59Z"
    assert (direct["chat_type"], direct["from_me"]) == ("direct", False)
    assert (direct["sender_id"], direct["sender_name"]) == ("111@s.whatsapp.net", "Asha")

    mine = msgs["111@s.whatsapp.net/A2"]
    assert mine["from_me"] is True
    assert (mine["sender_id"], mine["sender_name"]) == (None, None)

    group = msgs["999@g.us/G1"]
    assert (group["chat_type"], group["chat_name"]) == ("group", "Lab group")
    assert group["sender_name"] == "Meera"  # falls back to the push name


def test_media_captions_are_kept_and_deleted_messages_lose_their_content(tmp_path):
    deleted = (5, 1, None, 1, 0, FEB_1, 14, "A3", "regret")
    msgs = by_id(make_db(tmp_path / "c.sqlite", BASE + [deleted]))

    image = msgs["999@g.us/G2"]
    assert (image["kind"], image["caption"]) == ("image", "look at this")
    assert image["sender_name"] == "Ravi"

    gone = msgs["111@s.whatsapp.net/A3"]
    assert (gone["kind"], gone["text"], gone["caption"]) == ("deleted", None, None)


def test_reingest_is_idempotent_and_merges_changes(tmp_path):
    vault = tmp_path / "vault"
    out = vault / "raw" / "whatsapp" / "messages"

    first = whatsapp.ingest(vault, make_db(tmp_path / "1.sqlite", BASE))
    assert first == {"read": 4, "added": 4, "updated": 0, "months_written": 2}
    assert sorted(p.name for p in out.iterdir()) == ["2025-01.jsonl", "2025-02.jsonl"]

    again = whatsapp.ingest(vault, tmp_path / "1.sqlite")
    assert again == {"read": 4, "added": 0, "updated": 0, "months_written": 0}

    # Later store: A1 pruned from the Mac app, A2 deleted for everyone, A4 new.
    revoked = (2, 1, None, None, 1, FEB_1, 14, "A2", None)
    new = (6, 1, None, None, 1, FEB_1, 0, "A4", "ok")
    later = whatsapp.ingest(vault, make_db(tmp_path / "2.sqlite", [revoked, BASE[2], BASE[3], new]))
    assert later == {"read": 4, "added": 1, "updated": 1, "months_written": 1}

    jan = [json.loads(line) for line in (out / "2025-01.jsonl").read_text().splitlines()]
    feb = {r["id"]: r for r in map(json.loads, (out / "2025-02.jsonl").read_text().splitlines())}
    assert [r["id"] for r in jan] == ["111@s.whatsapp.net/A1"]
    assert feb["111@s.whatsapp.net/A2"]["text"] is None
    assert "111@s.whatsapp.net/A4" in feb


def test_vault_inside_the_public_repo_is_refused(monkeypatch):
    monkeypatch.setenv("TWIN_VAULT", str(config.REPO_ROOT / "vault"))
    with pytest.raises(ValueError, match="inside the public repo"):
        config.vault_path()
