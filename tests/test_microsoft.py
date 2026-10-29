"""Microsoft 365 mail and calendar through Graph, against a fake Graph. No network, no real mail."""

import io
import json
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import cli, master
from proxenos.ingest import email, microsoft

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
REFRESH = "M.C5-refresh-token-that-must-never-show"
ACCESS = "eyJ0eXAi.access-token-that-must-never-show"
GRAPH = microsoft.GRAPH

FOLDERS = [
    {"id": "inbox", "displayName": "Inbox", "parentFolderId": "root"},
    {"id": "projects", "displayName": "Projects", "parentFolderId": "inbox"},
    {"id": "sent", "displayName": "Sent Items", "parentFolderId": "root"},
    {"id": "junk", "displayName": "Junk Email", "parentFolderId": "root"},
    {"id": "trash", "displayName": "Deleted Items", "parentFolderId": "root"},
    {"id": "old", "displayName": "Old", "parentFolderId": "trash"},
]


def person(address, name=None):
    return {"emailAddress": {"name": name or address, "address": address}}


def message(mid, sender, to, subject, when, folder="inbox", **extra):
    return {
        "id": f"graph-{mid}",
        "internetMessageId": f"<{mid}>",
        "subject": subject,
        "from": person(sender, "Ann Example" if sender.startswith("ann") else None),
        "toRecipients": [person(a) for a in to],
        "ccRecipients": [],
        "sentDateTime": when,
        "receivedDateTime": when,
        "isDraft": False,
        "parentFolderId": folder,
        "conversationId": "conv-1",
        "body": {"contentType": "text", "content": "See you then.\r\n"},
        "internetMessageHeaders": None,
        "attachments": [],
        **extra,
    }


def mail():
    return [
        message(
            "m1",
            "ann@clinic.example",
            ["joe@work.example"],
            "Visit on Friday",
            "2026-10-01T09:00:00Z",
            folder="projects",
            ccRecipients=[person("Bo@Clinic.example")],
            attachments=[{"name": "form.pdf"}, {"name": "map.png"}],
            internetMessageHeaders=[{"name": "List-Id", "value": "<news.clinic.example>"}],
        ),
        message(
            "m2",
            "joe@work.example",
            ["ann@clinic.example"],
            "Re: Visit on Friday",
            "2026-10-02T10:30:00.0000000Z",
            folder="sent",
            body={
                "contentType": "text",
                "content": "Friday works.\r\n\r\nOn Thu, Ann wrote:\r\n> See you then.\r\n",
            },
            internetMessageHeaders=[{"name": "In-Reply-To", "value": "<m1>"}],
        ),
        message(
            "m3", "spam@junk.example", ["joe@work.example"], "Win", "2026-10-03T00:00:00Z", "junk"
        ),
        message(
            "m4", "ann@clinic.example", ["joe@work.example"], "Old", "2026-10-04T00:00:00Z", "old"
        ),
        message(
            "m5",
            "joe@work.example",
            ["ann@clinic.example"],
            "Draft",
            "2026-10-05T00:00:00Z",
            isDraft=True,
        ),
    ]


def events():
    attendees = [
        {
            "type": "required",
            "status": {"response": "accepted"},
            "emailAddress": {"name": "Ann Example", "address": "Ann@Clinic.example"},
        },
        {
            "type": "optional",
            "status": {"response": "tentativelyAccepted"},
            "emailAddress": {"name": "bo@clinic.example", "address": "bo@clinic.example"},
        },
        {
            "type": "resource",
            "status": {"response": "accepted"},
            "emailAddress": {"name": "Room 4", "address": "room4@work.example"},
        },
    ]
    return [
        {
            "iCalUId": "uid-visit",
            "type": "singleInstance",
            "subject": "Visit",
            "start": {"dateTime": "2026-10-30T14:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-10-30T15:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": False,
            "originalStartTimeZone": "Eastern Standard Time",
            "location": {"displayName": "Clinic"},
            "bodyPreview": "Bring the form.",
            "organizer": person("ann@clinic.example", "Ann Example"),
            "attendees": attendees,
            "isCancelled": False,
        },
        {
            "iCalUId": "uid-class",
            "type": "occurrence",
            "subject": "Pottery class",
            "start": {"dateTime": "2026-11-03T23:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-11-04T01:00:00.0000000", "timeZone": "UTC"},
            "originalStart": "2026-11-03T23:00:00Z",
            "isAllDay": False,
            "originalStartTimeZone": "Europe/London",
            "organizer": person("joe@work.example"),
            "attendees": [],
            "isCancelled": True,
        },
        {
            "iCalUId": "uid-leave",
            "type": "singleInstance",
            "subject": "Leave",
            "start": {"dateTime": "2026-12-24T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-12-27T00:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": True,
            "attendees": [],
        },
        {"iCalUId": "uid-broken", "type": "singleInstance", "subject": "No start"},
    ]


def http_error(url, code, body, headers=None):
    return urllib.error.HTTPError(
        url, code, "error", headers or {}, io.BytesIO(json.dumps(body).encode())
    )


class FakeGraph:
    """The token endpoint and the few Graph listings the ingester reads, two items a page."""

    def __init__(self, messages=None, calendar=None, refresh=REFRESH):
        self.messages = mail() if messages is None else messages
        self.calendar = events() if calendar is None else calendar
        self.refresh = refresh
        self.requests = []
        self.failures = {}  # path → errors to raise, in turn, before answering

    def __call__(self, request):
        self.requests.append(request)
        url = urllib.parse.urlparse(request.full_url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if self.failures.get(url.path):
            raise self.failures[url.path].pop(0)
        if request.full_url == microsoft.AUTHORITY + "token":
            self.form = {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}
            return {"access_token": ACCESS, "refresh_token": self.refresh, "expires_in": 3600}
        assert request.full_url.startswith(GRAPH + "/")
        assert request.headers["Authorization"] == f"Bearer {ACCESS}"
        path = url.path.removeprefix("/v1.0")
        if path == "/me/mailFolders/delta":
            return {
                "value": FOLDERS,
                "@odata.deltaLink": f"{GRAPH}/me/mailFolders/delta?$deltatoken=x",
            }
        if path in ("/me/mailFolders/junkemail", "/me/mailFolders/deleteditems"):
            return {"id": {"junkemail": "junk", "deleteditems": "trash"}[path.rsplit("/", 1)[1]]}
        if path == "/me/messages":
            assert request.headers["Prefer"] == 'outlook.body-content-type="text"'
            since = query["$filter"].removeprefix("receivedDateTime ge ")
            found = sorted(
                (m for m in self.messages if microsoft._instant(m["receivedDateTime"]) >= since),
                key=lambda m: microsoft._instant(m["receivedDateTime"]),
            )
            return self._page(path, query, found)
        if path == "/me/calendarView":
            assert request.headers["Prefer"] == 'outlook.timezone="UTC"'
            return self._page(path, query, self.calendar)
        raise AssertionError(f"unexpected request {request.full_url}")

    def _page(self, path, query, items):
        skip = int(query.pop("$skiptoken", 0))
        page = {"value": items[skip : skip + 2]}
        if skip + 2 < len(items):
            following = urllib.parse.urlencode({**query, "$skiptoken": skip + 2}, safe="$")
            page["@odata.nextLink"] = f"{GRAPH}{path}?{following}"
        return page

    def asked(self, path):
        return [
            r for r in self.requests if urllib.parse.urlparse(r.full_url).path == "/v1.0" + path
        ]


@pytest.fixture(autouse=True)
def client(monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(microsoft, "_wait", lambda seconds: None)


def stored(vault, kind, name="work"):
    out = vault / "raw" / kind / name
    return {
        r["id"]: r
        for f in sorted(out.glob("*.jsonl"))
        for r in map(json.loads, f.read_text().splitlines())
    }


def files(vault):
    return {p: p.read_bytes() for p in sorted(vault.rglob("*")) if p.is_file()}


def run(vault, fake, now=NOW, full=False):
    return microsoft.ingest(
        vault, "work", "joe@work.example", REFRESH, ["Joe@Home.example"], full, fake, now
    )


def test_mail_comes_in_the_mbox_shape_from_every_folder_but_junk_trash_and_drafts(tmp_path):
    fake = FakeGraph()
    stats = run(tmp_path, fake)

    got = stored(tmp_path, "email")
    assert set(got) == {"m1", "m2"}
    assert stats["mail_added"] == 2 and stats["mail_skipped"] == 0
    raw = b"From x\nFrom: a@b.example\nDate: Fri, 31 Jan 2025 10:00:00 +0000\n\nHi\n"
    assert set(got["m1"]) == set(email._record(raw, "work", set()))  # field for field

    received, sent = got["m1"], got["m2"]
    assert received["ts"] == "2026-10-01T09:00:00Z" and received["account"] == "work"
    assert (
        received["from_address"] == "ann@clinic.example" and received["from_name"] == "Ann Example"
    )
    assert not received["from_me"] and sent["from_me"]
    assert received["to"] == ["joe@work.example"] and received["cc"] == ["bo@clinic.example"]
    assert received["attachments"] == ["form.pdf", "map.png"] and sent["attachments"] is None
    assert received["bulk"] and not sent["bulk"]
    assert received["gmail_labels"] == ["Inbox/Projects"] and sent["gmail_labels"] == ["Sent Items"]
    assert received["gmail_thread"] == "conv-1"
    assert sent["ts"] == "2026-10-02T10:30:00Z" and sent["in_reply_to"] == "m1"
    assert sent["subject"] == "Re: Visit on Friday" and sent["from_name"] is None
    assert sent["body"].startswith("Friday works.\n") and sent["body_new"] == "Friday works."


def test_messages_and_events_are_read_page_by_page(tmp_path):
    fake = FakeGraph()
    run(tmp_path, fake)
    assert len(fake.asked("/me/messages")) == 3  # five messages, two a page
    assert len(fake.asked("/me/calendarView")) == 2
    first = urllib.parse.parse_qs(
        urllib.parse.urlparse(fake.asked("/me/messages")[0].full_url).query
    )
    assert first["$expand"] == ["attachments($select=name)"]
    assert first["$orderby"] == ["receivedDateTime asc"]


def test_a_rerun_changes_nothing_and_reads_only_newer_mail(tmp_path):
    fake = FakeGraph()
    run(tmp_path, fake)
    before = {p: b for p, b in files(tmp_path).items() if "raw" in p.parts}

    again = FakeGraph()
    stats = run(tmp_path, again, NOW + timedelta(hours=1))
    assert {p: b for p, b in files(tmp_path).items() if "raw" in p.parts} == before
    assert stats["mail_added"] == stats["mail_updated"] == stats["mail_months_written"] == 0
    assert stats["events_added"] == stats["events_updated"] == stats["events_months_written"] == 0
    asked = urllib.parse.parse_qs(
        urllib.parse.urlparse(again.asked("/me/messages")[0].full_url).query
    )
    assert asked["$filter"] == ["receivedDateTime ge 2026-10-05T00:00:00Z"]  # the newest seen

    full = FakeGraph()
    run(tmp_path, full, full=True)
    asked = urllib.parse.parse_qs(
        urllib.parse.urlparse(full.asked("/me/messages")[0].full_url).query
    )
    assert asked["$filter"] == ["receivedDateTime ge 1900-01-01T00:00:00Z"]


def test_new_mail_is_added_on_the_next_run(tmp_path):
    fake = FakeGraph()
    run(tmp_path, fake)
    later = message(
        "m6", "ann@clinic.example", ["joe@work.example"], "Results", "2026-10-20T08:00:00Z"
    )
    stats = run(tmp_path, FakeGraph([*mail(), later]))
    assert stats["mail_added"] == 1 and "m6" in stored(tmp_path, "email")


def test_the_calendar_comes_in_the_calendar_shape(tmp_path):
    fake = FakeGraph()
    stats = run(tmp_path, fake)
    got = stored(tmp_path, "calendar")
    assert stats["events_added"] == 3 and stats["events_skipped"] == 1

    window = urllib.parse.parse_qs(
        urllib.parse.urlparse(fake.asked("/me/calendarView")[0].full_url).query
    )
    assert window["startDateTime"] == ["2025-10-29T12:00:00Z"]
    assert window["endDateTime"] == ["2026-12-28T12:00:00Z"]

    visit = got["uid-visit"]
    assert set(visit) == {
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
    assert (visit["ts"], visit["start"], visit["end"]) == (
        "2026-10-30T14:00:00Z",
        "2026-10-30T14:00:00Z",
        "2026-10-30T15:00:00Z",
    )
    assert visit["timezone"] is None  # a Windows zone name isn't an IANA one
    assert visit["summary"] == "Visit" and visit["location"] == "Clinic"
    assert visit["description"] == "Bring the form." and visit["rrule"] is None
    assert visit["organizer"] == "ann@clinic.example" and visit["attendees"] == 3
    assert visit["guests"] == [
        {"name": "Ann Example", "email": "ann@clinic.example", "status": "accepted"},
        {"name": None, "email": "bo@clinic.example", "status": "tentative"},
    ]

    occurrence = got["uid-class/2026-11-03T23:00:00Z"]
    assert occurrence["status"] == "CANCELLED" and occurrence["timezone"] == "Europe/London"
    leave = got["uid-leave"]
    assert leave["all_day"] and leave["ts"] == "2026-12-24T00:00:00Z"
    assert (leave["start"], leave["end"]) == ("2026-12-24", "2026-12-27")


def test_the_refresh_has_no_secret_and_a_rotated_token_is_saved_once_a_week(
    tmp_path, fake_keychain
):
    fake = FakeGraph(refresh="rotated-1")
    run(tmp_path, fake)
    assert fake.form["grant_type"] == "refresh_token" and fake.form["refresh_token"] == REFRESH
    assert fake.form["scope"] == microsoft.SCOPES and "client_secret" not in fake.form
    assert fake_keychain.items == {"MICROSOFT_WORK": "joe@work.example:oauth:rotated-1"}

    run(tmp_path, FakeGraph(refresh="rotated-2"), NOW + timedelta(days=3))
    assert fake_keychain.items["MICROSOFT_WORK"].endswith(":rotated-1")
    run(tmp_path, FakeGraph(refresh="rotated-3"), NOW + timedelta(days=8))
    assert fake_keychain.items["MICROSOFT_WORK"].endswith(":rotated-3")

    state = (tmp_path / "state" / "microsoft_work.json").read_text()
    assert "rotated" not in state and REFRESH not in state and ACCESS not in state
    assert json.loads(state)["token_saved"] == "2026-11-06T12:00:00Z"


def test_a_refused_sign_in_says_how_to_sign_in_again_without_the_token(tmp_path, capsys):
    fake = FakeGraph()
    description = "AADSTS700082: The refresh token has expired.\r\nTrace ID: abc"
    fake.failures["/common/oauth2/v2.0/token"] = [
        http_error(
            microsoft.AUTHORITY + "token",
            400,
            {"error": "invalid_grant", "error_description": description},
        )
    ]
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, fake)
    said = str(stopped.value)
    assert "AADSTS700082: The refresh token has expired." in said and "Trace ID" not in said
    assert "`proxenos auth microsoft work joe@work.example`" in said
    assert REFRESH not in said + capsys.readouterr().err


def test_graph_errors_are_explained_and_throttling_is_waited_out(tmp_path, monkeypatch):
    fake = FakeGraph()
    busy = http_error(
        GRAPH + "/me/messages", 429, {"error": {"code": "TooManyRequests"}}, {"Retry-After": "2"}
    )
    fake.failures["/v1.0/me/messages"] = [busy, busy]
    waited = []
    monkeypatch.setattr(microsoft, "_wait", waited.append)
    run(tmp_path, fake)
    assert waited == [2.0, 2.0] and "m1" in stored(tmp_path, "email")

    denied = FakeGraph()
    denied.failures["/v1.0/me/mailFolders/delta"] = [
        http_error(GRAPH, 403, {"error": {"code": "ErrorAccessDenied", "message": "no"}})
    ]
    with pytest.raises(SystemExit, match="ErrorAccessDenied.*admin to approve"):
        run(tmp_path, denied)

    bad = FakeGraph()
    bad.failures["/v1.0/me/calendarView"] = [
        http_error(GRAPH, 400, {"error": {"code": "BadRequest"}})
    ]
    with pytest.raises(SystemExit, match="answered 400 \\(BadRequest\\); the next sync"):
        run(tmp_path, bad)


def test_a_next_page_somewhere_else_never_gets_the_token(tmp_path):
    fake = FakeGraph()
    fake.calendar = []
    original = fake._page

    def elsewhere(path, query, items):
        page = original(path, query, items)
        if path == "/me/messages":
            page["@odata.nextLink"] = "https://graph.evil.example/v1.0/me/messages?$skiptoken=2"
        return page

    fake._page = elsewhere
    with pytest.raises(SystemExit, match="somewhere else"):
        run(tmp_path, fake)
    assert all(r.full_url.startswith((GRAPH, microsoft.AUTHORITY)) for r in fake.requests)


def test_accounts_come_from_sign_ins_only(monkeypatch):
    monkeypatch.setenv("MICROSOFT_WORK", f"joe@work.example:oauth:{REFRESH}")
    monkeypatch.setenv("MICROSOFT_ODD", "not a sign-in")
    assert microsoft.accounts() == {"work": ("joe@work.example", REFRESH)}


def test_sync_reads_it_once_an_account_is_signed_in(monkeypatch):
    configured = dict(master._UNATTENDED)[master.microsoft]
    assert not configured()
    monkeypatch.setenv("MICROSOFT_WORK", f"joe@work.example:oauth:{REFRESH}")
    assert configured()


def test_the_command_reads_every_account_and_prints_no_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    monkeypatch.setenv("MICROSOFT_WORK", f"joe@work.example:oauth:{REFRESH}")
    fake = FakeGraph()
    monkeypatch.setattr(microsoft, "_fetch_json", fake)
    cli.main(["ingest", "microsoft"])
    out = capsys.readouterr()
    assert out.out.startswith("microsoft: ") and "2 mail added" in out.out
    assert REFRESH not in out.out + out.err and ACCESS not in out.out + out.err
    vault_text = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert REFRESH not in vault_text and ACCESS not in vault_text
