"""slackdump archives, against a synthetic SQLite file in slackdump's layout. No real data."""

import json
import sqlite3

from proxenos.ingest import slackdump

SCHEMA = """
create table WORKSPACE (ID integer, LOAD_DTTM text, TEAM text, TEAM_ID text, USER_ID text);
create table S_USER (ID text, LOAD_DTTM text, DATA text);
create table CHANNEL (ID text, LOAD_DTTM text, NAME text, DATA text);
create table MESSAGE (CHANNEL_ID text, TS text, LOAD_DTTM text, DATA text);
create table CHANNEL_USER (CHANNEL_ID text, USER_ID text, CHUNK_ID integer, LOAD_DTTM text,
                           IDX integer);
"""


def make_archive(root, run="slackdump_20250101_000000"):
    folder = root / run
    folder.mkdir(parents=True)
    con = sqlite3.connect(folder / "slackdump.sqlite")
    con.executescript(SCHEMA)
    con.execute("insert into WORKSPACE values (1, 't1', 'Acme Lab', 'T1', 'U_ME')")
    users = [
        ("U_ME", {"id": "U_ME", "real_name": "Me"}),
        ("U_A", {"id": "U_A", "real_name": "Asha", "profile": {"email": "Asha@Example.org"}}),
        ("U_B", {"id": "U_B", "real_name": "Bo Quiet"}),
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
    # Everyone in #general, Bo too though Bo never wrote; and the DM's two, which is no group.
    con.executemany(
        "insert into CHANNEL_USER values (?, ?, 1, 't1', ?)",
        [("C1", "U_ME", 0), ("C1", "U_A", 1), ("C1", "U_B", 2), ("C1", "U_A", 3)]
        + [("D1", "U_ME", 0), ("D1", "U_A", 1)],
    )
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


def test_who_is_in_each_channel_comes_from_channel_user(tmp_path):
    make_archive(tmp_path / "Personal")
    stats = slackdump.ingest(tmp_path / "vault", tmp_path / "Personal")
    assert stats["channels"] == 1
    path = tmp_path / "vault" / "raw" / "slack" / "acme-lab" / "channels" / "snapshot.jsonl"
    (general,) = map(json.loads, path.read_text().splitlines())
    assert (general["id"], general["channel_name"], general["joined"]) == ("C1", "general", True)
    assert general["members"] == [
        {"id": "U_ME", "name": "Me", "email": None, "me": True},
        {"id": "U_A", "name": "Asha", "email": "asha@example.org", "me": False},
        {"id": "U_B", "name": "Bo Quiet", "email": None, "me": False},
    ]


def test_without_a_root_the_setting_and_the_data_folder_are_searched(tmp_path, monkeypatch):
    monkeypatch.setattr(slackdump, "REPO_ROOT", tmp_path / "repo")
    make_archive(tmp_path / "repo" / "data", "slackdump_20250101_000000")
    make_archive(tmp_path / "elsewhere", "slackdump_20250202_000000")

    def found(*root):
        return sorted(db.parent.name for db in slackdump.archives(*root))

    assert found() == ["slackdump_20250101_000000"]  # no setting: the data/ folder alone
    monkeypatch.setenv("PROXENOS_SLACKDUMP_DIR", str(tmp_path / "elsewhere"))
    assert found() == ["slackdump_20250101_000000", "slackdump_20250202_000000"]
    assert found(tmp_path / "elsewhere") == ["slackdump_20250202_000000"]  # a root is all it reads
