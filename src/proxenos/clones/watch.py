"""What to watch next: films and shows the user hasn't seen, picked from what they loved.

It runs once a week: the night job calls it every night, and a run within EVERY_DAYS of the last
one does nothing (`--force` runs anyway). A run has two steps.

The first, in code with no model, reads Letterboxd (proxenos.ingest.letterboxd): every film the
user has logged, from an export's watched, diary, ratings, reviews and likes and from the public
feed, matched by title and year, with their latest rating, whether they hearted it and when they
last watched it; and their watchlist. Letterboxd keeps films, so shows come from the page: the
picks the user marks seen, want or not for me teach the next run their taste in TV.

The second is one model call. It reads the self-model's taste and interests, the films they loved
(rated LOVED or more, or hearted), what they watched in the last RECENT_DAYS, what they rated
DISLIKED or less, every film they've seen (so none comes back), the marks on earlier picks and
their watchlist, and returns:
- films: up to FILMS films they haven't seen, best first, each with why it suits them and the
  films they've seen that it follows from;
- shows: up to SHOWS series, the same way;
- watchlist: up to QUEUE films from their own watchlist that suit this week.
Code then drops what they've seen (by title and year), what they marked seen or not for me before,
and repeats, and links each pick to a search on Letterboxd and on JustWatch, which says where it
streams. The links are built in code, so none is made up, but a model can still name a film that
doesn't exist or get a year wrong: the search shows that at a glance.

A run lands in clones/watch/<date>.json, and clones/watch/history.json keeps every pick given. The
page marks a pick want, seen or not_me in clones/watch/feedback.jsonl. Picks marked want stay on
the page until marked seen; later runs never bring back a pick marked seen or not_me, and the model
is told about all three. Only the user's own logs and marks reach the model: no one else's.
"""

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, quote_plus

from proxenos import llm
from proxenos.clones import choices
from proxenos.config import env

EVERY_DAYS = 7
FILMS = 8
SHOWS = 6
QUEUE = 3
EXTRA = 4  # picks asked for beyond each list's size, for the ones code drops
LOVED = 4.5  # a rating this high, or a heart, makes a film a favourite
DISLIKED = 2.0
FAVOURITES = 60  # the most recent favourites the model reads
RECENT_DAYS = 120
RECENT = 25
SELF_FILES = ("taste", "interests")
KINDS = ("film", "show")
ACTIONS = ("want", "seen", "not_me")
_CLOSED = ("seen", "not_me")
_STREAMS = ("watched", "diary", "ratings", "reviews", "likes", "feed")
LETTERBOXD_SEARCH = "https://letterboxd.com/search/films/{q}/"
JUSTWATCH_SEARCH = "https://www.justwatch.com/us/search?q={q}"

_SYSTEM = """\
You are {person}'s digital twin, picking what they should watch next. You get their taste from \
their self-model, the films they loved, what they watched lately and how they rated it, what \
they disliked, every film they've seen, how they marked earlier picks, and their watchlist. \
Return three short lists.

films: up to {films} films {person} hasn't seen, best first. shows: up to {shows} TV series \
(miniseries included) the same way. For each:
- title: its usual English title, exactly, and year: the year it came out (for a show, its first \
season).
- why: one or two sentences said to {person} as "you": what in it suits you, naming the films \
you loved that it follows from or what in your taste it answers.
- because: the [F..] films or [S..] shows below it follows from. At least one when any fits.

watchlist: up to {queue} films from their own watchlist, the [W..] items, that suit this week \
best, each with ref and a one-sentence why.

Rules:
- Only real films and shows you're sure of, with the right year. Never one they've seen, never \
one already on their watchlist in films, and never one they marked seen or not_me, reworded or \
not.
- Range: not only the obvious classic. Mix a few well known with ones they'd be unlikely to find \
alone (another country, an older decade, a smaller release), as long as each fits.
- Learn from their marks: more like what they wanted, less like what they passed on.
- Refer to them as {person} and don't assume pronouns."""


def watch(vault: Path, force: bool = False, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = vault / "clones" / "watch"
    if not force and (wait := choices.days_left(out, now)):
        return {"days_until_next_run": wait}
    seen = films_seen(vault)
    if not seen:
        raise SystemExit(
            "watch: no films logged yet. Import a Letterboxd export (`proxenos import`), or set "
            "PROXENOS_LETTERBOXD_USER to read your public diary feed."
        )
    queue = [f for f in _watchlist(vault) if f["key"] not in seen]
    history = choices._load_json(out / "history.json")
    marks = _marks(out / "feedback.jsonl")
    refs = _refs(seen, history, marks, queue, now)

    answer = llm.ask(
        prompt(vault, seen, refs, history, marks, now),
        system=_SYSTEM.format(
            person=env("NAME", "the person"), films=FILMS, shows=SHOWS, queue=QUEUE
        ),
        schema=_schema(list(refs), [r for r in refs if r.startswith("W")]),
    )
    result = _accept(answer, refs, seen, history, marks)
    day = f"{now.astimezone():%Y-%m-%d}"
    for item in result["films"] + result["shows"] + result["watchlist"]:
        history.setdefault(
            item["id"], {k: item[k] for k in ("kind", "title", "year")} | {"day": day}
        )
    choices._write_json(out / f"{day}.json", {"generated": choices._iso(now), **result})
    choices._write_json(out / "history.json", history)
    return {
        "films_seen": len(seen),
        "films": len(result["films"]),
        "shows": len(result["shows"]),
        "from_watchlist": len(result["watchlist"]),
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force", action="store_true", help=f"run even within {EVERY_DAYS} days of the last run"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return watch(vault, force=args.force)


def key(kind: str, title: object, year: object) -> str:
    """A pick's id: the same title and year get the same one every week."""
    text = f"{kind}\n{choices._fold(title)}\n{year or ''}"
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def films_seen(vault: Path) -> dict[str, dict]:
    """Every film the user has logged, by key: title, year, latest rating, heart, last watched."""
    root = vault / "raw" / "letterboxd"
    films: dict[str, dict] = {}
    for stream in _STREAMS:
        for path in sorted((root / stream).glob("*.jsonl")):
            for r in choices._lines(path):
                if not (title := str(r.get("title") or "").strip()):
                    continue
                year = r.get("year") if isinstance(r.get("year"), int) else None
                film = films.setdefault(
                    key("film", title, year),
                    {"title": title, "year": year, "rating": None, "rated": "", "liked": False},
                )
                ts = str(r.get("ts") or "")
                if isinstance(r.get("rating"), int | float) and ts >= film["rated"]:
                    film["rating"], film["rated"] = float(r["rating"]), ts
                film["liked"] |= stream == "likes" or r.get("liked") is True
                if stream in ("diary", "feed", "reviews"):
                    film["watched"] = max(film.get("watched", ""), ts)
    return films


def _watchlist(vault: Path) -> list[dict]:
    films = {}
    for path in sorted((vault / "raw" / "letterboxd" / "watchlist").glob("*.jsonl")):
        for r in choices._lines(path):
            if title := str(r.get("title") or "").strip():
                year = r.get("year") if isinstance(r.get("year"), int) else None
                k = key("film", title, year)
                films[k] = {"key": k, "title": title, "year": year, "url": r.get("url") or ""}
    return list(films.values())


def _marks(path: Path) -> dict[str, str]:
    """The user's latest mark on each pick from the page: {id: action}."""
    latest: dict[str, tuple[datetime, str]] = {}
    for event in choices._lines(path):
        pick, action = event.get("item_id"), event.get("action")
        when = choices._when(event.get("ts"))
        if action not in ACTIONS or when is None or not isinstance(pick, str):
            continue  # the page writes this file, and one bad line shouldn't stop a run
        if pick not in latest or when >= latest[pick][0]:
            latest[pick] = (when, action)
    return {pick: action for pick, (_, action) in latest.items()}


def _refs(
    seen: dict[str, dict],
    history: dict,
    marks: dict[str, str],
    queue: list[dict],
    now: datetime,
) -> dict[str, dict]:
    """What the model may cite, by tag: the films that show their taste, the shows they've
    marked, and their watchlist."""
    since = choices._iso(now - timedelta(days=RECENT_DAYS))
    recent = sorted(
        (f for f in seen.values() if f.get("watched", "") >= since),
        key=lambda f: f["watched"],
        reverse=True,
    )[:RECENT]
    loved = sorted(
        (f for f in seen.values() if f["liked"] or (f["rating"] or 0) >= LOVED),
        key=lambda f: f.get("watched") or f["rated"],
        reverse=True,
    )[:FAVOURITES]
    disliked = [f for f in seen.values() if f["rating"] is not None and f["rating"] <= DISLIKED]
    refs: dict[str, dict] = {}
    for film in {id(f): f for f in recent + loved + disliked}.values():
        refs[f"F{len(refs) + 1}"] = {"kind": "film", **film}
    shows = [(pick, h) for pick, h in history.items() if h.get("kind") == "show" and pick in marks]
    for n, (pick, show) in enumerate(shows, 1):
        refs[f"S{n}"] = show | {"mark": marks[pick]}
    for n, film in enumerate(queue, 1):
        refs[f"W{n}"] = {"kind": "watchlist", **film}
    return refs


def prompt(
    vault: Path,
    seen: dict[str, dict],
    refs: dict[str, dict],
    history: dict,
    marks: dict[str, str],
    now: datetime,
) -> str:
    taste = []
    for name in SELF_FILES:
        path = vault / "self" / f"{name}.md"
        if path.exists() and (text := path.read_text(encoding="utf-8").strip()):
            taste.append(f'<self file="{name}">\n{text}\n</self>')
    since = choices._iso(now - timedelta(days=RECENT_DAYS))
    groups = {
        "Watched lately, newest first": lambda r: r.get("watched", "") >= since,
        "Loved (rated 4.5 or more, or hearted)": lambda r: (
            r.get("liked") or (r.get("rating") or 0) >= LOVED
        ),
        "Disliked (rated 2 or less)": lambda r: (
            r.get("rating") is not None and r["rating"] <= DISLIKED
        ),
    }
    parts = taste
    for heading, belongs in groups.items():
        lines = [
            f"[{tag}] {_film(r)}" for tag, r in refs.items() if r["kind"] == "film" and belongs(r)
        ]
        parts.append(f"## {heading}\n" + ("\n".join(lines) or "(none)"))
    shows = [f"[{tag}] {_film(r)}: {r['mark']}" for tag, r in refs.items() if tag[0] == "S"]
    parts.append("## Shows they marked\n" + ("\n".join(shows) or "(none yet)"))
    picks = [
        f"- {h['kind']}: {_film(h)}: {marks[pick]}"
        for pick, h in history.items()
        if pick in marks and h.get("kind") == "film"
    ]
    parts.append("## Earlier film picks they marked\n" + ("\n".join(picks) or "(none yet)"))
    queue = [f"[{tag}] {_film(r)}" for tag, r in refs.items() if tag[0] == "W"]
    parts.append("## Their watchlist\n" + ("\n".join(queue) or "(empty)"))
    every = "; ".join(_name(f) for f in sorted(seen.values(), key=lambda f: f["title"]))
    parts.append(f"## Every film they've seen ({len(seen)}): suggest none of these\n{every}")
    return "\n\n".join(parts)


def _name(r: dict) -> str:
    return f"{r['title']} ({r['year']})" if r.get("year") else r["title"]


def _film(r: dict) -> str:
    text = _name(r)
    if r.get("rating") is not None:
        text += f", {r['rating']:g}/5"
    return text + (", hearted" if r.get("liked") else "")


def _schema(refs: list[str], queue: list[str]) -> dict:
    text = {"type": "string"}

    def tags(allowed: list[str]) -> dict:
        return {"type": "string", "enum": allowed} if allowed else text

    def picks(size: int, properties: dict) -> dict:
        return {
            "type": "array",
            "maxItems": size,
            "items": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        }

    because = {"type": "array", "items": tags([r for r in refs if r[0] in "FS"])}
    pick = {"title": text, "year": {"type": "integer"}, "why": text, "because": because}
    return {
        "type": "object",
        "properties": {
            "films": picks(FILMS + EXTRA, pick),
            "shows": picks(SHOWS + EXTRA, pick),
            "watchlist": picks(QUEUE, {"ref": tags(queue), "why": text}),
        },
        "required": ["films", "shows", "watchlist"],
        "additionalProperties": False,
    }


def _accept(
    answer: object,
    refs: dict[str, dict],
    seen: dict[str, dict],
    history: dict,
    marks: dict[str, str],
) -> dict[str, list[dict]]:
    """The model's picks that hold up: nothing seen, closed or repeated, at most each list's
    size, with links built here."""
    answer = answer if isinstance(answer, dict) else {}
    closed = {pick for pick, action in marks.items() if action in _CLOSED}
    closed_titles = {
        (h.get("kind"), choices._fold(h.get("title"))) for p, h in history.items() if p in closed
    }
    seen_years: dict[str, set] = {}
    for f in seen.values():
        seen_years.setdefault(choices._fold(f["title"]), set()).add(f["year"])
    queued = {choices._fold(r["title"]) for r in refs.values() if r["kind"] == "watchlist"}
    result: dict[str, list[dict]] = {"films": [], "shows": [], "watchlist": []}
    taken: set[str] = set()
    for kind, field, size in (("film", "films", FILMS), ("show", "shows", SHOWS)):
        for raw in answer.get(field) or []:
            if not isinstance(raw, dict) or len(result[field]) >= size:
                continue
            title = " ".join(str(raw.get("title") or "").split())
            year = raw.get("year") if isinstance(raw.get("year"), int) else None
            pick, folded = key(kind, title, year), choices._fold(title)
            if (
                not title
                or pick in taken
                or pick in closed
                or (kind, folded) in closed_titles
                or (kind == "film" and (folded in queued or _seen(seen_years, folded, year)))
            ):
                continue
            taken.add(pick)
            because = [refs[t] for t in raw.get("because") or [] if t in refs and t[0] in "FS"]
            result[field].append(
                {
                    "id": pick,
                    "kind": kind,
                    "title": title,
                    "year": year,
                    "why": " ".join(str(raw.get("why") or "").split()),
                    "because": [_film(r) for r in because][:4],
                    "links": _links(kind, title),
                }
            )
    for raw in answer.get("watchlist") or []:
        ref = raw.get("ref") if isinstance(raw, dict) else None
        film = refs.get(ref) if isinstance(ref, str) and ref.startswith("W") else None
        if not film or len(result["watchlist"]) >= QUEUE:
            continue
        pick = key("film", film["title"], film["year"])
        if pick in taken or pick in closed:
            continue
        taken.add(pick)
        links = _links("film", film["title"])
        if film["url"]:
            links = [{"label": "Letterboxd", "url": film["url"]}] + links[1:]
        result["watchlist"].append(
            {
                "id": pick,
                "kind": "film",
                "title": film["title"],
                "year": film["year"],
                "why": " ".join(str(raw.get("why") or "").split()),
                "because": [],
                "links": links,
            }
        )
    return result


def _seen(years: dict[str, set], title: str, year: int | None) -> bool:
    """Whether a film of this title is among those seen, within a year of this one (a model's
    year can be a release year where Letterboxd keeps another)."""
    if title not in years:
        return False
    known = years[title]
    return year is None or None in known or any(abs(year - y) <= 1 for y in known)


def _links(kind: str, title: str) -> list[dict]:
    where = {"label": "Where to watch", "url": JUSTWATCH_SEARCH.format(q=quote_plus(title))}
    if kind == "show":
        return [where]
    return [{"label": "Letterboxd", "url": LETTERBOXD_SEARCH.format(q=quote(title))}, where]
