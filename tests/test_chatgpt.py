"""ChatGPT's data export, as synthetic files in its layout. No real data."""

import json

from proxenos import importer
from proxenos.ingest import chatgpt


def node(nid, parent, role, parts, t, kind="text"):
    message = {
        "id": nid,
        "author": {"role": role},
        "create_time": t,
        "content": {"content_type": kind, "parts": parts},
    }
    return nid, {"id": nid, "parent": parent, "message": message}


def export(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    mapping = dict(
        [
            ("root", {"id": "root", "parent": None, "message": None}),
            node("a", "root", "user", ["first try"], 1767225600),
            node(
                "b", "root", "user", ["what should I read on memory?", {"asset": "img"}], 1767225660
            ),
            node("c", "b", "assistant", ["Thinking..."], 1767225670, kind="thoughts"),
            node("d", "c", "assistant", ["Try the Titans paper."], 1767225680),
            node("s", "d", "system", ["You are ChatGPT"], 1767225690),
        ]
    )
    conversation = {
        "conversation_id": "conv1",
        "title": "Memory reading",
        "current_node": "s",
        "create_time": 1767225600,
        "default_model_slug": "gpt-x",
        "mapping": mapping,
    }
    (folder / "conversations-000.json").write_text(json.dumps([conversation]))
    (folder / "chat.html").write_text("<html></html>")
    return folder


def test_the_kept_branch_of_each_conversation_becomes_messages(tmp_path):
    folder = export(tmp_path)

    stats = chatgpt.ingest(tmp_path / "vault", folder)

    rows = [
        json.loads(line)
        for f in sorted((tmp_path / "vault" / "raw" / "chatgpt" / "messages").glob("*.jsonl"))
        for line in f.read_text().splitlines()
    ]
    assert [r["text"] for r in rows] == ["what should I read on memory?", "Try the Titans paper."]
    asked, answered = rows
    assert (asked["from_me"], asked["author"], asked["images"]) == (True, None, 1)
    assert (answered["from_me"], answered["author"]) == (False, "ChatGPT")
    assert asked["id"] == "conv1/b" and asked["conversation_title"] == "Memory reading"
    assert asked["ts"] == "2026-01-01T00:01:00Z" and stats["added"] == 2
    assert chatgpt.ingest(tmp_path / "vault", folder)["added"] == 0  # read again: nothing new


def test_a_chatgpt_download_is_recognized(tmp_path):
    folder = export(tmp_path)
    assert ("chatgpt", ["--export", str(folder)]) in importer.jobs_for(tmp_path)
