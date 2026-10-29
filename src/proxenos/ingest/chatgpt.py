"""ChatGPT conversations, from the data export (Settings, Data controls, Export data).

The export unzips to conversations.json, or conversations-000.json, -001.json and so on in newer
ones: a list of conversations, each with a title, a create_time and a "mapping" of message nodes
by id, each node pointing to its parent. Editing a message branches the tree, so the
conversation as it was left is the branch that ends at current_node, read back to the root;
earlier branches aren't kept. Of its messages, the user's and ChatGPT's text is kept: the parts
that are strings, joined, and how many images a message carried. The model's own thinking
("thoughts", "reasoning_recap"), system messages and tool calls are left out.

Writes vault/raw/chatgpt/messages/, one record per message: id (conversation id / message id),
ts, conversation_id, conversation_title, from_me (the user wrote it), author ("ChatGPT" for its
replies, None for the user's), text, images and model. What the user asks and tells ChatGPT is
their own words, and the observer reads only those, as it reads only their side of a chat.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from proxenos.store import merge_monthly

_SKIPPED_CONTENT = {"thoughts", "reasoning_recap", "user_editable_context"}


def read(export: Path) -> list[dict | None]:
    """Every message on the kept branch of every conversation; None for one with no time."""
    records: list[dict | None] = []
    for path in sorted(export.glob("conversations*.json")):
        conversations = json.loads(path.read_text(encoding="utf-8"))
        for conversation in conversations if isinstance(conversations, list) else []:
            if isinstance(conversation, dict) and isinstance(conversation.get("mapping"), dict):
                records += _conversation(conversation)
    return records


def _conversation(c: dict) -> list[dict | None]:
    mapping, node_id = c["mapping"], c.get("current_node")
    branch = []
    while node_id in mapping and len(branch) <= len(mapping):  # the kept branch, root last
        node = mapping[node_id]
        branch.append(node)
        node_id = node.get("parent")
    conversation_id = str(c.get("conversation_id") or c.get("id") or "")
    found = []
    for node in reversed(branch):
        m = node.get("message")
        if not isinstance(m, dict) or not conversation_id:
            continue
        role = (m.get("author") or {}).get("role")
        content = m.get("content") or {}
        if role not in ("user", "assistant") or content.get("content_type") in _SKIPPED_CONTENT:
            continue
        parts = content.get("parts") or []
        text = "\n".join(p for p in parts if isinstance(p, str) and p.strip()).strip()
        images = sum(isinstance(p, dict) for p in parts)
        if not text and not images:
            continue
        when = m.get("create_time") or c.get("create_time")
        if not isinstance(when, int | float):
            found.append(None)
            continue
        found.append(
            {
                "id": f"{conversation_id}/{m.get('id') or node.get('id')}",
                "ts": _iso(when),
                "conversation_id": conversation_id,
                "conversation_title": c.get("title") or None,
                "from_me": role == "user",
                "author": None if role == "user" else "ChatGPT",
                "text": text or None,
                "images": images or None,
                "model": c.get("default_model_slug") or None,
            }
        )
    return found


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not any(export.glob("conversations*.json")):
        raise SystemExit(f"No conversations*.json in {export}: is it an unzipped ChatGPT export?")
    records = read(export)
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    stats |= merge_monthly(
        [r for r in records if r is not None], vault / "raw" / "chatgpt" / "messages"
    )
    return stats | {"skipped": sum(r is None for r in records)}


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, help="the unzipped ChatGPT export folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())
