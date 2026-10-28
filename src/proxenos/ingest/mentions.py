"""Public mentions of the user and their published work: news, their papers and the papers
citing them.

Three sub-sources, each written to its own stream under raw/mentions/:

- news: Google News RSS for the exact name in PROXENOS_FULL_NAME. The feed only holds recent
  articles, so each run adds what's new and keeps what has dropped off.
- works: the user's papers from OpenAlex. PROXENOS_OPENALEX_ID picks the author profile.
  Without it the top hit of an author search on the name is used and printed with its works
  count, since a name can match someone else. Every work keeps the author id it was read under.
- citations: works citing their papers, the 25 most recent per paper. A work citing several of
  their papers is one record listing them all, and the list only grows, so a paper whose newest
  25 have moved on doesn't drop out of it.

Ids are the article link or the OpenAlex id, and ts is the publication date, at midnight UTC
when there is only a date. Each sub-source fails on its own: a request that errors or times
out is counted in "failed" and reported, and the rest still write. Every run re-reads
everything and merges by id.
"""

import argparse
import http.client
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from proxenos.config import env
from proxenos.store import merge_monthly

NEWS_URL = "https://news.google.com/rss/search"
AUTHORS_URL = "https://api.openalex.org/authors"
WORKS_URL = "https://api.openalex.org/works"
NAME_ENV = "PROXENOS_FULL_NAME"
AUTHOR_ENV = "PROXENOS_OPENALEX_ID"
TIMEOUT = 20  # seconds, per request
PER_PAGE = 100  # OpenAlex's maximum
CITING_PER_WORK = 25

# What a failing request or a garbled reply raises. URLError, HTTPError and timeouts are all
# OSErrors, and a bad JSON body is a ValueError.
_FAILURES = (OSError, ValueError, ET.ParseError, http.client.HTTPException)
_AUTHOR_ID = re.compile(r"(A\d+)$", re.IGNORECASE)

# Takes a URL and returns the response body, raising the way urlopen does.
Fetch = Callable[[str], bytes]


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return response.read()


def ingest(
    vault: Path, name: str, author_id: str | None = None, fetch: Fetch = _fetch
) -> dict[str, int]:
    out = vault / "raw" / "mentions"
    totals = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "failed": 0}

    def attempt(label: str, step: Callable, *args):
        try:
            return step(*args)
        except _FAILURES as e:
            totals["failed"] += 1
            print(f"mentions: skipped {label} ({e})", file=sys.stderr)
            return None

    def write(stream: str, records: list[dict]) -> None:
        for key, value in merge_monthly(records, out / stream).items():
            totals[key] += value

    news = attempt("news", _news, name, fetch)
    if news is not None:
        write("news", news)

    works = attempt("works", _works, name, author_id, fetch)
    if works is not None:
        write("works", works)
        stored, citing = _stored(out / "citations"), {}
        for work in works:
            if not work["cited_by_count"]:
                continue
            for record in attempt(f"citations of {work['id']}", _citing, work, fetch) or []:
                known = citing.get(record["id"]) or stored.get(record["id"]) or {}
                record["cites"] = sorted({*known.get("cites", []), *record["cites"]})
                citing[record["id"]] = record
        write("citations", list(citing.values()))
    return totals


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    name = env("FULL_NAME").strip()
    if not name:
        raise SystemExit(f"mentions: set {NAME_ENV} in the repo's .env to the name to search for")
    author_id = env("OPENALEX_ID").strip() or None
    if author_id and not _AUTHOR_ID.search(author_id):
        raise SystemExit(f"mentions: {AUTHOR_ENV} should be an OpenAlex author id like A123")
    return ingest(vault, name, author_id)


def _news(name: str, fetch: Fetch) -> list[dict]:
    query = {"q": f'"{name}"', "hl": "en-US", "gl": "US", "ceid": "US:en"}
    root = ET.fromstring(fetch(f"{NEWS_URL}?{urllib.parse.urlencode(query, safe=':')}"))
    records = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if not link:
            continue
        try:
            when = parsedate_to_datetime(published)
        except (TypeError, ValueError):
            continue
        source = getattr(item.find("source"), "text", None)
        records.append(
            {
                "id": link,
                "ts": _iso(when if when.tzinfo else when.replace(tzinfo=UTC)),
                "title": (item.findtext("title") or "").strip() or None,
                "link": link,
                "source": (source or "").strip() or None,
                "published": published,
                "snippet": _plain(item.findtext("description") or "") or None,
            }
        )
    return records


def _works(name: str, author_id: str | None, fetch: Fetch) -> list[dict]:
    if author_id:
        author = _AUTHOR_ID.search(author_id).group(1).upper()
    else:
        query = urllib.parse.urlencode({"search": name})
        results = json.loads(fetch(f"{AUTHORS_URL}?{query}")).get("results") or []
        if not results:
            raise ValueError("no OpenAlex author matches the name")
        author = _short(results[0]["id"])
        print(
            f"mentions: using OpenAlex author {author} ({results[0].get('works_count')} works),"
            f" the top search match; set {AUTHOR_ENV} to pin a different one",
            file=sys.stderr,
        )

    # OpenAlex pages with a cursor; "*" asks for the first page.
    works, cursor = [], "*"
    while cursor:
        params = {
            "filter": f"author.id:{author}",
            "per-page": PER_PAGE,
            "sort": "publication_date:desc",
            "cursor": cursor,
        }
        body = json.loads(fetch(f"{WORKS_URL}?{urllib.parse.urlencode(params, safe=':*')}"))
        batch = body.get("results") or []
        works += batch
        cursor = (body.get("meta") or {}).get("next_cursor") if batch else None

    records = []
    for work in works:
        record = _basics(work)
        if not record["ts"]:
            continue
        record["cited_by_count"] = work.get("cited_by_count") or 0
        record["coauthors"] = [name for id_, name in _authors(work) if id_ != author]
        record["abstract"] = _abstract(work.get("abstract_inverted_index"))
        record["author_id"] = author
        records.append(record)
    return records


def _citing(work: dict, fetch: Fetch) -> list[dict]:
    params = {
        "filter": f"cites:{_short(work['id'])}",
        "per-page": CITING_PER_WORK,
        "sort": "publication_date:desc",
    }
    body = json.loads(fetch(f"{WORKS_URL}?{urllib.parse.urlencode(params, safe=':')}"))
    records = []
    for citing in body.get("results") or []:
        record = _basics(citing)
        if not record["ts"]:
            continue
        authors = _authors(citing)
        record["authors"] = [name for _, name in authors]
        record["cites"] = [work["id"]]
        record["self_citation"] = any(id_ == work["author_id"] for id_, _ in authors)
        records.append(record)
    return records


def _basics(work: dict) -> dict:
    location = work.get("primary_location") or {}
    return {
        "id": work["id"],
        "ts": _date_ts(work),
        "title": work.get("display_name") or work.get("title"),
        "doi": work.get("doi"),
        "publication_date": work.get("publication_date"),
        "venue": (location.get("source") or {}).get("display_name"),
    }


def _authors(work: dict) -> list[tuple[str | None, str]]:
    pairs = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        name = author.get("display_name") or authorship.get("raw_author_name")
        if name:
            pairs.append((_short(author["id"]) if author.get("id") else None, name))
    return pairs


def _abstract(inverted: dict[str, list[int]] | None) -> str | None:
    # OpenAlex ships abstracts as word -> positions, so the text has to be laid back out.
    if not inverted:
        return None
    positions = {i: word for word, places in inverted.items() for i in places}
    return " ".join(positions[i] for i in sorted(positions)) or None


def _date_ts(work: dict) -> str | None:
    day = work.get("publication_date")
    if not day and work.get("publication_year"):
        day = f"{work['publication_year']}-01-01"
    try:
        return _iso(datetime.fromisoformat(day).replace(tzinfo=UTC)) if day else None
    except ValueError:
        return None


def _stored(directory: Path) -> dict[str, dict]:
    records = {}
    for path in directory.glob("*.jsonl"):
        with path.open(encoding="utf-8") as f:
            records.update((r["id"], r) for r in map(json.loads, f))
    return records


def _short(openalex_id: str) -> str:
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)


def _plain(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.chunks).split())
