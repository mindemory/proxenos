"""Google Docs, through the Drive API, with a sign-in that sees only the files Proxenos made.

`proxenos auth gdocs NAME ADDRESS` signs in once with the same Google client as Gmail's and
Google Calendar's (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, with the Google Drive API turned on
in its project), asks only for drive.file, and saves GDOCS_<NAME>=address:oauth:<refresh token>.
drive.file lets Proxenos see and change only the files it made itself: never the rest of the
Drive, nor a doc someone else shares. Each use swaps the refresh token for an access token;
Google's refresh tokens don't rotate, so nothing is saved back.

It's used for one thing, a project's manuscript as a Google Doc (proxenos.paperdoc): the text is
uploaded and converted to a Doc, the Doc's text is exported back, and its comments are read. No
sharing is set, so a doc is the user's alone until they share it from Docs, and nothing is ever
deleted.
"""

import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import PurePosixPath

SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FILES = "https://www.googleapis.com/drive/v3/files"
DOC = "application/vnd.google-apps.document"
OAUTH = "oauth:"
PAGE = 100  # comments a request
MAX_COMMENTS = 1000
MAX_CHARS = 20_000  # of one comment or reply kept
_COMMENT_FIELDS = (
    "nextPageToken,comments(id,author(displayName),content,quotedFileContent(value),resolved,"
    "createdTime,deleted,replies(author(displayName),content,createdTime,deleted))"
)
_ENV = re.compile(r"GDOCS_([A-Z0-9_]+)")
_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")  # a Drive file's id, safe in a URL's path

# Takes a request and returns the response's body, raising HTTPError the way urlopen does.
Fetch = Callable[[urllib.request.Request], bytes]


def accounts() -> dict[str, tuple[str, str]]:
    """name → (address, refresh token) for every GDOCS_<NAME> sign-in in the environment."""
    found = {}
    for key, value in os.environ.items():
        match = _ENV.fullmatch(key)
        if match and f":{OAUTH}" in value:
            address, token = value.split(f":{OAUTH}", 1)
            found[match.group(1).lower()] = (address.strip(), token.strip())
    return found


def mime_for(path: str) -> str:
    """What the manuscript goes up and comes back as: Markdown as Markdown, which Docs turns into
    headings, lists and emphasis; LaTeX and the rest as plain text, a line to a paragraph."""
    suffix = PurePosixPath(path).suffix.lower()
    return "text/markdown" if suffix in (".md", ".markdown") else "text/plain"


def is_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def again(name: str, address: str) -> str:
    return f"Sign in again with `proxenos auth gdocs {name} {address}`."


def access_token(name: str, address: str, refresh_token: str, fetch: Fetch | None = None) -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit(
            "gdocs: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, the Google client you signed "
            "in with (see docs/data_sources.md)."
        )
    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    request = urllib.request.Request(
        GOOGLE_TOKEN, data=urllib.parse.urlencode(form).encode(), method="POST"
    )
    try:
        token = _json((fetch or _fetch)(request))
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"gdocs: Google refused {name}'s sign-in ({e.code}). {again(name, address)}"
        ) from None
    except urllib.error.URLError:
        raise SystemExit("gdocs: couldn't reach Google. Is this computer online?") from None
    if not token.get("access_token"):
        raise SystemExit(f"gdocs: Google gave no access token for {name}. {again(name, address)}")
    return token["access_token"]


def create(token: str, title: str, text: str, mime: str, fetch: Fetch | None = None) -> dict:
    """A new Google Doc in the user's own Drive, made from the text: {id, link}. One multipart
    upload, the Doc's name and type, then the text as `mime`, which Drive converts."""
    boundary = f"proxenos-{secrets.token_hex(16)}"
    while boundary in text:  # never, but a boundary must not appear in what it bounds
        boundary = f"proxenos-{secrets.token_hex(16)}"
    meta = json.dumps({"name": title, "mimeType": DOC}, ensure_ascii=False)
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
        f"--{boundary}\r\nContent-Type: {mime}; charset=UTF-8\r\n\r\n{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    query = urllib.parse.urlencode({"uploadType": "multipart", "fields": "id,webViewLink"})
    request = urllib.request.Request(
        f"{UPLOAD}?{query}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method="POST",
    )
    made = _json(_call(request, fetch))
    if not is_id(made.get("id")):
        raise SystemExit("gdocs: Google made no doc; try again.")
    link = made.get("webViewLink")
    if not (isinstance(link, str) and link.startswith("https://docs.google.com/")):
        link = f"https://docs.google.com/document/d/{made['id']}/edit"
    return {"id": made["id"], "link": link}


def export(token: str, doc_id: str, mime: str, fetch: Fetch | None = None) -> str:
    """The Doc's text as `mime`, with Windows line ends and a byte-order mark taken out, so two
    exports compare by what's written."""
    query = urllib.parse.urlencode({"mimeType": mime})
    request = urllib.request.Request(
        f"{FILES}/{_checked(doc_id)}/export?{query}", headers={"Authorization": f"Bearer {token}"}
    )
    text = _call(request, fetch).decode("utf-8", errors="replace")
    return text.removeprefix("﻿").replace("\r\n", "\n")


def comments(token: str, doc_id: str, fetch: Fetch | None = None) -> list[dict]:
    """The Doc's comments, oldest first, each {id, author, content, quoted, resolved, created,
    replies: [{author, content, created}]}; none deleted."""
    found: list[dict] = []
    page = None
    while len(found) < MAX_COMMENTS:
        params = {"fields": _COMMENT_FIELDS, "pageSize": PAGE} | (
            {"pageToken": page} if page else {}
        )
        request = urllib.request.Request(
            f"{FILES}/{_checked(doc_id)}/comments?{urllib.parse.urlencode(params)}",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = _json(_call(request, fetch))
        for raw in body.get("comments") or []:
            if isinstance(raw, dict) and not raw.get("deleted"):
                found.append(_comment(raw))
        page = body.get("nextPageToken")
        if not isinstance(page, str) or not page:
            break
    found.sort(key=lambda c: c["created"])
    return found[:MAX_COMMENTS]


def _comment(raw: dict) -> dict:
    quoted = raw.get("quotedFileContent") if isinstance(raw.get("quotedFileContent"), dict) else {}
    return {
        "id": _text(raw.get("id"))[:200],
        "author": _author(raw),
        "content": _text(raw.get("content")),
        "quoted": _text(quoted.get("value")),
        "resolved": raw.get("resolved") is True,
        "created": _text(raw.get("createdTime"))[:40],
        "replies": [
            {
                "author": _author(r),
                "content": _text(r.get("content")),
                "created": _text(r.get("createdTime"))[:40],
            }
            for r in raw.get("replies") or []
            if isinstance(r, dict) and not r.get("deleted")
        ],
    }


def _author(raw: dict) -> str:
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    return _text(author.get("displayName"))[:200] or "Someone"


def _text(value: object) -> str:
    return value[:MAX_CHARS] if isinstance(value, str) else ""


def _checked(doc_id: str) -> str:
    if not is_id(doc_id):
        raise SystemExit("gdocs: that isn't a Google Doc's id")
    return doc_id


def _call(request: urllib.request.Request, fetch: Fetch | None) -> bytes:
    """The response's body, or why there's none in words that say what to do."""
    try:
        return (fetch or _fetch)(request)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(
                "gdocs: Google refused the sign-in. Sign in again with `proxenos auth gdocs NAME "
                "ADDRESS`."
            ) from None
        if e.code == 403:
            raise SystemExit(
                "gdocs: Google won't let Proxenos at the doc (403). Turn on the Google Drive API "
                "in the Google Cloud project that holds GOOGLE_CLIENT_ID."
            ) from None
        if e.code == 404:
            raise SystemExit(
                "gdocs: the doc isn't in your Drive any more, or this sign-in didn't make it. Make "
                "a fresh one."
            ) from None
        raise SystemExit(f"gdocs: Google answered {e.code}; try again.") from None
    except urllib.error.URLError:
        raise SystemExit("gdocs: couldn't reach Google. Is this computer online?") from None


def _json(data: bytes) -> dict:
    try:
        body = json.loads(data)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()
