"""YouTube ingester against synthetic Takeout history, in JSON and HTML. No real data here."""

import json

import pytest

from proxenos.ingest import youtube

WATCHED_JSON = [
    {
        "header": "YouTube",
        "title": "Watched How to make café ☕",
        "titleUrl": "https://www.youtube.com/watch?v=abc",
        "subtitles": [{"name": "Example Channel", "url": "https://www.youtube.com/channel/UC1"}],
        "time": "2024-03-05T21:15:02.123Z",
        "products": ["YouTube"],
    },
    {
        "header": "YouTube Music",
        "title": "Watched A song",
        "titleUrl": "https://music.youtube.com/watch?v=def",
        "time": "2024-03-06T08:00:00Z",
    },
    {
        "header": "YouTube",
        "title": "Watched An advert",
        "titleUrl": "https://www.youtube.com/watch?v=ad",
        "time": "2024-03-06T09:00:00Z",
        "details": [{"name": "From Google Ads"}],
    },
    {"header": "YouTube", "title": "Viewed a post", "time": "2024-03-06T10:00:00Z"},
    {"header": "YouTube", "title": "Watched a video that has been removed", "time": "bad"},
]
SEARCHED_JSON = [
    {
        "header": "YouTube",
        "title": "Searched for lab tutorial",
        "titleUrl": "https://www.youtube.com/results?search_query=lab+tutorial",
        "time": "2024-03-07T12:00:00Z",
    }
]


def cell(body, details=""):
    caption = "<b>Products:</b><br>&emsp;YouTube<br>" + details
    return (
        '<div class="outer-cell mdl-cell mdl-cell--12-col mdl-shadow--2dp"><div class="mdl-grid">'
        '<div class="header-cell mdl-cell mdl-cell--12-col">'
        '<p class="mdl-typography--title">YouTube<br></p></div>'
        '<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">'
        f"{body}</div>"
        '<div class="content-cell mdl-cell mdl-cell--12-col mdl-typography--caption">'
        f"{caption}</div></div></div>"
    )


WATCHED_HTML = (
    '<html><head><title>My Activity History</title><style type="text/css">.x{}</style></head>'
    '<body><div class="mdl-grid">'
    + cell(
        'Watched\xa0<a href="https://www.youtube.com/watch?v=xyz">Tom &amp; Jerry</a><br>'
        '<a href="https://www.youtube.com/channel/UC2">Cartoons</a><br>'
        "Mar 5, 2024, 9:15:02\u202fPM EST<br>"
    )
    + cell(
        'Watched\xa0<a href="https://www.youtube.com/watch?v=ad2">Advert</a><br>'
        "Mar 5, 2024, 9:16:00\u202fPM EST<br>",
        "<b>Details:</b><br>&emsp;From Google Ads<br>",
    )
    + cell(
        'Watched\xa0<a href="https://www.youtube.com/watch?v=in">Abroad</a><br>'
        "Jun 1, 2024, 10:00:00\u202fAM GMT+05:30<br>"
    )
    + cell("Answered survey question<br>Mar 6, 2024, 1:00:00\u202fPM EST<br>")
    + cell('Watched\xa0<a href="https://www.youtube.com/watch?v=z">Zoned</a><br>Mar 6, 2024 XYZ')
    + "</div></body></html>"
)
SEARCHED_HTML = (
    "<html><body>"
    + cell(
        'Searched for\xa0<a href="https://www.youtube.com/results?search_query=x">'
        "neuro &quot;talks&quot;</a><br>Apr 2, 2024, 7:05:09\u202fAM EDT<br>"
    )
    + "</body></html>"
)


def make_export(root, fmt):
    history = root / "Takeout" / "YouTube and YouTube Music" / "history"
    history.mkdir(parents=True)
    if fmt == "json":
        (history / "watch-history.json").write_text(json.dumps(WATCHED_JSON))
        (history / "search-history.json").write_text(json.dumps(SEARCHED_JSON))
    else:
        (history / "watch-history.html").write_text(WATCHED_HTML, encoding="utf-8")
        (history / "search-history.html").write_text(SEARCHED_HTML, encoding="utf-8")
    return root / "Takeout" / "YouTube and YouTube Music"


def test_json_history_keeps_videos_and_searches_but_not_ads(tmp_path):
    export = make_export(tmp_path / "e", "json")
    records = youtube.read_watched(export)
    assert records.count(None) == 1  # the time that won't parse
    first, song = [r for r in records if r]
    assert first == {
        "id": first["id"],
        "ts": "2024-03-05T21:15:02Z",
        "title": "How to make café ☕",
        "url": "https://www.youtube.com/watch?v=abc",
        "channel": "Example Channel",
        "channel_url": "https://www.youtube.com/channel/UC1",
        "product": "YouTube",
    }
    assert (song["product"], song["channel"]) == ("YouTube Music", None)

    (search,) = youtube.read_searched(export)
    assert (search["text"], search["from_me"], search["ts"]) == (
        "lab tutorial",
        True,
        "2024-03-07T12:00:00Z",
    )


def test_html_history_is_read_the_same_way(tmp_path):
    export = make_export(tmp_path / "e", "html")
    records = youtube.read_watched(export)
    assert records.count(None) == 1  # an unknown zone
    cartoon, abroad = [r for r in records if r]
    assert (cartoon["title"], cartoon["ts"], cartoon["channel"], cartoon["url"]) == (
        "Tom & Jerry",
        "2024-03-06T02:15:02Z",
        "Cartoons",
        "https://www.youtube.com/watch?v=xyz",
    )
    assert (cartoon["channel_url"], cartoon["product"]) == (
        "https://www.youtube.com/channel/UC2",
        "YouTube",
    )
    assert (abroad["ts"], abroad["channel"]) == ("2024-06-01T04:30:00Z", None)

    (search,) = youtube.read_searched(export)
    assert (search["text"], search["ts"]) == ('neuro "talks"', "2024-04-02T11:05:09Z")


def test_ingest_writes_both_streams_and_reruns_are_no_ops(tmp_path):
    vault = tmp_path / "vault"
    export = make_export(tmp_path / "e", "json")
    stats = youtube.ingest(vault, export)
    assert (stats["added"], stats["skipped"]) == (3, 1)
    assert sorted(p.name for p in (vault / "raw" / "youtube").iterdir()) == ["searched", "watched"]
    again = youtube.ingest(vault, export)
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)
    with pytest.raises(FileNotFoundError):
        youtube.ingest(vault, tmp_path / "e" / "Takeout" / "nothing")
