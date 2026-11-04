"""The outbox: replies that go out on their own, within rules the user sets on the Drafts page.

Off until the user switches it on, and then only per app ("channel"), and only for an app whose
replies have earned it on the evidence that matches what it sends. The outbox sends drafts nobody
touched, so its track record is the app's reply drafts the user didn't act on (didn't copy, open
in their app, edit, approve, mark sent, keep or think through in Think: proxenos.fidelity measures
them all, the page's feedback.jsonl and Think's threads say which were used) and that it didn't
send itself, since its own sends would vouch for themselves. It would have sent one whose chat
the user never answered too, so each of those counts as one not sent unchanged. Of them all,
the share that came out nearly unchanged (closeness at least NEARLY) must be at least min_share
(0.9) with 95% confidence: the Wilson lower bound of that share. With every one unchanged, 0.9
takes 35 drafts. At least min_measured of them, too. A rules.json from before keeps its
switches, and its min_closeness, the old bar on the mean, is read as min_share.

A reply qualifies only when it is a draft nobody has touched, for one person who has heard from
the user before (never someone new's first email), with no [placeholder] left and nothing it
asks the user, and only while its chat is still waiting on exactly the messages it answers. A
qualifying reply is queued at one sync and goes out at the next, so the user has until then
(about 15 minutes) to cancel it on the page; at most daily_limit go out a day. With the app's
"sign" on (off unless the user turns it on), it goes out with SIGN under it.

Then, as it goes, it's held for the user when it might reach more than one person, or carry
something from outside its own conversation:
- its chat isn't known to be with one person: a group, a chat whose records don't say, or an
  email whose mail went to anyone but the user;
- its prompt held anything beyond the chat: memory's research, the person's records elsewhere,
  Care, the user's notes or their calendar (the draft's "drew_on", which the drafting code sets
  from what it put in, never the model; a draft from before it was kept is held too), or the
  draft says it rested on something (its "found", the model's word);
- it mentions health, or a name or place (a capitalised word that isn't a sentence's first) the
  chat and the user's own messages there never had, other than a day, a month and the two
  people's own names: for what every draft gets, the self-model and the user's own writing;
- it has a link, an email address, a phone number or a run of DIGITS or more digits that's in
  neither the chat's messages nor the user's own earlier ones there, checked the way a call's
  words are checked against its sheet;
- it's an email reply to mail whose Reply-To isn't its From (a reply would go somewhere else) or
  that was read before Reply-To was kept.
A held reply stays a draft for the user, and the log says why.

How each app sends ("routes"): email through the Mail app (it replies in the thread, from the
account the mail came to, as if the user pressed Reply); Instagram, Messenger, X and LinkedIn,
and WhatsApp when it's added there, through Beeper Desktop's local API. Slack has none yet.

Files in clones/outbox/: rules.json (the page writes it; read as strictly as the page reads it),
cancelled.jsonl (the page appends), state.json (written here each sync: routes, track record,
what has earned sending, the queue), log.jsonl (every attempt, sent or not) and unanswered.jsonl
(the drafts whose chat went unanswered, kept for the track record after the draft is gone). A reply that
goes out is marked sent, as if the user had pressed Sent on the page.

Nothing goes out from a made-up vault (`proxenos demo`, marked by its DEMO file): it has no routes.
"""

import json
import math
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import chats, fidelity, links, voice
from proxenos.clones import work
from proxenos.config import env
from proxenos.ingest import beeper

CHANNELS = ("email", "whatsapp", "slack", "instagram", "messenger", "x", "linkedin")
_SOURCE_CHANNEL = {"facebook": "messenger", "twitter": "x"}  # a chat source by its channel
WAIT = timedelta(minutes=10)  # queued now, sent at the first sync after this
DIGITS = 6  # a run of digits this long is a number someone could act on: an account, a code
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,80}\]")
_WWW = re.compile(r"\bwww\.[^\s<>\"'(){}\[\]]+", re.IGNORECASE)  # a link without its https://
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A phone number or another number, with the spaces, dots, dashes and brackets inside it.
_NUMBER = re.compile(r"\+?\(?\d[\d ().-]*\d")
DEFAULT_RULE = {"on": False, "min_share": 0.9, "min_measured": 5, "sign": False}
MAX_SHARE = 0.99  # a share of 1 could never be shown: the bound is always under it
NEARLY = 0.9  # a measured draft this close to what was sent went out nearly unchanged
Z = 1.96  # 95% confidence, for the Wilson bound
# What the user does with a draft on the page that makes it theirs: all but discard, which
# counts against an app like a reply they rewrote.
USED = ("approve", "copy", "opened", "edit", "sent", "keep")
SIGN = "\n\n(sent by my assistant)"
# A capitalised word, to tell a name or a place; an apostrophe or a hyphen splits it.
_WORD = re.compile(r"[^\W\d_]+")
_DAYS = frozenset(
    """
    monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur thurs fri
    sat sun january february march april may june july august september october november
    december jan feb mar apr jun jul aug sep sept oct nov dec
    """.split()  # noqa: SIM905 (a word list reads better as words)
)
DEMO = "DEMO"  # the file that marks a vault `proxenos demo` made up

Send = Callable[[dict, str], None]  # (the draft's chat, the text) → sent, or raises


def is_demo(vault: Path) -> bool:
    """Whether the vault is one `proxenos demo` made up, which nothing is ever sent from."""
    return (vault / DEMO).is_file()


def run(vault: Path, now: datetime | None = None, senders: dict[str, Send] | None = None) -> dict:
    """One sync's turn: send what was queued and is still fine to send, then queue what now
    qualifies, and write the state the page shows."""
    now = now or datetime.now(UTC)
    folder = vault / "clones" / "outbox"
    rules = read_rules(folder / "rules.json")
    routes = {} if is_demo(vault) else _routes()
    log = _jsonl(folder / "log.jsonl")
    evidence = _evidence(vault, log, _unanswered(vault, now))
    earned = {}
    for ch, rule in rules["channels"].items():
        e = evidence.get(ch, {"n": 0, "unchanged": 0})
        earned[ch] = (
            e["n"] >= rule["min_measured"] and wilson(e["unchanged"], e["n"]) >= rule["min_share"]
        )
    allowed = {
        ch
        for ch, rule in rules["channels"].items()
        if rules["enabled"] and rule["on"] and earned[ch] and routes.get(ch)
    }
    cancelled = {e.get("draft_id") for e in _jsonl(folder / "cancelled.jsonl")}
    today = now.date().isoformat()
    sent_today = sum(1 for e in log if e.get("ok") and str(e.get("at", "")).startswith(today))
    held = {e.get("draft_id") for e in log if e.get("held")}  # left for the user, logged once
    previous = _json(folder / "state.json") or {}
    # The drafts that could go out now, for the apps allowed to send.
    replies = {r["id"]: r for r in _replies(vault, now, allowed)}
    stats = {"outbox_sent": 0, "outbox_failed": 0, "outbox_held": 0}

    def hold(draft: dict) -> None:
        if draft["id"] not in held:
            _log(folder, draft, routes[draft["channel"]], now, held=draft["held"])
            held.add(draft["id"])
            stats["outbox_held"] += 1

    queue = []
    for item in previous.get("queue", []):
        draft = replies.get(item.get("draft_id"))
        if item.get("draft_id") in cancelled or not draft or draft["channel"] not in allowed:
            continue  # cancelled, changed, answered, or no longer allowed: it doesn't go
        if draft["held"]:  # checked again as it goes, against the chat as it is now
            hold(draft)
            continue
        if item.get("sends_at", "") > _iso(now):
            queue.append(item)
            continue
        if sent_today >= rules["daily_limit"]:
            queue.append(item)  # waits for tomorrow's allowance
            continue
        route = routes[draft["channel"]]
        text = draft["text"] + (SIGN if rules["channels"][draft["channel"]]["sign"] else "")
        try:
            ((senders or {}).get(route) or SENDERS[route])(draft["thread"], text)
        except Exception as e:  # noqa: BLE001 - one failure is logged; it must not stop the sync
            _log(folder, draft, route, now, error=" ".join(str(e).split())[:300])
            stats["outbox_failed"] += 1
            continue
        _log(folder, draft, route, now)
        _mark_sent(draft["path"])
        sent_today += 1
        stats["outbox_sent"] += 1

    waiting = {item["draft_id"] for item in queue}
    for draft in replies.values():
        if draft["channel"] not in allowed or draft["id"] in waiting | cancelled | held:
            continue
        if draft["held"]:
            hold(draft)
        else:
            queue.append(
                {
                    "draft_id": draft["id"],
                    "channel": draft["channel"],
                    "to": draft["to"],
                    "queued_at": _iso(now),
                    "sends_at": _iso(now + WAIT),
                }
            )
    state = {
        "generated": _iso(now),
        "routes": routes,
        "closeness": _closeness(vault),
        "evidence": {
            ch: e | {"lower": round(wilson(e["unchanged"], e["n"]), 3)}
            for ch, e in evidence.items()
        },
        "earned": earned,
        "queue": queue,
        "sent_today": sent_today,
    }
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write(folder / "state.json", json.dumps(state, ensure_ascii=False, indent=1))
    return stats | {"outbox_queued": len(queue)}


def read_rules(path: Path) -> dict:
    """rules.json as the page reads it: a switch is on only when exactly true, and a number
    missing or outside the page's limits is its default, the stricter value."""
    raw = _json(path) or {}
    rules = {"enabled": raw.get("enabled") is True, "daily_limit": 10, "channels": {}}
    if _int(raw.get("daily_limit"), 1, 50):
        rules["daily_limit"] = raw["daily_limit"]
    given = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    for ch in CHANNELS:
        c = given.get(ch) if isinstance(given.get(ch), dict) else {}
        rule = dict(DEFAULT_RULE, on=c.get("on") is True, sign=c.get("sign") is True)
        # An older file's bar on the mean closeness is read as the bar on the share.
        share = c.get("min_share", c.get("min_closeness"))
        if isinstance(share, int | float) and not isinstance(share, bool) and 0.5 <= share <= 1:
            rule["min_share"] = min(float(share), MAX_SHARE)
        if _int(c.get("min_measured"), 1, 100):
            rule["min_measured"] = c["min_measured"]
        rules["channels"][ch] = rule
    return rules


def _replies(vault: Path, now: datetime, allowed: set[str]) -> list[dict]:
    """The reply drafts that could go out, on the `allowed` apps: nobody has touched them, they're
    for someone who isn't new, nothing is left to fill in or ask, and their chat still waits on
    what they answer. Each says why it must be held instead (see _held), or None."""
    folder = vault / "clones" / "drafts"
    edited = work._latest(folder / "feedback.jsonl", "draft_id", ("edit",))
    current = {work.reply_key(c): c for c in chats.waiting(vault, now)}
    found = []
    for path in sorted(folder.glob("reply-*.md")):
        text = path.read_text(encoding="utf-8")
        fields, front = work._front(text) or {}, work._FRONT.match(text)
        chat = current.get(path.stem)
        if not front or not chat or fields.get("status") != "draft" or path.stem in edited:
            continue
        channel = _SOURCE_CHANNEL.get(chat["source"], chat["source"])
        if channel not in allowed:
            continue
        body = text[front.end() :].strip()
        if not body or _PLACEHOLDER.search(body) or json.loads(fields.get("asks") or "[]"):
            continue
        if chat["source"] == "slack" and "/" in chat["chat"].split("/", 1)[1]:
            continue  # a channel thread, not a direct message
        if chat.get("first"):
            continue  # someone new's first email: the user answers that one themselves
        found.append(
            {
                "id": path.stem,
                "path": path,
                "channel": channel,
                "to": fields.get("to", ""),
                "thread": {"source": chat["source"], "chat": chat["chat"], "last": chat["id"]},
                "text": body,
                "held": _held(vault, chat, body, fields),
            }
        )
    return found


def _held(vault: Path, chat: dict, body: str, fields: dict) -> str | None:
    """Why a reply mustn't go out on its own, or None. It must reach one person (_group) and
    carry nothing from outside its own conversation (_outside). A link, an email address or a
    number in it that the chat never had is one the model may have made up, and a model that
    makes up where to go, whom to write or what to pay isn't the one to send it. And an email
    reply goes where the mail it answers says replies go, so only where that's its sender."""
    said = [m["text"] for m in [*chat["recent"], *chat["waiting"]]] + list(chat["own"])
    folded = "\n".join(said).casefold()
    if why := _group(vault, chat) or _outside(chat, body, fields, said):
        return why
    for link in [*links.find(body), *(w.rstrip(".,;:!?*") for w in _WWW.findall(body))]:
        if link.casefold() not in folded:
            return f"it has a link the chat doesn't ({link})"
    for address in _EMAIL.findall(body):
        if address.casefold() not in folded:
            return f"it has an email address the chat doesn't ({address})"
    known = [re.sub(r"\D", "", n) for text in said for n in _NUMBER.findall(text)]
    for number in _NUMBER.findall(body):
        digits = re.sub(r"\D", "", number)
        if len(digits) >= DIGITS and not any(digits in k for k in known):
            return f"it has a number the chat doesn't ({number.strip()})"
    if chat["source"] == "email":
        answered = _answered(vault, chat)
        if answered is None or "reply_to" not in answered:
            return "the mail it answers was read before Proxenos kept its Reply-To; sync mail again"
        sender = str(answered.get("from_address") or "").lower()
        if any(str(a).lower() != sender for a in answered.get("reply_to") or []):
            return "the mail it answers asks for replies to another address (Reply-To)"
    return None


def _group(vault: Path, chat: dict) -> str | None:
    """Why a reply might reach more than one person, or None when its chat is known to be with
    one: for email, the mail it answers came from one address to the user alone; for a chat,
    every record of it in the months the conversation spans says it's direct. A record that
    doesn't say counts against it: what can't be known is held."""
    if chat["source"] == "email":
        answered = _answered(vault, chat)
        me = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
        if answered is None or not me:
            return "who else the mail it answers went to can't be told"
        others = {
            a.lower()
            for entry in [*(answered.get("to") or []), *(answered.get("cc") or [])]
            for a in chats._ADDRESS.findall(str(entry))
        }
        if others - me or len(chats._ADDRESS.findall(str(answered.get("from_address")))) != 1:
            return "the mail it answers went to others too"
        return None
    if chat["source"] not in chats._SOURCES:
        return "it's a chat Proxenos can't tell is with one person"
    stream, _ = chats._SOURCES[chat["source"]]
    key = "conversation_id" if chat["source"] in ("linkedin", "twitter") else "chat_id"
    months = {m["ts"][:7] for m in [*chat["recent"], *chat["waiting"]]}
    paths = sorted((vault / "raw" / chat["source"] / stream).glob("*.jsonl"))
    records = [
        r
        for r in chats._records([p for p in paths if p.stem in months])
        if str(r.get(key)) == chat["chat"]
    ]
    if not records or any(_kind(chat["source"], r) != "direct" for r in records):
        return "it's a group, or its records don't say it's with one person"
    return None


def _kind(source: str, record: dict) -> str | None:
    """Whether a chat's record says it's "direct" or a "group", or None when it doesn't. A
    LinkedIn export says it by whom each message is to: one person, or several."""
    if source in ("whatsapp", "facebook", "instagram"):
        return record.get("chat_type")
    if kind := record.get("conversation_type"):
        return kind
    to = str(record.get("to") or "").strip() if source == "linkedin" else ""
    return ("group" if "," in to else "direct") if to else None


def _outside(chat: dict, body: str, fields: dict, said: list[str]) -> str | None:
    """Why a reply may carry something from outside its own conversation, or None: its prompt
    held anything beyond the chat (drew_on, which the drafting code sets from what it put in,
    not the model: memory's research, the person's records elsewhere, Care, the user's notes,
    the calendar), or a draft from before that was kept, which can't say; or the draft says it
    rested on something (found, the model's own word). And, for what's in every draft (the
    self-model, the user's own writing), a word of health, or a capitalised word that isn't a
    sentence's first, a day, a month, the two people's own names or anywhere in the chat or the
    user's own messages there."""
    drew = _drew_on(fields)
    if drew is None:
        return "it was drafted before Proxenos kept what its prompt held beyond the chat"
    if drew:
        return f"its prompt held more than this chat ({', '.join(_DREW[d] for d in drew)})"
    if work._one_line(fields.get("found")):
        return "it rests on what your memory holds beyond this chat"
    if health := voice._HEALTH.search(body):
        return f"it mentions health ({health[0]})"
    names = [chat.get("name") or "", env("NAME")]
    names += [m.get("sender") or "" for m in [*chat["recent"], *chat["waiting"]]]
    known = {w.casefold() for text in [*said, *names] for w in _WORD.findall(text)} | _DAYS
    for word in _WORD.finditer(body):
        name = word[0]
        if len(name) < 2 or not name[0].isupper() or name.isupper():
            continue  # "I", "OK": not a name
        before = body[: word.start()].rstrip(" \t\"'“‘(*_")
        if not before or before[-1] in ".!?:\n/…":
            continue  # a sentence's first word
        if name.casefold() not in known:
            return f"it names something the chat doesn't ({name})"
    return None


_DREW = {  # work.DREW_ON, as a held reply's reason says each
    "memory": "what memory found",
    "person": "their records elsewhere",
    "care": "your health care",
    "notes": "your notes",
    "calendar": "your calendar",
}


def _drew_on(fields: dict) -> list[str] | None:
    """What a reply's prompt held beyond its chat, as the drafting code wrote it (work.DREW_ON),
    or None when the draft doesn't say, or says it in a way the code never writes."""
    try:
        drew = json.loads(fields.get("drew_on") or "")
    except ValueError:
        return None
    if not isinstance(drew, list) or not all(d in _DREW for d in drew):
        return None
    return drew


def _answered(vault: Path, chat: dict) -> dict | None:
    """The mail an email reply answers, the chat's newest message, from its month's files."""
    month = chat["waiting"][-1]["ts"][:7]
    paths = sorted((vault / "raw" / "email").glob(f"*/{month}.jsonl"))
    return next((r for r in chats._records(paths) if str(r.get("id")) == chat["id"]), None)


def _routes() -> dict[str, str | None]:
    """How each app can send from this Mac now, or None."""
    routes: dict[str, str | None] = dict.fromkeys(CHANNELS)
    if shutil.which("osascript") and Path("/System/Applications/Mail.app").exists():
        routes["email"] = "apple_mail"
    if token := os.environ.get("BEEPER_ACCESS_TOKEN"):
        try:
            networks = {str(a.get("network", "")).lower() for a in _beeper(token)("/v1/accounts")}
        except (SystemExit, OSError, ValueError):
            networks = set()
        for ch, names in _BEEPER_NETWORKS.items():
            if networks & names:
                routes[ch] = "beeper"
    return routes


_BEEPER_NETWORKS = {
    "whatsapp": {"whatsapp"},
    "instagram": {"instagram"},
    "messenger": {"messenger", "facebook messenger", "facebook"},
    "x": {"x", "twitter", "x (twitter)"},
    "linkedin": {"linkedin"},
}


def _evidence(vault: Path, log: list[dict], unanswered: list[dict]) -> dict[str, dict]:
    """The track record per app that matches what the outbox sends, untouched drafts: of the
    reply drafts measured (fidelity.json) that the user didn't act on (USED in the page's
    feedback.jsonl, or a Think thread started from it) and that the outbox didn't send itself
    (an ok line in `log`), how many (n) and how many came out nearly unchanged (unchanged).
    The outbox would have sent one whose chat the user never answered too, and nothing says
    they'd have sent it, so each of those (`unanswered`) counts in n as not unchanged."""
    folder = vault / "clones" / "drafts"
    measured = (_json(folder / "fidelity.json") or {}).get("drafts")
    measured = [m for m in measured if isinstance(m, dict)] if isinstance(measured, list) else []
    used = set(work._latest(folder / "feedback.jsonl", "draft_id", USED)) | _thought(vault)
    used |= {e.get("draft_id") for e in log if e.get("ok")}
    found: dict[str, dict] = {}
    for m in measured:
        draft, closeness = m.get("id"), m.get("closeness")
        if not isinstance(draft, str) or not draft.startswith("reply-") or draft in used:
            continue
        if not isinstance(closeness, int | float) or isinstance(closeness, bool):
            continue
        e = found.setdefault(_SOURCE_CHANNEL.get(m.get("source"), m.get("source")), {"n": 0})
        e["n"] += 1
        e["unchanged"] = e.get("unchanged", 0) + (closeness >= NEARLY)
    answered = {m.get("id") for m in measured}
    for u in unanswered:
        if u.get("draft_id") in used | answered:
            continue
        e = found.setdefault(_SOURCE_CHANNEL.get(u.get("source"), u.get("source")), {"n": 0})
        e["n"] += 1
        e["unchanged"] = e.get("unchanged", 0)
        e["unanswered"] = e.get("unanswered", 0) + 1
    return found


def _unanswered(vault: Path, now: datetime) -> list[dict]:
    """The reply drafts whose chat the user didn't answer within fidelity's WINDOW of the draft,
    so fidelity never measured them: {draft_id, source, drafted}. Kept in the outbox's own
    unanswered.jsonl as they're found, since the drafts clone removes such a draft once its chat
    moves on or a month goes by, and the evidence must not forget them. Fidelity runs just
    before the outbox in a sync, so a draft answered in time is marked sent by then."""
    folder = vault / "clones" / "outbox"
    kept = _jsonl(folder / "unanswered.jsonl")
    known = {u.get("draft_id") for u in kept}
    until = _iso(now - fidelity.WINDOW)
    measured = (_json(vault / "clones" / "drafts" / "fidelity.json") or {}).get("drafts")
    answered = {m.get("id") for m in measured or [] if isinstance(m, dict)}
    new = []
    for path in sorted((vault / "clones" / "drafts").glob("reply-*.md")):
        try:
            fields = work._front(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError):
            continue
        draft, created = fields.get("id") or path.stem, fields.get("created") or ""
        thread = fidelity._json(fields.get("thread"))
        if draft in known | answered or not isinstance(thread, dict) or not created:
            continue
        # Only a draft still waiting, or one the user discarded: not one they approved or
        # marked sent, nor one filed away as needing no reply.
        if fields.get("status") in ("draft", "discarded") and created <= until:
            new.append({"draft_id": draft, "source": thread.get("source"), "drafted": created})
    if new:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (folder / "unanswered.jsonl").open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(u, ensure_ascii=False) + "\n" for u in new)
        (folder / "unanswered.jsonl").chmod(0o600)
    return kept + new


def _thought(vault: Path) -> set[str]:
    """The drafts the user thought through in Think: each thread's draft it started from."""
    found = set()
    for path in (vault / "clones" / "think").glob("*.json"):
        context = (_json(path) or {}).get("context")
        if isinstance(context, dict) and context.get("kind") == "draft":
            found.add(context.get("id"))
    return found


def wilson(k: int, n: int) -> float:
    """The share that k successes in n show with 95% confidence: the lower bound of the Wilson
    score interval. With all n successes it is n / (n + Z²), so a share of 0.9 needs 35."""
    if n <= 0:
        return 0.0
    p = k / n
    spread = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    return (p + Z * Z / (2 * n) - spread) / (1 + Z * Z / n)


def needed(share: float) -> int:
    """The fewest untouched drafts that could show `share`: every one of them unchanged."""
    return math.ceil(share * Z * Z / (1 - share))


def _closeness(vault: Path) -> dict:
    """Every measured draft's record per app, from fidelity.json's per-source means, as the
    page showed it before the evidence: what all drafts, used or not, came to."""
    data = _json(vault / "clones" / "drafts" / "fidelity.json") or {}
    return {
        _SOURCE_CHANNEL.get(source, source): s
        for source, s in (data.get("by_source") or {}).items()
    }


# How each route sends.


def _send_mail(thread: dict, text: str) -> None:
    """Reply in the thread with the Mail app: to the message the reply answers, found by its
    Message-ID, so it goes from the account that mail came to. A "Subject:" line is dropped."""
    body = re.sub(r"^\s*subject\s*:.*\n+", "", text, count=1, flags=re.IGNORECASE)
    message_id = thread["last"].strip("<>")
    script = """on run argv
    tell application "Mail"
        set found to (every message of inbox whose message id is (item 1 of argv))
        if found is {} then error "the mail this answers isn't in the Mail inbox"
        set answer to reply (item 1 of found) with opening window false
        set content of answer to (item 2 of argv)
        send answer
    end tell
end run"""
    done = subprocess.run(
        ["osascript", "-e", script, message_id, body],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(f"Mail: {done.stderr.strip()[:200]}")


def send_mail(address: str, subject: str, body: str, attachment: Path | None = None) -> None:
    """A new email with the Mail app, from its default account or PROXENOS_MAIL_FROM, with one
    file attached. Only an errand's Send calls it, for the one message the user pressed it on."""
    script = """on run argv
    set attached to missing value
    if (item 4 of argv) is not "" then set attached to (POSIX file (item 4 of argv)) as alias
    tell application "Mail"
        set m to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv), visible:false}
        tell m
            make new to recipient at end of to recipients with properties {address:(item 1 of argv)}
            if (item 5 of argv) is not "" then set sender to (item 5 of argv)
            if attached is not missing value then
                make new attachment with properties {file name:attached} at after the last paragraph
            end if
        end tell
        delay 3
        send m
    end tell
end run"""
    done = subprocess.run(
        [
            "osascript",
            "-e",
            script,
            address,
            subject,
            body + "\n",
            str(attachment or ""),
            os.environ.get("PROXENOS_MAIL_FROM", ""),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(f"Mail: {done.stderr.strip()[:200]}")


def _send_beeper(thread: dict, text: str) -> None:
    """Send in the chat through Beeper: a chat read through Beeper by its id, a WhatsApp chat by
    the phone number in its id."""
    fetch = _beeper(os.environ.get("BEEPER_ACCESS_TOKEN", ""))
    chat_id = (
        thread["chat"].removeprefix("beeper:") if thread["chat"].startswith("beeper:") else None
    )
    if chat_id is None and thread["source"] == "whatsapp":
        chat_id = _beeper_whatsapp_chat(fetch, thread["chat"])
    if not chat_id:
        raise RuntimeError("no Beeper chat for this conversation")
    beeper_post = _beeper(os.environ.get("BEEPER_ACCESS_TOKEN", ""), method="POST")
    beeper_post(f"/v1/chats/{urllib.parse.quote(chat_id, safe='')}/messages", {"text": text})


def _beeper_whatsapp_chat(fetch: Callable, jid: str) -> str | None:
    """The Beeper chat with the WhatsApp contact whose number is in `jid` (digits@s.whatsapp.net)."""
    digits = jid.split("@")[0]
    if not digits.isdigit():
        return None
    page = fetch("/v1/chats?limit=200")
    for chat in page.get("items") or []:
        if "whatsapp" not in str(chat.get("network", "")).lower() or chat.get("type") != "single":
            continue
        people = (chat.get("participants") or {}).get("items") or []
        if any(re.sub(r"\D", "", str(p.get("phoneNumber") or "")) == digits for p in people):
            return chat["id"]
    return None


def _beeper(token: str, method: str = "GET") -> Callable:
    """A Beeper Desktop API call, as the reader makes them, or a POST with a JSON body."""
    if method == "GET":
        return beeper._fetcher(token)

    def post(path: str, body: dict) -> dict:
        request = urllib.request.Request(
            beeper.BASE + path,
            json.dumps(body).encode(),
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    return post


SENDERS: dict[str, Send] = {"apple_mail": _send_mail, "beeper": _send_beeper}


# Files.


def _mark_sent(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    _write(path, re.sub(r"(?m)^status:.*$", "status: sent", text, count=1))


def _log(
    folder: Path,
    draft: dict,
    route: str,
    now: datetime,
    error: str | None = None,
    held: str | None = None,
) -> None:
    """One attempt in log.jsonl: sent, failed with its error, or held for the user with why
    (which the page shows as its error)."""
    if held:
        error = f"Held for you to send: {held}"
    entry = {
        "draft_id": draft["id"],
        "channel": draft["channel"],
        "to": draft["to"],
        "at": _iso(now),
        "via": route,
        "ok": error is None,
        "error": error,
        **({"held": held} if held else {}),
    }
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (folder / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    (folder / "log.jsonl").chmod(0o600)


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            found.append(entry)
    return found


def _int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
