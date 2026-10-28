"""LinkedIn ingester against a synthetic data export. No real data lives in this repo."""

import argparse
import csv
import json

import pytest

from twin.ingest import linkedin

NOTES = [
    ["Notes:"],
    ["When exporting your connection data, some email addresses may be missing.\nSee help."],
    [],
]

PROFILE = [
    ["First Name", "Last Name", "Maiden Name", "Address", "Birth Date", "Headline", "Summary"]
    + ["Industry", "Zip Code", "Geo Location", "Twitter Handles", "Websites"],
    ["Alex", "Example", "", "1 Test Street", "Jan 1, 1990", "Researcher", "Studies memory.\nRuns."]
    + ["Research", "00000", "Sample City", "", ""],
]
POSITIONS = [
    ["Company Name", "Title", "Description", "Location", "Started On", "Finished On"],
    ["Example Lab", "Postdoc", "Memory models", "Sample City", "Sep 2024", ""],
    ["Sample University", "Graduate Student", "", "", "Aug 2019", "Aug 2024"],
    ["Undated Co", "Intern", "", "", "", ""],
]
EDUCATION = [
    ["School Name", "Start Date", "End Date", "Notes", "Degree Name", "Activities"],
    ["Sample University", "2019", "2024", "Thesis on memory", "PhD", "Running club"],
    ["Example College", "", "2019", "", "BS", ""],
]
SHARES = [
    ["Date", "ShareLink", "ShareCommentary", "SharedUrl", "MediaUrl", "Visibility"],
    [
        "2025-02-01 10:00:00",
        "https://example.com/feed/update/urn%3Ali%3Ashare%3A7000000000000000001",
        'New paper out, "finally".\nLink below.',
        "https://example.com/paper",
        "",
        "MEMBER_NETWORK",
    ],
    ["2025-02-02 11:00:00", "", "A post without a link", "", "", "PUBLIC"],
]
COMMENTS = [
    ["Date", "Link", "Message"],
    ["2025-01-31 23:59:59", "https://example.com/feed/urn:li:activity:7002", "Congrats!"],
]
MESSAGES = [
    ["CONVERSATION ID", "CONVERSATION TITLE", "FROM", "SENDER PROFILE URL", "TO"]
    + ["RECIPIENT PROFILE URLS", "DATE", "SUBJECT", "CONTENT", "FOLDER"],
    ["2-abc==", "", "Sam Sample", "", "Alex Example", ""]
    + ["2025-02-01 12:00:00 UTC", "Hello", "Quick question?", "INBOX"],
    ["2-abc==", "", "alex  example", "", "Sam Sample", ""]
    + ["2025-02-01 12:30:00 UTC", "", "Sure, ask away", "INBOX"],
]
CONNECTIONS = NOTES + [
    ["First Name", "Last Name", "URL", "Email Address", "Company", "Position", "Connected On"],
    ["Sam", "Sample", "https://example.com/in/sam", "sam@example.com", "Example Lab", "Engineer"]
    + ["12 Apr 2023"],
    ["Kai", "Placeholder", "", "", "", "Student", "01 Jan 2024"],
    ["", "", "", "", "", "", ""],
]

FILES = {
    "Profile.csv": PROFILE,
    "Positions.csv": POSITIONS,
    "Education.csv": EDUCATION,
    "Shares.csv": SHARES,
    "Comments.csv": COMMENTS,
    "messages.csv": MESSAGES,
    "Connections.csv": CONNECTIONS,
}


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def make_export(root, files=FILES):
    for name, rows in files.items():
        write_csv(root / name, rows)
    return root


def by_id(records):
    return {r["id"]: r for r in records if r}


def stream(vault, name):
    out = vault / "raw" / "linkedin" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def test_profile_has_a_record_per_position_and_degree_and_a_snapshot(tmp_path):
    records = linkedin.read_profile(make_export(tmp_path / "2025-03-01"))
    assert records.count(None) == 1  # the position with no dates at all
    kept = sorted((r for r in records if r), key=lambda r: (r["ts"], r.get("organization") or ""))

    assert [(r["kind"], r.get("organization"), r["ts"]) for r in kept] == [
        ("education", "Example College", "2019-01-01T00:00:00Z"),  # no start, so its end
        ("education", "Sample University", "2019-01-01T00:00:00Z"),
        ("position", "Sample University", "2019-08-01T00:00:00Z"),
        ("position", "Example Lab", "2024-09-01T00:00:00Z"),
        ("profile", None, "2025-03-01T00:00:00Z"),
    ]

    postdoc = next(r for r in kept if r.get("title") == "Postdoc")
    assert (postdoc["started"], postdoc["finished"], postdoc["location"]) == (
        "2024-09",
        None,
        "Sample City",
    )
    assert (postdoc["from_me"], postdoc["author"]) == (True, "Alex Example")
    phd = next(r for r in kept if r.get("title") == "PhD")
    assert (phd["started"], phd["finished"], phd["description"], phd["activities"]) == (
        "2019",
        "2024",
        "Thesis on memory",
        "Running club",
    )

    snapshot = next(r for r in kept if r["kind"] == "profile")
    assert snapshot["id"] == "profile/2025-03-01"
    assert (snapshot["headline"], snapshot["location"]) == ("Researcher", "Sample City")
    assert snapshot["summary"] == "Studies memory.\nRuns."
    assert "1 Test Street" not in json.dumps(kept)  # address and birth date stay behind


def test_the_snapshot_takes_linkedins_own_date_format_in_the_folder_name(tmp_path):
    export = make_export(tmp_path / "Complete_LinkedInDataExport_03-01-2025")
    snapshot = next(r for r in linkedin.read_profile(export) if r and r["kind"] == "profile")
    assert snapshot["ts"] == "2025-03-01T00:00:00Z"


def test_shares_and_comments_are_mine_with_urn_ids_where_the_link_has_one(tmp_path):
    export = make_export(tmp_path / "e")
    posts = list(by_id(linkedin.read_posts(export)).values())
    assert posts[0]["id"] == "urn:li:share:7000000000000000001"
    assert posts[0]["ts"] == "2025-02-01T10:00:00Z"
    assert posts[0]["text"] == 'New paper out, "finally".\nLink below.'
    assert (posts[0]["shared_url"], posts[0]["visibility"]) == (
        "https://example.com/paper",
        "MEMBER_NETWORK",
    )
    assert posts[1]["id"].startswith("share/") and posts[1]["url"] is None
    assert {(p["from_me"], p["author"]) for p in posts} == {(True, "Alex Example")}

    (comment,) = by_id(linkedin.read_comments(export)).values()
    assert (comment["ts"], comment["text"], comment["from_me"]) == (
        "2025-01-31T23:59:59Z",
        "Congrats!",
        True,
    )


def test_messages_mark_from_me_by_the_profile_name_unless_me_is_given(tmp_path):
    export = make_export(tmp_path / "e")
    msgs = sorted(by_id(linkedin.read_messages(export)).values(), key=lambda r: r["ts"])
    assert [(m["author"], m["from_me"]) for m in msgs] == [
        ("Sam Sample", False),
        ("alex  example", True),  # matched ignoring case and spacing
    ]
    assert msgs[0]["ts"] == "2025-02-01T12:00:00Z"
    assert (msgs[0]["conversation_id"], msgs[0]["subject"], msgs[0]["folder"]) == (
        "2-abc==",
        "Hello",
        "INBOX",
    )
    assert msgs[0]["id"].startswith("2-abc==/")

    mine = {m["author"]: m["from_me"] for m in linkedin.read_messages(export, ["Sam Sample"])}
    assert mine == {"Sam Sample": True, "alex  example": False}


def test_connections_skip_the_notes_preamble_and_never_keep_email(tmp_path):
    export = make_export(tmp_path / "e")
    conns = sorted(by_id(linkedin.read_connections(export)).values(), key=lambda r: r["ts"])
    assert [(c["name"], c["company"], c["position"], c["ts"]) for c in conns] == [
        ("Sam Sample", "Example Lab", "Engineer", "2023-04-12T00:00:00Z"),
        ("Kai Placeholder", None, "Student", "2024-01-01T00:00:00Z"),
    ]
    assert {c["from_me"] for c in conns} == {False}
    assert "sam@example.com" not in json.dumps(conns)
    assert "example.com/in/sam" not in json.dumps(conns)


def test_file_and_column_names_are_matched_loosely(tmp_path):
    files = {
        "connections.csv": [
            ["first_name", "LAST NAME", "Company", "Title", "Connected on"],
            ["Sam", "Sample", "Example Lab", "Engineer", "4/12/23"],
        ],
        "POSITIONS.CSV": [
            ["Company", "Job Title", "Start Date", "End Date"],
            ["Example Lab", "Postdoc", "September 2024", ""],
        ],
    }
    export = make_export(tmp_path / "e", files)

    (conn,) = by_id(linkedin.read_connections(export)).values()
    assert (conn["name"], conn["position"], conn["ts"]) == (
        "Sam Sample",
        "Engineer",
        "2023-04-12T00:00:00Z",
    )
    (job,) = by_id(linkedin.read_profile(export)).values()
    assert (job["organization"], job["title"], job["started"]) == (
        "Example Lab",
        "Postdoc",
        "2024-09",
    )
    assert job["author"] is None  # no Profile.csv


def test_missing_files_are_empty_and_rows_with_bad_dates_are_skipped(tmp_path):
    bad_share = ["yesterday", "", "Undatable", "", "", ""]
    bad_message = ["2-x", "", "Sam Sample", "", "", "", "", "", "Hi", ""]
    files = {
        "Shares.csv": SHARES + [bad_share],
        "messages.csv": MESSAGES + [bad_message],
        "Connections.csv": CONNECTIONS + [["Pat", "Undated", "", "", "Co", "Role", ""]],
    }
    stats = linkedin.ingest(tmp_path / "vault", make_export(tmp_path / "e", files))
    assert stats == {"read": 6, "added": 6, "updated": 0, "months_written": 4, "skipped": 3}
    assert {m["from_me"] for m in stream(tmp_path / "vault", "messages")} == {False}  # no name


def test_reingest_through_run_is_idempotent_and_merges_changes(tmp_path):
    vault = tmp_path / "vault"
    args = argparse.Namespace(export=make_export(tmp_path / "2025-03-01"), me=[])

    first = linkedin.run(vault, args)
    assert (first["added"], first["updated"], first["skipped"]) == (12, 0, 1)
    assert sorted(p.name for p in (vault / "raw" / "linkedin").iterdir()) == [
        "comments",
        "connections",
        "messages",
        "posts",
        "profile",
    ]
    again = linkedin.run(vault, args)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)

    # A later export: Sam changed jobs, and the old export's other rows are kept.
    moved = CONNECTIONS[:4] + [CONNECTIONS[4][:4] + ["Sample Corp", "Lead", "12 Apr 2023"]]
    later = linkedin.ingest(vault, make_export(tmp_path / "2025-06-01", {"Connections.csv": moved}))
    assert (later["added"], later["updated"]) == (0, 1)
    conns = {c["name"]: c for c in stream(vault, "connections")}
    assert (conns["Sam Sample"]["company"], len(conns)) == ("Sample Corp", 2)


def test_a_folder_without_export_csvs_is_refused(tmp_path):
    (tmp_path / "e").mkdir()
    with pytest.raises(FileNotFoundError, match="no LinkedIn export CSVs"):
        linkedin.ingest(tmp_path / "vault", tmp_path / "e")
