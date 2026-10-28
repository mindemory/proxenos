"""Spotify ingester against a synthetic Extended Streaming History export. No real data here."""

import json

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
