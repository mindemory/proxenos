"""Spotify plays from the Extended Streaming History export.

Reads the export's Streaming_History_Audio_*.json and Streaming_History_Video_*.json and
writes one record per play into the vault. Spotify only hands this history out as a bulk
export of the account's whole life, so every run re-reads an export and merges by id: point
--export at a newer one and the overlapping years are a no-op while the new months are added.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from proxenos.store import merge_monthly

DEFAULT_EXPORT = Path(
    "~/Documents/Personal/spotifyExplorer/Spotify Extended Streaming History"
).expanduser()

_AUDIO = "Streaming_History_Audio_*.json"
_VIDEO = "Streaming_History_Video_*.json"


def read_plays(export: Path = DEFAULT_EXPORT) -> list[dict]:
    files = [(p, False) for p in sorted(export.glob(_AUDIO))]
    files += [(p, True) for p in sorted(export.glob(_VIDEO))]
    if not files:
        raise FileNotFoundError(f"no Streaming_History_*.json files in {export}")
    plays = []
    for path, video in files:
        with path.open(encoding="utf-8") as f:
            plays += [_record(entry, video) for entry in json.load(f)]
    return _with_ids(plays)


def ingest(vault: Path, export: Path = DEFAULT_EXPORT) -> dict[str, int]:
    return merge_monthly(read_plays(export), vault / "raw" / "spotify" / "plays")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT, metavar="DIR")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export)


def _record(entry: dict, video: bool) -> dict:
    # Each entry fills exactly one of the track, episode or audiobook field groups.
    if entry.get("spotify_track_uri") or entry.get("master_metadata_track_name"):
        kind, uri = "track", entry.get("spotify_track_uri")
    elif entry.get("spotify_episode_uri") or entry.get("episode_name"):
        kind, uri = "episode", entry.get("spotify_episode_uri")
    elif entry.get("audiobook_chapter_uri") or entry.get("audiobook_title"):
        kind, uri = "audiobook", entry.get("audiobook_chapter_uri")
    else:
        kind, uri = "other", None

    # ts is when the play ended. ip_addr and offline_timestamp (mixed s/ms units) are dropped.
    ts = datetime.fromisoformat(entry["ts"]).astimezone(UTC)
    return {
        "ts": ts.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "kind": kind,
        "video": video,
        "track": entry.get("master_metadata_track_name") or None,
        "artist": entry.get("master_metadata_album_artist_name") or None,
        "album": entry.get("master_metadata_album_album_name") or None,
        # Spotify models an audiobook as a show whose chapters are episodes, URIs included.
        "episode": entry.get("episode_name") or entry.get("audiobook_chapter_title") or None,
        "show": entry.get("episode_show_name") or entry.get("audiobook_title") or None,
        "uri": uri or None,
        "ms_played": entry.get("ms_played"),
        "reason_start": entry.get("reason_start") or None,
        "reason_end": entry.get("reason_end") or None,
        "shuffle": entry.get("shuffle"),
        "skipped": entry.get("skipped"),
        "offline": entry.get("offline"),
        "incognito": entry.get("incognito_mode"),
        "platform": entry.get("platform") or None,
        "conn_country": entry.get("conn_country") or None,
    }


def _with_ids(plays: list[dict]) -> list[dict]:
    """Key plays by end time and URI. Spotify occasionally logs a play twice, so exact copies
    collapse into one record, and distinct plays that share a key get #2, #3, ... in content
    order. That keeps ids the same however the export happens to order its entries."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for play in plays:
        name = play["track"] or play["episode"] or ""
        groups[f"{play['ts']}/{play['uri'] or play['kind'] + ':' + name}"].append(play)

    out = []
    for key, group in groups.items():
        unique = {json.dumps(play, sort_keys=True): play for play in group}
        for n, (_, play) in enumerate(sorted(unique.items()), start=1):
            out.append({"id": key if n == 1 else f"{key}#{n}", **play})
    return out
