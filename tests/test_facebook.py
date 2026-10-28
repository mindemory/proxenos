"""Facebook ingester against a synthetic Meta export. No real data lives in this repo."""

import json
from datetime import UTC, datetime

import pytest

from twin.ingest import facebook


def seconds(*args):
    return int(datetime(*args, tzinfo=UTC).timestamp())


MAR_1 = seconds(2024, 3, 1, 12)
MAR_2 = seconds(2024, 3, 2, 12)
APR_1 = seconds(2024, 4, 1, 8)

PROFILE = {"profile_v2": {"name": {"full_name": "Zoë Example", "first_name": "Zoë"}}}
DIRECT = {
    "participants": [{"name": "Sam Sample"}, {"name": "Zoë Example"}],
    "title": "Sam Sample",
    "messages": [
        {"sender_name": "Zoë Example", "timestamp_ms": MAR_1 * 1000, "content": "Café?"},
        {"sender_name": "Sam Sample", "timestamp_ms": MAR_1 * 1000 + 7, "content": "Sure ☕"},
    ],
}
OLD = {
    "participants": DIRECT["participants"],
    "title": "Sam Sample",
    "messages": [
        {
            "sender_name": "Sam Sample",
            "timestamp_ms": MAR_2 * 1000,
            "photos": [{"uri": "x.jpg", "creation_timestamp": MAR_2}],
        }
    ],
}
ARCHIVED = {
    "participants": [{"name": "Kai Placeholder"}, {"name": "Sam Sample"}, {"name": "Zoë Example"}],
    "title": "Trip",
    "messages": [{"sender_name": "Kai Placeholder", "timestamp_ms": APR_1 * 1000, "content": "Go"}],
}
FILTERED = {
    "participants": [{"name": "Spam Sender"}],
    "messages": [{"sender_name": "Spam Sender", "timestamp_ms": APR_1 * 1000, "content": "Buy"}],
}
POSTS = [
    {
        "timestamp": MAR_1,
        "data": [{"post": "First day at the lab ✨"}, {"update_timestamp": MAR_1}],
        "title": "Zoë Example updated her status.",
        "attachments": [
            {"data": [{"external_context": {"url": "https://example.com/a"}}]},
            {"data": [{"place": {"name": "Somewhere Café"}}]},
        ],
    },
    {
        "timestamp": MAR_2,
        "title": "Zoë Example added a new photo.",
        "attachments": [
            {"data": [{"media": {"uri": "posts/1.jpg"}}, {"media": {"uri": "2.mp4"}}]},
        ],
    },
    {
        "timestamp": MAR_2,
        "title": "Zoë Example added a new photo.",
        "attachments": [{"data": [{"media": {"uri": "3.jpg", "description": "Sunset 🌅"}}]}],
    },
    {
        "timestamp": APR_1,
        "attachments": [{"data": [{"life_event": {"title": "Started a new job"}}]}],
    },
    {"timestamp": APR_1, "data": [{"update_timestamp": APR_1}]},
    {"title": "no time"},
]
COMMENTS = {
    "comments_v2": [
        {
            "timestamp": MAR_2,
            "data": [{"comment": {"timestamp": MAR_2, "comment": "Congrats! 🎉", "author": "Zoë"}}],
            "title": "Zoë Example commented on Sam Sample's post.",
        },
        {
            "timestamp": APR_1,
            "title": "Zoë Example replied to a comment.",
            "attachments": [{"data": [{"media": {"uri": "c.jpg"}}]}],
        },
        {"timestamp": APR_1, "title": "Zoë Example commented on a post."},
    ]
}


def garble(value):
    """What Meta writes: each string's UTF-8 bytes read as latin-1, then JSON-escaped."""
    if isinstance(value, str):
        return value.encode("utf-8").decode("latin-1")
    if isinstance(value, list):
        return [garble(item) for item in value]
    if isinstance(value, dict):
        return {key: garble(item) for key, item in value.items()}
    return value


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(garble(data)))


def make_export(root, profile=True):
    activity = root / "your_facebook_activity"
    write(activity / "messages/inbox/samsample_1234567890/message_1.json", DIRECT)
    write(activity / "messages/e2ee_cutover/samsample_1234567890/message_1.json", OLD)
    write(activity / "messages/archived_threads/trip_5550001/message_1.json", ARCHIVED)
    write(activity / "messages/filtered_threads/spam_999/message_1.json", FILTERED)
    (activity / "messages/inbox/broken_42").mkdir(parents=True)
    (activity / "messages/inbox/broken_42/message_1.json").write_text("{not json")
    write(activity / "posts/your_posts__check_ins__photos_and_videos_1.json", POSTS)
    write(activity / "comments_and_reactions/comments.json", COMMENTS)
    if profile:
        write(root / "personal_information/profile_information/profile_information.json", PROFILE)
    return root


def by_text(records):
    return {r["text"]: r for r in records if r}


def stream(vault, name):
    out = vault / "raw" / "facebook" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def test_messages_from_inbox_cutover_and_archive_are_mine_by_the_profile_name(tmp_path):
    export = make_export(tmp_path / "e")
    assert facebook.read_owner(export) == ["Zoë Example"]
    records = facebook.read_messages(export)
    assert records.count(None) == 1  # the file that isn't JSON
    msgs = by_text(records)
    assert set(msgs) == {"Café?", "Sure ☕", None, "Go"}  # filtered_threads isn't read

    mine = msgs["Café?"]
    assert (mine["id"], mine["ts"], mine["from_me"], mine["chat_type"]) == (
        f"1234567890/{MAR_1 * 1000}",
        "2024-03-01T12:00:00Z",
        True,
        "direct",
    )
    assert (msgs["Sure ☕"]["from_me"], msgs["Sure ☕"]["author"]) == (False, "Sam Sample")
    photo = msgs[None]  # from e2ee_cutover, in the same thread
    assert (photo["chat_id"], photo["kind"]) == ("1234567890", "photo")
    assert (msgs["Go"]["chat_name"], msgs["Go"]["chat_type"]) == ("Trip", "group")


def test_without_a_profile_me_is_the_participant_in_the_most_threads(tmp_path):
    export = make_export(tmp_path / "e", profile=False)
    third = {"participants": [{"name": "Kai Placeholder"}, {"name": "Zoë Example"}], "messages": []}
    write(export / "your_facebook_activity/messages/inbox/kai_5550002/message_1.json", third)
    mine = {r["text"]: r["from_me"] for r in facebook.read_messages(export) if r}
    assert (mine["Café?"], mine["Sure ☕"], mine["Go"]) == (True, False, False)
    named = {r["text"]: r["from_me"] for r in facebook.read_messages(export, ["sam sample"]) if r}
    assert (named["Café?"], named["Sure ☕"]) == (False, True)


def test_posts_and_comments_keep_text_attachments_and_title(tmp_path):
    export = make_export(tmp_path / "e")
    records = facebook.read_posts(export)
    assert records.count(None) == 2  # no content, and no time
    posts = sorted((r for r in records if r), key=lambda r: (r["ts"], r["id"]))
    first, photos, captioned, event = posts
    assert (captioned["id"], captioned["text"]) == (f"{MAR_2}#2", "Sunset 🌅")
    assert (first["id"], first["text"], first["url"], first["place"]) == (
        str(MAR_1),
        "First day at the lab ✨",
        "https://example.com/a",
        "Somewhere Café",
    )
    assert (first["author"], first["from_me"]) == ("Zoë Example", True)
    assert (photos["text"], photos["media"], photos["title"]) == (
        None,
        ["photo", "video"],
        "Zoë Example added a new photo.",
    )
    assert (event["text"], event["title"]) == ("Started a new job", None)

    records = facebook.read_comments(export)
    assert records.count(None) == 1  # neither text nor attachment
    comments = sorted((r for r in records if r), key=lambda r: r["ts"])
    assert [(c["text"], c["author"], c["media"]) for c in comments] == [
        ("Congrats! 🎉", "Zoë", None),
        (None, "Zoë Example", ["photo"]),
    ]


def test_ingest_writes_three_streams_and_reruns_are_no_ops(tmp_path):
    vault = tmp_path / "vault"
    export = make_export(tmp_path / "e")
    stats = facebook.ingest(vault, export)
    assert (stats["added"], stats["skipped"]) == (10, 4)
    assert len(stream(vault, "messages")) == 4
    again = facebook.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)

    with pytest.raises(FileNotFoundError):
        facebook.ingest(vault, tmp_path / "nothing")
