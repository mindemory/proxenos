"""Google Calendar, live, through the Calendar API with a read-only Google sign-in.

`proxenos auth gcalendar NAME ADDRESS` signs in once with the same Google client as Gmail's
(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, with the Google Calendar API turned on in its
project), asks only for calendar.readonly, and saves GCALENDAR_<NAME>=address:oauth:<refresh
token>. It's a sign-in of its own rather than a wider Gmail one: a calendar can be connected
without granting mail access, and Gmail's restricted scope never rides along. Each run swaps the
refresh token for an access token; Google's refresh tokens don't rotate, so nothing is saved back.

Events go to vault/raw/calendar/<name>/ (NAME lowercased) in the calendar reader's shape
(calendar.py), from the account's primary calendar, PAST_DAYS back to FUTURE_DAYS ahead, read
whole every run and merged by id, so re-running changes nothing that didn't change. As with
Microsoft's, repeating events come expanded into their occurrences in that window (singleEvents),
each a record of its own with rrule None, so a moved or cancelled occurrence is right. The id is
the event's iCalUID, plus its original start for an occurrence of a series, the way an export
names a changed instance. Times are UTC and an all-day event keeps its dates; the time zone is
the event's, else the calendar's. Rooms and resources aren't guests. A description written as
HTML is kept as its text. It only reads.
"""

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from proxenos.ingest import calendar, email
from proxenos.store import merge_monthly

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
OAUTH = "oauth:"
PAST_DAYS, FUTURE_DAYS = 365, 60
PAGE = 250

_ENV = re.compile(r"GCALENDAR_([A-Z0-9_]+)")
_HTML = re.compile(r"<(br|p|div|a|b|i|ul|ol|li|span)\b[^>]*>", re.IGNORECASE)
_STATUS = {
    "accepted": "accepted",
    "declined": "declined",
    "tentative": "tentative",
    "needsAction": "needs-action",
}

# Takes a request and returns the decoded JSON body, raising HTTPError the way urlopen does.
Fetch = Callable[[urllib.request.Request], Any]


def accounts() -> dict[str, tuple[str, str]]:
    """name → (address, refresh token) for every GCALENDAR_<NAME> sign-in in the environment."""
    found = {}
    for key, value in os.environ.items():
        match = _ENV.fullmatch(key)
        if match and f":{OAUTH}" in value:
            address, token = value.split(f":{OAUTH}", 1)
            found[match.group(1).lower()] = (address.strip(), token.strip())
    return found


def ingest(
    vault: Path,
    name: str,
    address: str,
    refresh_token: str,
    fetch: Fetch | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    fetch = fetch or _fetch_json
    now = now or datetime.now(UTC)
    token = _access_token(name, address, refresh_token, fetch)
    params = {
        "singleEvents": "true",
        "timeMin": calendar._stamp(now - timedelta(days=PAST_DAYS)),
        "timeMax": calendar._stamp(now + timedelta(days=FUTURE_DAYS)),
        "maxResults": PAGE,
    }
    records: dict[str, dict] = {}
    skipped = 0
    page_token = None
    while True:
        query = params | ({"pageToken": page_token} if page_token else {})
        body = _get(f"{EVENTS}?{urllib.parse.urlencode(query)}", token, fetch, name, address)
        zone = body.get("timeZone") if isinstance(body.get("timeZone"), str) else None
        for item in body.get("items") or []:
            record = _event(item, zone) if isinstance(item, dict) else None
            if record is None:
                skipped += 1
            else:
                records[record["id"]] = record
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    stats = Counter(read=0, added=0, updated=0, months_written=0)
    if records:
        stats.update(merge_monthly(records.values(), vault / "raw" / "calendar" / name))
    stats["skipped"] = skipped
    return dict(stats)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="only this GCALENDAR_<NAME> account (default: all)")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    found = accounts()
    if args.account:
        found = {k: v for k, v in found.items() if k == args.account.lower()}
    if not found:
        raise SystemExit("gcalendar: no accounts. Run `proxenos auth gcalendar NAME ADDRESS`.")
    total = Counter()
    for name, (address, token) in found.items():
        total.update(ingest(vault, name, address, token))
    return dict(total)


def _fetch_json(request: urllib.request.Request) -> Any:
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _again(name: str, address: str) -> str:
    return f"Sign in again with `proxenos auth gcalendar {name} {address}`."


def _access_token(name: str, address: str, refresh_token: str, fetch: Fetch) -> str:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise SystemExit(
            "gcalendar: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, the Google client you "
            "signed in with (see docs/data_sources.md)."
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
        token = fetch(request)
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"gcalendar: Google refused {name}'s sign-in ({e.code}). {_again(name, address)}"
        ) from None
    if not isinstance(token, dict) or not token.get("access_token"):
        raise SystemExit(
            f"gcalendar: Google gave no access token for {name}. {_again(name, address)}"
        )
    return token["access_token"]


def _get(url: str, token: str, fetch: Fetch, name: str, address: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        body = fetch(request)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(
                f"gcalendar: Google refused {name}'s sign-in. {_again(name, address)}"
            ) from None
        if e.code == 403:
            raise SystemExit(
                "gcalendar: Google won't let Proxenos read the calendar (403). Turn on the Google "
                "Calendar API in the Google Cloud project that holds GOOGLE_CLIENT_ID."
            ) from None
        raise SystemExit(
            f"gcalendar: Google answered {e.code}; the next sync tries again."
        ) from None
    return body if isinstance(body, dict) else {}


def _event(e: dict, zone: str | None) -> dict | None:
    start, all_day = _time(e.get("start"))
    end, _ = _time(e.get("end"))
    uid = e.get("iCalUID") or e.get("id")
    if start is None or not uid:
        return None
    if e.get("recurringEventId"):
        original, _ = _time(e.get("originalStartTime"))
        uid = f"{uid}/{calendar._stamp(original or start)}"
    attendees = [a for a in e.get("attendees") or [] if isinstance(a, dict)]
    guests: dict[str, dict] = {}
    for attendee in attendees:
        address = (email._text(attendee.get("email")) or "").lower()
        if attendee.get("resource") or "@" not in address:
            continue  # a room or equipment, not a person
        name = email._text(attendee.get("displayName"))
        guests.setdefault(
            address,
            {
                "name": name if name and "@" not in name else None,
                "email": address,
                "status": _STATUS.get(str(attendee.get("responseStatus"))),
            },
        )
    organizer = e.get("organizer") if isinstance(e.get("organizer"), dict) else {}
    description = email._text(e.get("description"))
    if description and _HTML.search(description):
        description = email._text(email._html_text(description))
    status = str(e.get("status") or "").upper()
    timezone = (e.get("start") or {}).get("timeZone") or zone
    return {
        "id": uid,
        "ts": calendar._stamp(start),
        "start": calendar._day(start) if all_day else calendar._stamp(start),
        "end": None if end is None else calendar._day(end) if all_day else calendar._stamp(end),
        "all_day": all_day,
        "timezone": None if all_day else timezone,
        "summary": email._text(e.get("summary")),
        "location": email._text(e.get("location")),
        "description": description[: calendar.DESCRIPTION_CHARS] if description else None,
        "rrule": None,
        "status": status or None,
        "organizer": (email._text(organizer.get("email")) or "").lower() or None,
        "attendees": len(attendees),
        "guests": list(guests.values()),
    }


def _time(value: object) -> tuple[datetime | None, bool]:
    """The API's {"dateTime": RFC 3339} in UTC, or {"date": "2026-10-29"} as UTC midnight, the
    way an export's all-day date is; and whether it was a date."""
    if not isinstance(value, dict):
        return None, False
    try:
        if isinstance(value.get("date"), str):
            return datetime.fromisoformat(value["date"][:10]).replace(tzinfo=UTC), True
        if isinstance(value.get("dateTime"), str):
            when = datetime.fromisoformat(value["dateTime"])
            return (
                when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
            ), False
    except ValueError:
        pass
    return None, False
