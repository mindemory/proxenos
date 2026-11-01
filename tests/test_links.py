"""Reading linked pages, with the network faked out."""

import io
import socket

import pytest

from proxenos import links


def test_finds_links_without_trailing_punctuation_each_once():
    text = "see https://a.org/x. and (https://b.org/y?z=1), again https://a.org/x"
    assert links.find(text) == ["https://a.org/x", "https://b.org/y?z=1"]
    assert links.find("") == []


def test_reads_a_page_as_its_title_and_visible_text():
    html = b"<html><head><title>Burnout</title><script>x()</script></head><body><nav>Menu</nav>"
    html += b"<h1>Burnout</h1><p>Stage three is the last safe point.</p></body></html>"

    page = links.read("https://a.org/b", fetch=lambda url: ("text/html", html))

    assert page == {
        "url": "https://a.org/b",
        "title": "Burnout",
        "text": "Burnout\nStage three is the last safe point.",
    }


def test_says_why_a_page_could_not_be_read():
    def refused(url):
        raise OSError("HTTP Error 403: Forbidden")

    assert links.read("https://a.org", fetch=refused)["error"] == "HTTP Error 403: Forbidden"
    pdf = links.read("https://a.org/p", fetch=lambda url: ("application/pdf", b"%PDF"))
    assert pdf["error"] == "not a page (application/pdf)"
    empty = links.read("https://a.org/e", fetch=lambda url: ("text/html", b"<p> </p>"))
    assert empty["error"] == "no text on the page"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:4747/api",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.org/",
    ],
)
def test_never_reaches_this_computer_or_the_local_network(url):
    with pytest.raises(ValueError):
        links._public(url)
    assert "error" in links.read(url)


def test_a_redirect_to_the_local_network_is_refused():
    handler = links._PublicRedirects()
    with pytest.raises(ValueError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://192.168.1.1/admin")


# The connection itself, with name lookups and sockets faked out.

PUBLIC = "93.184.216.34"


def resolves(monkeypatch, answers):
    """Fake name lookups: each name answers with its addresses in turn, then the last for good,
    as a record with no time to live would. Returns the names asked, in order."""
    asked = []

    def getaddrinfo(host, port, *args, **kwargs):
        asked.append(host)
        found = answers[host]
        address = found.pop(0) if len(found) > 1 else found[0]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


class FakeSocket:
    """A socket that keeps what's sent to it and answers with one canned response."""

    def __init__(self, reply):
        self.sent, self.reply = b"", reply

    def setsockopt(self, *args):
        pass

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        return io.BytesIO(self.reply)

    def close(self):
        pass


def dials(monkeypatch, replies):
    """Fake connections, each answering with the next of `replies`. Returns what was dialed."""
    dialed = []

    def create_connection(address, timeout=None, source_address=None):
        sock = FakeSocket(replies.pop(0))
        dialed.append((address, sock))
        return sock

    monkeypatch.setattr(socket, "create_connection", create_connection)
    return dialed


def page(body=b"<title>Hi</title><p>Hello there.</p>"):
    head = f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n\r\n"
    return head.encode() + body


def test_dials_the_address_it_checked_with_the_name_as_host_and_no_proxy(monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    resolves(monkeypatch, {"a.org": [PUBLIC]})
    dialed = dials(monkeypatch, [page()])

    read = links.read("http://a.org/x")

    assert read == {"url": "http://a.org/x", "title": "Hi", "text": "Hello there."}
    ((address, sock),) = dialed
    assert address == (PUBLIC, 80)  # the address checked: not the proxy, nor the name again
    assert sock.sent.startswith(b"GET /x HTTP/1.1\r\n") and b"\r\nHost: a.org\r\n" in sock.sent


def test_a_name_that_turns_local_after_the_check_is_never_dialed(monkeypatch):
    # Public when first asked, this computer a moment later: the address dialed is checked too.
    asked = resolves(monkeypatch, {"rebind.example": [PUBLIC, "127.0.0.1"]})
    dialed = dials(monkeypatch, [page()])

    assert "not on the public internet" in links.read("http://rebind.example/")["error"]
    assert asked == ["rebind.example", "rebind.example"] and not dialed


def test_every_redirect_is_checked_and_dialed_the_same_way(monkeypatch):
    resolves(monkeypatch, {"a.org": [PUBLIC], "inside.example": ["10.0.0.7"]})
    moved = b"HTTP/1.1 302 Found\r\nLocation: http://inside.example/admin\r\n"
    dialed = dials(monkeypatch, [moved + b"Content-Length: 0\r\n\r\n", page()])

    assert "not on the public internet" in links.read("http://a.org/go")["error"]
    assert [address for address, _ in dialed] == [(PUBLIC, 80)]


def test_tls_keeps_the_name_for_its_server_name_and_certificate(monkeypatch):
    resolves(monkeypatch, {"a.org": [PUBLIC]})
    dialed = dials(monkeypatch, [b""])
    wrapped = []

    class Context:
        def wrap_socket(self, sock, server_hostname=None):
            wrapped.append(server_hostname)
            return sock

    links._PinnedHTTPS("a.org", 443, context=Context()).connect()

    assert dialed[0][0] == (PUBLIC, 443) and wrapped == ["a.org"]


@pytest.mark.parametrize(
    "address",
    [
        "::ffff:127.0.0.1",  # IPv4-mapped
        "::ffff:10.0.0.1",
        "::127.0.0.1",  # IPv4-compatible
        "::a00:1",
        "64:ff9b::7f00:1",  # NAT64, which Python 3.12 calls global
        "64:ff9b::a9fe:a9fe",
        "fe80::1",
        "fd00::1",
    ],
)
def test_ipv6_carrying_a_local_ipv4_address_is_refused(monkeypatch, address):
    resolves(monkeypatch, {"six.example": [address]})
    with pytest.raises(ValueError):
        links._public("https://six.example/")


def test_ipv6_carrying_a_public_ipv4_address_is_allowed():
    assert links._global("::ffff:93.184.216.34") and links._global("64:ff9b::5db8:d822")
    assert links._global("2606:4700::1111")


@pytest.mark.parametrize("url", ["https://a.org:8443/", "http://a.org:22/", "http://a.org:x/"])
def test_only_web_ports(monkeypatch, url):
    resolves(monkeypatch, {"a.org": [PUBLIC]})
    with pytest.raises(ValueError):
        links._public(url)
    links._public("http://a.org:80/")
    links._public("https://a.org:443/")
