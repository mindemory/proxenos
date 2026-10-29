"""Beeper Desktop's local API, against a fake one in memory. No network, no real chats."""

import json
from datetime import UTC, datetime

from proxenos.ingest import beeper

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def fake_api(chats, messages):
    """GET paths → pages: chats newest first in one page, each chat's messages in pages of two."""
    calls = []

    def fetch(path):
        calls.append(path)
        if path.startswith("/v1/chats?"):
            return {"items": chats, "hasMore": False}
        chat_id = path.split("/")[3]
        items = messages[chat_id]
        older = "cursor=" in path
        page = items[:-2] if older else items[-2:]
        return {"items": page, "hasMore": not older and len(items) > 2, "oldestCursor": "c1"}

    return fetch, calls


def msg(i, ts, text, mine=False, **extra):
    return {
        "id": f"m{i}",
        "timestamp": ts,
        "text": text,
        "isSender": mine,
        "senderName": None if mine else "Ana",
    } | extra


CHATS = [
    {
        "id": "ig1",
        "network": "Instagram",
        "title": "Ana",
        "type": "single",
        "lastActivity": "2026-03-09T09:00:00.000Z",
    },
    {
        "id": "wa1",
        "network": "WhatsApp",
        "title": "Ben",
        "type": "single",
        "lastActivity": "2026-03-09T08:00:00Z",
    },
    {
        "id": "fb1",
        "network": "Facebook Messenger",
        "title": "Crew",
        "type": "group",
        "lastActivity": "2026-03-08T08:00:00Z",
    },
    {
        "id": "li1",
        "network": "LinkedIn",
        "title": "Dee",
        "type": "single",
        "lastActivity": "2025-01-01T00:00:00Z",
    },
]
MESSAGES = {
    "ig1": [
        msg(1, "2026-03-01T09:00:00Z", "haha yes", mine=True),
        msg(2, "2026-03-02T09:00:00Z", "deleted", isDeleted=True),
        msg(3, "2026-03-09T08:59:00Z", "👍", type="REACTION"),
        msg(
            4,
            "2026-03-09T09:00:00Z",
            "coming sat?",
            links=[{"url": "https://x.org/a", "title": "a"}],
        ),
    ],
    "fb1": [msg(5, "2026-03-08T08:00:00Z", "who's in?")],
}


def stored(vault, source):
    rows = []
    for f in sorted((vault / "raw" / source / "messages").glob("*.jsonl")):
        rows += [json.loads(line) for line in f.read_text().splitlines()]
    return rows


def test_reads_meta_chats_into_their_sources_and_leaves_the_rest(tmp_path):
    fetch, calls = fake_api(CHATS, MESSAGES)

    stats = beeper.ingest(tmp_path, fetch, NOW)

    ig = stored(tmp_path, "instagram")
    assert [r["text"] for r in ig] == ["haha yes", "coming sat?"]  # older page read too
    assert (ig[1]["chat_id"], ig[1]["link"]) == ("beeper:ig1", "https://x.org/a")
    assert ig[0]["from_me"] and ig[1]["author"] == "Ana" and ig[1]["chat_type"] == "direct"
    assert stored(tmp_path, "facebook")[0]["chat_type"] == "group"
    assert not any("/wa1/" in c for c in calls)  # WhatsApp is read directly, not through Beeper
    assert not any("/li1/" in c for c in calls)  # quiet since before the first run's window
    assert stats["chats_read"] == 2 and stats["chats_skipped"] == 1


def test_a_later_run_reads_only_whats_new(tmp_path):
    fetch, calls = fake_api(CHATS, MESSAGES)
    beeper.ingest(tmp_path, fetch, NOW)
    calls.clear()

    later = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
    stats = beeper.ingest(tmp_path, fetch, later)

    assert calls == ["/v1/chats?limit=200"]  # nothing active since the last run
    assert stats == {}


def test_linkedin_comes_in_as_a_linkedin_conversation(tmp_path):
    chats = [CHATS[3] | {"lastActivity": "2026-03-09T09:00:00Z"}]
    fetch, _ = fake_api(chats, {"li1": [msg(6, "2026-03-09T09:00:00Z", "can we chat?")]})

    beeper.ingest(tmp_path, fetch, NOW)

    (row,) = stored(tmp_path, "linkedin")
    assert (row["conversation_id"], row["conversation_title"], row["folder"]) == (
        "beeper:li1",
        "Dee",
        "INBOX",
    )
