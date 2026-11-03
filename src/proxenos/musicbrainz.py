"""Genres for the artists the user listens to, from MusicBrainz's open data, asked by name only.

Spotify's export names each play's track and artist and nothing else, and its Web API is no
better a source: audio features and recommendations closed to new apps in November 2024, and
while an artist's genres are still there (GET /artists/{id}), the export holds no artist ids,
development-mode apps lost the batch lookups in February 2026, and it would need the user's
sign-in. MusicBrainz (musicbrainz.org, run by the non-profit MetaBrainz Foundation) needs no
account or key, and its genres are voted on by its editors, where the model's labels
(clones/rhythms) are a guess from a name.

What goes out, and nothing else: one artist's name per request, in a search
(/ws/2/artist?query=artist:"<name>"), and every GENRE_DAYS the list of genres MusicBrainz knows
(/ws/2/genre/all). No track, time, count or anything about the user; like any request, it
carries this computer's internet address, and Proxenos's own User-Agent, as MusicBrainz asks.
One request every PACE seconds at most, since MusicBrainz allows one a second, and a night's
lookups stop at the first sign it's busy or out of reach.

Of the best match whose name or alias is the artist's own, with a score of MIN_SCORE or more,
the tags on MusicBrainz's genre list, most voted first, are its genres (KEPT of them), and those
in MOOD_TAGS give moods in the rhythms clone's vocabulary. MusicBrainz's core data is CC0, but
tags and genres are its supplementary data, under CC BY-NC-SA 3.0: they're read for the user's
own use, kept in their vault and credited on the page, never shipped with Proxenos.

Kept in clones/rhythms/musicbrainz.json: each artist's genres and moods, or when none was found,
asked again after RETRY_DAYS. PROXENOS_MUSICBRAINZ=off stops the lookups.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos.clones import work
from proxenos.config import env

API = "https://musicbrainz.org/ws/2"
USER_AGENT = "proxenos/0.1 ( https://github.com/mindemory/proxenos )"
LOOK_UP = 120  # artists a night looks up, the most played first: two minutes
PACE = 1.1  # seconds between requests
TIMEOUT = 20
MIN_SCORE = 90  # of MusicBrainz's 100, for a match by name
KEPT = 3  # genres kept for an artist
RETRY_DAYS = 90  # an artist MusicBrainz has no genres for waits this long to be asked again
GENRE_DAYS = 90  # the genre list is fetched again after this long
# Tags that say a mood, as the rhythms clone's vocabulary names it.
MOOD_TAGS = {
    "melancholic": "melancholic",
    "melancholy": "melancholic",
    "sad": "melancholic",
    "happy": "upbeat",
    "upbeat": "upbeat",
    "uplifting": "upbeat",
    "feel good": "upbeat",
    "energetic": "energetic",
    "party": "energetic",
    "chill": "calm",
    "chillout": "calm",
    "relaxing": "calm",
    "mellow": "calm",
    "calm": "calm",
    "romantic": "romantic",
    "love songs": "romantic",
    "aggressive": "intense",
    "intense": "intense",
    "dark": "intense",
    "nostalgic": "nostalgic",
    "nostalgia": "nostalgic",
    "study": "focused",
    "focus": "focused",
}

Fetch = Callable[[urllib.request.Request], bytes]


def _fetch(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def on() -> bool:
    """Whether artists' names may be looked up: unless PROXENOS_MUSICBRAINZ says off."""
    return env("MUSICBRAINZ", "on").strip().casefold() not in ("off", "0", "no", "false")


def path(vault: Path) -> Path:
    return vault / "clones" / "rhythms" / "musicbrainz.json"


def genres(vault: Path) -> dict[str, dict]:
    """Each artist looked up with genres or moods found: {name: {"genres", "moods"}}."""
    found = {}
    for name, entry in (_json(path(vault)).get("artists") or {}).items():
        if isinstance(entry, dict):
            kinds = [str(g) for g in entry.get("genres") or [] if isinstance(g, str)][:KEPT]
            moods = [str(m) for m in entry.get("moods") or [] if isinstance(m, str)][:2]
            if kinds or moods:
                found[name] = {"genres": kinds, "moods": moods}
    return found


def asked(vault: Path) -> int:
    """How many artists' names have been looked up, found or not: for the privacy screen."""
    kept = _json(path(vault))
    return sum(
        len(kept.get(k) or {}) for k in ("artists", "unknown") if isinstance(kept.get(k), dict)
    )


def look_up(
    vault: Path,
    played: dict[str, float],
    limit: int = LOOK_UP,
    now: datetime | None = None,
    fetch: Fetch | None = None,
    wait: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Look up to `limit` artists not asked about yet, the most played first, one name a
    request. Counts of what it did."""
    if not on():
        return {"musicbrainz off": 1}
    now = now or datetime.now(UTC)
    kept = _json(path(vault))
    artists = kept.get("artists") if isinstance(kept.get("artists"), dict) else {}
    unknown = kept.get("unknown") if isinstance(kept.get("unknown"), dict) else {}
    listed = kept.get("genre_list") if isinstance(kept.get("genre_list"), dict) else {}
    retry = _iso(now - timedelta(days=RETRY_DAYS))
    due = [
        name
        for name, _ in sorted(played.items(), key=lambda p: (-p[1], p[0]))
        if name.strip() and name not in artists and str(unknown.get(name) or "") < retry
    ][: max(limit, 0)]
    stats = {"artists looked up": 0}
    if not due:
        return stats
    paced = _Pacer(wait)
    fetch = fetch or _fetch  # looked up now, so a test can stand in for the network
    try:
        if str(listed.get("at") or "") < _iso(now - timedelta(days=GENRE_DAYS)):
            names = _genre_list(fetch, paced)
            listed = {"at": _iso(now), "names": names}
        known = {str(g).casefold() for g in listed.get("names") or []}
        for name in due:
            entry = _artist(name, known, fetch, paced)
            if entry:
                artists[name] = entry | {"at": _iso(now)}
                unknown.pop(name, None)
            else:
                unknown[name] = _iso(now)
            stats["artists looked up"] += 1
    except (urllib.error.URLError, OSError, ValueError) as e:
        stats["musicbrainz stopped"] = 1
        print(f"rhythms: MusicBrainz stopped for tonight ({' '.join(str(e).split())[:200]})")
    finally:
        if listed:
            _save(
                path(vault),
                {"genre_list": listed, "artists": artists, "unknown": unknown},
            )
    return stats


class _Pacer:
    """Holds each request until PACE seconds after the one before."""

    def __init__(self, wait: Callable[[float], None]) -> None:
        self.wait, self.last = wait, None

    def __call__(self) -> None:
        if self.last is not None:
            left = PACE - (time.monotonic() - self.last)
            if left > 0:
                self.wait(left)
        self.last = time.monotonic()


def request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})


def _genre_list(fetch: Fetch, paced: _Pacer) -> list[str]:
    """Every genre MusicBrainz knows, by name."""
    paced()
    text = fetch(request(f"{API}/genre/all?fmt=txt")).decode("utf-8", "replace")
    names = [line.strip() for line in text.splitlines() if line.strip()]
    if not names:
        raise ValueError("MusicBrainz sent an empty genre list")
    return names


def query(name: str) -> str:
    """The search for one artist by name, as a phrase: the name is all that goes."""
    phrase = name.replace("\\", "\\\\").replace('"', '\\"')
    params = {"query": f'artist:"{phrase}"', "limit": "5", "fmt": "json"}
    return f"{API}/artist?{urllib.parse.urlencode(params)}"


def _artist(name: str, known: set[str], fetch: Fetch, paced: _Pacer) -> dict | None:
    paced()
    found = json.loads(fetch(request(query(name))))
    return match(name, found, known)


def match(name: str, found: object, known: set[str]) -> dict | None:
    """The genres and moods of the best result named `name`, or None when there's none, or it
    has neither."""
    want = _fold(name)
    best = None
    for item in found.get("artists") or [] if isinstance(found, dict) else []:
        if not isinstance(item, dict):
            continue
        names = {_fold(item.get("name"))} | {
            _fold(a.get("name")) for a in item.get("aliases") or [] if isinstance(a, dict)
        }
        try:
            score = int(item.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if want not in names or score < MIN_SCORE:
            continue
        tags = [t for t in item.get("tags") or [] if isinstance(t, dict) and t.get("name")]
        votes = sum(_count(t) for t in tags)
        if best is None or (score, votes) > best[0]:
            best = ((score, votes), item, tags)
    if best is None:
        return None
    _, item, tags = best
    ranked = sorted(tags, key=lambda t: (-_count(t), _fold(t["name"])))
    kinds = [_fold(t["name"]) for t in ranked if _fold(t["name"]) in known and _count(t) > 0]
    moods = list(
        dict.fromkeys(MOOD_TAGS[k] for t in ranked if (k := _fold(t["name"])) in MOOD_TAGS)
    )
    if not kinds and not moods:
        return None
    return {"id": str(item.get("id") or ""), "genres": kinds[:KEPT], "moods": moods[:2]}


def _count(tag: dict) -> int:
    try:
        return int(tag.get("count") or 0)
    except (TypeError, ValueError):
        return 0


def _fold(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _save(at: Path, data: dict) -> None:
    folder = at.parent
    for parent in reversed([folder, *folder.parents]):
        if not parent.exists() and parent.parent.exists():
            parent.mkdir(mode=0o700)
    work._write(at, json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def _json(at: Path) -> dict:
    try:
        found = json.loads(at.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
