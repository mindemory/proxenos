"""How close the twin's replies came to what the user sent.

Every reply draft records its chat. Once the user has written in that chat after the draft
(within WINDOW), their first messages there (those within BURST of the first) are what they
sent, and closeness is how much of the draft's text survived into it: 1.0 sent as written, near
0.0 rewritten or about something else. Case, spacing and line breaks don't count. It doesn't
matter whether they sent it from the page or typed their own; either way it says how near the
twin got.

Written to clones/drafts/fidelity.json: each measured draft {id, source, to, drafted, sent,
closeness} and, per source, how many and their mean. That's the measure that should decide when a
kind of reply can go out without asking (docs/memory.md). No model; nothing leaves the vault.
"""

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from proxenos import chats
from proxenos.clones import work

WINDOW = timedelta(days=3)
BURST = timedelta(minutes=15)


def measure(vault: Path) -> dict[str, int]:
    folder = vault / "clones" / "drafts"
    wanted: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        front = work._FRONT.match(text)
        fields = work._front(text) or {}
        thread = _json(fields.get("thread"))
        if front and isinstance(thread, dict) and fields.get("created"):
            body = text[front.end() :]
            wanted[thread.get("source"), thread.get("chat")].append(fields | {"body": body})

    measured = []
    for source, key, messages, *_ in chats.conversations(vault):
        for draft in wanted.get((source, key), []):
            if sent := _sent(messages, draft["created"]):
                measured.append(
                    {
                        "id": draft.get("id"),
                        "source": source,
                        "to": _json(draft.get("to")) or draft.get("to"),
                        "drafted": draft["created"],
                        "sent": sent[0]["ts"],
                        "closeness": round(_closeness(draft["body"], sent), 2),
                    }
                )
    measured.sort(key=lambda m: m["sent"], reverse=True)
    by_source: dict[str, list[float]] = defaultdict(list)
    for m in measured:
        by_source[m["source"]].append(m["closeness"])
    summary = {s: {"n": len(v), "mean": round(sum(v) / len(v), 2)} for s, v in by_source.items()}
    out = {"generated": _now(), "by_source": summary, "drafts": measured}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "fidelity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return {"drafts_measured": len(measured)}


def _sent(messages: list[dict], drafted: str) -> list[dict]:
    """The user's first messages in the chat after the draft: those within BURST of the first."""
    start = datetime.fromisoformat(drafted)
    after = sorted(
        (m for m in messages if m["mine"] and m["text"] and m["ts"] > drafted),
        key=lambda m: m["ts"],
    )
    after = [m for m in after if datetime.fromisoformat(m["ts"]) <= start + WINDOW]
    if not after:
        return []
    first = datetime.fromisoformat(after[0]["ts"])
    return [m for m in after if datetime.fromisoformat(m["ts"]) <= first + BURST]


def _closeness(draft: str, sent: list[dict]) -> float:
    return SequenceMatcher(None, _plain(draft), _plain(" ".join(m["text"] for m in sent))).ratio()


def _plain(text: str) -> str:
    """Words only, lower case: a line break, a " / " between lines or extra spaces don't count."""
    return " ".join(re.sub(r"\s+/\s+", " ", text).lower().split())


def _json(value: object) -> object:
    try:
        return json.loads(str(value))
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
