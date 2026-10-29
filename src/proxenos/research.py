"""What a reply needs to know beyond its own chat, looked up before it's drafted.

Two things. The person: the network clone's note on who they are to the user, and the newest
records that name them on any channel (a LinkedIn reply also sees the WhatsApp chat with the
same person). The matter: the model reads the chat and asks for what to look up (a paper's
deadline, what a collaborator already did, what was promised), and each search runs on the
memory index, for up to ROUNDS rounds, each seeing what the last one found. Both come back as
text for the drafting prompt. Nothing here writes anything; the index is read-only.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import llm, memory, vectors

PERSON_ROWS = 30  # records naming the person, newest first
SEARCHES = 4  # queries a round may run
HITS = 4  # results kept from each of a query's searches
ROUNDS = 2
RECENT_DAYS = 365  # how far back a loose search looks
SNIPPET_CHARS = 400

_PLAN_SYSTEM = """\
You prepare {person}'s reply to a chat by deciding what to look up first in their own \
memory: their email, chats, Slack, documents, notes and calendar, all searchable by keyword. \
Look up what a good reply depends on and the chat doesn't say: deadlines and dates, the state \
of a project, what was already done or promised, earlier decisions, the history with this \
person. Each search is 1 to 4 keywords, the words that would appear in the record (a journal \
name, a project name, a person's name, "deadline", "resubmission"), not a sentence. Ask for \
nothing when the chat needs nothing beyond itself or what was already found."""

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {"searches": {"type": "array", "items": {"type": "string"}}},
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
    vault: Path, brief: str, person_name: str, ask: Callable[..., object], who: str | None = None
) -> tuple[str, list[str]]:
    """What the model chose to look up for this chat, and what it found: (text, searches).
    `who` is the person the chat is with, whose own records are searched too."""
    found: list[str] = []
    searched: list[str] = []
    for _ in range(ROUNDS):
        so_far = "\n\n".join(found) or "Nothing yet."
        try:
            answer = ask(
                f"{brief}\n\nAlready searched: {json.dumps(searched)}\n"
                f"Found so far:\n{so_far}\n\nWhat should be looked up next, if anything?",
                system=_PLAN_SYSTEM.format(person=person_name),
                schema=_PLAN_SCHEMA,
                effort="medium",
            )
        except llm.ModelError:  # research helps a draft; a muddled plan mustn't sink it
            break
        queries = [q.strip() for q in answer.get("searches", []) if isinstance(q, str)]
        queries = [q for q in queries if q and q not in searched][:SEARCHES]
        if not queries:
            break
        for query in queries:
            searched.append(query)
            lines = "\n".join(_line(h, person_name) for h in _search(vault, query, who))
            found.append(f'Search "{query}":\n{lines or "nothing found."}')
    return "\n\n".join(found), searched


def _search(vault: Path, query: str, who: str | None) -> list[dict]:
    """The best records for a query: the nearest in meaning first (from the vector index, when
    there is one), anywhere and among the person's own records, then those holding every word,
    then those holding any of them among the person's records (a word also matching its longer
    forms). A record rarely holds a question's words exactly ("MEG paper deadline" against a
    journal letter's "the revision is due by 7th Oct"), so meaning finds what words miss."""
    loose = " ".join(w + "*" if len(w) >= 4 else w for w in re.findall(r"\w+", query))
    since = (datetime.now(UTC) - timedelta(days=RECENT_DAYS)).date().isoformat()
    ranked = [
        *_by_meaning(vault, query, since, who),
        memory.search(query, limit=HITS, vault=vault),
        memory.search(loose, who=who, since=since, limit=HITS, match="any", vault=vault)
        if who
        else [],
    ]
    seen, hits = set(), []
    for found in ranked:  # each pass keeps its own share, so one can't crowd out the others
        fresh = [h for h in found if h["id"] not in seen][:HITS]
        seen.update(h["id"] for h in fresh)
        hits += fresh
    return hits


def _by_meaning(vault: Path, query: str, since: str, who: str | None) -> list[list[dict]]:
    """The nearest records in meaning, anywhere and the person's; none without the index."""
    try:
        anywhere = vectors.search(vault, query, limit=HITS, since=since)
        theirs = vectors.search(vault, query, limit=HITS, since=since, who=who) if who else []
    except RuntimeError:  # the embedding model isn't running: words alone, then
        return []
    return [anywhere, theirs]


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
