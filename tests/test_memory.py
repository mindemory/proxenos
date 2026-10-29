"""The memory index, search and context, on a synthetic vault. No real data, no model."""

import json
import os
import sqlite3
import stat

import pytest

from proxenos import cli, memory


def write_month(vault, folder, month, records):
    path = vault / "raw" / folder / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def chat(n, text, sender="Mira Lund", chat_name="Book club", from_me=False, day=3, month="2025-03"):
    return {
        "id": f"w{n}",
        "ts": f"{month}-{day:02d}T10:{n:02d}:00+00:00",
        "chat_id": "chat-1",
        "chat_name": chat_name,
        "sender_name": sender,
        "from_me": from_me,
        "text": text,
        "caption": None,
    }


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    write_month(
        v,
        "whatsapp/messages",
        "2025-03",
        [
            chat(1, "Who wants to read the lichen paper this month?"),
            chat(2, "I do, send me the PDF", sender="Me", from_me=True),
            chat(3, "Sending it now, it is about symbiosis"),
            {**chat(4, None), "caption": None},  # a picture with no words: not indexed
        ],
    )
    write_month(
        v,
        "slack/acme/messages",
        "2025-03",
        [
            {
                "id": "s1",
                "ts": "2025-03-04T09:00:00Z",
                "channel_id": "C1",
                "channel_name": "lab-notes",
                "user_name": "Tobias Okafor",
                "from_me": False,
                "text": "The centrifuge is broken again",
            }
        ],
    )
    write_month(
        v,
        "email/me-example-org",
        "2025-03",
        [
            {
                "id": "<m1@x>",
                "ts": "2025-03-05T12:00:00Z",
                "subject": "Grant budget",
                "from_name": "Priya Raman",
                "to": ["me@example.org"],
                "from_me": False,
                "body_new": "Please review the budget before Friday. Café receipts attached.",
                "gmail_thread": "T9",
            },
            {
                "id": "<m2@x>",
                "ts": "2025-03-06T12:00:00Z",
                "subject": "Re: Grant budget",
                "from_name": "Me",
                "to": ["priya@example.org"],
                "from_me": True,
                "body_new": "Looks fine to me.",
                "gmail_thread": "T9",
            },
        ],
    )
    write_month(
        v,
        "calendar/work",
        "2025-03",
        [
            {
                "id": "e1",
                "ts": "2025-03-07T15:00:00Z",
                "summary": "Thesis committee",
                "description": "Chapter two draft",
                "location": "Room 12",
                "guests": [{"name": "Dana Whitfield", "email": "dana@example.org"}],
                "attendees": 2,
            },
            {"id": "e2", "ts": "2025-03-07T18:00:00Z", "summary": "Dinner", "attendees": 0},
        ],
    )
    write_month(
        v,
        "chrome/visits",
        "2025-03",
        [
            {
                "id": "c1",
                "ts": "2025-03-08T08:00:00Z",
                "title": "Mushroom field guide",
                "url": "https://www.example.com/private/path?token=SECRETVALUE",
            },
            {"id": "c2", "ts": "2025-03-08T08:01:00Z", "title": "", "url": "https://x.test/"},
        ],
    )
    write_month(
        v,
        "spotify/plays",
        "2025-03",
        [
            {"id": "p1", "ts": "2025-03-09T08:00:00Z", "kind": "track", "ms_played": 180000,
             "artist": "The Ferns", "track": "Moss Song", "incognito": False},
            {"id": "p2", "ts": "2025-03-09T08:05:00Z", "kind": "track", "ms_played": 0,
             "artist": "Skipped Band", "track": "Nope", "incognito": False},
        ],
    )  # fmt: skip
    write_month(
        v,
        "strava/activities",
        "2025-03",
        [
            {"id": "a1", "ts": "2025-03-10T07:00:00Z", "name": "Morning Run", "sport_type": "Run",
             "distance_m": 5000, "moving_time_s": 1500},
            {"id": "a2", "ts": "2025-03-12T07:00:00Z", "name": "Lunch Ride", "sport_type": "Ride",
             "distance_m": 20000, "moving_time_s": 3600},
        ],
    )  # fmt: skip
    # A group snapshot is not a month file.
    (v / "raw/whatsapp/messages/snapshot.jsonl").write_text(
        json.dumps({"id": "g", "text": "snapshot words"}) + "\n"
    )
    return v


def ids(hits):
    return [h["id"] for h in hits]


def test_build_indexes_every_month_file_but_not_snapshots(vault):
    stats = memory.build(vault)

    # 3 chat messages with words, 1 Slack, 2 mail, 2 calendar, 1 chrome with a title,
    # and one summary row each for Spotify and Strava.
    assert stats["records_total"] == 3 + 1 + 2 + 2 + 1 + 2
    assert stats["files_indexed"] == 7
    assert memory.stats(vault)["by_source"] == {
        "whatsapp": 3,
        "email": 2,
        "calendar": 2,
        "slack": 1,
        "chrome": 1,
        "spotify": 1,
        "strava": 1,
    }
    assert memory.search("snapshot", vault=vault) == []


def test_the_index_is_private(vault):
    memory.build(vault)

    folder = vault / "memory"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE((folder / "index.sqlite").stat().st_mode) == 0o600
    assert not (folder / "index.sqlite.new").exists()


def test_a_row_carries_who_where_title_and_text(vault):
    memory.build(vault)

    [hit] = memory.search("lichen", vault=vault)
    assert hit["id"] == "whatsapp/messages/w1"
    assert (hit["source"], hit["stream"]) == ("whatsapp", "messages")
    assert hit["ts"] == "2025-03-03T10:01:00Z"
    assert "Mira Lund" in hit["who"] and "Book club" in hit["who"]
    assert hit["where_"] == "Book club"
    assert hit["from_me"] is False
    assert f"{memory.MARK_START}lichen{memory.MARK_END}" in hit["snippet"]
    assert hit["score"] < 0

    [mail] = memory.search("budget before friday", vault=vault)
    assert mail["title"] == "Grant budget"
    assert mail["who"] == "Priya Raman, me@example.org"

    [event] = memory.search("chapter", vault=vault)  # the description is its words
    assert event["title"] == "Thesis committee"
    assert event["who"] == "Dana Whitfield"
    assert event["where_"] == "Room 12"
    assert event["from_me"] is None

    [mine] = memory.search("pdf", vault=vault)
    assert mine["from_me"] is True


def test_chrome_is_title_and_host_only(vault):
    memory.build(vault)

    [hit] = memory.search("mushroom", vault=vault)
    assert (hit["title"], hit["where_"]) == ("Mushroom field guide", "example.com")
    assert memory.search("SECRETVALUE", vault=vault) == []
    assert memory.search("private", vault=vault) == []
    assert memory.search("example.com", vault=vault)  # the host is searchable


def test_spotify_and_strava_months_are_one_summary_row_each(vault):
    memory.build(vault)

    [run] = memory.search("running march", sources=["strava"], vault=vault)
    assert run["id"] == "strava/activities/2025-03"
    assert run["ts"] == "2025-03-01T00:00:00Z"
    assert "2 activities" in run["snippet"] or "Strava" in run["title"]
    assert memory.search("cycling", vault=vault)[0]["source"] == "strava"
    [music] = memory.search("ferns", vault=vault)
    assert music["id"] == "spotify/plays/2025-03"
    assert memory.search("Skipped Band", vault=vault) == []  # nothing was played


def test_text_is_capped_and_control_characters_never_reach_the_marks(vault):
    long = "alpha " * 3000
    write_month(
        vault,
        "notes/pages",
        "2025-04",
        [
            {
                "id": "n1",
                "ts": "2025-04-01T00:00:00Z",
                "title": "Big",
                "text": f"\x02needle\x03 {long}",
            }
        ],
    )
    memory.build(vault)

    db = sqlite3.connect(memory.index_path(vault))
    (text,) = db.execute("SELECT text FROM records WHERE id = 'notes/pages/n1'").fetchone()
    assert len(text) == memory.MAX_TEXT
    assert "\x02" not in text and "\x03" not in text
    [hit] = memory.search("needle", vault=vault)
    assert hit["snippet"].count(memory.MARK_START) == 1


def test_a_second_run_reads_nothing_and_a_changed_file_is_redone(vault):
    memory.build(vault)

    assert memory.build(vault) == {
        "files_indexed": 0,
        "files_unchanged": 7,
        "files_removed": 0,
        "records_indexed": 0,
        "records_total": 11,
    }

    path = vault / "raw/whatsapp/messages/2025-03.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["text"] = "Who wants to read the moss paper this month?"
    rows.append(chat(5, "Next month: ferns"))
    write_month(vault, "whatsapp/messages", "2025-03", rows)
    stat_ = path.stat()
    os.utime(path, ns=(stat_.st_atime_ns, stat_.st_mtime_ns + 5_000_000_000))

    stats = memory.build(vault)

    assert (stats["files_indexed"], stats["files_unchanged"]) == (1, 6)
    assert memory.search("lichen", vault=vault) == []  # the old words are gone
    assert ids(memory.search("moss paper", sources=["whatsapp"], vault=vault)) == [
        "whatsapp/messages/w1"
    ]
    assert ids(memory.search("ferns", sources=["whatsapp"], vault=vault)) == [
        "whatsapp/messages/w5"
    ]
    assert stats["records_total"] == 12


def test_a_month_file_that_disappears_leaves_the_index(vault):
    memory.build(vault)
    (vault / "raw/slack/acme/messages/2025-03.jsonl").unlink()

    stats = memory.build(vault)

    assert stats["files_removed"] == 1
    assert memory.search("centrifuge", vault=vault) == []
    assert "slack" not in memory.stats(vault)["by_source"]


def test_rebuild_starts_over_and_swaps_the_file_in(vault):
    memory.build(vault)
    before = memory.search("lichen", vault=vault)

    stats = memory.build(vault, rebuild=True)

    assert stats["files_indexed"] == 7  # everything was read again
    assert memory.search("lichen", vault=vault) == before
    assert not (vault / "memory/index.sqlite.new").exists()


def test_an_index_from_another_version_is_rebuilt(vault):
    memory.build(vault)
    db = sqlite3.connect(memory.index_path(vault))
    db.execute("UPDATE meta SET value = '0' WHERE key = 'schema'")
    db.commit()
    db.close()

    assert memory.build(vault)["files_indexed"] == 7


def test_a_damaged_line_is_skipped_not_fatal(vault):
    path = vault / "raw/whatsapp/messages/2025-03.jsonl"
    path.write_text(path.read_text() + "{not json\n[1, 2]\n")

    assert memory.build(vault)["records_total"] == 11


def test_a_second_builder_does_nothing(vault):
    (vault / "memory").mkdir(mode=0o700)

    with memory._locked(vault / "memory") as free:
        assert free
        assert memory.build(vault) == {"already_running": 1}

    assert memory.build(vault)["files_indexed"] == 7  # the lock is let go


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("lichen", '"lichen"'),
        ("lichen paper", '"lichen" "paper"'),
        ('"lichen paper" moss', '"lichen paper" "moss"'),
        ("lich*", '"lich"*'),
        ('"machine lear"*', '"machine lear"*'),
        ("a*", '"a"'),  # too short to be a prefix
        ("*", ""),
        ("", ""),
        ("   ", ""),
        ("!!! ---", ""),
        ('unbalanced "quote', '"unbalanced" "quote"'),
        ("AND OR NOT NEAR", '"AND" "OR" "NOT" "NEAR"'),
        ("who:alice", '"who:alice"'),
        ("(a OR b) -c", '"(a" "OR" "b)" "-c"'),
        ("café", '"café"'),
        ("a\x00b", '"a" "b"'),
    ],
)
def test_user_text_becomes_quoted_terms(text, expected):
    assert memory.fts_query(text) == expected


def test_match_any_ors_the_terms():
    assert memory.fts_query("moss lichen", match="any") == '"moss" OR "lichen"'


def test_the_number_and_length_of_terms_are_bounded():
    query = memory.fts_query(" ".join(f"w{i}" for i in range(100)) + " " + "x" * 500)
    assert query.count('"') == 2 * memory.MAX_TERMS
    assert max(len(t) for t in memory.fts_query("y" * 500).split('"')) == memory.MAX_TERM_CHARS


@pytest.mark.parametrize(
    "hostile",
    [
        '") OR (',
        "NEAR(a b, 2)",
        "who: OR",
        '"',
        '""',
        "* * *",
        "-",
        "a AND",
        "{who where_}: x",
        "^lichen",
        "x' OR 1=1 --",
        "lichen; DROP TABLE records",
        "\\",
        "\x00",
    ],
)
def test_no_input_breaks_the_query(vault, hostile):
    memory.build(vault)

    memory.search(hostile, vault=vault)
    memory.search("lichen", who=hostile, vault=vault)
    memory.search(
        hostile, who=hostile, sources=[hostile], since=hostile, until=hostile, vault=vault
    )
    assert memory.stats(vault)["records"] == 11  # and nothing was dropped


def test_words_are_anded_phrases_and_prefixes_work(vault):
    memory.build(vault)

    assert ids(memory.search("lichen pdf", vault=vault)) == []  # in different messages
    assert ids(memory.search("send pdf", vault=vault)) == ["whatsapp/messages/w2"]
    assert ids(memory.search('"read the lichen"', vault=vault)) == ["whatsapp/messages/w1"]
    assert ids(memory.search('"lichen read"', vault=vault)) == []
    assert ids(memory.search("symbio*", vault=vault)) == ["whatsapp/messages/w3"]
    assert ids(memory.search("symbio", vault=vault)) == []
    assert ids(memory.search("LICHEN", vault=vault)) == ["whatsapp/messages/w1"]


def test_accents_are_ignored_both_ways(vault):
    memory.build(vault)

    assert ids(memory.search("cafe", vault=vault)) == ["email/me-example-org/<m1@x>"]
    assert ids(memory.search("café", vault=vault)) == ["email/me-example-org/<m1@x>"]


def test_a_title_match_outranks_a_text_match(vault):
    write_month(
        vault,
        "notes/pages",
        "2025-04",
        [
            {"id": "t", "ts": "2025-04-01T00:00:00Z", "title": "Zebra plan", "text": "nothing"},
            {"id": "x", "ts": "2025-04-02T00:00:00Z", "title": "Misc", "text": "zebra zebra"},
        ],
    )
    memory.build(vault)

    hits = memory.search("zebra", vault=vault)
    assert ids(hits) == ["notes/pages/t", "notes/pages/x"]
    assert hits[0]["score"] < hits[1]["score"] < 0
    assert memory.MARK_START in hits[0]["snippet"]  # a title match shows the title


def test_filters_by_source_person_and_dates(vault):
    memory.build(vault)
    m1, m2 = "email/me-example-org/<m1@x>", "email/me-example-org/<m2@x>"

    assert ids(memory.search("the", sources=["slack"], vault=vault)) == ["slack/acme/messages/s1"]
    both = memory.search("the", sources=["slack", "email"], vault=vault)
    assert {h["source"] for h in both} == {"slack", "email"}

    # A person is a name anywhere among who: here a sender, and an address in to.
    assert set(ids(memory.search("budget", who="priya", vault=vault))) == {m1, m2}
    assert ids(memory.search("budget", who="priya raman", vault=vault)) == [m1]
    assert memory.search("budget", who="tobias", vault=vault) == []

    assert ids(memory.search("budget", since="2025-03-06", vault=vault)) == [m2]
    assert ids(memory.search("budget", until="2025-03-05", vault=vault)) == [m1]
    assert memory.search("budget", until="2025-03-04", vault=vault) == []
    assert ids(memory.search("budget", since="2025-03-05T12:00:01Z", vault=vault)) == [m2]
    window = memory.search("budget", since="2025-03-05", until="2025-03-06", vault=vault)
    assert set(ids(window)) == {m1, m2}

    assert memory.search("lichen", exclude_sources=["whatsapp"], vault=vault) == []
    assert len(memory.search("the", limit=1, vault=vault)) == 1


def test_a_person_alone_lists_their_rows_newest_first(vault):
    memory.build(vault)

    hits = memory.search("", who="Priya Raman", vault=vault)

    assert ids(hits) == ["email/me-example-org/<m1@x>"]
    names = memory.search("", who="mira", vault=vault)
    assert ids(names) == ["whatsapp/messages/w3", "whatsapp/messages/w1"]


def test_any_mode_finds_rows_matching_either_word(vault):
    memory.build(vault)

    hits = memory.search("centrifuge lichen", match="any", vault=vault)

    assert set(ids(hits)) == {"slack/acme/messages/s1", "whatsapp/messages/w1"}


def test_searching_without_an_index_finds_nothing(tmp_path):
    assert memory.search("anything", vault=tmp_path) == []
    assert memory.context("x", vault=tmp_path) == []
    assert memory.stats(tmp_path) == {"records": 0, "files": 0, "bytes": 0, "by_source": {}}


def test_context_is_the_conversation_around_a_message(vault):
    rows = [chat(n, f"line {n}", day=3) for n in range(1, 31)]
    write_month(vault, "whatsapp/messages", "2025-03", rows)
    write_month(vault, "whatsapp/messages", "2025-02", [chat(1, "older", month="2025-02")])
    write_month(
        vault,
        "whatsapp/messages",
        "2025-04",
        [
            chat(1, "newer", month="2025-04"),
            {**chat(2, "elsewhere", month="2025-04"), "chat_id": "other"},
        ],
    )
    memory.build(vault)

    around = memory.context("whatsapp/messages/w15", vault=vault)

    assert [r["text"] for r in around] == [f"line {n}" for n in range(5, 26)]
    assert [r["id"] for r in around if r["target"]] == ["whatsapp/messages/w15"]
    assert around[10]["target"] is True
    assert {"id", "source", "stream", "ts", "who", "where_", "title", "text", "from_me"} <= around[
        0
    ].keys()

    short = memory.context("whatsapp/messages/w2", before=3, after=1, vault=vault)
    assert [r["text"] for r in short] == ["older", "line 1", "line 2", "line 3"]

    # Past the end of a month it goes on into the next, but never into another chat.
    end = memory.context("whatsapp/messages/w30", before=0, after=5, vault=vault)
    assert [r["text"] for r in end] == ["line 30", "newer"]


def test_context_without_a_conversation_is_the_same_source_and_day(vault):
    memory.build(vault)

    around = memory.context("calendar/work/e1", vault=vault)

    assert [r["id"] for r in around] == ["calendar/work/e1", "calendar/work/e2"]
    assert around[0]["target"] and not around[1]["target"]


def test_context_follows_a_mail_thread_and_ignores_the_subject_prefix(vault):
    memory.build(vault)

    around = memory.context("email/me-example-org/<m2@x>", vault=vault)

    assert [r["id"] for r in around] == [
        "email/me-example-org/<m1@x>",
        "email/me-example-org/<m2@x>",
    ]
    assert [r["from_me"] for r in around] == [False, True]


def test_context_of_an_unknown_id_is_empty(vault):
    memory.build(vault)

    assert memory.context("whatsapp/messages/nope", vault=vault) == []
    assert memory.context("'; DROP TABLE records; --", vault=vault) == []


def test_a_summary_row_has_a_context_of_itself(vault):
    memory.build(vault)

    around = memory.context("strava/activities/2025-03", vault=vault)

    assert [r["id"] for r in around] == ["strava/activities/2025-03"]


def test_the_index_command_builds_and_reports(vault, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))

    cli.main(["index"])
    first = capsys.readouterr().out
    cli.main(["index"])
    second = capsys.readouterr().out
    cli.main(["index", "--rebuild"])
    rebuilt = capsys.readouterr().out

    assert first.startswith("index: 7 files indexed, 0 files unchanged")
    assert "11 records total" in first
    assert second.startswith("index: 0 files indexed, 7 files unchanged")
    assert rebuilt.startswith("index: 7 files indexed")


def test_records_are_the_raw_records_behind_index_ids_whole(vault):
    memory.build(vault)
    ids = ["email/me-example-org/<m1@x>", "slack/acme/messages/s1", "whatsapp/messages/nope"]

    found = memory.records(ids, vault=vault)

    assert sorted(found) == ids[:2]
    assert found["email/me-example-org/<m1@x>"]["to"] == [
        "me@example.org"
    ]  # every field, as written
    assert found["slack/acme/messages/s1"]["user_name"] == "Tobias Okafor"
    assert memory.records([], vault=vault) == {}
