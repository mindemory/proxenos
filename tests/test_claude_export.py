"""claude.ai's data export, as a synthetic conversations.json. No real data."""

import json

from proxenos import importer
from proxenos.ingest import claude


def test_conversations_become_messages_and_the_export_is_recognized(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    conversation = {
        "uuid": "c1",
        "name": "Memory design",
        "created_at": "2026-10-28T20:00:00Z",
        "chat_messages": [
            {
                "uuid": "m1",
                "sender": "human",
                "created_at": "2026-10-28T20:00:00.123Z",
                "text": "how should memory decay?",
                "attachments": [{"file_name": "a.pdf"}],
            },
            {
                "uuid": "m2",
                "sender": "assistant",
                "created_at": "2026-10-28T20:00:05Z",
                "content": [
                    {"type": "thinking", "thinking": "hmm"},
                    {"type": "text", "text": "By surprise and recency."},
                ],
            },
            {
                "uuid": "m3",
                "sender": "assistant",
                "created_at": "2026-10-28T20:00:06Z",
                "content": [{"type": "tool_use"}],
            },
        ],
    }
    (folder / "conversations.json").write_text(json.dumps([conversation]))
    (folder / "users.json").write_text("[]")

    stats = claude.ingest(tmp_path / "vault", folder)

    out = tmp_path / "vault" / "raw" / "claude" / "messages"
    asked, answered = [
        json.loads(line) for f in sorted(out.glob("*.jsonl")) for line in f.read_text().splitlines()
    ]
    assert (asked["id"], asked["from_me"], asked["files"], asked["ts"]) == (
        "c1/m1",
        True,
        1,
        "2026-10-28T20:00:00Z",
    )
    assert (answered["author"], answered["text"]) == ("Claude", "By surprise and recency.")
    assert stats["added"] == 2
    assert ("claude", ["--export", str(folder)]) in importer.jobs_for(tmp_path)
