"""Memory by meaning: the last year of chats, mail, notes and documents as vectors, so a search
finds what a record is about and not only the words in it ("when is the MEG revision due"
finds a journal letter that says "the revision is due by 7th Oct").

The units come from the full-text index (memory.py): a chat's messages of one day together
(WhatsApp, Slack, LinkedIn, Messenger, Instagram, X), and each email, note, event and document on
its own, up to CHARS characters. A small embedding model on this Mac turns each into a vector
through Ollama (PROXENOS_EMBED_MODEL), so nothing leaves the computer. They go in
vault/memory/vectors.sqlite (0600): one row per unit with its key, a hash of its text, where and
when it is from, a snippet, and the vector, normalized, as float16. Like the index, it is derived
data: delete it and it is built again.

`update` embeds the units not embedded yet or changed since (a chat's day grows), newest first,
and stops after `seconds`, so a sync spends a few minutes on it and the backlog shrinks run by
run. `search` embeds the question the way the model is asked to read questions and returns the
nearest units, in the same shape as memory.search's hits.
"""

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from proxenos import memory
from proxenos.config import env

EMBED_MODEL = "qwen3-embedding:0.6b"
DAYS = 365
CHARS = 1500  # of a unit, embedded
SNIPPET_CHARS = 400
BATCH = 16
LOCK_WAIT = 120  # seconds to wait for another run's write to finish
_OLLAMA = "http://127.0.0.1:11434"
CHATS = ("whatsapp", "slack", "linkedin", "facebook", "instagram", "twitter")
SOURCES = (*CHATS, "email", "notes", "drive", "calendar", "keep", "gtasks")
# How the model is told to read a question, as Qwen3-Embedding expects; units are embedded as is.
_QUERY = (
    "Instruct: Given a question, find the person's own messages, email, notes and documents that "
    "answer it\nQuery: "
)

Embed = Callable[[list[str]], list[list[float]]]


def path(vault: Path) -> Path:
    return vault / "memory" / "vectors.sqlite"


def update(vault: Path, seconds: float | None = None, embed: Embed | None = None) -> dict:
    """Embed what's new or changed, newest first, for at most `seconds`."""
    embed = embed or _ollama
    deadline = time.monotonic() + seconds if seconds else None
    with closing(_connect(path(vault))) as db:
        have = dict(db.execute("SELECT key, hash FROM units"))
        todo = [u for u in _units(vault) if have.get(u["key"]) != u["hash"]]
        done = 0
        for start in range(0, len(todo), BATCH):
            if deadline and time.monotonic() > deadline:
                break
            batch = todo[start : start + BATCH]
            try:
                vectors = _normalized(embed([u["text"] for u in batch]))
            except RuntimeError:  # the model is busy or gone: what's left waits for the next run
                break
            db.executemany(
                "INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        u["key"],
                        u["hash"],
                        u["id"],
                        u["source"],
                        u["ts"],
                        u["who"],
                        u["where_"],
                        u["text"][:SNIPPET_CHARS],
                        v.astype(np.float16).tobytes(),
                    )
                    for u, v in zip(batch, vectors, strict=True)
                ],
            )
            try:
                db.commit()
            except sqlite3.OperationalError:  # still locked after LOCK_WAIT: the next run goes on
                break
            done += len(batch)
    return {"units_embedded": done, "units_waiting": len(todo) - done}


def search(
    vault: Path,
    query: str,
    limit: int = 10,
    since: str | None = None,
    who: str | None = None,
    embed: Embed | None = None,
) -> list[dict]:
    """The units nearest in meaning to `query`, as memory.search's hits (snippet, score as
    similarity, higher is nearer). `who` keeps units naming every word of it."""
    if not query.strip() or not path(vault).exists():
        return []
    rows, matrix = _load(path(vault))
    if not rows:
        return []
    asked = _normalized((embed or _ollama)([_QUERY + query]))[0]
    scores = matrix @ asked
    names = (who or "").lower().split()
    found = []
    for i in np.argsort(-scores):
        row = rows[i]
        if (since and row["ts"] < since) or not all(n in row["who"].lower() for n in names):
            continue
        found.append(row | {"score": float(scores[i])})
        if len(found) >= limit:
            break
    return found


def _units(vault: Path) -> Iterator[dict]:
    """The units to embed, newest first: a chat's day of messages, or one record."""
    since = (datetime.now(UTC) - timedelta(days=DAYS)).date().isoformat()
    marks = ",".join("?" * len(SOURCES))
    with closing(sqlite3.connect(f"file:{memory.index_path(vault)}?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT id, source, ts, who, where_, title, text, thread FROM records "
            f"WHERE ts >= ? AND source IN ({marks}) ORDER BY ts DESC",
            (since, *SOURCES),
        ).fetchall()
    days: dict[str, list[tuple]] = defaultdict(list)
    units = []
    for row in rows:
        if row[1] in CHATS:
            days[f"{row[7]}@{row[2][:10]}"].append(row)
        else:
            units.append(_unit(row[0], [row]))
    units += [_unit(key, messages) for key, messages in days.items()]
    units.sort(key=lambda u: u["ts"], reverse=True)
    return (u for u in units if u["text"])


def _unit(key: str, rows: list[tuple]) -> dict:
    """One unit from its records (newest first, as read): when and where, who, and the text."""
    newest = rows[0]
    who = sorted({n.strip() for r in rows for n in (r[3] or "").split(",") if n.strip()})
    if newest[1] in CHATS:  # a day of a chat, oldest message first
        lines = [f"{(r[3] or '').split(',')[0]}: {r[6]}" for r in reversed(rows) if r[6]]
        text = "\n".join(lines)
    else:
        text = "\n".join(t for t in (newest[5], newest[6]) if t)
    text = f"{newest[4] or newest[1]} | {text}".strip()[:CHARS] if text else ""
    return {
        "key": key,
        "hash": hashlib.sha1(text.encode()).hexdigest()[:16],
        "id": newest[0],
        "source": newest[1],
        "ts": newest[2],
        "who": ", ".join(who)[:300],
        "where_": newest[4] or "",
        "text": text,
    }


def _connect(file: Path) -> sqlite3.Connection:
    file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(file, timeout=LOCK_WAIT)  # a sync and a backfill may write at once
    db.execute(
        "CREATE TABLE IF NOT EXISTS units (key TEXT PRIMARY KEY, hash TEXT, id TEXT, "
        "source TEXT, ts TEXT, who TEXT, where_ TEXT, snippet TEXT, vec BLOB)"
    )
    file.chmod(0o600)
    return db


_cache: dict[Path, tuple[float, list[dict], np.ndarray]] = {}


def _load(file: Path) -> tuple[list[dict], np.ndarray]:
    """Every unit and the matrix of their vectors, read once per change of the file."""
    stamp = file.stat().st_mtime
    if file in _cache and _cache[file][0] == stamp:
        return _cache[file][1], _cache[file][2]
    with closing(sqlite3.connect(f"file:{file}?mode=ro", uri=True)) as db:
        found = db.execute("SELECT id, source, ts, who, where_, snippet, vec FROM units").fetchall()
    rows = [
        {
            "id": r[0],
            "source": r[1],
            "ts": r[2],
            "who": r[3],
            "where_": r[4],
            "title": "",
            "snippet": r[5],
            "from_me": None,
        }
        for r in found
    ]
    matrix = (
        np.stack([np.frombuffer(r[6], dtype=np.float16) for r in found]).astype(np.float32)
        if found
        else np.zeros((0, 0), np.float32)
    )
    _cache[file] = (stamp, rows, matrix)
    return rows, matrix


def _normalized(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)


def _ollama(texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": env("EMBED_MODEL", EMBED_MODEL), "input": texts}).encode()
    request = urllib.request.Request(
        f"{_OLLAMA}/api/embed", body, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)["embeddings"]
    except (urllib.error.URLError, TimeoutError, KeyError) as e:
        raise RuntimeError(f"the embedding model isn't answering ({e}); is Ollama running?") from e


def available() -> bool:
    """Whether the embedding model answers, so a sync can skip this rather than fail."""
    try:
        _ollama(["ok"])
    except RuntimeError:
        return False
    return True
