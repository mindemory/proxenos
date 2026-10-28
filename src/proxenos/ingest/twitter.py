"""X/Twitter posts, DMs and likes from the account archive.

Reads an unzipped "Download an archive of your data" export and writes three streams into
vault/raw/twitter/: posts, dms and likes. The archive is a copy of the account's whole life, so
every run re-reads one and merges by id: point --export at a newer archive and what overlaps
is a no-op.

The layout below follows the archive's documented format. It has only been checked against
synthetic files, since no real archive has been read yet:
- data/account.js: accountId and username. The id marks from_me in DMs; the username is the
  author of posts.
- data/tweets.js (tweet.js in older archives), plus tweets-part1.js, ... when it's split.
  Entries are {"tweet": {...}}, or bare in older archives, with id_str, created_at ("Wed Oct
  10 20:19:24 +0000 2018"), full_text, entities.urls, entities.media, in_reply_to_status_id_str,
  in_reply_to_screen_name, favorite_count, retweet_count and lang. full_text arrives
  HTML-escaped (&amp;) as the API sends it, and t.co links are expanded from the entities.
- data/direct-messages.js and direct-messages-group.js: dmConversation entries with
  conversationId and messages, of which only messageCreate events are read: id, senderId,
  recipientId, text, urls and createdAt, which is ISO-8601 rather than the tweet format.
- data/like.js: tweetId, fullText and expandedUrl, and nothing else.
- data/manifest.js: archiveInfo.generationDate, the date of the archive.
Every file is `window.YTD.<name>.part0 = [...]` (manifest.js is `window.__THAR_CONFIG = {...}`),
which is JSON after the first "=". A missing file reads as empty. A file or entry that won't
parse is counted as skipped.

Likes carry no time, so a like's ts is the date of the first archive it appeared in. That's
the manifest's generationDate, else a YYYY-MM-DD date in the export folder's name, else when
like.js was last modified. A like already in the vault keeps its ts, so a later archive
doesn't move it. The ts says "liked by then", not when.

from_me says who wrote the words. A retweet or a like is something the user did, but the text is
someone else's, so both are from_me false. A retweet's author is the handle after "RT @".
"""

import argparse
import html
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_RETWEET = re.compile(r"RT @(\w+):")
_DATE = re.compile(r"(19|20)\d\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")


def read_account(export: Path) -> dict:
    """The archive's account entry (accountId, username, ...), or {} when there isn't one."""
    for entry in _entries(export, "account"):
        if entry and isinstance(entry.get("account"), dict):
            return entry["account"]
    return {}


def read_posts(export: Path) -> list[dict | None]:
    """Tweets, replies and retweets in archive order. None marks an entry that wouldn't parse."""
    username = read_account(export).get("username") or None
    return [_parse(_post, e, username) for e in _entries(export, "tweets", "tweet")]


def read_dms(export: Path) -> list[dict | None]:
    """messageCreate events from one-to-one and group DMs. None marks a skipped one."""
    me = read_account(export).get("accountId")
    records = []
    for name, chat_type in [("direct-messages", "direct"), ("direct-messages-group", "group")]:
        for entry in _entries(export, name):
            try:
                conversation = entry["dmConversation"]
                events = list(conversation["messages"])
                conversation_id = str(conversation["conversationId"])
            except Exception:  # noqa: BLE001  a malformed conversation is skipped, not fatal
                records.append(None)
                continue
            for event in events:
                if not isinstance(event, dict):
                    records.append(None)
                elif "messageCreate" in event:
                    created = event["messageCreate"]
                    records.append(_parse(_dm, created, conversation_id, chat_type, me))
                # Joins, leaves, renames and reactions sit alongside messages. They're not read.
    return records


def read_likes(export: Path) -> list[dict | None]:
    """Liked tweets, each dated by the archive. None marks an entry that wouldn't parse."""
    entries = list(_entries(export, "like"))
    if not entries:
        return []
    ts = _archive_ts(export)
    return [_parse(_like, entry, ts) for entry in entries]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / "data").is_dir():
        raise FileNotFoundError(f"no data/ folder in {export}: point --export at the archive")
    out = vault / "raw" / "twitter"
    # A like keeps the ts it was first stored with. Moving it would leave a copy in the old month.
    seen = _stored_ts(out / "likes")
    likes = [r and {**r, "ts": seen.get(r["id"], r["ts"])} for r in read_likes(export)]
    streams = {"posts": read_posts(export), "dms": read_dms(export), "likes": likes}
    return _merge(streams, out)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped archive"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: an entry the archive repeats is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _post(entry: dict, username: str | None) -> dict:
    tweet = entry.get("tweet", entry)
    entities = tweet.get("entities") or {}
    links = (entities.get("urls") or []) + (entities.get("media") or [])
    text = _expand(html.unescape(tweet["full_text"]), links, "expanded_url")
    media = (tweet.get("extended_entities") or {}).get("media") or entities.get("media") or []
    retweet = _RETWEET.match(text)
    in_reply_to = tweet.get("in_reply_to_status_id_str") or tweet.get("in_reply_to_status_id")
    if retweet:
        kind = "retweet"
    elif in_reply_to:
        kind = "reply"
    else:
        kind = "tweet"
    return {
        "id": str(tweet.get("id_str") or tweet["id"]),
        "ts": _ts(tweet["created_at"]),
        "kind": kind,
        "from_me": not retweet,
        "author": retweet.group(1) if retweet else username,
        "text": text or None,
        "in_reply_to": str(in_reply_to) if in_reply_to else None,
        "in_reply_to_user": tweet.get("in_reply_to_screen_name") or None,
        "favorite_count": _int(tweet.get("favorite_count")),
        "retweet_count": _int(tweet.get("retweet_count")),
        "lang": tweet.get("lang") or None,
        "media": [m.get("type") or "other" for m in media] or None,
    }


def _dm(message: dict, conversation_id: str, chat_type: str, me: str | None) -> dict:
    sender = str(message["senderId"])
    return {
        "id": f"{conversation_id}/{message['id']}",
        "ts": _ts(message["createdAt"]),
        "conversation_id": conversation_id,
        "conversation_type": chat_type,
        "from_me": me is not None and sender == str(me),
        "sender_id": sender,
        "recipient_id": str(message["recipientId"]) if message.get("recipientId") else None,
        "text": _expand(message.get("text") or "", message.get("urls") or [], "expanded") or None,
        "media_count": len(message.get("mediaUrls") or []) or None,
    }


def _like(entry: dict, ts: str) -> dict:
    like = entry.get("like", entry)
    text = like.get("fullText")
    return {
        "id": str(like["tweetId"]),
        "ts": ts,
        "from_me": False,
        "tweet_id": str(like["tweetId"]),
        "text": html.unescape(text) if text else None,
        "url": like.get("expandedUrl") or None,
    }


def _parse(make: Callable[..., dict], entry: Any, *context: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    try:
        return make(entry, *context)
    except Exception:  # noqa: BLE001  a malformed entry is skipped, not fatal
        return None


def _entries(export: Path, *names: str) -> Iterator[dict | None]:
    """Every entry in data/<name>.js and its part files. None stands for one that won't parse."""
    data = export / "data"
    for name in names:
        for path in [data / f"{name}.js", *sorted(data.glob(f"{name}-part*.js"))]:
            if not path.is_file():
                continue
            try:
                entries = _load_js(path)
            except (OSError, ValueError):
                yield None
                continue
            if not isinstance(entries, list):
                yield None
                continue
            for entry in entries:
                yield entry if isinstance(entry, dict) else None


def _load_js(path: Path) -> Any:
    """`window.YTD.tweets.part0 = [...]` without the assignment."""
    _, _, body = path.read_text(encoding="utf-8").partition("=")
    return json.loads(body.strip().rstrip(";"))


def _archive_ts(export: Path) -> str:
    data = export / "data"
    try:
        return _ts(_load_js(data / "manifest.js")["archiveInfo"]["generationDate"])
    except Exception:  # noqa: BLE001  no manifest, or one without the date: try the folder name
        named = _DATE.search(export.name)
    if named:
        return f"{named[0]}T00:00:00Z"
    like = data / "like.js"
    return _utc(datetime.fromtimestamp((like if like.exists() else data).stat().st_mtime, UTC))


def _stored_ts(directory: Path) -> dict[str, str]:
    """ts by id for the records already in a stream."""
    seen = {}
    for path in directory.glob("*.jsonl"):
        with path.open(encoding="utf-8") as f:
            for record in map(json.loads, f):
                seen[record["id"]] = record["ts"]
    return seen


def _expand(text: str, links: list, key: str) -> str:
    """Swap t.co links for the URLs they stand for."""
    for link in links:
        if isinstance(link, dict) and link.get("url") and link.get(key):
            text = text.replace(link["url"], link[key])
    return text.strip()


def _ts(text: str) -> str:
    """Tweet dates ("Wed Oct 10 20:19:24 +0000 2018") or ISO-8601 ones, in UTC."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        when = parsedate_to_datetime(text)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return _utc(when)


def _utc(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _int(value: Any) -> int | None:
    """Counts arrive as strings ("3")."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
