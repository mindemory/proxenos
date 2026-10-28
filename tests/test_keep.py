"""Keep ingester against synthetic Takeout notes. No real data lives here."""

import json

from twin.ingest import keep

# 2024-03-05T12:00:00Z, and a day before it, in microseconds.
EDITED = 1709640000_123456
CREATED = 1709553600_000000


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def note(**extra):
    data = {
        "color": "DEFAULT",
        "isTrashed": False,
        "isPinned": False,
        "isArchived": False,
        "textContent": "Remember the thing",
        "title": "A title",
        "userEditedTimestampUsec": EDITED,
        "createdTimestampUsec": CREATED,
    }
    return {**data, **extra}


def make_keep(root):
    folder = root / "Keep"
    put(
        folder / "Weekend Plan.json",
        note(
            title="Weekend Plan",
            isPinned=True,
            color="BLUE",
            labels=[{"name": "personal"}, {"name": "ideas"}],
        ),
    )
    put(
        folder / "Groceries.json",
        note(
            title="Groceries",
            isArchived=True,
            textContent=None,
            listContent=[
                {"text": "milk", "isChecked": False},
                {"text": "", "isChecked": False},
                {"text": "eggs", "isChecked": True},
            ],
        ),
    )
    stem = "2024-01-08T14_41_00.745-05_00"
    put(
        folder / f"{stem}.json",
        note(title="", userEditedTimestampUsec=0, textContent="Untitled thought"),
    )
    put(folder / "Old.json", note(title="Old", isTrashed=True))
    put(folder / "Weekend Plan.html", "<html>the same note as html</html>")
    put(folder / "Labels.txt", "personal\nideas\n")
    return folder


def by_id(records):
    return {r["id"]: r for r in records if r is not None}


def test_notes_keep_their_text_labels_and_flags(tmp_path):
    records = by_id(keep.read_notes(make_keep(tmp_path)))

    assert records["Weekend Plan"] == {
        "id": "Weekend Plan",
        "ts": "2024-03-05T12:00:00Z",
        "from_me": True,
        "title": "Weekend Plan",
        "text": "Remember the thing",
        "labels": ["personal", "ideas"],
        "archived": False,
        "trashed": False,
        "pinned": True,
        "color": "BLUE",
    }
    groceries = records["Groceries"]
    assert groceries["text"] == "milk\neggs"  # a checklist's items, without the empty one
    assert groceries["archived"] is True
    assert groceries["labels"] == []


def test_an_untitled_note_takes_its_created_time_and_trashed_notes_are_left_out(tmp_path):
    records = keep.read_notes(make_keep(tmp_path))
    assert None not in records
    found = by_id(records)
    assert sorted(found) == ["2024-01-08T14_41_00.745-05_00", "Groceries", "Weekend Plan"]
    untitled = found["2024-01-08T14_41_00.745-05_00"]
    assert untitled["title"] is None
    assert untitled["ts"] == "2024-03-04T12:00:00Z"


def test_bad_notes_are_skipped_not_fatal(tmp_path):
    folder = make_keep(tmp_path)
    put(folder / "broken.json", "{not json")
    put(folder / "list.json", [1, 2])
    no_time = note()
    del no_time["userEditedTimestampUsec"], no_time["createdTimestampUsec"]
    put(folder / "no-time.json", no_time)
    put(folder / "bad-time.json", note(userEditedTimestampUsec="soon"))
    records = keep.read_notes(folder)
    assert records.count(None) == 4
    assert len([r for r in records if r]) == 3


def test_ingest_writes_the_notes_stream_and_reruns_are_no_ops(tmp_path):
    folder = make_keep(tmp_path)
    put(folder / "broken.json", "{not json")
    vault = tmp_path / "vault"

    first = keep.ingest(vault, folder)
    assert first == {"read": 3, "added": 3, "updated": 0, "months_written": 1, "skipped": 1}
    raw = vault / "raw" / "keep" / "notes"
    assert [p.name for p in raw.iterdir()] == ["2024-03.jsonl"]
    records = [json.loads(line) for line in (raw / "2024-03.jsonl").read_text().splitlines()]
    assert len(records) == 3 and all(r["ts"].endswith("Z") for r in records)

    again = keep.ingest(vault, folder)
    assert again["added"] == 0 and again["updated"] == 0 and again["months_written"] == 0

    put(folder / "Weekend Plan.json", note(title="Weekend Plan", textContent="Changed my mind"))
    changed = keep.ingest(vault, folder)
    assert changed["updated"] == 1 and changed["added"] == 0


def test_a_missing_folder_is_an_error(tmp_path):
    try:
        keep.ingest(tmp_path / "vault", tmp_path / "nowhere")
    except FileNotFoundError as e:
        assert "nowhere" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")
