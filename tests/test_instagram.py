"""Instagram ingester against a synthetic Meta export. No real data lives in this repo."""

import argparse
import json
from datetime import UTC, datetime

import pytest

from proxenos.ingest import instagram


def seconds(*args):
    return int(datetime(*args, tzinfo=UTC).timestamp())


JAN_31 = seconds(2025, 1, 31, 23, 59, 59)
FEB_1 = seconds(2025, 2, 1, 9)
FEB_2 = seconds(2025, 2, 2, 9)

PROFILE = "personal_information.json"
PERSONAL = {
    "profile_user": [
        {
            "string_map_data": {
                "Email": {"href": "", "value": "x@example.com", "timestamp": 0},
                "Username": {"href": "", "value": "me_example", "timestamp": 0},
                "Name": {"href": "", "value": "Zoë Example", "timestamp": 0},
            }
        }
    ]
}
DIRECT = {
    "participants": [{"name": "Sam Sample"}, {"name": "Zoë Example"}],
    "title": "Sam Sample",
    "thread_path": "inbox/samsample_1234567890",
    "messages": [
        {"sender_name": "Sam Sample", "timestamp_ms": JAN_31 * 1000, "content": "Café at noon? ☕"},
        {"sender_name": "Zoë Example", "timestamp_ms": FEB_1 * 1000, "content": "Yes!"},
        {
            "sender_name": "Zoë Example",
            "timestamp_ms": FEB_1 * 1000 + 5,
            "content": "Zoë sent an attachment.",
            "share": {"link": "https://example.com/p/1", "share_text": "a caption"},
        },
        {
            "sender_name": "Sam Sample",
            "timestamp_ms": FEB_1 * 1000 + 9,
            "photos": [{"uri": "messages/photos/1.jpg", "creation_timestamp": FEB_1}],
        },
    ],
}
OLDER = {
    "participants": DIRECT["participants"],
    "title": "Sam Sample",
    "messages": [{"sender_name": "Sam Sample", "timestamp_ms": JAN_31 * 1000 - 1, "content": "hi"}],
}
GROUP = {
    "participants": [{"name": "Kai Placeholder"}, {"name": "Sam Sample"}, {"name": "Zoë Example"}],
    "title": "Study group",
    "messages": [
        {"sender_name": "Zoë Example", "timestamp_ms": FEB_2 * 1000, "content": "Notes are up"},
        {"sender_name": "Kai Placeholder", "timestamp_ms": FEB_2 * 1000 + 1, "content": "Merci 🙏"},
    ],
}
POSTS = [
    {"media": [{"uri": "media/posts/1.jpg", "creation_timestamp": JAN_31, "title": "Run ☀"}]},
    {
        "media": [
            {"uri": "media/posts/2.jpg", "creation_timestamp": FEB_1, "title": ""},
            {"uri": "media/posts/3.mp4", "creation_timestamp": FEB_1, "title": ""},
        ],
        "title": "Weekend, part 2",
        "creation_timestamp": FEB_1,
    },
]
COMMENTS = [
    {
        "string_map_data": {
            "Comment": {"value": "Lovely 😍"},
            "Media Owner": {"value": "friend_example"},
            "Time": {"timestamp": FEB_1},
        }
    }
]
REEL_COMMENTS = {
    "comments_reels_comments": [
        {"string_map_data": {"Comment": {"value": "Ha"}, "Time": {"timestamp": FEB_2}}}
    ]
}
LIKES = {
    "likes_media_likes": [
        {
            "title": "friend_example",
            "string_list_data": [
                {"href": "https://example.com/p/abc/", "value": "👍", "timestamp": FEB_2}
            ],
        }
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


def make_export(root, activity="your_instagram_activity", personal=True):
    base = root / activity
    write(base / "messages/inbox/samsample_1234567890/message_1.json", DIRECT)
    write(base / "messages/inbox/samsample_1234567890/message_2.json", OLDER)
    write(base / "messages/inbox/studygroup_9876543210/message_1.json", GROUP)
    write(base / "content/posts_1.json", POSTS)
    write(base / "comments/post_comments_1.json", COMMENTS)
    write(base / "comments/reels_comments.json", REEL_COMMENTS)
    write(base / "likes/liked_posts.json", LIKES)
    if personal:
        write(root / "personal_information" / "personal_information" / PROFILE, PERSONAL)
    return root


def by_text(records):
    return {r["text"]: r for r in records if r}


def stream(vault, name):
    out = vault / "raw" / "instagram" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def test_mojibake_is_undone_and_text_that_was_fine_is_left_alone():
    assert instagram._fix("CafÃ© â\x98\x95") == "Café ☕"
    assert instagram._fix({"a": ["ZoÃ«"]}) == {"a": ["Zoë"]}
    assert instagram._fix("Café ☕") == "Café ☕"  # not garbled: encoding or decoding fails
    assert instagram._fix("plain") == "plain"


def test_messages_are_mine_by_the_profile_name_across_split_files(tmp_path):
    export = make_export(tmp_path / "e")
    assert instagram.read_owner(export) == ["Zoë Example", "me_example"]
    msgs = by_text(instagram.read_messages(export))

    theirs = msgs["Café at noon? ☕"]
    assert theirs["id"] == f"1234567890/{JAN_31 * 1000}"
    assert theirs["ts"] == "2025-01-31T23:59:59Z"
    assert (theirs["chat_id"], theirs["chat_name"], theirs["chat_type"]) == (
        "1234567890",
        "Sam Sample",
        "direct",
    )
    assert (theirs["from_me"], theirs["author"], theirs["kind"]) == (False, "Sam Sample", "text")

    assert msgs["Yes!"]["from_me"] is True
    share = msgs["Zoë sent an attachment."]
    assert (share["kind"], share["link"]) == ("share", "https://example.com/p/1")
    assert msgs["hi"]["ts"] == "2025-01-31T23:59:58Z"  # from message_2.json
    photo = msgs[None]
    assert (photo["kind"], photo["from_me"]) == ("photo", False)

    group = msgs["Merci 🙏"]
    assert (group["chat_id"], group["chat_type"], group["from_me"]) == (
        "9876543210",
        "group",
        False,
    )
    assert msgs["Notes are up"]["from_me"] is True


def test_without_personal_information_me_is_the_name_in_the_most_threads(tmp_path):
    export = make_export(tmp_path / "e", personal=False)
    third = {**GROUP, "participants": GROUP["participants"][::2], "messages": []}
    write(export / "your_instagram_activity/messages/inbox/kai_5550000/message_1.json", third)
    assert instagram.read_owner(export) == []

    mine = {r["text"]: r["from_me"] for r in instagram.read_messages(export)}
    assert (mine["Yes!"], mine["Notes are up"]) == (True, True)
    assert (mine["Café at noon? ☕"], mine["Merci 🙏"]) == (False, False)

    named = {r["text"]: r["from_me"] for r in instagram.read_messages(export, ["sam sample"])}
    assert (named["Café at noon? ☕"], named["Yes!"]) == (True, False)


def test_posts_take_the_caption_and_time_from_the_post_or_its_only_media(tmp_path):
    posts = sorted(instagram.read_posts(make_export(tmp_path / "e")), key=lambda r: r["ts"])
    assert [(p["id"], p["ts"], p["text"], p["media"]) for p in posts] == [
        (str(JAN_31), "2025-01-31T23:59:59Z", "Run ☀", ["photo"]),
        (str(FEB_1), "2025-02-01T09:00:00Z", "Weekend, part 2", ["photo", "video"]),
    ]
    assert {(p["from_me"], p["author"]) for p in posts} == {(True, "Zoë Example")}


def test_comments_and_likes_are_read_in_both_layouts(tmp_path):
    export = make_export(tmp_path / "e")
    comments = by_text(instagram.read_comments(export))
    assert comments["Lovely 😍"]["media_owner"] == "friend_example"
    assert comments["Lovely 😍"]["ts"] == "2025-02-01T09:00:00Z"
    assert (comments["Ha"]["from_me"], comments["Ha"]["media_owner"]) == (True, None)

    (like,) = instagram.read_likes(export)
    assert like["id"] == like["url"] == "https://example.com/p/abc/"
    assert (like["ts"], like["from_me"], like["author"]) == (
        "2025-02-02T09:00:00Z",
        False,
        "friend_example",
    )

    # Older exports: everything at the top, and comments as string_list_data under the owner.
    old = make_export(tmp_path / "old", activity=".")
    old_comment = {
        "title": "friend_example",
        "string_list_data": [{"value": "Nice", "timestamp": 1}],
    }
    write(old / "comments/post_comments.json", {"comments_media_comments": [old_comment]})
    comments = by_text(instagram.read_comments(old))
    assert comments["Nice"]["media_owner"] == "friend_example"
    assert comments["Nice"]["ts"] == "1970-01-01T00:00:01Z"
    assert len(by_text(instagram.read_messages(old))) == 7


def test_missing_files_are_empty_and_malformed_entries_are_skipped(tmp_path):
    base = tmp_path / "e" / "your_instagram_activity"
    one = {**DIRECT, "messages": DIRECT["messages"][:1]}
    write(base / "messages/inbox/a_1/message_1.json", one)
    (base / "messages/inbox/a_1/message_2.json").write_text('{"messages": [')  # cut off
    untimed = {"sender_name": "Sam Sample", "content": "when?"}
    write(base / "messages/inbox/b_2/message_1.json", {"participants": [], "messages": [untimed]})
    write(base / "content/posts_1.json", POSTS + [{"media": []}, "x"])
    write(
        base / "comments/post_comments_1.json", [{"string_map_data": {"Comment": {"value": "x"}}}]
    )

    stats = instagram.ingest(tmp_path / "vault", tmp_path / "e")
    assert stats == {"read": 3, "added": 3, "updated": 0, "months_written": 3, "skipped": 5}
    (msg,) = stream(tmp_path / "vault", "messages")
    assert msg["from_me"] is False  # no profile, and one thread can't say who I am


def test_reingest_through_run_is_idempotent_and_keys_that_collide_get_a_suffix(tmp_path):
    export = make_export(tmp_path / "e")
    # Same thread, same millisecond: an exact copy collapses, a different message gets #2.
    same_ms = {"sender_name": "Sam Sample", "timestamp_ms": FEB_1 * 1000, "content": "also yes"}
    copy = DIRECT["messages"][1]
    extra = {**OLDER, "messages": OLDER["messages"] + [same_ms, copy]}
    write(
        export / "your_instagram_activity/messages/inbox/samsample_1234567890/message_2.json", extra
    )

    vault = tmp_path / "vault"
    args = argparse.Namespace(export=export, me=[])
    first = instagram.run(vault, args)
    assert first == {"read": 13, "added": 13, "updated": 0, "months_written": 6, "skipped": 0}
    ids = {r["text"]: r["id"] for r in stream(vault, "messages")}
    assert {ids["Yes!"], ids["also yes"]} == {
        f"1234567890/{FEB_1 * 1000}",
        f"1234567890/{FEB_1 * 1000}#2",
    }

    again = instagram.run(vault, args)
    assert again == {"read": 13, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}


def test_a_folder_without_an_instagram_export_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="no Instagram export folders"):
        instagram.ingest(tmp_path / "vault", tmp_path)
