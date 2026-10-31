"""Letterboxd ingester against a synthetic export. No real data lives in this repo."""

import argparse
import json

import pytest

from proxenos.ingest import letterboxd

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


FEED = b"""<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0" xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org">
<channel><title>Letterboxd - Tess</title>
<item><title>Example Film, 1999 - 4.5</title>
 <link>https://letterboxd.com/tess/film/example-film/</link>
 <guid isPermaLink="false">letterboxd-watch-11</guid>
 <pubDate>Fri, 30 Oct 2026 15:44:17 +1300</pubDate>
 <letterboxd:watchedDate>2026-10-29</letterboxd:watchedDate>
 <letterboxd:rewatch>No</letterboxd:rewatch>
 <letterboxd:filmTitle>Example Film</letterboxd:filmTitle>
 <letterboxd:filmYear>1999</letterboxd:filmYear>
 <letterboxd:memberRating>4.5</letterboxd:memberRating>
 <letterboxd:memberLike>Yes</letterboxd:memberLike>
 <tmdb:movieId>101</tmdb:movieId>
 <description><![CDATA[ <p><img src="https://a.example/poster.jpg"/></p>
  <p>This review may contain spoilers.</p> <p>The caf&eacute; scene &amp; the rain.</p>
  <p>Watched on Thursday October 29, 2026.</p> ]]></description></item>
<item><title>A Miniseries, 2020</title>
 <guid isPermaLink="false">letterboxd-watch-12</guid>
 <pubDate>Sat, 24 Oct 2026 05:29:29 +0000</pubDate>
 <letterboxd:rewatch>Yes</letterboxd:rewatch>
 <letterboxd:filmTitle>A Miniseries</letterboxd:filmTitle>
 <letterboxd:filmYear>2020</letterboxd:filmYear>
 <tmdb:tvId>202</tmdb:tvId>
 <description><![CDATA[ <p>Watched on Saturday October 24, 2026.</p> ]]></description></item>
<item><title>Broken, year</title>
 <guid isPermaLink="false">letterboxd-watch-13</guid>
 <letterboxd:watchedDate>2026-10-20</letterboxd:watchedDate>
 <letterboxd:filmTitle>Broken</letterboxd:filmTitle>
 <letterboxd:filmYear>soon</letterboxd:filmYear></item>
<item><title>Films for a rainy day</title>
 <guid isPermaLink="false">letterboxd-list-14</guid>
 <pubDate>Fri, 23 Oct 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_the_public_feed_brings_in_films_logged_since_the_export(tmp_path):
    asked = []

    def fetch(url):
        asked.append(url)
        return FEED

    film, show, broken = letterboxd.read_feed("@tess", fetch)
    assert asked == ["https://letterboxd.com/tess/rss/"]
    assert film == {
        "id": "letterboxd-watch-11",
        "ts": "2026-10-29T00:00:00Z",
        "title": "Example Film",
        "year": 1999,
        "rating": 4.5,
        "rewatch": False,
        "liked": True,
        "tags": None,
        "text": "The café scene & the rain.",
        "url": "https://letterboxd.com/tess/film/example-film/",
        "tmdb": "movie/101",
    }
    # No watched date: the day it was posted. No rating, no review, a show's TMDB id.
    assert (show["ts"], show["rating"], show["rewatch"], show["text"], show["tmdb"]) == (
        "2026-10-24T05:29:29Z",
        None,
        True,
        None,
        "tv/202",
    )
    assert broken is None  # its year won't read; the list, no diary entry, isn't there at all

    vault = tmp_path / "vault"
    stats = letterboxd.ingest_feed(vault, "tess", fetch)
    assert (stats["added"], stats["skipped"]) == (2, 1)
    assert [r["title"] for r in stream(vault, "feed")] == ["A Miniseries", "Example Film"]
    assert letterboxd.ingest_feed(vault, "tess", fetch)["added"] == 0


def test_run_reads_the_feed_named_in_env_and_needs_one_or_an_export(tmp_path, monkeypatch):
    monkeypatch.setattr(letterboxd, "_fetch", lambda url: FEED)
    vault = tmp_path / "vault"
    args = argparse.Namespace(export=None, user=None)
    monkeypatch.delenv("PROXENOS_LETTERBOXD_USER", raising=False)
    with pytest.raises(SystemExit, match="--user NAME"):
        letterboxd.run(vault, args)

    monkeypatch.setenv("PROXENOS_LETTERBOXD_USER", "tess")
    assert letterboxd.run(vault, args)["added"] == 2
    both = letterboxd.run(vault, argparse.Namespace(export=make_export(tmp_path / "e"), user=None))
    assert (both["added"], both["skipped"]) == (6, 3)
