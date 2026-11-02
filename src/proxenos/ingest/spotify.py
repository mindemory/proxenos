"""Spotify plays from the Extended Streaming History export, and the latest ones live.

Reads the export's Streaming_History_Audio_*.json and Streaming_History_Video_*.json and
writes one record per play into the vault. Spotify only hands this history out as a bulk
export of the account's whole life, so every run re-reads an export and merges by id: point
--export at a newer one and the overlapping years are a no-op while the new months are added.
Without --export, the folder named by PROXENOS_SPOTIFY_EXPORT is read.

The export can take Spotify up to 30 days, so plays also come in live once the user has signed
in (`proxenos auth spotify`, through their own app at developer.spotify.com, whose client ID is
SPOTIFY_CLIENT_ID; PKCE, so no secret). Each run then reads the Web API's recently played: the
last 50 tracks, all Spotify keeps there, so a sync every hour or so misses only a long binge.
They go into the same month files, marked "source": "api", with the track's length as the time
played (the API doesn't say how much was heard; it lists a play only after 30 seconds). An
export replaces the live plays it covers: importing one drops those up to its newest play, so no
play is counted twice. Spotify may hand out a new refresh token on any refresh, so the latest is
kept in vault/state/spotify_token.json, as Strava's is.
"""

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxenos.config import env
from proxenos.store import drop_monthly, merge_monthly

_AUDIO = "Streaming_History_Audio_*.json"
_VIDEO = "Streaming_History_Video_*.json"
CLIENT = "SPOTIFY_CLIENT_ID"
REFRESH = "SPOTIFY_REFRESH_TOKEN"
SCOPE = "user-read-recently-played"
AUTHORIZE = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENT = "https://api.spotify.com/v1/me/player/recently-played?limit=50"
_STATE = Path("state", "spotify_token.json")
_HELP = "Sign in again with `proxenos auth spotify`."

Fetch = Callable[[urllib.request.Request], Any]


def _fetch_json(request: urllib.request.Request) -> Any:
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def live(vault: Path | None = None) -> bool:
    """Whether plays come in live: an app's client ID and a sign-in, saved or in the settings."""
    saved = vault is not None and (vault / _STATE).exists()
    return bool(os.environ.get(CLIENT) and (os.environ.get(REFRESH) or saved))


def default_export() -> Path:
    """The export folder from PROXENOS_SPOTIFY_EXPORT; stops with a message when it isn't set."""
    folder = env("SPOTIFY_EXPORT")
    if not folder:
        raise SystemExit(
            "spotify: set PROXENOS_SPOTIFY_EXPORT in .env to your Extended Streaming History "
            "folder, or pass --export DIR"
        )
    return Path(folder).expanduser()


def read_plays(export: Path | None = None) -> list[dict]:
    export = export or default_export()
    files = [(p, False) for p in sorted(export.glob(_AUDIO))]
    files += [(p, True) for p in sorted(export.glob(_VIDEO))]
    if not files:
        raise FileNotFoundError(f"no Streaming_History_*.json files in {export}")
    plays = []
    for path, video in files:
        with path.open(encoding="utf-8") as f:
            plays += [_record(entry, video) for entry in json.load(f)]
    return _with_ids(plays)


def ingest(vault: Path, export: Path | None = None) -> dict[str, int]:
    plays = read_plays(export)
    out = vault / "raw" / "spotify" / "plays"
    stats = merge_monthly(plays, out)
    if plays and (replaced := _drop_live(out, max(p["ts"] for p in plays))):
        stats["live_replaced"] = replaced
    return stats


def ingest_recent(vault: Path, fetch: Fetch = _fetch_json) -> dict[str, int]:
    """The account's last 50 plays from the Web API, into the month files the export fills."""
    token = _access_token(vault / _STATE, fetch)
    request = urllib.request.Request(RECENT, headers={"Authorization": f"Bearer {token}"})
    answer = _call(fetch, request)
    plays = [_recent(item) for item in answer.get("items") or [] if item.get("track")]
    return merge_monthly(_with_ids(plays), vault / "raw" / "spotify" / "plays")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export",
        type=Path,
        metavar="DIR",
        help="the Extended Streaming History folder (default: $PROXENOS_SPOTIFY_EXPORT)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    """The export when there's one to read, then the live plays when signed in."""
    stats: dict[str, int] = {}
    if args.export or env("SPOTIFY_EXPORT") or not live(vault):
        stats |= ingest(vault, args.export)
    if live(vault):
        recent = ingest_recent(vault)
        stats |= {f"live_{k}": v for k, v in recent.items()}
    return stats


def _access_token(state_path: Path, fetch: Fetch) -> str:
    """A fresh access token from the newest refresh token: the saved one while it descends from
    the SPOTIFY_REFRESH_TOKEN signed in with (by its hash), else that one, which means a new
    sign-in. Spotify's new refresh token, if it sent one, is saved before anything else."""
    client, env_token = os.environ.get(CLIENT), os.environ.get(REFRESH)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    seed = _sha256(env_token) if env_token else state.get("env_token_sha256")
    if state.get("refresh_token") and state.get("env_token_sha256") == seed:
        refresh = state["refresh_token"]
    else:
        refresh = env_token
    if not (client and refresh):
        raise SystemExit(f"spotify: set {CLIENT} and sign in once. {_HELP}")
    form = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client}
    request = urllib.request.Request(
        TOKEN_URL, data=urllib.parse.urlencode(form).encode(), method="POST"
    )
    token = _call(fetch, request)
    _save_state(
        state_path,
        {"refresh_token": token.get("refresh_token") or refresh, "env_token_sha256": seed},
    )
    return token["access_token"]


def _call(fetch: Fetch, request: urllib.request.Request) -> Any:
    try:
        return fetch(request)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit(
                "spotify: rate limited (HTTP 429); the next sync tries again."
            ) from None
        if e.code in (400, 401, 403):
            raise SystemExit(f"spotify: Spotify refused us (HTTP {e.code}). {_HELP}") from None
        raise


def _recent(item: dict) -> dict:
    """A play from recently played, in the export's record shape."""
    track = item["track"]
    episode = track.get("type") == "episode"
    ts = datetime.fromisoformat(item["played_at"]).astimezone(UTC)
    artists = track.get("artists") or []
    return {
        "ts": ts.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "kind": "episode" if episode else "track",
        "video": False,
        "track": None if episode else track.get("name") or None,
        "artist": (artists[0].get("name") if artists else None) or None,
        "album": (track.get("album") or {}).get("name") or None,
        "episode": track.get("name") or None if episode else None,
        "show": (track.get("show") or {}).get("name") or None,
        "uri": track.get("uri") or None,
        "ms_played": track.get("duration_ms"),
        "source": "api",
    }


def _drop_live(directory: Path, until: str) -> int:
    """Take the live plays up to `until`, an export's newest, out of the month files: the export
    has them now, with how long each was really heard."""
    return drop_monthly(directory, lambda r: r.get("source") == "api" and r["ts"] <= until, until)


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        # The mode above only applies when the file is new. (Not os.fchmod: Windows lacks it.)
        tmp.chmod(0o600)
        json.dump(state, f)
    os.replace(tmp, path)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
