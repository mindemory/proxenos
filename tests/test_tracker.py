"""Tracker clone against fake sources and a fake model. No network, no key, no real data."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from twin import llm
from twin.clones import tracker

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
BATCH = "2026-03-10T12:00:00Z"


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


SOURCES = {
    "arxiv": {"categories": ["q-bio.NC"], "queries": []},
    "openalex": {"queries": ["working memory"]},
    "feeds": [
        {"url": "https://blog.example.com/feed.xml", "kind": "post"},
        {"url": "https://down.example.com/rss", "kind": "news"},
        {"url": "https://garbled.example.com/atom", "kind": "news"},
    ],
    "hackernews": True,
}

LONG_ABSTRACT = "We record from synthetic neurons. " * 30

ARXIV = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2603.01234v2</id>
    <published>{ago(hours=19)}</published>
    <title>Attractor dynamics
      in working memory</title>
    <summary>{LONG_ABSTRACT}</summary>
    <author><name>Ada Example</name></author>
    <author><name>Bo Sample</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2603.00042v1</id>
    <published>{ago(days=4)}</published>
    <title>Announced late, after a weekend</title>
    <summary>Still inside arXiv's longer window.</summary>
    <author><name>Cy Placeholder</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2602.09999v1</id>
    <published>{ago(days=9)}</published>
    <title>Too old</title>
    <summary>Outside every window.</summary>
  </entry>
</feed>""".encode()

OPENALEX = json.dumps(
    {
        "results": [
            {  # arXiv's paper again, by its arXiv DOI
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.48550/arXiv.2603.01234",
                "title": "Attractor dynamics in working memory",
                "publication_date": NOW.date().isoformat(),
                "authorships": [{"author": {"display_name": "Ada Example"}}],
                "abstract_inverted_index": None,
            },
            {
                "id": "https://openalex.org/W2",
                "doi": "https://doi.org/10.5555/Synthetic.42",
                "title": "Gain control in <i>synthetic</i> cortex",
                "publication_date": (NOW - timedelta(days=1)).date().isoformat(),
                "authorships": [
                    {"author": {"display_name": "Di Fictional"}},
                    {"author": {"display_name": "Ed Madeup"}},
                ],
                "abstract_inverted_index": {"Neurons": [0], "fire": [1, 3], "and": [2]},
            },
        ]
    }
).encode()

RSS = f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example Science Blog</title>
    <item>
      <title>Notes on &lt;em&gt;rowing&lt;/em&gt; physiology</title>
      <link>https://blog.example.com/posts/rowing/?utm_source=rss</link>
      <pubDate>{(NOW - timedelta(hours=3)).strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate>
      <dc:creator>A. Writer</dc:creator>
      <description>&lt;p&gt;Lactate &amp;amp; you&lt;/p&gt;</description>
    </item>
    <item>
      <title>An old post</title>
      <link>https://blog.example.com/posts/old</link>
      <pubDate>Mon, 02 Feb 2026 08:00:00 +0000</pubDate>
    </item>
    <item>
      <title>A post with no date</title>
      <link>https://blog.example.com/posts/undated</link>
    </item>
  </channel>
</rss>""".encode()

HN = json.dumps(
    {
        "hits": [
            {  # the blog post again, without the tracking parameter
                "objectID": "101",
                "title": "Notes on rowing physiology",
                "url": "https://www.blog.example.com/posts/rowing",
                "created_at": ago(hours=2),
                "points": 50,
                "num_comments": 7,
                "author": "someone",
            },
            {
                "objectID": "102",
                "title": "Ask HN: What do you read on Sundays?",
                "url": None,
                "story_text": "<p>Looking for long reads &amp; essays.</p>",
                "created_at": ago(hours=1),
                "points": 120,
                "num_comments": 45,
                "author": "asker",
            },
        ]
    }
).encode()


class FakeWeb:
    """Stands in for the network: serves bodies by URL prefix and records every request. An
    exception in place of a body is raised; an unknown URL is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        for prefix, body in self.routes.items():
            if url.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return body
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)


def web():
    return FakeWeb(
        {
            tracker.ARXIV_URL: ARXIV,
            tracker.OPENALEX_URL: OPENALEX,
            tracker.HN_URL: HN,
            "https://blog.example.com/feed.xml": RSS,
            "https://down.example.com/": urllib.error.URLError("timed out"),
            "https://garbled.example.com/": b"<feed><entry>",
        }
    )


PROPOSED = {
    "arxiv": {"categories": ["q-bio.NC"], "queries": ["working memory"]},
    "openalex": {"queries": ["gain control"]},
    "feeds": [{"url": "https://blog.example.com/feed.xml", "kind": "post"}],
    "hackernews": False,
}


class FakeModel:
    """Stands in for llm.ask. Proposes PROPOSED as sources, and scores each candidate by its
    title from `verdicts` ({title: (score, explore)}), 0.5 and core by default."""

    def __init__(self):
        self.calls = []
        self.verdicts = {}

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=16000):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        if "hackernews" in schema["properties"]:
            return PROPOSED
        ranked = []
        for short_id, title in re.findall(r"^\[(c\d+)\] .*\n(.*)$", prompt, re.MULTILINE):
            score, explore = self.verdicts.get(title, (0.5, False))
            why = f"Close to what they said about {title.split()[0].lower()}."
            ranked.append(
                {
                    "id": short_id,
                    "score": score,
                    "why": why,
                    "interest": "memory",
                    "explore": explore,
                }
            )
        return {"ranked": ranked}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Anything that slips past the fakes fails here instead of reaching the network or model.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("live HTTP"))
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setattr(tracker, "ARXIV_PAUSE", 0)


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def make_vault(tmp_path, sources=SOURCES):
    vault = tmp_path / "vault"
    (vault / "self").mkdir(parents=True)
    (vault / "self" / "interests.md").write_text("# Interests\n- working memory\n- rowing\n")
    (vault / "self" / "taste.md").write_text("# Taste\nCareful empirical work over hype.\n")
    if sources is not None:
        (vault / "tracker").mkdir()
        (vault / "tracker" / "sources.json").write_text(json.dumps(sources))
    return vault


def stored(vault):
    out = vault / "tracker" / "items"
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["title"]: r for r in map(json.loads, lines)}


def track(vault, fake_web, **kwargs):
    return tracker.track(vault, fetch=fake_web, now=NOW, **kwargs)


def test_without_a_profile_the_run_stops_and_says_how_to_build_one(tmp_path, model):
    vault = tmp_path / "vault"
    (vault / "self").mkdir(parents=True)
    fake_web = web()

    with pytest.raises(SystemExit, match="twin master"):
        track(vault, fake_web)
    assert model.calls == [] and fake_web.requested == []


def test_first_run_proposes_sources_from_the_profile_and_only_my_shared_domains(tmp_path, model):
    vault = make_vault(tmp_path, sources=None)
    (vault / "self" / "identity.md").write_text("A synthetic person.\n")
    messages = vault / "raw" / "whatsapp" / "messages"
    messages.mkdir(parents=True)
    records = [
        {"from_me": True, "kind": "link", "text": "remember https://www.example.org/a"},
        {"from_me": True, "kind": "link", "text": "https://example.org/b https://example.org/c"},
        {"from_me": True, "kind": "link", "text": "https://news.example.com/story"},
        {"from_me": False, "kind": "link", "text": "https://friend.example.net/secret"},
        {"from_me": True, "kind": "text", "text": "typed https://typed.example.com/x"},
        {"from_me": True, "kind": "link", "text": None},
    ]
    (messages / "2026-03.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))

    track(vault, FakeWeb({}))

    proposal = model.calls[0]
    assert "- working memory" in proposal["system"] and "A synthetic person." in proposal["system"]
    # Domains only, most shared first, counted once per message and only from my own links.
    assert proposal["prompt"].split("most shared first:\n")[1] == "example.org\nnews.example.com"
    for leak in ("friend", "typed", "secret", "remember", "/story"):
        assert leak not in proposal["prompt"]
    saved = vault / "tracker" / "sources.json"
    assert json.loads(saved.read_text()) == PROPOSED

    # The file is mine from now on: edits stick and the model isn't asked again.
    saved.write_text(json.dumps({"feeds": ["https://blog.example.com/feed.xml"]}))
    model.calls.clear()
    fake_web = FakeWeb({})
    track(vault, fake_web)
    assert all("hackernews" not in c["schema"]["properties"] for c in model.calls)
    assert fake_web.requested == ["https://blog.example.com/feed.xml"]


def test_each_source_normalizes_to_the_same_fields():
    paper = tracker.parse_arxiv(ARXIV)[0]
    assert paper == {
        "id": tracker.item_id("https://arxiv.org/abs/2603.01234"),
        "url": "https://arxiv.org/abs/2603.01234",
        "title": "Attractor dynamics in working memory",
        "source": "arXiv",
        "kind": "paper",
        "published": ago(hours=19),
        "authors": ["Ada Example", "Bo Sample"],
        "summary": paper["summary"],
    }
    assert len(paper["summary"]) <= tracker.SUMMARY_CHARS and paper["summary"].endswith("…")

    work = tracker.parse_openalex(OPENALEX)[1]
    assert work["url"] == "https://doi.org/10.5555/Synthetic.42"
    assert (work["title"], work["summary"]) == (
        "Gain control in synthetic cortex",
        "Neurons fire and fire",
    )
    assert work["published"] == "2026-03-09T00:00:00Z"
    assert work["authors"] == ["Di Fictional", "Ed Madeup"]

    post = tracker.parse_feed(RSS, kind="post")[0]
    assert (post["title"], post["summary"]) == ("Notes on rowing physiology", "Lactate & you")
    assert (post["source"], post["authors"]) == ("Example Science Blog", ["A. Writer"])
    assert post["published"] == ago(hours=3)

    ask = tracker.parse_hn(HN)[1]
    assert ask["url"] == "https://news.ycombinator.com/item?id=102"
    assert (
        ask["summary"]
        == "120 points and 45 comments on Hacker News. Looking for long reads & essays."
    )
    assert (ask["kind"], ask["source"], ask["authors"]) == ("news", "Hacker News", [])


RSS1 = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel><title>Example Journal</title></channel>
  <item>
    <title>A new result</title>
    <link>https://journal.example.org/articles/1</link>
    <description>What they found.</description>
    <dc:creator>Fay Notreal</dc:creator>
    <dc:date>2026-03-09T08:00:00+01:00</dc:date>
  </item>
</rdf:RDF>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Journal</title>
  <entry>
    <title type="html">A &lt;b&gt;new&lt;/b&gt; result</title>
    <link rel="replies" href="https://journal.example.org/articles/1#comments"/>
    <link href="https://journal.example.org/articles/1"/>
    <updated>2026-03-09T07:00:00Z</updated>
    <author><name>Fay Notreal</name></author>
    <content type="html">&lt;p&gt;What they found.&lt;/p&gt;</content>
  </entry>
</feed>"""


@pytest.mark.parametrize("body", [RSS1, ATOM], ids=["rss1", "atom"])
def test_rdf_and_atom_feeds_read_like_rss(body):
    assert tracker.parse_feed(body, kind="news") == [
        {
            "id": tracker.item_id("https://journal.example.org/articles/1"),
            "url": "https://journal.example.org/articles/1",
            "title": "A new result",
            "source": "Example Journal",
            "kind": "news",
            "published": "2026-03-09T07:00:00Z",
            "authors": ["Fay Notreal"],
            "summary": "What they found.",
        }
    ]


@pytest.mark.parametrize(
    "url, normal",
    [
        ("http://www.Example.com/a/b/?utm_source=x&z=2&a=1#top", "https://example.com/a/b?a=1&z=2"),
        ("https://example.com/a?ref=feed&fbclid=xyz", "https://example.com/a"),
        ("http://arxiv.org/abs/2603.01234v2", "https://arxiv.org/abs/2603.01234"),
        ("https://arxiv.org/pdf/2603.01234v1.pdf", "https://arxiv.org/abs/2603.01234"),
        ("https://doi.org/10.48550/arXiv.2603.01234", "https://arxiv.org/abs/2603.01234"),
        ("https://export.arxiv.org/abs/hep-th/9901001v3", "https://arxiv.org/abs/hep-th/9901001"),
        ("https://dx.doi.org/10.5555/ABC.1", "https://doi.org/10.5555/abc.1"),
    ],
)
def test_links_to_the_same_thing_normalize_alike(url, normal):
    assert tracker.normalize_url(url) == normal


def test_a_run_dedupes_ranks_stores_and_skips_failing_sources(tmp_path, model):
    vault = make_vault(tmp_path)
    model.verdicts = {"Gain control in synthetic cortex": (0.9, True)}
    fake_web = web()

    stats = track(vault, fake_web)

    # 2 arXiv in window + 2 OpenAlex + 1 blog post + 2 HN, of which 2 are repeats.
    assert stats == {"fetched": 7, "new": 5, "kept": 5, "sources_failed": 2}
    arxiv_query, openalex_query = (
        urllib.parse.parse_qs(urllib.parse.urlsplit(u).query) for u in fake_web.requested[:2]
    )
    assert arxiv_query["search_query"] == ["cat:q-bio.NC"]
    assert arxiv_query["sortBy"] == ["submittedDate"]
    assert openalex_query["filter"] == [
        "from_publication_date:2026-03-08,to_publication_date:2026-03-10"
    ]
    assert not {"mailto", "email"} & openalex_query.keys()

    ranking = model.calls[-1]
    # The profile is the system prompt, so it's cached across runs.
    assert ranking["system"] == tracker.read_profile(vault / "self")
    assert "- rowing" in ranking["system"] and "Careful empirical work" in ranking["system"]
    assert ranking["effort"] == "medium" and "ranked" in ranking["schema"]["properties"]
    assert "They haven't reacted to any recent picks yet." in ranking["prompt"]

    items = stored(vault)
    assert set(items) == {
        "Attractor dynamics in working memory",
        "Announced late, after a weekend",
        "Gain control in synthetic cortex",
        "Notes on rowing physiology",
        "Ask HN: What do you read on Sundays?",
    }
    assert items["Gain control in synthetic cortex"] == {
        "id": tracker.item_id("https://doi.org/10.5555/synthetic.42"),
        "ts": BATCH,
        "batch": BATCH,
        "url": "https://doi.org/10.5555/Synthetic.42",
        "title": "Gain control in synthetic cortex",
        "source": "OpenAlex",
        "kind": "paper",
        "published": "2026-03-09T00:00:00Z",
        "authors": ["Di Fictional", "Ed Madeup"],
        "summary": "Neurons fire and fire",
        "score": 0.9,
        "why": "Close to what they said about gain.",
        "interest": "memory",
        "explore": True,
        "by": "twin",
    }
    assert items["Attractor dynamics in working memory"]["source"] == "arXiv"  # arXiv's copy wins
    assert items["Notes on rowing physiology"]["source"] == "Example Science Blog"
    assert all(re.fullmatch(r"[0-9a-f]{16}", item["id"]) for item in items.values())

    # Nothing new next time, so no ranking call and nothing rewritten.
    model.calls.clear()
    again = track(vault, web())
    assert again == {"fetched": 7, "new": 0, "kept": 0, "sources_failed": 2}
    assert model.calls == []


def test_candidates_passed_over_are_not_offered_again(tmp_path, model):
    vault = make_vault(tmp_path, sources={"hackernews": True})
    model.verdicts = {"Ask HN: What do you read on Sundays?": (0.1, False)}

    assert track(vault, web(), max_items=1)["kept"] == 1
    assert list(stored(vault)) == ["Notes on rowing physiology"]

    model.calls.clear()
    assert track(vault, web(), max_items=1) == {
        "fetched": 2,
        "new": 0,
        "kept": 0,
        "sources_failed": 0,
    }
    assert model.calls == []


def test_recent_reactions_reach_the_ranking_prompt(tmp_path, model):
    vault = make_vault(tmp_path, sources={"hackernews": True})
    items = vault / "tracker" / "items"
    items.mkdir()
    old = [
        {"id": f"i{n}", "ts": "2026-02-20T00:00:00Z", "title": f"Earlier pick {n}"}
        for n in range(6)
    ]
    (items / "2026-02.jsonl").write_text("".join(json.dumps(r) + "\n" for r in old))
    feedback = [
        {"item_id": "i0", "action": "useful", "ts": ago(days=1)},
        {"item_id": "i1", "action": "not_me", "ts": ago(days=2)},
        {"item_id": "i2", "action": "save", "ts": ago(days=3)},
        {"item_id": "i3", "action": "open", "ts": ago(days=1)},  # opens aren't reactions
        {"item_id": "i4", "action": "useful", "ts": ago(days=20)},  # too long ago
        {"item_id": "gone", "action": "useful", "ts": ago(days=1)},  # no such item
    ]
    lines = [json.dumps(f) for f in feedback] + ['{"item_id": "i5", "act', ""]
    (vault / "tracker" / "feedback.jsonl").write_text("\n".join(lines))

    track(vault, web())

    prompt = model.calls[-1]["prompt"]
    assert "- useful: Earlier pick 0\n- save: Earlier pick 2\n- not_me: Earlier pick 1" in prompt
    assert "Earlier pick 3" not in prompt and "Earlier pick 4" not in prompt


def verdict(n, score, explore=False):
    return {"id": f"x{n}", "score": score, "explore": explore}


def test_about_a_fifth_of_the_slots_are_held_for_explore_picks():
    core = [verdict(n, 0.9 - n / 20) for n in range(10)]
    explore = [verdict(10, 0.3, True), verdict(11, 0.2, True), verdict(12, 0.1, True)]

    kept = tracker.select(core + explore, max_items=5)
    assert [r["id"] for r in kept] == ["x0", "x1", "x2", "x3", "x10"]

    kept = tracker.select(core + explore, max_items=10)
    assert [r["id"] for r in kept][-2:] == ["x10", "x11"]

    # Explore picks that score well take open slots too.
    strong = [verdict(20, 0.99, True), verdict(21, 0.98, True)]
    kept = tracker.select(core + strong, max_items=5)
    assert [r["id"] for r in kept] == ["x20", "x21", "x0", "x1", "x2"]


def test_big_batches_are_trimmed_newest_first_from_each_source_in_turn():
    def candidate(source, hours):
        return {"source": source, "published": ago(hours=hours)}

    busy = [candidate("busy", h) for h in range(200)]
    quiet = [candidate("quiet", 100 + h) for h in range(5)]

    pool = tracker.trim(busy + quiet, 20)
    assert len(pool) == 20
    assert [c for c in pool if c["source"] == "quiet"] == quiet
    assert [c for c in pool if c["source"] == "busy"] == busy[:15]
    assert tracker.trim(quiet, 20) == quiet
