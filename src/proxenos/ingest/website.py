"""Pages and posts of the user's website, read from its local git repo.

Reads every tracked HTML page, and Markdown with front matter (what Jekyll renders), and
writes its title, site path, date and plain text into the vault. A page's date is the first
of: `date` in its front matter, a published date in the page itself (a date <meta>, or an
element marked datePublished, pubdate or dt-published), a date in its path (as in
_posts/2024-03-05-title.md), and the day git first saw the file, following renames. The text
leaves out <nav>, <script> and <style>, and elements whose class or id marks them as
navigation, a sidebar or a menu, so the site's chrome isn't repeated in every page. As in
Jekyll, anything under a name starting with _ or . is a template or tooling and is skipped,
except _posts, and so is third-party code under vendor or node_modules.

If the site keeps its CV as data (cv_data.js or cv.json), every entry in it becomes a record
in the cv stream, dated by the earliest month or year it mentions, or by when git first saw
the file. The JS is read as JSON once comments, trailing commas, single quotes and bare keys
are dealt with; a file that still won't parse is skipped with a note.

Every run re-reads the repo and merges by id, the path relative to the repo. A page whose
date source changes (say, front matter added later) moves month and leaves its old record.

Without --repo, the repo named by PROXENOS_WEBSITE_REPO is read.
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from proxenos.config import env
from proxenos.store import merge_monthly

_HTML = {".html", ".htm"}
_MARKDOWN = {".md", ".markdown"}
_POSTS = "_posts"
_NOT_PAGES = {"node_modules", "vendor"}
_CV_DATA = re.compile(r"^(cv|resume)[_-]?data\.(js|json)$|^(cv|resume)\.json$", re.IGNORECASE)

# Dropped with everything inside them. Text in <title> is the title, not the body.
_SKIP_TAGS = {"nav", "script", "style", "noscript", "template", "svg", "button", "select"}
_CHROME = re.compile(r"(?:^|[\s_-])(nav|navbar|navigation|sidebar|menu)(?=$|[\s_-])", re.IGNORECASE)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
_VOID |= {"track", "wbr"}
_BLOCK_TAGS = {"address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "figure"}
_BLOCK_TAGS |= {"figcaption", "footer", "header", "hr", "li", "main", "ol", "p", "pre"}
_BLOCK_TAGS |= {"section", "table", "td", "th", "tr", "ul"} | {f"h{n}" for n in range(1, 7)}
_DATE_META = {"date", "article:published_time", "dc.date", "dcterms.date", "dcterms.created"}

_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_DATE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?)?"
)
_PATH_DATE = re.compile(r"(?<!\d)(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)")
_MONTH_OR_YEAR = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b|\b((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_CV_DATE_KEYS = {"date", "dates", "year", "period", "when"}
_CV_TITLE_KEYS = ("title", "degree", "role", "course", "institution", "name", "category", "item")

# Strings are kept (single-quoted ones re-quoted), comments dropped and bare keys quoted. One
# pass, so nothing inside a string is touched.
_JS_TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/'
    r"|(?<=[{,])(\s*)([A-Za-z_$][\w$]*)(\s*:)",
    re.DOTALL,
)

FirstAdded = Callable[[str], datetime | None]


def default_repo() -> Path:
    """The site repo from PROXENOS_WEBSITE_REPO; stops with a message when it isn't set."""
    folder = env("WEBSITE_REPO")
    if not folder:
        raise SystemExit(
            "website: set PROXENOS_WEBSITE_REPO in .env to your site's git repo, or pass --repo DIR"
        )
    return Path(folder).expanduser()


def ingest(vault: Path, repo: Path | None = None) -> dict[str, int]:
    repo = repo or default_repo()
    out = vault / "raw" / "website"
    files = [rel for rel in _tracked(repo) if (repo / rel).is_file()]
    first_added = cache(lambda rel: _first_added(repo, rel))

    pages = [_page(repo, rel, first_added) for rel in files if _is_page(rel)]
    pages = [page for page in pages if page]
    cv = []
    for rel in files:
        if _CV_DATA.match(PurePosixPath(rel).name):
            cv += _cv(repo, rel, first_added)

    totals = {"read": 0, "added": 0, "updated": 0, "months_written": 0}
    undated = 0
    for stream, records in (("pages", pages), ("cv", cv)):
        dated = [r for r in records if r["ts"]]
        undated += len(records) - len(dated)
        for key, value in merge_monthly(dated, out / stream).items():
            totals[key] += value
    # Only a file that is staged but never committed can have no date at all.
    return totals | ({"undated": undated} if undated else {})


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        type=Path,
        metavar="DIR",
        help="the site's git repo (default: $PROXENOS_WEBSITE_REPO)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.repo.expanduser() if args.repo else None)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    command = ["git", "-C", str(repo), *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _tracked(repo: Path) -> list[str]:
    listing = _git(repo, "ls-files", "-z")
    if listing.returncode:
        raise SystemExit(f"website: {repo} is not a git repository; point --repo at the site")
    return [rel for rel in listing.stdout.split("\0") if rel]


def _first_added(repo: Path, rel: str) -> datetime | None:
    log = _git(repo, "log", "--follow", "--diff-filter=A", "--format=%aI", "--", rel)
    dates = log.stdout.split() if log.returncode == 0 else []
    return datetime.fromisoformat(dates[-1]).astimezone(UTC) if dates else None  # oldest last


def _is_page(rel: str) -> bool:
    path = PurePosixPath(rel)
    for part in path.parts:
        if part in _NOT_PAGES or (part[0] in "_." and part != _POSTS):
            return False
    return path.suffix.lower() in _HTML | _MARKDOWN


def _page(repo: Path, rel: str, first_added: FirstAdded) -> dict | None:
    raw = (repo / rel).read_text(encoding="utf-8", errors="replace")
    front, body = _front_matter(raw)
    markdown = PurePosixPath(rel).suffix.lower() in _MARKDOWN
    if markdown and front is None:
        return None  # a README or similar, which Jekyll copies without rendering
    front = front or {}

    parser = _PageText()
    parser.feed(_markdown_as_html(body) if markdown else body)
    parser.close()
    text = parser.text()
    heading = re.search(r"^#\s+(.+?)[\s#]*$", body, re.MULTILINE) if markdown else None
    title = front.get("title") or parser.title or (heading and heading.group(1)) or parser.h1

    when, source = _page_date(rel, front, parser.date, first_added)
    path = PurePosixPath(rel)
    return {
        "id": rel,
        "ts": _iso(when) if when else None,
        "kind": "post" if _POSTS in path.parts else "page",
        "title": title or path.stem,
        "url": _url(path, front, when),
        "text": text or None,
        "words": len(text.split()),
        "date_from": source,
    }


def _page_date(
    rel: str, front: dict[str, str], in_page: str | None, first_added: FirstAdded
) -> tuple[datetime | None, str | None]:
    # Most deliberate first. Git comes last, being the slowest to ask.
    if when := _parse_date(front.get("date")):
        return when, "front matter"
    if when := _parse_date(in_page):
        return when, "page"
    if when := _path_date(rel):
        return when, "path"
    if when := first_added(rel):
        return when, "git"
    return None, None


def _front_matter(raw: str) -> tuple[dict[str, str] | None, str]:
    match = _FRONT_MATTER.match(raw)
    if not match:
        return None, raw
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key[0].isspace():  # top-level keys only
            fields[key.strip()] = value.strip().strip("'\"")
    return fields, raw[match.end() :]


def _markdown_as_html(markdown: str) -> str:
    # Enough Markdown to get at the words; inline HTML is left for the parser.
    text = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", markdown, flags=re.DOTALL)  # Liquid
    text = re.sub(r"^\s*(```|~~~).*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s*\[[^\]]+\]:\s*\S+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}(#{1,6}|>+)\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*([-*+]|\d+\.)\s+", "<br>", text, flags=re.MULTILINE)  # a line per item
    text = re.sub(r"\*\*|__|\*|`", "", text)
    return "".join(f"<p>{para}</p>" for para in re.split(r"\n\s*\n", text))


def _url(path: PurePosixPath, front: dict[str, str], when: datetime | None) -> str:
    if front.get("permalink"):
        return front["permalink"]
    if _POSTS in path.parts and when:
        # Jekyll's default for posts: /:categories/:year/:month/:day/:title.html
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
        categories = re.findall(r"[^\s\[\],'\"]+", front.get("categories") or "")
        return "/" + "/".join([*categories, when.strftime("%Y/%m/%d"), f"{slug}.html"])
    if path.suffix.lower() in _MARKDOWN:
        path = path.with_suffix(".html")
    if path.name == "index.html":
        return "/" if path.parent == PurePosixPath(".") else f"/{path.parent}/"
    return f"/{path}"


def _parse_date(text: str | None) -> datetime | None:
    match = _DATE.search(text or "")
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        when = datetime(
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)
        )
    except ValueError:
        return None
    when = when.replace(tzinfo=UTC)  # no zone means UTC
    if zone and zone != "Z":
        offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[-2:]))
        when -= offset if zone[0] == "+" else -offset
    return when


def _path_date(rel: str) -> datetime | None:
    for match in _PATH_DATE.finditer(rel):
        try:
            return datetime(*map(int, match.groups()), tzinfo=UTC)
        except ValueError:
            continue
    return None


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class _PageText(HTMLParser):
    """The visible text of a page, a line per block, plus its title, first <h1> and date."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.title: str | None = None
        self.h1: str | None = None
        self.date: str | None = None
        self._capture: tuple[str, list[str]] | None = None  # (tag, chunks) of title or h1
        # The element being skipped, and how deep its own tag is nested inside itself.
        # Counting only that tag survives the unclosed <p> and <li> real pages have.
        self._skip: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._skip:
            if tag == self._skip:
                self._skip_depth += 1
            return
        attrs = {name: value or "" for name, value in attrs}
        marks = f"{attrs.get('id', '')} {attrs.get('class', '')}"
        if tag in _SKIP_TAGS or attrs.get("role") == "navigation" or _CHROME.search(marks):
            if tag not in _VOID:
                self._skip, self._skip_depth = tag, 1
            return
        meta = (attrs.get("name") or attrs.get("property") or "").lower()
        published = attrs.get("itemprop") == "datePublished" or "pubdate" in attrs
        if (tag == "meta" and meta in _DATE_META) or published or "dt-published" in marks:
            self.date = self.date or attrs.get("datetime") or attrs.get("content")
        if tag == "title" or (tag == "h1" and self.h1 is None):
            self._capture = (tag, [])
        if tag in _BLOCK_TAGS or tag == "br":
            self.chunks.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in _VOID or tag == "br":
            self.handle_starttag(tag, attrs)  # a self-closed element opens nothing to skip

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag == self._skip:
                self._skip_depth -= 1
                if not self._skip_depth:
                    self._skip = None
            return
        if self._capture and tag == self._capture[0]:
            found = " ".join("".join(self._capture[1]).split()) or None
            if tag == "title":
                self.title = self.title or found
            else:
                self.h1 = found
            self._capture = None
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._capture:
            self._capture[1].append(data)
            if self._capture[0] == "title":
                return
        self.chunks.append(re.sub(r"\s+", " ", data))  # source line breaks are spaces

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.chunks).splitlines())
        return "\n".join(line for line in lines if line)


def _cv(repo: Path, rel: str, first_added: FirstAdded) -> list[dict]:
    source = (repo / rel).read_text(encoding="utf-8", errors="replace")
    data = _lenient_json(source)
    if not isinstance(data, dict):
        print(f"website: skipped {rel}, which didn't parse as CV data", file=sys.stderr)
        return []
    records = []
    for section, value in data.items():
        if isinstance(value, list):
            entries = [e if isinstance(e, dict) else {"item": e} for e in value]
        elif isinstance(value, dict) and value and all(isinstance(v, list) for v in value.values()):
            entries = [{"category": key, "items": items} for key, items in value.items()]
        else:
            continue  # the name, contact details and other single values
        seen: dict[str, int] = {}
        for entry in entries:
            title = next((str(entry[k]) for k in _CV_TITLE_KEYS if entry.get(k)), None)
            slug = _slug(title or json.dumps(entry, sort_keys=True))
            seen[slug] = seen.get(slug, 0) + 1
            if seen[slug] > 1:
                slug = f"{slug}-{seen[slug]}"
            when_text = _cv_dates(entry)
            when, date_from = _earliest(when_text), "entry"
            if when is None:
                when, date_from = first_added(rel), "git"
            records.append(
                {
                    "id": f"{rel}#{section}/{slug}",
                    "ts": _iso(when) if when else None,
                    "section": section,
                    "title": title,
                    "when": "; ".join(when_text) or None,
                    "entry": entry,
                    "date_from": date_from if when else None,
                }
            )
    return records


def _lenient_json(source: str) -> object:
    def fix(match: re.Match) -> str:
        token = match.group()
        if token.startswith("'"):
            return json.dumps(token[1:-1].replace("\\'", "'"))
        if token.startswith("/"):
            return ""
        if match.group(2):
            return f'{match.group(1)}"{match.group(2)}"{match.group(3)}'
        return token

    cleaned = _JS_TOKEN.sub(fix, source)
    # The data starts after the first "=" or "export default" in a script, or at once in JSON.
    start = re.search(r"(?:=|export\s+default)\s*[\[{]|\A\s*[\[{]", cleaned)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if not start or end < start.end():
        return None
    body = cleaned[start.end() - 1 : end + 1]
    body = re.sub(r",(\s*[}\]])", r"\1", body)  # trailing commas
    try:
        return json.loads(body)
    except ValueError:
        return None


def _cv_dates(entry: object) -> list[str]:
    found = []
    if isinstance(entry, dict):
        for key, value in entry.items():
            if key.lower() in _CV_DATE_KEYS and isinstance(value, str | int):
                if str(value).strip():
                    found.append(str(value).strip())
            else:
                found += _cv_dates(value)
    elif isinstance(entry, list):
        for value in entry:
            found += _cv_dates(value)
    return found


def _earliest(texts: list[str]) -> datetime | None:
    # A month without a year takes the next year named, as in "May - Aug 2019".
    dates = []
    for text in texts:
        months: list[int] = []
        for month, year in _MONTH_OR_YEAR.findall(text):
            if month:
                months.append(_MONTHS.index(month[:3].lower()) + 1)
            else:
                dates += [datetime(int(year), m, 1, tzinfo=UTC) for m in months or [1]]
                months = []
    return min(dates, default=None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "entry"
