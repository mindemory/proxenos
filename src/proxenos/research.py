"""What a reply needs to know beyond its own chat, looked up before it's drafted.

Two things. The person: the network clone's note on who they are to the user, and the newest
records that name them on any channel (a LinkedIn reply also sees the WhatsApp chat with the
same person). The matter: the model reads the chat and asks for what to look up (a paper's
deadline, what a collaborator already did, what was promised), and each search runs on the
memory index, for up to ROUNDS rounds, each seeing what the last one found. Both come back as
text for the drafting prompt. Nothing here writes anything; the index is read-only.
"""

import json
from collections.abc import Callable
from pathlib import Path

from proxenos import memory

PERSON_ROWS = 30  # records naming the person, newest first
SEARCHES = 4  # queries a round may run
HITS = 6  # results kept per query
ROUNDS = 2
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
    vault: Path, brief: str, person_name: str, ask: Callable[..., object]
) -> tuple[str, list[str]]:
    """What the model chose to look up for this chat, and what it found: (text, searches)."""
    found: list[str] = []
    searched: list[str] = []
    for _ in range(ROUNDS):
        so_far = "\n\n".join(found) or "Nothing yet."
        answer = ask(
            f"{brief}\n\nAlready searched: {json.dumps(searched)}\nFound so far:\n{so_far}\n\n"
            "What should be looked up next, if anything?",
            system=_PLAN_SYSTEM.format(person=person_name),
            schema=_PLAN_SCHEMA,
            effort="medium",
        )
        queries = [q.strip() for q in answer.get("searches", []) if isinstance(q, str)]
        queries = [q for q in queries if q and q not in searched][:SEARCHES]
        if not queries:
            break
        for query in queries:
            searched.append(query)
            hits = memory.search(query, limit=HITS, vault=vault) or memory.search(
                query, limit=HITS, match="any", vault=vault
            )
            if hits:
                found.append(
                    f'Search "{query}":\n' + "\n".join(_line(h, person_name) for h in hits)
                )
            else:
                found.append(f'Search "{query}": nothing found.')
    return "\n\n".join(found), searched


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
