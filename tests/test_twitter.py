"""X/Twitter ingester against a synthetic account archive. No real data lives in this repo."""

import argparse
import json

import pytest

from proxenos.ingest import twitter

ACCOUNT = [{"account": {"accountId": "1000", "username": "me_example", "email": "x@example.com"}}]

TWEET = {
    "id_str": "1100",
    "created_at": "Fri Jan 31 23:59:59 +0000 2025",
    "full_text": "Notes &amp; links: https://t.co/aaa",
    "entities": {"urls": [{"url": "https://t.co/aaa", "expanded_url": "https://example.com/n"}]},
    "favorite_count": "3",
    "retweet_count": "1",
    "lang": "en",
}
REPLY = {
    "id_str": "1101",
    "created_at": "Sat Feb 01 10:00:00 +0000 2025",
    "full_text": "@friend_example agreed",
    "in_reply_to_status_id_str": "900",
    "in_reply_to_screen_name": "friend_example",
    "favorite_count": "0",
    "retweet_count": "0",
    "lang": "en",
}
RETWEET = {
    "id_str": "1102",
    "created_at": "Sat Feb 01 11:00:00 +0000 2025",
    "full_text": "RT @friend_example: a thought worth passing on",
    "favorite_count": "0",
    "retweet_count": "7",
    "lang": "en",
}
PHOTO = {
    "id_str": "1103",
    "created_at": "Sat Feb 01 12:00:00 +0000 2025",
    "full_text": "Two views https://t.co/ppp",
    "entities": {
        "media": [{"url": "https://t.co/ppp", "expanded_url": "https://example.com/p/1103"}]
    },
    "extended_entities": {"media": [{"type": "photo"}, {"type": "video"}]},
    "favorite_count": "2",
    "retweet_count": "0",
}

DMS = [
    {
        "dmConversation": {
            "conversationId": "1000-2000",
            "messages": [
                {
                    "messageCreate": {
                        "id": "5001",
                        "senderId": "2000",
                        "recipientId": "1000",
                        "text": "see https://t.co/ddd",
                        "urls": [{"url": "https://t.co/ddd", "expanded": "https://example.com/d"}],
                        "mediaUrls": [],
                        "createdAt": "2025-02-01T12:00:00.000Z",
                    }
                },
                {
                    "messageCreate": {
                        "id": "5002",
                        "senderId": "1000",
                        "recipientId": "2000",
                        "text": "thanks",
                        "mediaUrls": ["https://example.com/m/1.jpg"],
                        "createdAt": "2025-02-01T12:05:00.000Z",
                    }
                },
            ],
        }
    }
]
GROUP_DMS = [
    {
        "dmConversation": {
            "conversationId": "g42",
            "messages": [
                {"joinConversation": {"initiatingUserId": "2000", "createdAt": "2025-01-01"}},
                {
                    "messageCreate": {
                        "id": "6001",
                        "senderId": "1000",
                        "text": "hi all",
                        "createdAt": "2025-02-02T08:00:00.000Z",
                    }
                },
            ],
        }
    }
]

LIKES = [
    {"like": {"tweetId": "3001", "fullText": "Q &amp; A", "expandedUrl": "https://example.com/1"}},
    {"like": {"tweetId": "3002", "expandedUrl": "https://example.com/2"}},  # protected or deleted
]


def write_js(data, filename, entries):
    data.mkdir(parents=True, exist_ok=True)
    name = filename.split("-part")[0].removesuffix(".js").replace("-", "_")
    (data / filename).write_text(f"window.YTD.{name}.part0 = {json.dumps(entries, indent=2)}")


def make_archive(root, generated="2025-03-04T05:06:07.000Z", likes=LIKES):
    data = root / "data"
    write_js(data, "account.js", ACCOUNT)
    write_js(data, "tweets.js", [{"tweet": t} for t in [TWEET, REPLY, RETWEET, PHOTO]])
    write_js(data, "direct-messages.js", DMS)
    write_js(data, "direct-messages-group.js", GROUP_DMS)
    write_js(data, "like.js", likes)
    manifest = {"archiveInfo": {"generationDate": generated, "isPartialArchive": False}}
    (data / "manifest.js").write_text(f"window.__THAR_CONFIG = {json.dumps(manifest)}")
    return root


def stream(vault, name):
    out = vault / "raw" / "twitter" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["id"]: r for r in map(json.loads, lines)}


def test_posts_are_typed_and_links_are_expanded(tmp_path):
    posts = {r["id"]: r for r in twitter.read_posts(make_archive(tmp_path / "a"))}

    tweet = posts["1100"]
    assert tweet["ts"] == "2025-01-31T23:59:59Z"
    assert (tweet["kind"], tweet["from_me"], tweet["author"]) == ("tweet", True, "me_example")
    assert tweet["text"] == "Notes & links: https://example.com/n"
    assert (tweet["favorite_count"], tweet["retweet_count"], tweet["lang"]) == (3, 1, "en")

    reply = posts["1101"]
    assert (reply["kind"], reply["in_reply_to"], reply["in_reply_to_user"]) == (
        "reply",
        "900",
        "friend_example",
    )

    # A retweet is the user's to have made, but the words are someone else's.
    retweet = posts["1102"]
    assert (retweet["kind"], retweet["from_me"], retweet["author"]) == (
        "retweet",
        False,
        "friend_example",
    )

    photo = posts["1103"]
    assert photo["text"] == "Two views https://example.com/p/1103"
    assert photo["media"] == ["photo", "video"]
    assert photo["lang"] is None


def test_dms_mark_from_me_by_account_id_and_include_group_chats(tmp_path):
    dms = {r["id"]: r for r in twitter.read_dms(make_archive(tmp_path / "a"))}
    assert sorted(dms) == ["1000-2000/5001", "1000-2000/5002", "g42/6001"]  # no join event

    theirs = dms["1000-2000/5001"]
    assert theirs["ts"] == "2025-02-01T12:00:00Z"
    assert (theirs["from_me"], theirs["sender_id"], theirs["conversation_type"]) == (
        False,
        "2000",
        "direct",
    )
    assert theirs["text"] == "see https://example.com/d"

    mine = dms["1000-2000/5002"]
    assert (mine["from_me"], mine["text"], mine["media_count"]) == (True, "thanks", 1)

    group = dms["g42/6001"]
    assert (group["from_me"], group["conversation_type"], group["recipient_id"]) == (
        True,
        "group",
        None,
    )


def test_likes_are_dated_by_the_archive_and_keep_the_date_they_were_first_seen(tmp_path):
    vault = tmp_path / "vault"
    twitter.ingest(vault, make_archive(tmp_path / "a"))
    likes = stream(vault, "likes")
    assert {r["ts"] for r in likes.values()} == {"2025-03-04T05:06:07Z"}
    assert likes["3001"]["text"] == "Q & A"
    assert (likes["3001"]["from_me"], likes["3002"]["text"]) == (False, None)

    # Three months on: 3001 is still liked, 3003 is new.
    newer = LIKES[:1] + [{"like": {"tweetId": "3003", "fullText": "new"}}]
    later = make_archive(tmp_path / "b", generated="2025-06-01T00:00:00.000Z", likes=newer)
    twitter.ingest(vault, later)
    likes = stream(vault, "likes")
    assert {i: r["ts"][:7] for i, r in likes.items()} == {
        "3001": "2025-03",
        "3002": "2025-03",
        "3003": "2025-06",
    }
    june = (vault / "raw" / "twitter" / "likes" / "2025-06.jsonl").read_text().splitlines()
    assert len(june) == 1  # 3001 didn't move into June as a second copy


def test_without_a_manifest_likes_take_the_date_in_the_folder_name(tmp_path):
    export = make_archive(tmp_path / "2025-05-06")
    (export / "data" / "manifest.js").unlink()
    assert {r["ts"] for r in twitter.read_likes(export)} == {"2025-05-06T00:00:00Z"}


def test_older_archives_name_the_file_tweet_js_split_it_and_skip_the_wrapper(tmp_path):
    data = tmp_path / "a" / "data"
    write_js(data, "tweet.js", [TWEET])  # bare entries, as before the {"tweet": ...} wrapper
    write_js(data, "tweet-part1.js", [{"tweet": REPLY}])
    write_js(data, "tweets-part1.js", [{"tweet": PHOTO}])

    posts = {r["id"]: r for r in twitter.read_posts(tmp_path / "a")}
    assert sorted(posts) == ["1100", "1101", "1103"]
    assert posts["1100"]["author"] is None  # no account.js to name the user


def test_missing_files_are_empty_and_malformed_entries_are_skipped(tmp_path):
    data = tmp_path / "a" / "data"
    no_date = {**TWEET, "id_str": "1200", "created_at": None}
    bad_date = {**TWEET, "id_str": "1201", "created_at": "sometime"}
    write_js(data, "tweets.js", [{"tweet": TWEET}, {"tweet": no_date}, {"tweet": bad_date}, "x"])
    (data / "like.js").write_text("window.YTD.like.part0 = [ {")  # cut off mid-download
    broken_dm = {"dmConversation": {"conversationId": "c", "messages": [{"messageCreate": {}}]}}
    write_js(data, "direct-messages.js", [broken_dm, {"dmConversation": {}}])

    stats = twitter.ingest(tmp_path / "vault", tmp_path / "a")
    assert stats == {"read": 1, "added": 1, "updated": 0, "months_written": 1, "skipped": 6}
    assert list(stream(tmp_path / "vault", "posts")) == ["1100"]


def test_reingest_through_run_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    args = argparse.Namespace(export=make_archive(tmp_path / "a"))

    first = twitter.run(vault, args)
    assert first == {"read": 9, "added": 9, "updated": 0, "months_written": 4, "skipped": 0}
    assert sorted(p.name for p in (vault / "raw" / "twitter").iterdir()) == [
        "dms",
        "likes",
        "posts",
    ]

    again = twitter.run(vault, args)
    assert again == {"read": 9, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}

    # A later archive: the tweet picked up likes. Records it no longer has are kept.
    data = args.export / "data"
    write_js(data, "tweets.js", [{"tweet": {**TWEET, "favorite_count": "10"}}])
    later = twitter.run(vault, args)
    assert (later["updated"], later["added"]) == (1, 0)
    posts = stream(vault, "posts")
    assert posts["1100"]["favorite_count"] == 10
    assert len(posts) == 4


def test_an_export_without_a_data_folder_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="no data/ folder"):
        twitter.ingest(tmp_path / "vault", tmp_path)
