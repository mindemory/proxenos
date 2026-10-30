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


def note(folder, name, channel, to, created="2026-03-10T12:00:00Z", status="draft"):
    """A draft with no chat of its own, as a task's or an outreach idea's message is written."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(
        f'---\nid: {name}\ntitle: "Message"\nkind: reply\nfor: task\nchannel: {channel}\n'
        f"to: {json.dumps(to)}\ncreated: {created}\nstatus: {status}\n---\n\nSee you friday\n"
    )


def test_a_draft_with_no_chat_is_handled_once_the_user_wrote_to_that_person_there(tmp_path):
    group = {
        **wa("2026-03-10T12:30:00Z", "in the group", True),
        "chat_id": "g",
        "chat_type": "group",
    }
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [wa("2026-03-10T11:30:00Z", "coming friday?", False), group],
    )
    folder = tmp_path / "clones" / "drafts"
    note(folder, "task-1", "whatsapp", "Asha")
    note(folder, "task-2", "slack", "Asha")  # another channel: not answered there

    # Only a group chat named after her has the user writing since: not her own chat.
    assert fidelity.measure(tmp_path)["drafts_answered"] == 0

    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("2026-03-10T11:30:00Z", "coming friday?", False),
            group,
            wa("2026-03-10T13:00:00Z", "yes", True),
        ],
    )
    assert fidelity.measure(tmp_path) == {"drafts_measured": 1, "drafts_answered": 1}
    assert "status: sent" in (folder / "task-1.md").read_text()
    assert "status: draft" in (folder / "task-2.md").read_text()


def test_slack_direct_messages_and_emails_are_matched_by_name_and_address(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_EMAILS", "me@example.org")

    def slack(ts, text, mine, channel="D1", kind="dm", thread=None):
        return {
            "id": ts,
            "ts": ts,
            "slack_ts": ts,
            "thread_ts": thread,
            "channel_id": channel,
            "channel_name": "Ben Ng" if kind == "dm" else "general",
            "channel_type": kind,
            "user_id": "U0" if mine else "U1",
            "user_name": "Me" if mine else "Ben Ng",
            "from_me": mine,
            "text": text,
        }

    write_jsonl(
        tmp_path / "raw" / "slack" / "lab" / "messages" / "2026-03.jsonl",
        [
            slack("2026-03-10T11:00:00Z", "draft ready?", False),
            slack("2026-03-10T12:30:00Z", "in a thread", True, "C1", "channel", "1"),
            slack("2026-03-10T13:00:00Z", "sending it tonight", True),
        ],
    )
    email = {
        "id": "e1",
        "ts": "2026-03-10T14:00:00Z",
        "from_me": True,
        "from_address": "me@example.org",
        "to": ["Dee Roy <dee@clinic.org>"],
        "subject": "Bill",
        "body": "About the bill",
    }
    write_jsonl(tmp_path / "raw" / "email" / "me" / "2026-03.jsonl", [email])
    folder = tmp_path / "clones" / "drafts"
    note(folder, "task-1", "slack", "Ben  Ng")
    note(folder, "care-1", "email", "Dee Roy <DEE@clinic.org>")
    note(folder, "care-2", "email", "Dee Roy")  # no address to match by

    assert fidelity.measure(tmp_path)["drafts_answered"] == 2
    assert "status: sent" in (folder / "task-1.md").read_text()
    assert "status: sent" in (folder / "care-1.md").read_text()
    assert "status: draft" in (folder / "care-2.md").read_text()
