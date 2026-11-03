"""A project's manuscript as a Google Doc and back, against a fake Drive and a small git
repository made here. No network, no model, no real document and no real repository."""

import io
import json
import os
import re
import stat
import subprocess
import urllib.error
import urllib.parse
from datetime import UTC, datetime

import pytest

from proxenos import cli, gdocs, llm, manuscript, paperdoc
from proxenos.clones import projects, steps

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 11, 2, 0, tzinfo=UTC)
LATEST = datetime(2026, 3, 12, 2, 0, tzinfo=UTC)
REFRESH = "1//refresh-token-that-must-never-show"
ACCESS = "ya29.access-token-that-must-never-show"

PAPER = (
    "# Birdsong at dawn\n\n"
    "Birds sing *loudly* at dawn [@smith2020].\n\n"
    "- wrens\n- robins\n\n"
    "Methods follow.\n\n"
    "Thanks to the lab.\n"
)


def as_docs_writes_it(text, mime):
    """What a Doc made from the text exports as: Markdown in Docs' own spelling."""
    if mime != "text/markdown":
        return text
    return text.replace("*loudly*", "_loudly_").replace("[@", "\\[@").replace("- ", "* ")


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, io.BytesIO(b"{}"))


class FakeDrive:
    """Google's token endpoint and the Drive API for the docs this sign-in made: an upload makes
    a doc of the text as Docs would write it, an export gives the doc back (plain text with a
    byte-order mark and Windows line ends, as Docs gives it), and comments come a page at a
    time. A test edits a doc as a co-author would, through `docs`."""

    def __init__(self):
        self.docs = {}  # doc id → its text, as exported
        self.notes = {}  # doc id → its comments, as the API lists them
        self.uploads = []
        self.requests = []
        self.failures = {}  # url without its query → errors to raise first

    def __call__(self, request):
        self.requests.append(request)
        base, _, query = request.full_url.partition("?")
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        if self.failures.get(base):
            raise self.failures[base].pop(0)
        if base == gdocs.GOOGLE_TOKEN:
            form = {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}
            assert form["refresh_token"] == REFRESH and form["grant_type"] == "refresh_token"
            return json.dumps({"access_token": ACCESS, "expires_in": 3599}).encode()
        assert request.headers["Authorization"] == f"Bearer {ACCESS}"
        if base == gdocs.UPLOAD:
            return self.upload(request, params)
        doc, what = re.fullmatch(re.escape(gdocs.FILES) + r"/([\w-]+)/(\w+)", base).groups()
        if doc not in self.docs:
            raise http_error(404)
        if what == "export":
            text = self.docs[doc]
            if params["mimeType"] == "text/plain":
                text = "\ufeff" + text.replace("\n", "\r\n")
            return text.encode()
        assert what == "comments" and "replies(" in params["fields"]
        start = int(params.get("pageToken", 0))
        page = {"comments": self.notes.get(doc, [])[start : start + 2]}
        if start + 2 < len(self.notes.get(doc, [])):
            page["nextPageToken"] = str(start + 2)
        return json.dumps(page).encode()

    def upload(self, request, params):
        assert request.get_method() == "POST" and params["uploadType"] == "multipart"
        kind, _, boundary = request.get_header("Content-type").partition("; boundary=")
        assert kind == "multipart/related" and boundary
        body = request.data.decode()
        assert body.endswith(f"--{boundary}--\r\n")
        parts = [p.removeprefix("\r\n").split("\r\n\r\n", 1) for p in body.split(f"--{boundary}")]
        (meta_head, meta), (media_head, media) = parts[1], parts[2]
        upload = {
            "meta_type": meta_head,
            "meta": json.loads(meta),
            "media_type": media_head,
            "text": media.removesuffix("\r\n"),
            "fields": params["fields"],
        }
        self.uploads.append(upload)
        doc = f"doc-{len(self.uploads):02d}-made-by-proxenos"
        mime = media_head.removeprefix("Content-Type: ").split(";")[0]
        self.docs[doc] = as_docs_writes_it(upload["text"], mime)
        return json.dumps(
            {"id": doc, "webViewLink": f"https://docs.google.com/document/d/{doc}/edit"}
        ).encode()

    def urls(self):
        return [r.full_url for r in self.requests]


def git(where, *args):
    return subprocess.run(
        ["git", "-C", str(where), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo, files, message, day):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    git(repo, "add", "-A")
    stamp = f"2026-03-0{day}T12:00:00+00:00"
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", message],
        check=True,
        env=dict(os.environ) | {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A vault, a Google Docs sign-in, and a project's repository checked out on main, with its
    paper on a side branch."""
    monkeypatch.setenv("PROXENOS_WORKTREES", str(tmp_path / "worktrees"))
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GDOCS_PERSONAL", f"joe@home.example:oauth:{REFRESH}")
    repo = tmp_path / "code"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Joe")
    git(repo, "config", "user.email", "joe@example.org")
    commit(repo, {"analysis.py": "print('mean')\n"}, "Start", 1)
    git(repo, "checkout", "-q", "-b", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": PAPER}, "Draft the paper", 2)
    git(repo, "checkout", "-q", "main")
    vault = tmp_path / "vault"
    write_list(vault, {"id": "calls", "name": "Calls", "repo": str(repo)})
    return vault, repo


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": list(items)}))


def project(vault):
    return projects.listed_projects(vault)[0]


def kept(vault, name):
    return (vault / "clones" / "projects" / "calls" / "gdocs" / name).read_text()


def checkout_of(repo):
    return (
        git(repo, "branch", "--show-current"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "status", "--porcelain"),
    )


def private(path):
    return os.name == "nt" or stat.S_IMODE(path.stat().st_mode) == 0o600


def test_opening_uploads_the_manuscript_as_a_private_google_doc_and_keeps_a_baseline(setup):
    vault, repo = setup
    fake = FakeDrive()
    tip = git(repo, "rev-parse", "paper-storyline")
    before = checkout_of(repo)

    shown = paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)

    # One multipart upload: the doc's name and Google Docs' type, then the text at the tip, as
    # Markdown. Nothing else is asked of Drive but the export back: no sharing, no listing.
    [upload] = fake.uploads
    assert upload["meta"] == {"name": "Calls: paper.md", "mimeType": gdocs.DOC}
    assert upload["meta_type"] == "Content-Type: application/json; charset=UTF-8"
    assert upload["media_type"] == "Content-Type: text/markdown; charset=UTF-8"
    assert upload["text"] == PAPER and upload["fields"] == "id,webViewLink"
    doc_id = "doc-01-made-by-proxenos"
    assert [u.partition("?")[0] for u in fake.urls()] == [
        gdocs.GOOGLE_TOKEN,
        gdocs.UPLOAD,
        f"{gdocs.FILES}/{doc_id}/export",
    ]
    assert not any("permissions" in u for u in fake.urls())

    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    assert shown["doc"] == {
        "link": link,
        "title": "Calls: paper.md",
        "account": "personal",
        "address": "joe@home.example",
        "path": "docs/paper/paper.md",
        "branch": "paper-storyline",
        "commit": tip,
        "at": "2026-03-10T02:00:00Z",
        "pulled": None,
        "step": None,
    }
    assert shown["accounts"] == [{"name": "personal", "address": "joe@home.example"}]
    assert shown["comments"] == [] and shown["comments_read"] is None
    record = json.loads(kept(vault, "doc.json"))
    assert record["doc_id"] == doc_id and record["from"] == tip
    # The baseline is the doc as Docs writes it, not the manuscript.
    assert kept(vault, "baseline.txt") == as_docs_writes_it(PAPER, "text/markdown") != PAPER

    folder = vault / "clones" / "projects" / "calls" / "gdocs"
    assert os.name == "nt" or stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert all(private(f) for f in folder.iterdir())
    assert checkout_of(repo) == before
    shown_text = json.dumps(shown)
    assert REFRESH not in shown_text and ACCESS not in shown_text


def test_a_project_has_one_doc_unless_a_fresh_copy_is_asked_for(setup):
    vault, _ = setup
    fake = FakeDrive()
    first = paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)

    again = paperdoc.open_doc(vault, project(vault), now=LATER, fetch=fake)
    assert again["doc"] == first["doc"] and len(fake.uploads) == 1
    assert len(fake.requests) == 3  # the link from the vault, with nothing asked of Google

    fresh = paperdoc.open_doc(vault, project(vault), fresh=True, now=LATER, fetch=fake)
    assert len(fake.uploads) == 2 and fresh["doc"]["link"] != first["doc"]["link"]
    assert fresh["doc"]["at"] == "2026-03-11T02:00:00Z"
    assert json.loads(kept(vault, "doc.json"))["doc_id"] == "doc-02-made-by-proxenos"


def test_a_doc_made_but_never_read_back_is_read_back_not_made_again(setup):
    vault, _ = setup
    fake = FakeDrive()
    fake.failures[f"{gdocs.FILES}/doc-01-made-by-proxenos/export"] = [http_error(500)]
    with pytest.raises(SystemExit, match="Google answered 500"):
        paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)

    shown = paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    assert len(fake.uploads) == 1 and shown["doc"]["link"].endswith("doc-01-made-by-proxenos/edit")
    assert kept(vault, "baseline.txt") == as_docs_writes_it(PAPER, "text/markdown")


def test_latex_goes_up_and_comes_back_as_plain_text(setup):
    vault, repo = setup
    tex = "\\section{Dawn}\r\n\r\nBirds sing.\r\n\r\nMethods follow.\r\n"
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"paper/main.tex": tex}, "Start the LaTeX", 3)
    git(repo, "checkout", "-q", "main")
    write_list(
        vault,
        {
            "id": "calls",
            "name": "Calls",
            "repo": str(repo),
            "manuscript": {"path": "paper/main.tex", "branch": "paper-storyline"},
        },
    )
    assert gdocs.mime_for("paper/main.tex") == "text/plain"
    assert gdocs.mime_for("notes.markdown") == "text/markdown"
    fake = FakeDrive()

    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)

    [upload] = fake.uploads
    assert upload["media_type"] == "Content-Type: text/plain; charset=UTF-8"
    assert upload["text"] == tex.replace("\r\n", "\n")
    # The export's byte-order mark and Windows line ends are taken out.
    assert kept(vault, "baseline.txt") == tex.replace("\r\n", "\n")

    # A changed paragraph comes back with the file's own line ends kept.
    doc = "doc-01-made-by-proxenos"
    fake.docs[doc] = fake.docs[doc].replace("Methods follow.", "Methods follow, in brief.")
    answer = paperdoc.pull(vault, project(vault), LATER, fake)
    branch = steps.load(vault, answer["step"])["branch"]
    shown = subprocess.run(
        ["git", "-C", str(repo), "show", f"{branch}:paper/main.tex"],
        capture_output=True,
        check=True,
    ).stdout
    assert shown == tex.replace("Methods follow.", "Methods follow, in brief.").encode()


def test_only_the_paragraphs_changed_in_docs_change(setup):
    baseline = as_docs_writes_it(PAPER, "text/markdown")
    # Nothing changed: the manuscript as it was, to the byte.
    assert paperdoc.rebuild(PAPER, baseline, baseline) == PAPER

    # One edited, one added after it, one deleted: the others keep their Markdown.
    now = (
        baseline.replace("Methods follow.", "Methods follow, in short.\n\nData came from wrens.")
        .replace("Thanks to the lab.\n", "")
        .rstrip("\n")
        + "\n"
    )
    rebuilt = paperdoc.rebuild(PAPER, baseline, now)
    assert rebuilt == (
        "# Birdsong at dawn\n\n"
        "Birds sing *loudly* at dawn [@smith2020].\n\n"
        "- wrens\n- robins\n\n"
        "Methods follow, in short.\n\n"
        "Data came from wrens.\n"
    )

    # A paragraph added at the end doesn't run into the one that was last.
    added = baseline + "\nAnd the owls.\n"
    assert paperdoc.rebuild(PAPER, baseline, added) == PAPER + "\nAnd the owls.\n"
    # One added at the start keeps the rest.
    first = "A note first.\n\n" + baseline
    assert paperdoc.rebuild(PAPER, baseline, first) == "A note first.\n\n" + PAPER
    # An edited paragraph comes back as Docs writes it; its neighbours as the manuscript does.
    edited = baseline.replace("_loudly_ at dawn", "_softly_ at dawn")
    assert paperdoc.rebuild(PAPER, baseline, edited) == PAPER.replace(
        "Birds sing *loudly* at dawn [@smith2020].",
        "Birds sing _softly_ at dawn \\[@smith2020].",
    )
    # Everything deleted is an empty manuscript.
    assert paperdoc.rebuild(PAPER, baseline, "") == ""

    # When Docs split the text into another number of paragraphs, there's no pairing to trust,
    # so the doc comes back whole.
    reshaped = baseline.replace("* wrens\n* robins", "* wrens\n\n* robins")
    changed = reshaped.replace("Methods follow.", "Methods follow, in short.")
    assert paperdoc.rebuild(PAPER, reshaped, changed) == changed


def test_bringing_back_nothing_changed_makes_no_step(setup):
    vault, repo = setup
    fake = FakeDrive()
    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    baseline = kept(vault, "baseline.txt")

    answer = paperdoc.pull(vault, project(vault), LATER, fake)

    assert answer["changed"] is False and answer["step"] is None
    assert answer["said"] == "Nothing has changed in the doc."
    assert answer["doc"]["pulled"] == "2026-03-11T02:00:00Z"
    assert projects.steps_taken(vault, "calls") == []
    assert git(repo, "branch", "--list", "proxenos/*") == ""
    assert kept(vault, "baseline.txt") == baseline

    # Changes that come back to the manuscript as it is bring nothing back either.
    fake.docs["doc-01-made-by-proxenos"] = PAPER.rstrip("\n")
    answer = paperdoc.pull(vault, project(vault), LATEST, fake)
    assert answer["changed"] is False and answer["said"].startswith("Only how Docs writes it")
    assert projects.steps_taken(vault, "calls") == []


def test_bringing_back_changes_makes_a_step_from_the_commit_uploaded(setup):
    vault, repo = setup
    fake = FakeDrive()
    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    uploaded = git(repo, "rev-parse", "paper-storyline")
    # Meanwhile the paper moves on in git, in a paragraph no one touches in Docs.
    git(repo, "checkout", "-q", "paper-storyline")
    commit(repo, {"docs/paper/paper.md": PAPER.replace("Thanks", "Our thanks")}, "Thank", 3)
    git(repo, "checkout", "-q", "main")
    before = checkout_of(repo)
    doc = "doc-01-made-by-proxenos"
    fake.docs[doc] = fake.docs[doc].replace("Methods follow.", "Methods follow, in short.")

    answer = paperdoc.pull(vault, project(vault), LATER, fake)

    assert answer["changed"] is True and answer["step"] == "calls/20260311-020000"
    step = steps.load(vault, answer["step"])
    assert step["kind"] == "edit" and step["status"] == "ready"
    assert step["base"] == "paper-storyline" and step["base_commit"] == uploaded
    assert step["branch"] == "proxenos/calls-edit-20260311-020000"
    assert step["step"] == "What changed in its Google Doc, for docs/paper/paper.md"
    assert step["did"].startswith("Brought back what changed in docs/paper/paper.md's Google Doc")
    assert answer["said"] == step["summary"]
    # Only that paragraph changed; the rest is the manuscript's own Markdown, to the byte.
    on_branch = git(repo, "show", f"{step['branch']}:docs/paper/paper.md") + "\n"
    assert on_branch == PAPER.replace("Methods follow.", "Methods follow, in short.")
    assert git(repo, "log", "-1", "--format=%s", step["branch"]) == (
        "Bring in what changed in its Google Doc to docs/paper/paper.md."
    )
    assert kept(vault, "baseline.txt") == fake.docs[doc]
    assert answer["doc"]["step"] == step["id"]
    assert checkout_of(repo) == before
    # It's one of the manuscript's versions, as an edit waiting on the user.
    listed = manuscript.versions(project(vault), manuscript.find(project(vault)))
    assert listed[0]["edit"] and listed[0]["step"] == step["id"]

    # While it waits, another pull is refused, and nothing is fetched.
    asked = len(fake.requests)
    with pytest.raises(SystemExit, match="still waits on you"):
        paperdoc.pull(vault, project(vault), LATEST, fake)
    assert len(fake.requests) == asked

    # Accepted, it merges with what changed in git, and the next pull starts from it.
    git(repo, "checkout", "-q", "paper-storyline")
    steps.accept(vault, step["id"], LATER)
    merged = (repo / "docs" / "paper" / "paper.md").read_text()
    assert "Methods follow, in short." in merged and "Our thanks to the lab." in merged
    fake.docs[doc] = fake.docs[doc].replace("# Birdsong at dawn", "# Birdsong at first light")
    second = paperdoc.pull(vault, project(vault), LATEST, fake)
    later = steps.load(vault, second["step"])
    assert later["base_commit"] == step["head"]
    shown = git(repo, "show", f"{later['branch']}:docs/paper/paper.md") + "\n"
    assert shown == PAPER.replace("Methods follow.", "Methods follow, in short.").replace(
        "# Birdsong at dawn", "# Birdsong at first light"
    )
    steps.accept(vault, later["id"], LATEST)
    final = (repo / "docs" / "paper" / "paper.md").read_text()
    assert final == (
        PAPER.replace("Methods follow.", "Methods follow, in short.")
        .replace("# Birdsong at dawn", "# Birdsong at first light")
        .replace("Thanks", "Our thanks")
    )


def test_a_discarded_pull_is_not_brought_back_again(setup):
    vault, repo = setup
    fake = FakeDrive()
    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    uploaded = git(repo, "rev-parse", "paper-storyline")
    doc = "doc-01-made-by-proxenos"
    fake.docs[doc] = fake.docs[doc].replace("Methods follow.", "Methods follow, roughly.")
    first = paperdoc.pull(vault, project(vault), LATER, fake)
    steps.discard(vault, first["step"], LATER)

    fake.docs[doc] = fake.docs[doc].replace("Thanks to the lab.", "Thanks to everyone.")
    second = paperdoc.pull(vault, project(vault), LATEST, fake)

    later = steps.load(vault, second["step"])
    assert later["base_commit"] == uploaded
    shown = git(repo, "show", f"{later['branch']}:docs/paper/paper.md") + "\n"
    assert shown == PAPER.replace("Thanks to the lab.", "Thanks to everyone.")


def test_comments_are_kept_for_the_page_and_never_reach_a_model(setup, monkeypatch):
    vault, _ = setup

    def no_model(*args, **kwargs):
        pytest.fail("a comment went to a model")

    for name in ("ask", "ask_voice", "_ask", "_ask_local", "_chat", "_complete"):
        monkeypatch.setattr(llm, name, no_model)
    fake = FakeDrive()
    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    doc = "doc-01-made-by-proxenos"
    fake.notes[doc] = [
        {
            "id": "c2",
            "author": {"displayName": "Ana Lee"},
            "content": "Cite the 2019 study here.",
            "quotedFileContent": {"mimeType": "text/html", "value": "Methods follow."},
            "resolved": False,
            "createdTime": "2026-03-10T09:00:00.000Z",
            "replies": [
                {
                    "author": {"displayName": "Joe"},
                    "content": "Will do.",
                    "createdTime": "2026-03-10T10:00:00.000Z",
                },
                {"author": {"displayName": "Joe"}, "deleted": True, "content": ""},
            ],
        },
        {
            "id": "c1",
            "author": {"displayName": "Ben Ode"},
            "content": "Lovely opening.",
            "resolved": True,
            "createdTime": "2026-03-09T08:00:00.000Z",
        },
        {"id": "c3", "deleted": True, "createdTime": "2026-03-10T11:00:00.000Z"},
    ]

    shown = paperdoc.read_comments(vault, project(vault), LATER, fake)

    assert shown["comments_read"] == "2026-03-11T02:00:00Z"
    assert shown["comments"] == [
        {
            "id": "c1",
            "author": "Ben Ode",
            "content": "Lovely opening.",
            "quoted": "",
            "resolved": True,
            "created": "2026-03-09T08:00:00.000Z",
            "replies": [],
        },
        {
            "id": "c2",
            "author": "Ana Lee",
            "content": "Cite the 2019 study here.",
            "quoted": "Methods follow.",
            "resolved": False,
            "created": "2026-03-10T09:00:00.000Z",
            "replies": [
                {"author": "Joe", "content": "Will do.", "created": "2026-03-10T10:00:00.000Z"}
            ],
        },
    ]
    assert private(vault / "clones" / "projects" / "calls" / "gdocs" / "comments.json")
    # Kept, they're shown again with nothing fetched.
    asked = len(fake.requests)
    assert paperdoc.status(vault, project(vault))["comments"] == shown["comments"]
    assert len(fake.requests) == asked

    # A pull reads them again, and they never reach the step it makes.
    fake.docs[doc] = fake.docs[doc].replace("Methods follow.", "Methods follow (2019).")
    fake.notes[doc].append(
        {
            "id": "c4",
            "author": {"displayName": "Ana Lee"},
            "content": "Better.",
            "createdTime": "2026-03-11T09:00:00.000Z",
        }
    )
    answer = paperdoc.pull(vault, project(vault), LATEST, fake)
    assert [c["id"] for c in answer["comments"]] == ["c1", "c2", "c4"]
    saved = json.dumps(steps.load(vault, answer["step"]))
    assert "Cite the 2019 study" not in saved and "Better." not in saved


def test_without_a_sign_in_it_says_how_and_never_holds_the_token(setup, monkeypatch):
    vault, _ = setup
    monkeypatch.delenv("GDOCS_PERSONAL")
    shown = paperdoc.status(vault, project(vault))
    assert shown["accounts"] == [] and shown["doc"] is None and shown["comments"] == []
    with pytest.raises(SystemExit, match="`proxenos auth gdocs NAME ADDRESS`"):
        paperdoc.open_doc(vault, project(vault), now=NOW, fetch=FakeDrive())
    with pytest.raises(SystemExit, match="no Google Doc of it yet"):
        paperdoc.pull(vault, project(vault), NOW, FakeDrive())

    monkeypatch.setenv("GDOCS_PERSONAL", f"joe@home.example:oauth:{REFRESH}")
    refused = FakeDrive()
    refused.failures[gdocs.GOOGLE_TOKEN] = [http_error(400)]
    with pytest.raises(SystemExit) as stopped:
        paperdoc.open_doc(vault, project(vault), now=NOW, fetch=refused)
    assert "`proxenos auth gdocs personal joe@home.example`" in str(stopped.value)
    assert REFRESH not in str(stopped.value)

    off = FakeDrive()
    off.failures[gdocs.UPLOAD] = [http_error(403)]
    with pytest.raises(SystemExit, match="Turn on the Google Drive API"):
        paperdoc.open_doc(vault, project(vault), now=NOW, fetch=off)
    assert paperdoc.record(vault, "calls") is None

    # A doc deleted from the Drive says to make a fresh one.
    fake = FakeDrive()
    paperdoc.open_doc(vault, project(vault), now=NOW, fetch=fake)
    fake.docs.clear()
    with pytest.raises(SystemExit, match="Make a fresh one"):
        paperdoc.pull(vault, project(vault), LATER, fake)
    # A doc made with a sign-in that's gone says which to sign in with again.
    monkeypatch.delenv("GDOCS_PERSONAL")
    monkeypatch.setenv("GDOCS_WORK", f"joe@work.example:oauth:{REFRESH}")
    with pytest.raises(SystemExit, match="joe@home.example's Drive"):
        paperdoc.pull(vault, project(vault), LATER, fake)


def test_the_command_prints_json_for_the_page(setup, monkeypatch, capsys):
    vault, _ = setup
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    fake = FakeDrive()
    monkeypatch.setattr(gdocs, "_fetch", fake)

    cli.main(["project", "gdocs", "calls"])
    assert json.loads(capsys.readouterr().out)["doc"] is None and not fake.requests

    cli.main(["project", "gdocs", "calls", "open"])
    made = json.loads(capsys.readouterr().out)
    assert made["doc"]["link"].startswith("https://docs.google.com/document/d/")

    doc = "doc-01-made-by-proxenos"
    fake.docs[doc] = fake.docs[doc] + "\nAnd the owls.\n"
    cli.main(["project", "gdocs", "calls", "pull"])
    pulled = json.loads(capsys.readouterr().out)
    assert pulled["changed"] and pulled["step"].startswith("calls/")

    cli.main(["project", "gdocs", "calls", "comments"])
    assert json.loads(capsys.readouterr().out)["comments_read"]
    with pytest.raises(SystemExit, match="no project"):
        cli.main(["project", "gdocs", "nope"])
