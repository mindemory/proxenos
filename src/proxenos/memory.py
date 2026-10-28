"""Personal memory: a full-text index over everything in raw/, and search and context on it.

`proxenos index` reads every month file under vault/raw and writes vault/memory/index.sqlite (the
folder is 0700, the file 0600). It is derived data: delete it and `proxenos index --rebuild` makes
it again. Each record becomes one row with these columns:

- id: raw directory, then the record's own id, e.g. "whatsapp/messages/<id>". Unique.
- source, stream: the first directory under raw/, and the rest of the path ("acme-lab/messages").
- ts: when it happened, normalized to UTC "YYYY-MM-DDTHH:MM:SSZ".
- who: names of senders, chats, recipients, authors, attendees and people in it.
- where_: the chat, channel, collection, album or list it lives in, else the URL's host.
- title: subject, title or summary. text: its words, the same fields observe.py reads, cut to
  4,000 characters. from_me: 1, 0, or empty when a source doesn't say.

Records with no title and no words aren't indexed. Chrome is indexed as page title and host
only. Spotify and Strava aren't text, so each of their months becomes one summary row (top
artists, activity types and distances), enough for "running in March" to find something.

The table `mem` is FTS5 (unicode61, diacritics removed) over the content table `records`, which
also holds a `thread` key (chat, channel, mail thread, else source and day) and the month file a
row came from. Re-indexing is incremental: `files` remembers each month file's mtime and size,
and only changed files are read again, their old rows deleted first.

`search` takes plain text: words are ANDed, "double quotes" make a phrase, a trailing * makes the
last word a prefix. Everything is quoted before it reaches FTS5, so no input is ever read as
query syntax. `context` returns the records around one, read from the month files.
"""

import fcntl
import json
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from proxenos.config import vault_path
from proxenos.observe import _TEXT_FIELDS

SCHEMA = 3  # bump when the table layout or what gets indexed changes: the index is rebuilt
MAX_TEXT = 4000
MAX_WHO = 400  # characters of names kept on one row
MAX_NAMES = 30
SUMMARIZED = ("spotify", "strava")  # not text: one summary row per month instead
MARK_START, MARK_END = "\x02", "\x03"  # around matched words in a snippet; stripped from text
SNIPPET_TOKENS = 32
# Column weights for bm25, in the table's order: a hit in a title counts most, then in names.
WEIGHTS = (0.0, 0.0, 0.0, 0.0, 2.0, 1.0, 3.0, 1.0, 0.0)
MAX_TERMS = 16
MAX_TERM_CHARS = 64

_MONTH_FILE = re.compile(r"\d{4}-\d{2}\.jsonl")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANKS = re.compile(r"[ \t]+")
_WORD = re.compile(r"\w", re.UNICODE)
_TERM = re.compile(r'"([^"]*)"(\*?)|([^\s"]+)')
_REPLY = re.compile(r"^((re|fwd?|aw)\s*:\s*)+", re.IGNORECASE)

_TITLE_FIELDS = ("subject", "title", "summary", "name")
# Words kept only when nothing in observe's fields has any.
_EXTRA_TEXT = ("description", "notes", "abstract", "snippet", "entry", "body")
_WHO_FIELDS = (
    "sender_name",
    "user_name",
    "from_name",
    "to",
    "cc",
    "chat_name",
    "channel_name",
    "conversation_title",
    "author",
    "authors",
    "coauthors",
    "attendees",
    "guests",
    "people",
    "channel",
)
_WHERE_FIELDS = (
    "chat_name",
    "channel_name",
    "conversation_title",
    "collection",
    "album",
    "list",
    "labels",
    "location",
    "place",
    "venue",
)
_THREAD_FIELDS = ("chat_id", "channel_id", "conversation_id", "gmail_thread")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_SPORTS = {
    "run": "running run",
    "trailrun": "running trail run",
    "virtualrun": "running run treadmill",
    "ride": "cycling biking ride",
    "virtualride": "cycling biking ride",
    "mountainbikeride": "cycling biking mountain bike ride",
    "walk": "walking walk",
    "hike": "hiking hike",
    "swim": "swimming swim",
    "weighttraining": "weight training gym lifting",
    "yoga": "yoga",
    "rowing": "rowing",
    "elliptical": "elliptical",
}

_COLUMNS = "id, source, stream, ts, who, where_, title, text, from_me"
_RECORD_COLUMNS = f"{_COLUMNS}, thread, file"

_SCHEMA_SQL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE files (
    path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL, records INTEGER NOT NULL
);
CREATE TABLE records (
    id TEXT NOT NULL UNIQUE, source TEXT NOT NULL, stream TEXT NOT NULL, ts TEXT NOT NULL,
    who TEXT NOT NULL, where_ TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
    from_me INTEGER, thread TEXT NOT NULL, file TEXT NOT NULL
);
CREATE INDEX records_file ON records (file);
CREATE INDEX records_thread ON records (thread, ts);
CREATE INDEX records_source ON records (source);
CREATE VIRTUAL TABLE mem USING fts5(
    id UNINDEXED, source UNINDEXED, stream UNINDEXED, ts UNINDEXED,
    who, where_, title, text, from_me UNINDEXED,
    content='records', content_rowid='rowid', tokenize='unicode61 remove_diacritics 2'
);
"""


def index_path(vault: Path) -> Path:
    return vault / "memory" / "index.sqlite"


def exists(vault: Path) -> bool:
    return index_path(vault).exists()


# Building the index


def build(vault: Path, rebuild: bool = False) -> dict[str, int]:
    """Bring the index up to date with raw/: read month files that are new or changed since the
    last run, forget ones that are gone. With `rebuild`, start over. Another `proxenos index` already
    running makes this one a no-op that says so."""
    folder = vault / "memory"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    with _locked(folder) as free:
        if not free:
            return {"already_running": 1}
        final = index_path(vault)
        fresh = rebuild or not final.exists() or _stale(final)
        target = final.with_name(final.name + ".new") if fresh else final
        if fresh:
            _remove(target)
        else:
            target.chmod(0o600)
        stats = Counter(
            {"files_indexed": 0, "files_unchanged": 0, "files_removed": 0, "records_indexed": 0}
        )
        fd = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        with closing(_connect(target, write=True, bulk=fresh)) as db:
            if fresh:
                db.executescript(_SCHEMA_SQL)
                db.execute("INSERT INTO meta VALUES ('schema', ?)", (str(SCHEMA),))
            _sync_files(db, vault / "raw", stats)
            if fresh:
                db.execute("INSERT INTO mem(mem) VALUES ('optimize')")
            stats["records_total"] = db.execute("SELECT count(*) FROM records").fetchone()[0]
        if fresh:
            _remove(final, keep=True)  # a left-over journal must not be applied to the new file
            os.replace(target, final)
            final.chmod(0o600)
        return dict(stats)


@contextmanager
def _locked(folder: Path) -> Iterator[bool]:
    fd = os.open(folder / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def _remove(path: Path, keep: bool = False) -> None:
    """Delete a database file's side files, and the file itself unless `keep`."""
    for suffix in ("-journal", "-wal", "-shm", *(() if keep else ("",))):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _stale(path: Path) -> bool:
    """Whether an existing index is damaged or written by another version of this module."""
    try:
        with closing(_connect(path)) as db:
            row = db.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
    except sqlite3.Error:
        return True
    return row is None or row[0] != str(SCHEMA)


def _connect(path: Path, write: bool = False, bulk: bool = False) -> sqlite3.Connection:
    if write:
        db = sqlite3.connect(path, timeout=30, isolation_level=None)
    else:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=30)
        db.execute("PRAGMA query_only = ON")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA cache_size = -65536")
    if bulk:  # a new file is thrown away if the build fails, so it needn't survive a crash
        db.execute("PRAGMA journal_mode = OFF")
        db.execute("PRAGMA synchronous = OFF")
    return db


def _month_files(raw: Path) -> dict[str, Path]:
    """Every month file under raw/, by its path relative to raw/."""
    found = {}
    for path in raw.glob("**/*.jsonl"):
        if _MONTH_FILE.fullmatch(path.name) and path.parent != raw:
            found[path.relative_to(raw).as_posix()] = path
    return dict(sorted(found.items()))


def _sync_files(db: sqlite3.Connection, raw: Path, stats: Counter) -> None:
    known = {r["path"]: (r["mtime_ns"], r["size"]) for r in db.execute("SELECT * FROM files")}
    found = _month_files(raw)
    for rel in known.keys() - found.keys():
        db.execute("BEGIN")
        _forget(db, rel)
        db.execute("DELETE FROM files WHERE path = ?", (rel,))
        db.execute("COMMIT")
        stats["files_removed"] += 1
    for rel, path in found.items():
        info = path.stat()
        if known.get(rel) == (info.st_mtime_ns, info.st_size):
            stats["files_unchanged"] += 1
            continue
        rows = list(_read(rel, path))
        db.execute("BEGIN")
        _forget(db, rel)
        db.executemany(
            f"INSERT INTO records ({_RECORD_COLUMNS}) VALUES ({','.join('?' * 11)}) "
            "ON CONFLICT(id) DO NOTHING",
            rows,
        )
        db.execute(
            f"INSERT INTO mem(rowid, {_COLUMNS}) SELECT rowid, {_COLUMNS} FROM records "
            "WHERE file = ?",
            (rel,),
        )
        db.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
            (rel, info.st_mtime_ns, info.st_size, len(rows)),
        )
        db.execute("COMMIT")
        stats["files_indexed"] += 1
        stats["records_indexed"] += len(rows)


def _forget(db: sqlite3.Connection, rel: str) -> None:
    """Drop every row that came from one month file, from the full-text table first."""
    db.execute(
        f"INSERT INTO mem(mem, rowid, {_COLUMNS}) "
        f"SELECT 'delete', rowid, {_COLUMNS} FROM records WHERE file = ?",
        (rel,),
    )
    db.execute("DELETE FROM records WHERE file = ?", (rel,))


# Turning raw records into rows


def _read(rel: str, path: Path) -> Iterator[tuple]:
    """The rows of one month file, as (id, source, stream, ts, who, where_, title, text,
    from_me, thread, file)."""
    folder = rel.rsplit("/", 1)[0]
    source, _, stream = folder.partition("/")
    records = _load(path)
    if source in SUMMARIZED:
        row = _summary(source, folder, path.stem, records)
        if row:
            yield (*row[:9], _thread(folder, source, {}, row[3]), rel)
        return
    for record in records:
        row = _row(folder, source, stream, record)
        if row:
            yield (*row, _thread(folder, source, record, row[3]), rel)


def _load(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("id") is not None and record.get("ts"):
                records.append(record)
    return records


def _row(folder: str, source: str, stream: str, r: dict) -> tuple | None:
    ts = _stamp(str(r["ts"]))
    title = _first(r, _TITLE_FIELDS)
    if source == "chrome":
        host = _host(r.get("url"))
        return (
            (f"{folder}/{r['id']}", source, stream, ts, "", host, title, "", None)
            if title
            else None
        )
    text = next((t for f in _TEXT_FIELDS if (t := _clean(r.get(f))) and t != title), "")
    if not text:
        text = " ".join(t for f in _EXTRA_TEXT if (t := _clean(r.get(f))))
    if not text and source == "linkedin":
        text = " ".join(t for f in ("position", "company", "headline") if (t := _clean(r.get(f))))
    if not title and not text:
        return None
    who_fields = (*_WHO_FIELDS, "name") if source == "linkedin" else _WHO_FIELDS
    where = _names(r, _WHERE_FIELDS, 5)
    if not where and r.get("path"):
        where = os.path.dirname(str(r["path"]))
    where = where or _host(r.get("url"))
    from_me = r.get("from_me")
    return (
        f"{folder}/{r['id']}",
        source,
        stream,
        ts,
        _names(r, who_fields, MAX_NAMES)[:MAX_WHO],
        _clean(where)[:MAX_WHO],
        title[:500],
        text[:MAX_TEXT],
        None if from_me is None else int(bool(from_me)),
    )


def _summary(source: str, folder: str, month: str, records: list[dict]) -> tuple | None:
    """One row for a whole month of plays or activities."""
    if not records:
        return None
    label = f"{_MONTHS[int(month[5:7]) - 1]} {month[:4]}"
    if source == "spotify":
        plays = [r for r in records if r.get("ms_played") and not r.get("incognito")]
        if not plays:
            return None
        minutes: Counter = Counter()
        tracks: Counter = Counter()
        for r in plays:
            who = r.get("artist") if r.get("kind") == "track" else r.get("show")
            minutes[_clean(who) or "unknown"] += r["ms_played"] / 60000
            if r.get("kind") == "track" and r.get("track"):
                tracks[f"{_clean(r['track'])} by {_clean(r.get('artist'))}"] += 1
        hours = sum(minutes.values()) / 60
        text = (
            f"Spotify listening in {label}: {len(plays)} plays, {hours:.1f} hours. "
            f"Top artists and shows: {', '.join(f'{k} ({v:.0f} min)' for k, v in minutes.most_common(12))}. "
            f"Most played: {', '.join(k for k, _ in tracks.most_common(10))}."
        )
        title = f"Spotify listening, {label}"
    else:
        kinds: Counter = Counter()
        names: list[str] = []
        km = hours = 0.0
        for r in records:
            sport = str(r.get("sport_type") or "workout")
            kinds[_SPORTS.get(sport.lower(), sport.lower())] += 1
            km += (r.get("distance_m") or 0) / 1000
            hours += (r.get("moving_time_s") or 0) / 3600
            if r.get("name"):
                names.append(_clean(r["name"]))
        text = (
            f"Strava activities in {label}: {len(records)} activities, {km:.1f} km, "
            f"{hours:.1f} hours. {'; '.join(f'{k}: {v}' for k, v in kinds.most_common())}. "
            f"{'; '.join(names[:12])}."
        )
        title = f"Strava activities, {label}"
    ts = f"{month}-01T00:00:00Z"
    return (
        f"{folder}/{month}",
        source,
        folder.partition("/")[2],
        ts,
        "",
        "",
        title,
        text[:MAX_TEXT],
        1,
    )


def _thread(folder: str, source: str, r: dict, ts: str) -> str:
    """What a record's conversation is: its chat, channel or mail thread, else its source and
    day. Chats and threads are scoped to the stream, so two accounts never share one."""
    key = next((str(r[f]) for f in _THREAD_FIELDS if r.get(f)), "")
    if not key and source == "email":
        subject = _REPLY.sub("", _clean(r.get("subject"))).strip().casefold()
        key = f"subject:{subject}" if subject else ""
    return f"{folder}|{key}" if key else f"day:{source}|{ts[:10]}"


def _clean(value: object) -> str:
    if value is None or isinstance(value, bool | int | float | list | dict):
        return ""
    return _BLANKS.sub(" ", _CONTROL.sub(" ", str(value))).strip()


def _first(r: dict, fields: Iterable[str]) -> str:
    return next((t for f in fields if (t := _clean(r.get(f)))), "")


def _names(r: dict, fields: Iterable[str], limit: int) -> str:
    """The distinct names in these fields, which hold a string, a list of strings, or a list of
    {"name", "email"} objects."""
    unique: dict[str, str] = {}
    for field in fields:
        value = r.get(field)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                item = item.get("name") or item.get("email")
            if name := _clean(item):
                unique.setdefault(name.casefold(), name)
    return ", ".join(list(unique.values())[:limit])


def _host(url: object) -> str:
    try:
        return urlparse(str(url or "")).netloc.removeprefix("www.").split("@")[-1][:100]
    except ValueError:
        return ""


def _stamp(ts: str) -> str:
    """A timestamp as UTC to the second, so strings sort and compare as times."""
    try:
        moment = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Searching


def fts_query(text: str, match: str = "all") -> str:
    """User text as an FTS5 expression that can mean nothing but words. Each word or "phrase" is
    quoted (a quote can't occur inside, since quotes delimit), so AND, OR, NOT, NEAR, colons,
    parentheses and the like are plain text. A trailing * after a word or phrase makes its last
    word a prefix, and counts only when that word has two letters or more. Words are ANDed, or
    ORed with match="any". Empty when nothing searchable is left."""
    terms = []
    for phrase, star, word in _TERM.findall(text.replace("\x00", " "))[: MAX_TERMS * 2]:
        body = (phrase or word).strip()
        prefix = bool(star)
        if not phrase and body.endswith("*"):
            body = body.rstrip("*")
            prefix = True
        body = body[:MAX_TERM_CHARS]
        if not _WORD.search(body):
            continue
        last = re.findall(r"\w+", body)[-1]
        terms.append(f'"{body}"' + ("*" if prefix and len(last) >= 2 else ""))
    return (" OR " if match == "any" else " ").join(terms[:MAX_TERMS])


def search(
    query: str,
    sources: Iterable[str] | None = None,
    who: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    *,
    match: str = "all",
    exclude_sources: Iterable[str] | None = None,
    vault: Path | None = None,
) -> list[dict]:
    """The best hits for `query`, as dicts with id, source, stream, ts, who, where_, title,
    snippet (matched words between MARK_START and MARK_END), score (bm25, lower is better) and
    from_me. `who` limits to rows with that person's name; `since` and `until` are dates or
    times, `until` a date meaning through the end of that day. With no query, `who` alone lists
    that person's rows, newest first. Nothing indexed yet means no hits."""
    path = index_path(vault or vault_path())
    expression = fts_query(query, match)
    ranked = bool(expression)
    person = fts_query(who or "")
    if expression and person:
        expression = f"({expression}) AND who : ({person})"
    elif person:
        expression = f"who : ({person})"
    if not expression or not path.exists():
        return []
    sql = [
        "SELECT id, source, stream, ts, who, where_, title,",
        "snippet(mem, 7, ?, ?, '…', ?) AS in_text, snippet(mem, 6, ?, ?, '…', ?) AS in_title,",
        f"bm25(mem, {', '.join(map(str, WEIGHTS))}) AS score, from_me",
        "FROM mem WHERE mem MATCH ?",
    ]
    marks = [MARK_START, MARK_END, SNIPPET_TOKENS]
    params: list = [*marks, *marks, expression]
    if sources:
        names = list(sources)
        sql.append(f"AND source IN ({','.join('?' * len(names))})")
        params += names
    if exclude_sources:
        names = list(exclude_sources)
        sql.append(f"AND source NOT IN ({','.join('?' * len(names))})")
        params += names
    if since and (low := _bound(since)):
        sql.append("AND ts >= ?")
        params.append(low)
    if until and (high := _bound(until, end=True)):
        sql.append("AND ts < ?")
        params.append(high)
    sql.append("ORDER BY score, ts DESC" if ranked else "ORDER BY ts DESC")
    sql.append("LIMIT ?")
    params.append(max(1, min(int(limit), 500)))
    with closing(_connect(path)) as db:
        rows = db.execute(" ".join(sql), params).fetchall()
    return [_hit(r) for r in rows]


def _hit(row: sqlite3.Row) -> dict:
    snippet = next(
        (s for s in (row["in_text"], row["in_title"]) if MARK_START in s), row["in_text"]
    )
    return {
        "id": row["id"],
        "source": row["source"],
        "stream": row["stream"],
        "ts": row["ts"],
        "who": row["who"],
        "where_": row["where_"],
        "title": row["title"],
        "snippet": snippet,
        "score": row["score"],
        "from_me": None if row["from_me"] is None else bool(row["from_me"]),
    }


def _bound(value: str, end: bool = False) -> str | None:
    """A date or time as a timestamp to compare ts with. An end date means the day after, so the
    whole day counts. None for anything that isn't one."""
    value = value.strip()
    try:
        if len(value) == 10:
            day = date.fromisoformat(value) + timedelta(days=1 if end else 0)
            return f"{day.isoformat()}T00:00:00Z"
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return _stamp(value)


def frequencies(terms: Iterable[str], vault: Path | None = None) -> dict[str, int]:
    """How many rows each word or "phrase" is in: a word in thousands of rows says little about
    what a record is about. Terms with nothing searchable in them count as 0."""
    path = index_path(vault or vault_path())
    if not path.exists():
        return {}
    counts = {}
    with closing(_connect(path)) as db:
        for term in terms:
            expression = fts_query(term)
            counts[term] = (
                db.execute("SELECT count(*) FROM mem WHERE mem MATCH ?", (expression,)).fetchone()[
                    0
                ]
                if expression
                else 0
            )
    return counts


def stats(vault: Path | None = None) -> dict:
    """What the index holds: records per source, month files, and the file's size in bytes."""
    path = index_path(vault or vault_path())
    if not path.exists():
        return {"records": 0, "files": 0, "bytes": 0, "by_source": {}}
    with closing(_connect(path)) as db:
        by_source = {
            r["source"]: r["n"]
            for r in db.execute("SELECT source, count(*) AS n FROM records GROUP BY source")
        }
        files = db.execute("SELECT count(*) FROM files").fetchone()[0]
    return {
        "records": sum(by_source.values()),
        "files": files,
        "bytes": path.stat().st_size,
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
    }


# Context

_KEYS = ("id", "source", "stream", "ts", "who", "where_", "title", "text", "from_me")


def context(id: str, before: int = 10, after: int = 10, *, vault: Path | None = None) -> list[dict]:
    """The record `id` and the ones around it in the same chat, channel or thread (or, for
    sources without one, the same source and day), oldest first, read from the month files. The
    record itself has "target": True. A long chat goes on into neighbouring months when the
    month it's in has too few records. Unknown ids give an empty list."""
    vault = vault or vault_path()
    path = index_path(vault)
    if not path.exists():
        return []
    with closing(_connect(path)) as db:
        found = db.execute("SELECT ts, thread, file FROM records WHERE id = ?", (id,)).fetchone()
    if found is None:
        return []
    folder, _, name = found["file"].rpartition("/")
    month, thread = name.removesuffix(".jsonl"), found["thread"]
    by_day = thread.startswith("day:")
    # A day's records may sit in any of the source's streams; a chat's only in its own.
    prefix = thread.split("|", 1)[0].removeprefix("day:") + "/" if by_day else folder + "/"
    by_month: dict[str, list[tuple[str, Path]]] = {}
    for rel, file in _month_files(vault / "raw").items():
        if rel.startswith(prefix):
            by_month.setdefault(rel[-13:-6], []).append((rel, file))

    def records_in(when: str) -> list[dict]:
        rows = [
            dict(zip(_KEYS, row[:9], strict=True)) | {"target": False}
            for rel, file in by_month[when]
            for row in _read(rel, file)
            if row[9] == thread
        ]
        for row in rows:
            row["from_me"] = None if row["from_me"] is None else bool(row["from_me"])
        return sorted(rows, key=lambda r: (r["ts"], r["id"]))

    key = (found["ts"], id)
    here = records_in(month)
    earlier = [r for r in here if (r["ts"], r["id"]) < key]
    later = [r for r in here if (r["ts"], r["id"]) > key]
    if not by_day:
        months = sorted(by_month)
        at = months.index(month)
        for earlier_month in reversed(months[max(0, at - 6) : at]):
            if len(earlier) >= before:
                break
            earlier = records_in(earlier_month) + earlier
        for later_month in months[at + 1 : at + 7]:
            if len(later) >= after:
                break
            later += records_in(later_month)
    target = [{**r, "target": True} for r in here if r["id"] == id]
    return [*(earlier[-before:] if before else []), *target, *later[:after]]
