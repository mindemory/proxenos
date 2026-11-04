r"""A LaTeX paper made ready for arXiv: its references checked against the scholarly record, and
its source bundled the way arXiv takes it.

Since May 2026 arXiv bars an author for a year when a paper shows a language model's output no one
checked, and a reference to a work that doesn't exist is the plainest sign of it. And arXiv builds
the paper itself from its source, which it then makes public.

`proxenos preprint refs PATH` reads the paper's BibTeX (the .bib files its \bibliography or
\addbibresource names, or a .bib given directly) and looks each entry up where it would be if it
were real: by its DOI at Crossref (at DataCite, for a DOI Crossref doesn't hold), by its arXiv id
at arXiv, and, with neither or when they lead elsewhere, by its title at Crossref and then
OpenAlex. A web page or software (a @misc, @online or @software with a url and no DOI) is fetched
instead. What's found is compared with the entry by title, first author and year, and each entry
is `found`, `differs` (saying how), `not found`, `page reachable`, `page unreachable`, or `error`
when a lookup failed, which is never taken for not found. Keys the paper cites with no entry, and
entries it never cites, are listed too.

`proxenos preprint bundle PATH.tex` writes `<stem>-arxiv.tar.gz`: the main file, what it pulls in
with \input and \include, its figures, the class, style and bibliography-style files beside it,
the .bbl (arXiv doesn't run BibTeX, so there's no bundle without a current one), and `--anc` files
under anc/. Nothing the paper doesn't name goes in. Comments are taken out of the TeX files, since
arXiv publishes them, except inside verbatim, lstlisting and comment environments. It warns, but
never refuses, over what shouldn't be published: a home folder's path, an email address that isn't
an author's, a TODO.

What goes out, and only from `refs`: each entry's DOI or arXiv id, or its title and first author's
surname, to those indexes, and a web entry's own address, fetched through links.py, so only from
the public internet. Nothing about the user and nothing of the paper's text, and no model. Each
request names Proxenos and its repository (no email address), requests to one host wait PACE
seconds (arXiv asks for three), and what the indexes found is kept for CACHE_DAYS in the vault's
state/preprint.json, when there's a vault, so running it again asks only what's new.
"""

import argparse
import html
import io
import json
import os
import posixpath
import re
import sys
import tarfile
import time
import unicodedata
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from proxenos import links
from proxenos.clones import work
from proxenos.ingest.website import PageText

CROSSREF = "https://api.crossref.org/works"
DATACITE = "https://api.datacite.org/dois"
ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
INDEXES = {
    "api.crossref.org": "Crossref",
    "api.datacite.org": "DataCite",
    "export.arxiv.org": "arXiv",
    "api.openalex.org": "OpenAlex",
}
USER_AGENT = "Proxenos (https://github.com/mindemory/proxenos)"
PACE = 1.0  # seconds between two requests to one host
PACES = {"export.arxiv.org": 3.0}  # arXiv asks its API's clients to leave three
CACHE = Path("state", "preprint.json")
CACHE_DAYS = 30
ROWS = 3  # results read from a title search
# How alike two titles are (similarity): the same but for a letter or two; the same work's, by
# the title alone; the same work's, changed, when its first author or year agrees.
SAME, LIKE, CLOSE = 0.97, 0.9, 0.75
OVERLAP = 0.5  # of an entry's title words a web page's title should share
LIMIT = 50_000_000  # bytes: the most arXiv takes in one submission
STATUSES = ("found", "differs", "not found", "page reachable", "page unreachable", "error")
WEB = {"misc", "online", "software", "electronic", "www", "webpage"}  # checked by their url
# Kinds of work that can be real and still in no index.
UNINDEXED = {
    "book", "phdthesis", "mastersthesis", "thesis", "techreport", "report", "manual", "unpublished",
}  # fmt: skip
GRAPHICS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")  # tried in this order, as pdflatex does
OUTPUTS = (".aux", ".log", ".out", ".blg", ".pdf")  # the main file's, never bundled
BINARY = (".pdf", ".png", ".jpg", ".jpeg", ".gif")  # never read for warnings
_MONTHS = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April", "may": "May",
    "jun": "June", "jul": "July", "aug": "August", "sep": "September", "oct": "October",
    "nov": "November", "dec": "December",
}  # fmt: skip

# Takes a URL and returns the response's content type and body, raising the way urlopen does.
Fetch = Callable[[str], tuple[str, bytes]]

# BibTeX.
_ENTRY = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
_FIELD = re.compile(r"[\s,]*([^\s=,{}\"#()]+)\s*=\s*")
_TOKEN = re.compile(r"[^\s,#{}\"=]+")
_AND = re.compile(r"\s+and\s+", re.IGNORECASE)
_COMMA = re.compile(r"\s*,\s*")
_SPACE = re.compile(r"\s+")
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.IGNORECASE)
_ARXIV_ID = r"(\d{4}\.\d{4,5}|[a-z][a-z.\-]*/\d{7})(?:v\d+)?"
_ARXIV_IN = (
    re.compile(rf"arxiv\.org/(?:abs|pdf)/{_ARXIV_ID}", re.IGNORECASE),
    re.compile(rf"10\.48550/arxiv\.{_ARXIV_ID}", re.IGNORECASE),
    re.compile(rf"arxiv:\s*{_ARXIV_ID}", re.IGNORECASE),  # "arXiv preprint arXiv:1706.03762"
)
_URL_IN = re.compile(r"\\url\s*\{([^}]*)\}")
# LaTeX in a value, to plain text: accents on their letters, letters of their own, then commands.
_ACCENT = re.compile(
    r"\\([`'^\"~=.]|[uvHcdbrk](?![A-Za-z]))\s*(?:\{\s*\\?([A-Za-z])\s*\}|\\?([A-Za-z]))"
)
_COMBINING = {
    "`": "\u0300", "'": "\u0301", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
    ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "d": "\u0323",
    "b": "\u0331", "r": "\u030a", "k": "\u0328",
}  # fmt: skip
_LETTER = re.compile(r"\\(ss|aa|AA|ae|AE|oe|OE|o|O|l|L|i|j)(?![A-Za-z])\s*")
_LETTERS = {
    "ss": "ß", "aa": "å", "AA": "Å", "ae": "æ", "AE": "Æ", "oe": "œ", "OE": "Œ", "o": "ø",
    "O": "Ø", "l": "ł", "L": "Ł", "i": "i", "j": "j",
}  # fmt: skip
_ESCAPED = re.compile(r"\\([&%$#_{}])")
_COMMAND = re.compile(r"\\[A-Za-z]+\*?\s*|\\.")
# Letters that don't come apart into a letter and its accent, as words compare them.
_FOLD = str.maketrans({"ø": "o", "ł": "l", "æ": "ae", "œ": "oe", "đ": "d", "ı": "i", "þ": "th"})
_TAG = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"

# LaTeX.
_CITE = re.compile(
    r"\\([A-Za-z]*cite[A-Za-z]*)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^}]*)\}", re.IGNORECASE
)
_BIBLIOGRAPHY = re.compile(
    r"\\(?:bibliography|addbibresource|addglobalbib)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
)
_INPUT = re.compile(r"\\(input|include|subfile)(?![A-Za-z@])\s*(?:\{([^{}]*)\}|([^\s{}\\%]+))")
_GRAPHICS = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}")
_GRAPHICSPATH = re.compile(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\})*)\s*\}")
_PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_CLASS = re.compile(r"\\(?:documentclass|LoadClass)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_BST = re.compile(r"\\bibliographystyle\s*\{([^}]*)\}")
_BIBLATEX = re.compile(r"\\usepackage\s*(?:\[[^\]]*\])?\s*\{[^}]*\bbiblatex\b")
_BEGIN_VERBATIM = re.compile(r"\\begin\s*\{(verbatim\*?|Verbatim\*?|lstlisting|minted|comment)\}")
_INLINE_VERBATIM = re.compile(r"\\(?:verb|lstinline|mintinline)(?![A-Za-z])\*?")
_URL_COMMAND = re.compile(r"\\(?:url|href)\s*(?=\{)")

# What shouldn't be published.
_HOME = re.compile(r"(?<![\w.\-])(?:/Users/|/home/|[A-Za-z]:[\\/]+Users[\\/]+)[^\s/\\{}()\"'<>]*")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_NOTE = re.compile(r"(?<![A-Za-z])(?:TODO|FIXME|XXX)(?![A-Za-z])|\\todo(?![A-Za-z])")
# Commands whose arguments hold the authors and where to reach them.
_AUTHORS = re.compile(
    r"\\(?:author|affil|affiliation|email|address|institute|institution|thanks|corresp|"
    r"correspondingauthor|icmlauthor|icmlaffiliation|icmlcorrespondingauthor)\*?\s*"
    r"(?:\[[^\]]*\]\s*)?(?=\{)"
)
_TITLE_END = re.compile(r"\\maketitle|\\begin\s*\{abstract\}")


class _Failed(Exception):
    """A lookup that couldn't be made, which says nothing about whether the work exists."""


def _fetch(url: str) -> tuple[str, bytes]:
    """A request as `refs` makes it, naming Proxenos, through links.py: only to the public
    internet, so a web entry can't point it at this computer or the local network."""
    return links._fetch(url, {"User-Agent": USER_AGENT})


# Checking references.


def check(
    path: Path,
    fetch: Fetch | None = None,
    cache: Path | None = None,
    wait: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    say: Callable[[str], None] | None = None,
) -> dict:
    """Every entry of the paper's BibTeX looked up and compared with what was found, with the
    keys it cites that have no entry and the entries it never cites. SystemExit when the file, or
    every .bib it names, can't be read."""
    now = now or datetime.now(UTC)
    entries, cited, bibs, unread = _references(path)
    asker = _Asker(fetch or _fetch, _cache_read(cache, now), wait, now)  # looked up now, for tests
    if say and entries:
        say(f"refs: looking up {_count(len(entries), 'reference')}, a second or so each")
    try:
        checked = [_check(entry, asker) for entry in entries]
    finally:
        if cache is not None and asker.added:
            _cache_write(cache, asker.cache)
    keys = {entry["key"] for entry in entries}
    missing, uncited = [], []
    if cited is not None:
        used = set(cited)
        if "*" in used:  # \nocite{*}
            used |= keys
        used |= {_plain_value(e["fields"].get("crossref", "")) for e in entries if e["key"] in used}
        missing = [key for key in dict.fromkeys(cited) if key != "*" and key not in keys]
        uncited = [entry["key"] for entry in entries if entry["key"] not in used]
    return {
        "path": str(path),
        "bibs": [str(bib) for bib in bibs],
        "unread_bibs": [str(bib) for bib in unread],
        "counts": {status: sum(e["status"] == status for e in checked) for status in STATUSES},
        "entries": checked,
        "cites_checked": cited is not None,
        "cited_missing": missing,
        "uncited": uncited,
    }


def _references(path: Path) -> tuple[list[dict], list[str] | None, list[Path], list[Path]]:
    """The entries to check, the keys the paper cites (None for a .bib alone), the .bib files read
    and those it names that aren't there."""
    if not path.is_file():
        raise SystemExit(f"refs: no such file: {path}")
    if path.suffix.lower() == ".bib":
        return parse_bib(_read(path)[0]), None, [path], []
    if path.suffix.lower() != ".tex":
        raise SystemExit(f"refs: give the paper's .tex, or a .bib, not {path.name}")
    files, _ = _tex_tree(path)
    texts = [strip_comments(f["text"])[0] for f in files]
    names = [
        name.strip()
        for text in texts
        for match in _BIBLIOGRAPHY.finditer(text)
        for name in match[1].split(",")
        if name.strip()
    ]
    bibs = [path.parent / (n if n.lower().endswith(".bib") else f"{n}.bib") for n in names]
    bibs = list(dict.fromkeys(bibs))
    found = [bib for bib in bibs if bib.is_file()]
    if not bibs:
        raise SystemExit(
            f"refs: {path.name} names no .bib in \\bibliography or \\addbibresource: give the "
            ".bib itself"
        )
    if not found:
        raise SystemExit(
            f"refs: {path.name} names {', '.join(b.name for b in bibs)}, and none is beside it"
        )
    entries = [entry for bib in found for entry in parse_bib(_read(bib)[0])]
    cited = [key for text in texts for key in cites(text)]
    return entries, cited, found, [bib for bib in bibs if not bib.is_file()]


def cites(text: str) -> list[str]:
    """The keys a TeX text cites, in order, with \\cite, \\citep, \\citet, \\parencite, \\nocite
    and the rest; "*" for \\nocite{*}."""
    keys = []
    for match in _CITE.finditer(text):
        if "style" in match[1].lower():  # \citestyle, \setcitestyle
            continue
        for key in match[2].split(","):
            key = key.strip()
            if key and "#" not in key and "\\" not in key:  # not a macro's own argument
                keys.append(key)
    return keys


def _check(entry: dict, asker: "_Asker") -> dict:
    """One entry, looked up by its DOI or arXiv id, then by its title, and compared with the
    record found; or, for a web page, fetched."""
    fields = entry["fields"]
    doi, arxiv = _doi(fields), _arxiv(fields)
    if doi.lower().startswith("10.48550/"):  # arXiv's own DOI: asked of arXiv
        doi = ""
    result = {
        "key": entry["key"],
        "type": entry["type"],
        "title": _latex_text(fields.get("title", "")),
        "author": _surname(fields.get("author") or fields.get("editor") or ""),
        "year": _year(fields),
        "doi": doi or None,
        "arxiv": arxiv or None,
        "url": _url(fields) or None,
        "status": "",
        "why": [],
        "notes": [],
        "found": None,
    }
    if entry["type"] in WEB and result["url"] and not doi and not arxiv:
        return _page(result, asker)
    failed: list[str] = []
    elsewhere: tuple[str, dict] | None = None  # an id that leads to another work, and that work
    unknown: list[str] = []  # ids no index holds
    match = None
    for kind, value in (("DOI", doi), ("arXiv", arxiv)):
        if not value:
            continue
        try:
            records = _by_id(kind, value, asker)
        except _Failed as e:
            failed.append(str(e))
            continue
        if not records:
            where = "at Crossref or DataCite" if kind == "DOI" else "on arXiv"
            unknown.append(f"{kind} {value} isn't registered {where}")
        elif _is_by_id(result, records[0]):
            match = records[0]
            break
        elif elsewhere is None:
            elsewhere = (f"{kind} {value}", records[0])
    # By title: OpenAlex too unless Crossref has one by the same title, as its first few results
    # can hold a review or a reply named after the work and not the work itself.
    found: list[dict] = []
    for search in (_crossref_search, _openalex_search) if result["title"] and not match else ():
        try:
            found += search(result, asker)
        except _Failed as e:
            failed.append(str(e))
            continue
        match = _best(result, found)
        if match and _likeness(result["title"], match) >= LIKE:
            break
    if match:
        # Found, by one id or by its title: an id that led nowhere, or elsewhere, still differs.
        _compared(result, match)
        same_doi = doi and match["id"].casefold() == doi.casefold()
        if elsewhere:
            result["why"].insert(0, f"{_another(*elsewhere)}; the entry's is {_where(match)}")
        elif unknown and not same_doi:
            result["why"].insert(0, f"{unknown[0]}; the entry's work is {_where(match)}")
        result["status"] = "differs" if result["why"] else "found"
        return result
    why = ([_another(*elsewhere)] if elsewhere else []) + unknown
    if failed:
        return result | {"status": "error", "why": [f"not checked: {'; '.join(failed)}", *why]}
    if result["title"]:
        why.append("no work with this title at Crossref or OpenAlex")
    elif not (doi or arxiv):
        why.append("no title, DOI or arXiv id to look it up by")
    return result | {"status": "not found", "why": why}


def _by_id(kind: str, value: str, asker: "_Asker") -> list[dict]:
    if kind == "arXiv":
        query = urllib.parse.urlencode({"id_list": value, "max_results": 1})
        return asker.records(f"{ARXIV}?{query}", _arxiv_records)
    quoted = urllib.parse.quote(value, safe="/")
    return asker.records(f"{CROSSREF}/{quoted}", _crossref_work) or asker.records(
        f"{DATACITE}/{quoted}", _datacite_records
    )


def _crossref_search(result: dict, asker: "_Asker") -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "query.bibliographic": f"{result['title']} {result['author']}".strip(),
            "rows": ROWS,
            "select": "DOI,title,subtitle,author,issued,published-print,published-online",
        }
    )
    return asker.records(f"{CROSSREF}?{query}", _crossref_items)


def _openalex_search(result: dict, asker: "_Asker") -> list[dict]:
    # The title's words alone, in lower case, so none reads as AND, OR or NOT.
    query = urllib.parse.urlencode(
        {
            "search": " ".join(_words(result["title"])),
            "per-page": ROWS,
            "select": "id,doi,display_name,publication_year,authorships",
        }
    )
    return asker.records(f"{OPENALEX}?{query}", _openalex_records)


def _is_by_id(result: dict, record: dict) -> bool:
    """Whether the work an id leads to is the entry's: its title close enough, or, where the
    title isn't, its first author or year the entry's."""
    if not result["title"] or _likeness(result["title"], record) >= CLOSE:
        return True
    return _agrees(result, record)


def _best(result: dict, records: list[dict]) -> dict | None:
    """Of title searches' results, the entry's work: the most alike of those with the same title,
    or nearly the same with the first author agreeing (see _agrees)."""
    ranked = sorted(records, key=lambda r: _likeness(result["title"], r), reverse=True)
    for record in ranked:
        likeness = _likeness(result["title"], record)
        if likeness >= LIKE or (likeness >= CLOSE and _agrees(result, record)):
            return record
    return None


def _agrees(result: dict, record: dict) -> bool:
    """Whether the first author agrees, or, where a side names none, the year within one. A year
    alone is no sign where the authors differ: a review of a paper is a year after it."""
    name = record["authors"][0] if record["authors"] else ""
    if result["author"] and name:
        return _same_name(result["author"], name)
    years = record["years"]
    return bool(result["year"] and years and min(abs(y - result["year"]) for y in years) <= 1)


def _compared(result: dict, record: dict) -> dict:
    """The entry set beside the record found: what differs, and a year one off as a note."""
    where, why, notes = record["source"], result["why"], result["notes"]
    if result["title"] and _likeness(result["title"], record) < SAME:
        why.append(f"title: the entry says “{result['title']}”, {where} has “{_titled(record)}”")
    name = record["authors"][0] if record["authors"] else ""
    if result["author"] and name and not _same_name(result["author"], name):
        why.append(f"first author: the entry says {result['author']}, {where} has {name}")
    year = None
    if record["years"]:
        year = min(record["years"], key=lambda y: abs(y - (result["year"] or y)))
    if result["year"] and year and year != result["year"]:
        said = f"year: the entry says {result['year']}, {where} has {year}"
        if abs(year - result["year"]) == 1:
            notes.append(f"{said}, within a year (a preprint and its journal often differ so)")
        else:
            why.append(said)
    found = {k: record[k] for k in ("source", "id", "url")}
    result["found"] = found | {"title": _titled(record), "author": name, "year": year}
    result["status"] = "differs" if why else "found"
    return result


def _another(said: str, record: dict) -> str:
    who = " ".join(str(x) for x in [*record["authors"][:1], *record["years"][:1]])
    return f"{said} is another work: “{_titled(record)}”" + (f" ({who})" if who else "")


def _where(record: dict) -> str:
    return f"{record['id']} at {record['source']}" if record["id"] else f"at {record['source']}"


def _page(result: dict, asker: "_Asker") -> dict:
    """A web entry: whether its address opens, and how the page's title matches the entry's."""
    url = result["url"]
    try:
        kind, body = asker.page(url)
    except urllib.error.HTTPError as e:
        if e.code == 429 or e.code >= 500:
            return result | {"status": "error", "why": [f"not checked: {url} answered {e.code}"]}
        why = f"{url} answered {e.code} {e.reason}".strip()
        if e.code in (401, 403):
            why += " (some sites refuse requests that aren't a browser's: open it to see)"
        return result | {"status": "page unreachable", "why": [why]}
    except ValueError as e:  # no such host, or not a public web address
        return result | {"status": "page unreachable", "why": [f"{url}: {_said(e)}"]}
    except links._FAILURES as e:
        return result | {"status": "error", "why": [f"not checked: {url}: {_said(e)}"]}
    title = ""
    if kind in ("text/html", "application/xhtml+xml"):
        parser = PageText()
        parser.feed(body.decode("utf-8", errors="replace"))
        parser.close()
        title = parser.title or ""
    result |= {
        "status": "page reachable",
        "found": {"source": "the web", "url": url, "title": title},
    }
    wanted = {w for w in _words(result["title"]) if len(w) > 2}
    if title and wanted:
        shared = len(wanted & set(_words(title)))
        result["found"]["overlap"] = round(shared / len(wanted), 2)
        if shared / len(wanted) < OVERLAP:
            result["notes"].append(
                f"the page's title, “{title}”, shares {shared} of the {len(wanted)} words of the "
                "entry's title"
            )
    return result


class _Asker:
    """The indexes and the web as `refs` asks them: requests to one host PACE apart, an index's
    answers kept in the cache, and a failed request raised as _Failed, never taken for nothing
    found."""

    def __init__(self, fetch: Fetch, cache: dict, wait: Callable[[float], None], now: datetime):
        self.fetch, self.cache, self.wait, self.now = fetch, cache, wait, now
        self.last: dict[str, float] = {}
        self.added = 0

    def records(self, url: str, read: Callable[[bytes], list[dict]]) -> list[dict]:
        """What an index holds at `url`, read into records; [] when it holds nothing there."""
        if url in self.cache:
            return self.cache[url]["records"]
        where = INDEXES.get(_host(url), _host(url))
        try:
            found = read(self._get(url)[1])
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return []
            raise _Failed(f"{where} answered {e.code}") from e
        except (*links._FAILURES, KeyError, TypeError, AttributeError, ET.ParseError) as e:
            raise _Failed(f"{where}: {_said(e)}") from e
        if found:
            self.cache[url] = {"at": _iso(self.now), "records": found}
            self.added += 1
        return found

    def page(self, url: str) -> tuple[str, bytes]:
        return self._get(url)

    def _get(self, url: str) -> tuple[str, bytes]:
        host = _host(url)
        if host in self.last:
            left = PACES.get(host, PACE) - (time.monotonic() - self.last[host])
            if left > 0:
                self.wait(left)
        try:
            return self.fetch(url)
        finally:
            self.last[host] = time.monotonic()


def _crossref_work(body: bytes) -> list[dict]:
    return [_crossref_record(json.loads(body)["message"])]


def _crossref_items(body: bytes) -> list[dict]:
    return [_crossref_record(item) for item in json.loads(body)["message"]["items"]]


def _crossref_record(item: dict) -> dict:
    years = []
    for key in ("issued", "published-print", "published-online"):
        parts = (item.get(key) or {}).get("date-parts") or [[]]
        if parts[0] and isinstance(parts[0][0], int):
            years.append(parts[0][0])
    doi = str(item.get("DOI") or "")
    return {
        "source": "Crossref",
        "id": doi,
        "url": f"https://doi.org/{doi}" if doi else "",
        "title": _html_text(" ".join(str(t) for t in item.get("title") or [])),
        "subtitle": _html_text(" ".join(str(t) for t in item.get("subtitle") or [])),
        "authors": [
            str(a.get("family") or a.get("name") or "")
            for a in item.get("author") or []
            if isinstance(a, dict)
        ][:5],
        "years": sorted(set(years)),
    }


def _datacite_records(body: bytes) -> list[dict]:
    data = json.loads(body)["data"]["attributes"]
    titles = [str(t.get("title") or "") for t in data.get("titles") or [] if isinstance(t, dict)]
    year = str(data.get("publicationYear") or "")
    doi = str(data.get("doi") or "")
    if not any(titles):
        return []
    return [
        {
            "source": "DataCite",
            "id": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
            "title": _html_text(titles[0]),
            "subtitle": "",
            "authors": [
                str(c.get("familyName") or c.get("name") or "")
                for c in data.get("creators") or []
                if isinstance(c, dict)
            ][:5],
            "years": [int(year)] if year.isdigit() else [],
        }
    ]


def _arxiv_records(body: bytes) -> list[dict]:
    found = []
    for entry in ET.fromstring(body).iter(f"{_ATOM}entry"):
        link = entry.findtext(f"{_ATOM}id") or ""
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        if "/api/errors" in link or not title:  # an id arXiv can't read, or has nothing for
            continue
        years = {
            int(when[:4])
            for tag in ("published", "updated")
            if (when := entry.findtext(f"{_ATOM}{tag}") or "")[:4].isdigit()
        }
        number = _ARXIV_IN[0].search(link)
        number = number[1] if number else link
        names = [
            " ".join((a.findtext(f"{_ATOM}name") or "").split())
            for a in entry.iter(f"{_ATOM}author")
        ]
        found.append(
            {
                "source": "arXiv",
                "id": f"arXiv:{number}",
                "url": f"https://arxiv.org/abs/{number}",
                "title": title,
                "subtitle": "",
                "authors": [n for n in names if n][:5],
                "years": sorted(years),
            }
        )
    return found


def _openalex_records(body: bytes) -> list[dict]:
    found = []
    for paper in json.loads(body)["results"]:
        title = _html_text(str(paper.get("display_name") or ""))
        if not title:
            continue
        doi, year = str(paper.get("doi") or ""), paper.get("publication_year")
        names = [
            str((a.get("author") or {}).get("display_name") or "")
            for a in paper.get("authorships") or []
            if isinstance(a, dict)
        ]
        found.append(
            {
                "source": "OpenAlex",
                "id": doi.removeprefix("https://doi.org/") or str(paper.get("id") or ""),
                "url": doi or str(paper.get("id") or ""),
                "title": title,
                "subtitle": "",
                "authors": [n for n in names if n][:5],
                "years": [year] if isinstance(year, int) else [],
            }
        )
    return found


def _cache_read(path: Path | None, now: datetime) -> dict:
    """The indexes' answers kept from earlier runs, those under CACHE_DAYS old."""
    if path is None:
        return {}
    try:
        kept = json.loads(path.read_text(encoding="utf-8")).get("answers")
    except (OSError, ValueError, AttributeError):
        return {}
    since = _iso(now - timedelta(days=CACHE_DAYS))
    fresh = {}
    for url, answer in (kept if isinstance(kept, dict) else {}).items():
        if not isinstance(answer, dict) or str(answer.get("at") or "") < since:
            continue
        records = answer.get("records")
        if isinstance(records, list) and records and all(map(_record_shaped, records)):
            fresh[url] = answer
    return fresh


def _record_shaped(record: object) -> bool:
    return (
        isinstance(record, dict)
        and all(isinstance(record.get(k), str) for k in ("source", "id", "url", "title"))
        and isinstance(record.get("authors"), list)
        and all(isinstance(a, str) for a in record["authors"])
        and isinstance(record.get("years"), list)
        and all(isinstance(y, int) for y in record["years"])
    )


def _cache_write(path: Path, answers: dict) -> None:
    work._write(path, json.dumps({"answers": answers}, ensure_ascii=False) + "\n")


# BibTeX, read.


def parse_bib(text: str) -> list[dict]:
    """A .bib's entries, each {key, type, fields}, in order: @string macros (and the months')
    expanded and joined with #, @comment and @preamble skipped, entries in braces or parentheses.
    Field names are lower case; values keep their inner braces and LaTeX."""
    strings = dict(_MONTHS)
    entries = []
    i = 0
    while (at := text.find("@", i)) >= 0:
        match = _ENTRY.match(text, at)
        if not match:
            i = at + 1
            continue
        kind, start = match[1].lower(), match.end() - 1
        end = _group_end(text, start) if match[2] == "{" else _paren_end(text, start)
        body, i = text[match.end() : end], end + 1
        if kind in ("comment", "preamble"):
            continue
        if kind == "string":
            strings.update(_fields(body, strings))
            continue
        key, _, rest = body.partition(",")
        entries.append({"key": key.strip(), "type": kind, "fields": dict(_fields(rest, strings))})
    return entries


def _fields(body: str, strings: dict[str, str]) -> Iterator[tuple[str, str]]:
    i = 0
    while i < len(body):
        match = _FIELD.match(body, i)
        if not match:  # not a field: on to the next comma
            comma = body.find(",", i + 1)
            if comma < 0:
                return
            i = comma + 1
            continue
        value, i = _value(body, match.end(), strings)
        yield match[1].lower(), value


def _value(body: str, i: int, strings: dict[str, str]) -> tuple[str, int]:
    """A field's value from `i`: braced, quoted, a number or a macro, joined with #."""
    parts, n = [], len(body)
    while i < n:
        if body[i] == "{":
            end = _group_end(body, i)
            parts.append(body[i + 1 : end])
        elif body[i] == '"':
            end = _quote_end(body, i)
            parts.append(body[i + 1 : end])
        elif match := _TOKEN.match(body, i):
            word, end = match[0], match.end() - 1
            parts.append(word if word.isdigit() else strings.get(word.lower(), ""))
        else:
            break
        i = end + 1
        while i < n and body[i].isspace():
            i += 1
        if i >= n or body[i] != "#":
            break
        i += 1
        while i < n and body[i].isspace():
            i += 1
    return "".join(parts), i


def _group_end(text: str, start: int) -> int:
    """The index of the brace that closes the one at `start`, or the text's length if none does."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if not depth:
                return i
    return len(text)


def _paren_end(text: str, start: int) -> int:
    depth = 0
    for i in range(start + 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        elif text[i] == ")" and depth <= 0:
            return i
    return len(text)


def _quote_end(text: str, start: int) -> int:
    depth = 0
    for i in range(start + 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        elif text[i] == '"' and depth <= 0:
            return i
    return len(text)


def _split(text: str, sep: re.Pattern) -> list[str]:
    """`text` split where `sep` matches outside braces."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        char = text[i]
        if char in "{}":
            depth += 1 if char == "{" else -1
        elif not depth and (match := sep.match(text, i)) and match.end() > i:
            parts.append(text[start:i])
            start = i = match.end()
            continue
        i += 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _surname(authors: str) -> str:
    """The first author's surname, as BibTeX writes names: "Lee, Ana", "Ana Lee",
    "Jan {van der Berg}", "{OpenAI}"; "" for none, or "others"."""
    names = _split(authors, _AND)
    if not names or names[0].casefold() == "others":
        return ""
    parts = _split(names[0], _COMMA)
    last = parts[0] if len(parts) > 1 else _split(names[0], _SPACE)[-1]
    return _latex_text(last)


def _year(fields: dict[str, str]) -> int | None:
    match = _YEAR.search(fields.get("year") or fields.get("date") or "")
    return int(match[1]) if match else None


def _doi(fields: dict[str, str]) -> str:
    """The entry's DOI, from its doi field or a doi.org link."""
    for name in ("doi", "url"):
        value = urllib.parse.unquote(_plain_value(fields.get(name, "")))
        if name == "url" and "doi.org/" not in value.lower():
            continue
        if match := _DOI.search(value):
            return match[1].rstrip(".,;")
    return ""


def _arxiv(fields: dict[str, str]) -> str:
    """The entry's arXiv id: its eprint with archivePrefix (or eprinttype) arXiv, or one in an
    arxiv.org link, arXiv's DOI, or "arXiv:…" where Google Scholar puts it."""
    prefix = _plain_value(fields.get("archiveprefix") or fields.get("eprinttype") or "")
    eprint = _plain_value(fields.get("eprint", "")).removeprefix("arXiv:").strip()
    if prefix.casefold() == "arxiv" and (match := re.fullmatch(_ARXIV_ID, eprint, re.IGNORECASE)):
        return match[1]
    for name in ("eprint", "doi", "url", "journal", "journaltitle", "note", "howpublished"):
        value = _plain_value(fields.get(name, ""))
        for pattern in _ARXIV_IN:
            if match := pattern.search(value):
                return match[1]
    return ""


def _url(fields: dict[str, str]) -> str:
    url = _plain_value(fields.get("url", ""))
    for name in ("howpublished", "note"):
        if not url and (match := _URL_IN.search(fields.get(name, ""))):
            url = _plain_value(match[1])
    return url if url.lower().startswith(("http://", "https://")) else ""


def _plain_value(value: str) -> str:
    """A value that isn't prose (a DOI, a link, a key) without its braces and escapes."""
    return _ESCAPED.sub(r"\1", value).replace("{", "").replace("}", "").strip()


def _latex_text(value: str) -> str:
    """A BibTeX value as plain text: accents on their letters, commands and braces gone."""
    text = _ACCENT.sub(
        lambda m: unicodedata.normalize("NFC", (m[2] or m[3]) + _COMBINING[m[1]]), value
    )
    text = _LETTER.sub(lambda m: _LETTERS[m[1]], text)
    text = _ESCAPED.sub(r"\1", text)
    text = _COMMAND.sub(" ", text.replace("~", " "))
    return " ".join(text.replace("{", "").replace("}", "").replace("$", "").split())


def _html_text(value: str) -> str:
    """An index's title as text: Crossref's can hold HTML and MathML."""
    return " ".join(html.unescape(_TAG.sub("", value)).split())


def _words(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.translate(_FOLD))
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()
    return re.findall(r"[a-z0-9]+", folded.translate(_FOLD))


def similarity(a: str, b: str) -> float:
    """How alike two titles are, 0 to 1, by their words: case, accents, LaTeX and punctuation
    aside. One that is the other with a subtitle left off counts as the same."""
    x, y = " ".join(_words(_latex_text(a))), " ".join(_words(_latex_text(b)))
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    short, long = sorted((x, y), key=len)
    if short.count(" ") >= 3 and long.startswith(f"{short} "):
        return SAME
    return SequenceMatcher(None, x, y, autojunk=False).ratio()


def _likeness(title: str, record: dict) -> float:
    return max(similarity(title, record["title"]), similarity(title, _titled(record)))


def _titled(record: dict) -> str:
    subtitle = record.get("subtitle") or ""
    return f"{record['title']}: {subtitle}" if subtitle else record["title"]


def _same_name(a: str, b: str) -> bool:
    """Whether two ways of writing a surname are one: "Grill-Spector" and "Grill Spector",
    "Berg" and "van der Berg", "Lee" and "Ana Lee"."""
    x, y = _words(a), _words(b)
    return bool(x and y) and (set(x) <= set(y) or set(y) <= set(x) or "".join(x) == "".join(y))


# TeX source.


def strip_comments(text: str) -> tuple[str, int, int]:
    """TeX with its comments taken out, and how many whole lines and line ends that took. A line
    that is only a comment goes; a comment after text goes but its % stays, as it keeps the line
    end from making a space. An escaped \\%, and anything in a verbatim, lstlisting, minted or
    comment environment, \\verb, \\url or \\href's address, stays as it is."""
    return _stripped(text)[:3]


def _stripped(text: str) -> tuple[str, int, int, list[int]]:
    """strip_comments, with the line in `text` each line left came from, so a warning can name
    the line in the user's own file."""
    out: list[str] = []
    kept: list[int] = []
    lines = trailing = 0
    inside: str | None = None
    pieces = text.split("\n")
    for number, piece in enumerate(pieces, 1):
        body = piece.removesuffix("\r")
        end = piece[len(body) :] + ("\n" if number < len(pieces) else "")
        cut, inside = _comment_at(body, inside)
        if cut is None or (cut == len(body) - 1 and body[:cut].strip()):
            out.append(body + end)
        elif not body[:cut].strip():
            lines += 1
            continue
        else:
            out.append(body[: cut + 1] + end)
            trailing += 1
        kept.append(number)
    return "".join(out), lines, trailing, kept


def _comment_at(line: str, inside: str | None) -> tuple[int | None, str | None]:
    """Where a line's comment starts, if it has one, and the verbatim environment the line ends
    in, given the one it starts in."""
    i, n = 0, len(line)
    while i < n:
        if inside:
            end = line.find(f"\\end{{{inside}}}", i)
            if end < 0:
                return None, inside
            i, inside = end + len(inside) + 6, None
            continue
        if line[i] == "%":
            return i, None
        if line[i] != "\\":
            i += 1
        elif match := _BEGIN_VERBATIM.match(line, i):
            i, inside = match.end(), match[1]
        elif match := _INLINE_VERBATIM.match(line, i):
            i = _past_inline(line, match.end())
        elif match := _URL_COMMAND.match(line, i):
            i = _group_end(line, match.end()) + 1
        else:
            i += 2  # an escaped character, \% among them, or a command's first letter
    return None, inside


def _past_inline(line: str, i: int) -> int:
    """Past \\verb|…|, \\lstinline[…]{…} and the like, starting after the command's name."""
    if i < len(line) and line[i] == "[":
        i = line.find("]", i) + 1 or len(line)
    if i >= len(line):
        return len(line)
    closer = "}" if line[i] == "{" else line[i]
    end = line.find(closer, i + 1)
    return end + 1 if end >= 0 else len(line)


def _tex_tree(main: Path) -> tuple[list[dict], list[dict]]:
    """The main file and every file it pulls in with \\input, \\include or \\subfile, each once,
    in the order TeX reads them, as {name, path, text, encoding}; and, as warnings, what it names
    that isn't in its folder. Names are found from the main file's folder, as TeX finds them."""
    folder, files, warnings, seen = main.parent, [], [], set()

    def visit(name: str, path: Path) -> None:
        seen.add(name)
        text, encoding = _read(path)
        files.append({"name": name, "path": path, "text": text, "encoding": encoding})
        for match in _INPUT.finditer(strip_comments(text)[0]):
            wanted = (match[2] or match[3] or "").strip()
            tries = (wanted,) if wanted.lower().endswith(".tex") else (f"{wanted}.tex", wanted)
            said = f"\\{match[1]}{{{wanted}}}"
            found = _locate(folder, wanted, tries, said, name, warnings)
            if found and found[0] not in seen:
                visit(*found)

    visit(main.name, main)
    return files, warnings


def _locate(
    folder: Path, wanted: str, tries: tuple[str, ...], said: str, where: str | None, warnings: list
) -> tuple[str, Path] | None:
    """The first of `tries` in the paper's folder, as (its name in the bundle, its path). A name
    outside the folder, or none there, is a warning; a macro's argument is passed over."""
    if not wanted or "#" in wanted or "\\" in wanted or wanted.startswith("|"):
        return None
    for candidate in tries:
        relative = posixpath.normpath(candidate.replace("\\", "/"))
        if posixpath.isabs(relative) or relative.split("/")[0] == ".." or ":" in relative:
            why = f"{said} is outside the paper's folder, so it's left out: move it in"
            warnings.append(_warning(where, "outside", why))
            return None
        if (folder / relative).is_file():
            return relative, folder / relative
    warnings.append(_warning(where, "missing", f"{said} names no file in the paper's folder"))
    return None


def _beside(folder: Path, name: str) -> tuple[str, Path] | None:
    """A class, style or bibliography style in the paper's folder; None for one TeX has."""
    relative = posixpath.normpath(name.strip().replace("\\", "/"))
    if posixpath.isabs(relative) or relative.split("/")[0] == ".." or ":" in relative:
        return None
    return (relative, folder / relative) if (folder / relative).is_file() else None


# The bundle.


def bundle(main: Path, out: Path | None = None, anc: list[Path] | None = None) -> dict:
    """Write the paper's arXiv bundle, `<stem>-arxiv.tar.gz`, beside it or in `out`: what's in
    it, its size and the warnings. SystemExit without a current .bbl, when the paper uses BibTeX."""
    if main.suffix.lower() != ".tex" or not main.is_file():
        raise SystemExit(f"bundle: no such .tex: {main}")
    folder = main.parent
    files, warnings = _tex_tree(main)
    texts = [strip_comments(f["text"])[0] for f in files]
    joined = "\n".join(texts)
    others = _others(folder, joined, warnings)
    bbl = _bbl(main, joined)
    contents: dict[str, tuple[bytes, float]] = {}
    numbers: dict[str, list[int]] = {}  # each kept line's own number, in a file cut
    removed = {"lines": 0, "trailing": 0}
    for f in files:
        text = f["text"]
        if not f["name"].lower().endswith(".bbl"):  # biblatex reads its .bbl's comments
            text, lines, trailing, numbers[f["name"]] = _stripped(text)
            removed["lines"] += lines
            removed["trailing"] += trailing
        contents[f["name"]] = (text.encode(f["encoding"]), f["path"].stat().st_mtime)
    for name, path in [*others, *([(bbl.name, bbl)] if bbl else [])]:
        if name not in contents and not _never(name, main.stem):
            contents[name] = (path.read_bytes(), path.stat().st_mtime)
    for name, path in _ancillary(anc or []):
        if name in contents:
            raise SystemExit(f"bundle: two files for {name}: rename one")
        contents[name] = (path.read_bytes(), path.stat().st_mtime)
    if _BIBLATEX.search(joined):
        why = "it uses biblatex, whose .bbl arXiv reads only when made by the biber it runs"
        warnings.append(_warning(None, "biblatex", why))
    for name, (data, _) in contents.items():
        warnings += _published(name, data, numbers.get(name))
    target = (out or folder) / f"{main.stem}-arxiv.tar.gz"
    compressed = _write_tar(target, contents)
    if compressed > LIMIT:
        why = f"it's {_size(compressed)}, over the {_size(LIMIT)} arXiv takes: shrink its figures"
        warnings.append(_warning(None, "size", why))
    return {
        "bundle": str(target),
        "files": [{"name": name, "bytes": len(data)} for name, (data, _) in contents.items()],
        "bytes": sum(len(data) for data, _ in contents.values()),
        "compressed": compressed,
        "limit": LIMIT,
        "comments": removed,
        "warnings": warnings,
    }


def _others(folder: Path, text: str, warnings: list) -> list[tuple[str, Path]]:
    """The figures the paper includes, and the classes, styles and bibliography styles it uses
    that sit in its folder, with those its own styles and classes load in turn."""
    dirs = [d for m in _GRAPHICSPATH.finditer(text) for d in re.findall(r"\{([^{}]*)\}", m[1])]
    found = []
    for match in _GRAPHICS.finditer(text):
        wanted = match[1].strip()
        tries = []
        for base in ["", *dirs]:
            name = posixpath.join(base, wanted)
            known = posixpath.splitext(wanted)[1].lower() in GRAPHICS
            tries += [name] if known else [*(name + ext for ext in GRAPHICS), name]
        said = f"\\includegraphics{{{wanted}}}"
        if located := _locate(folder, wanted, tuple(tries), said, None, warnings):
            found.append(located)
    queue, seen = [text], set()
    while queue:
        scanned = queue.pop()
        names = [
            *(f"{n.strip()}.sty" for m in _PACKAGE.finditer(scanned) for n in m[1].split(",")),
            *(f"{m[1].strip()}.cls" for m in _CLASS.finditer(scanned)),
            *(f"{m[1].strip()}.bst" for m in _BST.finditer(scanned)),
        ]
        for name in names:
            if name in seen or not (located := _beside(folder, name)):
                continue
            seen.add(name)
            found.append(located)
            if not name.endswith(".bst"):
                queue.append(strip_comments(_read(located[1])[0])[0])
    return found


def _bbl(main: Path, text: str) -> Path | None:
    """The main file's .bbl, when it uses BibTeX: SystemExit when there's none, or it's older
    than a .bib it's made from, since arXiv builds the references only from it."""
    names = [n.strip() for m in _BIBLIOGRAPHY.finditer(text) for n in m[1].split(",") if n.strip()]
    bbl = main.with_suffix(".bbl")
    if not names:
        return bbl if bbl.is_file() else None
    if not bbl.is_file():
        raise SystemExit(
            f"bundle: there's no {bbl.name}. arXiv doesn't run BibTeX, so compile the paper first "
            f"(pdflatex, bibtex, then pdflatex twice, or latexmk) to make it beside {main.name}"
        )
    bibs = [main.parent / (n if n.lower().endswith(".bib") else f"{n}.bib") for n in names]
    newer = [b.name for b in bibs if b.is_file() and b.stat().st_mtime > bbl.stat().st_mtime]
    if newer:
        raise SystemExit(
            f"bundle: {bbl.name} is older than {', '.join(newer)}: compile the paper again so its "
            "references are the ones in the .bib"
        )
    return bbl


def _ancillary(items: list[Path]) -> list[tuple[str, Path]]:
    """Files for anc/, a folder's with its own name, its hidden files and caches left out."""
    found = []
    for item in items:
        if item.is_dir():
            for path in sorted(item.rglob("*")):
                parts = path.relative_to(item).parts
                if path.is_file() and not any(
                    p.startswith(".") or p == "__pycache__" for p in parts
                ):
                    found.append((posixpath.join("anc", item.name, *parts), path))
        elif item.is_file():
            found.append((f"anc/{item.name}", item))
        else:
            raise SystemExit(f"bundle: no such file for anc/: {item}")
    return found


def _never(name: str, stem: str) -> bool:
    """What a bundle never holds: git's folder, and the main file's own outputs."""
    return ".git" in name.split("/") or name in {f"{stem}{ext}" for ext in OUTPUTS}


def _published(name: str, data: bytes, numbers: list[int] | None = None) -> list[dict]:
    """What a bundled text file has that arXiv would publish and shouldn't: a home folder's path,
    an email address not the authors', a note left in; by line, as `numbers` gives each line's
    number in the user's own file when comments were cut from it."""
    if name.lower().endswith(BINARY) or b"\0" in data[:65536]:
        return []
    text = data.decode("utf-8", errors="replace")
    allowed = _authors_spans(text) if name.lower().endswith(".tex") else []
    found: dict[tuple[int, str], dict] = {}

    def warn(at: int, kind: str, what: str) -> None:
        line = text.count("\n", 0, at)
        line = numbers[line] if numbers and line < len(numbers) else line + 1
        found.setdefault((line, kind), _warning(name, kind, what, line))

    for match in _HOME.finditer(text):
        warn(match.start(), "home", f"a home folder's path: {match[0]}")
    for match in _EMAIL.finditer(text):
        if not any(start <= match.start() < end for start, end in allowed):
            warn(match.start(), "email", f"an email address: {match[0]}")
    for match in _NOTE.finditer(text):
        warn(match.start(), "note", f"a note left in: {match[0]}")
    return [found[at] for at in sorted(found)]


def _authors_spans(text: str) -> list[tuple[int, int]]:
    """Where a .tex names its authors and how to reach them: the arguments of \\author, \\affil,
    \\email and the like, and a mailto: link before \\maketitle (or the abstract)."""
    spans = []
    for match in _AUTHORS.finditer(text):
        end = match.end()
        while end < len(text) and text[end] == "{":
            end = _group_end(text, end) + 1
            while end < len(text) and text[end] in " \t":
                end += 1
        spans.append((match.end(), end))
    title_end = _TITLE_END.search(text)
    block = title_end.start() if title_end else (len(text) if "\\author" in text else 0)
    for match in re.finditer(r"mailto:", text[:block]):
        spans.append((match.end(), match.end() + 1))
    return spans


def _write_tar(target: Path, contents: dict[str, tuple[bytes, float]]) -> int:
    """The .tar.gz written in whole, its members owned by no one named (tarfile would otherwise
    put this computer's user name in it), and its size."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    with open(tmp, "wb") as raw, tarfile.open(target.name, "w:gz", fileobj=raw) as tar:
        for name, (data, mtime) in contents.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), int(mtime), 0o644
            tar.addfile(info, io.BytesIO(data))
    os.replace(tmp, target)
    return target.stat().st_size


def _warning(file: str | None, kind: str, text: str, line: int | None = None) -> dict:
    return {"file": file, "line": line, "kind": kind, "text": text}


# Small helpers.


def _read(path: Path) -> tuple[str, str]:
    """A file's text and the encoding to write it back in: UTF-8, else Latin-1, as older TeX."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise SystemExit(f"preprint: can't read {path}: {e.strerror or e}") from None
    encoding = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        return data.decode(encoding), encoding
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _said(e: Exception) -> str:
    return " ".join(str(e).split())[:200] or type(e).__name__


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[: chars - 1].rstrip() + "…"


def _size(n: int) -> str:
    if n < 1000:
        return f"{n} B"
    return f"{n / 1000:.1f} kB" if n < 1_000_000 else f"{n / 1_000_000:.1f} MB"


# What the commands print.

_HEADINGS = {
    "not found": (
        "Not found at Crossref, DataCite, arXiv or OpenAlex. These are what arXiv bars authors "
        "for: find each in the work it cites and correct it, or take it out."
    ),
    "differs": "Found, but the entry differs from the record: correct it to match.",
    "page unreachable": "Web references that don't open: fix the link, or cite something else.",
    "error": "Not checked, as a lookup failed: run this again.",
}


def summary(report: dict) -> str:
    """The check as the command prints it: counts, then every entry to fix, and why."""
    entries, counts = report["entries"], report["counts"]
    bibs = ", ".join(Path(b).name for b in report["bibs"])
    lines = [f"{Path(report['path']).name}: {_count(len(entries), 'reference')} in {bibs}"]
    said = [
        f"{n} {status}{'s' if status == 'error' and n != 1 else ''}"
        for status, n in counts.items()
        if n
    ]
    lines.append("  " + (", ".join(said) or "nothing to check"))
    for bib in report["unread_bibs"]:
        lines.append(f"  {Path(bib).name} is named but isn't there, so it wasn't checked")
    for status, heading in _HEADINGS.items():
        rows = [entry for entry in entries if entry["status"] == status]
        if rows:
            lines += ["", heading, *(line for entry in rows for line in _described(entry))]
    noted = [e for e in entries if e["notes"] and e["status"] in ("found", "page reachable")]
    if noted:
        lines += ["", "Found, with something to look at:"]
        lines += [line for entry in noted for line in _described(entry)]
    missing, uncited = report["cited_missing"], report["uncited"]
    if missing:
        lines += ["", f"Cited, but in no .bib (they print as [?]): {', '.join(missing)}"]
    if uncited:
        lines += ["", f"In the .bib, never cited (left out of the paper): {', '.join(uncited)}"]
    if not report["cites_checked"]:
        lines += ["", "A .bib alone: give the .tex to check its citations too."]
    fix = sum(counts[s] for s in ("not found", "differs", "page unreachable"))
    if fix or missing:
        what = [_count(fix, "reference")] if fix else []
        what += [_count(len(missing), "citation") + " with no entry"] if missing else []
        lines += ["", f"To fix before you post it: {' and '.join(what)}."]
    elif counts["error"]:
        lines += ["", f"Nothing wrong found, but {counts['error']} not checked: run it again."]
    else:
        lines += ["", "Nothing to fix: every reference matches the record."]
    return "\n".join(lines)


def _described(entry: dict) -> list[str]:
    who = " ".join(str(x) for x in (entry["author"], entry["year"]) if x)
    title = f"“{_clip(entry['title'], 90)}”" if entry["title"] else "(no title)"
    lines = [f"  {entry['key']}: {title}" + (f" ({who})" if who else "")]
    lines += [f"    - {line}" for line in entry["why"] + entry["notes"]]
    if entry["status"] == "differs" and entry["found"] and entry["found"].get("url"):
        lines.append(f"    - the record: {entry['found']['url']}")
    if entry["status"] == "not found" and entry["type"] in UNINDEXED:
        lines.append("    - a book, thesis or report can be real and in no index: check it by hand")
    return lines


def described(report: dict) -> str:
    """The bundle as the command prints it: each file and its size, the total, the comments
    taken out and the warnings."""
    rows, removed = report["files"], report["comments"]
    width = max(len(row["name"]) for row in rows)
    head = (
        f"{Path(report['bundle']).name}: {_count(len(rows), 'file')}, {_size(report['bytes'])}, "
        f"{_size(report['compressed'])} compressed, of the {_size(report['limit'])} arXiv takes"
    )
    comments = (
        f"Comments taken out: {_count(removed['lines'], 'whole line')} and "
        f"{removed['trailing']} at the ends of lines."
    )
    lines = [
        head,
        *(f"  {row['name']:<{width}}  {_size(row['bytes']):>9}" for row in rows),
        "",
        comments,
    ]
    if report["warnings"]:
        lines += ["", "Look at these before you upload (they don't stop the bundle):"]
        for warning in report["warnings"]:
            where = warning["file"] or ""
            where += f":{warning['line']}" if warning["line"] else ""
            lines.append(f"  {where + '  ' if where else ''}{warning['text']}")
    lines += ["", f"Written to {report['bundle']}"]
    return "\n".join(lines)


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    what = parser.add_subparsers(dest="what", required=True)
    refs = what.add_parser(
        "refs", help="check its references against Crossref, DataCite, arXiv and OpenAlex"
    )
    refs.add_argument("path", type=Path, help="the paper's .tex, or a .bib")
    refs.add_argument("--json", action="store_true", help="print the whole check as JSON")
    pack = what.add_parser("bundle", help="the .tar.gz arXiv wants, with its comments taken out")
    pack.add_argument("path", type=Path, help="the paper's main .tex")
    pack.add_argument(
        "--out", type=Path, metavar="DIR", help="where the .tar.gz goes (default: beside the .tex)"
    )
    pack.add_argument(
        "--anc",
        type=Path,
        nargs="+",
        action="extend",
        default=[],
        metavar="FILE",
        help="files (or folders) for the bundle's anc/, such as the analysis scripts",
    )


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.what == "refs":
        cache = vault / CACHE if vault.is_dir() else None
        report = check(args.path, cache=cache, say=lambda line: print(line, file=sys.stderr))
        print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else summary(report))
        return
    print(described(bundle(args.path, args.out, args.anc)))
