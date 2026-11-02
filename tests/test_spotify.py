"""Spotify ingester against a synthetic Extended Streaming History export. No real data here."""

import argparse
import json
import os
import stat
import urllib.parse

import pytest

from proxenos.ingest import spotify

# Every key an entry in the export carries, in the export's order.
FIELDS = [
    "ts",
    "platform",
    "ms_played",
    "conn_country",
    "ip_addr",
    "master_metadata_track_name",
    "master_metadata_album_artist_name",
    "master_metadata_album_album_name",
    "spotify_track_uri",
    "episode_name",
    "episode_show_name",
    "spotify_episode_uri",
    "audiobook_title",
    "audiobook_uri",
    "audiobook_chapter_uri",
    "audiobook_chapter_title",
    "reason_start",
    "reason_end",
    "shuffle",
    "skipped",
    "offline",
    "offline_timestamp",
    "incognito_mode",
]


def entry(ts, ms=200_000, **fields):
    base = dict.fromkeys(FIELDS)
    base.update(
        ts=ts,
        ms_played=ms,
        platform="ios",
        conn_country="US",
        ip_addr="192.0.2.1",
        reason_start="trackdone",
        reason_end="trackdone",
        shuffle=False,
        skipped=False,
        offline=False,
        offline_timestamp=1700000000,
        incognito_mode=False,
    )
    base.update(fields)
    return base


def song(ts, n=1, **fields):
    return entry(
        ts,
        master_metadata_track_name=f"Song {n}",
        master_metadata_album_artist_name="Artist A",
        master_metadata_album_album_name="Album A",
        spotify_track_uri=f"spotify:track:t{n}",
        **fields,
    )


EPISODE = entry(
    "2025-02-01T08:00:00Z",
    episode_name="Episode 7",
    episode_show_name="Podcast X",
    spotify_episode_uri="spotify:episode:e7",
)
CHAPTER = entry(
    "2025-02-02T21:00:00Z",
    audiobook_title="Book B",
    audiobook_uri="spotify:show:b1",
    audiobook_chapter_uri="spotify:episode:c3",
    audiobook_chapter_title="Chapter 3",
)
AUDIO = [song("2025-01-31T23:59:59Z", 1), song("2025-02-01T00:03:20Z", 2), EPISODE, CHAPTER]
VIDEO = [song("2025-02-03T12:00:00Z", 3)]


def make_export(path, audio, video=()):
    path.mkdir(parents=True)
    (path / "Streaming_History_Audio_2025_0.json").write_text(json.dumps(audio))
    if video:
        (path / "Streaming_History_Video_2025.json").write_text(json.dumps(list(video)))
    return path


def by_id(export):
    return {r["id"]: r for r in spotify.read_plays(export)}


def test_entries_become_flat_play_records(tmp_path):
    plays = by_id(make_export(tmp_path / "x", AUDIO, VIDEO))
    assert len(plays) == 5

    track = plays["2025-01-31T23:59:59Z/spotify:track:t1"]
    assert (track["kind"], track["video"], track["ms_played"]) == ("track", False, 200_000)
    assert (track["track"], track["artist"], track["album"]) == ("Song 1", "Artist A", "Album A")
    assert (track["episode"], track["show"]) == (None, None)
    assert "ip_addr" not in track and "offline_timestamp" not in track

    episode = plays["2025-02-01T08:00:00Z/spotify:episode:e7"]
    assert (episode["kind"], episode["episode"], episode["show"]) == (
        "episode",
        "Episode 7",
        "Podcast X",
    )
    assert episode["track"] is None

    chapter = plays["2025-02-02T21:00:00Z/spotify:episode:c3"]
    assert (chapter["kind"], chapter["episode"], chapter["show"]) == (
        "audiobook",
        "Chapter 3",
        "Book B",
    )

    assert plays["2025-02-03T12:00:00Z/spotify:track:t3"]["video"] is True


def test_older_exports_missing_keys_get_none(tmp_path):
    old = song("2021-09-01T10:00:00+00:00")
    for key in ("audiobook_title", "audiobook_uri", "audiobook_chapter_uri", "skipped"):
        del old[key]
    [play] = spotify.read_plays(make_export(tmp_path / "x", [old]))
    assert play["ts"] == "2021-09-01T10:00:00Z"
    assert (play["kind"], play["skipped"]) == ("track", None)


def test_colliding_plays_get_deterministic_ids(tmp_path):
    ts = "2025-03-01T09:00:00Z"
    dup = song(ts, ip_addr="198.51.100.7")  # same play logged twice; only the address differs
    short = song(ts, ms=1_000, reason_end="fwdbtn", skipped=True)
    local = entry(ts, master_metadata_track_name="Home Demo")  # a local file has no URI
    first = by_id(make_export(tmp_path / "a", [song(ts), dup, short, local]))
    second = by_id(make_export(tmp_path / "b", [local, short, song(ts), dup]))

    assert first == second
    base = f"{ts}/spotify:track:t1"
    assert set(first) == {base, f"{base}#2", f"{ts}/track:Home Demo"}
    assert {first[base]["ms_played"], first[f"{base}#2"]["ms_played"]} == {200_000, 1_000}


def test_reingest_is_idempotent_and_newer_exports_only_add(tmp_path):
    vault = tmp_path / "vault"
    out = vault / "raw" / "spotify" / "plays"

    first = spotify.ingest(vault, make_export(tmp_path / "1", AUDIO, VIDEO))
    assert first == {"read": 5, "added": 5, "updated": 0, "months_written": 2}
    assert sorted(p.name for p in out.iterdir()) == ["2025-01.jsonl", "2025-02.jsonl"]

    again = spotify.ingest(vault, tmp_path / "1")
    assert again == {"read": 5, "added": 0, "updated": 0, "months_written": 0}

    # A later export repeats the whole history and adds a month.
    later = spotify.ingest(
        vault, make_export(tmp_path / "2", AUDIO + [song("2025-04-01T00:00:00Z")], VIDEO)
    )
    assert later == {"read": 6, "added": 1, "updated": 0, "months_written": 1}

    jan = [json.loads(line) for line in (out / "2025-01.jsonl").read_text().splitlines()]
    assert [r["id"] for r in jan] == ["2025-01-31T23:59:59Z/spotify:track:t1"]


def test_an_export_without_history_files_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError, match="Streaming_History"):
        spotify.read_plays(tmp_path)


def test_without_an_export_argument_the_setting_names_the_folder(tmp_path, monkeypatch):
    export = make_export(tmp_path / "history", AUDIO, VIDEO)
    monkeypatch.setenv("PROXENOS_SPOTIFY_EXPORT", str(export))
    assert spotify.run(tmp_path / "vault", argparse.Namespace(export=None))["added"] == 5


def test_with_neither_an_argument_nor_the_setting_it_names_the_setting(tmp_path):
    with pytest.raises(SystemExit, match="PROXENOS_SPOTIFY_EXPORT"):
        spotify.ingest(tmp_path / "vault")


def played(at, n, kind="track"):
    track = {
        "type": kind,
        "name": f"Live {n}",
        "uri": f"spotify:{kind}:live{n}",
        "duration_ms": 180_000,
        "artists": [{"name": "Artist L"}],
        "album": {"name": "Album L"},
    }
    return {"played_at": at, "track": track}


class FakeSpotify:
    """The token endpoint, which rotates the refresh token once, and recently played."""

    def __init__(self, items):
        self.items, self.refreshed = items, []

    def __call__(self, request):
        if request.full_url == spotify.TOKEN_URL:
            form = dict(urllib.parse.parse_qsl(request.data.decode()))
            self.refreshed.append(form["refresh_token"])
            assert form["client_id"] == "client" and "client_secret" not in form
            return {"access_token": "access", "refresh_token": "rotated"}
        assert request.full_url == spotify.RECENT
        assert request.headers["Authorization"] == "Bearer access"
        return {"items": self.items}


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", "first")


def test_live_plays_come_in_as_play_records_and_the_newest_token_is_kept(tmp_path, signed_in):
    vault = tmp_path / "vault"
    api = FakeSpotify([played("2025-04-02T10:00:00.123Z", 1), played("2025-04-02T10:03:00Z", 2)])

    first = spotify.ingest_recent(vault, api)
    again = spotify.ingest_recent(vault, api)

    assert first["added"] == 2 and again["added"] == 0  # the same 50 again change nothing
    assert api.refreshed == ["first", "rotated"]  # the rotated token is the one used next
    state = vault / "state" / "spotify_token.json"
    assert json.loads(state.read_text())["refresh_token"] == "rotated"
    assert os.name == "nt" or stat.S_IMODE(state.stat().st_mode) == 0o600
    rows = [json.loads(line) for line in (vault / "raw/spotify/plays/2025-04.jsonl").open()]
    assert rows[0]["id"] == "2025-04-02T10:00:00Z/spotify:track:live1"
    assert (rows[0]["track"], rows[0]["artist"], rows[0]["ms_played"]) == (
        "Live 1",
        "Artist L",
        180_000,
    )
    assert rows[0]["source"] == "api" and spotify.live(vault)


def test_an_export_replaces_the_live_plays_it_covers(tmp_path, signed_in):
    vault = tmp_path / "vault"
    before, after = played("2025-02-02T09:00:00Z", 1), played("2025-04-05T09:00:00Z", 2)
    spotify.ingest_recent(vault, FakeSpotify([before, after]))

    stats = spotify.ingest(vault, make_export(tmp_path / "export", AUDIO, VIDEO))

    assert stats["live_replaced"] == 1  # the export runs to Feb 3, so April's play stays
    plays = vault / "raw" / "spotify" / "plays"
    kept = [json.loads(line) for f in sorted(plays.glob("*.jsonl")) for line in f.open()]
    assert [r["id"] for r in kept if r.get("source") == "api"] == [
        "2025-04-05T09:00:00Z/spotify:track:live2"
    ]


def test_a_sync_signed_in_with_no_export_reads_only_the_live_plays(
    tmp_path, signed_in, monkeypatch
):
    monkeypatch.delenv("PROXENOS_SPOTIFY_EXPORT", raising=False)
    monkeypatch.setattr(spotify, "ingest_recent", lambda v, fetch=spotify._fetch_json: {"added": 1})
    stats = spotify.run(tmp_path, argparse.Namespace(export=None))
    assert stats == {"live_added": 1}
