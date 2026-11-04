"""What the user tells Proxenos directly: what their messages don't show.

Two kinds of note, written from the page's home view into state/told.jsonl, one line each
({at, text, always}):
- a rule, kept until the user removes it ("always"): how everything drafted for them goes,
  such as "keep replies to my manager short";
- a fact, true for now: something that changed and no message shows yet, such as "I'm not
  going to Tuesday's clinic visit". It counts for FACT_DAYS.
Removing a note appends {at, forget: <the note's at>}, so the file only grows, as feedback does.

Every drafting prompt gets both (`prompt`): the work clone's drafts and care's messages and
scripts. The tasks clone reads the facts as something the user said (`conversation`), so a task
or plan they settle here closes the way one settled in a chat does, and the calendar follows.
A month's diary (clones/life) reads the facts told that month as its milestones, and a fact told
or removed since a month was written (`changed`) has the night write it again.
The notes are the user's own words, sent to the model only with the prompts above.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

FACT_DAYS = 14
NOTE_CHARS = 1000  # as the page caps a note
TOLD = Path("state", "told.jsonl")


def notes(vault: Path, now: datetime | None = None, fade: bool = True) -> list[dict]:
    """The notes that count now, oldest first: every rule, and the facts of the last FACT_DAYS
    (every fact, without `fade`), as {at, text, always}, without those removed since. None
    written after `now`, nor a removal after it, which only a reply drafted as of an earlier
    time (proxenos.compare, `proxenos voice eval`) would find."""
    now = now or datetime.now(UTC)
    found: dict[str, dict] = {}
    try:
        lines = (vault / TOLD).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            note = json.loads(line)
            at = datetime.fromisoformat(str(note["at"]))
        except (ValueError, KeyError, TypeError):
            continue  # the page writes this file, and one bad line shouldn't hide the rest
        if at.tzinfo and at > now:
            continue  # told, or taken back, after `now`
        if note.get("forget"):
            found.pop(str(note["forget"]), None)
            continue
        text = " ".join(str(note.get("text") or "").split())[:NOTE_CHARS]
        always = note.get("always") is True
        if text and (always or not fade or now - at <= timedelta(days=FACT_DAYS)):
            found[str(note["at"])] = {"at": str(note["at"]), "text": text, "always": always}
    return sorted(found.values(), key=lambda n: n["at"])


def changed(vault: Path) -> dict[str, str]:
    """When each fact last changed, by the fact's own at: when it was told, or when it was
    removed, since what was written from it is out of date then too. Removed facts stay here;
    rules don't, which say how drafts go rather than what happened."""
    found: dict[str, str] = {}
    try:
        lines = (vault / TOLD).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            note = json.loads(line)
            datetime.fromisoformat(str(note["at"]))
        except (ValueError, KeyError, TypeError):
            continue
        if note.get("forget"):
            if str(note["forget"]) in found:
                found[str(note["forget"])] = str(note["at"])
        elif str(note.get("text") or "").strip() and note.get("always") is not True:
            found[str(note["at"])] = str(note["at"])
    return found


def prompt(vault: Path, person: str, now: datetime | None = None) -> str:
    """The notes as part of a system prompt, or "" when there are none."""
    told = notes(vault, now)
    rules = [n["text"] for n in told if n["always"]]
    facts = [f"- {n['at'][:10]}: {n['text']}" for n in told if not n["always"]]
    parts = []
    if rules:
        lines = "\n".join(f"- {text}" for text in rules)
        parts.append(
            f"{person}'s own rules for everything written for them. Never break one:\n{lines}"
        )
    if facts:
        lines = "\n".join(facts)
        parts.append(f"What {person} told you lately, newer than their messages:\n{lines}")
    return "\n\n".join(parts)


def conversation(vault: Path, since: str, now: datetime | None = None) -> dict | None:
    """The facts told since `since`, as a conversation for the tasks clone, or None. The
    conversation's own window decides which, as it does for messages."""
    said = [
        {"id": f"told/{n['at']}", "ts": _utc(n["at"]), "sender": "me", "text": n["text"]}
        for n in notes(vault, now, fade=False)
        if not n["always"] and _utc(n["at"]) >= since
    ]
    return {"source": "told", "title": "Told to Proxenos", "messages": said} if said else None


def _utc(at: str) -> str:
    when = datetime.fromisoformat(at)
    when = when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")
