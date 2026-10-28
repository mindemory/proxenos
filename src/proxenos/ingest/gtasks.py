"""Google Tasks from Google Takeout.

Reads Tasks.json in Takeout's Tasks folder and writes one stream into vault/raw/gtasks/: tasks.
Every export is a full snapshot, so each run re-reads one and merges by id. The same task in
several exports is one record.

A task has list (the title of the task list it's in), title, notes, status ("needsAction" or
"completed"), due, completed and from_me, always true since the user wrote them. due and completed
are UTC times; due is the task's due date, else the first time Google scheduled it for. ts is when
the task was last updated, else its due time. The id is Google's id for the task.

A task without an id, or without a time that parses, is counted as skipped, and so is a list
that isn't laid out as Takeout writes them.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly


def read_tasks(export: Path) -> list[dict | None]:
    """Every task of every list. None marks a file, list or task that couldn't be read."""
    path = export / "Tasks.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lists = data["items"]
        if not isinstance(lists, list):
            return [None]
    except (OSError, ValueError, KeyError, TypeError):
        return [None]
    records: list[dict | None] = []
    for task_list in lists:
        if not isinstance(task_list, dict):
            records.append(None)
            continue
        title = task_list.get("title")
        for task in task_list.get("items") or []:
            records.append(_parse(task, title))
    return records


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not (export / "Tasks.json").is_file():
        raise FileNotFoundError(f"no Tasks.json in {export}")
    return _merge({"tasks": read_tasks(export)}, vault / "raw" / "gtasks")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="Takeout's Tasks folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: a task in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _parse(task: Any, list_title: Any) -> dict | None:
    if not isinstance(task, dict):
        return None
    try:
        due = _when(task.get("due") or _scheduled(task))
        ts = _when(task.get("updated")) or due
        if not task["id"] or ts is None:
            return None
        completed = _when(task.get("completed"))
        return {
            "id": str(task["id"]),
            "ts": _stamp(ts),
            "from_me": True,
            "list": list_title or None,
            "title": str(task.get("title") or ""),
            "notes": task.get("notes") or None,
            "status": task.get("status") or None,
            "due": _stamp(due) if due else None,
            "completed": _stamp(completed) if completed else None,
        }
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def _scheduled(task: dict) -> str | None:
    """The first time a task was scheduled for, in Google's newer layout, which has no due."""
    for slot in task.get("scheduled_time") or []:
        if isinstance(slot, dict) and slot.get("start"):
            return slot["start"]
    return None


def _when(text: Any) -> datetime | None:
    """An RFC 3339 time as UTC; None when there isn't one."""
    if not text:
        return None
    when = datetime.fromisoformat(str(text))
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
