"""Strava ingester against a fake Strava API. No real data or credentials live in this repo."""

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from proxenos.ingest import strava

START = datetime(2024, 1, 1, 6, 30, tzinfo=UTC)


def activity(n, **changes):
    """A summary activity as /athlete/activities returns it, one per day from START."""
    return {
        "id": 9000 + n,
        "name": f"Morning run {n}",
        "sport_type": "Run",
        "start_date": (START + timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "(GMT-05:00) America/New_York",
        "distance": 5000.0,
        "moving_time": 1500,
        "elapsed_time": 1620,
        "total_elevation_gain": 40.0,
        "average_speed": 3.33,
        "max_speed": 4.8,
        "average_heartrate": 151.2,
        "max_heartrate": 176.0,
        "kudos_count": 2,
        "commute": False,
        "trainer": False,
        "gear_id": "g1",
        "start_latlng": [10.0, 20.0],
        "end_latlng": [10.5, 20.5],
        "map": {"id": "a1", "summary_polyline": "synthetic-polyline", "resource_state": 2},
        **changes,
    }


class FakeStrava:
    """Stands in for urlopen: the token endpoint rotates refresh tokens, the activities
    endpoint filters on `after` and pages. `fail` maps a page number to an HTTP status."""

    def __init__(self, activities):
        self.activities = activities
        self.refresh_tokens_sent = []
        self.queries = []
        self.fail = {}

    def __call__(self, request):
        if request.full_url == strava.TOKEN_URL:
            form = urllib.parse.parse_qs(request.data.decode())
            assert form["grant_type"] == ["refresh_token"]
            self.refresh_tokens_sent.append(form["refresh_token"][0])
            rotated = f"rotated-{len(self.refresh_tokens_sent)}"
            return {"access_token": "access", "refresh_token": rotated, "expires_at": 0}

        url, _, query = request.full_url.partition("?")
        assert url == strava.ACTIVITIES_URL
        assert request.get_header("Authorization") == "Bearer access"
        query = {k: int(v) for k, v in urllib.parse.parse_qsl(query)}
        self.queries.append(query)
        if query["page"] in self.fail:
            raise urllib.error.HTTPError(url, self.fail[query["page"]], "error", {}, None)
        after = query.get("after", 0)
        matching = [a for a in self.activities if _epoch(a["start_date"]) > after]
        size, page = query["per_page"], query["page"]
        return matching[(page - 1) * size : page * size]


def _epoch(start_date):
    return datetime.fromisoformat(start_date).timestamp()


def stored(vault):
    out = vault / "raw" / "strava" / "activities"
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return {r["id"]: r for r in map(json.loads, lines)}


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "12345")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("STRAVA_REFRESH_TOKEN", "from-env")
    # Anything that slips past the fake fails here instead of reaching Strava.
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("live HTTP"))


def test_records_keep_the_summary_and_drop_location(tmp_path):
    no_hr = {k: v for k, v in activity(1).items() if "heartrate" not in k}
    strava.ingest(tmp_path, fetch=FakeStrava([activity(0), no_hr]))
    records = stored(tmp_path)

    assert records["strava:9000"] == {
        "id": "strava:9000",
        "ts": "2024-01-01T06:30:00Z",
        "name": "Morning run 0",
        "sport_type": "Run",
        "distance_m": 5000.0,
        "moving_time_s": 1500,
        "elapsed_time_s": 1620,
        "total_elevation_gain_m": 40.0,
        "average_speed": 3.33,
        "max_speed": 4.8,
        "average_heartrate": 151.2,
        "max_heartrate": 176.0,
        "kudos_count": 2,
        "commute": False,
        "trainer": False,
        "gear_id": "g1",
        "timezone": "(GMT-05:00) America/New_York",
    }
    without_hr = records["strava:9001"]
    assert without_hr["average_heartrate"] is without_hr["max_heartrate"] is None
    raw = (tmp_path / "raw" / "strava" / "activities" / "2024-01.jsonl").read_text()
    assert "polyline" not in raw and "latlng" not in raw and "20.5" not in raw


def test_first_run_pages_through_everything(tmp_path):
    fake = FakeStrava([activity(n) for n in range(450)])
    stats = strava.ingest(tmp_path, fetch=fake)

    assert [q["page"] for q in fake.queries] == [1, 2, 3, 4]  # 200, 200, 50, then empty
    assert all(q["per_page"] == 200 and "after" not in q for q in fake.queries)
    assert (stats["read"], stats["added"]) == (450, 450)
    assert len(stored(tmp_path)) == 450


def test_later_runs_ask_only_since_the_latest_stored_start_less_a_margin(tmp_path):
    fake = FakeStrava([activity(n) for n in range(30)])
    strava.ingest(tmp_path, fetch=fake)

    # A late kudo on the newest stored run, and a new run.
    fake.activities[29] = activity(29, kudos_count=5)
    fake.activities.append(activity(30))
    fake.queries.clear()
    stats = strava.ingest(tmp_path, fetch=fake)

    latest = START + timedelta(days=29)
    assert fake.queries[0]["after"] == int((latest - strava.MARGIN).timestamp())
    # Runs 23 to 30 start after the cutoff; run 22 sits exactly on it.
    assert stats == {"read": 8, "added": 1, "updated": 1, "months_written": 1}
    assert stored(tmp_path)["strava:9029"]["kudos_count"] == 5

    fake.queries.clear()
    stats = strava.ingest(tmp_path, full=True, fetch=fake)
    assert "after" not in fake.queries[0]
    assert stats == {"read": 31, "added": 0, "updated": 0, "months_written": 0}


def test_rotated_refresh_tokens_are_saved_and_preferred(tmp_path, monkeypatch):
    fake = FakeStrava([])
    state = tmp_path / "state" / "strava_token.json"

    strava.ingest(tmp_path, fetch=fake)
    assert json.loads(state.read_text())["refresh_token"] == "rotated-1"
    assert os.name == "nt" or stat.S_IMODE(state.stat().st_mode) == 0o600

    strava.ingest(tmp_path, fetch=fake)
    monkeypatch.delenv("STRAVA_REFRESH_TOKEN")
    strava.ingest(tmp_path, fetch=fake)  # the saved token is enough on its own
    # Re-authorizing puts a new token in the env, which replaces the saved one.
    monkeypatch.setenv("STRAVA_REFRESH_TOKEN", "reauthorized")
    strava.ingest(tmp_path, fetch=fake)
    strava.ingest(tmp_path, fetch=fake)

    sent = ["from-env", "rotated-1", "rotated-2", "reauthorized", "rotated-4"]
    assert fake.refresh_tokens_sent == sent
    assert "reauthorized" not in state.read_text()  # only its hash is kept


def test_missing_credentials_name_the_env_vars(tmp_path, monkeypatch):
    for name in ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"):
        monkeypatch.delenv(name)
    fake = FakeStrava([activity(0)])

    names = "STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN"
    with pytest.raises(SystemExit, match=names):
        strava.ingest(tmp_path, fetch=fake)
    assert fake.refresh_tokens_sent == fake.queries == []


@pytest.mark.parametrize(
    "page, status, message", [(2, 429, "rate limited"), (1, 401, "activity:read_all")]
)
def test_http_errors_stop_cleanly_without_writing(tmp_path, page, status, message):
    fake = FakeStrava([activity(n) for n in range(450)])
    fake.fail[page] = status

    with pytest.raises(SystemExit, match=message):
        strava.ingest(tmp_path, fetch=fake)
    assert not (tmp_path / "raw" / "strava" / "activities").exists()
    # The refresh token rotated before the failure, so it must still have been saved.
    assert json.loads((tmp_path / "state" / "strava_token.json").read_text())["refresh_token"]
