"""Chrome ingester against a synthetic Takeout History.json. No real data lives in this repo."""

import json
from datetime import UTC, datetime

import pytest

from twin.ingest import chrome


def micros(*args):
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1_000_000)


HISTORY = {
    "Browser History": [
        {
            "favicon_url": "https://example.com/favicon.ico",
            "page_transition_qualifier": "CLIENT_REDIRECT",
            "title": "Example — Home",
            "url": "https://example.com/",
            "time_usec": micros(2025, 1, 31, 23, 59, 59) + 123,
            "client_id": "abc==",
        },
        {"title": "", "url": "https://example.com/redirect", "time_usec": micros(2025, 2, 1)},
        {"url": "https://example.com/download", "time_usec": micros(2025, 2, 1)},
        {"title": "Docs", "url": "https://docs.example.com/a", "time_usec": micros(2025, 2, 2)},
        {"title": "No time", "url": "https://example.com/x"},
        {"title": "No url", "time_usec": micros(2025, 2, 3)},
    ],
    "Session": [],
}


def make_export(root):
    chrome_dir = root / "Takeout" / "Chrome"
    chrome_dir.mkdir(parents=True)
    (chrome_dir / "History.json").write_text(json.dumps(HISTORY))
    (chrome_dir / "Bookmarks.html").write_text("<html></html>")
    return chrome_dir


def test_titled_visits_are_kept_with_their_time(tmp_path):
    records = chrome.read_visits(make_export(tmp_path / "e"))
    assert records.count(None) == 2  # no time, and no url
    home, docs = [r for r in records if r]
    assert (home["ts"], home["url"], home["title"]) == (
        "2025-01-31T23:59:59Z",
        "https://example.com/",
        "Example — Home",
    )
    assert set(home) == {"id", "ts", "url", "title"}
    assert docs["ts"] == "2025-02-02T00:00:00Z"
    assert home["id"] != docs["id"]


def test_ingest_merges_by_id(tmp_path):
    vault = tmp_path / "vault"
    export = make_export(tmp_path / "e")
    stats = chrome.ingest(vault, export)
    assert (stats["added"], stats["months_written"], stats["skipped"]) == (2, 2, 2)
    again = chrome.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        chrome.ingest(vault, tmp_path / "empty")
