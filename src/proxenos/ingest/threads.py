"""Threads posts and replies from Meta's "Download your information".

Reads an unzipped JSON-format Threads export (Accounts Center, Your information and
permissions, Download your information, Threads) and writes one stream, vault/raw/threads/posts.
Every export is a full snapshot, so each run re-reads one and merges by id.

The files and keys below were checked against a real export (names and keys only):
- threads/threads_and_replies.json: text_post_app_text_posts[], each with media[] holding title
  (the post's text), creation_timestamp, uri (empty for a post without a photo or video), and
  text_app_post with is_reply and in_reply_to_username. A post with several photos repeats
  these on each, so the first one with text gives the text and time.
- threads/personal_information.json: text_post_app_text_post_app_profile[0].string_map_data
  with Username, which is the author.
Likes, follows and the rest aren't read. An Instagram export can hold the same files under
your_instagram_activity/threads/, and either folder works.

Strings are decoded back from Meta's mojibake as in instagram.py, whose helpers this reuses.
kind is "reply" or "post", and in_reply_to names the account replied to. A post is keyed by its
time, with #2, #3, ... for different posts in the same second. A post without a time, or with
neither text nor media, and a file that isn't JSON are counted as skipped.
"""

import argparse
from pathlib import Path
from typing import Any

from proxenos.ingest.instagram import _VIDEO, _load, _merge, _parse, _utc, _with_ids

_POSTS = "threads/threads_and_replies.json"
_PROFILE = "threads/personal_information.json"


def read_owner(export: Path) -> str | None:
    """The user's Threads username, or None without personal_information.json."""
    try:
        profile = _load(export / _PROFILE)["text_post_app_text_post_app_profile"][0]
        return profile["string_map_data"]["Username"]["value"] or None
    except Exception:  # noqa: BLE001  missing, or not the layout this expects
        return None


def read_posts(export: Path) -> list[dict | None]:
    try:
        data = _load(export / _POSTS)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return [None]
    entries: list[Any] = []
    if isinstance(data, dict):
        entries = [entry for value in data.values() if isinstance(value, list) for entry in value]
    author = read_owner(export)
    return _with_ids([_parse(_post, entry, author) for entry in entries])


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / _POSTS).is_file():
        raise FileNotFoundError(f"no {_POSTS} in {export}")
    return _merge({"posts": read_posts(export)}, vault / "raw" / "threads")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="the unzipped export"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _post(entry: dict, author: str | None) -> tuple[str, dict]:
    items = [m for m in entry.get("media") or [] if isinstance(m, dict)]
    first = next((m for m in items if m.get("title")), items[0] if items else {})
    seconds = first.get("creation_timestamp") or entry.get("creation_timestamp")
    about = first.get("text_app_post") or {}
    media = [
        "video" if Path(m["uri"]).suffix.lower() in _VIDEO else "photo"
        for m in items
        if m.get("uri")
    ]
    text = first.get("title") or entry.get("title") or None
    if not (text or media):
        raise ValueError("post without text or media")
    record = {
        "ts": _utc(seconds),
        "from_me": True,
        "author": author,
        "kind": "reply" if about.get("is_reply") else "post",
        "text": text,
        "in_reply_to": about.get("in_reply_to_username") or None,
        "media": media or None,
    }
    return str(int(seconds)), record
