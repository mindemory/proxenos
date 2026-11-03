"""Which of two models writes replies most like the user, judged blind by the user.

Someone choosing what drafts for them, a local model through Ollama (private and free), a hosted
one, or a voice model trained on their writing (proxenos.voicemodel), needs the one that writes as
they would, not the one that writes best, and needs to judge it without knowing which wrote what.
So a round takes the user's own replies in their ROUND most recent conversations, one each, and
has both models draft each of them again; the user sees the conversation and the two drafts as A
and B, in an order drawn for each reply, and picks the one that reads more like them, both or
neither. Only then is it said which model wrote which, beside what they actually sent. A pick
can be changed.

Each reply is held out. A draft is asked for with the chat as chats.waiting would have given it
the moment before the user answered (chats._waiting on the messages before their reply), so a
reply counts only where a draft would have been written then: someone else had the last word,
within chats.DAYS, saying something to answer, and the user had written in that chat before. The
examples of their writing are only what they wrote before it (voice.Writing.until), so no model
sees that reply, anything after it in that chat or anywhere else, nor a draft they changed and
sent after it. The system prompt is the one reply drafts get, as of that moment: the self-model,
the notes they had told Proxenos by then, their calendar from that day. Two things a real draft
has are left out: what research finds in memory, which holds the reply itself and everything
since and can't be bounded by time, and the pages linked in the chat, which may have changed
since and would be fetched again. Both models get the same prompt, so the only difference is
the model.

A drafting model writes through the work clone's own code for a reply (work._reply_job and
work._answered, with its retries) under llm.using, which points those calls at it and logs them
as "compare". A voice model writes as it does for a reply draft (voicemodel.reply), from the same
chat. All of one model's drafts are written before the other's, so two local models aren't
swapped in and out of memory for every reply. Nothing is sent to anyone: a round writes its file.

Per model, the results say the share of picks it won, with a Wilson 95% interval (Wilson, 1927,
which stays inside 0 to 1 and holds up for few picks), how many picks there were (under about
MIN_PICKS they tell little), and how close its drafts came to what the user sent, by fidelity's
measure. A new round skips the replies earlier rounds of the same two models drafted, so the
rounds add up, and `pooled` counts them together.

A round is state/compare/<id>.json, written after each draft so the page can show how far it got,
and its picks go to <id>.picks.jsonl, one line each, the latest for a reply counting: the page's
picks never race a round still being drafted. Both are private to the user.
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

from proxenos import chats, fidelity, llm, setup, voice, voicemodel
from proxenos.clones import work
from proxenos.config import env

ROUND = 10  # replies a round drafts unless asked for another number
MAX_ROUND = 50
MIN_PICKS = 20  # picks under which the intervals are too wide to tell much
TRIES = 5  # of the user's newest replies in a conversation, those tried for one that counts
LISTED = 20  # rounds listed, newest first
FOLDER = Path("state", "compare")
PICKS = ("A", "B", "both", "neither")
VOICE = "voice:"  # in front of a voice model's setting, to tell it from a drafting model
NO_REPLY = "(No reply needed.)"  # a drafting model's draft when it said no answer was needed
Z = 1.96  # for a 95% interval
_ID = re.compile(r"\d{8}T\d{6}Z")


def model(name: str) -> str:
    """A model as a round names it, checked as Settings checks the settings it stands for: a
    drafting model as PROXENOS_MODEL takes one ("ollama:<name>", "local:<name>", or Anthropic's
    by name), or a voice model as "voice:" and what PROXENOS_VOICE_MODEL takes ("voice:mlx",
    "voice:ollama:<name>", "voice:local:<name>"). "voice" alone is the voice model set up now. ValueError otherwise."""
    name = name.strip()
    if name == "voice":
        if not (set_up := env("VOICE_MODEL").strip()):
            raise ValueError(
                "No voice model is set up: name one, as voice:mlx or voice:ollama:<name>."
            )
        name = VOICE + set_up
    if name.startswith(VOICE):
        if not setup._VOICE.fullmatch(name.removeprefix(VOICE)):
            raise ValueError(
                "A voice model is voice:mlx, voice:mlx:<port>, voice:ollama:<name> or "
                "voice:local:<name>."
            )
        return name
    if not setup._MODEL.fullmatch(name):
        raise ValueError(f"{name!r} isn't a model's name.")
    return name


def where(name: str) -> str:
    """Where a model runs: "this computer" or "Anthropic", as the calls log says it."""
    return "this computer" if name.startswith((*llm.LOCAL, VOICE)) else "Anthropic"


def label(name: str) -> str:
    """A model's name as the page shows it."""
    if name.startswith(VOICE):
        return f"voice model {llm.bare(name.removeprefix(VOICE))}"
    return llm.bare(name)


# ── A round ──────────────────────────────────────────────────────────────────


def start(
    vault: Path,
    first: str,
    against: str | None = None,
    n: int = ROUND,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> dict:
    """Draft a new round: the user's replies in their `n` most recent conversations, each by
    `first` and by `against` (the drafting model set up now when None), and what `results`
    says of it. Raises ValueError for a model that isn't one, SystemExit when there's nothing
    to compare on or no key for a hosted model."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    rng = rng or random.SystemRandom()  # nothing the user could guess the order from
    models = [model(first), model(against or env("MODEL", llm.DEFAULT_MODEL))]
    if models[0] == models[1]:
        raise ValueError(f"Both are {models[0]}: name another with --against.")
    for name in models:
        if where(name) == "Anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                f"There's no Anthropic API key to draft with {name}: add one in Settings."
            )
    folder = vault / FOLDER
    done = {  # replies these two have both drafted already; one a round didn't finish is free
        item["key"]
        for r in _rounds(folder)
        if sorted(r["models"]) == sorted(models)
        for item in r["items"]
        if all(d["text"] is not None for d in item["drafts"].values())
    }
    found = held_out(vault, max(1, min(n, MAX_ROUND)), skip=done)
    if not found:
        raise SystemExit(
            "No replies of yours to compare on: a round needs chats where someone wrote to you, "
            "you answered, and you'd written there before"
            + (", and these two models have drafted all of them already." if done else ".")
        )

    while (folder / f"{now:%Y%m%dT%H%M%SZ}.json").exists():  # two rounds started in a second
        now += timedelta(seconds=1)
    path = folder / f"{now:%Y%m%dT%H%M%SZ}.json"
    items = []
    for i, pair in enumerate(found, 1):
        order = models if rng.random() < 0.5 else models[::-1]
        items.append(
            {
                "n": i,
                "key": pair["key"],
                "source": pair["chat"]["source"],
                "name": pair["chat"]["name"],
                "replied": pair["replied"],
                "recent": pair["chat"]["recent"],
                "waiting": pair["chat"]["waiting"],
                "sent": pair["sent"],
                "drafts": {
                    side: {"model": name, "text": None, "closeness": None, "error": None}
                    for side, name in zip(("A", "B"), order, strict=True)
                },
            }
        )
    doc = {
        "id": path.stem,
        "started": _iso(now),
        "updated": _iso(now),
        "models": models,
        "status": "drafting",
        "error": None,
        "items": items,
    }
    _write(path, doc)

    person = env("NAME", "the person")
    written = voice.Writing(vault)  # read once; each reply sees only what came before it
    health = work._health(work._load_json(vault / "clones" / "care" / "care.json"))
    asked = [_asked(vault, pair, written, person, health) for pair in found]
    try:
        for name in models:  # one model's drafts, then the other's
            for k, (item, pair, (prompt, system)) in enumerate(zip(items, found, asked), 1):
                print(f"compare: {label(name)}, {k} of {len(items)}", file=sys.stderr, flush=True)
                side = next(s for s, d in item["drafts"].items() if d["model"] == name)
                _drafted(item, item["drafts"][side], pair["chat"], prompt, system, person)
                doc["updated"] = _iso(datetime.now(UTC))
                _write(path, doc)
    except BaseException as e:  # stopped, or no key after all: say so in the round
        doc |= {"status": "failed", "error": " ".join(str(e).split())[:300] or "It was stopped."}
        _write(path, doc)
        raise
    doc |= {"status": "ready", "updated": _iso(datetime.now(UTC))}
    _write(path, doc)
    return results(vault, doc["id"])


def held_out(vault: Path, n: int, skip: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """The user's replies in their `n` most recent conversations, newest first, one each and
    none of `skip` (by key): each {key, replied, chat, sent}, where chat is the chat as
    chats.waiting would have given it just before they replied, and sent what they sent."""
    found = []
    for source, key, messages, *_ in chats.conversations(vault):
        if pair := _reply(source, key, messages, skip):
            found.append(pair)
    return sorted(found, key=lambda p: p["replied"], reverse=True)[:n]


def _reply(
    source: str, key: str, messages: list[dict], skip: set[str] | frozenset[str]
) -> dict | None:
    """Of the user's TRIES newest replies to someone in a conversation, the newest a draft
    would have been written for, or None."""
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    tried = 0
    for i in range(len(said) - 1, 0, -1):
        if not said[i]["mine"] or said[i - 1]["mine"]:
            continue
        tried += 1
        if tried > TRIES:
            break
        reply = said[i]
        pair_key = hashlib.sha1(f"{source}\0{key}\0{reply['id']}".encode()).hexdigest()[:16]
        try:
            when = datetime.fromisoformat(reply["ts"])
        except ValueError:
            continue
        if pair_key in skip:
            continue
        # The chat as it waited on the user then: only the messages before their reply.
        chat = chats._waiting(
            said[:i],
            _iso(when - timedelta(days=chats.DAYS)),
            _iso(when - timedelta(days=chats.CONTEXT_DAYS)),
        )
        if not chat or chat["name"].casefold() in chats._ASSISTANTS:
            continue
        sent = _burst(said[i:])
        if len(" ".join(sent).split()) < voice.MIN_WORDS:
            continue  # a word or an emoji shows little of how they write
        return {
            "key": pair_key,
            "replied": reply["ts"],
            "chat": {"source": source, "chat": key, **chat},
            "sent": sent,
        }
    return None


def _burst(said: list[dict]) -> list[str]:
    """What the user sent: their messages from the reply on, until someone else wrote, within
    fidelity.BURST of the first, as fidelity counts what was sent."""
    first = datetime.fromisoformat(said[0]["ts"])
    sent = []
    for m in said:
        try:
            if not m["mine"] or datetime.fromisoformat(m["ts"]) > first + fidelity.BURST:
                break
        except ValueError:
            break
        sent.append(m["text"])
    return sent


def _asked(
    vault: Path, pair: dict, written: voice.Writing, person: str, health: str
) -> tuple[str, str]:
    """The prompt and system prompt a reply draft would have had just before the user replied,
    from what was there then, without memory's research or the linked pages."""
    when = datetime.fromisoformat(pair["replied"])
    job = work._reply_job(pair["chat"], person, health, work._today(when))
    prompt = job["prompt"] + work._examples(written.until(pair["replied"]), job) + job["ask"]
    system = work._system(vault / "self", when) + work._shared(vault / "clones" / "drafts", when)
    return prompt, system


def _drafted(item: dict, draft: dict, chat: dict, prompt: str, system: str, person: str) -> None:
    """One model's draft of a held-out reply, with how close it came to what was sent, or why it
    failed: one failed draft doesn't cost the others."""
    name = draft["model"]
    try:
        if name.startswith(VOICE):
            with llm.using(voice=name.removeprefix(VOICE), step="compare"):
                text = voicemodel.reply(chat, person)
        else:
            with llm.using(model=name, step="compare"):
                answer = work._answered(prompt, system, chat)
            needed = answer.get("needed") is not False or work._asked(chat)
            text = str(answer.get("body") or "").strip() if needed else NO_REPLY
        if not text:
            raise llm.ModelError("it wrote nothing")
    except Exception as e:  # noqa: BLE001 - one failed draft must not cost the others
        draft["error"] = " ".join(str(e).split())[:200] or type(e).__name__
        print(f"compare: a draft by {label(name)} failed ({draft['error']})", file=sys.stderr)
        return
    sent = [{"text": text_sent} for text_sent in item["sent"]]
    draft |= {"text": text, "closeness": round(fidelity._closeness(text, sent), 3)}


# ── Picks and results ────────────────────────────────────────────────────────


def pick(vault: Path, round_id: str, n: int, choice: str, now: datetime | None = None) -> dict:
    """Pick for reply `n` of a round: "A", "B", "both" or "neither" (any case). A new pick
    replaces the last; the same one again changes nothing. What `results` then says."""
    choice = {p.casefold(): p for p in PICKS}.get(choice.strip().casefold(), "")
    if not choice:
        raise SystemExit("Pick A, B, both or neither.")
    doc = _round(vault / FOLDER, round_id)
    item = next((i for i in doc["items"] if i["n"] == n), None)
    if item is None:
        raise SystemExit(f"Round {round_id} has no reply {n}.")
    if any(d["text"] is None for d in item["drafts"].values()):
        raise SystemExit(f"Reply {n} doesn't have both drafts to pick from.")
    if doc["picks"].get(n, {}).get("pick") != choice:
        now = now or datetime.now(UTC)
        _append(_picks_path(vault / FOLDER, doc["id"]), {"at": _iso(now), "n": n, "pick": choice})
    return results(vault, doc["id"])


def results(vault: Path, round_id: str | None = None) -> dict:
    """A round, the newest unless named, as the page shows it: each reply blind until it's been
    picked, then which model wrote A and B and what the user sent; how each model fared in it,
    and in every round of the same two models together; the rounds there are; and the models set
    up now, for the page to offer."""
    folder = vault / FOLDER
    rounds = _rounds(folder)
    doc = _round(folder, round_id) if round_id else (rounds[0] if rounds else None)
    listed = [
        {
            "id": r["id"],
            "started": r["started"],
            "status": r["status"],
            "models": [label(name) for name in r["models"]],
            "n": len(r["items"]),
            "picked": len(r["picks"]),
        }
        for r in rounds[:LISTED]
    ]
    voice_model = env("VOICE_MODEL").strip()
    set_up = {
        "drafting": env("MODEL", llm.DEFAULT_MODEL),
        "hosted": llm.DEFAULT_MODEL,  # Anthropic's, by default
        "key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "voice": VOICE + voice_model if setup._VOICE.fullmatch(voice_model) else None,
    }
    if doc is None:
        none = {"round": None, "results": None, "pooled": None, "items": []}
        return none | {"rounds": listed, "set_up": set_up}
    same = [r for r in rounds if sorted(r["models"]) == sorted(doc["models"])]
    drafted = sum(d["text"] is not None or d["error"] is not None for d in _drafts([doc]))
    return {
        "round": {
            "id": doc["id"],
            "started": doc["started"],
            "updated": doc["updated"],
            "status": doc["status"],
            "error": doc["error"],
            "models": [
                {"name": name, "label": label(name), "where": where(name)} for name in doc["models"]
            ],
            "n": len(doc["items"]),
            "drafted": drafted,
        },
        "rounds": listed,
        "results": fared(doc["models"], [doc]),
        "pooled": fared(doc["models"], same) | {"rounds": len(same)} if len(same) > 1 else None,
        "items": [_shown(item, doc["picks"].get(item["n"])) for item in doc["items"]],
        "set_up": set_up,
    }


def fared(models: list[str], rounds: list[dict]) -> dict:
    """How each model fared in `rounds`: picks won, as a share with its Wilson interval, and its
    drafts' closeness to what was sent."""
    picked = [
        (item, chosen["pick"])
        for r in rounds
        for item in r["items"]
        if (chosen := r["picks"].get(item["n"]))
    ]
    total = len(picked)
    each = []
    for name in models:
        won = sum(p in ("A", "B") and item["drafts"][p]["model"] == name for item, p in picked)
        low, high = wilson(won, total)
        mine = [d for d in _drafts(rounds) if d["model"] == name]
        close = [d["closeness"] for d in mine if isinstance(d["closeness"], int | float)]
        each.append(
            {
                "name": name,
                "label": label(name),
                "where": where(name),
                "won": won,
                "share": round(won / total, 3) if total else None,
                "low": low,
                "high": high,
                "closeness": round(mean(close), 3) if close else None,
                "drafted": len(close),
                "failed": sum(d["error"] is not None for d in mine),
            }
        )
    return {
        "picks": total,
        "both": sum(p == "both" for _, p in picked),
        "neither": sum(p == "neither" for _, p in picked),
        "models": each,
        "note": _note(total, each),
    }


def wilson(k: int, n: int, z: float = Z) -> tuple[float | None, float | None]:
    """The Wilson score interval for `k` of `n` (E. B. Wilson, 1927), rounded; (None, None) for
    no picks. Unlike p ± z·se it stays within 0 and 1 and isn't zero wide at 0 of n or n of n."""
    if n <= 0:
        return None, None
    p = k / n
    scale = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / scale
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / scale
    return round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)


def _note(picks: int, each: list[dict]) -> str:
    if not picks:
        return "No picks yet."
    if picks < MIN_PICKS:
        return (
            f"{picks} pick{'s' * (picks != 1)} so far. Under about {MIN_PICKS}, this tells little: "
            "the intervals are wide. Another round adds more."
        )
    first, second = each
    if first["low"] <= second["high"] and second["low"] <= first["high"]:
        return "The intervals overlap, so neither is clearly ahead yet."
    ahead = first if first["won"] > second["won"] else second
    return f"{ahead['label']} won clearly more of your picks."


def _shown(item: dict, chosen: dict | None) -> dict:
    """A reply as the page shows it: its drafts only once both are there, and which model wrote
    each, how close it came and what the user sent only once they've picked."""
    a, b = item["drafts"]["A"], item["drafts"]["B"]
    ready = a["text"] is not None and b["text"] is not None
    failed = a["error"] is not None or b["error"] is not None
    shown = {
        "n": item["n"],
        "source": item["source"],
        "name": item["name"],
        "replied": item["replied"],
        "recent": item["recent"],
        "waiting": item["waiting"],
        "state": "ready" if ready else "failed" if failed else "drafting",
        "a": a["text"] if ready else None,
        "b": b["text"] if ready else None,
        "pick": chosen["pick"] if chosen else None,
        "picked": chosen["at"] if chosen else None,
    }
    if chosen:
        shown |= {
            "a_model": label(a["model"]),
            "b_model": label(b["model"]),
            "a_closeness": a["closeness"],
            "b_closeness": b["closeness"],
            "sent": "\n".join(item["sent"]),
        }
    return shown


def _drafts(rounds: list[dict]) -> list[dict]:
    return [d for r in rounds for item in r["items"] for d in item["drafts"].values()]


# ── Files ────────────────────────────────────────────────────────────────────


def _rounds(folder: Path) -> list[dict]:
    """Every round that can be read, newest first, each with its picks."""
    found = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        if _ID.fullmatch(path.stem) and (doc := _load(path)):
            found.append(doc)
    return found


def _round(folder: Path, round_id: str) -> dict:
    doc = _load(folder / f"{round_id}.json") if _ID.fullmatch(round_id) else None
    if doc is None:
        raise SystemExit(f"There's no round {round_id}.")
    return doc


def _load(path: Path) -> dict | None:
    """A round's file with its picks ({n: {at, pick}}, the latest of each), or None when it
    isn't one."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        shaped = len(doc["models"]) == 2 and all(
            isinstance(item["n"], int) and set(item["drafts"]) == {"A", "B"}
            for item in doc["items"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not shaped:
        return None
    picks: dict[int, dict] = {}
    try:
        lines = _picks_path(path.parent, path.stem).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            chosen = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(chosen, dict)
            and isinstance(chosen.get("n"), int)
            and chosen.get("pick") in PICKS
        ):
            picks[chosen["n"]] = {"at": str(chosen.get("at") or ""), "pick": chosen["pick"]}
    return doc | {"picks": picks}


def _picks_path(folder: Path, round_id: str) -> Path:
    return folder / f"{round_id}.picks.jsonl"


def _write(path: Path, doc: dict) -> None:
    """Swap the round's file in whole, private to the user, so the page never reads half."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        json.dump({k: v for k, v in doc.items() if k != "picks"}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _append(path: Path, line: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line) + "\n")


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── The command ──────────────────────────────────────────────────────────────


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    begin = actions.add_parser("start", help="draft a new round with two models")
    begin.add_argument(
        "--model",
        required=True,
        help="a drafting model (ollama:<name>, local:<name>, or Anthropic's), or voice:mlx, "
        "voice:ollama:<name>, voice:local:<name> or voice (the voice model set up now)",
    )
    begin.add_argument("--against", help="the other model (default: the drafting model set up)")
    begin.add_argument("-n", type=int, default=ROUND, help=f"replies to draft (default {ROUND})")
    choose = actions.add_parser("pick", help="say which draft of a reply reads more like you")
    choose.add_argument("round")
    choose.add_argument("item", type=int)
    choose.add_argument("choice", help="A, B, both or neither")
    results_of = actions.add_parser("results", help="a round and how each model fared, as JSON")
    results_of.add_argument("round", nargs="?", help="default: the newest")


def run(vault: Path, args: argparse.Namespace) -> dict:
    try:
        if args.action == "start":
            return start(vault, args.model, args.against, args.n)
        if args.action == "pick":
            return pick(vault, args.round, args.item, args.choice)
        return results(vault, args.round)
    except ValueError as e:
        raise SystemExit(str(e)) from None
