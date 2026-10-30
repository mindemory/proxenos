"""A voice model: a small open model fine-tuned on this computer on the user's own writing, so
reply drafts sound like them with no paid model behind them. Optional, and off until the voice
model setting names it (PROXENOS_VOICE_MODEL, see proxenos.llm). docs/voice-model.md has the how-to.

`proxenos voice build` writes the training set into vault/voice/, readable only by the user. Each
example is a conversation as it stood when the user answered someone, and what they sent, as
proxenos.chats reads the chats in raw/ (direct chats, Slack threads they're in, and email threads
of every month), and only where what they answered says something, as a chat must to get a
draft. Their consecutive messages within BURST are one answer, one per line. Then their own
longer writing: each sent email that starts a thread (from its subject) and each LinkedIn post
in the export's Shares CSV under exports/. Only the last YEARS, at most PER_CHAT answers a
conversation (the newest), so one long chat doesn't drown the rest. Links, addresses and long
numbers are blanked as the care clone blanks them before its model call.

The newest tenth of the conversations, by their last message, is held out: those answers go to
eval.jsonl for `eval` and data/test.jsonl, never into training. Of the rest, one conversation in
VALID goes to data/valid.jsonl, for the loss mlx-lm reports while it trains.

`train` LoRA fine-tunes the base model with mlx-lm (Apple silicon only) into vault/voice/adapter.
`serve` runs mlx-lm's server with it on 127.0.0.1, which drafts reach as PROXENOS_VOICE_MODEL=mlx.
`eval` drafts the newest held-out answer in each held-out chat with the base model, the fine-tuned
one and the drafting model set up now, given the prompt reply drafts get, with the examples of
the user's writing proxenos.voice picks from what they wrote before it, and scores each by
how much of it survived into what the user sent (fidelity's closeness). `score` reads texts (a
post, an essay, a web page) paragraph by paragraph and says how much more likely the fine-tuned
model finds each than the base model does: how much it reads like the user, next to the same
measure on their own held-out emails and posts. Everything stays here:
the base model's weights come from Hugging Face once, and nothing else leaves the computer.
"""

import argparse
import bisect
import hashlib
import html
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median

from proxenos import chats, links, llm
from proxenos.clones import care
from proxenos.config import env
from proxenos.ingest import linkedin

# Gemma 4 E4B at 4 bits: 5 GB, for a Mac with 32 GB; with 16 GB, mlx-community/gemma-4-e2b-it-4bit
# (3.6 GB). Not Qwen3.5: mlx trains its DeltaNet layers one token at a time, which runs out of
# memory here. Thinking is switched off for any model that has it: a draft doesn't need it.
BASE = "mlx-community/gemma-4-e4b-it-4bit"
NO_THINKING = {"enable_thinking": False}
YEARS = 5
PER_CHAT = 40
HELD_OUT = 0.1
VALID = 20
VALID_MAX = 400
BURST = timedelta(minutes=15)  # as fidelity counts what was sent
CONTEXT_CHARS = 3000  # the most of a conversation shown, its newest lines
ANSWER_CHARS = 2000  # so that with the conversation it mostly fits MAX_SEQ tokens
# Training: 1000 steps of 4 examples, about two hours on an M1 Pro with 32 GB. One example a
# pass, four passes a step: a vocabulary this big makes large logits.
ITERS = 1000
BATCH = 1
ACCUMULATE = 4
# Smaller GPU command buffers, so macOS doesn't stop training for holding up the screen.
SMALL_BUFFERS = {"MLX_MAX_OPS_PER_BUFFER": "4", "MLX_MAX_MB_PER_BUFFER": "16"}
LAYERS = 16
LEARNING_RATE = 1e-4
MAX_SEQ = 1536
EVAL_N = 60
MODELS = ("base", "tuned", "current")
SCORE_WORDS = 8  # a paragraph shorter than this says too little to score
REFERENCE = 30  # of the user's own held-out emails and posts, scored the same way
REFERENCE_WORDS = 30
# What a text to score is asked as, by its kind, as the training set asked for one.
KINDS = {"post": "A LinkedIn post.", "email": "A new email to someone.", "message": "A message."}
_WHERE = {
    "whatsapp": "WhatsApp",
    "linkedin": "LinkedIn",
    "facebook": "Messenger",
    "instagram": "Instagram",
    "twitter": "X",
    "slack": "Slack",
    "email": "Email",
}
_SYSTEM = """\
You are {person}. Write {person}'s next message here, as they would write it: their language, \
length, case, punctuation and emoji. Several short messages go one per line. Only the message, \
nothing around it."""
_TIME = re.compile(r"^\s*\[[\d: -]+\]\s*")


def system(person: str) -> str:
    return _SYSTEM.format(person=person)


def prompt(chat: dict, person: str) -> str:
    """What the voice model answers, the same in training and drafting: where, with whom, and
    the chat's newest lines up to CONTEXT_CHARS, oldest first, times UTC, the newest cut to its
    start if it alone is longer. `chat` is shaped as chats.waiting gives it (source, name,
    recent, waiting)."""
    name = chat.get("name") or "them"
    lines = [
        f"[{m['ts'][:16].replace('T', ' ')}] "
        f"{person if m['mine'] else m.get('sender') or name}: {redact(m['text'])}"
        for m in [*chat.get("recent", []), *chat["waiting"]]
    ]
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        if kept and size + len(line) > CONTEXT_CHARS:
            break
        if len(line) > CONTEXT_CHARS:
            line = line[: CONTEXT_CHARS - 1].rsplit(" ", 1)[0] + "…"
        kept.append(line)
        size += len(line) + 1
    where = _WHERE.get(chat["source"], chat["source"])
    return f"{where}, with {name}:\n" + "\n".join(reversed(kept))


def reply(chat: dict, person: str) -> str:
    """The voice model's reply to a chat waiting on the user (raises llm.ModelError)."""
    return clean(llm.ask_voice(prompt(chat, person), system(person)), person)


def clean(text: str, person: str) -> str:
    """A draft as the user would send it: no thinking, and no "[time] Name:" in front, which a
    model copying the conversation's lines sometimes writes."""
    text = _TIME.sub("", text.split("</think>")[-1].strip(), count=1)
    return text.removeprefix(f"{person}:").strip()[:ANSWER_CHARS]


def redact(text: str) -> str:
    return care._redact(text)


# ── The training set ─────────────────────────────────────────────────────────


def build(vault: Path, now: datetime | None = None) -> dict[str, int]:
    """Write the training set (see the module's notes) and count what's in it."""
    now = now or datetime.now(UTC)
    person = env("NAME", "the person")
    since = _iso(now - timedelta(days=365 * YEARS))
    # Each conversation: its key, when it last said anything, and its examples.
    found: list[tuple[str, str, list[dict]]] = []
    for source, key, messages, *_ in chats.conversations(vault, email_months=0):
        points = _answers(source, messages, since)
        if points:
            last = max(m["ts"] for m in messages)
            found.append((f"{source}/{key}", last, points))
    written = len(found)
    for item in [*_new_emails(vault), *_posts(vault)]:
        if item["ts"] >= since:
            found.append((f"{item['source']}/{item['id']}", item["ts"], [item]))

    found.sort(key=lambda c: c[1])
    cut = len(found) - (max(1, round(len(found) * HELD_OUT)) if len(found) > 1 else 0)
    kept, held = found[:cut], found[cut:]
    train: list[dict] = []
    valid: list[dict] = []
    for key, _, points in kept:
        (valid if _bucket(key) % VALID == 0 else train).extend(_example(p, person) for p in points)
    rng = random.Random(0)
    rng.shuffle(train)
    rng.shuffle(valid)
    held_points = [p | {"conversation": key} for key, _, points in held for p in points]
    test = [_example(p, person) for p in held_points]
    rng.shuffle(test)

    out = vault / "voice"
    out.mkdir(mode=0o700, exist_ok=True)
    out.chmod(0o700)
    _write_jsonl(out / "data" / "train.jsonl", train)
    _write_jsonl(out / "data" / "valid.jsonl", valid[:VALID_MAX])
    _write_jsonl(out / "data" / "test.jsonl", test[:VALID_MAX])
    _write_jsonl(out / "eval.jsonl", [p for p in held_points if p["kind"] == "reply"])
    kinds = defaultdict(int)
    for _, _, points in found:
        for p in points:
            kinds[p["kind"]] += 1
    return {
        "conversations": written,
        "answers": kinds["reply"],
        "emails": kinds["email"],
        "posts": kinds["post"],
        "train": len(train),
        "valid": min(len(valid), VALID_MAX),
        "held_out": len(held_points),
    }


def _answers(source: str, messages: list[dict], since: str = "") -> list[dict]:
    """The newest PER_CHAT times since `since` the user answered someone in a conversation,
    oldest first: the chat as it stood (as chats.waiting gives one), their own messages before
    it, and what they sent."""
    said = sorted((m for m in messages if m["text"]), key=lambda m: m["ts"])
    mine = [i for i, m in enumerate(said) if m["mine"]]
    found: list[dict] = []
    for i in reversed(mine):
        if len(found) == PER_CHAT or said[i]["ts"] < since:
            break
        if i == 0 or said[i - 1]["mine"] or not said[i - 1]["direct"]:
            continue
        start = i
        while start > 0 and not said[start - 1]["mine"]:
            start -= 1
        waiting = said[start:i][-chats.CONTEXT_MESSAGES :]
        text = " ".join(w["text"] for w in waiting)
        if "?" not in text and not links.find(text) and len(text.split()) < 3:
            continue  # nothing a draft would be written for
        first = datetime.fromisoformat(said[i]["ts"])
        earliest = _iso(first - timedelta(days=chats.CONTEXT_DAYS))
        sent = []
        for later in said[i:]:
            if not later["mine"] or datetime.fromisoformat(later["ts"]) > first + BURST:
                break
            sent.append(later["text"])
        own = mine[: bisect.bisect_left(mine, i)][-chats.OWN_MESSAGES :]
        found.append(
            {
                "kind": "reply",
                "source": source,
                "name": said[i - 1]["name"] or said[i - 1]["sender"] or "them",
                "ts": said[i]["ts"],
                "since": waiting[0]["ts"],
                "waiting": [_shown(w) for w in waiting],
                "recent": [
                    _shown(w)
                    for w in said[:start][-chats.CONTEXT_MESSAGES :]
                    if w["ts"] >= earliest
                ],
                "own": [redact(said[j]["text"]) for j in own],
                "sent": "\n".join(_lines(redact(t)) for t in sent),
            }
        )
    return found[::-1]


def _new_emails(vault: Path) -> Iterator[dict]:
    """Each email the user sent that starts a thread: its subject, and what they wrote."""
    seen = set()
    for record in chats._records(sorted((vault / "raw" / "email").glob("*/*.jsonl"))):
        subject = " ".join(str(record.get("subject") or "").split())
        body = str(record.get("body_new") or record.get("body") or "").strip()
        if (
            not record.get("from_me")
            or not isinstance(record.get("ts"), str)
            or not subject
            or chats._REPLY_PREFIX.match(subject)
            or record.get("in_reply_to")
            or len(body.split()) < 3
            or record.get("id") in seen
        ):
            continue
        seen.add(record.get("id"))
        to = [re.sub(r"\s*<[^>]*>", "", str(t)).strip(" \"'") for t in record.get("to") or []]
        to = [redact(t) for t in to if t and "@" not in t] or ["someone"]
        yield {
            "kind": "email",
            "source": "email",
            "id": str(record.get("id") or record["ts"]),
            "ts": record["ts"],
            "ask": f"A new email to {', '.join(to[:3])}. Subject: {redact(subject)}",
            "sent": _paragraphs(redact(body))[:ANSWER_CHARS],
        }


def _posts(vault: Path) -> Iterator[dict]:
    """The user's LinkedIn posts, from each Shares CSV in an export under exports/."""
    for path in sorted((vault / "exports").glob("**/[Ss]hares*.csv")):
        for row in linkedin._rows(path.parent, path.stem, "commentary"):
            post = linkedin._parse(linkedin._share, row, None)
            if not post or not post.get("ts") or not (post.get("text") or "").strip():
                continue
            shared = post.get("shared_url")
            yield {
                "kind": "post",
                "source": "linkedin",
                "id": post["id"],
                "ts": post["ts"],
                "ask": "A LinkedIn post."
                + (f" Sharing a link: {redact(shared)}" if shared else ""),
                "sent": _paragraphs(redact(post["text"]))[:ANSWER_CHARS],
            }


def _example(point: dict, person: str) -> dict:
    """One example in the chat format mlx-lm trains on."""
    ask = prompt(point, person) if point["kind"] == "reply" else point["ask"]
    return {
        "messages": [
            {"role": "system", "content": system(person)},
            {"role": "user", "content": ask},
            {"role": "assistant", "content": point["sent"]},
        ]
    }


def _shown(m: dict) -> dict:
    return {"ts": m["ts"], "mine": m["mine"], "sender": m["sender"], "text": redact(m["text"])}


def _lines(text: str) -> str:
    """A chat message's own line breaks, which chats shows as " / ", back as lines."""
    return re.sub(r"\s+/\s+", "\n", text)


def _paragraphs(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()


def _bucket(key: str) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Records as JSON lines, readable only by the user."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    path.chmod(0o600)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── Training and serving ─────────────────────────────────────────────────────


def train(
    vault: Path,
    base: str = BASE,
    iters: int = ITERS,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    tokens: Callable[[list[dict]], int] | None = None,
) -> dict[str, int]:
    """LoRA fine-tune `base` on the training set with mlx-lm, logging to vault/voice/train.log.
    The base model's weights download once, into Hugging Face's cache. `tokens` counts an
    example's tokens, by the base model's tokenizer unless given."""
    out = vault / "voice"
    if not (out / "data" / "train.jsonl").is_file():
        raise SystemExit("No training set yet: run `proxenos voice build` first.")
    if run is subprocess.run and importlib.util.find_spec("mlx_lm") is None:
        raise SystemExit("Training needs mlx-lm, on a Mac with Apple silicon: pip install mlx-lm")
    left_out = _fit(out, tokens or _tokens(base))
    command = [
        sys.executable,
        "-m",
        "mlx_lm",
        "lora",
        "--model",
        base,
        "--train",
        "--data",
        str(out / "fit"),
        "--adapter-path",
        str(out / "adapter"),
        "--iters",
        str(iters),
        "--batch-size",
        str(BATCH),
        "--grad-accumulation-steps",
        str(ACCUMULATE),
        "--num-layers",
        str(LAYERS),
        "--learning-rate",
        str(LEARNING_RATE),
        "--max-seq-length",
        str(MAX_SEQ),
        "--mask-prompt",
        "--grad-checkpoint",
        "--steps-per-eval",
        "100",
        "--val-batches",
        "25",
        "--save-every",
        "100",
        "--seed",
        "0",
    ]
    (out / "adapter").mkdir(mode=0o700, parents=True, exist_ok=True)
    started = datetime.now(UTC)
    with (out / "train.log").open("a", encoding="utf-8") as log:
        done = run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            env=SMALL_BUFFERS | dict(os.environ),
        )
    if done.returncode:
        raise SystemExit(f"Training stopped (exit {done.returncode}); see {out / 'train.log'}.")
    about = {"base": base, "iters": iters, "trained": _iso(datetime.now(UTC))}
    (out / "voice.json").write_text(json.dumps(about, indent=1))
    minutes = round((datetime.now(UTC) - started).total_seconds() / 60)
    return {"steps": iters, "minutes": minutes, "left out": left_out}


def _fit(out: Path, tokens: Callable[[list[dict]], int]) -> int:
    """The training and validation examples that fit MAX_SEQ tokens, into voice/fit/, and how
    many were left out. mlx-lm cuts a longer one: its answer loses its end, or, when the
    conversation alone is longer, all of it, and an example with nothing to learn from makes
    the loss NaN, which ruins the adapter from there on."""
    left_out = 0
    for name in ("train", "valid"):
        examples = _read_jsonl(out / "data" / f"{name}.jsonl")
        fit = [e for e in examples if tokens(e["messages"]) <= MAX_SEQ]
        left_out += len(examples) - len(fit)
        _write_jsonl(out / "fit" / f"{name}.jsonl", fit)
    return left_out


def _tokens(base: str) -> Callable[[list[dict]], int]:
    """An example's tokens as mlx-lm counts them, by the base model's tokenizer (which comes
    with mlx-lm; only its small tokenizer files download here)."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base)
    return lambda messages: len(tokenizer.apply_chat_template(messages, return_dict=False))


def trained(vault: Path) -> dict | None:
    """What was trained ({base, iters, trained}), or None before `train` has finished."""
    try:
        about = json.loads((vault / "voice" / "voice.json").read_text())
    except (OSError, ValueError):
        return None
    return about if (vault / "voice" / "adapter" / "adapters.safetensors").is_file() else None


def serve(vault: Path, port: int = llm.VOICE_PORT) -> None:
    """Run mlx-lm's server with the adapter on 127.0.0.1:`port`, until stopped."""
    about = trained(vault)
    if about is None:
        raise SystemExit("No voice model yet: run `proxenos voice train` first.")
    command = [
        sys.executable,
        "-m",
        "mlx_lm",
        "server",
        "--model",
        about["base"],
        "--adapter-path",
        str(vault / "voice" / "adapter"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--chat-template-args",
        json.dumps(NO_THINKING),
    ]
    os.execv(sys.executable, command)


# ── Evaluation ───────────────────────────────────────────────────────────────


def evaluate(
    vault: Path,
    n: int = EVAL_N,
    models: tuple[str, ...] = MODELS,
    drafters: dict[str, Callable[[list[dict]], list[str]]] | None = None,
) -> dict:
    """Draft `n` held-out answers with each of `models` and score them against what the user
    sent. Writes vault/voice/eval.json, with every draft, and returns the summary. A model not
    asked for this time keeps its drafts from the last evaluation of the same answers, so the
    voice model can be trained and scored again without drafting the rest again."""
    from proxenos import fidelity  # it reads the work clone, which reads this module

    person = env("NAME", "the person")
    points = _sample(_read_jsonl(vault / "voice" / "eval.jsonl"), n)
    if not points:
        raise SystemExit("Nothing held out to evaluate on: run `proxenos voice build` first.")
    drafters = drafters or _drafters(vault, person)
    before = _drafted(vault / "voice" / "eval.json", points)
    drafts: dict[str, list[str]] = {"last message again": [p["own"][-1] for p in points]}
    for name in MODELS:
        if name in models:
            print(f"voice eval: {name}, {len(points)} drafts", file=sys.stderr, flush=True)
            drafts[name] = drafters[name](points)
        elif name in before:
            drafts[name] = before[name]

    scores = {
        name: [
            round(fidelity._closeness(d, [{"text": p["sent"]}]), 3) for d, p in zip(texts, points)
        ]
        for name, texts in drafts.items()
    }
    summary = {
        name: {
            "mean": round(mean(s), 3),
            "median": round(median(s), 3),
            "words": round(mean(len(d.split()) for d in drafts[name]), 1),
        }
        for name, s in scores.items()
    }
    out = {
        "generated": _iso(datetime.now(UTC)),
        "n": len(points),
        "sent_words": round(mean(len(p["sent"].split()) for p in points), 1),
        "by_source": dict(sorted(_count(p["source"] for p in points).items())),
        "summary": summary,
        "items": [
            {
                "source": p["source"],
                "conversation": p.get("conversation"),
                "sent": p["sent"],
                "drafts": {name: drafts[name][i] for name in drafts},
                "closeness": {name: scores[name][i] for name in scores},
            }
            for i, p in enumerate(points)
        ],
    }
    (vault / "voice").mkdir(mode=0o700, parents=True, exist_ok=True)
    (vault / "voice" / "eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (vault / "voice" / "eval.json").chmod(0o600)
    return {key: out[key] for key in ("generated", "n", "sent_words", "by_source", "summary")}


def table(result: dict) -> str:
    """The evaluation as a markdown table."""
    rows = [
        "| drafts by | closeness, mean | median | words |",
        "|---|---|---|---|",
        *(
            f"| {name} | {s['mean']:.2f} | {s['median']:.2f} | {s['words']:.0f} |"
            for name, s in result["summary"].items()
        ),
    ]
    sources = ", ".join(f"{k} {v}" for k, v in result["by_source"].items())
    return (
        "\n".join(rows)
        + f"\n\n{result['n']} held-out answers ({sources}); what was sent averaged "
        + f"{result['sent_words']:.0f} words."
    )


def _sample(points: list[dict], n: int) -> list[dict]:
    """Up to `n` answers, the newest in each conversation as a draft would be, taking each
    source in turn so all have a share."""
    rng = random.Random(0)
    by_source: dict[str, list[dict]] = defaultdict(list)
    newest: dict[str, dict] = {}
    for p in points:
        if p["own"] and p["ts"] > newest.get(p["conversation"], {}).get("ts", ""):
            newest[p["conversation"]] = p
    for conversation in sorted(newest):
        by_source[newest[conversation]["source"]].append(newest[conversation])
    for found in by_source.values():
        rng.shuffle(found)
    picked: list[dict] = []
    while len(picked) < n and any(by_source.values()):
        for source in sorted(by_source):
            if by_source[source] and len(picked) < n:
                picked.append(by_source[source].pop())
    return picked


def _drafted(path: Path, points: list[dict]) -> dict[str, list[str]]:
    """Each model's drafts of these answers in an earlier evaluation, when it had them all."""
    try:
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        found = {(i["conversation"], i["sent"]): i["drafts"] for i in items}
        rows = [found[(p.get("conversation"), p["sent"])] for p in points]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {name: [row[name] for row in rows] for name in MODELS if all(name in r for r in rows)}


def _drafters(vault: Path, person: str) -> dict[str, Callable[[list[dict]], list[str]]]:
    about = trained(vault)
    base = about["base"] if about else BASE

    def mlx(adapter: Path | None) -> Callable[[list[dict]], list[str]]:
        def draft(points: list[dict]) -> list[str]:
            import mlx.core as mx
            from mlx_lm import generate, load
            from mlx_lm.sample_utils import make_sampler

            if adapter is not None and about is None:
                raise SystemExit("No voice model yet: run `proxenos voice train` first.")
            model, tokenizer = load(base, adapter_path=str(adapter) if adapter else None)
            mx.random.seed(0)
            sampler = make_sampler(temp=llm.VOICE_TEMPERATURE)
            texts = []
            for point in points:
                messages = [
                    {"role": "system", "content": system(person)},
                    {"role": "user", "content": prompt(point, person)},
                ]
                text = tokenizer.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=False, **NO_THINKING
                )
                answer = generate(
                    model, tokenizer, prompt=text, max_tokens=llm.VOICE_TOKENS, sampler=sampler
                )
                texts.append(clean(answer, person))
            del model
            mx.clear_cache()
            return texts

        return draft

    def current(points: list[dict]) -> list[str]:
        from proxenos import voice
        from proxenos.clones import work  # it reads this module

        if not llm.configured():
            raise SystemExit("No drafting model set up to compare with.")
        drafting = work._system(vault / "self")
        written = voice.Writing(vault)
        texts = []
        for point in points:
            # The prompt a reply draft gets, with the user's own writing from before the
            # answer only, as drafting it then would have seen it: never the answer itself.
            before = voice.Writing(vault)
            before.__dict__["messages"] = [m for m in written.messages if m["ts"] < point["ts"]]
            before.__dict__["long"] = [t for t in written.long if t["ts"] < point["ts"]]
            source, key = point["source"], point["conversation"].split("/", 1)[1]
            job = {"for": "reply", "voice": {"channel": source, "chat": (source, key)}}
            job["voice"]["here"] = point["own"]
            text, ask = work._reply_text(point, person, "")
            prompt = text + work._examples(before, job) + ask
            try:
                answer = llm.ask(prompt, system=drafting, schema=work._SCHEMA, effort="medium")
                texts.append(str(answer.get("body") or ""))
            except llm.ModelError as e:
                print(f"voice eval: a draft failed ({e})", file=sys.stderr)
                texts.append("")
        return texts

    return {"base": mlx(None), "tuned": mlx(vault / "voice" / "adapter"), "current": current}


def _count(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item] += 1
    return counts


def _read_jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


# ── How much a text reads like the user ──────────────────────────────────────

Scorer = Callable[[list[tuple[str, str]]], list[tuple[float, int]]]


def score(
    vault: Path,
    texts: dict[str, str],
    kind: str = "post",
    scorers: dict[str, Scorer] | None = None,
) -> dict:
    """Each paragraph of each text, with how much more likely the voice model finds it than
    the base model, in nats a token: above 0 it reads more like the user than the base model
    expects, below 0 less. `reference` is the same for the user's own held-out emails and posts,
    what their writing scores; `texts` maps a name to its text (HTML or plain)."""
    person = env("NAME", "the person")
    ask = KINDS[kind]
    pieces = [(name, para) for name, text in texts.items() for para in paragraphs(text)]
    own = [
        example["messages"]
        for example in _read_jsonl(vault / "voice" / "data" / "test.jsonl")
        if not example["messages"][1]["content"].startswith(tuple(_WHERE.values()))
        and len(example["messages"][2]["content"].split()) >= REFERENCE_WORDS
    ][:REFERENCE]
    asks = [(ask, para) for _, para in pieces] + [(m[1]["content"], m[2]["content"]) for m in own]
    scorers = scorers or _scorers(vault, person)
    base, tuned = scorers["base"](asks), scorers["tuned"](asks)
    gains = [(t - b) / max(n, 1) for (b, n), (t, _) in zip(base, tuned, strict=True)]
    found = [
        {"text": name, "paragraph": para, "score": round(gain, 3)}
        for (name, para), gain in zip(pieces, gains, strict=False)
    ]
    reference = gains[len(pieces) :]
    by_text = {
        name: round(mean(f["score"] for f in found if f["text"] == name), 3)
        for name in texts
        if any(f["text"] == name for f in found)
    }
    return {
        "texts": by_text,
        "paragraphs": found,
        "reference": round(mean(reference), 3) if reference else None,
        "reference_n": len(reference),
    }


def paragraphs(text: str) -> list[str]:
    """A text's paragraphs, as plain text: a web page's without its markup, scripts and
    navigation, a draft's without its front matter, and none shorter than SCORE_WORDS words."""
    text = re.sub(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(\r?\n|\Z)", "", text, flags=re.DOTALL)
    if re.search(r"<(p|div|html|body|li)\b", text, re.IGNORECASE):
        text = re.sub(r"(?is)<(script|style|nav|header|footer|head)\b.*?</\1>", " ", text)
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(
            r"(?i)</?(p|div|li|h\d|br|ul|ol|section|article|blockquote)\b[^>]*>", "\n\n", text
        )
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    found = []
    for block in re.split(r"\n\s*\n", text):
        block = " ".join(
            re.sub(r"^\s*(#+|[-*>]|\d+\.)\s+", "", line) for line in block.splitlines()
        )
        block = " ".join(block.split())
        if len(block.split()) >= SCORE_WORDS:
            found.append(block)
    return found


def score_table(result: dict, shown: int = 6) -> str:
    """The scores, each text's, then its paragraphs that read least like the user."""
    lines = [
        f"Your own held-out emails and posts score {result['reference']:+.2f} "
        f"({result['reference_n']} of them); 0 is no more like you than the base model expects."
        if result["reference"] is not None
        else "No held-out emails or posts to compare with: run `proxenos voice build`.",
        "",
        "| text | score |",
        "|---|---|",
        *(f"| {name} | {value:+.2f} |" for name, value in result["texts"].items()),
    ]
    for name in result["texts"]:
        least = sorted(
            (p for p in result["paragraphs"] if p["text"] == name), key=lambda p: p["score"]
        )
        lines += ["", f"Least like you in {name}:"]
        lines += [f"- {p['score']:+.2f} {p['paragraph'][:120]}" for p in least[:shown]]
    return "\n".join(lines)


def _scorers(vault: Path, person: str) -> dict[str, Scorer]:
    about = trained(vault)
    if about is None:
        raise SystemExit("No voice model yet: run `proxenos voice train` first.")

    def scorer(adapter: Path | None) -> Scorer:
        def logprobs(asks: list[tuple[str, str]]) -> list[tuple[float, int]]:
            import mlx.core as mx
            from mlx_lm import load

            model, tokenizer = load(about["base"], adapter_path=str(adapter) if adapter else None)
            found = []
            for ask, text in asks:
                messages = [
                    {"role": "system", "content": system(person)},
                    {"role": "user", "content": ask},
                ]
                start = tokenizer.apply_chat_template(
                    messages, add_generation_prompt=True, return_dict=False, **NO_THINKING
                )
                ids = mx.array([*start, *tokenizer.encode(text, add_special_tokens=False)])
                logits = model(ids[None, :-1])[0]
                logits = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
                picked = mx.take_along_axis(logits, ids[1:, None], axis=-1)[len(start) - 1 :]
                found.append((picked.sum().item(), picked.size))
            del model
            mx.clear_cache()
            return found

        return logprobs

    return {"base": scorer(None), "tuned": scorer(vault / "voice" / "adapter")}


# ── The command ──────────────────────────────────────────────────────────────


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["build", "train", "serve", "eval", "score"])
    parser.add_argument("files", nargs="*", type=Path, help="for score: texts or web pages")
    parser.add_argument(
        "--kind", choices=list(KINDS), default="post", help="for score: what the texts are"
    )
    parser.add_argument("--base", default=BASE, help=f"the model to train (default {BASE})")
    parser.add_argument("--iters", type=int, default=ITERS, help="training steps")
    parser.add_argument("--port", type=int, default=llm.VOICE_PORT, help="where serve answers")
    parser.add_argument("--n", type=int, default=EVAL_N, help="held-out answers to evaluate on")
    parser.add_argument(
        "--models",
        default=",".join(MODELS),
        help="which to evaluate: base (untrained), tuned, current (the drafting model)",
    )


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.action == "build":
        print(_summary(build(vault)))
    elif args.action == "train":
        print(_summary(train(vault, args.base, args.iters)))
    elif args.action == "serve":
        serve(vault, args.port)
    elif args.action == "score":
        if not args.files:
            raise SystemExit("usage: proxenos voice score FILE [FILE ...]")
        texts = {path.name: path.read_text(encoding="utf-8") for path in args.files}
        print(score_table(score(vault, texts, args.kind)))
    else:
        models = tuple(m for m in args.models.split(",") if m in MODELS)
        print(table(evaluate(vault, args.n, models)))


def _summary(stats: dict[str, int]) -> str:
    return "voice: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items())
