"""How close reply drafts came to what was sent, on a synthetic vault. No model, no real data."""

import json

from proxenos import fidelity


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def wa(ts, text, mine):
    return {
        "id": ts,
        "ts": ts,
        "chat_id": "asha",
        "chat_name": "Asha",
        "chat_type": "direct",
        "from_me": mine,
        "sender_name": None if mine else "Asha",
        "text": text,
    }


def draft(folder, name, body, created="2026-03-10T12:00:00Z", chat="asha", status="sent"):
    folder.mkdir(parents=True, exist_ok=True)
    thread = json.dumps({"source": "whatsapp", "chat": chat})
    (folder / f"{name}.md").write_text(
        f'---\nid: {name}\ntitle: "Reply"\nkind: reply\nfor: reply\nchannel: whatsapp\nto: "Asha"\n'
        f"created: {created}\nstatus: {status}\nthread: {thread}\n---\n\n{body}\n"
    )


def test_a_draft_is_compared_with_what_was_sent_in_its_chat_after_it(tmp_path):
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("2026-03-10T11:00:00Z", "earlier, not this", True),
            wa("2026-03-10T11:30:00Z", "coming friday?", False),
            wa("2026-03-10T12:05:00Z", "yaa coming", True),
            wa("2026-03-10T12:06:00Z", "see you friday", True),
            wa("2026-03-10T15:00:00Z", "much later, another burst", True),
        ],
    )
    folder = tmp_path / "clones" / "drafts"
    draft(folder, "reply-1", "yaa coming\nsee you friday")
    draft(folder, "reply-2", "Unsent so far", created="2026-03-10T16:00:00Z")
    draft(folder, "reply-3", "Another chat", chat="ben")

    assert fidelity.measure(tmp_path) == {"drafts_measured": 1, "drafts_answered": 0}

    data = json.loads((folder / "fidelity.json").read_text())
    (m,) = data["drafts"]
    assert (m["id"], m["source"], m["to"], m["sent"]) == (
        "reply-1",
        "whatsapp",
        "Asha",
        "2026-03-10T12:05:00Z",
    )
    assert m["closeness"] == 1.0  # sent as written, over two messages
    assert data["by_source"] == {"whatsapp": {"n": 1, "mean": 1.0}}


def test_a_draft_still_waiting_is_marked_sent_once_its_chat_was_answered(tmp_path):
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("2026-03-10T11:30:00Z", "coming friday?", False),
            wa("2026-03-10T12:05:00Z", "yes!", True),
        ],
    )
    folder = tmp_path / "clones" / "drafts"
    draft(folder, "reply-1", "yaa coming", status="approved")
    draft(folder, "reply-2", "Not answered yet", created="2026-03-10T16:00:00Z", status="draft")

    assert fidelity.measure(tmp_path)["drafts_answered"] == 1
    assert "status: sent" in (folder / "reply-1.md").read_text()
    assert "status: draft" in (folder / "reply-2.md").read_text()


def test_closeness_falls_as_the_draft_is_rewritten():
    sent = [{"text": "sorry can't make it friday"}]
    assert fidelity._closeness("sorry can't make it friday", sent) == 1.0
    assert fidelity._closeness("Sorry, can't make it on Friday!", sent) > 0.8
    assert fidelity._closeness("Let's do lunch next week instead", sent) < 0.5
