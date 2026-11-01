"""What a reply needs to know beyond its own chat, looked up before it's drafted.

Two things. The person: the network clone's note on who they are to the user, and the newest
records that name them on any channel (a LinkedIn reply also sees the WhatsApp chat with the
same person). The matter: the model reads the chat and asks for what to look up (a paper's
deadline, what a collaborator already did, what was promised), and each search runs on the
memory indexes, by meaning and by words, for up to ROUNDS rounds, each seeing what the last one
found. A search may carry the days to look in, when the chat points to a time ("around the March
conference", "last week"): LongMemEval (Wu and others, ICLR 2025) found that narrowing a search
to the time a question names raised recall on questions about time by 7 to 11 percent. A
query's searches are fused by reciprocal rank (memory.fuse), so a record several of them rank
high comes first. Then the model keeps, of everything found, only what the reply depends on, so
near misses don't drown the record that matters. Both come back as text for the drafting prompt.

The indexes are read-only. The one thing written is a line per run in memory/research.jsonl, for
tuning the searches and the gate: the searches' words and days, each search's ids in rank order,
the fused order and the ids kept. Ids only, never what a record says.
"""

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import llm, memory, vectors

PERSON_ROWS = 30  # records naming the person, newest first
SEARCHES = 4  # queries a round may run
HITS = 4  # records a query keeps for each of its searches that found any, the best fused
DEPTH = 10  # records read from each search, to fuse
ROUNDS = 2
RECENT_DAYS = 365  # how far back a loose search looks when its plan gives no days
SNIPPET_CHARS = 400
LOG = "memory/research.jsonl"
LOG_BYTES = 20_000_000  # the log's most, thousands of runs: past it, the older half goes

_PLAN_SYSTEM = """\
You prepare {person}'s reply to a chat by deciding what to look up first in their own \
memory: their email, chats, Slack, documents, notes and calendar, all searchable by keyword. \
Look up what a good reply depends on and the chat doesn't say: deadlines and dates, the state \
of a project, what was already done or promised, earlier decisions, the history with this \
person. Each search's words are 1 to 4 keywords, the words that would appear in the record (a \
journal name, a project name, a person's name, "deadline", "resubmission"), not a sentence. When \
the chat points to a time ("around the March conference", "last week", "what we said in the \
summer"), give the first and last day to look in as after and before (YYYY-MM-DD), a little \
wider than the time itself; otherwise leave them out. Ask for nothing when the chat needs \
nothing beyond itself or what was already found."""

_GATE_SYSTEM = """\
You check what was found in {person}'s memory before their reply to a chat is drafted. Keep \
the records the reply depends on: the facts, dates, deadlines, earlier decisions and history \
it should get right. Leave out near misses: records that share words with the chat but are \
about something else. Return the numbers of the records to keep, or none."""

_GATE_SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "integer"}}},
    "required": ["keep"],
    "additionalProperties": False,
}

# The days are optional, so a local model held to the schema item by item (llm._conform) keeps
# a search that leaves them out.
_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "searches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "words": {"type": "string"},
                    "after": {"type": "string"},
                    "before": {"type": "string"},
                },
                "required": ["words"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["searches"],
    "additionalProperties": False,
}


def person(vault: Path, name: str, me: str, chat: tuple[str, str] | None = None) -> str:
    """Who `name` is to the user (`me`) and their newest records anywhere but `chat`, the
    (source, chat name) being answered, or ""."""
    note = _network_note(vault, name)
    names = [name, *(note or {}).get("aka", [])]
    seen, rows = set(), []
    for alias in names:
        for hit in memory.search("", who=alias, limit=PERSON_ROWS, vault=vault):
            if hit["id"] in seen or (hit["source"], hit["where_"]) == chat:
                continue  # this chat's own messages are in the prompt already
            seen.add(hit["id"])
            rows.append(hit)
    rows = sorted(rows, key=lambda h: h["ts"], reverse=True)[:PERSON_ROWS]
    parts = []
    if note:
        fields = ("relation", "context", "org", "topics", "first_seen", "last_seen", "sources")
        about = [f"- {k}: {_text(note[k])}" for k in fields if note.get(k)]
        parts.append(f"Who {name} is to them, from their network:\n" + "\n".join(about))
    if rows:
        parts.append(
            f"Their newest records with {name} elsewhere, newest first:\n"
            + "\n".join(_line(h, me) for h in rows)
        )
    return "\n\n".join(parts)


def matter(
    vault: Path,
    brief: str,
    person_name: str,
    ask: Callable[..., object],
    who: str | None = None,
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    """What the model chose to look up for this chat, and of what it found, what the reply
    depends on: (text, searches). `who` is the person the chat is with, whose own records are
    searched too."""
    now = now or datetime.now(UTC)
    today = now.astimezone().date()  # the user's day, for "last week"
    found: list[str] = []
    hits: dict[str, dict] = {}  # every record found, once, in the order found
    searched: list[str] = []
    runs: list[dict] = []  # each search's lists and fused order, as ids, for the log
    for _ in range(ROUNDS):
        so_far = "\n\n".join(found) or "Nothing yet."
        try:
            answer = ask(
                f"{brief}\n\nToday is {today:%A, %Y-%m-%d}.\n"
                f"Already searched: {json.dumps(searched)}\n"
                f"Found so far:\n{so_far}\n\nWhat should be looked up next, if anything?",
                system=_PLAN_SYSTEM.format(person=person_name),
                schema=_PLAN_SCHEMA,
                effort="medium",
            )
        except llm.ModelError:  # research helps a draft; a muddled plan mustn't sink it
            break
        planned = [q for item in answer.get("searches", []) if (q := _planned(item, today))]
        queries = [q for q in dict.fromkeys(planned) if _label(*q) not in searched][:SEARCHES]
        if not queries:
            break
        for words, after, before in queries:
            searched.append(_label(words, after, before))
            lists = _ranked(vault, words, who, after, before)
            results = _fused(lists)
            hits.update((h["id"], h) for h in results if h["id"] not in hits)
            runs.append(
                {
                    "words": words,
                    "after": after,
                    "before": before,
                    "lists": {name: [h["id"] for h in ranked] for name, ranked in lists.items()},
                    "fused": [h["id"] for h in results],
                }
            )
            lines = "\n".join(_line(h, person_name) for h in results)
            found.append(f'Search "{searched[-1]}":\n{lines or "nothing found."}')
    kept = _gate(brief, list(hits.values()), person_name, ask)
    _log(vault, {"at": _iso(now), "searches": runs, "kept": [h["id"] for h in kept]})
    return "\n".join(_line(h, person_name) for h in kept), searched


def _planned(item: object, today: date) -> tuple[str, str | None, str | None] | None:
    """One planned search as (words, after, before), its days checked; None without words."""
    if not isinstance(item, dict) or not isinstance(item.get("words"), str):
        return None
    words = " ".join(item["words"].split())
    return (words, *_span(item.get("after"), item.get("before"), today)) if words else None


def _span(after: object, before: object, today: date) -> tuple[str | None, str | None]:
    """A search's first and last day, as dates a model can get wrong: one that isn't a real
    YYYY-MM-DD is left out, two in the wrong order are swapped, and a first day after today,
    which nothing could be found from, is left out."""
    low, high = _day(after), _day(before)
    if low and high and low > high:
        low, high = high, low
    if low and low > today:
        low = None
    return (low.isoformat() if low else None, high.isoformat() if high else None)


def _day(value: object) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:  # a day no month has, 2026-02-30
        return None


def _label(words: str, after: str | None, before: str | None) -> str:
    """A search as the model is shown it among those already run."""
    if after and before:
        return f"{words} ({after} to {before})"
    if after:
        return f"{words} (from {after})"
    return f"{words} (until {before})" if before else words


def _gate(brief: str, hits: list[dict], person_name: str, ask: Callable[..., object]) -> list[dict]:
    """Of the records found, the ones the reply depends on, as the model judges them against
    the chat: near misses are left out, so they don't drown the one that matters. All of them
    when the model can't say."""
    if not hits:
        return []
    numbered = "\n".join(
        f"{i}. {_line(h, person_name).removeprefix('- ')}" for i, h in enumerate(hits, 1)
    )
    try:
        answer = ask(
            f"{brief}\n\nRecords found in their memory:\n{numbered}\n\n"
            "Which of these does the reply depend on?",
            system=_GATE_SYSTEM.format(person=person_name),
            schema=_GATE_SCHEMA,
            effort="medium",
        )
    except llm.ModelError:
        return hits
    keep = {i for i in answer.get("keep", []) if isinstance(i, int) and 1 <= i <= len(hits)}
    return [h for i, h in enumerate(hits, 1) if i in keep]


def _search(
    vault: Path, query: str, who: str | None, after: str | None = None, before: str | None = None
) -> list[dict]:
    """The best records for a query, best first: what its searches by meaning and by words
    found (`_ranked`), fused (`_fused`). `after` and `before` are its first and last day."""
    return _fused(_ranked(vault, query, who, after, before))


def _ranked(
    vault: Path, query: str, who: str | None, after: str | None = None, before: str | None = None
) -> dict[str, list[dict]]:
    """Each search's records for a query, best first, by the search's name: the nearest in
    meaning (from the vector index, when there is one), anywhere and among the person's own
    records, those holding every word, and those holding any of them among the person's records
    (a word also matching its longer forms). A record rarely holds a question's words exactly
    ("cookbook deadline" against an editor's "the second draft is due by 7th Oct"), so meaning
    finds what words miss. Each looks between `after` and `before` when given; without `after`,
    the loose ones, by meaning and by any word, look back RECENT_DAYS."""
    loose = " ".join(w + "*" if len(w) >= 4 else w for w in re.findall(r"\w+", query))
    since = after or (datetime.now(UTC) - timedelta(days=RECENT_DAYS)).date().isoformat()
    meaning, their_meaning = _by_meaning(vault, query, since, before, who)
    words = memory.search(query, since=after, until=before, limit=DEPTH, vault=vault)
    their_words = (
        memory.search(
            loose, who=who, since=since, until=before, limit=DEPTH, match="any", vault=vault
        )
        if who
        else []
    )
    return {
        "meaning": meaning,
        "their_meaning": their_meaning,
        "words": words,
        "their_words": their_words,
    }


def _fused(lists: dict[str, list[dict]]) -> list[dict]:
    """The searches' records as one list by reciprocal rank, HITS for each search that found
    any. Each search's best stays in, so one can't crowd out the others."""
    found = [ranked for ranked in lists.values() if ranked]
    return memory.fuse(found, limit=HITS * len(found), keep=1)


def _by_meaning(
    vault: Path, query: str, since: str, until: str | None, who: str | None
) -> tuple[list[dict], list[dict]]:
    """The nearest records in meaning, anywhere and the person's; none without the index."""
    try:
        anywhere = vectors.search(vault, query, limit=DEPTH, since=since, until=until)
        theirs = (
            vectors.search(vault, query, limit=DEPTH, since=since, until=until, who=who)
            if who
            else []
        )
    except RuntimeError:  # the embedding model isn't running: words alone, then
        return [], []
    return anywhere, theirs


def _network_note(vault: Path, name: str) -> dict | None:
    """The network clone's record for this name or one of its aliases, if there is one."""
    try:
        people = json.loads((vault / "clones" / "network" / "people.json").read_text())["people"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    wanted = " ".join(name.lower().split())
    for p in people if isinstance(people, list) else []:
        if not isinstance(p, dict):
            continue
        names = [p.get("name"), *(p.get("aka") or [])]
        if any(" ".join(str(n).lower().split()) == wanted for n in names if n):
            return p
    return None


def _line(hit: dict, me: str) -> str:
    """One record as a line: when, where, who wrote it, and the matched words."""
    snippet = " ".join(str(hit["snippet"] or hit["title"] or "").split())
    for mark in (memory.MARK_START, memory.MARK_END):
        snippet = snippet.replace(mark, "")
    who = me if hit["from_me"] else " ".join(str(hit["who"] or "").split())[:80] or "someone"
    where = hit["where_"] or hit["source"]
    return f"- [{hit['ts'][:10]}, {hit['source']}, {where}] {who}: {snippet[:SNIPPET_CHARS]}"


def _text(value: object) -> str:
    return ", ".join(map(str, value)) if isinstance(value, list) else " ".join(str(value).split())


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(vault: Path, record: dict) -> None:
    """Append one run's line, private to the user, as the model calls' log does (llm._log). A
    run's line grows with its searches, so the log is cut by size: past LOG_BYTES, to its newer
    half. A log that can't be written never fails the reply it records."""
    path = vault / LOG
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if path.stat().st_size > LOG_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            lines = lines[len(lines) // 2 :]
            tmp = path.with_name(f".{path.name}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.writelines(lines)
            os.replace(tmp, path)
    except OSError:
        pass
