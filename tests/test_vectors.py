"""The vector index, with a fake embedding model: words as dimensions. No model, no real data."""

import json

from proxenos import memory, vectors

WORDS = ["revision", "due", "deadline", "dinner", "friday", "paper", "lunch"]


def fake_embed(texts):
    """A vector per text: how often each of WORDS appears, plus one so none is all zero."""
    return [[t.lower().count(w) + 0.01 for w in WORDS] for t in texts]


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def vault_with(tmp_path):
    write_jsonl(
        tmp_path / "raw" / "email" / "me" / "2026-10.jsonl",
        [
            {
                "id": "e1",
                "ts": "2026-10-09T09:00:00Z",
                "subject": "Decision on your paper",
                "from_name": "Journal",
                "body": "The revision is due by 7th Oct.",
            }
        ],
    )
    write_jsonl(
        tmp_path / "raw" / "whatsapp" / "messages" / "2026-10.jsonl",
        [
            {
                "id": f"w{i}",
                "ts": f"2026-10-2{i}T09:00:00Z",
                "chat_id": "ana",
                "chat_name": "Ana",
                "chat_type": "direct",
                "from_me": False,
                "sender_name": "Ana",
                "text": text,
            }
            for i, text in enumerate(["dinner friday?", "or lunch friday"])
        ],
    )
    memory.build(tmp_path)
    return tmp_path


def test_units_are_a_chats_day_or_one_record_and_search_finds_by_meaning(tmp_path):
    vault = vault_with(tmp_path)

    stats = vectors.update(vault, embed=fake_embed)

    assert stats == {"units_embedded": 3, "units_waiting": 0}  # the email, and Ana on two days
    (hit,) = vectors.search(vault, "when is the revision due", limit=1, embed=fake_embed)
    assert (hit["id"], hit["source"]) == ("email/me/e1", "email")
    assert "revision is due" in hit["snippet"] and hit["score"] > 0.5
    ana = vectors.search(vault, "friday dinner", limit=5, who="Ana", embed=fake_embed)
    assert {h["source"] for h in ana} == {"whatsapp"}
    assert vectors.search(vault, "friday", since="2026-10-21", embed=fake_embed)[0]["ts"] >= (
        "2026-10-21"
    )
    assert vectors.update(vault, embed=fake_embed) == {"units_embedded": 0, "units_waiting": 0}


def test_a_run_stops_at_its_time_and_the_next_one_goes_on(tmp_path):
    vault = vault_with(tmp_path)
    vectors.BATCH, saved = 1, vectors.BATCH
    try:
        first = vectors.update(vault, seconds=1e-9, embed=fake_embed)
        rest = vectors.update(vault, embed=fake_embed)
    finally:
        vectors.BATCH = saved
    assert first["units_embedded"] + rest["units_embedded"] == 3
    assert rest["units_waiting"] == 0


def test_without_an_index_or_a_model_search_finds_nothing(tmp_path):
    assert vectors.search(tmp_path, "anything") == []
    assert not vectors.available()  # tests never reach a real model


def test_a_model_that_stops_answering_ends_the_run_and_keeps_what_was_done(tmp_path):
    vault = vault_with(tmp_path)
    calls = []

    def flaky(texts):
        calls.append(texts)
        if len(calls) > 1:
            raise RuntimeError("the embedding model isn't answering")
        return fake_embed(texts)

    vectors.BATCH, saved = 1, vectors.BATCH
    try:
        stats = vectors.update(vault, embed=flaky)
    finally:
        vectors.BATCH = saved
    assert stats == {"units_embedded": 1, "units_waiting": 2}
