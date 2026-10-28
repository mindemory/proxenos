"""Reading the pages people link to, so a reply can answer what the link says.

`find` pulls the web links out of a message. `read` fetches one page and returns its title and
visible text, or why it couldn't. It only goes to hosts on the public internet: every address
the name resolves to, and every redirect's, must be a global one, so a link in a message never
reaches this computer, the local network or a cloud metadata address. Only HTML and plain text
are read, and each page is capped in bytes, time and characters.
"""

import http.client
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from collections.abc import Callable

from proxenos.ingest.website import PageText

MAX_BYTES = 2_000_000
PAGE_CHARS = 8000
TIMEOUT = 15  # seconds
USER_AGENT = "Mozilla/5.0 (compatible; proxenos/0.1)"

_URL = re.compile(r"https?://[^\s<>\"'(){}\[\]]+", re.IGNORECASE)
_READABLE = ("text/html", "application/xhtml+xml", "text/plain")

# Takes a URL and returns the response's content type and body, raising the way urlopen does.
Fetch = Callable[[str], tuple[str, bytes]]

# What a dead, slow, refused or garbled page raises. URLError, HTTPError and timeouts are all
# OSErrors; a refused address is a ValueError.
_FAILURES = (OSError, ValueError, UnicodeError, http.client.HTTPException)


def find(text: str) -> list[str]:
    """The web links in a message, in order, each once, without the punctuation after them."""
    links: list[str] = []
    for match in _URL.finditer(text or ""):
        link = match[0].rstrip(".,;:!?*")
        if link not in links:
            links.append(link)
    return links


def read(url: str, fetch: Fetch | None = None, chars: int = PAGE_CHARS) -> dict:
    """{url, title, text} for a page that could be read, else {url, error}."""
    try:
        kind, body = (fetch or _fetch)(url)
    except _FAILURES as e:
        return {"url": url, "error": " ".join(str(e).split())[:200] or type(e).__name__}
    if kind not in _READABLE:
        return {"url": url, "error": f"not a page ({kind or 'unknown type'})"}
    html = body.decode("utf-8", errors="replace")
    if kind == "text/plain":
        title, text = "", " ".join(html.split())
    else:
        parser = PageText()
        parser.feed(html)
        parser.close()
        title, text = parser.title or parser.h1 or "", parser.text()
    if not text.strip():
        return {"url": url, "error": "no text on the page"}
    return {"url": url, "title": title, "text": text[:chars]}


def _fetch(url: str) -> tuple[str, bytes]:
    _public(url)
    opener = urllib.request.build_opener(_PublicRedirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=TIMEOUT) as response:
        return response.headers.get_content_type(), response.read(MAX_BYTES)


def _public(url: str) -> None:
    """Raise ValueError unless the link is http(s) to a host whose every address is global."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("not a web link")
    try:
        found = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"no such host ({parts.hostname})") from e
    for *_, address in found:
        if not ipaddress.ip_address(str(address[0]).split("%")[0]).is_global:
            raise ValueError(f"not on the public internet ({parts.hostname})")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a public host, checked the same way as the link itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
