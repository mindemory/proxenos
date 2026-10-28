"""Reading linked pages, with the network faked out."""

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
