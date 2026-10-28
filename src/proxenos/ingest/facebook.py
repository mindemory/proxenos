"""Facebook messages, posts and comments from Meta's "Download your information".

Reads an unzipped JSON-format export (Accounts Center, Your information and permissions,
Download your information, Facebook) and writes three streams into vault/raw/facebook/: messages,
posts and comments. Every export is a full snapshot, so each run re-reads one and merges by id.
A large export arrives as several zips. Unzip them all into the same folder.

The files and keys below were checked against a real export (names and keys only):
- your_facebook_activity/messages/<folder>/<thread>/message_*.json, for the folders inbox,
  e2ee_cutover (a chat's history from before it moved to end-to-end encryption) and
  archived_threads: participants[].name, title, and messages[] laid out as in Instagram's
  export. filtered_threads and message_requests aren't read.
- your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_*.json: a list of posts
  with timestamp, title ("... updated his status."), data[].post (the text), and
  attachments[].data[] holding media (uri, description), external_context (url), place (name),
  life_event (title) or text. A post without text of its own takes its photos' descriptions, a
  life event's title or an attachment's text.
- your_facebook_activity/comments_and_reactions/comments.json: comments_v2[] with timestamp,
  title, data[].comment (comment, author) and attachments like a post's. Reactions aren't read.
- personal_information/profile_information/profile_information.json: profile_v2.name.full_name.
  It marks from_me in messages and is the author of posts and comments. Without it, the
  participant in the most threads is taken to be the user (no one on a tie).
A missing file reads as empty. A file that isn't JSON, and an entry without a time, is counted
as skipped, and so is a post or comment with no text, title or attachment.

Strings are decoded back from Meta's mojibake, messages become records, and ids are made just as
in instagram.py, whose helpers this reuses: a message is keyed by its thread and timestamp_ms,
and a post or comment by its time, with #2, #3, ... for different entries that share a key.
"""

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from proxenos.ingest.instagram import (
    _VIDEO,
    _chat_id,
    _load,
    _merge,
    _message,
    _most_common,
    _norm,
    _parse,
    _utc,
    _with_ids,
)

_ACTIVITY = "your_facebook_activity"
_THREADS = ("inbox", "e2ee_cutover", "archived_threads")
_PROFILE = "personal_information/profile_information/profile_information.json"


def read_owner(export: Path) -> list[str]:
    """The user's full name from profile_information.json, or [] without it."""
    try:
        name = _load(export / _PROFILE)["profile_v2"]["name"]["full_name"]
    except Exception:  # noqa: BLE001  missing, or not the layout this expects
        return []
    return [name] if isinstance(name, str) and name.strip() else []


def read_messages(export: Path, me: Iterable[str] = ()) -> list[dict | None]:
    """Messages from every thread. None marks a file or message that couldn't be read."""
    threads: dict[str, dict] = {}
    skipped: list[None] = []
    paths = [
        path
        for folder in _THREADS
        for path in sorted((export / _ACTIVITY / "messages" / folder).glob("*/message_*.json"))
    ]
    for path in paths:
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
    entries = _entries(export, "posts/your_posts__check_ins__photos_and_videos_*.json")
    return _with_ids([_parse(_post, entry, author) for entry in entries])


def read_comments(export: Path) -> list[dict | None]:
    author = next(iter(read_owner(export)), None)
    entries = _entries(export, "comments_and_reactions/comments.json")
    return _with_ids([_parse(_comment, entry, author) for entry in entries])


def ingest(vault: Path, export: Path, me: Iterable[str] = ()) -> dict[str, int]:
    if not (export / _ACTIVITY).is_dir():
        raise FileNotFoundError(f"no {_ACTIVITY} folder in {export}")
    streams = {
        "messages": read_messages(export, me),
        "posts": read_posts(export),
        "comments": read_comments(export),
    }
    return _merge(streams, vault / "raw" / "facebook")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped export"
    )
    parser.add_argument(
        "--me",
        action="append",
        default=[],
        metavar="NAME",
        help="your name as messages show it (repeatable; default: from profile_information)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser(), args.me)


def _post(entry: dict, author: str | None) -> tuple[str, dict]:
    seconds = entry["timestamp"]
    parts = _attached(entry)
    texts = [d["post"] for d in entry.get("data") or [] if isinstance(d, dict) and d.get("post")]
    text = "\n\n".join(texts or parts["text"]) or None
    if not (text or entry.get("title") or parts["media"] or parts["url"] or parts["place"]):
        raise ValueError("empty post")
    record = {
        "ts": _utc(seconds),
        "from_me": True,
        "author": author,
        "text": text,
        "title": entry.get("title") or None,
        "media": parts["media"] or None,
        "url": next(iter(parts["url"]), None),
        "place": next(iter(parts["place"]), None),
    }
    return str(int(seconds)), record


def _comment(entry: dict, author: str | None) -> tuple[str, dict]:
    seconds = entry["timestamp"]
    parts = _attached(entry)
    data = [d.get("comment") for d in entry.get("data") or [] if isinstance(d, dict)]
    comments = [c for c in data if isinstance(c, dict)]
    text = "\n\n".join(c["comment"] for c in comments if c.get("comment")) or None
    if not (text or parts["media"] or parts["url"]):
        raise ValueError("comment without text or attachment")
    record = {
        "ts": _utc(seconds),
        "from_me": True,
        "author": next((c["author"] for c in comments if c.get("author")), author),
        "text": text,
        "title": entry.get("title") or None,
        "media": parts["media"] or None,
        "url": next(iter(parts["url"]), None),
    }
    return str(int(seconds)), record


def _attached(entry: dict) -> dict[str, list[str]]:
    """What a post's or comment's attachments hold: media kinds, link urls, place names, and
    text (a photo's description, a life event's title or an attachment's own text)."""
    found: dict[str, list[str]] = {"media": [], "url": [], "place": [], "text": []}
    for attachment in entry.get("attachments") or []:
        items = attachment.get("data") if isinstance(attachment, dict) else None
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if isinstance(media := item.get("media"), dict):
                video = Path(media.get("uri") or "").suffix.lower() in _VIDEO
                found["media"].append("video" if video else "photo")
                if isinstance(media.get("description"), str) and media["description"].strip():
                    found["text"].append(media["description"])
            if isinstance(link := item.get("external_context"), dict) and link.get("url"):
                found["url"].append(link["url"])
            if isinstance(place := item.get("place"), dict) and place.get("name"):
                found["place"].append(place["name"])
            if isinstance(event := item.get("life_event"), dict) and event.get("title"):
                found["text"].append(event["title"])
            if isinstance(item.get("text"), str) and item["text"].strip():
                found["text"].append(item["text"])
    return found


def _entries(export: Path, pattern: str) -> list[Any]:
    """Every entry in the matching files. A file that won't parse is one None."""
    entries: list[Any] = []
    for path in sorted((export / _ACTIVITY).glob(pattern)):
        try:
            data = _load(path)
        except (OSError, ValueError):
            entries.append(None)
            continue
        # Lists sit at the top (posts) or under one key ({"comments_v2": [...]}).
        if isinstance(data, dict):
            data = [entry for value in data.values() if isinstance(value, list) for entry in value]
        entries += data if isinstance(data, list) else [None]
    return entries
