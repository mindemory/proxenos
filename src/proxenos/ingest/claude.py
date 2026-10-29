"""Claude conversations, from claude.ai's data export (Settings, Privacy, Export data).

The export unzips to conversations.json, users.json and projects.json. conversations.json is a
list of conversations, each with a uuid, a name, created_at and chat_messages: each message's
uuid, sender ("human" or "assistant"), created_at, and its words, as text or as content blocks of
type "text" (thinking and tool blocks are left out). Attached files are counted, not read.

Writes vault/raw/claude/messages/, one record per message, in the shape the ChatGPT reader uses
(chatgpt.py): id (conversation uuid / message uuid), ts, conversation_id, conversation_title,
from_me (the user wrote it), author ("Claude" for its replies, None for the user's), text and
files. Like ChatGPT's, the observer reads only the user's side.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from proxenos.store import merge_monthly


def read(export: Path) -> list[dict | None]:
    data = json.loads((export / "conversations.json").read_text(encoding="utf-8"))
    records: list[dict | None] = []
    for c in data if isinstance(data, list) else []:
        if not isinstance(c, dict) or not c.get("uuid"):
            continue
        for m in c.get("chat_messages") or []:
            records.append(_message(c, m) if isinstance(m, dict) else None)
    return [r for r in records if r is not False]


def _message(c: dict, m: dict) -> dict | None | bool:
    """A message as a record, None when it can't be dated, or False when it says nothing."""
    blocks = [b for b in m.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
    text = (
        "\n".join(str(b.get("text") or "") for b in blocks).strip()
        or str(m.get("text") or "").strip()
    )
    files = len(m.get("attachments") or []) + len(m.get("files") or [])
    if not text and not files:
        return False
    ts = _iso(m.get("created_at") or c.get("created_at"))
    if ts is None or not m.get("uuid"):
        return None
    mine = m.get("sender") == "human"
    return {
        "id": f"{c['uuid']}/{m['uuid']}",
        "ts": ts,
        "conversation_id": c["uuid"],
        "conversation_title": c.get("name") or None,
        "from_me": mine,
        "author": None if mine else "Claude",
        "text": text or None,
        "files": files or None,
    }


def _iso(value: object) -> str | None:
    try:
        when = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / "conversations.json").is_file():
        raise SystemExit(f"No conversations.json in {export}: is it an unzipped Claude export?")
    records = read(export)
    stats = merge_monthly([r for r in records if r], vault / "raw" / "claude" / "messages")
    return stats | {"skipped": sum(r is None for r in records)}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export", type=Path, required=True, help="the unzipped Claude export")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())
