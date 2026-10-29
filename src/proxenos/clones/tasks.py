"""What is on the user's plate: tasks asked of them or promised by them in recent messages.

Each run reads the last two weeks of WhatsApp, Slack and email and has the model bring
clones/tasks/tasks.json up to date: new tasks added, finished ones marked done, ones where
the user is waiting on someone marked waiting. Tasks are mostly asked of the user by other
people, so this is the one clone that sends the other side of a conversation to the model. It
only sends conversations the user is part of: direct chats, groups and channels they wrote in
during the window (on Slack, also ones where they were @-mentioned), and mail addressed to
them or that they answered.
Newsletters, notifications and promotions stay home.

The page marks tasks done, not mine or dismissed in clones/tasks/feedback.jsonl. Those stay
closed: the model is told not to bring them back, and anything that comes back anyway is
dropped. clones/tasks/closed.json remembers them, and when each done task was closed, so done
tasks leave the list 30 days later.
"""

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import llm
from proxenos.config import env

DAYS = 14
MAX_CHARS = 400_000  # about 100k tokens of messages; past this the oldest are cut
MESSAGE_CHARS = 2000  # long mails and pasted documents are clipped to this
DONE_KEEP = timedelta(days=30)  # how long a done task stays on the list
CLOSED_KEEP = timedelta(days=90)  # how long a closed task is remembered, at least
ADDRESS_MONTHS = 6  # newest months searched for the user's own mail addresses and Slack ids

SOURCES = ("whatsapp", "slack", "email")
STATUSES = ("open", "waiting", "done")
PRIORITIES = ("high", "medium", "low")
_CLOSING = ("done", "not_mine", "dismiss")
_MARKED = {"done": "done", "not_mine": "not theirs", "dismiss": "dismissed"}
# Gmail's tabs and folders for mail that isn't to the user as a person. Takeout writes
# "Category Promotions" where the API says CATEGORY_PROMOTIONS; both normalize to the latter.
_BULK_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
    "SPAM",
    "TRASH",
}
# Senders nobody answers. Apple Mail keeps no Gmail labels, so this catches what they would.
_NO_REPLY = re.compile(
    r"(no-?reply|do-?not-?reply|notifications?|newsletters?|mailer-daemon)\b", re.IGNORECASE
)
# Slack's housekeeping events: they carry text, but nobody wrote it.
_SLACK_EVENTS = re.compile(
    r"(channel|group)_(join|leave|topic|purpose|name|archive|unarchive)|(un)?pinned_item"
)
_MENTION = re.compile(r"<@(\w+)(?:\|[^>]*)?>")
_REF = re.compile(r"m\d+")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")

_SYSTEM = """\
You keep the task list of {person}: what is on their plate right now. You get their \
WhatsApp, Slack and email from the last {days} days, both sides of every conversation they \
take part in, and the list as it stood after the last run. Return the whole updated list.

A task is something {person} has to do: asked of them ("can you send ...", "please review \
...") or promised by them ("I'll send it tomorrow"). Not tasks: what other people will do, \
unless {person} is waiting on it; pleasantries like "let's catch up sometime" unless a time \
was agreed; newsletters, notifications and receipts; anything already settled in the messages \
before it became a task.

For each task:
- id: its id from the current list if it's already there, "new" if it isn't. One entry per \
real task: when new messages are about a listed task, update that task.
- title: a short imperative, under 12 words ("Send Priya the slides for lab meeting").
- detail: one or two sentences: who wants what, and anything agreed about it.
- source: whatsapp, slack or email, where it was asked or promised.
- with: the person (or group or channel) it's with, or "" if nobody.
- asked_in: the [m..] ref of the message where it was asked or promised, or "" if that \
message isn't shown.
- due: YYYY-MM-DD when a deadline is stated or clearly implied ("by Friday" is that Friday's \
date), else "". Don't invent deadlines.
- priority: high when due within about two days or someone is blocked on it; low when \
optional or open-ended; medium otherwise.
- status: open while it's theirs to do. waiting when they've done their part and wait on \
someone else, or someone else is blocking it. done when the messages show it was done (sent, \
answered, "done", thanked for it).
- evidence: the [m..] refs of the messages that show the task and its current status.

Rules:
- Every task on the current list comes back, changed or not. Keep done ones, marked done.
- Never add back a task {person} closed on their own, however it's worded.
- Only what the messages show. A message from someone else is evidence of what they asked, \
not of what {person} agreed to.
- Refer to them as {person} and don't assume pronouns."""

_PROMPT = """\
Today is {today}. Message times are local.

## Current list
{current}
{closed}
## Messages from the last {days} days, one conversation at a time, oldest first
{cut}
{messages}"""

_TASKS_SCHEMA = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "source": {"type": "string", "enum": list(SOURCES)},
                    "with": {"type": "string"},
                    "asked_in": {"type": "string"},
                    "due": {"type": "string"},
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "title",
                    "detail",
                    "source",
                    "with",
                    "asked_in",
                    "due",
                    "priority",
                    "status",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


def plan(vault: Path, days: float = DAYS, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = vault / "clones" / "tasks"
    tasks = {task["id"]: task for task in _load_tasks(out / "tasks.json")}
    closed = _load_closed(out / "closed.json")
    verdicts = _feedback(out / "feedback.jsonl")

    # What the user closed on the page is closed for good, whatever the messages say.
    for key, (action, ts) in verdicts.items():
        if key in tasks:
            closed[key] = _closed_entry(tasks[key], action, ts)
        elif key in closed:
            closed[key] |= {"action": action, "closed_at": ts}
    mine = {k for k, entry in closed.items() if entry["action"]} | verdicts.keys()

    found = conversations(vault, _iso(now - timedelta(days=days)))
    text, refs, cut = render(found, llm.fit(MAX_CHARS))
    new = 0
    if refs:
        shown = {k: task for k, task in tasks.items() if k not in mine}
        answer = llm.ask(
            _PROMPT.format(
                today=now.astimezone().strftime("%A %Y-%m-%d, %H:%M (UTC%z)"),
                current="\n".join(map(_task_line, shown.values())) or "Empty: nothing yet.",
                closed=_closed_text({k: closed[k] for k in mine if k in closed}),
                days=f"{days:g}",
                cut="(Only the newest fit; older ones were cut.)\n" if cut else "",
                messages=text,
            ),
            system=_system(vault / "self" / "identity.md", days),
            schema=_TASKS_SCHEMA,
        )
        updated, new = merge(answer["tasks"], shown, refs, _closed_keys(closed, mine))
        tasks = {k: task for k, task in tasks.items() if k in mine} | updated

    tasks = _settle(tasks, closed, verdicts, now)
    keep = max(CLOSED_KEEP, timedelta(days=days) + DONE_KEEP)
    closed = {k: e for k, e in closed.items() if e["closed_at"] >= _iso(now - keep)}
    _write_json(out / "tasks.json", {"generated": _iso(now), "tasks": _sorted(tasks.values())})
    _write_json(out / "closed.json", closed)
    counts = {status: sum(t["status"] == status for t in tasks.values()) for status in STATUSES}
    return {"messages": len(refs), **counts, "new": new}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--days", type=float, default=DAYS, help="how many days of messages to read"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return plan(vault, days=args.days)


def conversations(vault: Path, since: str) -> list[dict]:
    """Every conversation the user is part of with text since `since`, as {source, title,
    messages}. Messages are oldest first, each {id, ts, sender, text}, and sender is "me" for the
    user's own."""
    return [*_whatsapp(vault, since), *_slack(vault, since), *_email(vault, since)]


def render(convos: list[dict], limit: int = MAX_CHARS) -> tuple[str, dict[str, dict], bool]:
    """The conversations as prompt text, the message behind each [m..] ref, and whether any
    were cut. Over `limit` characters the oldest messages go first. Each conversation keeps
    its messages in order, and the one with the newest message comes last."""
    newest_first = sorted(
        ((m["ts"], n, i, m) for n, c in enumerate(convos) for i, m in enumerate(c["messages"])),
        key=lambda t: t[:3],
        reverse=True,
    )
    kept: dict[int, list[dict]] = defaultdict(list)
    used, cut = 0, False
    for _, n, _, message in newest_first:
        cost = len(_line("m00000", message)) + 1
        if n not in kept:
            cost += len(convos[n]["title"]) + 6
        if used + cost > limit:
            cut = True
            break
        used += cost
        kept[n].append(message)

    parts, refs = [], {}
    for n in sorted(kept, key=lambda n: kept[n][0]["ts"]):
        lines = [f"### {convos[n]['title']}"]
        for message in reversed(kept[n]):
            ref = f"m{len(refs) + 1}"
            refs[ref] = {**message, "source": convos[n]["source"]}
            lines.append(_line(ref, message))
        parts.append("\n".join(lines))
    return "\n\n".join(parts), refs, cut


def merge(
    answer: list[dict], shown: dict[str, dict], refs: dict[str, dict], closed_keys: set
) -> tuple[dict[str, dict], int]:
    """The model's list applied to the tasks it was shown, and how many it added. Shown tasks
    it left out stay as they were, and anything new that matches a task the user closed is
    dropped."""
    tasks = dict(shown)
    new = 0
    for item in answer:
        title = " ".join(item["title"].split())
        if not title or item["id"] in closed_keys:
            continue
        cited = [refs[r] for r in _refs(item["evidence"]) if r in refs]
        asked = [refs[r] for r in _refs([item["asked_in"]]) if r in refs] or cited
        asked_at = min((m["ts"] for m in asked), default=None)
        key = item["id"] if item["id"] in shown else task_id(title, item["source"], asked_at)
        old = tasks.get(key)  # also a new task the model wrote out twice
        if old is None:
            if _matches(closed_keys, key, title, item["source"], asked_at):
                continue
            new += 1
        before = old or {}
        tasks[key] = {
            "id": key,
            "title": title,
            "detail": item["detail"].strip(),
            "source": before.get("source") or item["source"],
            "with": item["with"].strip() or None,
            "asked_at": before.get("asked_at") or asked_at,
            "due": _due(item["due"]),
            "priority": item["priority"],
            "status": item["status"],
            "evidence": list(
                dict.fromkeys([*before.get("evidence", []), *(m["id"] for m in cited)])
            ),
        }
    return tasks, new


def task_id(title: str, source: str, asked_at: str | None) -> str:
    return hashlib.sha1(f"{title}{source}{asked_at or ''}".encode()).hexdigest()[:12]


def _whatsapp(vault: Path, since: str) -> list[dict]:
    chats: dict[str, dict] = {}
    for r in _records(vault / "raw" / "whatsapp" / "messages", since):
        words = r.get("text") or r.get("caption")
        if not words:
            continue
        direct = r.get("chat_type") == "direct"
        kind = "direct chat" if direct else "group"
        chat = chats.setdefault(
            r["chat_id"],
            _convo("whatsapp", f"WhatsApp, {r.get('chat_name') or 'unknown'} ({kind})", direct),
        )
        chat["mine"] = chat["mine"] or r["from_me"]
        # Never the sender's JID: that's a phone number.
        sender = "me" if r["from_me"] else r.get("sender_name") or "someone"
        chat["messages"].append(_message(r, sender, words))
    return _kept(chats.values())


def _slack(vault: Path, since: str) -> list[dict]:
    found = []
    for directory in sorted((vault / "raw" / "slack").glob("*/messages")):
        team = directory.parent.name
        records = [
            r
            for r in _records(directory, since)
            if r.get("text") and not _SLACK_EVENTS.fullmatch(r.get("subtype") or "")
        ]
        names = {r["user_id"]: r["user_name"] for r in records if r.get("user_name")}
        me = _mine(directory, "user_id")

        def name(match: re.Match, me: set[str] = me, names: dict = names) -> str:
            return "@me" if match[1] in me else f"@{names.get(match[1]) or 'someone'}"

        channels: dict[str, dict] = {}
        for r in records:
            channel = channels.setdefault(
                r["channel_id"], _convo("slack", _slack_title(team, r), r["channel_type"] == "dm")
            )
            mentioned = bool(me & set(_MENTION.findall(r["text"])))
            channel["mine"] = channel["mine"] or r["from_me"] or mentioned
            sender = "me" if r["from_me"] else r.get("user_name") or "someone"
            if r.get("is_reply"):
                sender += " (in a thread)"
            channel["messages"].append(_message(r, sender, _MENTION.sub(name, r["text"])))
        found += _kept(channels.values())
    return found


def _slack_title(team: str, r: dict) -> str:
    name = r.get("channel_name") or "unnamed"
    if r["channel_type"] == "dm":
        return f"Slack ({team}), direct messages with {name}"
    if r["channel_type"] == "group_dm":
        return f"Slack ({team}), group DM {name}"
    return f"Slack ({team}), #{name}"


def _email(vault: Path, since: str) -> list[dict]:
    accounts = sorted(p for p in (vault / "raw" / "email").glob("*") if p.is_dir())
    me = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
    for account in accounts:
        me |= _mine(account, "from_address")
    found = []
    for account in accounts:
        records = [r for r in _records(account, since) if r.get("body_new") or r.get("subject")]
        by_id = {r["id"]: r for r in records}
        threads: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            threads[_thread(r, by_id)].append(r)
        for thread in threads.values():
            # Kept when the user answered it or someone wrote to them directly, minus the bulk mail.
            mail = [r for r in thread if r["from_me"] or not _bulk(r)]
            direct = any(me & {*(r.get("to") or []), *(r.get("cc") or [])} for r in mail)
            if not any(r["from_me"] for r in mail) and not direct:
                continue
            title = f"Email ({account.name}): {mail[0].get('subject') or '(no subject)'}"
            convo = _convo("email", title, True)
            for r in mail:
                sender = "me" if r["from_me"] else r.get("from_name") or r.get("from_address")
                text = r.get("body_new") or r.get("subject")
                convo["messages"].append(_message(r, sender or "someone", text))
            found.append(convo)
    return _kept(found)


def _thread(record: dict, by_id: dict[str, dict]) -> str:
    """The first message of a thread: the reply chain followed back as far as it's known.
    Replies to a message from before the window share that message's id."""
    seen = {record["id"]}
    while (parent := record.get("in_reply_to")) and parent not in seen:
        if parent not in by_id:
            return parent
        seen.add(parent)
        record = by_id[parent]
    return record["id"]


def _bulk(record: dict) -> bool:
    """Mail that isn't to the user as a person: promotions, notifications, lists, spam. IMAP writes
    system labels with a backslash (\\Spam), Takeout and the API without."""
    labels = {
        label.upper().lstrip("\\").replace(" ", "_") for label in record.get("gmail_labels") or []
    }
    local_part = (record.get("from_address") or "").split("@")[0]
    return bool(labels & _BULK_LABELS) or bool(_NO_REPLY.match(local_part))


def _mine(directory: Path, field: str) -> set[str]:
    """`field` of the user's own messages in the newest months of one stream: their addresses or
    ids."""
    found = set()
    for path in sorted(directory.glob("*.jsonl"))[-ADDRESS_MONTHS:]:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if '"from_me": true' in line and (value := json.loads(line).get(field)):
                    found.add(value)
    return found


def _records(directory: Path, since: str) -> Iterator[dict]:
    for path in sorted(directory.glob("*.jsonl")):
        if path.stem >= since[:7]:
            with path.open(encoding="utf-8") as f:
                yield from (r for r in map(json.loads, f) if r["ts"] >= since)


def _convo(source: str, title: str, mine: bool) -> dict:
    return {"source": source, "title": title, "mine": mine, "messages": []}


def _kept(convos: Iterable[dict]) -> list[dict]:
    """The conversations the user is part of. Groups count only when they wrote in them (or, on
    Slack, was mentioned)."""
    return [
        {"source": c["source"], "title": c["title"], "messages": c["messages"]}
        for c in convos
        if c["mine"] and c["messages"]
    ]


def _message(record: dict, sender: str, text: str) -> dict:
    return {
        "id": record["id"],
        "ts": record["ts"],
        "sender": sender,
        "text": _clip(text.strip(), MESSAGE_CHARS),
    }


def _line(ref: str, message: dict) -> str:
    when = datetime.fromisoformat(message["ts"]).astimezone().strftime("%m-%d %a %H:%M")
    return f"[{ref}] {when} {message['sender']}: {message['text']}"


def _system(identity: Path, days: float) -> str:
    person = env("NAME", "the person")
    system = _SYSTEM.format(person=person, days=f"{days:g}")
    if identity.exists():
        text = identity.read_text(encoding="utf-8").strip()
        system += f"\n\nWho {person} is, from their self-model:"
        system += f"\n<identity>\n{text}\n</identity>"
    return system


def _task_line(task: dict) -> str:
    state = [task["status"], task["priority"]] + ([f"due {task['due']}"] if task["due"] else [])
    origin = [task["source"]]
    if task.get("with"):
        origin.append(f"with {task['with']}")
    if task.get("asked_at"):
        origin.append(f"asked {_local_day(task['asked_at'])}")
    detail = f" {task['detail']}" if task.get("detail") else ""
    return f"- id {task['id']} [{', '.join(state)}] {task['title']}.{detail} ({', '.join(origin)})"


def _closed_text(closed: dict[str, dict]) -> str:
    if not closed:
        return ""
    lines = ["\n## Closed by them on their own. Never add these back, however they're worded"]
    for entry in sorted(closed.values(), key=lambda e: e["closed_at"]):
        who = f", with {entry['with']}" if entry.get("with") else ""
        lines.append(f"- {entry['title']} ({entry['source']}{who}): {_MARKED[entry['action']]}")
    return "\n".join(lines) + "\n"


def _closed_entry(task: dict, action: str | None, closed_at: str) -> dict:
    return {
        "title": task["title"],
        "source": task["source"],
        "with": task.get("with"),
        "asked_at": task.get("asked_at"),
        "action": action,  # None when the messages showed it done, not the user
        "closed_at": closed_at,
    }


def _closed_keys(closed: dict[str, dict], mine: set[str]) -> set:
    """What a new task can match a task the user closed by: its id, its title in any case and
    spacing, or the message it was asked in (source and time)."""
    keys: set = set(mine)
    for task_id_ in mine & closed.keys():
        entry = closed[task_id_]
        keys.add(_fold(entry["title"]))
        if entry.get("asked_at"):
            keys.add((entry["source"], entry["asked_at"]))
    return keys


def _matches(keys: set, task_id_: str, title: str, source: str, asked_at: str | None) -> bool:
    return task_id_ in keys or _fold(title) in keys or (source, asked_at) in keys


def _settle(
    tasks: dict[str, dict], closed: dict[str, dict], verdicts: dict, now: datetime
) -> dict[str, dict]:
    """The user's verdicts applied, done tasks dated in `closed`, and the long-done ones dropped."""
    settled = {}
    for key, task in tasks.items():
        action = verdicts.get(key, (None,))[0] or (closed.get(key) or {}).get("action")
        if action in ("not_mine", "dismiss"):
            continue
        if action == "done":
            task = {**task, "status": "done"}
        if task["status"] == "done":
            if key not in closed:
                closed[key] = _closed_entry(task, None, _iso(now))
            if closed[key]["closed_at"] < _iso(now - DONE_KEEP):
                continue
        elif key in closed and not closed[key]["action"]:
            del closed[key]  # the messages reopened it
        settled[key] = task
    return settled


def _sorted(tasks: Iterable[dict]) -> list[dict]:
    """Open first, then waiting, then done; by priority, then nearest due, then newest."""
    by_age = sorted(tasks, key=lambda t: t.get("asked_at") or "", reverse=True)
    return sorted(
        by_age,
        key=lambda t: (
            STATUSES.index(t["status"]),
            PRIORITIES.index(t["priority"]),
            t.get("due") or "9999",
        ),
    )


def _load_tasks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))["tasks"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SystemExit(f"tasks: {path} isn't a task list ({e}). Fix or delete it.") from None


def _load_closed(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _feedback(path: Path) -> dict[str, tuple[str, str]]:
    """The user's latest verdict on each task from the page: {task_id: (action, ts)}."""
    if not path.exists():
        return {}
    verdicts: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                task, action, when = event["task_id"], event["action"], _when(event["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # the page writes this file, and one bad line shouldn't stop a run
            if action not in _CLOSING or when is None or not isinstance(task, str):
                continue
            if task not in verdicts or _iso(when) >= verdicts[task][1]:
                verdicts[task] = (action, _iso(when))
    return verdicts


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _refs(values: list[str]) -> list[str]:
    """Refs as the model wrote them, "[m12]" or "m12", as "m12"."""
    return [match[0] for v in values if (match := _REF.search(v))]


def _due(text: str) -> str | None:
    text = text.strip()
    if not _DAY.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _fold(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", title.casefold()).split())


def _local_day(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d")


def _when(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
