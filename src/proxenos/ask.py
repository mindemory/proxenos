"""`proxenos ask`: a question, a pasted message or screenshots, answered as the user would think
it through.

The page's Ask view passes one JSON line on stdin: {text, images: [{type, data}]}, data being
base64. First the model reads any screenshots: who wrote what, word for word, and what it is.
Then it looks through the user's memory as a reply does (research.py): the person, if the
screenshot or question names one, and what the answer depends on, by meaning and by words. Then
it answers from the self-model, the "right now" note and what it found, the way the user would,
and, when what they brought is a message to them, drafts their reply in their voice.

Each ask is a file, clones/ask/<id>.json, written first as "working" and then "done" or
"failed", which the page polls; a drafted reply is also saved as a draft (for: ask), so it shows
in Drafts with its actions. The id is the last line printed, for the page's job runner.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from proxenos import llm, research
from proxenos.clones import work
from proxenos.config import env

TEXT_CHARS = 8000
MAX_IMAGES = 4
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")

_SEE = """\
Transcribe these screenshots for {person}, who wants help answering or understanding them. \
For a message, email or chat: who wrote it, to whom, when, and every word, in order. For \
anything else: what it shows, with every name, number, date and line of text. Then, in `from`, \
the name of the one person it's from or about when there is one, as written, else "". Add \
nothing that isn't in the image."""

_SEE_SCHEMA = {
    "type": "object",
    "properties": {"seen": {"type": "string"}, "from": {"type": "string"}},
    "required": ["seen", "from"],
    "additionalProperties": False,
}

_ANSWER = """\
{person} brought you this, as their digital twin. Think it through the way they would, from who \
they are and what their memory shows above, and answer them directly, in `answer`, in plain \
markdown: what it is, what matters in it, what they could do, and what you'd do in their place. \
Where it is a message to them that wants a reply, also draft the reply in their voice for that \
person and kind of message (`draft_body`, with `draft_to` and `draft_channel`); otherwise leave \
draft_body "". Get facts, dates and history right from what was found; never invent any. Say in \
`found` what their memory showed that this rests on, and in `asks` what only they can decide."""

_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "draft_to": {"type": "string"},
        "draft_channel": {"type": "string", "enum": list(work.CHANNELS)},
        "draft_body": {"type": "string"},
        "found": {"type": "string"},
        "asks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "draft_to", "draft_channel", "draft_body", "found", "asks"],
    "additionalProperties": False,
}


def ask(
    vault: Path,
    text: str,
    images: list[dict],
    now: datetime | None = None,
    model: Callable[..., object] = llm.ask,
) -> dict:
    now = now or datetime.now(UTC)
    person = env("NAME", "the person")
    ask_id = f"ask-{now:%Y%m%dT%H%M%SZ}"
    path = vault / "clones" / "ask" / f"{ask_id}.json"
    result = {
        "id": ask_id,
        "at": _iso(now),
        "status": "working",
        "question": text[:TEXT_CHARS],
        "images": len(images),
        "seen": "",
        "answer": "",
        "draft": None,
        "found": "",
        "asks": [],
        "error": None,
    }
    _write(path, result)
    try:
        who = ""
        if images:
            note = f"\n\nWhat they wrote with them: {text}" if text else ""
            seen = model(
                "Transcribe the screenshots." + note,
                system=_SEE.format(person=person),
                schema=_SEE_SCHEMA,
                images=images,
                effort="medium",
            )
            result["seen"], who = str(seen["seen"]).strip(), str(seen["from"]).strip()
        brief = f"What {person} brought:\n{text or '(only screenshots)'}"
        if result["seen"]:
            brief += f"\n\nWhat the screenshots show:\n{result['seen']}"
        about = research.person(vault, who, person) if who else ""
        context = f"{brief}\n\n{about}" if about else brief
        found, _ = research.matter(vault, context, person, model, who or None)
        if found:
            found = f"What {person}'s memory holds that this depends on:\n{found}"
        memory = "\n\n".join(p for p in (about, found) if p)
        answer = model(
            brief + (f"\n\n{memory}" if memory else "") + "\n\n" + _ANSWER.format(person=person),
            system=work._system(vault / "self", now),
            schema=_ANSWER_SCHEMA,
            effort="high",
        )
        result |= {
            "status": "done",
            "answer": str(answer["answer"]).strip(),
            "found": work._one_line(answer.get("found")),
            "asks": [work._one_line(a) for a in answer.get("asks") or [] if work._one_line(a)][:5],
        }
        if body := str(answer.get("draft_body") or "").strip():
            result["draft"] = {
                "to": work._one_line(answer["draft_to"]),
                "channel": answer["draft_channel"],
                "body": body,
            }
            _save_draft(vault, ask_id, result, now)
    except Exception as e:  # noqa: BLE001 - the page shows why it failed, rather than spinning
        result |= {"status": "failed", "error": " ".join(str(e).split())[:500]}
    _write(path, result)
    return result


def _save_draft(vault: Path, ask_id: str, result: dict, now: datetime) -> None:
    draft = result["draft"]
    channel = draft["channel"] if draft["channel"] in work.CHANNELS else "other"
    work._write(
        vault / "clones" / "drafts" / f"{ask_id}.md",
        work.render(
            {
                "id": ask_id,
                "title": work._clip(f"Reply to {draft['to'] or 'them'}", work.TITLE_CHARS),
                "kind": "reply",
                "for": "ask",
                "channel": channel,
                "to": draft["to"],
                "created": _iso(now),
                "status": "draft",
                "found": result["found"],
                "asks": result["asks"],
                "body": draft["body"],
            }
        ),
    )


def read_request(line: str) -> tuple[str, list[dict]]:
    """The page's JSON line as (text, images), keeping only what's well formed."""
    data = json.loads(line or "{}")
    text = str(data.get("text") or "")[:TEXT_CHARS]
    images = [
        {"type": i["type"], "data": i["data"]}
        for i in (data.get("images") or [])[:MAX_IMAGES]
        if isinstance(i, dict) and i.get("type") in IMAGE_TYPES and isinstance(i.get("data"), str)
    ]
    if not text.strip() and not images:
        raise SystemExit("Ask something, or add a screenshot.")
    return text, images


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("question", nargs="*", help="a question; without one, a JSON line on stdin")


def run(vault: Path, args: argparse.Namespace) -> None:
    if args.question:
        text, images = " ".join(args.question), []
    else:
        text, images = read_request(sys.stdin.readline())
    result = ask(vault, text, images)
    if result["status"] == "done":
        print(result["answer"])
    print(result["id"])
