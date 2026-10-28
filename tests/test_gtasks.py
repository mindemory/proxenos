"""Google Tasks ingester against a synthetic Takeout Tasks.json. No real data lives here."""

import json

from twin.ingest import gtasks


def make_tasks(root):
    folder = root / "Tasks"
    folder.mkdir(parents=True)
    data = {
        "kind": "tasks#taskLists",
        "items": [
            {
                "kind": "tasks#taskList",
                "id": "list1",
                "title": "Errands",
                "updated": "2024-03-01T00:00:00.000Z",
                "items": [
                    {
                        "id": "t1",
                        "title": "Buy stamps",
                        "notes": "At the post office",
                        "status": "completed",
                        "due": "2024-03-04T00:00:00.000Z",
                        "completed": "2024-03-04T15:30:00.123456Z",
                        "updated": "2024-03-04T15:30:01.000Z",
                    },
                    {
                        "id": "t2",
                        "title": "Call back",
                        "status": "needsAction",
                        "updated": "2024-02-10T09:00:00.500000Z",
                    },
                    {
                        # Newer exports schedule a task instead of giving it a due date.
                        "id": "t3",
                        "title": "Water plants",
                        "status": "needsAction",
                        "scheduled_time": [{"current": True, "start": "2024-04-01T04:00:00Z"}],
                        "updated": "2024-02-11T09:00:00Z",
                    },
                    {"id": "t4", "title": "Only due", "due": "2024-05-06T00:00:00Z"},
                ],
            },
            {
                "kind": "tasks#taskList",
                "id": "list2",
                "title": "Empty list",
                "updated": "2024-01-01T00:00:00Z",
            },
            {
                "kind": "tasks#taskList",
                "id": "list3",
                "title": "Reading",
                "items": [{"id": "t5", "title": "A paper", "updated": "2023-12-31T23:59:59-05:00"}],
            },
        ],
    }
    (folder / "Tasks.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def by_id(records):
    return {r["id"]: r for r in records if r is not None}


def test_every_task_of_every_list_is_a_record(tmp_path):
    records = by_id(gtasks.read_tasks(make_tasks(tmp_path)))
    assert sorted(records) == ["t1", "t2", "t3", "t4", "t5"]

    assert records["t1"] == {
        "id": "t1",
        "ts": "2024-03-04T15:30:01Z",
        "from_me": True,
        "list": "Errands",
        "title": "Buy stamps",
        "notes": "At the post office",
        "status": "completed",
        "due": "2024-03-04T00:00:00Z",
        "completed": "2024-03-04T15:30:00Z",
    }
    assert records["t2"]["due"] is None and records["t2"]["completed"] is None
    assert records["t2"]["notes"] is None
    assert records["t2"]["ts"] == "2024-02-10T09:00:00Z"
    assert records["t3"]["due"] == "2024-04-01T04:00:00Z"
    # No update time: the due time is the timestamp.
    assert records["t4"]["ts"] == "2024-05-06T00:00:00Z"
    assert records["t4"]["status"] is None
    # Times with an offset are converted to UTC.
    assert records["t5"]["ts"] == "2024-01-01T04:59:59Z"
    assert records["t5"]["list"] == "Reading"
    assert all(r["from_me"] is True for r in records.values())


def test_bad_tasks_are_skipped_not_fatal(tmp_path):
    folder = make_tasks(tmp_path)
    data = json.loads((folder / "Tasks.json").read_text())
    data["items"][0]["items"] += [
        {"title": "No id", "updated": "2024-03-01T00:00:00Z"},
        {"id": "t6", "title": "No time at all"},
        {"id": "t7", "title": "Bad time", "updated": "yesterday"},
        "not a task",
    ]
    data["items"].append("not a list")
    (folder / "Tasks.json").write_text(json.dumps(data))
    records = gtasks.read_tasks(folder)
    assert records.count(None) == 5
    assert len(by_id(records)) == 5


def test_a_file_that_is_not_json_is_one_skipped_entry(tmp_path):
    folder = tmp_path / "Tasks"
    folder.mkdir()
    (folder / "Tasks.json").write_text("{nope")
    assert gtasks.read_tasks(folder) == [None]


def test_ingest_writes_the_tasks_stream_and_reruns_are_no_ops(tmp_path):
    folder = make_tasks(tmp_path)
    vault = tmp_path / "vault"

    first = gtasks.ingest(vault, folder)
    assert first == {"read": 5, "added": 5, "updated": 0, "months_written": 4, "skipped": 0}
    raw = vault / "raw" / "gtasks" / "tasks"
    assert sorted(p.name for p in raw.iterdir()) == [
        "2024-01.jsonl",
        "2024-02.jsonl",
        "2024-03.jsonl",
        "2024-05.jsonl",
    ]
    records = [json.loads(line) for p in raw.iterdir() for line in p.read_text().splitlines()]
    assert len(records) == 5 and all(r["ts"].endswith("Z") for r in records)

    again = gtasks.ingest(vault, folder)
    assert again["added"] == 0 and again["updated"] == 0 and again["months_written"] == 0


def test_a_folder_without_tasks_json_is_an_error(tmp_path):
    (tmp_path / "Tasks").mkdir()
    try:
        gtasks.ingest(tmp_path / "vault", tmp_path / "Tasks")
    except FileNotFoundError as e:
        assert "Tasks.json" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")
