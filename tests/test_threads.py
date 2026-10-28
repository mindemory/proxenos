"""Threads ingester against a synthetic Meta export. No real data lives in this repo."""

import json
from datetime import UTC, datetime

import pytest

from twin.ingest import threads


def seconds(*args):
    return int(datetime(*args, tzinfo=UTC).timestamp())


JUL_1 = seconds(2023, 7, 1, 10)
JUL_2 = seconds(2023, 7, 2, 10)


def item(ts, title, uri="", reply=False, to=None):
    about = {"is_reply": reply, "reply_control": "everyone"}
    if to:
        about["in_reply_to_username"] = to
    return {"uri": uri, "creation_timestamp": ts, "title": title, "text_app_post": about}


POSTS = {
    "text_post_app_text_posts": [
        {"media": [item(JUL_1, "Hello, Threads ✨")]},
        {"media": [item(JUL_1 + 60, "Agreed!", reply=True, to="friend_example")]},
        {
            "media": [
                item(JUL_2, "Two photos", "media/posts/202307/1.jpg"),
                item(JUL_2, "Two photos", "media/posts/202307/2.mp4"),
            ]
        },
        {"media": [item(JUL_2, "")]},
        {"media": [{"title": "no time"}]},
    ]
}
PROFILE = {
    "text_post_app_text_post_app_profile": [
        {"string_map_data": {"Username": {"value": "me_example"}, "Name": {"value": "Zoë"}}}
    ]
}


def garble(value):
    if isinstance(value, str):
        return value.encode("utf-8").decode("latin-1")
    if isinstance(value, list):
        return [garble(v) for v in value]
    if isinstance(value, dict):
        return {k: garble(v) for k, v in value.items()}
    return value


def make_export(root):
    (root / "threads").mkdir(parents=True)
    (root / "threads" / "threads_and_replies.json").write_text(json.dumps(garble(POSTS)))
    (root / "threads" / "personal_information.json").write_text(json.dumps(garble(PROFILE)))
    return root


def test_posts_and_replies_are_read_with_their_media(tmp_path):
    export = make_export(tmp_path / "e")
    assert threads.read_owner(export) == "me_example"
    records = threads.read_posts(export)
    assert records.count(None) == 2  # neither text nor media, and no time
    posts = {r["text"]: r for r in records if r}

    hello = posts["Hello, Threads ✨"]
    assert hello == {
        "id": str(JUL_1),
        "ts": "2023-07-01T10:00:00Z",
        "from_me": True,
        "author": "me_example",
        "kind": "post",
        "text": "Hello, Threads ✨",
        "in_reply_to": None,
        "media": None,
    }
    reply = posts["Agreed!"]
    assert (reply["kind"], reply["in_reply_to"]) == ("reply", "friend_example")
    assert posts["Two photos"]["media"] == ["photo", "video"]


def test_ingest_writes_posts_and_reruns_are_no_ops(tmp_path):
    vault = tmp_path / "vault"
    export = make_export(tmp_path / "e")
    assert threads.ingest(vault, export)["added"] == 3
    again = threads.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)
    with pytest.raises(FileNotFoundError):
        threads.ingest(vault, tmp_path / "nothing")
