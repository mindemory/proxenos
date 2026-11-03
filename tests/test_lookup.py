"""Looking a person's address up on the web, with the search engine and every page faked out:
synthetic pages for made-up people, and no network."""

import json
import socket
import urllib.parse

import pytest

from proxenos import cli, links, lookup


def ddg(*results):
    """DuckDuckGo's HTML page with these (url, title) results, behind its redirect, after an ad."""
    ad = "https://duckduckgo.com/y.js?ad_domain=ads.example"
    rows = [f'<div class="result result--ad"><a class="result__a" href="{ad}">Ad</a></div>']
    for url, title in results:
        wrapped = "//duckduckgo.com/l/?uddg=" + urllib.parse.quote(url, safe="") + "&amp;rut=x"
        rows.append(
            f'<div class="result"><h2><a class="result__a" href="{wrapped}">{title}</a></h2>'
            '<a class="result__snippet" href="#">A <b>snippet</b>.</a></div>'
        )
    return "<html><body>" + "".join(rows) + "</body></html>"


class Web:
    """A search engine and some pages, keeping every request made."""

    def __init__(self, search, pages, searches=None):
        self.search, self.pages, self.searches = search, pages, searches or {}
        self.asked: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.asked.append((url, headers))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("q", [""])[0]
        if url.startswith(lookup.DUCKDUCKGO):
            return "text/html", self.searches.get(query, self.search).encode()
        if url not in self.pages:
            raise OSError(f"HTTP Error 404: {url}")
        return "text/html", self.pages[url].encode()

    def urls(self):
        return [url for url, _ in self.asked]


PROFILE = "https://profiles.uni.edu/ana-lee"
LAB = "https://leelab.uni.edu/people"
SCRAPED = "https://contacts.example.com/ana-lee"


def test_an_address_is_taken_only_from_the_places_own_pages_plain_or_hidden():
    web = Web(
        ddg(
            (SCRAPED, "Ana Lee email address"),
            (PROFILE, "Ana Lee | Uni Profiles"),
            (LAB, "People - Lee Lab"),
        ),
        {
            PROFILE: "<h1>Ana Lee</h1><p>Professor.</p><a href='mailto:alee@uni.edu'>Email</a>",
            LAB: "<p>Ana Lee, PI: alee [at] uni [dot] edu</p><p>Lab: office@uni.edu</p>",
            SCRAPED: "<p>Ana Lee: ana.lee@uni.edu</p>",  # a guess, on someone else's site
        },
    )

    found = lookup.email("Ana Lee", "uni.edu", web)

    assert found == {
        "address": "alee@uni.edu",
        "evidence": [PROFILE, LAB],
        "domain": "uni.edu",
        "how": "as given",
        "other": [],
    }
    assert SCRAPED not in web.urls()  # off the place's domain: never read
    assert "ads.example" not in " ".join(web.urls())
    (search, _), *_ = web.asked
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(search).query) == {
        "q": ['"Ana Lee" uni.edu email']
    }


def test_the_persons_own_address_beats_the_labs_on_more_pages():
    pages = {
        f"https://leelab.uni.edu/{n}": "<p>Lee Lab. Write to leelab@uni.edu</p>" for n in range(3)
    }
    pages[PROFILE] = "<h1>Ana Lee</h1><p>ana.lee@uni.edu</p><p>Lab: leelab@uni.edu</p>"
    results = [(url, "Lee Lab") for url in pages]

    found = lookup.email("Ana Lee", "uni.edu", Web(ddg(*results), pages))

    assert found["address"] == "ana.lee@uni.edu" and found["evidence"] == [PROFILE]
    assert found["other"] == ["leelab@uni.edu"]  # the lab's, with her name in it, comes after


def test_a_role_address_beside_the_name_is_not_theirs_and_a_neighbours_is_not_either():
    page = (
        "<ul><li>Ana Lee <a href='mailto:info@uni.edu'>Contact</a></li>"
        "<li>Ben Ode, bode@uni.edu</li><li>Cy Moe, cmoe@uni.edu</li></ul>"
    )
    web = Web(ddg((PROFILE, "People")), {PROFILE: page})

    assert lookup.email("Ana Lee", "uni.edu", web) is None
    report = lookup.look("Ana Lee", "uni.edu", web)
    assert report["read"] == [PROFILE] and "looks like Ana Lee's" in report["error"]


def test_an_address_beside_their_name_counts_and_their_initials_more():
    page = "<p>Kai Ruth Moss, director. Write to x9@uni.edu</p><p>Staff: zed@uni.edu</p>"
    web = Web(ddg((PROFILE, "Director")), {PROFILE: page})

    found = lookup.email("Kai Ruth Moss", "uni.edu", web)

    assert (found["address"], found["other"]) == ("x9@uni.edu", [])  # beside her name
    page = "<p>Kai Ruth Moss: krm@uni.edu</p><p>Kai Ruth Moss, on leave; write to x9@uni.edu</p>"
    found = lookup.email("Kai Ruth Moss", "uni.edu", Web(ddg((PROFILE, "D")), {PROFILE: page}))
    assert (found["address"], found["other"]) == ("krm@uni.edu", ["x9@uni.edu"])


@pytest.mark.parametrize(
    "written",
    [
        "alee (at) uni (dot) edu",
        "alee[at]uni.edu",
        "alee-at-uni.edu",
        "alee at uni dot edu",
        "ALEE @ UNI.EDU",
        "<a href='/cdn-cgi/l/email-protection#{}'>[email protected]</a>",
        "<span data-cfemail='{}'>[email protected]</span>",
    ],
)
def test_hidden_addresses_are_read(written):
    key = 0x42
    hidden = bytes([key, *(b ^ key for b in b"alee@uni.edu")]).hex()
    page = f"<p>Ana Lee. {written.format(hidden)}</p>"

    found = lookup.email("Ana Lee", "uni.edu", Web(ddg((PROFILE, "Ana")), {PROFILE: page}))

    assert found["address"] == "alee@uni.edu"


def test_none_when_only_other_sites_have_an_address():
    web = Web(
        ddg(
            (SCRAPED, "Ana Lee"),
            ("https://www.researchgate.net/profile/Ana-Lee", "Ana Lee"),
            (PROFILE, "Ana Lee"),
        ),
        {
            SCRAPED: "<p>Ana Lee alee@uni.edu</p>",
            "https://www.researchgate.net/profile/Ana-Lee": "<p>alee@uni.edu</p>",
            PROFILE: "<h1>Ana Lee</h1><p>Office hours on Tuesdays.</p>",
        },
    )

    assert lookup.email("Ana Lee", "uni.edu", web) is None
    assert web.urls()[1:] == [PROFILE]  # the one page of the place's own, and nothing else


def test_linkedin_is_never_read_and_comes_back_as_the_profile():
    profile = "https://www.linkedin.com/in/ana-lee-12345"
    web = Web(
        ddg((profile, "Ana Lee - Professor - Uni | LinkedIn"), (PROFILE, "Ana Lee")),
        {PROFILE: "<p>Ana Lee: alee@uni.edu</p>", profile: "<p>alee@uni.edu</p>"},
    )

    found = lookup.email("Ana Lee", "uni.edu", web)

    assert found["profile"] == profile
    assert not any("linkedin" in url for url in web.urls()[1:])
    # LinkedIn's own people aren't looked up on LinkedIn either.
    web = Web(ddg((profile, "Ana Lee | LinkedIn")), {profile: "<p>alee@linkedin.com</p>"})
    assert lookup.email("Ana Lee", "linkedin.com", web) is None
    assert web.asked == []


def test_a_result_on_this_computer_or_the_local_network_is_never_fetched(monkeypatch):
    search = ddg(
        ("http://127.0.0.1:4747/api/memory", "Ana Lee"),
        ("http://10.0.0.5/people", "Ana Lee"),
        ("https://intranet.uni.edu/people", "Ana Lee"),  # a name on the local network
    )
    resolved, dialed = [], []

    def resolve(host, port, *args, **kwargs):
        resolved.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: dialed.append(a))

    def fetch(url, headers):  # the search is faked; every page goes through links.py
        if url.startswith(lookup.DUCKDUCKGO):
            return "text/html", search.encode()
        return links._fetch(url, headers)

    report = lookup.look("Ana Lee", "uni.edu", fetch)

    assert report["address"] is None and report["read"] == []
    assert resolved == ["intranet.uni.edu"]  # the others are off the domain: not even resolved
    assert dialed == []
    assert "could be read" in report["error"]


def test_the_place_is_named_by_its_domain_a_list_or_the_first_result_like_it():
    assert lookup._place("stanford.edu") == ("stanford.edu", "as given")
    assert lookup._place("https://www.psych.ox.ac.uk/") == ("ox.ac.uk", "as given")
    assert lookup._place("Stanford University") == ("stanford.edu", "a well-known one")
    assert lookup._place("University of California, Berkeley") == (
        "berkeley.edu",
        "a well-known one",
    )
    assert lookup._place("Penn State") == ("", "")

    acme = "https://www.acmelabs.org/team"
    web = Web(
        ddg(
            ("https://www.linkedin.com/company/acme-labs", "Acme Labs | LinkedIn"),
            ("https://www.zoominfo.com/c/acme-labs", "Acme Labs - ZoomInfo"),
            ("https://news.example.com/acme", "Ana Lee joins a startup"),
            (acme, "Team"),
        ),
        {acme: "<p>Ana Lee, founder, ana@acmelabs.org</p>"},
    )

    found = lookup.email("Ana Lee", "Acme Labs", web)

    assert (found["address"], found["domain"]) == ("ana@acmelabs.org", "acmelabs.org")
    assert found["how"] == f"the first result that looked like Acme Labs's own ({acme})"


def test_with_none_of_the_places_pages_found_it_searches_the_site():
    later = '"Ana Lee" site:uni.edu'
    web = Web(
        ddg((SCRAPED, "Ana Lee")),
        {PROFILE: "<p>Ana Lee alee@uni.edu</p>"},
        searches={later: ddg((PROFILE, "Ana Lee"))},
    )

    report = lookup.look("Ana Lee", "Uni", web)  # not a known place, and no result like it
    assert report["error"] == "no result looked like Uni's own site"

    found = lookup.look("Ana Lee", "uni.edu", web)
    assert found["queries"] == ['"Ana Lee" uni.edu email', later]
    assert found["address"] == "alee@uni.edu"


def test_brave_and_searxng_are_sent_only_the_name_and_the_place(monkeypatch):
    brave = json.dumps({"web": {"results": [{"url": PROFILE, "title": "<strong>Ana</strong>"}]}})
    searx = json.dumps({"results": [{"url": PROFILE, "title": "Ana Lee", "content": "x"}]})
    asked = []

    def fetch(url, headers):
        asked.append((url, headers))
        if url.startswith(lookup.BRAVE):
            return "application/json", brave.encode()
        if url.startswith("http://127.0.0.1:8888/search?"):
            return "application/json", searx.encode()
        return "text/html", b"<p>Ana Lee alee@uni.edu</p>"

    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test-key")
    assert lookup.engine() == "brave"
    assert lookup.email("Ana Lee", "uni.edu", fetch)["address"] == "alee@uni.edu"
    url, headers = asked[0]
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["q"] == [
        '"Ana Lee" uni.edu email'
    ]
    assert headers["X-Subscription-Token"] == "test-key"

    monkeypatch.setenv("PROXENOS_SEARXNG_URL", "http://127.0.0.1:8888/")
    assert (lookup.engine(), lookup.engine_host()) == ("searxng", "127.0.0.1")
    asked.clear()
    assert lookup.email("Ana Lee", "uni.edu", fetch)["evidence"] == [PROFILE]
    url, headers = asked[0]
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query) == {
        "q": ['"Ana Lee" uni.edu email'],
        "format": ["json"],
    }
    assert "X-Subscription-Token" not in headers  # the Brave key goes only to Brave


def test_a_failed_search_says_so_and_finds_nothing():
    report = lookup.look("Ana Lee", "uni.edu")  # the network is off in tests

    assert report["address"] is None
    assert report["error"] == "the search failed: no web lookups in tests"
    # A puzzle for a person instead of results is said, never tried.
    puzzle = Web('<div class="anomaly-modal__title">Select all squares with a duck</div>', {})
    report = lookup.look("Ana Lee", "uni.edu", puzzle)
    assert "DuckDuckGo asked whether this is a person" in report["error"]
    assert len(puzzle.asked) == 1


def test_off_means_nothing_is_asked(monkeypatch):
    web = Web(ddg((PROFILE, "Ana")), {PROFILE: "<p>Ana Lee alee@uni.edu</p>"})
    monkeypatch.setenv("PROXENOS_LOOKUP", "off")

    assert lookup.email("Ana Lee", "uni.edu", web) is None
    assert web.asked == []
    assert lookup.for_answer({"lookup": {"name": "Ana Lee", "org": "uni.edu"}}, web) == ("", None)


def test_the_command_prints_the_whole_lookup(monkeypatch, capsys):
    web = Web(ddg((PROFILE, "Ana")), {PROFILE: "<p>Ana Lee alee@uni.edu</p>"})
    monkeypatch.setattr(lookup, "_fetch", web)

    cli.main(["lookup", "email", "Ana Lee", "--org", "uni.edu"])

    printed = json.loads(capsys.readouterr().out)
    assert printed["address"] == "alee@uni.edu" and printed["read"] == [PROFILE]
    assert printed["engine"] == "duckduckgo"


def test_an_answer_gets_what_was_found_with_its_pages_or_that_none_was():
    web = Web(ddg((PROFILE, "Ana")), {PROFILE: "<p>Ana Lee alee@uni.edu</p>"})

    said, found = lookup.for_answer({"lookup": {"name": "Ana Lee", "org": "uni.edu"}}, web)

    assert "alee@uni.edu" in said and f"]({PROFILE})" in said
    assert found["address"] == "alee@uni.edu" and found["evidence"] == [PROFILE]
    assert lookup.for_answer({"lookup": {"name": " ", "org": "uni.edu"}}, web) == ("", None)
    said, found = lookup.for_answer({"lookup": {"name": "Ana Lee", "org": ""}}, web)
    assert "say where Ana Lee is" in said and found["address"] is None
    said, _ = lookup.for_answer({"lookup": {"name": "Ben Ode", "org": "uni.edu"}}, web)
    assert "No address on uni.edu's pages looks like Ben Ode's" in said and "@" not in said
