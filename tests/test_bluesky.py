"""Bluesky ingester against a fake AppView. The handles, dids and posts are made up."""

import argparse
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from twin.ingest import bluesky

ME = "me.example.com"
DID = "did:plc:testme"
NEWEST = datetime(2025, 3, 1, 12, tzinfo=UTC)


def uri(n, collection="app.bsky.feed.post", did=DID):
    return f"at://{did}/{collection}/{n}"


def stamp(when):
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def item(n, hours_ago=None, reason=None, author=ME, did=DID, likes=None, **record):
    """A feed item as getAuthorFeed returns it, an hour apart from NEWEST unless told."""
    created = NEWEST - timedelta(hours=n if hours_ago is None else hours_ago)
    post = {
        "uri": uri(n, did=did),
        "cid": f"cid{n}",
        "author": {"did": did, "handle": author},
        "record": {
            "$type": "app.bsky.feed.post",
            "text": f"post {n}",
            "createdAt": stamp(created),
            **record,
        },
        "indexedAt": stamp(created + timedelta(seconds=5)),
        "likeCount": n if likes is None else likes,
        "repostCount": 1,
        "replyCount": 0,
        "quoteCount": 0,
    }
    return {"post": post, **({"reason": reason} if reason else {})}


class FakeAppView:
    """Stands in for the JSON fetch: serves `feed` newest first, `page_size` per page, with an
    offset as the cursor. `fail` is an HTTP status to raise instead."""

    def __init__(self, feed, page_size=2):
        self.feed, self.page_size = feed, page_size
        self.queries = []
        self.fail = None

    def __call__(self, url):
        base, _, query = url.partition("?")
        assert base == bluesky.FEED_URL
        params = dict(urllib.parse.parse_qsl(query))
        self.queries.append(params)
        if self.fail:
            raise urllib.error.HTTPError(url, self.fail, "error", {}, None)
        start = int(params.get("cursor", 0))
        body = {"feed": self.feed[start : start + self.page_size]}
        if start + self.page_size < len(self.feed):
            body["cursor"] = str(start + self.page_size)
        return body


def stored(vault):
    out = vault / "raw" / "bluesky" / "posts"
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["id"]: r for r in map(json.loads, lines)}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv(bluesky.HANDLE_ENV, ME)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("live HTTP"))


def test_records_cover_posts_replies_reposts_and_links(tmp_path):
    link = {
        "index": {"byteStart": 0, "byteEnd": 10},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://example.org/a"}],
    }
    card = {
        "$type": "app.bsky.embed.external",
        "external": {"uri": "https://example.org/b", "title": "B", "description": ""},
    }
    reply = {"parent": {"uri": uri(90), "cid": "p"}, "root": {"uri": uri(90), "cid": "p"}}
    quote = {
        "$type": "app.bsky.embed.recordWithMedia",
        "record": {"$type": "app.bsky.embed.record", "record": {"uri": uri(91), "cid": "q"}},
        "media": {"$type": "app.bsky.embed.external", "external": {"uri": "https://example.org/a"}},
    }
    repost = {
        "$type": "app.bsky.feed.defs#reasonRepost",
        "by": {"did": DID, "handle": ME},
        "uri": uri("r1", "app.bsky.feed.repost"),
        "indexedAt": "2025-03-01T11:30:00.000Z",
    }
    pin = {"$type": "app.bsky.feed.defs#reasonPin"}
    feed = [
        item(9, hours_ago=500, reason=pin),
        item(7, did="did:plc:friend", author="friend.example.com", reason=repost),
        item(1, facets=[link], embed=card),
        item(2, reply=reply, embed=quote),
        item(3, createdAt="not a date"),
    ]
    bluesky.ingest(tmp_path, ME, fetch=FakeAppView(feed))
    records = stored(tmp_path)

    assert records[uri(1)] == {
        "id": uri(1),
        "ts": "2025-03-01T11:00:00Z",
        "kind": "post",
        "author": ME,
        "text": "post 1",
        "reply_parent": None,
        "quote_of": None,
        "like_count": 1,
        "repost_count": 1,
        "reply_count": 0,
        "links": ["https://example.org/a", "https://example.org/b"],
    }
    replied = records[uri(2)]
    assert (replied["kind"], replied["reply_parent"]) == ("reply", uri(90))
    assert (replied["quote_of"], replied["links"]) == (uri(91), ["https://example.org/a"])
    assert records[uri(3)]["ts"] == "2025-03-01T09:00:05Z"  # falls back to indexedAt

    reposted = records[uri("r1", "app.bsky.feed.repost")]
    assert reposted["kind"] == "repost"
    assert reposted["ts"] == "2025-03-01T11:30:00Z"  # when it was reposted
    assert (reposted["author"], reposted["text"]) == ("friend.example.com", "post 7")
    assert uri(9) not in records  # the pinned copy is skipped
    assert len(records) == 4


def test_first_run_pages_to_the_end_and_later_runs_stop_at_stored_posts(tmp_path):
    fake = FakeAppView([item(n) for n in range(10, 17)])
    stats = bluesky.ingest(tmp_path, ME, fetch=fake)

    assert [q.get("cursor") for q in fake.queries] == [None, "2", "4", "6"]
    assert all(q["actor"] == ME and q["limit"] == "100" for q in fake.queries)
    assert (stats["read"], stats["added"]) == (7, 7)

    # Three new posts, and a like on the newest stored one.
    fake.feed = [item(n) for n in range(7, 10)] + [item(10, likes=50)] + fake.feed[1:]
    fake.queries.clear()
    stats = bluesky.ingest(tmp_path, ME, fetch=fake)
    assert len(fake.queries) == 2  # the second page holds post 10, which is stored
    assert stats == {"read": 4, "added": 3, "updated": 1, "months_written": 1}
    assert stored(tmp_path)[uri(10)]["like_count"] == 50

    fake.queries.clear()
    stats = bluesky.ingest(tmp_path, ME, full=True, fetch=fake)
    assert len(fake.queries) == 5
    assert stats == {"read": 10, "added": 0, "updated": 0, "months_written": 0}


def test_run_reads_the_handle_from_the_env(tmp_path, monkeypatch):
    urls = []

    def urlopen(url, timeout):
        urls.append(url)
        return io.BytesIO(json.dumps({"feed": [item(1)]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv(bluesky.HANDLE_ENV, f" @{ME} ")
    stats = bluesky.run(tmp_path, argparse.Namespace(full=False))

    assert stats["added"] == 1
    assert urllib.parse.parse_qs(urls[0].partition("?")[2])["actor"] == [ME]


def test_missing_handle_names_the_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv(bluesky.HANDLE_ENV)
    with pytest.raises(SystemExit, match=bluesky.HANDLE_ENV):
        bluesky.run(tmp_path, argparse.Namespace(full=False))


@pytest.mark.parametrize("status, message", [(400, bluesky.HANDLE_ENV), (429, "rate limited")])
def test_http_errors_stop_cleanly_without_writing(tmp_path, status, message):
    fake = FakeAppView([item(1)])
    fake.fail = status
    with pytest.raises(SystemExit, match=message):
        bluesky.ingest(tmp_path, ME, fetch=fake)
    assert not (tmp_path / "raw" / "bluesky").exists()
