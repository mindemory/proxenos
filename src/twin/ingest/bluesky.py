"""Bluesky posts, replies and reposts from the public AppView.

Pages through app.bsky.feed.getAuthorFeed for the handle in TWIN_BLUESKY_HANDLE and writes
monthly JSONL into the vault. The AppView serves public posts without auth, newest first.
Runs are incremental: paging stops after the first page that holds a post already stored, so
the counts on that page are refreshed and older posts are left alone. `--full` pages to the
end, which also refreshes the like, repost and reply counts of older posts. Merging by id
makes both safe to repeat.

A repost is stored under the repost's own uri and dated when it was reposted. Its text,
counts and links are those of the reposted post, and `author` says whose post it is.
"""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from twin.store import merge_monthly

FEED_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
HANDLE_ENV = "TWIN_BLUESKY_HANDLE"
PAGE_SIZE = 100  # the AppView's maximum

_REPOST = "app.bsky.feed.defs#reasonRepost"
# A pinned post can head the feed out of order. It also appears in its own place.
_PIN = "app.bsky.feed.defs#reasonPin"
_LINK = "app.bsky.richtext.facet#link"

# Takes a URL and returns the decoded JSON body, raising HTTPError the way urlopen does.
Fetch = Callable[[str], Any]


def _fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def ingest(
    vault: Path, handle: str, full: bool = False, fetch: Fetch = _fetch_json
) -> dict[str, int]:
    out = vault / "raw" / "bluesky" / "posts"
    stored = set() if full else _stored_ids(out)
    records = []
    for feed in _pages(handle, fetch):
        page = [_record(item) for item in feed if _reason(item) != _PIN]
        records += page
        if any(record["id"] in stored for record in page):
            break
    return merge_monthly(records, out)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--full", action="store_true", help="page through every post, not just new ones"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    handle = (os.environ.get(HANDLE_ENV) or "").strip().lstrip("@")
    if not handle:
        raise SystemExit(f"bluesky: set {HANDLE_ENV} in the repo's .env, e.g. you.bsky.social")
    return ingest(vault, handle, full=args.full)


def _pages(handle: str, fetch: Fetch) -> Iterator[list[dict]]:
    cursor = None
    while True:
        params = {"actor": handle, "limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        body = _call(fetch, f"{FEED_URL}?{urllib.parse.urlencode(params)}")
        feed = body.get("feed") or []
        if feed:
            yield feed
        cursor = body.get("cursor")
        if not feed or not cursor:
            return


def _call(fetch: Fetch, url: str) -> Any:
    try:
        return fetch(url)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit(
                "bluesky: rate limited (HTTP 429), so no posts were written; run again later."
            ) from None
        if e.code == 400:
            raise SystemExit(
                f"bluesky: the AppView refused the feed (HTTP 400); check that {HANDLE_ENV} "
                "is a handle that exists."
            ) from None
        raise


def _stored_ids(directory: Path) -> set[str]:
    ids = set()
    for path in directory.glob("*.jsonl"):
        with path.open(encoding="utf-8") as f:
            ids.update(json.loads(line)["id"] for line in f)
    return ids


def _reason(item: dict) -> str | None:
    return (item.get("reason") or {}).get("$type")


def _record(item: dict) -> dict:
    post, reason = item["post"], item.get("reason") or {}
    record = post.get("record") or {}
    if _reason(item) == _REPOST:
        kind = "repost"
        # Older AppViews leave out the repost's own uri.
        id_ = reason.get("uri") or f"repost:{post['uri']}"
        ts = _utc(reason.get("indexedAt"), post.get("indexedAt"))
    else:
        kind = "reply" if record.get("reply") else "post"
        id_ = post["uri"]
        # createdAt is set by the client and can be malformed; indexedAt never is.
        ts = _utc(record.get("createdAt"), post.get("indexedAt"))
    return {
        "id": id_,
        "ts": ts,
        "kind": kind,
        "author": (post.get("author") or {}).get("handle"),
        "text": record.get("text") or None,
        "reply_parent": ((record.get("reply") or {}).get("parent") or {}).get("uri"),
        "quote_of": _quoted(record.get("embed") or {}),
        "like_count": post.get("likeCount"),
        "repost_count": post.get("repostCount"),
        "reply_count": post.get("replyCount"),
        "links": _links(record),
    }


def _links(record: dict) -> list[str]:
    links = [
        feature["uri"]
        for facet in record.get("facets") or []
        for feature in facet.get("features") or []
        if feature.get("$type") == _LINK and feature.get("uri")
    ]
    # Link cards sit in the embed, or in its media when the post also quotes another.
    embed = record.get("embed") or {}
    for part in (embed, embed.get("media") or {}):
        uri = (part.get("external") or {}).get("uri")
        if uri:
            links.append(uri)
    return list(dict.fromkeys(links))


def _quoted(embed: dict) -> str | None:
    # app.bsky.embed.record holds a strong ref; recordWithMedia nests it one level deeper.
    ref = embed.get("record") or {}
    return ref.get("uri") or (ref.get("record") or {}).get("uri")


def _utc(*candidates: str | None) -> str:
    for value in candidates:
        try:
            when = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    raise ValueError(f"no usable timestamp among {candidates}")
