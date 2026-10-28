"""Mentions ingester against a fake Google News and OpenAlex. The people and papers are made up."""

import argparse
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from proxenos.ingest import mentions

NAME = "Kai Example"


def oa(n, kind="W"):
    return f"https://openalex.org/{kind}{n}"


def work(n, date, authors, cited_by=0, abstract=None):
    """A work as OpenAlex returns it; `authors` holds (author number, name) pairs."""
    return {
        "id": oa(n),
        "display_name": f"Paper {n}",
        "doi": f"https://doi.org/10.0000/test.{n}",
        "publication_date": date,
        "publication_year": int(date[:4]) if date else None,
        "primary_location": {"source": {"display_name": "Journal of Tests"}},
        "cited_by_count": cited_by,
        "authorships": [{"author": {"id": oa(a, "A"), "display_name": who}} for a, who in authors],
        "abstract_inverted_index": abstract,
    }


ABSTRACT = {"Memory": [0], "is": [1, 4], "what": [2], "it": [3], "used": [5]}
AUTHORS = [
    {"id": oa(100, "A"), "display_name": NAME, "works_count": 3},
    {"id": oa(200, "A"), "display_name": "Kai Example-Other", "works_count": 40},
]
MY_WORKS = [
    work(1, "2024-06-01", [(100, NAME), (300, "Asha Test")], cited_by=2, abstract=ABSTRACT),
    work(2, "2023-02-15", [(300, "Asha Test"), (100, NAME)], cited_by=1),
    work(3, "2022-01-01", [(100, NAME)]),
    work(4, None, [(100, NAME)]),  # undated, so dropped
]
CITING = {
    "W1": [work(11, "2025-01-10", [(400, "Ravi Test")]), work(12, "2024-12-01", [(100, NAME)])],
    "W2": [work(11, "2025-01-10", [(400, "Ravi Test")])],
}

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item>
  <title>Lab wins award - Example Times</title>
  <link>https://news.example.com/articles/1</link>
  <pubDate>Tue, 04 Feb 2025 15:30:00 GMT</pubDate>
  <description>&lt;a href="https://news.example.com/articles/1"&gt;Lab wins award&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Example Times&lt;/font&gt;</description>
  <source url="https://times.example.com">Example Times</source>
</item>
<item>
  <title>Talk at a workshop</title>
  <link>https://news.example.com/articles/2</link>
  <pubDate>Sat, 01 Mar 2025 00:30:00 +0100</pubDate>
</item>
<item>
  <title>No usable date</title>
  <link>https://news.example.com/articles/3</link>
  <pubDate>someday</pubDate>
</item>
</channel></rss>"""


class FakeWeb:
    """Stands in for the fetch: answers Google News and OpenAlex from the data above, with my
    works two to a page. `fail` maps a base URL or an OpenAlex filter to an exception."""

    def __init__(self):
        self.urls = []
        self.authors = AUTHORS
        self.citing = dict(CITING)
        self.fail = {}

    def __call__(self, url):
        self.urls.append(url)
        base, _, query = url.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        key = params.get("filter", base)
        if key in self.fail:
            raise self.fail[key]
        if base == mentions.NEWS_URL:
            return RSS
        if base == mentions.AUTHORS_URL:
            return json.dumps({"results": self.authors}).encode()
        assert base == mentions.WORKS_URL
        kind, _, value = key.partition(":")
        if kind == "cites":
            return json.dumps({"results": self.citing.get(value, [])}).encode()
        start = 0 if params["cursor"] == "*" else int(params["cursor"])
        more = start + 2 < len(MY_WORKS)
        meta = {"next_cursor": str(start + 2) if more else None}
        return json.dumps({"results": MY_WORKS[start : start + 2], "meta": meta}).encode()

    def queries(self, base):
        return [
            dict(urllib.parse.parse_qsl(url.partition("?")[2]))
            for url in self.urls
            if url.startswith(base)
        ]


def stored(vault, stream):
    out = vault / "raw" / "mentions" / stream
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["id"]: r for r in map(json.loads, lines)}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setenv(mentions.NAME_ENV, NAME)
    monkeypatch.delenv(mentions.AUTHOR_ENV, raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("live HTTP"))


def test_news_items_become_records(tmp_path):
    fake = FakeWeb()
    mentions.ingest(tmp_path, NAME, fetch=fake)
    news = stored(tmp_path, "news")

    assert news["https://news.example.com/articles/1"] == {
        "id": "https://news.example.com/articles/1",
        "ts": "2025-02-04T15:30:00Z",
        "title": "Lab wins award - Example Times",
        "link": "https://news.example.com/articles/1",
        "source": "Example Times",
        "published": "Tue, 04 Feb 2025 15:30:00 GMT",
        "snippet": "Lab wins award Example Times",
    }
    second = news["https://news.example.com/articles/2"]
    assert second["ts"] == "2025-02-28T23:30:00Z"
    assert second["source"] is second["snippet"] is None
    assert len(news) == 2  # the undated item is skipped

    query = fake.queries(mentions.NEWS_URL)[0]
    assert query == {"q": f'"{NAME}"', "hl": "en-US", "gl": "US", "ceid": "US:en"}


def test_works_come_from_the_top_author_match(tmp_path, capsys):
    fake = FakeWeb()
    mentions.ingest(tmp_path, NAME, fetch=fake)
    works = stored(tmp_path, "works")

    assert works[oa(1)] == {
        "id": oa(1),
        "ts": "2024-06-01T00:00:00Z",
        "title": "Paper 1",
        "doi": "https://doi.org/10.0000/test.1",
        "publication_date": "2024-06-01",
        "venue": "Journal of Tests",
        "cited_by_count": 2,
        "coauthors": ["Asha Test"],
        "abstract": "Memory is what it is used",
        "author_id": "A100",
    }
    assert works[oa(3)]["coauthors"] == [] and works[oa(3)]["abstract"] is None
    assert sorted(works) == [oa(1), oa(2), oa(3)]
    assert "A100 (3 works)" in capsys.readouterr().err

    assert fake.queries(mentions.AUTHORS_URL) == [{"search": NAME}]
    pages = fake.queries(mentions.WORKS_URL + "?filter=author.id")
    assert [q["cursor"] for q in pages] == ["*", "2"]
    assert all(q["per-page"] == "100" and q["sort"] == "publication_date:desc" for q in pages)


def test_an_author_id_from_the_env_skips_the_search(tmp_path, monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: io.BytesIO(fake(url)))
    monkeypatch.setenv(mentions.AUTHOR_ENV, oa(200, "a"))
    mentions.run(tmp_path, argparse.Namespace())

    assert fake.queries(mentions.AUTHORS_URL) == []
    assert fake.queries(mentions.WORKS_URL)[0]["filter"] == "author.id:A200"
    assert stored(tmp_path, "works")[oa(3)]["author_id"] == "A200"


def test_citations_are_merged_per_citing_work(tmp_path):
    fake = FakeWeb()
    mentions.ingest(tmp_path, NAME, fetch=fake)
    citations = stored(tmp_path, "citations")

    assert citations[oa(11)] == {
        "id": oa(11),
        "ts": "2025-01-10T00:00:00Z",
        "title": "Paper 11",
        "doi": "https://doi.org/10.0000/test.11",
        "publication_date": "2025-01-10",
        "venue": "Journal of Tests",
        "authors": ["Ravi Test"],
        "cites": [oa(1), oa(2)],
        "self_citation": False,
    }
    assert citations[oa(12)]["self_citation"] is True
    cites = fake.queries(mentions.WORKS_URL + "?filter=cites")
    assert [q["filter"] for q in cites] == ["cites:W1", "cites:W2"]  # W3 has no citations
    assert all(q["per-page"] == "25" and q["sort"] == "publication_date:desc" for q in cites)

    # Paper 11 falls out of paper 2's newest citing works, but it still cites paper 2.
    fake.citing["W2"] = [work(13, "2025-02-01", [(500, "Meera Test")])]
    mentions.ingest(tmp_path, NAME, fetch=fake)
    citations = stored(tmp_path, "citations")
    assert citations[oa(11)]["cites"] == [oa(1), oa(2)]
    assert citations[oa(13)]["cites"] == [oa(2)]


def test_a_failing_sub_source_is_counted_and_skipped(tmp_path, capsys):
    fake = FakeWeb()
    fake.fail[mentions.NEWS_URL] = urllib.error.HTTPError("", 503, "unavailable", {}, None)
    fake.fail["cites:W2"] = TimeoutError("timed out")
    stats = mentions.ingest(tmp_path, NAME, fetch=fake)

    assert stats["failed"] == 2
    assert not (tmp_path / "raw" / "mentions" / "news").exists()
    assert len(stored(tmp_path, "works")) == 3
    assert stored(tmp_path, "citations")[oa(11)]["cites"] == [oa(1)]
    err = capsys.readouterr().err
    assert "skipped news" in err and "skipped citations of https://openalex.org/W2" in err

    fake = FakeWeb()
    fake.authors = []
    stats = mentions.ingest(tmp_path / "other", NAME, fetch=fake)
    assert stats["failed"] == 1
    assert len(stored(tmp_path / "other", "news")) == 2


def test_requests_time_out_after_20s_and_send_no_email(tmp_path, monkeypatch):
    fake, timeouts = FakeWeb(), []

    def urlopen(url, timeout):
        timeouts.append(timeout)
        return io.BytesIO(fake(url))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    stats = mentions.ingest(tmp_path, NAME)

    assert stats["failed"] == 0 and stats["added"] == 2 + 3 + 2
    assert set(timeouts) == {20} and len(timeouts) == len(fake.urls)
    assert not any("mailto" in url or "@" in url for url in fake.urls)


def test_run_needs_the_name_and_a_well_formed_author_id(tmp_path, monkeypatch):
    monkeypatch.setenv(mentions.AUTHOR_ENV, "someone")
    with pytest.raises(SystemExit, match=mentions.AUTHOR_ENV):
        mentions.run(tmp_path, argparse.Namespace())

    monkeypatch.delenv(mentions.NAME_ENV)
    with pytest.raises(SystemExit, match=mentions.NAME_ENV):
        mentions.run(tmp_path, argparse.Namespace())
    assert not (tmp_path / "raw").exists()
