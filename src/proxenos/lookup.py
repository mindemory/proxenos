"""Finding a person's public email address on the web, the way a person would, when the user's
records don't have it.

Given a name and a place ("Kalanit Grill-Spector" at "Stanford"), it:
1. names the place's domain: as given when it's one ("stanford.edu"), else from a short list of
   well-known places (KNOWN), else from the search below: the first result that isn't a site
   about everyone (LinkedIn, ResearchGate, Wikipedia, people finders: ELSEWHERE) and whose
   address or title has the place's name in it;
2. searches for `"<name>" <place> email`, and when that finds none of the place's pages, for
   `"<name>" site:<domain>`, one request at a time;
3. reads at most PAGES of the results on that domain or its subdomains, and no other page;
4. takes the addresses on them, written out, as mailto links, or hidden ("name [at] stanford
   [dot] edu", "name-at-stanford.edu", Cloudflare's), and keeps those on the place's domain that
   look like the person's: their name in it, or the first address after their name on a page.
   A role's address (info@, lab@, admin@) counts only with their name in it;
5. ranks them: the person's own name in it first, then by how many of the pages give it.

The best comes back with every page it was on, the others that qualified, and a LinkedIn profile
when a result is one (it's never fetched). When none qualifies, there's no address: nothing is
ever made from the name (first.last@domain is a guess, and a wrong address is worse than none).

What goes out: the person's name and the place, to the search engine, and requests for that
place's own public pages. Nothing about the user. The engine is the user's own SearXNG when
PROXENOS_SEARXNG_URL names one (its JSON API, which has to be on in its settings), else Brave
Search's API with a BRAVE_SEARCH_KEY, else DuckDuckGo's HTML page. Pages are read through
links.py's fetching, so only from hosts on the public internet, on ports 80 and 443, capped in
size and time: a result can't point it at this computer or the local network. Every request
names Proxenos in its User-Agent. PROXENOS_LOOKUP=off turns it all off.

Errands look up whom they can't reach (clones/errands.py), and Ask and Think when they're asked
for someone's address: the model only names whom to look up (FIELD), and what's found is added
to its answer by code (`for_answer`), so the model never writes the address itself.
"""

import argparse
import bisect
import html
import ipaddress
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser

from proxenos import links
from proxenos.config import env, load

PAGES = 5  # of the place's own pages, read at most
RESULTS = 10  # results read from a search
OTHERS = 5  # other addresses listed beside the best
AFTER = 250  # characters after a name in which the first address is "beside" it
PACE = 1.0  # seconds between two searches
TEXT_CHARS = 400_000  # of a page, searched for addresses
NAME_CHARS, ORG_CHARS = 120, 160
USER_AGENT = (
    "Mozilla/5.0 (compatible; Proxenos/0.1; +https://github.com/mindemory/proxenos; "
    "a person's public email address, one request at a time)"
)
DUCKDUCKGO = "https://html.duckduckgo.com/html/"
BRAVE = "https://api.search.brave.com/res/v1/web/search"

# Takes a URL and headers to add, and returns the response's content type and body, raising the
# way urlopen does.
Fetch = Callable[[str, dict[str, str]], tuple[str, bytes]]

# Well-known places, by their name's own words (the generic ones left out, see _GENERIC).
KNOWN = {
    "stanford": "stanford.edu", "harvard": "harvard.edu", "mit": "mit.edu",
    "massachusetts technology": "mit.edu", "yale": "yale.edu", "princeton": "princeton.edu",
    "columbia": "columbia.edu", "cornell": "cornell.edu", "dartmouth": "dartmouth.edu",
    "brown": "brown.edu", "penn": "upenn.edu", "upenn": "upenn.edu",
    "pennsylvania": "upenn.edu", "caltech": "caltech.edu", "california technology": "caltech.edu",
    "berkeley": "berkeley.edu", "uc berkeley": "berkeley.edu",
    "california berkeley": "berkeley.edu", "ucla": "ucla.edu",
    "california los angeles": "ucla.edu", "ucsd": "ucsd.edu", "uc san diego": "ucsd.edu",
    "california san diego": "ucsd.edu", "ucsf": "ucsf.edu", "california san francisco": "ucsf.edu",
    "nyu": "nyu.edu", "new york": "nyu.edu", "cmu": "cmu.edu", "carnegie mellon": "cmu.edu",
    "chicago": "uchicago.edu", "uchicago": "uchicago.edu", "johns hopkins": "jhu.edu",
    "jhu": "jhu.edu", "michigan": "umich.edu", "umich": "umich.edu", "oxford": "ox.ac.uk",
    "cambridge": "cam.ac.uk", "ucl": "ucl.ac.uk", "imperial": "imperial.ac.uk",
    "eth zurich": "ethz.ch", "eth": "ethz.ch", "epfl": "epfl.ch", "toronto": "utoronto.ca",
    "mcgill": "mcgill.ca", "nih": "nih.gov",
}  # fmt: skip
# Words of a place's name that don't tell one place from another.
_GENERIC = {
    "the", "of", "at", "for", "and", "in", "university", "univ", "college", "institute",
    "school", "department", "dept", "lab", "labs", "laboratory", "center", "centre", "group",
    "inc", "llc", "ltd", "corp", "company", "co", "gmbh", "plc",
}  # fmt: skip
_STOP = {"of", "the", "and", "for", "at", "in"}  # left out of a place's initials
# Sites about everyone: never a place's own, whatever a search ranks first.
ELSEWHERE = {
    "linkedin.com", "researchgate.net", "google.com", "wikipedia.org", "academia.edu",
    "orcid.org", "x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com",
    "github.com", "medium.com", "substack.com", "semanticscholar.org", "dblp.org",
    "ratemyprofessors.com", "rocketreach.co", "zoominfo.com", "contactout.com",
    "signalhire.com", "lusha.com", "apollo.io", "crunchbase.com", "glassdoor.com", "indeed.com",
    "duckduckgo.com", "bing.com", "yahoo.com", "reddit.com", "wikidata.org",
}  # fmt: skip
# A local part that is a role's, not a person's: info@, lab-admin@, office@.
_ROLES = {
    "info", "contact", "admin", "administrator", "office", "lab", "labs", "help", "support",
    "webmaster", "web", "dept", "department", "inquiries", "enquiries", "hr", "jobs", "careers",
    "press", "media", "news", "events", "registrar", "admissions", "noreply", "postmaster",
    "secretary", "reception", "team", "hello", "general", "mail", "frontdesk", "feedback",
    "communications", "it", "staff", "students", "questions", "group", "manager", "coordinator",
}  # fmt: skip
_ROLE_END = re.compile(r"(?:lab|labs|group|admin|office|info|team)$|^(?:lab|info|admin|office)")
_TITLES = {"dr", "prof", "professor", "mr", "ms", "mrs", "mx", "phd", "md", "jr", "sr"}
# Second-level labels under which a country's registered domains sit (ox.ac.uk, co.uk).
_SECOND = {"ac", "co", "com", "edu", "gov", "net", "org"}

_DOMAIN = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}")
_ADDRESS = re.compile(r"[a-z0-9][a-z0-9._%+-]*@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
# How pages hide an address from harvesters, written back as one: "[at]", "(dot)", "-at-",
# " @ ", and "name at place dot edu" spelled out.
_AT = re.compile(r"\s*[\[({<]\s*at\s*[\])}>]\s*|\s+@\s+|(?<=[a-z0-9])-at-(?=[a-z0-9])")
_DOT = re.compile(r"\s*[\[({<]\s*dot\s*[\])}>]\s*|(?<=[a-z0-9])-dot-(?=[a-z0-9])")
_SPELLED = re.compile(r"\b([a-z0-9][a-z0-9._+-]*)\s+at\s+([a-z0-9-]+(?:\s+dot\s+[a-z0-9-]+)+)\b")
_DOTS_AFTER = re.compile(r"@([a-z0-9-]+(?:(?:\.|\s+dot\s+)[a-z0-9-]+)+)")
# DuckDuckGo's page asking whether a person is searching (a CAPTCHA), instead of results.
_CHALLENGE = re.compile(r"anomaly-modal|bots use duckduckgo too", re.IGNORECASE)

# What a dead, slow, refused or garbled answer raises (links') and an answer that isn't JSON.
_FAILURES = (*links._FAILURES, KeyError, TypeError, AttributeError)


def on() -> bool:
    """Whether people may be looked up on the web: unless PROXENOS_LOOKUP says off."""
    return env("LOOKUP", "on").strip().casefold() not in ("off", "0", "no", "false")


def engine() -> str:
    """The search engine: "searxng", "brave" or "duckduckgo", as the module's notes say."""
    load()
    if _searxng():
        return "searxng"
    return "brave" if os.environ.get("BRAVE_SEARCH_KEY", "").strip() else "duckduckgo"


def engine_host() -> str:
    """Where searches go, for the Privacy view: the host, never a key."""
    kind = engine()
    if kind == "searxng":
        return urllib.parse.urlsplit(_searxng()).hostname or ""
    return urllib.parse.urlsplit(BRAVE if kind == "brave" else DUCKDUCKGO).hostname or ""


def email(name: str, org: str, fetch: Fetch | None = None) -> dict | None:
    """The person's address from their place's own pages, {address, evidence: [the pages it's
    on], domain, how (the domain was chosen), other: [addresses], profile?}, or None when no
    address there looks like theirs (or lookups are off, or the search failed)."""
    report = look(name, org, fetch)
    if not report["address"]:
        return None
    found = {k: report[k] for k in ("address", "evidence", "domain", "how", "other")}
    return found | ({"profile": report["profile"]} if report["profile"] else {})


def look(name: str, org: str, fetch: Fetch | None = None) -> dict:
    """The whole lookup, as the command prints it: what was searched and where, the domain and
    how it was chosen, the pages read, and the address with the pages it's on, or why there's
    none (`error`)."""
    name, org = _one_line(name)[:NAME_CHARS], _one_line(org)[:ORG_CHARS]
    report = {
        "name": name,
        "org": org,
        "engine": engine(),
        "queries": [],
        "domain": "",
        "how": "",
        "read": [],
        "address": None,
        "evidence": [],
        "other": [],
        "profile": "",
        "error": None,
    }
    if not on():
        return report | {"error": "looking people up on the web is off (PROXENOS_LOOKUP)"}
    if not _names(name) or not org:
        return report | {"error": "a lookup needs a person's name and where they are"}
    fetch = fetch or _fetch  # looked up now, so a test can stand in for the network
    domain, how = _place(org)
    if domain == "linkedin.com":
        return report | {"domain": domain, "how": how, "error": "LinkedIn's pages are never read"}

    def search(query: str) -> list[dict]:
        if report["queries"]:
            time.sleep(PACE)
        report["queries"].append(query)
        return _search(query, fetch)

    try:
        results = search(f'"{name}" {org} email')
        report["profile"] = _profile(results, name)
        if not domain:
            picked = _domain_from(results, org)
            if picked is None:
                return report | {"error": f"no result looked like {org}'s own site"}
            domain, how = picked[0], f"the first result that looked like {org}'s own ({picked[1]})"
        report |= {"domain": domain, "how": how}
        pages = _pages(results, domain)
        if not pages:
            pages = _pages(search(f'"{name}" site:{domain}'), domain)
    except _FAILURES as e:
        why = f"the search failed: {_said(e)}"
        if report["engine"] == "searxng":
            why += " (SearXNG answers only with json among its search formats)"
        return report | {"error": why}

    found: dict[str, dict] = {}
    for url in pages:
        try:
            kind, body = fetch(url, {})
        except _FAILURES:
            continue
        if kind not in links._READABLE:
            continue
        report["read"].append(url)
        for address, marks in _on_page(_page_text(kind, body), name, domain).items():
            entry = found.setdefault(address, {"pages": [], "tier": 0, "beside": 0})
            entry["pages"].append(url)
            entry["tier"] = max(entry["tier"], marks["tier"])
            entry["beside"] += marks["beside"]
    ranked = sorted(found, key=lambda a: _rank(found[a]), reverse=True)
    if ranked:
        best = ranked[0]
        return report | {
            "address": best,
            "evidence": found[best]["pages"],
            "other": ranked[1:][:OTHERS],
        }
    if report["read"]:
        why = f"no address on {domain}'s pages looks like {name}'s"
    elif pages:
        why = f"none of {domain}'s own pages could be read"
    else:
        why = f"the search found none of {domain}'s own pages"
    return report | {"error": why}


def _rank(entry: dict) -> tuple:
    """An address's place among those found: how plainly it's the person's, then on how many of
    the pages, then how often beside their name."""
    return entry["tier"], len(entry["pages"]), entry["beside"]


# What Ask and Think add to an answer.

FIELD = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "org": {"type": "string"}},
    "required": ["name", "org"],
    "additionalProperties": False,
}
ASKED = (
    "When {person} asks for someone's email address or how to reach someone, fill `lookup` with "
    "that person's name and where they are (a university, a company, a lab), as {person} or the "
    'records name them ("" when nothing says); otherwise leave it out. Never write an address '
    "you weren't given: Proxenos looks on that place's own web pages and adds what it finds, "
    "with the pages it's on."
)


def wanted(answer: object) -> tuple[str, str] | None:
    """The (name, place) a model's answer asks to look up, or None."""
    asked = answer.get("lookup") if isinstance(answer, dict) else None
    if not isinstance(asked, dict) or not _names(_one_line(asked.get("name"))):
        return None
    return _one_line(asked.get("name")), _one_line(asked.get("org"))


def for_answer(answer: object, fetch: Fetch | None = None) -> tuple[str, dict | None]:
    """What an Ask or Think answer that names someone to look up gets added to it, in markdown,
    and what was found ({name, org, address, evidence, domain, other, profile, error}); ("",
    None) when it names no one or lookups are off."""
    asked = wanted(answer)
    if asked is None or not on():
        return "", None
    name, org = asked
    if not org:
        said = (
            f"**From the web:** say where {name} is (a university or a company) and Proxenos "
            "can look for their address on its own pages. It never guesses one."
        )
        return said, {"name": name, "org": "", "address": None, "error": "no place named"}
    report = look(name, org, fetch)
    kept = ("name", "org", "address", "evidence", "domain", "other", "profile", "error")
    return note(report), {k: report[k] for k in kept}


def note(report: dict) -> str:
    """A lookup in a few lines of markdown: the address and the pages it's on, or why there's
    none. Only an address the pages gave."""
    name, domain = report["name"], report["domain"]
    if not report["address"]:
        why = report["error"] or f"no address for {name} was found"
        return f"**From the web:** {why[0].upper()}{why[1:]}. Proxenos never guesses an address."
    pages = report["evidence"]
    on = f"on {_count(len(pages), 'page')} of {domain}'s own"
    lines = [f"**From the web:** {report['address']}, {on}:"]
    lines += [f"- [{_shown(url)}]({url})" for url in pages]
    if report["other"]:
        lines.append(f"\nAlso there: {', '.join(report['other'])}.")
    if report["profile"]:
        lines.append(f"\nLinkedIn: [{_shown(report['profile'])}]({report['profile']})")
    lines.append("\nCheck it's theirs before you write: it's from public pages, not your records.")
    return "\n".join(lines)


# Searching.


def _search(query: str, fetch: Fetch) -> list[dict]:
    """The results of one search, {url, title, snippet}, from the engine set up."""
    kind = engine()
    if kind == "searxng":
        url = f"{_searxng()}/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        data = json.loads(fetch(url, {"Accept": "application/json"})[1])
        found = [
            (r.get("url"), r.get("title"), r.get("content")) for r in data.get("results") or []
        ]
    elif kind == "brave":
        key = os.environ["BRAVE_SEARCH_KEY"].strip()
        url = f"{BRAVE}?" + urllib.parse.urlencode({"q": query, "count": RESULTS})
        data = json.loads(
            fetch(url, {"Accept": "application/json", "X-Subscription-Token": key})[1]
        )
        listed = (data.get("web") or {}).get("results") or []
        found = [(r.get("url"), r.get("title"), r.get("description")) for r in listed]
    else:
        url = f"{DUCKDUCKGO}?" + urllib.parse.urlencode({"q": query})
        page = fetch(url, {})[1].decode("utf-8", errors="replace")
        if _CHALLENGE.search(page):  # a puzzle for a person to solve: never tried
            raise OSError(
                "DuckDuckGo asked whether this is a person, and it isn't answered; set up Brave "
                "Search or your own SearXNG for lookups"
            )
        parser = _DuckDuckGo()
        parser.feed(page)
        parser.close()
        found = [(r["url"], r["title"], r["snippet"]) for r in parser.results]
    return [
        {"url": u, "title": _plain_text(t), "snippet": _plain_text(s)}
        for u, t, s in found
        if isinstance(u, str) and u.lower().startswith(("http://", "https://"))
    ][:RESULTS]


class _DuckDuckGo(HTMLParser):
    """The results on DuckDuckGo's HTML page: each one's link, title and snippet. Its ads link
    back to DuckDuckGo, and are left out with every other link that does."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._in: str | None = None  # "title" or "snippet" while inside one

    def handle_starttag(self, tag: str, attrs: list) -> None:
        marks = dict(attrs)
        classes = (marks.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            url = _unwrapped(marks.get("href") or "")
            self.results.append({"url": url, "title": "", "snippet": ""})
            self._in = "title"
        elif self.results and ("result__snippet" in classes or "result-snippet" in classes):
            self._in = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "td", "div"):
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in:
            self.results[-1][self._in] += data

    def close(self) -> None:
        super().close()
        self.results = [r for r in self.results if r["url"]]


def _unwrapped(href: str) -> str:
    """A DuckDuckGo result's own address, out of the redirect it's wrapped in; "" for a link
    to DuckDuckGo itself (an ad, or its own pages)."""
    url = urllib.parse.urljoin("https://duckduckgo.com/", href.strip())
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if host == "duckduckgo.com" or host.endswith(".duckduckgo.com"):
        if parts.path.startswith("/l/"):
            return urllib.parse.parse_qs(parts.query).get("uddg", [""])[0]
        return ""
    return url


def _searxng() -> str:
    """The user's SearXNG, without a trailing /, or "" when none (or not a web address) is set."""
    url = env("SEARXNG_URL").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    return url if parts.scheme in ("http", "https") and parts.hostname else ""


def _fetch(url: str, headers: dict[str, str]) -> tuple[str, bytes]:
    """A request as a lookup makes it, naming Proxenos: to the user's own SearXNG as is (it can
    be on this computer, and the user named it), anything else through links.py, so only to the
    public internet."""
    headers = {"User-Agent": USER_AGENT, **headers}
    base = _searxng()
    if base and url.startswith(f"{base}/search?"):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(url, headers=headers)
        with opener.open(request, timeout=links.TIMEOUT) as response:
            return response.headers.get_content_type(), response.read(links.MAX_BYTES)
    return links._fetch(url, headers)


# The place and its pages.


def _place(org: str) -> tuple[str, str]:
    """The place's domain and how it was chosen, when that needs no search: as given when it's a
    domain or a web address, or from KNOWN. ("", "") otherwise."""
    text = org.strip().lower()
    host = urllib.parse.urlsplit(text).hostname if "://" in text else text.rstrip("./")
    if host and _DOMAIN.fullmatch(host):
        return _registered(host), "as given"
    domain = KNOWN.get(" ".join(_words(org)))
    return (domain, "a well-known one") if domain else ("", "")


def _domain_from(results: list[dict], org: str) -> tuple[str, str] | None:
    """The first result's domain that looks like the place's own, and that result's address:
    not a site about everyone, with the place's name in its domain (or its initials as the
    domain), or every word of the place's name in its title."""
    words = [w for w in _words(org) if len(w) >= 3]
    initials = "".join(w[0] for w in re.findall(r"[a-z0-9]+", _fold(org)) if w not in _STOP)
    for result in results:
        host = (urllib.parse.urlsplit(result["url"]).hostname or "").lower()
        if not host or _is_ip(host) or "." not in host:
            continue
        site = _registered(host)
        if site in ELSEWHERE:
            continue
        label = site.split(".")[0]
        title = _fold(result.get("title") or "")
        if any(w in label for w in words) or (len(initials) >= 2 and label == initials):
            return site, result["url"]
        if words and all(re.search(rf"\b{re.escape(w)}\b", title) for w in words):
            return site, result["url"]
    return None


def _pages(results: list[dict], domain: str) -> list[str]:
    """The results on the place's domain or its subdomains, each once, PAGES at most."""
    pages: list[str] = []
    for result in results:
        url = result["url"].split("#")[0]
        if _official(url, domain) and url not in pages:
            pages.append(url)
    return pages[:PAGES]


def _official(url: str, domain: str) -> bool:
    """Whether a link is to the place's own site: http(s), by name (not an address), on its
    domain or under it, and never LinkedIn's."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme.lower() not in ("http", "https") or not host or _is_ip(host):
        return False
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return False
    return host == domain or host.endswith(f".{domain}")


def _profile(results: list[dict], name: str) -> str:
    """A LinkedIn profile among the results whose title has the person's last name; never
    fetched."""
    last = _names(name)[-1]
    for result in results:
        parts = urllib.parse.urlsplit(result["url"])
        host = (parts.hostname or "").lower()
        linkedin = host == "linkedin.com" or host.endswith(".linkedin.com")
        named = re.search(rf"\b{re.escape(last)}\b", _fold(result.get("title") or ""))
        if linkedin and parts.path.startswith("/in/") and named:
            return f"https://www.linkedin.com{parts.path}"
    return ""


def _registered(host: str) -> str:
    """The domain a host is registered under: profiles.stanford.edu → stanford.edu, www.ox.ac.uk
    → ox.ac.uk. A rule of thumb, not the public suffix list."""
    labels = host.lower().rstrip(".").split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


# Addresses on a page.


class _Text(HTMLParser):
    """A page's text, scripts and styles left out, with each mailto link's address (and each
    one Cloudflare hides) written where the link is, so an address can be found beside a name."""

    _SKIP = frozenset({"script", "style", "noscript", "template"})
    _BLOCKS = frozenset({"p", "div", "li", "tr", "td", "th", "br", "h1", "h2", "h3", "section"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip += 1
            return
        marks = {k: v or "" for k, v in attrs}
        href = marks.get("href", "").strip()
        if href.lower().startswith("mailto:"):
            self.chunks.append(f" {urllib.parse.unquote(href[7:].split('?')[0])} ")
        hidden = marks.get("data-cfemail") or (
            href.split("#", 1)[1] if "/cdn-cgi/l/email-protection#" in href else ""
        )
        if hidden:
            self.chunks.append(f" {_cloudflare(hidden)} ")
        if tag in self._BLOCKS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def _cloudflare(hidden: str) -> str:
    """An address Cloudflare hid: its hex, each byte after the first XORed with the first."""
    try:
        data = bytes.fromhex(hidden)
        return bytes(b ^ data[0] for b in data[1:]).decode("utf-8")
    except (ValueError, IndexError, UnicodeDecodeError):
        return ""


def _page_text(kind: str, body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    if kind != "text/plain":
        parser = _Text()
        parser.feed(text)
        parser.close()
        text = "".join(parser.chunks)
    return text[:TEXT_CHARS]


def _unhidden(text: str) -> str:
    """The text with each hidden address written as one: lower case, accents off, "[at]",
    "(dot)", "-at-" and "name at place dot edu" as @ and ."""
    text = _AT.sub("@", _fold(text))
    text = _DOT.sub(".", text)
    text = _SPELLED.sub(lambda m: f"{m[1]}@{m[2]}", text)
    return _DOTS_AFTER.sub(lambda m: "@" + re.sub(r"\s+dot\s+", ".", m[1]), text)


def _on_page(text: str, name: str, domain: str) -> dict[str, dict]:
    """The addresses on a page that look like the person's, each with how plainly (its tier) and
    how often it's beside their name. Only addresses on the place's domain. The tiers: 5, their
    first name or initial with another of their names (alee, laura.gwilliams); 4, one of their
    names (gwilliams, kalanit); 3, their initials, beside their name (kgs); 2, beside their name;
    1, a role's address with their name in it (gwilliamslab). A role's without it never counts."""
    text = _unhidden(text)
    names = _names(name)
    spots = [
        (m.start(), m[0].rstrip("."))
        for m in _ADDRESS.finditer(text)
        if _on_domain(m[0].rstrip("."), domain)
    ]
    starts = [s for s, _ in spots]
    beside: dict[str, int] = {}
    for m in _name_spots(names).finditer(text):
        i = bisect.bisect_left(starts, m.end())
        if i < len(spots) and spots[i][0] - m.end() <= AFTER:
            beside[spots[i][1]] = beside.get(spots[i][1], 0) + 1
    found: dict[str, dict] = {}
    for _, address in spots:
        local = address.split("@")[0]
        named, near = _named(local, names), beside.get(address, 0)
        if _role(local):
            tier = 1 if named else 0
        elif named:
            tier = 3 + named
        elif near:
            tier = 3 if _initials(local, names) else 2
        else:
            tier = 0
        if tier:
            found[address] = {"tier": tier, "beside": near}
    return found


def _name_spots(names: list[str]) -> re.Pattern:
    """Where a page names the person in full: first then last, a little between (a middle name,
    an initial, the rest of a hyphenated name), or "Last, First"."""
    first, last = (re.escape(n) for n in (names[0], names[-1]))
    if first == last:
        return re.compile(rf"\b{first}\b")
    return re.compile(rf"\b{first}\b[^@\n]{{0,30}}?\b{last}\b|\b{last}\b,\s*{first}\b")


def _named(local: str, names: list[str]) -> int:
    """How plainly a local part carries the person's name: 2 for their first name, or its
    initial in front, with another of their names (alee, laura.gwilliams, lgwilliams); 1 for one
    of their names alone (gwilliams, kalanit, but not laura.smith); 0 for none."""
    letters = re.sub(r"[^a-z]", "", local)
    first, last = names[0], names[-1]
    if any(len(n) >= 3 and n in letters for n in names[1:]):
        return 2 if first in letters or letters.startswith(first[0]) else 1
    if letters in {first + last, first[0] + last, first + last[0], last + first, last + first[0]}:
        return 2 if len(names) >= 2 else 1
    if len(first) >= 3 and first in letters and len(letters) - len(first) <= 2:
        return 1
    return 1 if letters == last else 0


def _initials(local: str, names: list[str]) -> bool:
    return len(names) >= 2 and re.sub(r"[^a-z]", "", local) == "".join(n[0] for n in names)


def _role(local: str) -> bool:
    segments = re.split(r"[._+-]", local)
    return any(s in _ROLES for s in segments) or bool(
        _ROLE_END.search(re.sub(r"[^a-z]", "", local))
    )


def _on_domain(address: str, domain: str) -> bool:
    host = address.rsplit("@", 1)[-1]
    return host == domain or host.endswith(f".{domain}")


# Small helpers.


def _names(name: object) -> list[str]:
    """A person's names, lower case and without accents, titles left out: "Dr. José Núñez-Gil"
    → jose, nunez, gil."""
    words = re.split(r"[^a-z]+", _fold(str(name or "")))
    return [w for w in words if len(w) >= 2 and w not in _TITLES]


def _words(org: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _fold(org)) if w not in _GENERIC]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _plain_text(value: object) -> str:
    """A search result's title or snippet as text: Brave marks matches with <strong>."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).split())


def _shown(url: str) -> str:
    shown = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    return shown if len(shown) <= 80 else shown[:79] + "…"


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _said(e: Exception) -> str:
    return " ".join(str(e).split())[:200] or type(e).__name__


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    what = parser.add_subparsers(dest="what", required=True)
    one = what.add_parser("email", help="a person's address, from their place's own pages")
    one.add_argument("name", help='the person, e.g. "Ana Lee"')
    one.add_argument("--org", required=True, help="where they are: Stanford, or stanford.edu")


def run(args: argparse.Namespace) -> dict:
    load()
    return look(args.name, args.org)
