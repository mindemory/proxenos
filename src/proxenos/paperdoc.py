"""A project's manuscript as a Google Doc, for the user to edit, comment on and share with
co-authors the way they already work, with git still the source of truth.

Open in Google Docs uploads the manuscript at its branch's tip to the user's own Drive through
their GDOCS_<NAME> sign-in (proxenos.gdocs), converted to a Doc: Markdown as Markdown, LaTeX and
the rest as plain text. No sharing is set; the user shares it from Docs. The new Doc is exported
straight back, and that export is the baseline: the text as Docs writes it, before anyone has
changed it. A project has one doc: opening it again gives its link, unless a fresh copy is asked
for, which leaves the old one in the Drive.

Bring back its changes exports the Doc again. The same as the baseline: nothing changed. Else the
manuscript is rebuilt so that only the paragraphs changed in Docs change in git. The text the
baseline came from, the baseline and the new export are each split into paragraphs, as
manuscript.diff splits them. When the text and the baseline have as many, they pair one to one,
and the baseline's paragraphs are matched against the new export's: those that stayed keep the
manuscript's own Markdown or LaTeX byte for byte, and only those edited, added or deleted in Docs
take the Doc's text. When the counts differ, the conversion changed the text's shape and there's
no pairing to trust, so the new export is taken whole. The result is saved as an edit
(manuscript.edit): a branch from the commit the text came from, waiting on the user as a step,
which Accept merges, along with whatever changed in git meanwhile, and Discard deletes. The new
export becomes the baseline once that step exists. While the step waits, another pull is
refused; once it's accepted, the next pull starts from it, and once it's discarded, from where it
started.

Its comments are read on each pull and when the page asks, and kept beside the doc's record for
the page to show. They're other people's words: shown on the page, never sent to a model.

Kept in clones/projects/<id>/gdocs/, private to the user: doc.json, the record; baseline.txt; and
comments.json.
"""

import argparse
import json
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

from proxenos import gdocs, manuscript
from proxenos.clones import steps, work

ACTIONS = ("show", "open", "fresh", "pull", "comments")
# What the page is shown of the record.
SHOWN = ("link", "title", "account", "address", "path", "branch", "commit", "at", "pulled", "step")
_ENDS_PARAGRAPH = re.compile(r"\n[ \t]*\n\s*\Z")


# Making it.


def open_doc(
    vault: Path,
    project: dict,
    fresh: bool = False,
    account: str | None = None,
    now: datetime | None = None,
    fetch: gdocs.Fetch | None = None,
) -> dict:
    """The project's Google Doc: made from the manuscript at its branch's tip the first time, or
    when `fresh`, else the one there is. What the page shows."""
    now = now or datetime.now(UTC)
    pid = project["id"]
    doc = record(vault, pid)
    if doc and not fresh:
        if _baseline(vault, pid) is None:  # made, but never read back
            token = _token(doc["account"], fetch, doc["address"])
            mime = gdocs.mime_for(doc["path"])
            _save(vault, pid, "baseline.txt", gdocs.export(token, doc["doc_id"], mime, fetch))
        return status(vault, project)

    found = manuscript.find(project)
    if found is None:
        raise SystemExit("gdocs: this project has no manuscript to open in Google Docs")
    repo = steps._repo(project)
    tip = manuscript._tip(repo, found["branch"])
    text = _text_at(repo, tip, found["path"])
    name, address = _account(account or (doc or {}).get("account"))
    token = _token(name, fetch)
    mime = gdocs.mime_for(found["path"])
    title = f"{project.get('name') or pid}: {PurePosixPath(found['path']).name}"
    made = gdocs.create(token, title, text, mime, fetch)
    (folder(vault, pid) / "baseline.txt").unlink(missing_ok=True)
    doc = {
        "doc_id": made["id"],
        "link": made["link"],
        "title": title,
        "account": name,
        "address": address,
        "path": found["path"],
        "branch": found["branch"],
        "commit": tip,  # uploaded from
        "from": tip,  # where the baseline's text is in git, so where the next pull starts
        "at": steps._iso(now),
        "pulled": None,
        "step": None,  # the step the last pull made, and its head
        "head": None,
    }
    _keep(vault, pid, doc)  # first, so a doc that can't be read back isn't made twice
    _save(vault, pid, "comments.json", json.dumps({"read": None, "comments": []}))
    _save(vault, pid, "baseline.txt", gdocs.export(token, made["id"], mime, fetch))
    return status(vault, project)


# Bringing it back.


def pull(
    vault: Path, project: dict, now: datetime | None = None, fetch: gdocs.Fetch | None = None
) -> dict:
    """What changed in the doc, as a step waiting on the user, and its comments read again. What
    the page shows, with {changed, step, said}."""
    now = now or datetime.now(UTC)
    pid = project["id"]
    doc = record(vault, pid)
    if doc is None:
        raise SystemExit("gdocs: there's no Google Doc of it yet: Open in Google Docs makes one")
    baseline = _baseline(vault, pid)
    if baseline is None:
        raise SystemExit("gdocs: the doc was never read back: Open in Google Docs again first")
    repo = steps._repo(project)
    start = _start(vault, repo, doc)
    token = _token(doc["account"], fetch, doc["address"])
    now_text = gdocs.export(token, doc["doc_id"], gdocs.mime_for(doc["path"]), fetch)
    _read_comments(vault, pid, doc, token, now, fetch)
    doc["pulled"] = steps._iso(now)
    answer = {"changed": False, "step": None, "said": "Nothing has changed in the doc."}
    if now_text != baseline:
        original = _text_at(repo, start, doc["path"])
        text = rebuild(original, baseline, now_text)
        if original.endswith("\n") and not text.endswith("\n"):
            text += "\n"  # as an edit would end it
        if text == original:
            answer["said"] = "Only how Docs writes it changed, so there's nothing to bring back."
        else:
            request = {"path": doc["path"], "branch": doc["branch"], "from": start, "text": text}
            step = manuscript.edit(vault, project, request, now, docs=True)
            _save(vault, pid, "baseline.txt", now_text)
            doc |= {"step": step["id"], "head": step["head"]}
            answer = {"changed": True, "step": step["id"], "said": step["summary"]}
    _keep(vault, pid, doc)
    return status(vault, project) | answer


def rebuild(original: str, baseline: str, now: str) -> str:
    """The manuscript with only the paragraphs changed in Docs changed: `original` is its text,
    `baseline` the Doc's export of it, `now` the Doc's export as it is. Paragraphs that stayed
    keep the original's bytes; the rest are the Doc's. When the original and the baseline don't
    split into as many paragraphs, `now` whole."""
    mine = manuscript._paragraphs(original)
    was = manuscript._paragraphs(baseline)
    if len(mine) != len(was):
        return now
    came = manuscript._paragraphs(now)
    pieces: list[str] = []
    keys = [p.strip() for p in was], [p.strip() for p in came]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, *keys, autojunk=False).get_opcodes():
        pieces += mine[i1:i2] if tag == "equal" else came[j1:j2]
    return _join(pieces, original[len(original.rstrip()) :])


def _join(pieces: list[str], ending: str) -> str:
    """Paragraphs as one text: each but the last ending with a blank line, so two never run
    together where one moved, and the last ending as the manuscript did."""
    out = []
    for i, piece in enumerate(pieces):
        if i == len(pieces) - 1:
            piece = piece.rstrip() + ending
        elif not _ENDS_PARAGRAPH.search(piece):
            piece = piece.rstrip("\n") + "\n\n"
        out.append(piece)
    return "".join(out)


def _start(vault: Path, repo: Path, doc: dict) -> str:
    """Where this pull starts in git: the commit the baseline's text was read from. The last
    pull's step, once it's been decided, moves it on when it was accepted."""
    if doc.get("step"):
        try:
            step = steps.load(vault, doc["step"])
        except SystemExit:
            step = {}
        if step.get("status") in ("ready", "working"):
            raise SystemExit(
                f"gdocs: what was brought back last time still waits on you ({doc['step']}): "
                "accept or discard it first"
            )
        head, tip = str(doc.get("head") or ""), manuscript._tip(repo, doc["branch"])
        if step.get("status") == "accepted" and head and tip and _merged(repo, head, tip):
            doc["from"] = head
        doc |= {"step": None, "head": None}
    return doc["from"]


def _merged(repo: Path, commit: str, tip: str) -> bool:
    return steps._git_run(repo, "merge-base", "--is-ancestor", commit, tip).returncode == 0


# Its comments.


def read_comments(
    vault: Path, project: dict, now: datetime | None = None, fetch: gdocs.Fetch | None = None
) -> dict:
    """The doc's comments, read again and kept. What the page shows."""
    doc = record(vault, project["id"])
    if doc is None:
        raise SystemExit("gdocs: there's no Google Doc of it yet: Open in Google Docs makes one")
    token = _token(doc["account"], fetch, doc["address"])
    _read_comments(vault, project["id"], doc, token, now or datetime.now(UTC), fetch)
    return status(vault, project)


def _read_comments(
    vault: Path, pid: str, doc: dict, token: str, now: datetime, fetch: gdocs.Fetch | None
) -> None:
    found = gdocs.comments(token, doc["doc_id"], fetch)
    kept = {"read": steps._iso(now), "comments": found}
    _save(vault, pid, "comments.json", json.dumps(kept, ensure_ascii=False, indent=1))


# What's kept.


def status(vault: Path, project: dict) -> dict:
    """What the page shows: the sign-ins, the doc and its comments as kept. Nothing is fetched."""
    pid = project["id"]
    doc = record(vault, pid)
    kept = _json(folder(vault, pid) / "comments.json")
    comments = kept.get("comments")
    return {
        "project": pid,
        "accounts": [
            {"name": name, "address": address}
            for name, (address, _) in sorted(gdocs.accounts().items())
        ],
        "doc": {key: doc.get(key) for key in SHOWN} if doc else None,
        "comments": [c for c in comments if isinstance(c, dict)]
        if isinstance(comments, list)
        else [],
        "comments_read": kept.get("read") if isinstance(kept.get("read"), str) else None,
    }


def folder(vault: Path, project_id: str) -> Path:
    return vault / "clones" / "projects" / project_id / "gdocs"


def record(vault: Path, project_id: str) -> dict | None:
    doc = _json(folder(vault, project_id) / "doc.json")
    return doc if gdocs.is_id(doc.get("doc_id")) and doc.get("from") else None


def _baseline(vault: Path, project_id: str) -> str | None:
    try:
        return (folder(vault, project_id) / "baseline.txt").read_text(encoding="utf-8")
    except OSError:
        return None


def _keep(vault: Path, project_id: str, doc: dict) -> None:
    _save(vault, project_id, "doc.json", json.dumps(doc, ensure_ascii=False, indent=1))


def _save(vault: Path, project_id: str, name: str, text: str) -> None:
    """Swapped in whole, 0600 in a 0700 folder."""
    where = folder(vault, project_id)
    where.mkdir(mode=0o700, parents=True, exist_ok=True)
    work._write(where / name, text)


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# Helpers.


def _account(name: str | None) -> tuple[str, str]:
    """The sign-in to use, (name, address): the one named, else the first."""
    signed = gdocs.accounts()
    if not signed:
        raise SystemExit(
            "gdocs: not signed in to Google Docs. Run `proxenos auth gdocs NAME ADDRESS`, or sign "
            "in on the Connect page."
        )
    key = (name or min(signed)).lower()
    if key not in signed:
        raise SystemExit(f"gdocs: no Google Docs sign-in named {name}: {', '.join(sorted(signed))}")
    return key, signed[key][0]


def _token(name: str, fetch: gdocs.Fetch | None, address: str = "") -> str:
    """An access token for that sign-in. The doc lives in one account's Drive, and only that
    sign-in can reach it."""
    signed = gdocs.accounts()
    if name not in signed:
        raise SystemExit(
            f"gdocs: the doc is in {address or name}'s Drive; sign in again with `proxenos auth "
            f"gdocs {name} {address or 'ADDRESS'}`"
        )
    address, refresh = signed[name]
    return gdocs.access_token(name, address, refresh, fetch)


def _text_at(repo: Path, commit: str, path: str) -> str:
    """The manuscript's text at that commit, with Windows line ends as \\n."""
    data = manuscript._blob(repo, commit, path) if commit else None
    if data is None or b"\0" in data:
        raise SystemExit(f"gdocs: {path} isn't a text file at {commit[:7] or 'its branch'}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(f"gdocs: {path} isn't UTF-8, so it can't go to Google Docs") from None
    if len(text) > manuscript.MAX_CHARS:
        raise SystemExit(f"gdocs: {path} is too long to bring back from Google Docs here")
    return text.replace("\r\n", "\n")


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", help="the project's id, as in clones/projects/projects.json")
    parser.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=ACTIONS,
        help="show (the default): the doc and its comments as kept, nothing fetched; open: make "
        "the doc the first time, then give its link; fresh: make a new one; pull: bring back its "
        "changes as a step waiting on you, and its comments; comments: read its comments again",
    )
    parser.add_argument(
        "--account",
        metavar="NAME",
        help="the GDOCS_<NAME> sign-in to make it with (default: first)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict:
    """What the page shows of the project's Google Doc, as JSON, after doing what was asked."""
    project = manuscript.listed(vault, args.id)
    if args.action in ("open", "fresh"):
        return open_doc(vault, project, fresh=args.action == "fresh", account=args.account)
    if args.action == "pull":
        return pull(vault, project)
    if args.action == "comments":
        return read_comments(vault, project)
    return status(vault, project)
