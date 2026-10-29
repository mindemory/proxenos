"""Instagram, Messenger, X and LinkedIn chats through Beeper Desktop's local API, as they come in.

Meta and LinkedIn give other apps no way to read personal messages, but Beeper Desktop
(beeper.com, free for up to five accounts) signs in to them and keeps the chats on this Mac,
with a local API at http://localhost:23373. Turn the API on in Beeper's settings, create a token
there (Settings, Integrations, the + by Approved connections) and put it in .env as
BEEPER_ACCESS_TOKEN. Beeper has to be running for a sync to read it.

Each run reads the chats active since the last one and their new messages, and writes them where
those sources' own exports go, in the same shape, so replies are drafted for them like any other
chat: vault/raw/instagram/messages/, raw/facebook/messages/, raw/twitter/dms/ and
raw/linkedin/messages/. Chats and
messages keep Beeper's ids, prefixed "beeper:", so they never collide with an export's. Networks
Proxenos reads directly (WhatsApp, Slack, email) are left alone. The first run goes back
FIRST_DAYS days, for enough of the user's own messages to show how they write in each chat.
It only reads: nothing is sent, marked read or changed in Beeper.
"""

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos.store import merge_monthly

BASE = "http://localhost:23373"
FIRST_DAYS = 90
OVERLAP = timedelta(minutes=10)  # each run looks back past the last, for messages that came late
PAGES = 20  # pages of a chat's messages read at most per run
_STATE = Path("state", "beeper.json")

Fetch = Callable[[str], dict]


def ingest(
    vault: Path,
    fetch: Fetch,
    now: datetime | None = None,
    full: bool = False,
    days: int = FIRST_DAYS,
    pages: int = PAGES,
) -> dict:
    now = now or datetime.now(UTC)
    state_path = vault / _STATE
    state = json.loads(state_path.read_text()) if state_path.exists() and not full else {}
    since = state.get("since") or _iso(now - timedelta(days=days))

    stats: Counter = Counter()
    streams: dict[str, list[dict]] = defaultdict(list)
    for chat in _chats(fetch, since):
        source = _source(chat.get("network"))
        if source is None:
            stats["chats_skipped"] += 1
            continue
        stats["chats_read"] += 1
        for message in _messages(fetch, chat["id"], since, pages):
            if record := _record(source, chat, message):
                streams[source].append(record)
    for source, records in streams.items():
        stream = "dms" if source == "twitter" else "messages"  # as the X export names it
        stats.update(merge_monthly(records, vault / "raw" / source / stream))

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"since": _iso(now - OVERLAP)}))
    return dict(stats)


def _chats(fetch: Fetch, since: str) -> Iterator[dict]:
    """Chats active since `since`: they come most recent first, so stop at the first older one."""
    query = {"limit": 200}
    while True:
        page = fetch(f"/v1/chats?{urllib.parse.urlencode(query)}")
        for chat in page.get("items") or []:
            if _iso_of(chat.get("lastActivity")) < since:
                return
            yield chat
        if not page.get("hasMore") or not page.get("oldestCursor"):
            return
        query = {"limit": 200, "cursor": page["oldestCursor"], "direction": "before"}


def _messages(fetch: Fetch, chat_id: str, since: str, pages: int = PAGES) -> Iterator[dict]:
    """A chat's messages since `since`, newest page first, going back until they're older."""
    path = f"/v1/chats/{urllib.parse.quote(chat_id, safe='')}/messages"
    query: dict = {}
    for _ in range(pages):
        page = fetch(f"{path}?{urllib.parse.urlencode(query)}" if query else path)
        items = page.get("items") or []
        yield from (m for m in items if _iso_of(m.get("timestamp")) >= since)
        if not items or min(_iso_of(m.get("timestamp")) for m in items) < since:
            return
        if not page.get("hasMore") or not page.get("oldestCursor"):
            return
        query = {"cursor": page["oldestCursor"], "direction": "before"}


def _source(network: object) -> str | None:
    name = str(network or "").lower()
    if "instagram" in name:
        return "instagram"
    if "messenger" in name or "facebook" in name:
        return "facebook"
    if "linkedin" in name:
        return "linkedin"
    if name in ("x", "twitter", "x (twitter)") or "twitter" in name:
        return "twitter"
    return None  # read directly, or not a source Proxenos knows


def _record(source: str, chat: dict, m: dict) -> dict | None:
    if m.get("isDeleted") or m.get("isHidden") or m.get("type") == "REACTION" or not m.get("id"):
        return None
    ts = _iso_of(m.get("timestamp"))
    if not ts:
        return None
    chat_id = f"beeper:{chat['id']}"
    mine = bool(m.get("isSender"))
    common = {
        "id": f"{chat_id}/{m['id']}",
        "ts": ts,
        "from_me": mine,
        "text": m.get("text") or None,
    }
    sender = m.get("senderName") or None
    if source == "linkedin":
        return common | {
            "conversation_id": chat_id,
            "conversation_title": chat.get("title") or None,
            "author": sender,
            "folder": "INBOX",
        }
    if source == "twitter":
        return common | {
            "conversation_id": chat_id,
            "conversation_type": "direct" if chat.get("type") == "single" else "group",
            "conversation_title": chat.get("title") or None,
            "sender_id": m.get("senderID"),
            "sender_name": sender,
        }
    links = m.get("links") or []
    return common | {
        "chat_id": chat_id,
        "chat_name": chat.get("title") or None,
        "chat_type": "direct" if chat.get("type") == "single" else "group",
        "author": sender,
        "kind": str(m.get("type") or "TEXT").lower(),
        "link": links[0].get("url") if links else None,
    }


def _iso_of(value: object) -> str:
    """An API timestamp as the vault writes them, in UTC to the second; "" for anything else."""
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    return _iso(when if when.tzinfo else when.replace(tzinfo=UTC))


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fetcher(token: str, base: str = BASE) -> Fetch:
    def fetch(path: str) -> dict:
        request = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(
                    "Beeper refused the token: create a new one in Beeper (Settings, Integrations)"
                    " and put it in .env as BEEPER_ACCESS_TOKEN"
                ) from None
            raise
        except urllib.error.URLError:
            raise SystemExit(
                "Beeper Desktop isn't answering: open it, and turn on its API in Settings"
            ) from None

    return fetch


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--full", action="store_true", help="read back --days again")
    parser.add_argument(
        "--days", type=int, default=FIRST_DAYS, help="how far back a full read goes"
    )
    parser.add_argument("--pages", type=int, default=PAGES, help="pages of each chat read at most")


def run(vault: Path, args: argparse.Namespace) -> dict:
    token = os.environ.get("BEEPER_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set BEEPER_ACCESS_TOKEN in .env first (see `proxenos ingest beeper -h`).")
    return ingest(vault, _fetcher(token), full=args.full, days=args.days, pages=args.pages)
