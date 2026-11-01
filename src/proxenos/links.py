"""Reading the pages people link to, so a reply can answer what the link says.

`find` pulls the web links out of a message. `read` fetches one page and returns its title and
visible text, or why it couldn't. It only goes to hosts on the public internet, on ports 80
and 443: every address the name resolves to, and every redirect's, must be a global one, so a
link in a message never reaches this computer, the local network or a cloud metadata address.
The name is resolved once per connection and the socket goes to the address that was checked,
so a name that answers differently a moment later (DNS rebinding) can't slip past; the Host
header, TLS's server name and its certificate check stay the name's. No proxy is used, whatever
the environment says, since a proxy would do its own resolving. Only HTML and plain text are
read, and each page is capped in bytes, time and characters.
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
PORTS = (80, 443)
# IPv6 ranges that carry an IPv4 address in their last 32 bits, judged by that address:
# IPv4-compatible (::a.b.c.d) and NAT64 (64:ff9b::a.b.c.d), which Python 3.12 calls global even
# when the address inside is 127.0.0.1. IPv4-mapped (::ffff:a.b.c.d) has ipv4_mapped.
_EMBEDS_IPV4 = (ipaddress.ip_network("::/96"), ipaddress.ip_network("64:ff9b::/96"))

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
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PublicHTTP, _PublicHTTPS, _PublicRedirects
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=TIMEOUT) as response:
        return response.headers.get_content_type(), response.read(MAX_BYTES)


def _public(url: str) -> None:
    """Raise ValueError unless the link is http(s), on port 80 or 443, to a host whose every
    address is global. It refuses a bad link before any request; the connection checks again
    the address it actually dials (see _Pinned)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("not a web link")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as e:  # a port that isn't a number
        raise ValueError("not a web link") from e
    _vetted(parts.hostname, port)


def _vetted(host: str, port: int) -> str:
    """The address to connect to for host: resolved here, once, and only when every address the
    name has is global and the port is a web one. Else ValueError."""
    if port not in PORTS:
        raise ValueError(f"not a web port ({port})")
    try:
        found = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"no such host ({host})") from e
    addresses = [str(address[0]).split("%")[0] for *_, address in found]
    if not addresses or not all(_global(a) for a in addresses):
        raise ValueError(f"not on the public internet ({host})")
    return addresses[0]


def _global(address: str) -> bool:
    """Whether an address is on the public internet, an IPv6 one that carries an IPv4 address
    judged by the IPv4 address it carries."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif any(ip in net for net in _EMBEDS_IPV4):
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global


class _Pinned:
    """A connection whose socket goes to the address _vetted checked, not to whatever the name
    resolves to next. Everything else, the Host header and TLS's server name and certificate
    check included, still goes by the name."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = self._dial

    def _dial(self, address, timeout, source_address=None):
        host, port = address
        return socket.create_connection((_vetted(host, port), port), timeout, source_address)


class _PinnedHTTP(_Pinned, http.client.HTTPConnection):
    pass


class _PinnedHTTPS(_Pinned, http.client.HTTPSConnection):
    pass


class _PublicHTTP(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTP, req)


class _PublicHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPS, req, context=self._context)


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a public host, checked the same way as the link itself (and
    dialed the same way, through _Pinned)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)
