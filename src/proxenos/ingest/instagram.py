"""Instagram messages, posts, comments and likes from Meta's "Download your information".

Reads an unzipped JSON-format export (Accounts Center, Your information and permissions,
Download your information) and writes four streams into vault/raw/instagram/: messages, posts,
comments and likes. Every export is a full snapshot, so each run re-reads one and merges by id.
A large export arrives as several zips. Unzip them all into the same folder.

The layout below follows Meta's export as documented. It has only been checked against synthetic
files, since no real export has been read yet. Newer exports keep activity under
your_instagram_activity/ and older ones at the top of the export, so both are searched:
- messages/inbox/<thread>/message_*.json: participants[].name, title, and messages[] with
  sender_name, timestamp_ms, content, share.link, and photos, videos, audio_files, gifs,
  files or sticker for attachments. Other folders (message_requests, ...) aren't read.
- content/posts_*.json (media/posts_*.json is tried too): media[] with uri, title (the
  caption) and creation_timestamp. A post with several media has title and creation_timestamp
  at the top instead.
- comments/post_comments*.json and comments/reels_comments.json: string_map_data with Comment,
  Media Owner and Time, or the older string_list_data (value, timestamp) under the media owner
  as title.
- likes/liked_posts*.json: string_list_data (href, timestamp) under the post owner as title.
- personal_information/personal_information/personal_information.json, or
  personal_information/personal_information.json in older exports:
  profile_user[0].string_map_data with Name and Username. Those mark from_me in messages.
  Without the file, the participant in the most threads is taken to be the user (no one on a tie).
A missing file reads as empty. A file that isn't JSON, and an entry in any other layout or
without a time, is counted as skipped.

Meta writes non-ASCII text as UTF-8 bytes read as latin-1 ("cafÃ©"), so every string is decoded
back, and one that wasn't garbled that way is left as it is.

from_me says who wrote the words. Posts and comments are the user's. A like is something they did to
someone else's post, so it's from_me false with the post's owner as author.

Nothing in the export has an id. A message is keyed by its thread and timestamp_ms. The thread
is the number that ends the thread folder's name, assumed to be the thread's id, since the name
before it follows renames. A post or comment is keyed by its time, and a like by the post's
URL. Exact copies collapse into one record, and different entries that share a key get #2, #3,
... in content order.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_ROOTS = ("your_instagram_activity", ".")
_PERSONAL = (
    "personal_information/personal_information/personal_information.json",
    "personal_information/personal_information.json",
)
_ATTACHMENTS = [
    ("photos", "photo"),
    ("videos", "video"),
    ("audio_files", "audio"),
    ("gifs", "gif"),
    ("files", "file"),
    ("sticker", "sticker"),
    ("share", "share"),
]
_VIDEO = {".mp4", ".mov", ".m4v", ".webm"}


def read_owner(export: Path) -> list[str]:
    """The user's Name and Username from personal_information.json, or [] without it."""
    for relative in _PERSONAL:
        if names := _names(export / relative):
            return names
    return []


def read_messages(export: Path, me: Iterable[str] = ()) -> list[dict | None]:
    """Messages from every inbox thread. None marks a file or message that couldn't be read."""
    threads: dict[str, dict] = {}
    skipped: list[None] = []
    for path in _files(export, "messages/inbox/*/message_*.json"):
        try:
            data = _load(path)
            messages = list(data["messages"])
            people = data.get("participants") or []
            names = {p["name"] for p in people if isinstance(p, dict) and p.get("name")}
        except Exception:  # noqa: BLE001  a file that won't parse is skipped, not fatal
            skipped.append(None)
            continue
        chat_id = _chat_id(path.parent.name)
        thread = threads.setdefault(chat_id, {"title": None, "names": set(), "messages": []})
        thread["title"] = thread["title"] or data.get("title")
        thread["names"].update(names)
        thread["messages"] += messages

    mine = {_norm(name) for name in me if name.strip()}
    mine = mine or {_norm(name) for name in read_owner(export)}
    if not mine and (likely := _most_common([t["names"] for t in threads.values()])):
        mine = {_norm(likely)}

    keyed: list[tuple[str, dict] | None] = []
    for chat_id, thread in threads.items():
        for message in thread["messages"]:
            keyed.append(_parse(_message, message, chat_id, thread, mine))
    return skipped + _with_ids(keyed)


def read_posts(export: Path) -> list[dict | None]:
    author = next(iter(read_owner(export)), None)
    entries = _entries(export, "content/posts_*.json", "media/posts_*.json")
    return _with_ids([_parse(_post, entry, author) for entry in entries])


def read_comments(export: Path) -> list[dict | None]:
    author = next(iter(read_owner(export)), None)
    entries = _entries(export, "comments/post_comments*.json", "comments/reels_comments.json")
    return _with_ids([_parse(_comment, entry, author) for entry in entries])


def read_likes(export: Path) -> list[dict | None]:
    entries = _entries(export, "likes/liked_posts*.json")
    return _with_ids([_parse(_like, entry) for entry in entries])


def ingest(vault: Path, export: Path, me: Iterable[str] = ()) -> dict[str, int]:
    folders = ["messages", "content", "media", "comments", "likes", "personal_information"]
    if not any((export / root / folder).is_dir() for root in _ROOTS for folder in folders):
        raise FileNotFoundError(f"no Instagram export folders in {export}")
    streams = {
        "messages": read_messages(export, me),
        "posts": read_posts(export),
        "comments": read_comments(export),
        "likes": read_likes(export),
    }
    return _merge(streams, vault / "raw" / "instagram")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped export"
    )
    parser.add_argument(
        "--me",
        action="append",
        default=[],
        metavar="NAME",
        help="your name as messages show it (repeatable; default: from personal_information)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser(), args.me)


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # _with_ids already made ids unique within a stream, so nothing is lost here.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _message(m: dict, chat_id: str, thread: dict, me: set[str]) -> tuple[str, dict]:
    sender = m.get("sender_name") or None
    kind = next((kind for key, kind in _ATTACHMENTS if m.get(key)), None)
    if kind is None:
        kind = "call" if "call_duration" in m else "text" if m.get("content") else "other"
    record = {
        "ts": _utc(int(m["timestamp_ms"]) / 1000),
        "chat_id": chat_id,
        "chat_name": thread["title"] or None,
        "chat_type": "group" if len(thread["names"]) > 2 else "direct",
        "from_me": sender is not None and _norm(sender) in me,
        "author": sender,
        "kind": kind,
        "text": m.get("content") or None,
        "link": (m.get("share") or {}).get("link") or None,
    }
    return f"{chat_id}/{int(m['timestamp_ms'])}", record


def _post(post: dict, author: str | None) -> tuple[str, dict]:
    media = post.get("media") or []
    first = media[0] if media else {}
    seconds = post.get("creation_timestamp") or first.get("creation_timestamp")
    kinds = [
        "video" if Path(m.get("uri") or "").suffix.lower() in _VIDEO else "photo" for m in media
    ]
    record = {
        "ts": _utc(seconds),
        "from_me": True,
        "author": author,
        "text": post.get("title") or first.get("title") or None,
        "media": kinds or None,
    }
    return str(int(seconds)), record


def _comment(entry: dict, author: str | None) -> tuple[str, dict]:
    fields = _fields(entry)
    seconds = fields.get("time") or fields.get("timestamp")
    text = fields.get("comment") or fields.get("value")
    if not text:
        raise ValueError("comment without text")
    record = {
        "ts": _utc(seconds),
        "from_me": True,
        "author": author,
        "text": text,
        "media_owner": fields.get("media owner") or fields.get("title") or None,
    }
    return str(int(seconds)), record


def _like(entry: dict) -> tuple[str, dict]:
    fields = _fields(entry)
    seconds = fields.get("timestamp") or fields.get("time")
    record = {
        "ts": _utc(seconds),
        "from_me": False,
        "author": fields.get("title") or None,
        "url": fields.get("href") or None,
    }
    return record["url"] or str(int(seconds)), record


def _fields(entry: dict) -> dict:
    """An activity entry's values by lowercased label, whichever of Meta's two layouts it uses.

    string_map_data: {"Comment": {"value": "..."}, "Time": {"timestamp": 1690000000}}.
    string_list_data: [{"href": "...", "value": "...", "timestamp": 1690000000}] beside "title".
    """
    fields = {"title": entry.get("title")}
    for item in entry.get("string_list_data") or []:
        fields.update({key: value for key, value in item.items() if value not in ("", None)})
    for label, item in (entry.get("string_map_data") or {}).items():
        fields[label.lower()] = item.get("value") or item.get("timestamp") or item.get("href")
    return fields


def _parse(
    make: Callable[..., tuple[str, dict]], entry: Any, *context: Any
) -> tuple[str, dict] | None:
    if not isinstance(entry, dict):
        return None
    try:
        return make(entry, *context)
    except Exception:  # noqa: BLE001  a malformed entry is skipped, not fatal
        return None


def _with_ids(keyed: list[tuple[str, dict] | None]) -> list[dict | None]:
    """Records with ids from their keys. Exact copies collapse, and distinct records that share
    a key get #2, #3, ... in content order, so ids don't depend on the export's ordering."""
    groups: dict[str, list[dict]] = defaultdict(list)
    out: list[dict | None] = []
    for item in keyed:
        if item is None:
            out.append(None)
        else:
            groups[item[0]].append(item[1])
    for key, group in groups.items():
        unique = {json.dumps(record, sort_keys=True): record for record in group}
        for n, (_, record) in enumerate(sorted(unique.items()), start=1):
            out.append({"id": key if n == 1 else f"{key}#{n}", **record})
    return out


def _files(export: Path, *patterns: str) -> list[Path]:
    return sorted(
        {p for root in _ROOTS for pattern in patterns for p in (export / root).glob(pattern)}
    )


def _entries(export: Path, *patterns: str) -> list[Any]:
    """Every entry in the matching files. A file that won't parse is one None."""
    entries: list[Any] = []
    for path in _files(export, *patterns):
        try:
            data = _load(path)
        except (OSError, ValueError):
            entries.append(None)
            continue
        # Lists sit at the top (posts_1.json) or under one key ({"likes_media_likes": [...]}).
        if isinstance(data, dict):
            data = [entry for value in data.values() if isinstance(value, list) for entry in value]
        entries += data if isinstance(data, list) else [None]
    return entries


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return _fix(json.load(f))


def _fix(value: Any) -> Any:
    """Undo Meta's mojibake: 'cafÃ©' is the UTF-8 for 'café' read as latin-1."""
    if isinstance(value, str):
        try:
            return value.encode("latin-1").decode("utf-8")
        except UnicodeError:
            return value
    if isinstance(value, list):
        return [_fix(item) for item in value]
    if isinstance(value, dict):
        return {key: _fix(item) for key, item in value.items()}
    return value


def _names(path: Path) -> list[str]:
    try:
        fields = _load(path)["profile_user"][0]["string_map_data"]
        return [v for key in ("Name", "Username") if (v := (fields.get(key) or {}).get("value"))]
    except Exception:  # noqa: BLE001  missing, or not the layout this expects
        return []


def _chat_id(folder: str) -> str:
    """'someone_1234567890' as '1234567890'. A folder name without the number is kept whole."""
    match = re.search(r"_(\d+)$", folder)
    return match.group(1) if match else folder


def _most_common(name_sets: list[set[str]]) -> str | None:
    """The name in the most threads, or None when it's a tie."""
    top = Counter(name for names in name_sets for name in names).most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def _utc(seconds: Any) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, int | float | str):
        raise TypeError(f"not a timestamp: {seconds!r}")
    when = datetime.fromtimestamp(float(seconds), UTC)
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")
