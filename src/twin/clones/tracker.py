"""Research and news feed, ranked against my profile.

Each run pulls the last couple of days from public sources (arXiv, OpenAlex, RSS and Atom
feeds, the Hacker News front page), drops whatever was offered before, and asks the model to
score the rest against `self/` and my recent reactions on the page. The best go into
tracker/items as monthly JSONL, tagged as made by the twin.

The sources live in tracker/sources.json, which is mine to edit. When it's missing, the model
proposes a first set from the profile and from the sites I link to most on WhatsApp. Only
those domain names go to the model, nothing else from the messages. A source that fails is
counted and skipped, so one dead feed never costs a run.

Every candidate that reaches the model is remembered in tracker/seen.json. Later runs rank
only what's new, so items it passed over don't come back to fill the slots.
"""

import argparse
import hashlib
import html
import http.client
import itertools
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import partial
from pathlib import Path

from twin import llm
from twin.store import merge_monthly

ARXIV_URL = "https://export.arxiv.org/api/query"
OPENALEX_URL = "https://api.openalex.org/works"
HN_URL = "https://hn.algolia.com/api/v1/search"
TIMEOUT = 20  # seconds, per request
USER_AGENT = "twin-tracker/0.1"

PER_QUERY = 25  # results asked for per arXiv category or query, and per OpenAlex query
# arXiv asks API clients to leave 3 seconds between requests.
ARXIV_PAUSE = 3.0
# arXiv announces papers a day or more after submission and not at weekends, so its window
# reaches further back. Dedupe keeps the overlap from showing twice.
ARXIV_LAG = timedelta(days=3)
MAX_CANDIDATES = 150  # beyond this the ranking prompt is trimmed
EXPLORE_SHARE = 0.2
SUMMARY_CHARS = 600
FEEDBACK_WINDOW = timedelta(days=14)
REACTIONS_SHOWN = 30  # per kind of reaction
SEEN_WINDOW = timedelta(days=30)
TOP_DOMAINS = 30
# Room for thinking plus ~150 verdicts. The SDK refuses non-streaming requests above ~21k.
RANK_MAX_TOKENS = 20000

# Takes a URL and returns the response body, raising on HTTP errors the way urlopen does.
Fetch = Callable[[str], bytes]
# Turns one response body into candidates.
Parse = Callable[[bytes], list[dict]]

# What a dead, slow or garbled source can raise. Each costs only that source; anything else
# is a bug and stops the run.
_SOURCE_ERRORS = (
    OSError,  # urllib's errors and timeouts
    http.client.HTTPException,
    ET.ParseError,
    ValueError,  # bad JSON or bytes, or an arXiv error entry
    LookupError,
    TypeError,
    AttributeError,
)
_ATOM = "{http://www.w3.org/2005/Atom}"
_RSS1 = "{http://purl.org/rss/1.0/}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_REACTIONS = ("useful", "save", "not_me")
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://[^\s<>\"']+")
# Abstract pages, PDFs and arXiv DOIs of one paper, in any version, share its bare id.
_ARXIV_ID = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|doi\.org/10\.48550/arxiv\.)"
    r"([\w.\-/]+?)(?:v\d+)?(?:\.pdf)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_TRACKING = re.compile(r"utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src")

_PROFILE_FILES = ("identity", "interests", "taste")
_PROFILE_INTRO = (
    "You are choosing reading for one person. Below is their profile, which their digital "
    "twin keeps from their own writing and reactions. Judge everything by what this person "
    "would want."
)

_SOURCES_PROMPT = """\
Propose public sources for this person's research and news feed. A program polls them every \
few hours and you rank what comes in, so favour sources that publish often and that they \
would actually read.

- arxiv.categories: arXiv category codes they would browse, like q-bio.NC or cs.LG.
- arxiv.queries: short phrases (one to four words) for topics that cut across categories. \
Each is matched as an exact phrase.
- openalex.queries: short search phrases for new journal papers that never reach arXiv.
- feeds: RSS or Atom feed URLs of blogs, newsletters and news sites they would read. Only \
feeds you are confident exist. kind is "news" for news outlets and "post" for blogs and \
newsletters.
- hackernews: whether the Hacker News front page belongs in their feed.

Keep each list to about eight entries.

The sites they link to most in their own messages, most shared first:
{domains}"""

_RANK_PROMPT = """\
Score every candidate below for this person's feed: a page they keep open while they work, \
which should show what they would have picked themselves.

For each candidate return its id and:
- score: 0 to 1, how much they would want to see it today. Use the whole range.
- why: one sentence, under 25 words, on why it matters to this person in particular. Make \
the link to them; don't summarize the item.
- interest: the interest from their profile it bears on, as a short label.
- explore: true when it sits beside or against their core interests rather than squarely in \
one. A few of these keep the feed from closing into a bubble.

{reactions}

Candidates:

{candidates}"""

_STRINGS = {"type": "array", "items": {"type": "string"}}
_SOURCES_SCHEMA = {
    "type": "object",
    "properties": {
        "arxiv": {
            "type": "object",
            "properties": {"categories": _STRINGS, "queries": _STRINGS},
            "required": ["categories", "queries"],
            "additionalProperties": False,
        },
        "openalex": {
            "type": "object",
            "properties": {"queries": _STRINGS},
            "required": ["queries"],
            "additionalProperties": False,
        },
        "feeds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "kind": {"type": "string", "enum": ["news", "post"]},
                },
                "required": ["url", "kind"],
                "additionalProperties": False,
            },
        },
        "hackernews": {"type": "boolean"},
    },
    "required": ["arxiv", "openalex", "feeds", "hackernews"],
    "additionalProperties": False,
}
_RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "number"},
                    "why": {"type": "string"},
                    "interest": {"type": "string"},
                    "explore": {"type": "boolean"},
                },
                "required": ["id", "score", "why", "interest", "explore"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ranked"],
    "additionalProperties": False,
}


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def track(
    vault: Path,
    max_items: int = 20,
    days: float = 2,
    fetch: Fetch = _fetch,
    now: datetime | None = None,
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    batch = _iso(now)
    out = vault / "tracker"
    profile = read_profile(vault / "self")
    sources = _sources(out / "sources.json", profile, vault / "raw" / "whatsapp" / "messages")
    candidates, failed = fetch_candidates(sources, now - timedelta(days=days), now, fetch)

    items = _load_items(out / "items")
    seen = _load_seen(out / "seen.json", now)
    fresh = _dedupe(candidates, items.keys() | seen.keys())
    stats = {"fetched": len(candidates), "new": len(fresh), "kept": 0, "sources_failed": failed}
    if not fresh:
        return stats

    pool = trim(fresh, MAX_CANDIDATES)
    ranked = _rank(pool, profile, _reactions(out / "feedback.jsonl", items, now))
    kept = select(ranked, max_items)
    merge_monthly([_record(item, batch) for item in kept], out / "items")
    _save_seen(out / "seen.json", seen | dict.fromkeys((c["id"] for c in pool), batch))
    stats["kept"] = len(kept)
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-items", type=int, default=20, help="how many items to keep from this run"
    )
    parser.add_argument("--days", type=float, default=2, help="how far back to look for new items")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return track(vault, max_items=args.max_items, days=args.days)


def read_profile(self_dir: Path) -> str:
    if not (self_dir / "interests.md").exists():
        raise SystemExit(
            f"tracker: there's no profile yet ({self_dir / 'interests.md'} is missing). "
            "`twin master` builds it; run that first."
        )
    parts = [_PROFILE_INTRO]
    for name in _PROFILE_FILES:
        path = self_dir / f"{name}.md"
        if path.exists():
            parts.append(f"<{name}>\n{path.read_text(encoding='utf-8').strip()}\n</{name}>")
    return "\n\n".join(parts)


def shared_domains(directory: Path, limit: int = TOP_DOMAINS) -> list[str]:
    """The sites I link to most on WhatsApp, most shared first. Only my own messages count."""
    counts: Counter[str] = Counter()
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for record in map(json.loads, f):
                if record.get("from_me") and record.get("kind") == "link":
                    hosts = {_host(url) for url in _URL.findall(record.get("text") or "")}
                    counts.update(hosts - {None})
    return [domain for domain, _ in counts.most_common(limit)]


def fetch_candidates(
    sources: dict, since: datetime, now: datetime, fetch: Fetch = _fetch
) -> tuple[list[dict], int]:
    """Recent candidates from every source, and how many requests failed."""
    candidates, failed, arxiv_calls = [], 0, 0
    for label, url, parse, cutoff in _requests(sources, since, now):
        if url.startswith(ARXIV_URL):
            if arxiv_calls:
                time.sleep(ARXIV_PAUSE)
            arxiv_calls += 1
        try:
            found = parse(fetch(url))
        except _SOURCE_ERRORS as e:
            failed += 1
            print(f"tracker: skipped {label}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        candidates.extend(
            c for c in found if c["url"] and c["title"] and (c["published"] or "") >= cutoff
        )
    return candidates, failed


def parse_arxiv(body: bytes) -> list[dict]:
    root = ET.fromstring(body)
    papers = []
    for entry in root.iter(f"{_ATOM}entry"):
        link = entry.findtext(f"{_ATOM}id", "")
        if "/api/errors" in link:
            raise ValueError(_plain(entry.findtext(f"{_ATOM}summary")))
        arxiv_id = _ARXIV_ID.search(link)
        papers.append(
            _candidate(
                url=f"https://arxiv.org/abs/{arxiv_id[1]}" if arxiv_id else link,
                # arXiv text is plain, and its maths can hold a bare "<".
                title=_plain(entry.findtext(f"{_ATOM}title")),
                source="arXiv",
                kind="paper",
                published=entry.findtext(f"{_ATOM}published"),
                authors=[_plain(a.findtext(f"{_ATOM}name")) for a in entry.iter(f"{_ATOM}author")],
                summary=_plain(entry.findtext(f"{_ATOM}summary")),
            )
        )
    return papers


def parse_openalex(body: bytes) -> list[dict]:
    works = []
    for work in json.loads(body)["results"]:
        location = work.get("primary_location") or {}
        authorships = work.get("authorships") or []
        works.append(
            _candidate(
                url=work.get("doi") or location.get("landing_page_url") or work.get("id"),
                title=_text(work.get("title")),
                source="OpenAlex",
                kind="paper",
                published=work.get("publication_date"),
                authors=[_plain((a.get("author") or {}).get("display_name")) for a in authorships],
                summary=_text(_abstract(work.get("abstract_inverted_index"))),
            )
        )
    return works


def parse_feed(body: bytes, kind: str = "post", fallback: str | None = None) -> list[dict]:
    """Items from an RSS 2.0, RSS 1.0 (RDF) or Atom feed. The source is the feed's title."""
    root = ET.fromstring(body)
    title_paths = ("channel/title", f"{_RSS1}channel/{_RSS1}title", f"{_ATOM}title")
    source = _plain(_first(root, *title_paths)) or fallback or "feed"
    posts = []
    for entry in root.iter(f"{_ATOM}entry"):
        posts.append(
            _candidate(
                url=_atom_link(entry),
                title=_text(entry.findtext(f"{_ATOM}title")),
                source=source,
                kind=kind,
                published=_first(entry, f"{_ATOM}published", f"{_ATOM}updated"),
                authors=[_plain(a.findtext(f"{_ATOM}name")) for a in entry.iter(f"{_ATOM}author")],
                summary=_text(_first(entry, f"{_ATOM}summary", f"{_ATOM}content")),
            )
        )
    for item in itertools.chain(root.iter("item"), root.iter(f"{_RSS1}item")):
        ns = _RSS1 if item.tag.startswith(_RSS1) else ""
        creators = item.findall(f"{_DC}creator") + item.findall("author")
        posts.append(
            _candidate(
                url=_first(item, f"{ns}link", "guid"),
                title=_text(item.findtext(f"{ns}title")),
                source=source,
                kind=kind,
                published=_first(item, "pubDate", f"{_DC}date"),
                authors=[_plain(creator.text) for creator in creators],
                summary=_text(_first(item, f"{ns}description", f"{_CONTENT}encoded")),
            )
        )
    return posts


def parse_hn(body: bytes) -> list[dict]:
    stories = []
    for hit in json.loads(body)["hits"]:
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        points, comments = hit.get("points") or 0, hit.get("num_comments") or 0
        talk = f"{points} points and {comments} comments on Hacker News."
        stories.append(
            _candidate(
                url=hit.get("url") or discussion,  # Ask HN and the like link to the thread
                title=_text(hit.get("title")),
                source="Hacker News",
                kind="news",
                published=hit.get("created_at"),
                authors=[],  # the submitter, not the author
                summary=f"{talk} {_text(hit.get('story_text'))}".strip(),
            )
        )
    return stories


def trim(candidates: list[dict], limit: int) -> list[dict]:
    """At most `limit` candidates, taking the newest from each source in turn so that one busy
    source can't crowd out the rest."""
    if len(candidates) <= limit:
        return candidates
    by_source: dict[str, list[dict]] = defaultdict(list)
    for candidate in sorted(candidates, key=lambda c: c["published"], reverse=True):
        by_source[candidate["source"]].append(candidate)
    turns = itertools.chain.from_iterable(itertools.zip_longest(*by_source.values()))
    return [c for c in turns if c is not None][:limit]


def select(ranked: list[dict], max_items: int) -> list[dict]:
    """The best `max_items` by score, with about a fifth of the slots held for explore picks.
    Explore picks beyond that share still compete for the other slots on score."""
    by_score = sorted(ranked, key=lambda r: r["score"], reverse=True)
    held = [r for r in by_score if r["explore"]][: round(max_items * EXPLORE_SHARE)]
    held_ids = {r["id"] for r in held}
    rest = [r for r in by_score if r["id"] not in held_ids][: max_items - len(held)]
    return sorted(held + rest, key=lambda r: r["score"], reverse=True)


def normalize_url(url: str) -> str:
    """The form two links to the same page share: https, no www, no tracking parameters,
    fragment or trailing slash, and one form for every link to an arXiv paper."""
    if arxiv_id := _ARXIV_ID.search(url):
        return f"https://arxiv.org/abs/{arxiv_id[1].lower()}"
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    path = parts.path.rstrip("/")
    if host in ("doi.org", "dx.doi.org"):  # DOIs are case-insensitive
        host, path = "doi.org", path.lower()
    query = sorted(
        (key, value)
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING.fullmatch(key)
    )
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(query), ""))


def item_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:16]


def _sources(path: Path, profile: str, messages: Path) -> dict:
    if not path.exists():
        domains = "\n".join(shared_domains(messages)) or "(none on record yet)"
        # A one-off call, so it can afford to think harder than ranking does.
        proposed = llm.ask(
            _SOURCES_PROMPT.format(domains=domains),
            system=profile,
            schema=_SOURCES_SCHEMA,
            effort="high",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proposed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"tracker: {path} isn't valid JSON ({e}). Fix it, or delete it to have new "
            "sources proposed."
        ) from None


def _requests(
    sources: dict, since: datetime, now: datetime
) -> Iterator[tuple[str, str, Parse, str]]:
    """(label, url, parser, cutoff) for each request. Candidates published before the cutoff
    are dropped. arXiv comes first, so its copy of a paper wins over OpenAlex's."""
    arxiv = sources.get("arxiv") or {}
    terms = [f"cat:{category}" for category in arxiv.get("categories", [])]
    terms += [f'all:"{query}"' for query in arxiv.get("queries", [])]
    for term in terms:
        params = {
            "search_query": term,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": PER_QUERY,
        }
        yield f"arXiv {term}", _url(ARXIV_URL, params), parse_arxiv, _iso(since - ARXIV_LAG)

    day = since.date().isoformat()
    for query in (sources.get("openalex") or {}).get("queries", []):
        params = {
            "search": query,
            # Capped at today: some journals date their issues months ahead.
            "filter": f"from_publication_date:{day},to_publication_date:{now.date()}",
            "sort": "publication_date:desc",
            "per-page": PER_QUERY,
            "select": "id,doi,title,publication_date,authorships,abstract_inverted_index,"
            "primary_location",
        }
        yield f"OpenAlex {query!r}", _url(OPENALEX_URL, params), parse_openalex, f"{day}T00:00:00Z"

    for feed in sources.get("feeds", []):
        feed = {"url": feed} if isinstance(feed, str) else feed
        parse = partial(parse_feed, kind=feed.get("kind", "post"), fallback=_host(feed["url"]))
        yield f"feed {feed['url']}", feed["url"], parse, _iso(since)

    if sources.get("hackernews"):
        params = {"tags": "front_page", "hitsPerPage": 50}
        yield "Hacker News", _url(HN_URL, params), parse_hn, _iso(since)


def _candidate(
    *,
    url: str | None,
    title: str,
    source: str,
    kind: str,
    published: str | None,
    authors: list[str],
    summary: str,
) -> dict:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = ""  # a guid that isn't a link, say; dropped with the rest of the item
    when = _when(published)
    return {
        "id": item_id(url) if url else "",
        "url": url,
        "title": title,
        "source": source,
        "kind": kind,
        "published": _iso(when) if when else None,
        "authors": [author for author in authors if author],
        "summary": _clip(summary, SUMMARY_CHARS),
    }


def _dedupe(candidates: list[dict], known: set[str]) -> list[dict]:
    fresh, ids = [], set(known)
    for candidate in candidates:
        if candidate["id"] not in ids:
            ids.add(candidate["id"])
            fresh.append(candidate)
    return fresh


def _reactions(path: Path, items: dict[str, dict], now: datetime) -> dict[str, list[str]]:
    """Titles of the items I marked lately, by reaction, newest first. Opens don't count."""
    if not path.exists():
        return {}
    cutoff = now - FEEDBACK_WINDOW
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                when, action = _when(event["ts"]), event["action"]
                item = items.get(event["item_id"])
            except (ValueError, KeyError, TypeError):
                continue  # the page writes this file, and one bad line shouldn't stop a run
            if action in _REACTIONS and item and when and when >= cutoff:
                events.append((when, action, item["title"]))
    titles: dict[str, list[str]] = defaultdict(list)
    for _, action, title in sorted(events, reverse=True):
        if title not in titles[action] and len(titles[action]) < REACTIONS_SHOWN:
            titles[action].append(title)
    return titles


def _rank(pool: list[dict], profile: str, reactions: dict[str, list[str]]) -> list[dict]:
    """The candidates the model scored, each with its score, why, interest and explore flag."""
    by_short_id = {f"c{n}": candidate for n, candidate in enumerate(pool, 1)}
    prompt = _RANK_PROMPT.format(
        reactions=_reactions_text(reactions),
        candidates="\n\n".join(_candidate_text(k, c) for k, c in by_short_id.items()),
    )
    answer = llm.ask(
        prompt, system=profile, schema=_RANK_SCHEMA, effort="medium", max_tokens=RANK_MAX_TOKENS
    )
    ranked = {}
    for verdict in answer["ranked"]:
        candidate = by_short_id.get(verdict["id"])
        if candidate is None:
            continue  # an id the model made up
        ranked[verdict["id"]] = {
            **candidate,
            "score": min(max(float(verdict["score"]), 0.0), 1.0),
            "why": verdict["why"].strip(),
            "interest": verdict["interest"].strip(),
            "explore": bool(verdict["explore"]),
        }
    return list(ranked.values())


def _reactions_text(reactions: dict[str, list[str]]) -> str:
    if not reactions:
        return "They haven't reacted to any recent picks yet."
    lines = ["How they reacted to recent picks. Let this steer your scores."]
    for action in _REACTIONS:
        lines += [f"- {action}: {title}" for title in reactions.get(action, [])]
    return "\n".join(lines)


def _candidate_text(short_id: str, candidate: dict) -> str:
    authors = candidate["authors"]
    header = f"[{short_id}] {candidate['kind']} from {candidate['source']}"
    lines = [f"{header}, {candidate['published'][:10]}", candidate["title"]]
    if authors:
        lines.append("By " + ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else ""))
    if candidate["summary"]:
        lines.append(candidate["summary"])
    return "\n".join(lines)


def _record(item: dict, batch: str) -> dict:
    return {
        "id": item["id"],
        "ts": batch,
        "batch": batch,
        "url": item["url"],
        "title": item["title"],
        "source": item["source"],
        "kind": item["kind"],
        "published": item["published"],
        "authors": item["authors"],
        "summary": item["summary"],
        "score": item["score"],
        "why": item["why"],
        "interest": item["interest"],
        "explore": item["explore"],
        "by": "twin",  # twin-made, so it's never read back as something I wrote
    }


def _load_items(directory: Path) -> dict[str, dict]:
    items = {}
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            items.update((record["id"], record) for record in map(json.loads, f))
    return items


def _load_seen(path: Path, now: datetime) -> dict[str, str]:
    if not path.exists():
        return {}
    cutoff = _iso(now - SEEN_WINDOW)
    return {k: batch for k, batch in json.loads(path.read_text()).items() if batch >= cutoff}


def _save_seen(path: Path, seen: dict[str, str]) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(seen, sort_keys=True))
    os.replace(tmp, path)


def _first(element: ET.Element, *paths: str) -> str | None:
    """The text at the first of `paths` that has any."""
    for path in paths:
        text = element.findtext(path)
        if text and text.strip():
            return text
    return None


def _atom_link(entry: ET.Element) -> str | None:
    for link in entry.findall(f"{_ATOM}link"):
        if link.get("rel", "alternate") == "alternate":
            return link.get("href")
    return None


def _abstract(inverted: dict | None) -> str:
    """OpenAlex keeps abstracts as {word: [positions]}. This puts the words back in order."""
    words = {i: word for word, places in (inverted or {}).items() for i in places}
    return " ".join(words[i] for i in sorted(words))


def _when(text: str | None) -> datetime | None:
    """A timestamp in either form feeds use (ISO 8601 or RFC 822), in UTC."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        when = datetime.fromisoformat(text.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(text.strip())
        except (TypeError, ValueError):
            return None
    return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _plain(text: str | None) -> str:
    return " ".join((text or "").split())


def _text(markup: str | None) -> str:
    """Plain text from HTML: tags dropped, entities decoded, whitespace collapsed."""
    return _plain(html.unescape(_TAG.sub(" ", markup or "")))


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _host(url: str) -> str | None:
    try:
        host = urllib.parse.urlsplit(url).hostname
    except ValueError:
        return None
    return host.removeprefix("www.") if host else None


def _url(base: str, params: dict) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"
