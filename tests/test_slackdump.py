"""slackdump archives, against a synthetic SQLite file in slackdump's layout. No real data."""

import json
import sqlite3

from twin.ingest import slackdump

SCHEMA = """
create table WORKSPACE (ID integer, LOAD_DTTM text, TEAM text, TEAM_ID text, USER_ID text);
create table S_USER (ID text, LOAD_DTTM text, DATA text);
create table CHANNEL (ID text, LOAD_DTTM text, NAME text, DATA text);
create table MESSAGE (CHANNEL_ID text, TS text, LOAD_DTTM text, DATA text);
"""


def make_archive(root, run="slackdump_20250101_000000"):
    folder = root / run
    folder.mkdir(parents=True)
    con = sqlite3.connect(folder / "slackdump.sqlite")
    con.executescript(SCHEMA)
    con.execute("insert into WORKSPACE values (1, 't1', 'Acme Lab', 'T1', 'U_ME')")
    users = [
        ("U_ME", {"id": "U_ME", "real_name": "Me"}),
        ("U_A", {"id": "U_A", "real_name": "Asha"}),
    ]
    con.executemany(
        "insert into S_USER values (?, 't1', ?)", [(u, json.dumps(d)) for u, d in users]
    )
    channels = [
        ("C1", "general", {"id": "C1", "name": "general"}),
        ("D1", "", {"id": "D1", "is_im": True, "user": "U_A"}),
    ]
    con.executemany(
        "insert into CHANNEL values (?, 't1', ?, ?)",
        [(c, n, json.dumps(d)) for c, n, d in channels],
    )
    messages = [
        (
            "C1",
            "1735689600.000100",
            "t1",
            {"ts": "1735689600.000100", "user": "U_A", "text": "old"},
        ),
        (
            "C1",
            "1735689600.000100",
            "t2",
            {"ts": "1735689600.000100", "user": "U_A", "text": "edited"},
        ),
        (
            "D1",
            "1735689700.000200",
            "t1",
            {"ts": "1735689700.000200", "user": "U_ME", "text": "hi"},
        ),
    ]
    con.executemany(
        "insert into MESSAGE values (?, ?, ?, ?)",
        [(c, ts, t, json.dumps(d)) for c, ts, t, d in messages],
    )
    con.commit()
    con.close()


def stored(vault):
    out = vault / "raw" / "slack" / "acme-lab" / "messages"
    return {
        r["id"]: r for f in out.glob("*.jsonl") for r in map(json.loads, f.read_text().splitlines())
    }


def test_archives_become_slack_records_with_the_latest_copy_of_each_message(tmp_path):
    make_archive(tmp_path / "Personal")
    stats = slackdump.ingest(tmp_path / "vault", tmp_path / "Personal")
    assert (stats["archives"], stats["added"]) == (1, 2)

    got = stored(tmp_path / "vault")
    general = got["C1/1735689600.000100"]
    assert (general["text"], general["user_name"], general["from_me"]) == ("edited", "Asha", False)
    dm = got["D1/1735689700.000200"]
    assert (dm["channel_type"], dm["channel_name"], dm["from_me"]) == ("dm", "Asha", True)


def test_rereading_the_same_archives_changes_nothing(tmp_path):
    make_archive(tmp_path / "Personal")
    slackdump.ingest(tmp_path / "vault", tmp_path / "Personal")
    again = slackdump.ingest(tmp_path / "vault", tmp_path / "Personal")
    assert (again["added"], again["updated"]) == (0, 0)
