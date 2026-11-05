"""A LaTeX paper made ready for arXiv, from made-up papers in a temporary folder: its references
checked against fake indexes and pages (no network), and its source bundled."""

import json
import os
import tarfile
import urllib.error
import urllib.parse

import pytest

from proxenos import cli, links, preprint

REAL_FETCH = preprint._fetch  # taken before conftest stands a fake in for it


def work(doi, title, family, year, subtitle=None):
    """A Crossref work, as its REST API sends one."""
    found = {
        "DOI": doi,
        "title": [title],
        "author": [{"family": family, "given": "A."}],
        "issued": {"date-parts": [[year, 5]]},
    }
    return found | ({"subtitle": [subtitle]} if subtitle else {})


def http_error(url, code, reason="Not Found"):
    return urllib.error.HTTPError(url, code, reason, None, None)


class Web:
    """Crossref, DataCite, arXiv, OpenAlex and some pages, from dicts, keeping every request.
    A title search answers with every work it has, as a search ranks loosely."""

    def __init__(
        self, dois=None, datacite=None, arxiv=None, crossref=None, openalex=None, pages=None
    ):
        self.dois, self.datacite, self.arxiv = dois or {}, datacite or {}, arxiv or {}
        self.crossref, self.openalex, self.pages = crossref or [], openalex or [], pages or {}
        self.down: set[str] = set()
        self.asked: list[str] = []

    def __call__(self, url):
        self.asked.append(url)
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        if parts.hostname in self.down:
            raise urllib.error.URLError("timed out")
        if parts.hostname == "api.crossref.org":
            if parts.path.startswith("/works/"):
                doi = urllib.parse.unquote(parts.path.removeprefix("/works/"))
                if doi not in self.dois:
                    raise http_error(url, 404)
                return "application/json", json.dumps({"message": self.dois[doi]}).encode()
            assert query["rows"] == "3" and query["query.bibliographic"]
            return "application/json", json.dumps({"message": {"items": self.crossref}}).encode()
        if parts.hostname == "api.datacite.org":
            doi = urllib.parse.unquote(parts.path.removeprefix("/dois/"))
            if doi not in self.datacite:
                raise http_error(url, 404)
            return "application/json", json.dumps({"data": self.datacite[doi]}).encode()
        if parts.hostname == "export.arxiv.org":
            entries = "".join(self.arxiv.get(query["id_list"], []))
            feed = f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
            return "application/atom+xml", feed.encode()
        if parts.hostname == "api.openalex.org":
            assert query["search"] == query["search"].lower()  # no AND, OR or NOT
            return "application/json", json.dumps({"results": self.openalex}).encode()
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        if isinstance(page, int):
            raise http_error(url, page, "Forbidden" if page == 403 else "Not Found")
        if page is None:
            raise http_error(url, 404)
        return "text/html", page.encode()


def atom(number, title, names, year):
    authors = "".join(f"<author><name>{name}</name></author>" for name in names)
    return (
        f"<entry><id>http://arxiv.org/abs/{number}v2</id><title>\n  {title}\n</title>"
        f"<published>{year}-01-05T00:00:00Z</published>"
        f"<updated>{year}-06-01T00:00:00Z</updated>{authors}</entry>"
    )


def no_wait(seconds):
    pass


# BibTeX.

BIB = r"""
This text sits outside every entry, and so does me@example.org.
@string{jml = "Journal of Made-up Learning"}
@String{ME = {Ana Lee}}
@comment{ @article{hidden, title = {Never read}} }
@preamble{"\newcommand{\noop}[1]{#1}"}
@Article{lee2021,
  Author = ME # " and Kim, Bo",
  title = {Synthetic {G}radients for {\"U}ber-Imaginary {N}etworks},
  journal = jml,
  year = 2021,
  month = mar,
  note = "A quoted {value, with a comma} and {\"o}",
}
@misc(kim2020, title = "Parenthesised", url = {https://example.org/a\_b},
  howpublished = {\url{https://example.org/x}})
@book{empty,}
"""


def test_a_bib_is_read_with_its_macros_nesting_quotes_and_comments_skipped():
    entries = preprint.parse_bib(BIB)

    assert [(e["key"], e["type"]) for e in entries] == [
        ("lee2021", "article"),
        ("kim2020", "misc"),
        ("empty", "book"),
    ]
    lee = entries[0]["fields"]
    assert lee["author"] == "Ana Lee and Kim, Bo"
    assert lee["journal"] == "Journal of Made-up Learning"
    assert (lee["year"], lee["month"]) == ("2021", "March")
    assert lee["note"] == 'A quoted {value, with a comma} and {\\"o}'
    assert preprint._latex_text(lee["title"]) == "Synthetic Gradients for Über-Imaginary Networks"
    assert preprint._url(entries[1]["fields"]) == "https://example.org/a_b"
    assert entries[2]["fields"] == {}


@pytest.mark.parametrize(
    ("authors", "surname"),
    [
        ("Lee, Ana and Kim, Bo", "Lee"),
        ("Ana Lee and others", "Lee"),
        ("Lee, Jr., Ana", "Lee"),
        ("{Imaginary Research Collective}", "Imaginary Research Collective"),
        ("Jan {van der Berg} AND Ana Lee", "van der Berg"),
        ('{\\"O}zt{\\"u}rk, Deniz', "Öztürk"),
        ("M{\\o}ller, Kai", "Møller"),
        ("\\'Alvarez, Ines", "Álvarez"),
        ("others", ""),
        ("", ""),
    ],
)
def test_the_first_authors_surname_is_read_as_bibtex_writes_names(authors, surname):
    assert preprint._surname(authors) == surname


def test_titles_compare_by_their_words_with_latex_and_a_left_off_subtitle_aside():
    same = preprint.similarity(
        "{S}ynthetic {G}radients: a \\emph{Study}", "Synthetic gradients — a study"
    )
    assert same == 1.0
    full = "Synthetic gradients for imaginary networks: a survey of nothing"
    assert preprint.similarity("Synthetic gradients for imaginary networks", full) == preprint.SAME
    assert preprint.similarity("Synthetic gradients", "Real gradients of trees") < preprint.CLOSE
    assert preprint._same_name("Grill-Spector", "Grill Spector")
    assert preprint._same_name("Berg", "van der Berg") and preprint._same_name("Lee", "Ana Lee")
    assert not preprint._same_name("Lee", "Kim")


def test_ids_are_found_wherever_a_bib_puts_them():
    def ids(**fields):
        return preprint._doi(fields), preprint._arxiv(fields)

    assert ids(doi="https://doi.org/10.5555/A.1") == ("10.5555/A.1", "")
    assert ids(url="https://dx.doi.org/10.5555/b\\_2") == ("10.5555/b_2", "")
    assert ids(eprint="2101.01234", archiveprefix="arXiv") == ("", "2101.01234")
    assert ids(eprint="math/0601001v3", eprinttype="arxiv") == ("", "math/0601001")
    assert ids(journal="arXiv preprint arXiv:2203.04567") == ("", "2203.04567")
    assert ids(url="https://arxiv.org/pdf/2101.01234v1.pdf") == ("", "2101.01234")
    assert ids(doi="10.48550/arXiv.2101.01234")[1] == "2101.01234"
    assert ids(eprint="2101.01234") == ("", "")  # an eprint not said to be arXiv's


# Checking references.

REFS = r"""
@article{found, author = {Lee, Ana}, title = {Synthetic Gradients for Imaginary Networks},
  year = {2021}, doi = {10.5555/found.1}}
@article{nearyear, author = {Kim, Bo}, title = {Counting Sheep at Scale}, year = {2020},
  doi = {10.5555/near.2}}
@article{offby, author = {Lee, Ana}, title = {Mapping Unreal Rivers}, year = {2020},
  doi = {10.5555/off.3}}
@article{wrongdoi, author = {Diaz, Cam}, title = {Dreaming in Seven Dimensions}, year = {2019},
  doi = {10.5555/other.4}}
@article{ghost, author = {Moss, Eli}, title = {A Survey of Things That Never Were},
  year = {2022}}
@article{garbled, author = {Moss, Eli}, title = {Dreams of Electric Goats at Scale},
  year = {2022}}
@article{fakedoi, author = {Moss, Eli}, title = {Benchmarks for Nothing in Particular},
  year = {2023}, doi = {10.5555/ghost.6}}
@misc{preprint, author = {Lee, Ana}, title = {Gradients All the Way Down}, year = {2021},
  eprint = {2101.01234}, archivePrefix = {arXiv}}
@software{tool, author = {Lee, Ana}, title = {Imaginary Toolkit}, year = {2022},
  doi = {10.5281/zenodo.42}}
@misc{site, title = {The Imaginary Toolkit Manual}, url = {https://example.org/manual}}
@online{dead, title = {A Page That Moved}, url = {https://example.org/gone}}
@phdthesis{thesis, author = {Moss, Eli}, title = {On Theses Nobody Indexed}, year = {2018}}
@inproceedings{workshop, author = {Park, Jo}, title = {Workshop Notes on Fictional Data},
  year = {2024}}
"""


def web_for_refs():
    return Web(
        dois={
            "10.5555/found.1": work(
                "10.5555/found.1", "Synthetic gradients for imaginary networks", "Lee", 2021
            ),
            "10.5555/near.2": work("10.5555/near.2", "Counting sheep at scale", "Kim", 2021),
            "10.5555/off.3": work("10.5555/off.3", "Mapping unreal rivers", "Kim", 2015),
            "10.5555/other.4": work("10.5555/other.4", "Soil chemistry of the moon", "Ng", 2001),
        },
        datacite={
            "10.5281/zenodo.42": {
                "attributes": {
                    "doi": "10.5281/zenodo.42",
                    "titles": [{"title": "Imaginary Toolkit"}],
                    "creators": [{"name": "Lee, Ana", "familyName": "Lee"}],
                    "publicationYear": 2022,
                }
            }
        },
        arxiv={"2101.01234": [atom("2101.01234", "Gradients all the way down", ["Ana Lee"], 2021)]},
        crossref=[
            work("10.5555/decoy.9", "A survey of rivers", "Ng", 2010),
            work("10.5555/right.5", "Dreaming in seven dimensions", "Diaz", 2019),
            work("10.5555/sheep.7", "Dreams of electric sheep at scale", "Moss", 2022),
        ],
        openalex=[
            {
                "id": "https://openalex.org/W1",
                "doi": None,
                "display_name": "Workshop notes on fictional data",
                "publication_year": 2024,
                "authorships": [{"author": {"display_name": "Jo Park"}}],
            }
        ],
        pages={
            "https://example.org/manual": "<html><head><title>Imaginary Toolkit: Manual"
            "</title></head><body>Docs</body></html>",
        },
    )


def checked(tmp_path, web, bib=REFS, **kwargs):
    path = tmp_path / "refs.bib"
    path.write_text(bib)
    report = preprint.check(path, fetch=web, wait=no_wait, **kwargs)
    return report, {entry["key"]: entry for entry in report["entries"]}


def test_each_reference_is_found_differs_or_is_not_found_and_says_why(tmp_path):
    report, by_key = checked(tmp_path, web_for_refs())

    status = {key: entry["status"] for key, entry in by_key.items()}
    assert status == {
        "found": "found",
        "nearyear": "found",
        "offby": "differs",
        "wrongdoi": "differs",
        "ghost": "not found",
        "garbled": "differs",
        "fakedoi": "not found",
        "preprint": "found",
        "tool": "found",
        "site": "page reachable",
        "dead": "page unreachable",
        "thesis": "not found",
        "workshop": "found",
    }
    assert report["counts"] == {
        "found": 5,
        "differs": 3,
        "not found": 3,
        "page reachable": 1,
        "page unreachable": 1,
        "error": 0,
    }
    assert by_key["found"]["found"]["url"] == "https://doi.org/10.5555/found.1"
    near = "year: the entry says 2020, Crossref has 2021, within a year"
    assert by_key["nearyear"]["notes"] == [f"{near} (a preprint and its journal often differ so)"]
    assert by_key["offby"]["why"] == [
        "first author: the entry says Lee, Crossref has Kim",
        "year: the entry says 2020, Crossref has 2015",
    ]
    other = "DOI 10.5555/other.4 is another work: “Soil chemistry of the moon” (Ng 2001)"
    assert by_key["wrongdoi"]["why"] == [f"{other}; the entry's is 10.5555/right.5 at Crossref"]
    assert by_key["ghost"]["why"] == ["no work with this title at Crossref or OpenAlex"]
    # A word changed: the same work, its title wrong.
    said = "the entry says “Dreams of Electric Goats at Scale”"
    assert by_key["garbled"]["why"] == [
        f"title: {said}, Crossref has “Dreams of electric sheep at scale”"
    ]
    assert by_key["fakedoi"]["why"] == [
        "DOI 10.5555/ghost.6 isn't registered at Crossref or DataCite",
        "no work with this title at Crossref or OpenAlex",
    ]
    assert by_key["preprint"]["found"]["url"] == "https://arxiv.org/abs/2101.01234"
    assert by_key["tool"]["found"]["source"] == "DataCite"
    assert by_key["workshop"]["found"]["source"] == "OpenAlex"
    assert by_key["site"]["found"] == {
        "source": "the web",
        "url": "https://example.org/manual",
        "title": "Imaginary Toolkit: Manual",
        "overlap": 0.75,
    }
    assert by_key["dead"]["why"] == ["https://example.org/gone answered 404 Not Found"]


def test_a_review_named_after_a_work_is_not_taken_for_it(tmp_path):
    sheep = {
        "id": "https://openalex.org/W2",
        "doi": "https://doi.org/10.5555/sheep.2",
        "display_name": "Counting imaginary sheep",
        "publication_year": 2020,
        "authorships": [{"author": {"display_name": "Ana Lee"}}],
    }
    web = Web(
        crossref=[work("10.5555/review.1", 'Review of "Counting imaginary sheep"', "Singh", 2021)],
        openalex=[sheep],
    )
    bib = "@article{lee, author = {Lee, Ana}, title = {Counting Imaginary Sheep}, year = {2020}}"

    _, by_key = checked(tmp_path, web, bib=bib)

    assert by_key["lee"]["status"] == "found"
    assert by_key["lee"]["found"]["id"] == "10.5555/sheep.2"


def test_only_the_references_own_metadata_goes_out(tmp_path):
    web = web_for_refs()
    checked(tmp_path, web)

    hosts = {urllib.parse.urlsplit(url).hostname for url in web.asked}
    assert hosts == {
        "api.crossref.org",
        "api.datacite.org",
        "export.arxiv.org",
        "api.openalex.org",
        "example.org",
    }
    queries = [dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query)) for u in web.asked]
    assert "A Survey of Things That Never Were Moss" in [
        q.get("query.bibliographic") for q in queries
    ]
    assert "a survey of things that never were" in [q.get("search") for q in queries]
    assert not any("@" in url for url in web.asked)


def test_a_failed_lookup_is_an_error_never_not_found(tmp_path):
    web = web_for_refs()
    web.down = {"api.crossref.org", "api.openalex.org"}

    report, by_key = checked(tmp_path, web)

    assert by_key["ghost"]["status"] == "error"
    assert by_key["ghost"]["why"] == [
        "not checked: Crossref: <urlopen error timed out>; OpenAlex: <urlopen error timed out>"
    ]
    assert by_key["preprint"]["status"] == "found"  # arXiv still answered
    assert report["counts"]["not found"] == 0
    assert "Not checked, as a lookup failed: run this again." in preprint.summary(report)


@pytest.mark.parametrize(
    ("page", "status", "why"),
    [
        (403, "page unreachable", "answered 403 Forbidden (some sites refuse"),
        (
            http_error("u", 503, "Unavailable"),
            "error",
            "not checked: https://example.org/p answered 503",
        ),
        (ValueError("no such host (example.org)"), "page unreachable", "no such host"),
        (urllib.error.URLError("timed out"), "error", "not checked: https://example.org/p:"),
    ],
)
def test_a_web_reference_that_does_not_open_says_how(tmp_path, page, status, why):
    web = Web(pages={"https://example.org/p": page})

    _, by_key = checked(
        tmp_path, web, bib="@misc{p, title = {A Page}, url = {https://example.org/p}}"
    )

    assert by_key["p"]["status"] == status
    assert why in by_key["p"]["why"][0]


def test_a_page_whose_title_shares_few_of_the_entrys_words_is_noted(tmp_path):
    web = Web(pages={"https://example.org/p": "<title>Parked domain for sale</title>"})
    bib = "@misc{p, title = {Imaginary Toolkit Documentation}, url = {https://example.org/p}}"

    _, by_key = checked(tmp_path, web, bib=bib)

    assert by_key["p"]["status"] == "page reachable"
    assert by_key["p"]["notes"] == [
        "the page's title, “Parked domain for sale”, shares 0 of the 3 words of the entry's title"
    ]


def test_answers_are_kept_so_a_second_run_asks_only_whats_new_and_hosts_are_paced(tmp_path):
    cache = tmp_path / "vault" / "state" / "preprint.json"
    web, waits = web_for_refs(), []
    path = tmp_path / "refs.bib"
    path.write_text(REFS)

    preprint.check(path, fetch=web, cache=cache, wait=waits.append)
    first = len(web.asked)
    again = preprint.check(path, fetch=web, cache=cache, wait=waits.append)

    # Asked again: only what found nothing (never kept) and the pages.
    assert len(web.asked) - first < first / 2
    assert not any("found.1" in url for url in web.asked[first:])
    assert again["counts"]["found"] == 5
    assert waits and all(0 < w <= preprint.PACES.get("export.arxiv.org") for w in waits)
    if os.name != "nt":
        assert cache.stat().st_mode & 0o777 == 0o600


def test_the_user_agent_names_proxenos_and_no_email_address(monkeypatch):
    sent = []
    monkeypatch.setattr(links, "_fetch", lambda url, headers: sent.append(headers) or ("", b""))

    REAL_FETCH("https://api.crossref.org/works/10.5555/x")

    assert sent == [{"User-Agent": "Proxenos (https://github.com/mindemory/proxenos)"}]
    assert "@" not in preprint.USER_AGENT


PAPER = r"""\documentclass{article}
\usepackage{natbib}
\begin{document}
Known \cite{found, missingone}, \citep[see][p.~3]{nearyear} and \Citet{ghost}.
\citeauthor*{found} again; \nocite{site}
% \cite{commented}
\setcitestyle{authoryear}
\newcommand{\mycite}[1]{\citep{#1}}
\input{back}
\end{document}
"""


def test_citations_with_no_entry_and_entries_never_cited_are_listed(tmp_path):
    (tmp_path / "paper.tex").write_text(PAPER)
    (tmp_path / "back.tex").write_text("\\bibliographystyle{plainnat}\n\\bibliography{refs,gone}\n")
    (tmp_path / "refs.bib").write_text(
        "@misc{found, title={A}}\n@misc{nearyear, title={B}}\n@misc{ghost, title={C}}\n"
        "@misc{site, title={D}}\n@misc{never, title={E}}\n@misc{parent, title={F}}\n"
        "@misc{child, title={G}, crossref={parent}}\n"
    )

    report = preprint.check(tmp_path / "paper.tex", fetch=Web(), wait=no_wait)

    assert report["cited_missing"] == ["missingone"]
    assert report["uncited"] == ["never", "parent", "child"]
    assert report["unread_bibs"] == [str(tmp_path / "gone.bib")]
    said = preprint.summary(report)
    assert "Cited, but in no .bib (they print as [?]): missingone" in said
    assert "gone.bib is named but isn't there" in said


def test_nocite_star_cites_everything_and_a_crossref_parent_counts(tmp_path):
    (tmp_path / "p.tex").write_text("\\cite{child}\\nocite{*}\\bibliography{refs}")
    (tmp_path / "refs.bib").write_text("@misc{a, title={A}}\n@misc{child, title={G}, crossref={a}}")
    assert preprint.check(tmp_path / "p.tex", fetch=Web(), wait=no_wait)["uncited"] == []
    (tmp_path / "p.tex").write_text("\\cite{child}\\bibliography{refs}")
    assert preprint.check(tmp_path / "p.tex", fetch=Web(), wait=no_wait)["uncited"] == []


def test_the_summary_says_plainly_what_to_fix(tmp_path):
    report, _ = checked(tmp_path, web_for_refs())

    said = preprint.summary(report)

    assert said.startswith("refs.bib: 13 references in refs.bib\n  5 found, 3 differs, 3 not found")
    assert "These are what arXiv bars authors for" in said
    assert "  ghost: “A Survey of Things That Never Were” (Moss 2022)" in said
    assert "a book, thesis or report can be real and in no index" in said
    assert "    - the record: https://doi.org/10.5555/off.3" in said
    assert "Found, with something to look at:" in said and "nearyear" in said
    assert said.splitlines()[-1] == "To fix before you post it: 7 references."


def test_a_paper_with_no_bib_or_no_file_is_said_and_exits(tmp_path):
    (tmp_path / "p.tex").write_text("\\begin{document}\\end{document}")
    with pytest.raises(SystemExit, match="names no .bib"):
        preprint.check(tmp_path / "p.tex", fetch=Web())
    with pytest.raises(SystemExit, match="no such file"):
        preprint.check(tmp_path / "nope.tex", fetch=Web())
    (tmp_path / "q.tex").write_text("\\bibliography{absent}")
    with pytest.raises(SystemExit, match="none is beside it"):
        preprint.check(tmp_path / "q.tex", fetch=Web())


# The source.

SOURCE = r"""\documentclass{article}
% a whole-line comment
   % an indented one
Text with 5\% of it kept. % a trailing comment
A line break \\% then a comment
Glued%
lines
\begin{verbatim}
% kept in verbatim
\end{verbatim}
\begin{lstlisting}
x = 1 % kept in a listing
\end{lstlisting}
\begin{comment}
% kept in a comment environment
\end{comment}
Inline \verb|50%| and \url{https://example.org/a%20b} stay. % but this goes
%
"""

STRIPPED = r"""\documentclass{article}
Text with 5\% of it kept. %
A line break \\%
Glued%
lines
\begin{verbatim}
% kept in verbatim
\end{verbatim}
\begin{lstlisting}
x = 1 % kept in a listing
\end{lstlisting}
\begin{comment}
% kept in a comment environment
\end{comment}
Inline \verb|50%| and \url{https://example.org/a%20b} stay. %
"""


def test_comments_go_but_escaped_percents_line_ends_and_verbatim_stay():
    text, lines, trailing = preprint.strip_comments(SOURCE)

    assert text == STRIPPED
    assert (lines, trailing) == (3, 3)
    assert preprint.strip_comments("a % b\r\nc\r\n")[0] == "a %\r\nc\r\n"


def paper(tmp_path):
    """A made-up paper's folder, with what the bundle takes and what it leaves."""
    folder = tmp_path / "paper"
    (folder / "sections").mkdir(parents=True)
    (folder / "figs").mkdir()
    (folder / ".git").mkdir()
    (folder / "main.tex").write_text(
        "\\documentclass[11pt]{mycls}\n"
        "\\usepackage{mystyle,amsmath}\n"
        "\\graphicspath{{figs/}}\n"
        "\\begin{document}\n"
        "\\input{sections/intro}\n"
        "\\include{appendix}\n"
        "\\includegraphics[width=\\linewidth]{fig1}\n"
        "\\includegraphics{plot}\n"
        "% \\input{secret}\n"
        "\\bibliographystyle{mybst}\n"
        "\\bibliography{refs}\n"
        "\\end{document}\n"
    )
    (folder / "sections" / "intro.tex").write_text("Intro. % to cut\n% gone\nMore.\n")
    (folder / "appendix.tex").write_text("Appendix.\n")
    (folder / "secret.tex").write_text("Not referenced.\n")
    (folder / "mycls.cls").write_text("\\LoadClass{article}\n")
    (folder / "mystyle.sty").write_text("\\RequirePackage{helper}\n% keep me in a style\n")
    (folder / "helper.sty").write_text("\\relax\n")
    (folder / "mybst.bst").write_text("ENTRY\n")
    (folder / "fig1.pdf").write_bytes(b"%PDF-1.4 one")
    (folder / "fig1.png").write_bytes(b"\x89PNG not this one")
    (folder / "figs" / "plot.png").write_bytes(b"\x89PNG plot")
    for name in ("unused.png", "notes.txt", "main.aux", "main.log", "main.pdf", "main.out"):
        (folder / name).write_text("left out")
    (folder / ".git" / "config").write_text("[core]")
    (folder / "refs.bib").write_text("@misc{a, title={A}}")
    (folder / "main.bbl").write_text("\\begin{thebibliography}{1}\\end{thebibliography}\n")
    for written in (p for p in folder.rglob("*") if p.is_file()):  # \n, not Windows' CRLF
        written.write_bytes(written.read_bytes().replace(b"\r\n", b"\n"))
    os.utime(folder / "refs.bib", (1_000_000, 1_000_000))
    os.utime(folder / "main.bbl", (2_000_000, 2_000_000))
    return folder


def members(path):
    with tarfile.open(path) as tar:
        return {
            m.name: (m, tar.extractfile(m).read().decode(errors="replace"))
            for m in tar.getmembers()
        }


def test_the_bundle_holds_what_the_paper_uses_and_nothing_else(tmp_path):
    folder = paper(tmp_path)

    report = preprint.bundle(folder / "main.tex")

    assert report["bundle"] == str(folder / "main-arxiv.tar.gz")
    inside = members(folder / "main-arxiv.tar.gz")
    assert set(inside) == {
        "main.tex",
        "sections/intro.tex",
        "appendix.tex",
        "fig1.pdf",
        "figs/plot.png",
        "mycls.cls",
        "mystyle.sty",
        "helper.sty",
        "mybst.bst",
        "main.bbl",
    }
    assert inside["sections/intro.tex"][1] == "Intro. %\nMore.\n"
    assert "secret" not in inside["main.tex"][1]
    assert "% keep me in a style" in inside["mystyle.sty"][1]  # only .tex files are cut
    assert inside["fig1.pdf"][1] == "%PDF-1.4 one"
    assert all(m.uname == "" and m.gname == "" and m.uid == 0 for m, _ in inside.values())
    assert report["comments"] == {"lines": 2, "trailing": 1}
    assert report["files"][0]["name"] == "main.tex"
    assert report["warnings"] == []
    said = preprint.described(report)
    assert "main-arxiv.tar.gz: 10 files" in said and "of the 50.0 MB arXiv takes" in said
    assert "Comments taken out: 2 whole lines and 1 at the ends of lines." in said


def test_there_is_no_bundle_without_a_current_bbl(tmp_path):
    folder = paper(tmp_path)
    os.utime(folder / "refs.bib", (3_000_000, 3_000_000))
    with pytest.raises(SystemExit, match="main.bbl is older than refs.bib: compile the paper"):
        preprint.bundle(folder / "main.tex")
    (folder / "main.bbl").unlink()
    with pytest.raises(SystemExit, match="there's no main.bbl. arXiv doesn't run BibTeX"):
        preprint.bundle(folder / "main.tex")
    assert not (folder / "main-arxiv.tar.gz").exists()


def test_ancillary_files_go_in_anc_and_what_shouldnt_be_published_is_warned_of(tmp_path):
    folder = paper(tmp_path)
    (folder / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\author{Ana Lee \\\\ \\texttt{ana@uni.example}}\n"
        "\\date{\\href{mailto:lab@uni.example}{lab}}\n"
        "\\begin{document}\n\\maketitle\n"
        "Write to bo@other.example for data.\n"
        "% TODO hidden in a comment, so gone\n"
        "TODO: say more.\n"
        "\\includegraphics{/Users/ana/figs/raw.pdf}\n"
        "\\includegraphics{missing}\n"
        "\\end{document}\n"
    )
    scripts = tmp_path / "scripts"
    (scripts / "__pycache__").mkdir(parents=True)
    (scripts / "fit.py").write_text("DATA = '/home/ana/data'  # FIXME\n")
    (scripts / "__pycache__" / "fit.pyc").write_bytes(b"\0")
    (tmp_path / "analysis.py").write_text("print('hi')\n")
    out = tmp_path / "out"

    report = preprint.bundle(folder / "main.tex", out, [tmp_path / "analysis.py", scripts])

    inside = members(out / "main-arxiv.tar.gz")
    assert {"anc/analysis.py", "anc/scripts/fit.py"} <= set(inside)
    assert "anc/scripts/__pycache__/fit.pyc" not in inside
    # By the line in the user's own main.tex, the comment line cut from the bundle counted.
    assert [(w["file"], w["line"], w["kind"]) for w in report["warnings"]] == [
        (None, None, "outside"),
        (None, None, "missing"),
        ("main.tex", 6, "email"),
        ("main.tex", 8, "note"),
        ("main.tex", 9, "home"),
        ("anc/scripts/fit.py", 1, "home"),
        ("anc/scripts/fit.py", 1, "note"),
    ]
    texts = [w["text"] for w in report["warnings"]]
    assert "an email address: bo@other.example" in texts
    assert "a home folder's path: /home/ana" in texts
    said = preprint.described(report)
    assert "Look at these before you upload" in said and "main.tex:6  an email address" in said


def test_the_commands_print_the_check_and_the_bundle(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(preprint, "_fetch", web_for_refs())
    monkeypatch.setattr(preprint, "PACE", 0)
    monkeypatch.setattr(preprint, "PACES", {})
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    (tmp_path / "refs.bib").write_text(REFS)

    cli.main(["preprint", "refs", str(tmp_path / "refs.bib")])
    printed = capsys.readouterr()
    assert "5 found, 3 differs, 3 not found" in printed.out
    assert "refs: looking up 13 references" in printed.err
    assert (vault / "state" / "preprint.json").is_file()  # kept in the vault there is

    cli.main(["preprint", "refs", str(tmp_path / "refs.bib"), "--json"])
    assert json.loads(capsys.readouterr().out)["counts"]["differs"] == 3

    folder = paper(tmp_path)
    cli.main(["preprint", "bundle", str(folder / "main.tex"), "--anc", str(folder / "notes.txt")])
    assert "anc/notes.txt" in capsys.readouterr().out
    assert "anc/notes.txt" in members(folder / "main-arxiv.tar.gz")
