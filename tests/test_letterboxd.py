"""Letterboxd ingester against a synthetic export. No real data lives in this repo."""

import json

import pytest

from twin.ingest import letterboxd

FILES = {
    "diary.csv": (
        "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
        '2024-03-06,Example Film,1999,https://boxd.it/aaa1,4.5,Yes,"cozy, rainy day",2024-03-05\n'
        "2024-04-01,Other Film,2010,https://boxd.it/aaa2,,,,2024-03-31\n"
        "2024-04-02,Bad Date,2011,https://boxd.it/aaa3,3,,,yesterday\n"
    ),
    "watched.csv": (
        "Date,Name,Year,Letterboxd URI\n"
        "2024-03-06,Example Film,1999,https://boxd.it/film1\n"
        "2024-03-07,,2000,https://boxd.it/film2\n"
    ),
    "ratings.csv": "Date,Name,Year,Letterboxd URI,Rating\n2024-03-06,Example Film,1999,,4.5\n",
    "reviews.csv": (
        "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Review,Tags,Watched Date\n"
        '2024-03-06,Example Film,1999,https://boxd.it/rev1,4.5,Yes,"Loved it, café scene ☕",,'
        "2024-03-05\n"
    ),
    "likes/films.csv": "Date,Name,Year,Letterboxd URI\n2024-05-01,Liked Film,2001,https://boxd.it/f3\n",
    "deleted/diary.csv": (
        "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
        "2024-01-01,Deleted Film,1990,https://boxd.it/del1,1,,,2024-01-01\n"
    ),
}


def make_export(root):
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def stream(vault, name):
    out = vault / "raw" / "letterboxd" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def test_diary_rows_are_dated_when_watched_and_keep_rating_rewatch_and_tags(tmp_path):
    records = letterboxd.read_stream(make_export(tmp_path / "e"), "diary")
    assert records.count(None) == 1  # the unparseable watched date
    first, second = [r for r in records if r]
    assert first == {
        "id": "https://boxd.it/aaa1",
        "ts": "2024-03-05T00:00:00Z",
        "title": "Example Film",
        "year": 1999,
        "rating": 4.5,
        "rewatch": True,
        "tags": ["cozy", "rainy day"],
        "text": None,
        "url": "https://boxd.it/aaa1",
    }
    assert (second["ts"], second["rating"], second["rewatch"], second["tags"]) == (
        "2024-03-31T00:00:00Z",
        None,
        False,
        None,
    )


def test_other_files_have_none_for_columns_they_lack(tmp_path):
    export = make_export(tmp_path / "e")
    watched = letterboxd.read_stream(export, "watched")
    assert watched[1] is None  # no film name
    assert (watched[0]["rewatch"], watched[0]["tags"], watched[0]["rating"]) == (None, None, None)

    (rating,) = letterboxd.read_stream(export, "ratings")
    assert (rating["rating"], rating["url"], len(rating["id"])) == (4.5, None, 16)
    (review,) = letterboxd.read_stream(export, "reviews")
    assert review["text"] == "Loved it, café scene ☕"
    assert letterboxd.read_stream(export, "watchlist") == []


def test_ingest_writes_each_stream_and_skips_deleted_entries(tmp_path):
    vault = tmp_path / "vault"
    export = make_export(tmp_path / "e")
    stats = letterboxd.ingest(vault, export)
    assert (stats["added"], stats["skipped"]) == (6, 2)
    assert [r["title"] for r in stream(vault, "likes")] == ["Liked Film"]
    assert "Deleted Film" not in {r["title"] for r in stream(vault, "diary")}

    again = letterboxd.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)

    with pytest.raises(FileNotFoundError):
        letterboxd.ingest(vault, tmp_path)
