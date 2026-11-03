"""A card for each month: how you felt, what you listened to, how much you wrote, and how your
mood and your music moved together. The rhythms clone's weeks count; this reads a month whole.

For each local month, on this computer:

- mood, from the user's own writing a day at a time (proxenos.mood): the messages they sent on
  the channels with people (rhythms.CHANNELS), read from the memory index's rows marked as
  theirs, and the mail they sent, of which only what they wrote (body_new), never what they
  quoted or forwarded. Other people's messages are never read for it. Each day's valence comes
  with no model, its emotions from a model on this computer only.
- music, from Spotify's month files: each day's hours, and the month's top artists, genres and
  moods from the artists' labels (clones/rhythms/artists.json, the model's, from names) and
  kinds of music from MusicBrainz (proxenos.musicbrainz), each by the hours behind it.
- writing: the words the user wrote by channel, the notes they wrote, and the documents they
  changed, beside their usual month: the median of the USUAL months before that hold any.
- relations: each day's valence beside its music, as Pearson's r, with the days it rests on and
  how often chance alone would give one as strong (Fisher's z), on the same day and a day apart
  (music then mood, mood then music), and on days with and without each of the month's top
  genres, kinds and artists. Each is said in a sentence that never says which led.
- story: a short paragraph in the second person, written by the local model from the card's
  numbers and names only, never anyone's words; with a hosted model or none, written here from
  the same numbers.

A card is clones/rhythms/months/YYYY-MM.json: numbers, labels and artists' names, each day's
words only as a hash. Its basis is the time and size of each file it read: the night (`night`)
makes a card again only when one of them changed, or, while under COVERED of its music is
labelled, when the labels did, or when it waits on a model that's now on this computer. It
makes this month's, last month's until one is made after it ended, then up to BACKFILL older
months, newest first. A day's emotions and the story are asked for again only when the day's
words, or the numbers the story is written from, changed. state/rhythms.json says how far it got.
"""

import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import llm, memory, mood, musicbrainz
from proxenos.clones import rhythms

VERSION = 1  # bump when what a card holds changes: every card is made again
BACKFILL = 6  # older months a night makes, newest first
USUAL = 12  # months before one that its usual month is the median of
COVERED = 0.95  # the share of music labelled past which new labels don't remake a card
RETRY_DAYS = 3  # a card whose model step failed waits this long to be tried again
MIN_DAYS = 10  # days a correlation needs to count
MIN_SIDE = 4  # days with, and without, a kind of music, to compare them
MIN_PAIRS = 5  # days a correlation needs to be worked out at all
NOTABLE = 0.3  # |r| from which a relation is worth a line: a moderate link or more
KIND_MS = 15 * 60_000  # a day "with" a kind of music: this much of it
MOOD_MS = 10 * 60_000  # music with moods a day needs before its shares count
STORY_CHARS = 1200
TOP = 5
NOTES = ("notes", "keep")  # the notes the user wrote
PROSE = {"docx", "doc", "odt", "rtf", "md", "txt", "pages"}  # documents written, not read
LIFTING = {"upbeat", "energetic"}
SAD = {"melancholic"}

_WORD = re.compile(r"\w+")
_SOURCES = ("email", "spotify", *NOTES, "drive")  # read from their own month files

_SYSTEM = """\
You write a short card for one month of someone's life, from numbers and names only. Write one \
paragraph of three to five sentences, in the second person ("you"), warm and plain: how the \
month felt in their own writing (its top moods, its brightest and hardest weeks), what they \
listened to, how much they wrote, and at most two of the relations given, as carefully as they \
are given. Rules:
- Use only what's given: no events, people, places, reasons or numbers of your own.
- A relation is never a cause: never say the music changed their mood, or the other way round.
- No advice and no praise. Don't start with the month's name."""

_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}

# Each measure of music a day is compared by, and where a day holds it.
_FIELD = {"hours": "music_hours", "upbeat": "upbeat", "melancholic": "melancholic"}
# How each measure is said in a relation's sentence, high and low.
_SAID = {
    "valence": ("your writing was brighter", "your writing was heavier"),
    "hours": ("you listened to more music", "you listened to less music"),
    "upbeat": ("more of your music was upbeat", "less of your music was upbeat"),
    "melancholic": ("more of your music was melancholic", "less of your music was melancholic"),
}


# What a month is made from


def inputs(vault: Path) -> dict[str, list[list]]:
    """The files cards are made from, by the month in their name: the chat month files the
    memory index read, with the time and size it read them at, and the email, Spotify, notes and
    Drive month files, with theirs. [[path, mtime_ns, size]]"""
    found: dict[str, list[list]] = {}
    index = memory.index_path(vault)
    if index.exists():
        with closing(memory._connect(index)) as db:
            rows = db.execute("SELECT path, mtime_ns, size FROM files").fetchall()
        for row in rows:
            rel = row["path"]
            if rhythms._is_chat(rel) and not rel.startswith("email/"):
                name = rel.rsplit("/", 1)[-1]
                if rhythms._MONTH_FILE.fullmatch(name):
                    found.setdefault(name[:7], []).append([rel, row["mtime_ns"], row["size"]])
    root = vault / "raw"
    for source in _SOURCES:
        for path in sorted((root / source).glob("**/*.jsonl")):
            if rhythms._MONTH_FILE.fullmatch(path.name):
                info = path.stat()
                rel = path.relative_to(root).as_posix()
                found.setdefault(path.name[:7], []).append([rel, info.st_mtime_ns, info.st_size])
    return found


def basis(files: dict[str, list[list]], month: str) -> str:
    """A hash of the files a month is read from (its own and its neighbours', since a local day
    can sit in either), with the time zone and VERSION: a card is made again when it changes."""
    near = [files.get(m) or [] for m in (_shift(month, -1), month, _shift(month, 1))]
    held = sorted(tuple(f) for part in near for f in part)
    return _hash(json.dumps([VERSION, "/".join(time.tzname), held]))


def _labels_basis(vault: Path) -> str:
    """When the artists' labels last changed: the model's and MusicBrainz's files."""
    stamps = []
    for at in (rhythms._labels_path(vault), musicbrainz.path(vault)):
        try:
            info = at.stat()
            stamps.append([info.st_mtime_ns, info.st_size])
        except OSError:
            stamps.append(None)
    return _hash(json.dumps(stamps))


def held(files: dict[str, list[list]], this: str) -> list[str]:
    """The months with messages, mail or plays, up to this one, newest first."""
    found = set()
    for month, part in files.items():
        if month <= this and any(
            f[0].split("/")[0] in (*rhythms.CHANNELS, "spotify") for f in part
        ):
            found.add(month)
    return sorted(found, reverse=True)


def own_writing(vault: Path, month: str) -> dict[str, list[tuple[str, str]]]:
    """What the user wrote each local day of a month, [(channel, text)]: their own messages on
    the channels with people, from the memory index's rows marked as theirs, and what they wrote
    in the mail they sent. Never anyone else's words."""
    found: dict[str, list[tuple[str, str]]] = {}
    near = {_shift(month, -1), month, _shift(month, 1)}
    index = memory.index_path(vault)
    if index.exists():
        chats = [s for s in rhythms.CHANNELS if s != "email"]
        with closing(memory._connect(index)) as db:
            files = [
                r["path"]
                for r in db.execute("SELECT path FROM files").fetchall()
                if rhythms._is_chat(r["path"])
                and r["path"].rsplit("/", 1)[-1][:7] in near
                and not r["path"].startswith("email/")
            ]
            if files:
                rows = db.execute(
                    "SELECT source, date(ts, 'localtime') AS day, text FROM records "
                    f"WHERE file IN ({','.join('?' * len(files))}) AND from_me = 1 "
                    f"AND source IN ({','.join('?' * len(chats))}) ORDER BY ts",
                    [*files, *chats],
                ).fetchall()
                for row in rows:
                    if str(row["day"] or "").startswith(month) and (row["text"] or "").strip():
                        found.setdefault(row["day"], []).append(
                            (rhythms.CHANNELS[row["source"]], row["text"])
                        )
    for path in _month_files(vault, "email", near):
        for r in rhythms._jsonl(path):
            text = r.get("body_new")  # what they wrote, not what they quoted or forwarded
            if r.get("from_me") is not True or not isinstance(text, str) or not text.strip():
                continue
            if (when := _day_of(r.get("ts"))) and when.startswith(month):
                found.setdefault(when, []).append((rhythms.CHANNELS["email"], text))
    return found


def written(vault: Path, month: str, own: dict[str, list[tuple[str, str]]] | None = None) -> dict:
    """The words the user wrote in a month: in messages and mail by channel, in the notes they
    wrote, and in the documents they changed (counted apart, since a document changed holds far
    more than what was written that month)."""
    own = own_writing(vault, month) if own is None else own
    channels: dict[str, list[int]] = {}
    for said in own.values():
        for channel, text in said:
            words, pieces = channels.setdefault(channel, [0, 0])
            channels[channel] = [words + len(_WORD.findall(text)), pieces + 1]
    near = {_shift(month, -1), month, _shift(month, 1)}
    notes = [0, 0]
    for source in NOTES:
        for path in _month_files(vault, source, near):
            if path.parent.name == "tasks":
                continue
            for r in rhythms._jsonl(path):
                when = _day_of(r.get("ts"))
                if r.get("from_me") is not False and when and when.startswith(month):
                    notes = [notes[0] + 1, notes[1] + len(_WORD.findall(str(r.get("text") or "")))]
    documents = [0, 0]
    for path in _month_files(vault, "drive", near):
        for r in rhythms._jsonl(path):
            when = _day_of(r.get("ts"))
            if str(r.get("ext") or "").casefold() in PROSE and when and when.startswith(month):
                words = r.get("words")
                n = (
                    words
                    if isinstance(words, int)
                    else len(_WORD.findall(str(r.get("text") or "")))
                )
                documents = [documents[0] + 1, documents[1] + n]
    by = sorted(channels.items(), key=lambda c: -c[1][0])
    return {
        "words": sum(w for w, _ in channels.values()) + notes[1],
        "channels": [{"name": c, "words": w, "pieces": n} for c, (w, n) in by],
        "notes": {"count": notes[0], "words": notes[1]},
        "documents": {"count": documents[0], "words": documents[1]},
    }


def usual(vault: Path, month: str, files: dict[str, list[list]]) -> int | None:
    """The user's usual month of writing before this one: the median words of the USUAL months
    before it that hold any, once there are three. Each month's words are kept in
    clones/rhythms/words.json with its basis, and counted again only when that changes."""
    at = vault / "clones" / "rhythms" / "words.json"
    kept = rhythms._json(at)
    months = kept.get("months") if isinstance(kept.get("months"), dict) else {}
    found, changed = [], False
    before = [m for m in sorted(files, reverse=True) if m < month][:USUAL]
    for m in before:
        stamp = basis(files, m)
        entry = months.get(m)
        if not isinstance(entry, dict) or entry.get("basis") != stamp:
            entry = {"basis": stamp, "words": written(vault, m)["words"]}
            months[m] = entry
            changed = True
        if entry["words"] > 0:
            found.append(entry["words"])
    if changed:
        rhythms._save(at, {"months": months})
    return round(statistics.median(found)) if len(found) >= 3 else None


def music(vault: Path, month: str) -> dict[str, dict]:
    """Each local day's listening in a month: all the time played, the music's, plays of 30
    seconds or more, and each artist's time. Not what was played in a private session."""
    days: dict[str, dict] = {}
    near = {_shift(month, -1), month, _shift(month, 1)}
    for path in _month_files(vault, "spotify", near):
        for r in rhythms._jsonl(path):
            ms = rhythms._num(r.get("ms_played"))
            when = _day_of(r.get("ts"))
            if ms <= 0 or r.get("incognito") or not when or not when.startswith(month):
                continue
            d = days.setdefault(when, {"ms": 0, "music": 0, "plays": 0, "artists": Counter()})
            d["ms"] += int(ms)
            d["plays"] += ms >= rhythms.PLAYED_MS
            if r.get("kind") == "track":
                d["music"] += int(ms)
                if name := rhythms._one_line(r.get("artist")):
                    d["artists"][name] += int(ms)
    return days


# Making a card


def make(
    vault: Path,
    month: str,
    now: datetime | None = None,
    files: dict | None = None,
    label: Callable[[dict[str, list[str]]], dict[str, list[str]]] | None = None,
) -> dict:
    """A month's card, kept in clones/rhythms/months/. The emotions of a day whose words haven't
    changed, and a story whose numbers haven't, are kept from the card before; the rest are asked
    of the model on this computer, if there is one. `label` names the days' emotions in its place
    (the demo's are made up)."""
    now = now or datetime.now(UTC)
    files = inputs(vault) if files is None else files
    before = card(vault, month) or {}
    this = f"{now.astimezone():%Y-%m}"
    today = now.astimezone().date()
    own = own_writing(vault, month)
    played = music(vault, month)
    named, kinds = rhythms.labels(vault), musicbrainz.genres(vault)

    # Each day's mood: valence here, emotions from the local model where its words changed.
    was = {d["day"]: d for d in before.get("days") or [] if isinstance(d, dict) and "day" in d}
    days, ask = [], {}
    for when in _days(month, today):
        texts = [text for _, text in own.get(when, [])]
        scored = mood.day(texts)
        stamp = mood.digest(texts) if texts else None
        old = was.get(when) or {}
        same = stamp is not None and old.get("hash") == stamp and old.get("labelled")
        d = {"day": when, **scored, "words": sum(len(_WORD.findall(t)) for t in texts)}
        d |= {"hash": stamp, "emotions": (old.get("emotions") or []) if same else []}
        d["labelled"] = bool(same)
        if scored["valence"] is not None and not same:
            ask[when] = texts
        days.append(d)
    waits, failed = False, None
    label = label or (mood.label if mood.local() else None)
    if ask and label:
        try:
            labelled = label(ask)
            for d in days:
                if d["day"] in ask:
                    d["emotions"], d["labelled"] = labelled.get(d["day"], []), True
        except (llm.ModelError, ValueError) as e:
            waits, failed = True, _iso(now)
            print(f"rhythms: no emotions for {month} ({' '.join(str(e).split())[:200]})")
    elif ask:
        waits = True

    heard = _heard(played, named, kinds, days)
    found = {
        "version": VERSION,
        "month": month,
        "generated": _iso(now),
        "complete": month < this,
        "basis": basis(files, month),
        "labels": _labels_basis(vault),
        "mood": mood.roll_up(days) | {"by_model": any(d["emotions"] for d in days)},
        "music": heard,
        "writing": written(vault, month, own),
        "days": days,
    }
    found["writing"]["usual"] = typical = usual(vault, month, files)
    if typical and not found["complete"]:  # a month so far, beside the same share of a usual one
        whole = (date.fromisoformat(f"{_shift(month, 1)}-01") - timedelta(days=1)).day
        found["writing"]["usual_by_now"] = round(typical * len(days) / whole)
    found["writing"]["beside_usual"] = _beside_usual(found["writing"])
    found["mood"]["usual_sd"] = _usual_sd(vault, month)
    found["relations"] = relations(days, heard)

    facts = _facts(found)
    digest = _hash(json.dumps(facts, sort_keys=True))
    story = before.get("story") if isinstance(before.get("story"), dict) else {}
    if story.get("digest") != digest or (story.get("by") != "model" and mood.local()):
        story = {"by": "numbers", "digest": digest, "text": plain_story(found)}
        if mood.local():
            try:
                story = {"by": "model", "digest": digest, "text": _write(facts)}
            except (llm.ModelError, ValueError) as e:
                waits, failed = True, failed or _iso(now)
                print(f"rhythms: no story for {month} ({' '.join(str(e).split())[:200]})")
        else:
            waits = True
    found["story"] = story
    found["waits_on_model"] = waits
    if failed:
        found["failed"] = failed
    rhythms._save(_card_path(vault, month), found)
    return found


def _days(month: str, today: date) -> list[str]:
    """The days of a month, up to today."""
    first = date.fromisoformat(f"{month}-01")
    found = []
    while first.strftime("%Y-%m") == month and first <= today:
        found.append(first.isoformat())
        first += timedelta(days=1)
    return found


def _heard(played: dict[str, dict], named: dict, kinds: dict, days: list[dict]) -> dict:
    """The month's music, and each day's beside its mood: hours, and the shares of music with
    upbeat and with melancholic moods, where enough of it has moods."""
    artists: Counter = Counter()
    genres: Counter = Counter()
    sorts: Counter = Counter()
    moods: Counter = Counter()
    music_ms = covered = 0
    for p in played.values():
        artists.update(p["artists"])
        music_ms += p["music"]
    for name, ms in artists.items():
        label, found = named.get(name), kinds.get(name)
        if label:
            genres[label["genre"]] += ms
        if found and found["genres"]:
            sorts[found["genres"][0]] += ms
        felt = _moods(name, named, kinds)
        for m in felt:
            moods[m] += ms / len(felt)
        covered += ms if label or found else 0
    shares = {
        "genres": _share(genres),
        "kinds": _share(sorts),
        "moods": _share(moods),
    }
    by_day = {d["day"]: d for d in days}
    for when, d in by_day.items():
        p = played.get(when) or {"ms": 0, "music": 0, "artists": Counter()}
        d["music_hours"] = rhythms._hours(p["music"])
        d["hours"] = rhythms._hours(p["ms"])
        felt = {n: _moods(n, named, kinds) for n in p["artists"]}
        with_moods = sum(ms for n, ms in p["artists"].items() if felt[n])
        for key, kinds_of in (("upbeat", LIFTING), ("melancholic", SAD)):
            part = sum(
                ms * len(set(felt[n]) & kinds_of) / len(felt[n])
                for n, ms in p["artists"].items()
                if felt[n]
            )
            d[key] = round(part / with_moods, 3) if with_moods >= MOOD_MS else None
        d["played"] = {}  # the minutes of each of the month's top genres, kinds and artists
    tops = _tops(shares, artists)
    for when, d in by_day.items():
        p = played.get(when) or {"artists": Counter()}
        for kind, name in tops:
            ms = sum(
                ms
                for n, ms in p["artists"].items()
                if (kind == "artist" and n == name)
                or (kind == "genre" and (named.get(n) or {}).get("genre") == name)
                or (kind == "kind" and ((kinds.get(n) or {}).get("genres") or [None])[0] == name)
            )
            if ms:
                d["played"][f"{kind}:{name}"] = round(ms / 60_000)
    total = sum(p["ms"] for p in played.values())
    return {
        "hours": rhythms._hours(total),
        "music_hours": rhythms._hours(music_ms),
        "spoken_hours": rhythms._hours(total - music_ms),
        "plays": sum(p["plays"] for p in played.values()),
        "artists": len(artists),
        "top_artists": [
            {"name": n, "hours": rhythms._hours(ms)} for n, ms in artists.most_common(TOP)
        ],
        **shares,
        "labelled": round(covered / music_ms, 3) if music_ms else 0,
        "compared": [{"kind": kind, "name": name} for kind, name in tops],
    }


def _moods(name: str, named: dict, kinds: dict) -> list[str]:
    """An artist's moods: the model's label, else MusicBrainz's tags."""
    return list((named.get(name) or {}).get("moods") or (kinds.get(name) or {}).get("moods") or [])


def _share(by: Counter) -> list[dict]:
    """The top labels by hours, each with its share of the hours labelled."""
    total = sum(by.values())
    return [
        {"name": n, "hours": rhythms._hours(ms), "share": round(ms / total, 3)}
        for n, ms in by.most_common(TOP)
        if total and rhythms._hours(ms) > 0
    ]


def _tops(shares: dict, artists: Counter) -> list[tuple[str, str]]:
    """What the days are compared by: the month's top two genres, kinds and artists."""
    found = [("genre", g["name"]) for g in shares["genres"][:2]]
    found += [("kind", k["name"]) for k in shares["kinds"][:2]]
    found += [("artist", n) for n, _ in artists.most_common(2)]
    return found


def _usual_sd(vault: Path, month: str) -> float | None:
    """How much daily mood usually varies: the median spread of the cards before this one."""
    spreads = []
    for m, c in sorted(cards(vault).items(), reverse=True):
        sd = ((c.get("mood") or {}).get("variability") or {}).get("sd")
        if m < month and isinstance(sd, int | float):
            spreads.append(sd)
        if len(spreads) >= USUAL:
            break
    return round(statistics.median(spreads), 3) if len(spreads) >= 3 else None


# How mood and music moved together


def correlate(xs: list[float], ys: list[float]) -> dict | None:
    """Pearson's r, the pairs it rests on, and how often chance alone would give one at least
    as strong (two-sided, by Fisher's z); None with fewer than three pairs or no spread."""
    n = len(xs)
    if n < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    r = statistics.correlation(xs, ys)
    p = None
    if n > 3:
        z = math.atanh(max(-0.999999, min(0.999999, r))) * math.sqrt(n - 3)
        p = math.erfc(abs(z) / math.sqrt(2))
    return {"r": round(r, 3), "n": n, "p": None if p is None else round(p, 3)}


def relations(days: list[dict], heard: dict) -> list[dict]:
    """Each relation between the days' mood and their music, strongest evidence first, with a
    sentence for each and whether it's notable: MIN_DAYS or more, and |r| of NOTABLE or more."""
    valued = [d for d in days if d.get("valence") is not None]
    by_day = {d["day"]: d for d in days}
    found = []
    for measure, key in _FIELD.items():
        same = [(d[key], d["valence"]) for d in valued if d.get(key) is not None]
        then = [
            (d[key], nxt["valence"])
            for d in days
            if d.get(key) is not None
            and (nxt := by_day.get(_next(d["day"])))
            and nxt.get("valence") is not None
        ]
        after = [
            (d["valence"], nxt[key])
            for d in valued
            if (nxt := by_day.get(_next(d["day"]))) and nxt.get(key) is not None
        ]
        for kind, pairs in (
            ("same day", same),
            ("music then mood", then),
            ("mood then music", after),
        ):
            if len(pairs) >= MIN_PAIRS and (c := correlate(*map(list, zip(*pairs)))):
                found.append({"kind": kind, "music": measure, **c})
    split = set()  # the days each comparison splits, so an artist that's all of a genre is one
    for compared in heard.get("compared") or []:
        key = f"{compared['kind']}:{compared['name']}"
        for lag in (0, 1):
            rows = []
            for d in days:
                at = by_day.get(_next(d["day"])) if lag else d
                if at and at.get("valence") is not None:
                    rows.append((d["played"].get(key, 0) * 60_000 >= KIND_MS, at["valence"]))
            on = [v for played, v in rows if played]
            off = [v for played, v in rows if not played]
            days_on = (lag, tuple(played for played, _ in rows))
            if len(on) < MIN_SIDE or len(off) < MIN_SIDE or days_on in split:
                continue
            split.add(days_on)
            c = correlate([float(p) for p, _ in rows], [v for _, v in rows])
            if c:
                found.append(
                    {
                        "kind": "next day with" if lag else "with",
                        "music": compared["name"],
                        "of": compared["kind"],
                        "with": round(statistics.fmean(on), 3),
                        "without": round(statistics.fmean(off), 3),
                        "days_with": len(on),
                        "days_without": len(off),
                        **c,
                    }
                )
    for rel in found:
        rel["notable"] = _notable(rel)
        rel["text"] = sentence(rel)
    return sorted(found, key=lambda r: (not r["notable"], r["p"] if r["p"] is not None else 1))


def _notable(rel: dict) -> bool:
    if abs(rel["r"]) < NOTABLE:
        return False
    return rel["kind"] in ("with", "next day with") or rel["n"] >= MIN_DAYS


def sentence(rel: dict) -> str:
    """A relation in plain words: which way it went, r and the days, how strong, and that it
    doesn't say which led; "it could be chance" where chance alone would give one this strong
    one time in twenty or more."""
    r, n = rel["r"], rel["n"]
    up = r > 0
    size = abs(r)
    strength = (
        "no real link"
        if size < 0.1
        else "a weak link"
        if size < 0.3
        else "a moderate link"
        if size < 0.5
        else "a strong link"
    )
    stat = f"r = {_signed(r)}"
    chance = (
        " With this few days, it could be chance." if rel["p"] is None or rel["p"] >= 0.05 else ""
    )
    if rel["kind"] in ("with", "next day with"):
        what = rel["music"]
        brighter = rel["with"] > rel["without"]
        how = "brighter" if brighter else "heavier"
        on = (
            f"On days you played {what} (15 minutes or more), your writing was {how} than on days "
            "you didn't"
            if rel["kind"] == "with"
            else f"The day after you played {what}, your writing was {how} than after days you "
            "didn't"
        )
        return (
            f"{on} ({_signed(rel['with'])} against {_signed(rel['without'])} on a scale of "
            f"−1 to 1; {rel['days_with']} days against {rel['days_without']}; {stat}, "
            f"{strength}). This doesn't say which led.{chance}"
        )
    music_high, music_low = _SAID[rel["music"]]
    mood_high, mood_low = _SAID["valence"]
    if rel["kind"] == "same day":
        text = f"On days {mood_high}, {music_high if up else music_low}"
        tail = "This doesn't say which led."
        span = f"{n} days"
    elif rel["kind"] == "music then mood":
        text = f"After days {music_high}, {mood_high if up else mood_low} the next day"
        tail = "A day apart fits the music shaping your mood, but doesn't show it."
        span = f"{n} pairs of days"
    else:
        text = f"After days {mood_high}, {music_high if up else music_low} the next day"
        tail = "A day apart fits your music following your mood, but doesn't show it."
        span = f"{n} pairs of days"
    return f"{text} ({stat}, {span}, {strength}). {tail}{chance}"


# The story


def _facts(c: dict) -> dict:
    """What the story is written from: the card's numbers and names, no one's words."""
    m, w, heard = c["mood"], c["writing"], c["music"]
    arc = m["arc"]
    return {
        "month": _named(c["month"]),
        "so_far": not c["complete"],
        "mood": {
            "days_with_a_mood": m["days"],
            "top_moods": [f"{t['name']} ({t['days']} days)" for t in m["top"]],
            "tone": m["tone"],
            "brightest_week": _week(arc["best"]),
            "hardest_week": _week(arc["hardest"]),
            "day_to_day": m["variability"]["word"],
        },
        "music": {
            "hours": heard["music_hours"],
            "podcasts_and_books_hours": heard["spoken_hours"],
            "top_artists": [a["name"] for a in heard["top_artists"][:3]],
            "genres": [g["name"] for g in heard["genres"][:3]],
            "kinds": [k["name"] for k in heard["kinds"][:3]],
            "moods": [x["name"] for x in heard["moods"][:3]],
        },
        "writing": {
            "words": w["words"],
            "usual_month": w["usual"],
            "more_or_less_than_usual": w["beside_usual"],  # 0.2: a fifth more; so far, if not over
            "most_on": [ch["name"] for ch in w["channels"][:2]],
        },
        "relations": [r["text"] for r in c["relations"] if r["notable"]][:2],
    }


def _write(facts: dict) -> str:
    """The story, by the model on this computer only."""
    if not mood.local():
        raise llm.ModelError("the story is written only by a model on this computer")
    answer = llm.ask(
        json.dumps(facts, ensure_ascii=False, indent=1),
        system=_SYSTEM,
        schema=_SCHEMA,
        effort="low",
        max_tokens=1500,
    )
    text = " ".join(str(answer.get("text") if isinstance(answer, dict) else "").split())
    if not text:
        raise ValueError("an empty story")
    return text[:STORY_CHARS]


def plain_story(c: dict) -> str:
    """The story written here from the card's numbers, with no model."""
    m, w, heard = c["mood"], c["writing"], c["music"]
    month = _named(c["month"]).split(" ")[0]
    lines = []
    tone = m["tone"]
    if m["top"]:
        names = [t["name"] for t in m["top"]]
        lines.append(f"In your own words, {month} felt mostly {_listed(names)}.")
    elif m["days"]:
        ran = (
            "mostly bright"
            if tone["brighter"] > tone["heavier"] + tone["mixed"]
            else "heavier more often than bright"
            if tone["heavier"] > tone["brighter"]
            else "mixed"
        )
        lines.append(
            f"In your own words, {month} ran {ran}: {tone['brighter']} brighter "
            f"{_plural(tone['brighter'], 'day')}, {tone['mixed']} mixed and {tone['heavier']} "
            "heavier."
        )
    else:
        lines.append(f"There's too little of your own writing in {month} to read its mood.")
    arc = m["arc"]
    if arc["best"] and arc["hardest"]:
        lines.append(
            f"It was brightest in {_week(arc['best'])} and hardest in {_week(arc['hardest'])}."
        )
    if heard["music_hours"]:
        genres = [g["name"] for g in heard["genres"][:2]] or [k["name"] for k in heard["kinds"][:2]]
        most = f", most of it {_listed(genres)}" if genres else ""
        who = f", {heard['top_artists'][0]['name']} above all" if heard["top_artists"] else ""
        lines.append(f"You listened to {_amount(heard['music_hours'])} hours of music{most}{who}.")
    if w["words"]:
        vs = ""
        if (change := _beside_usual(w)) is not None:
            by = " by this point" if w.get("usual_by_now") else ""
            vs = (
                f", about as much as in your usual month{by}"
                if abs(change) < 0.1
                else f", {round(abs(change) * 100)}% {'more' if change > 0 else 'less'} than in "
                f"your usual month{by}"
            )
        so_far = " so far" if not c["complete"] else ""
        lines.append(f"You wrote about {w['words']:,} words{so_far}{vs}.")
    notable = [r for r in c["relations"] if r["notable"]]
    if notable:
        lines.append(notable[0]["text"])
    elif m["days"] >= MIN_DAYS and heard["music_hours"]:
        lines.append("Your mood and your music didn't move together in a way these days show.")
    return " ".join(lines)


def _beside_usual(w: dict) -> float | None:
    """How much more (0.2) or less (-0.2) the user wrote than in their usual month, or than by
    this point in one for a month still going; None with no usual month."""
    usual_words = w.get("usual_by_now") or w.get("usual")
    return round(w["words"] / usual_words - 1, 2) if usual_words else None


# The cards


def card(vault: Path, month: str) -> dict | None:
    found = rhythms._json(_card_path(vault, month))
    return found if found.get("month") == month and found.get("version") == VERSION else None


def cards(vault: Path) -> dict[str, dict]:
    """Every card made, by month."""
    found = {}
    for at in sorted((vault / "clones" / "rhythms" / "months").glob("*.json")):
        if c := card(vault, at.stem):
            found[at.stem] = c
    return found


def shown(c: dict) -> dict:
    """A card as the page reads it: without the days' hashes or the story's."""
    days = [{k: v for k, v in d.items() if k not in ("hash", "labelled")} for d in c["days"]]
    story = {k: v for k, v in c["story"].items() if k != "digest"}
    hidden = ("basis", "labels", "version")
    return {k: v for k, v in c.items() if k not in hidden} | {"days": days, "story": story}


def night(vault: Path, now: datetime | None = None, backfill: int | None = BACKFILL) -> dict:
    """This month's card, last month's, then up to `backfill` older ones (every one, with None),
    newest first: each only where it has none, or new data, or waits on a model that's here now.
    Counts of what it did."""
    now = now or datetime.now(UTC)
    this = f"{now.astimezone():%Y-%m}"
    files = inputs(vault)
    made = cards(vault)
    labels_now = _labels_basis(vault)
    state_at = vault / "state" / "rhythms.json"
    state = rhythms._json(state_at)
    retry = _iso(now - timedelta(days=RETRY_DAYS))

    def due_again(month: str, c: dict) -> bool:
        """Whether a card is behind: its files changed, it was made before its month ended, its
        music had labels missing and the labels moved, or it waits on a model that's here."""
        return (
            c["basis"] != basis(files, month)
            or (month < this and not c["complete"])
            or (c["labels"] != labels_now and (c["music"]["labelled"] or 0) < COVERED)
            or (
                bool(c.get("waits_on_model"))
                and mood.local()
                and str(c.get("failed") or "") < retry
            )
        )

    due = [m for m in held(files, this) if m not in made or due_again(m, made[m])]
    recent = [m for m in due if m >= _shift(this, -1)]
    older = [m for m in due if m < _shift(this, -1)]
    todo = recent + (older if backfill is None else older[: max(backfill, 0)])
    for month in todo:
        make(vault, month, now, files)
    stats = {"month cards": len(todo), "months left": len(due) - len(todo)}
    rhythms._save(state_at, state | {"at": _iso(now), "made": todo, "left": stats["months left"]})
    return stats


# Small helpers


def _card_path(vault: Path, month: str) -> Path:
    return vault / "clones" / "rhythms" / "months" / f"{month}.json"


def _month_files(vault: Path, source: str, months: set[str]) -> list[Path]:
    return [
        p
        for p in sorted((vault / "raw" / source).glob("**/*.jsonl"))
        if rhythms._MONTH_FILE.fullmatch(p.name) and p.name[:7] in months
    ]


def _day_of(ts: object) -> str | None:
    """The local day a UTC time falls on; None for one that isn't a time."""
    if not isinstance(ts, str):
        return None
    try:
        return rhythms._local(ts).date().isoformat()
    except ValueError:
        return None


def _next(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _shift(month: str, by: int) -> str:
    year, number = divmod(int(month[:4]) * 12 + int(month[5:7]) - 1 + by, 12)
    return f"{year:04d}-{number + 1:02d}"


def _named(month: str) -> str:
    return f"{date.fromisoformat(f'{month}-01'):%B %Y}"


def _week(w: dict | None) -> str | None:
    """A week as the story names it, in a month whose year goes without saying: the week of
    Mar 9."""
    if not w:
        return None
    start = date.fromisoformat(w["start"])
    return f"the week of {start:%b} {start.day}"


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _plural(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def _amount(hours: float) -> str:
    return f"{hours:.1f}" if hours < 10 else f"{hours:,.0f}"


def _signed(v: float) -> str:
    return f"{v:.2f}".replace("-", "−")


def _hash(text: str) -> str:
    return hashlib.blake2b(text.encode(), digest_size=8).hexdigest()


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
