"""Google Calendar through the Calendar API, against a fake API. No network, no real calendar."""

import io
import json
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import cli, master
from proxenos.ingest import gcalendar

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
REFRESH = "1//refresh-token-that-must-never-show"
ACCESS = "ya29.access-token-that-must-never-show"


def items():
    return [
        {
            "id": "e1",
            "iCalUID": "uid-visit@calendar.example",
            "status": "confirmed",
            "summary": "Eye test",
            "location": "Optician, High Street",
            "description": "Bring your <b>old glasses</b>.<br>Ten minutes early.",
            "start": {"dateTime": "2026-10-30T09:00:00-04:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-10-30T09:30:00-04:00", "timeZone": "America/New_York"},
            "organizer": {"email": "Joe@Home.example", "self": True},
            "attendees": [
                {"email": "joe@home.example", "self": True, "responseStatus": "accepted"},
                {
                    "email": "desk@optician.example",
                    "displayName": "Front desk",
                    "responseStatus": "needsAction",
                },
                {
                    "email": "room1@rooms.example",
                    "resource": True,
                    "responseStatus": "accepted",
                },
            ],
        },
        {
            "id": "e2_20261103T190000Z",
            "iCalUID": "uid-garden@calendar.example",
            "recurringEventId": "e2",
            "originalStartTime": {"dateTime": "2026-11-03T19:00:00Z"},
            "status": "tentative",
            "summary": "Garden plot",
            "start": {"dateTime": "2026-11-03T20:00:00Z"},
            "end": {"dateTime": "2026-11-03T21:00:00Z"},
        },
        {
            "id": "e3",
            "iCalUID": "uid-holiday@calendar.example",
            "status": "confirmed",
            "summary": "Away",
            "start": {"date": "2026-12-24"},
            "end": {"date": "2026-12-27"},
        },
        {"id": "e4", "status": "confirmed", "summary": "No start"},
    ]


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, io.BytesIO(b"{}"))


class FakeCalendar:
    """Google's token endpoint and the primary calendar's events, two a page."""

    def __init__(self, events=None):
        self.events = items() if events is None else events
        self.requests = []
        self.failures = {}  # url without its query → errors to raise first

    def __call__(self, request):
        self.requests.append(request)
        base, _, query = request.full_url.partition("?")
        if self.failures.get(base):
            raise self.failures[base].pop(0)
        if base == gcalendar.GOOGLE_TOKEN:
            self.form = {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}
            return {"access_token": ACCESS, "expires_in": 3599}
        assert base == gcalendar.EVENTS
        assert request.headers["Authorization"] == f"Bearer {ACCESS}"
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        skip = int(params.get("pageToken", 0))
        page = {"timeZone": "Europe/London", "items": self.events[skip : skip + 2]}
        if skip + 2 < len(self.events):
            page["nextPageToken"] = str(skip + 2)
        return page

    def listings(self):
        found = [r.full_url for r in self.requests if r.full_url.startswith(gcalendar.EVENTS)]
        return [
            {k: v[0] for k, v in urllib.parse.parse_qs(u.partition("?")[2]).items()} for u in found
        ]


@pytest.fixture(autouse=True)
def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")


def stored(vault, name="personal"):
    out = vault / "raw" / "calendar" / name
    return {
        r["id"]: r
        for f in sorted(out.glob("*.jsonl"))
        for r in map(json.loads, f.read_text().splitlines())
    }


def run(vault, fake, now=NOW):
    return gcalendar.ingest(vault, "personal", "joe@home.example", REFRESH, fake, now)


def test_events_come_in_the_calendar_shape_page_by_page(tmp_path):
    fake = FakeCalendar()
    stats = run(tmp_path, fake)
    assert stats["added"] == 3 and stats["skipped"] == 1

    listings = fake.listings()
    assert len(listings) == 2 and listings[1]["pageToken"] == "2"
    assert listings[0]["singleEvents"] == "true"
    assert (listings[0]["timeMin"], listings[0]["timeMax"]) == (
        "2025-10-29T12:00:00Z",
        "2026-12-28T12:00:00Z",
    )
    assert fake.form["grant_type"] == "refresh_token" and fake.form["refresh_token"] == REFRESH
    assert fake.form["client_secret"] == "client-secret"

    got = stored(tmp_path)
    test = got["uid-visit@calendar.example"]
    assert set(test) == {
        "id",
        "ts",
        "start",
        "end",
        "all_day",
        "timezone",
        "summary",
        "location",
        "description",
        "rrule",
        "status",
        "organizer",
        "attendees",
        "guests",
    }
    assert (test["ts"], test["start"], test["end"]) == (
        "2026-10-30T13:00:00Z",
        "2026-10-30T13:00:00Z",
        "2026-10-30T13:30:00Z",
    )
    assert test["timezone"] == "America/New_York" and test["status"] == "CONFIRMED"
    assert test["description"] == "Bring your old glasses.\nTen minutes early."
    assert test["organizer"] == "joe@home.example" and test["attendees"] == 3
    assert test["guests"] == [
        {"name": None, "email": "joe@home.example", "status": "accepted"},
        {"name": "Front desk", "email": "desk@optician.example", "status": "needs-action"},
    ]
    assert test["rrule"] is None and not test["all_day"]

    garden = got["uid-garden@calendar.example/2026-11-03T19:00:00Z"]  # by its original start
    assert garden["start"] == "2026-11-03T20:00:00Z" and garden["status"] == "TENTATIVE"
    assert garden["timezone"] == "Europe/London"  # the calendar's, when the event has none
    away = got["uid-holiday@calendar.example"]
    assert away["all_day"] and away["ts"] == "2026-12-24T00:00:00Z" and away["timezone"] is None
    assert (away["start"], away["end"]) == ("2026-12-24", "2026-12-27")


def test_a_rerun_changes_nothing(tmp_path):
    run(tmp_path, FakeCalendar())
    before = {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.jsonl")}
    stats = run(tmp_path, FakeCalendar(), NOW + timedelta(minutes=15))
    assert stats["added"] == stats["updated"] == stats["months_written"] == 0
    assert {p: p.read_bytes() for p in (tmp_path / "raw").rglob("*.jsonl")} == before

    moved = items()
    moved[0] = {**moved[0], "summary": "Eye test, moved room"}
    assert run(tmp_path, FakeCalendar(moved))["updated"] == 1


def test_refusals_say_what_to_do_and_never_hold_the_token(tmp_path):
    expired = FakeCalendar()
    expired.failures[gcalendar.GOOGLE_TOKEN] = [http_error(400)]
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, expired)
    assert "`proxenos auth gcalendar personal joe@home.example`" in str(stopped.value)
    assert REFRESH not in str(stopped.value)

    off = FakeCalendar()
    off.failures[gcalendar.EVENTS] = [http_error(403)]
    with pytest.raises(SystemExit, match="Turn on the Google Calendar API"):
        run(tmp_path, off)

    revoked = FakeCalendar()
    revoked.failures[gcalendar.EVENTS] = [http_error(401)]
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, revoked)
    assert "Sign in again" in str(stopped.value) and ACCESS not in str(stopped.value)


def test_it_needs_the_google_client(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    with pytest.raises(SystemExit, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        run(tmp_path, FakeCalendar())


def test_sync_reads_it_once_signed_in_and_the_command_prints_no_token(
    tmp_path, monkeypatch, capsys
):
    configured = dict(master._UNATTENDED)[master.gcalendar]
    assert not configured()
    monkeypatch.setenv("GCALENDAR_PERSONAL", f"joe@home.example:oauth:{REFRESH}")
    monkeypatch.setenv("GMAIL_PERSONAL", "joe@home.example:app-password")  # a different sign-in
    assert configured() and gcalendar.accounts() == {"personal": ("joe@home.example", REFRESH)}

    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(gcalendar, "_fetch_json", FakeCalendar())
    cli.main(["ingest", "gcalendar"])
    out = capsys.readouterr()
    assert out.out.startswith("gcalendar: ") and "3 added" in out.out
    assert REFRESH not in out.out + out.err and ACCESS not in out.out + out.err
