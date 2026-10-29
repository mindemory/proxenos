"""Microsoft 365 and Outlook.com mail and calendar, read through Microsoft Graph with a sign-in.

`proxenos auth microsoft NAME ADDRESS` signs in once in the browser against the person's own app
registration (MICROSOFT_CLIENT_ID, a public client with no secret) and saves
MICROSOFT_<NAME>=address:oauth:<refresh token>. NAME (lowercased) names the streams. Each run
swaps the refresh token for an access token. Microsoft hands back a new refresh token every time
and keeps the old one working until it expires, 90 days after it was issued, so the newest is
saved again (through config.save_secret) at most once every ROTATE_DAYS: often enough that a
sign-in that keeps syncing never lapses, rarely enough that the Keychain isn't rewritten every 15
minutes. Only the date it was saved goes in vault/state/microsoft_<name>.json, never the token.

Mail goes to vault/raw/email/<name>/ in the mbox ingester's record shape, field for field, so a
message that is also in an export merges with it by Message-ID. Every folder is read except Junk
Email, Deleted Items and the folders inside them, and drafts are left out. The folder's path
("Inbox", "Inbox/Projects") goes in gmail_labels and Outlook's conversation id in gmail_thread,
as Apple Mail's mailboxes do. In-Reply-To and the list headers come from the message's internet
headers, which mail sent from Outlook itself may not carry. Attachments are kept by name only.
The body is Graph's plain-text rendering, cut to BODY_CHARS. The first run reads everything;
later runs read mail received since the newest one seen, oldest first, and that point is saved
after every batch, so an interrupted backfill picks up where it stopped. --full reads it all.

The calendar goes to vault/raw/calendar/<name>/ in the calendar reader's shape (calendar.py),
from the account's main calendar, PAST_DAYS back to FUTURE_DAYS ahead, read whole every run.
Graph expands repeating events into their occurrences in that window, so each occurrence is a
record of its own (rrule stays None) and a moved or cancelled one is right. The id is the
event's iCalUId, plus its original start for an occurrence of a series, the way an export names
a changed instance, so an occurrence that is edited later keeps its record. Times are UTC and an
all-day event keeps its dates; the time zone is kept when it's an IANA name (Outlook mostly
writes Windows names, which aren't). Rooms and resources aren't guests. A cancelled meeting still
on the calendar is kept, with status CANCELLED, so it replaces the copy read before.

It only reads: nothing is sent, moved or marked read. A refused request names what to do next
and never holds the token.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from proxenos.config import env, save_secret
from proxenos.ingest import calendar, email
from proxenos.store import merge_monthly

AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0/"
SCOPES = "offline_access User.Read Mail.Read Calendars.Read"
GRAPH = "https://graph.microsoft.com/v1.0"
CLIENT = "MICROSOFT_CLIENT_ID"
OAUTH = "oauth:"  # what the secret holds after the address, as a Google sign-in's does
PAST_DAYS, FUTURE_DAYS = 365, 60
ROTATE_DAYS = 7
BODY_CHARS = 256 * 1024
MAIL_PAGE = 50  # messages per request; each carries its attachments' names
EVENT_PAGE = 100
BATCH = 2000  # records per merge
RETRIES = 3  # for a request Graph asks to slow down (429) or can't answer yet (503, 504)
MAX_WAIT = 60  # seconds, whatever Retry-After says

_ENV = re.compile(r"MICROSOFT_([A-Z0-9_]+)")
_MAIL_FIELDS = (
    "internetMessageId,subject,from,toRecipients,ccRecipients,sentDateTime,receivedDateTime,"
    "isDraft,parentFolderId,conversationId,body,internetMessageHeaders"
)
_EVENT_FIELDS = (
    "iCalUId,type,subject,start,end,isAllDay,originalStart,originalStartTimeZone,location,"
    "bodyPreview,organizer,attendees,isCancelled"
)
_LEFT_OUT = ("junkemail", "deleteditems")  # Graph's names for the folders not read
_STATUS = {
    "accepted": "accepted",
    "declined": "declined",
    "tentativelyAccepted": "tentative",
    "notResponded": "needs-action",
    "organizer": "accepted",
}

# Takes a request and returns the decoded JSON body, raising HTTPError the way urlopen does.
Fetch = Callable[[urllib.request.Request], Any]


class Refused(Exception):
    """Microsoft said no: the HTTP status and its short reason, never the request. sign_in says
    it was the sign-in that was refused, as opposed to a read."""

    def __init__(self, code: int, why: str = "", sign_in: bool = False) -> None:
        super().__init__(f"{code} {why}".strip())
        self.code = code
        self.why = why
        self.sign_in = sign_in


def accounts() -> dict[str, tuple[str, str]]:
    """name → (address, refresh token) for every MICROSOFT_<NAME> sign-in in the environment."""
    found = {}
    for key, value in os.environ.items():
        match = _ENV.fullmatch(key)
        if match and key != CLIENT and f":{OAUTH}" in value:
            address, token = value.split(f":{OAUTH}", 1)
            found[match.group(1).lower()] = (address.strip(), token.strip())
    return found


def profile(access_token: str, fetch: Fetch | None = None) -> dict:
    """Who signed in: Graph's /me, with the account's mail address and sign-in name."""
    url = _query("/me", {"$select": "mail,userPrincipalName"})
    return _get(url, access_token, fetch or _fetch_json)


def refused(e: urllib.error.HTTPError) -> Refused:
    """What an error answer says, shortly: Graph's error code, or the sign-in's AADSTS line."""
    try:
        body = json.loads(e.read() or b"{}")
    except (OSError, ValueError):
        body = {}
    body = body if isinstance(body, dict) else {}
    error = body.get("error")
    if isinstance(error, dict):  # Graph: {"error": {"code": ..., "message": ...}}
        why = str(error.get("code") or "")
    else:  # the sign-in: {"error": ..., "error_description": "AADSTS...: ... Trace ID: ..."}
        why = str(body.get("error_description") or error or "")
        why = why.splitlines()[0].split(" Trace ID")[0] if why else ""
    return Refused(e.code, " ".join(why.split())[:200])


def ingest(
    vault: Path,
    name: str,
    address: str,
    refresh_token: str,
    me=(),
    full: bool = False,
    fetch: Fetch | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    fetch = fetch or _fetch_json
    now = now or datetime.now(UTC)
    state_path = vault / "state" / f"microsoft_{name}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    mine = {a.strip().lower() for a in [address, *me] if a.strip()}
    try:
        token = _access_token(name, address, refresh_token, state, fetch, now)
        _save(state_path, state)
        stats = {
            f"mail_{k}": v
            for k, v in _mail(vault, name, mine, token, fetch, state_path, state, full).items()
        }
        stats |= {f"events_{k}": v for k, v in _calendar(vault, name, token, fetch, now).items()}
    except Refused as e:
        raise SystemExit(_explain(e, name, address)) from None
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="only this MICROSOFT_<NAME> account (default: all)")
    parser.add_argument("--full", action="store_true", help="read all the mail again")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    found = accounts()
    if args.account:
        found = {k: v for k, v in found.items() if k == args.account.lower()}
    if not found:
        raise SystemExit("microsoft: no accounts. Run `proxenos auth microsoft NAME ADDRESS`.")
    me = env("EMAILS").split(",")
    total = Counter()
    for name, (address, token) in found.items():
        total.update(ingest(vault, name, address, token, me, args.full))
    return dict(total)


# Signing in


def _access_token(
    name: str, address: str, refresh_token: str, state: dict, fetch: Fetch, now: datetime
) -> str:
    client_id = os.environ.get(CLIENT)
    if not client_id:
        raise SystemExit(
            "microsoft: set MICROSOFT_CLIENT_ID to the app registration you signed in with "
            "(see docs/data_sources.md)."
        )
    form = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPES,
    }
    data = urllib.parse.urlencode(form).encode()
    try:
        token = _call(fetch, urllib.request.Request(AUTHORITY + "token", data=data, method="POST"))
    except Refused as e:
        e.sign_in = True
        raise
    if not isinstance(token, dict) or not token.get("access_token"):
        raise Refused(400, "no access token", sign_in=True)
    fresh = token.get("refresh_token")
    saved = _parse(state.get("token_saved"))
    if (
        fresh
        and fresh != refresh_token
        and (saved is None or now - saved >= timedelta(days=ROTATE_DAYS))
    ):
        try:
            save_secret(f"MICROSOFT_{name.upper()}", f"{address}:{OAUTH}{fresh}")
            state["token_saved"] = calendar._stamp(now)
        except Exception:  # noqa: BLE001  the token saved before still works; say nothing of it
            print(
                f"microsoft: couldn't save {name}'s newer sign-in; the saved one works for now",
                file=sys.stderr,
            )
    return token["access_token"]


def _explain(e: Refused, name: str, address: str) -> str:
    why = f" ({e.why})" if e.why else ""
    if e.sign_in or e.code == 401:
        return (
            f"microsoft: {name}'s sign-in no longer works{why}. Sign in again with "
            f"`proxenos auth microsoft {name} {address}`."
        )
    if e.code == 403:
        return (
            f"microsoft: Microsoft won't let Proxenos read {address}{why}. A work or school "
            "account may need an admin to approve the app."
        )
    return f"microsoft: Microsoft answered {e.code}{why}; the next sync tries again."


# Graph


def _fetch_json(request: urllib.request.Request) -> Any:
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _wait(seconds: float) -> None:
    time.sleep(seconds)


def _call(fetch: Fetch, request: urllib.request.Request) -> Any:
    for attempt in range(RETRIES + 1):
        try:
            return fetch(request)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503, 504) and attempt < RETRIES:
                _wait(_retry_after(e))
                continue
            raise refused(e) from None
    raise AssertionError("unreachable")


def _retry_after(e: urllib.error.HTTPError) -> float:
    try:
        return max(0.0, min(float(e.headers.get("Retry-After", 5)), MAX_WAIT))
    except (AttributeError, TypeError, ValueError):
        return 5.0


def _query(path: str, params: dict) -> str:
    return f"{GRAPH}{path}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe='$')}"


def _get(url: str, token: str, fetch: Fetch, prefer: str | None = None) -> Any:
    # A next page comes back as a full address: the token only ever goes to Graph itself.
    if not url.startswith(GRAPH + "/"):
        raise Refused(0, "Graph pointed somewhere else")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    return _call(fetch, urllib.request.Request(url, headers=headers))


def _pages(url: str, token: str, fetch: Fetch, prefer: str | None = None) -> Iterator[list[dict]]:
    """Each page of a listing, following @odata.nextLink to the end."""
    following: str | None = url
    while following:
        body = _get(following, token, fetch, prefer)
        body = body if isinstance(body, dict) else {}
        yield [item for item in body.get("value") or [] if isinstance(item, dict)]
        following = body.get("@odata.nextLink")


# Mail


def _mail(
    vault: Path,
    name: str,
    mine: set[str],
    token: str,
    fetch: Fetch,
    state_path: Path,
    state: dict,
    full: bool,
) -> dict[str, int]:
    paths, left_out = _folders(token, fetch)
    newest = None if full else state.get("mail_since")
    url = _query(
        "/me/messages",
        {
            "$select": _MAIL_FIELDS,
            "$expand": "attachments($select=name)",
            "$filter": f"receivedDateTime ge {newest or '1900-01-01T00:00:00Z'}",
            "$orderby": "receivedDateTime asc",
            "$top": MAIL_PAGE,
        },
    )
    out = vault / "raw" / "email" / name
    stats = Counter(read=0, added=0, updated=0, months_written=0, skipped=0)
    batch: dict[str, dict] = {}
    for page in _pages(url, token, fetch, prefer='outlook.body-content-type="text"'):
        for message in page:
            received = _instant(message.get("receivedDateTime"))
            if received and (newest is None or received > newest):
                newest = received
            if message.get("isDraft") or message.get("parentFolderId") in left_out:
                continue
            record = _message(message, name, mine, paths)
            if record is None:
                stats["skipped"] += 1
                continue
            batch[record["id"]] = record
        if len(batch) >= BATCH:
            stats.update(merge_monthly(batch.values(), out))
            batch = {}
            state["mail_since"] = newest
            _save(state_path, state)
    if batch:
        stats.update(merge_monthly(batch.values(), out))
    if newest:
        state["mail_since"] = newest
        _save(state_path, state)
    return dict(stats)


def _folders(token: str, fetch: Fetch) -> tuple[dict[str, str], set[str]]:
    """Each mail folder's path ("Inbox/Projects") by id, and the ids of the folders left out:
    Junk Email, Deleted Items and every folder inside them. The delta listing is the one that
    holds every folder at once, nested ones included."""
    folders: dict[str, tuple[str, str | None]] = {}
    for page in _pages(
        _query("/me/mailFolders/delta", {"$select": "displayName,parentFolderId"}), token, fetch
    ):
        for folder in page:
            if folder.get("id") and "@removed" not in folder:
                folders[folder["id"]] = (
                    str(folder.get("displayName") or ""),
                    folder.get("parentFolderId"),
                )
    unwanted = {
        str(_get(_query(f"/me/mailFolders/{w}", {"$select": "id"}), token, fetch).get("id"))
        for w in _LEFT_OUT
    }
    paths, left_out = {}, set(unwanted)
    for folder in folders:
        names, at, seen = [], folder, set()
        while at in folders and at not in seen:
            seen.add(at)
            if at in unwanted:
                left_out.add(folder)
            names.append(folders[at][0])
            at = folders[at][1]
        paths[folder] = "/".join(reversed(names))
    return paths, left_out


def _message(m: dict, account: str, mine: set[str], paths: dict[str, str]) -> dict | None:
    ts = _instant(m.get("sentDateTime")) or _instant(m.get("receivedDateTime"))
    if ts is None:
        return None
    from_name, from_address = next(iter(_people([m.get("from")])), (None, None))
    headers: dict[str, str] = {}
    for header in m.get("internetMessageHeaders") or []:
        if isinstance(header, dict) and header.get("name"):
            headers.setdefault(str(header["name"]).lower(), str(header.get("value") or ""))
    part = m.get("body") if isinstance(m.get("body"), dict) else {}
    text = str(part.get("content") or "")
    if str(part.get("contentType") or "").lower() == "html":  # the Prefer header wasn't heard
        text = email._html_text(text)
    body = email._text(text.replace("\r\n", "\n").replace("\r", "\n")[:BODY_CHARS])
    subject = email._text(m.get("subject"))
    message_id = email._message_id(m.get("internetMessageId"))
    if message_id is None:
        key = "\n".join([ts, from_address or "", subject or "", (body or "")[:200]])
        message_id = hashlib.sha256(key.encode()).hexdigest()
    folder = paths.get(str(m.get("parentFolderId") or ""))
    return {
        "id": message_id,
        "ts": ts,
        "account": account,
        "from_address": from_address,
        "from_name": from_name,
        "from_me": from_address in mine,
        "to": [a for _, a in _people(m.get("toRecipients"))] or None,
        "cc": [a for _, a in _people(m.get("ccRecipients"))] or None,
        "subject": subject,
        "in_reply_to": email._message_id(headers.get("in-reply-to")),
        "gmail_labels": [folder] if folder else None,
        "gmail_thread": m.get("conversationId") or None,
        # Sent to a list or in bulk, as the mbox reader tells from the same headers.
        "bulk": bool(
            headers.get("list-id")
            or headers.get("list-unsubscribe")
            or headers.get("precedence", "").strip().lower() in ("bulk", "list", "junk")
        ),
        "attachments": [
            n
            for a in m.get("attachments") or []
            if isinstance(a, dict) and (n := email._text(a.get("name")))
        ]
        or None,
        "body": body,
        "body_new": email._new_text(body) if body else None,
    }


def _people(recipients: object) -> list[tuple[str | None, str]]:
    """(display name, lowercased address) for each of Graph's {"emailAddress": {name, address}}
    with an address. A name that is just the address is no name, as in a bare header."""
    found = []
    for recipient in recipients if isinstance(recipients, list) else []:
        mailbox = recipient.get("emailAddress") if isinstance(recipient, dict) else None
        if not isinstance(mailbox, dict):
            continue
        address = (email._text(mailbox.get("address")) or "").lower()
        if "@" not in address:
            continue
        name = email._text(mailbox.get("name"))
        found.append((None if name and name.lower() == address else name, address))
    return found


# Calendar


def _calendar(vault: Path, name: str, token: str, fetch: Fetch, now: datetime) -> dict[str, int]:
    url = _query(
        "/me/calendarView",
        {
            "startDateTime": calendar._stamp(now - timedelta(days=PAST_DAYS)),
            "endDateTime": calendar._stamp(now + timedelta(days=FUTURE_DAYS)),
            "$select": _EVENT_FIELDS,
            "$top": EVENT_PAGE,
        },
    )
    records: dict[str, dict] = {}
    skipped = 0
    for page in _pages(url, token, fetch, prefer='outlook.timezone="UTC"'):
        for item in page:
            record = _event(item)
            if record is None:
                skipped += 1
            else:
                records[record["id"]] = record
    stats = Counter(read=0, added=0, updated=0, months_written=0)
    if records:
        stats.update(merge_monthly(records.values(), vault / "raw" / "calendar" / name))
    stats["skipped"] = skipped
    return dict(stats)


def _event(e: dict) -> dict | None:
    all_day = bool(e.get("isAllDay"))
    start, end = _time(e.get("start"), all_day), _time(e.get("end"), all_day)
    uid = e.get("iCalUId")
    if start is None or not uid:
        return None
    if e.get("type") in ("occurrence", "exception"):
        original = _parse(_instant(e.get("originalStart"))) or start
        uid = f"{uid}/{calendar._stamp(original)}"
    attendees = [a for a in e.get("attendees") or [] if isinstance(a, dict)]
    guests: dict[str, dict] = {}
    for attendee in attendees:
        if str(attendee.get("type") or "").lower() == "resource":
            continue  # a room or equipment, not a person
        for guest_name, guest_address in _people([attendee]):
            response = attendee.get("status") if isinstance(attendee.get("status"), dict) else {}
            guests.setdefault(
                guest_address,
                {
                    "name": guest_name,
                    "email": guest_address,
                    "status": _STATUS.get(str(response.get("response"))),
                },
            )
    organizer = next(iter(_people([e.get("organizer")])), (None, None))[1]
    location = e.get("location") if isinstance(e.get("location"), dict) else {}
    description = email._text(e.get("bodyPreview"))
    return {
        "id": uid,
        "ts": calendar._stamp(start),
        "start": calendar._day(start) if all_day else calendar._stamp(start),
        "end": None if end is None else calendar._day(end) if all_day else calendar._stamp(end),
        "all_day": all_day,
        "timezone": None if all_day else _iana(e.get("originalStartTimeZone")),
        "summary": email._text(e.get("subject")),
        "location": email._text(location.get("displayName")),
        "description": description[: calendar.DESCRIPTION_CHARS] if description else None,
        "rrule": None,
        "status": "CANCELLED" if e.get("isCancelled") else None,
        "organizer": organizer,
        "attendees": len(attendees),
        "guests": list(guests.values()),
    }


def _time(value: object, all_day: bool = False) -> datetime | None:
    """Graph's {"dateTime": "2026-10-29T18:00:00.0000000", "timeZone": "UTC"} in UTC. An all-day
    event's is midnight on its date, whatever the zone, kept as UTC midnight as an export's is."""
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        return None
    try:
        local = datetime.fromisoformat(value["dateTime"][:19])
    except ValueError:
        return None
    if all_day:
        return datetime(local.year, local.month, local.day, tzinfo=UTC)
    zone = calendar._zone(str(value.get("timeZone") or "UTC"))
    return local.replace(tzinfo=zone).astimezone(UTC)


def _iana(name: object) -> str | None:
    """A time zone's name when it's one zoneinfo knows, as an export's TZID is; else None."""
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name.strip()


# Times and state


def _instant(value: object) -> str | None:
    """An ISO time ("2026-10-29T18:00:00Z", with or without fractions) as UTC ISO, or None."""
    when = _parse(value)
    return calendar._stamp(when) if when else None


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _save(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")
