"""Forms: a PDF filled in from what the vault holds about the user, for them to check, sign and
send.

`proxenos form PATH` reads the form, has the model answer each blank from the user's records,
writes the filled copy beside it (<name>-filled.pdf, or --out), and keeps what it did in
clones/forms/<name>.json: each answer and the record it came from, and what's left for the user.

What it reads of a form (`read`):
- a fillable PDF's own fields (AcroForm): each field's tooltip, else its name, as its label;
- a flat PDF's drawn blanks, from where its text and lines sit (pdfminer): each horizontal rule
  is a blank, labelled by the text right under it, one blank per label when a rule carries
  several, else by the text on its left on the same line ("Policy #/ID# ____"). The text just
  above it is offered as columns, so a table row can be filled cell by cell. Each small circle or
  square is a choice, labelled by the text to its right, with the question that starts its line.

The model gets the blanks and choices, who the user is (identity, what they told Proxenos,
proxenos.told) and the records memory finds for each label and question (proxenos.research),
and answers only from those: anything they don't show stays blank. It never sees, and nothing
fills, a blank for a Social Security number or another government id, a bank, card or account
number, a PIN or password, or a signature and its date; numbers shaped like an SSN or a card are
blanked in the records it reads. Those are listed for the user to fill by hand.

Answers go above each rule in dark blue, shrunk to fit; a choice is marked with a filled dot.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from proxenos import llm, research, told
from proxenos.config import env

MAX_HITS = 3  # of memory's records for each label or question, the user's own and newest first
POOL = 12  # records looked at for each, to pick those from
# What records call what forms ask for, so a search finds "DOB 01/02/1990" for "Date of Birth".
_ALSO = {
    "birth": "DOB born birthday",
    "address": "address lease apartment street moved",
    "phone": "phone mobile cell number",
    "employer": "employer appointment letter job position",
    "employment": "salary appointment letter annualized pay",
    "income": "salary income pay annualized",
    "insurance": "insurance plan Cigna Aetna member",
    "deductible": "deductible out-of-pocket maximum plan",
    "marital": "single married spouse partner",
}
FACT_CHARS = 30_000  # of records the model reads
FONT = 9  # points, shrunk to fit a short blank
INK = "0.05 0.16 0.45"  # dark blue, like a pen
_UNDER = 14  # points under a rule a label may sit
_ABOVE = 40  # points above a rule a column heading may sit
# Never filled, never sent to the model: what only the user should write in.
_PRIVATE = re.compile(
    r"\b(ssn|social security|soc\.? sec|passport|driver'?s? licen[cs]e|licen[cs]e (no|number|#)|"
    r"itin\b|ein\b|tax ?id|taxpayer|routing|account (no|number|#)|acct|card (no|number|#)|"
    r"credit card|debit card|cvv|cvc|pin\b|password|alien|a-number|uscis)",
    re.IGNORECASE,
)
_SIGNATURE = re.compile(r"\bsignature\b|\bsign here\b|\binitials? here\b", re.IGNORECASE)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

_SYSTEM = """\
You fill in a form for {person} from what you're given about them. For each blank you can \
answer from it, return its id and the value, written as the form expects (dates as \
MM/DD/YYYY unless the form shows otherwise; money as a plain number such as 6,000.00). A blank \
in a table row may take a value per column: give the column, as listed, with each value. \
Simple arithmetic on a record is fine (a yearly salary over 12 is the monthly one). A balance \
or another amount that changes comes only from a record of the last month: an older one stays \
blank. For each \
choice that's right, return its id: exactly one option per question, and only where you know \
the answer from what you were given or from who they are (a single person with no dependants \
has no spouse). In from, say in a few words which record or note it came from.

Leave out every blank and choice you can't answer from what you were given: never guess, never \
write "N/A" or "unknown", never invent a number. Refer to {person} by name, and don't assume \
pronouns."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "fills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "value": {"type": "string"},
                    "column": {"type": "string"},
                    "from": {"type": "string"},
                },
                "required": ["id", "value", "column", "from"],
                "additionalProperties": False,
            },
        },
        "marks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fills", "marks"],
    "additionalProperties": False,
}


def fill(vault: Path, path: Path, out: Path | None = None, now: datetime | None = None) -> dict:
    """Fill the form at `path` from the vault: the filled copy, and what was filled and left."""
    now = now or datetime.now(UTC)
    out = out or path.with_name(f"{path.stem}-filled.pdf")
    form = read(path)
    asked = [b for b in form["blanks"] if not b["private"]]
    choices = [c for c in form["choices"] if not c["private"]]
    filled, marked = [], []
    if asked or choices:
        person = env("FULL_NAME") or env("NAME", "the person")
        prompt = _prompt(vault, form, asked, choices, person)
        system = _SYSTEM.format(person=person) + _about(vault, person, now)
        answer = llm.ask(prompt, system=system, schema=_SCHEMA)
        filled, marked = _answers(answer, asked, choices, shown=prompt + system)
    _write(path, out, form, filled, marked)
    done = {f["id"] for f in filled}
    left = [
        {
            "page": b["page"],
            "label": b["label"],
            "why": "yours to write" if b["private"] else "not in your records",
        }
        for b in form["blanks"]
        if b["private"] or b["id"] not in done
    ]
    answered = {(c["page"], c["question"]) for c in marked}
    left += [
        {"page": page, "label": question, "why": "not in your records"}
        for page, question in dict.fromkeys((c["page"], c["question"]) for c in form["choices"])
        if (page, question) not in answered
    ]
    report = {
        "form": str(path),
        "filled_copy": str(out),
        "at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "filled": [{k: f[k] for k in ("page", "label", "value", "from")} for f in filled],
        "marked": [
            {"page": c["page"], "question": c["question"], "option": c["label"]} for c in marked
        ],
        "left": left,
    }
    folder = vault / "clones" / "forms"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{path.stem}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return report


# Reading a form


def read(path: Path) -> dict:
    """The form's blanks and choices: {kind: "fields" or "drawn", blanks, choices}. A blank is
    {id, page, label, question, columns, private, x0, x1, y} (or field, for a fillable PDF); a
    choice is {id, page, label, question, private, x, y, r} (or field and state)."""
    from pypdf import PdfReader

    fields = PdfReader(path).get_fields() or {}
    return _fields(fields) if fields else _drawn(path)


def _fields(fields: dict) -> dict:
    blanks, choices = [], []
    for name, f in fields.items():
        label = " ".join(str(f.get("/TU") or name).split())
        private = bool(_PRIVATE.search(label) or _SIGNATURE.search(label))
        if f.get("/FT") == "/Btn":
            for state in [s for s in f.get("/_States_", []) if s != "/Off"]:
                option = state.lstrip("/")
                choices.append(
                    {
                        "id": f"c{len(choices) + 1}",
                        "page": 0,
                        "label": option,
                        "question": label,
                        "private": private,
                        "field": name,
                        "state": state,
                    }
                )
        elif f.get("/FT") in ("/Tx", "/Ch"):
            blanks.append(
                {
                    "id": f"b{len(blanks) + 1}",
                    "page": 0,
                    "label": label,
                    "question": "",
                    "columns": [],
                    "private": private,
                    "field": name,
                }
            )
    return {"kind": "fields", "blanks": blanks, "choices": choices}


def _drawn(path: Path) -> dict:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams

    blanks, choices = [], []
    params = LAParams(char_margin=1.2, line_margin=0.2, word_margin=0.2)
    for number, page in enumerate(extract_pages(str(path), laparams=params)):
        texts, rules, rounds = _shapes(page)
        for rule in rules:
            for blank in _blanks(rule, texts):
                blank |= {"id": f"b{len(blanks) + 1}", "page": number}
                blanks.append(blank)
        options = {(round(x), round(y)): _right_of(texts, x, y) for x, y, _ in rounds}
        labels = {o for o in options.values() if o}
        for x, y, r in rounds:
            option = _right_of(texts, x, y)
            if not option:
                continue  # part of a logo or a drawing, not a choice
            question = _left_of(texts, x, y, labels)
            choices.append(
                {
                    "id": f"c{len(choices) + 1}",
                    "page": number,
                    "label": option,
                    "question": question,
                    "private": bool(_PRIVATE.search(f"{option} {question}")),
                    "x": x,
                    "y": y,
                    "r": r,
                }
            )
    _signature_dates(blanks)
    return {"kind": "drawn", "blanks": blanks, "choices": choices}


def _shapes(page) -> tuple[list[dict], list[tuple], list[tuple]]:
    """A page's text lines {text, x0, x1, y0, y1}, rules (x0, x1, y) and round marks (x, y, r)."""
    from pdfminer.layout import LTCurve, LTTextContainer, LTTextLineHorizontal

    texts, rules, rounds = [], [], []

    def walk(item):
        for o in item:
            if isinstance(o, LTTextLineHorizontal):
                texts.extend(_parts(o))
            elif isinstance(o, LTTextContainer):
                walk(o)
            elif isinstance(o, LTCurve):  # lines and rectangles are curves too
                w, h = o.x1 - o.x0, o.y1 - o.y0
                if h <= 1.6 and w >= 15:
                    rules.append((o.x0, o.x1, (o.y0 + o.y1) / 2))
                elif 4 <= w <= 14 and 4 <= h <= 14 and abs(w - h) < 2:
                    rounds.append(((o.x0 + o.x1) / 2, (o.y0 + o.y1) / 2, w / 2))
            elif hasattr(o, "__iter__"):
                walk(o)

    walk(page)
    return texts, _unique(rules, 1.5), _unique(rounds, 1.5)


def _parts(line) -> list[dict]:
    """A line of text as its parts: a wide gap or a run of spaces is two labels, not one."""
    from pdfminer.layout import LTChar

    parts, chars, gap, last = [], [], 0, None
    for c in [c for c in line if isinstance(c, LTChar) or c.get_text().isspace()]:
        if not isinstance(c, LTChar) or c.get_text().isspace():
            gap += 1
            continue
        if chars and (gap >= 3 or (last is not None and c.x0 - last.x1 > 3 * (last.x1 - last.x0))):
            parts.append(chars)
            chars = []
        elif chars and gap:
            chars.append(None)  # a space within the label
        chars.append(c)
        gap, last = 0, c
    if chars:
        parts.append(chars)
    found = []
    for part in parts:
        glyphs = [c for c in part if c is not None]
        text = "".join(" " if c is None else c.get_text() for c in part).strip()
        if text:
            found.append(
                {
                    "text": text,
                    "x0": glyphs[0].x0,
                    "x1": glyphs[-1].x1,
                    "y0": line.y0,
                    "y1": line.y1,
                }
            )
    return found


def _unique(shapes: list[tuple], near: float) -> list[tuple]:
    """Shapes drawn twice (a fill and its outline, or a shadow) count once."""
    kept: list[tuple] = []
    for shape in sorted(shapes):
        if not any(all(abs(a - b) <= near for a, b in zip(shape, k, strict=True)) for k in kept):
            kept.append(shape)
    return kept


def _blanks(rule: tuple, texts: list[dict]) -> list[dict]:
    """A rule's blanks: one per label right under it, else one labelled from its left."""
    x0, x1, y = rule
    under = sorted(
        (t for t in texts if y - _UNDER <= t["y1"] <= y + 1 and x0 - 2 <= t["x0"] < x1),
        key=lambda t: t["x0"],
    )
    if under and under[0]["x0"] > x0 + 6:
        under = []  # labels under a rule start where it starts; these belong to the next line
    if under:
        starts = [t["x0"] for t in under] + [x1]
        return [_blank(t["text"], "", [], starts[i], starts[i + 1], y) for i, t in enumerate(under)]
    left = [t for t in texts if t["y0"] - 4 <= y <= t["y1"] + 2 and t["x0"] < x0 - 1]
    left = [t for t in left if t["text"] not in ("$", ",", ":")] or left
    label = max(left, key=lambda t: t["x0"])["text"] if left else ""
    return [_blank(label, _row_start(texts, y + 2, x0), _headings(texts, x0, x1, y), x0, x1, y)]


def _headings(texts: list[dict], x0: float, x1: float, y: float) -> list[str]:
    """Column headings over a blank that's a table row: the nearest row of three or more pieces
    of text above it, those over the blank, when two or more are, or one that starts where it
    starts ("Person 1:" over its own blank)."""
    above = sorted({round(t["y0"]) for t in texts if y < t["y0"] <= y + _ABOVE})
    for row_y in above:  # nearest first
        row = [t for t in texts if abs(t["y0"] - row_y) <= 2]
        if len(row) < 3:
            continue
        over = [t for t in row if x0 - 2 <= t["x0"] < x1]
        if len(over) >= 2 or (len(over) == 1 and abs(over[0]["x0"] - x0) <= 10):
            return [t["text"] for t in sorted(over, key=lambda t: t["x0"])]
    return []


def _blank(label: str, question: str, columns: list[str], x0: float, x1: float, y: float) -> dict:
    label = label.strip(" ,:")
    return {
        "label": label,
        "question": question if question != label else "",
        "columns": [c for c in columns if c != label],
        "private": bool(_PRIVATE.search(label) or _SIGNATURE.search(label)),
        "x0": x0,
        "x1": x1,
        "y": y,
    }


def _signature_dates(blanks: list[dict]) -> None:
    """A "Date" blank on the same line as a signature is the signing date: the user's too."""
    for blank in blanks:
        if blank["label"].lower() == "date" and any(
            other["page"] == blank["page"]
            and abs(other["y"] - blank["y"]) < 2
            and _SIGNATURE.search(other["label"])
            for other in blanks
        ):
            blank["private"] = True


def _right_of(texts: list[dict], x: float, y: float) -> str:
    near = [t for t in texts if x < t["x0"] <= x + 15 and t["y0"] - 4 <= y <= t["y1"] + 4]
    return min(near, key=lambda t: t["x0"])["text"].split("  ")[0].strip(" :") if near else ""


def _left_of(texts: list[dict], x: float, y: float, options: set[str]) -> str:
    """A choice's question: the nearest text on its left that isn't another choice's option."""
    near = [
        t
        for t in texts
        if t["x0"] < x - 3
        and t["y0"] - 4 <= y <= t["y1"] + 4
        and t["text"].strip(" :") not in options
    ]
    return max(near, key=lambda t: t["x0"])["text"].strip(" ,") if near else ""


def _row_start(texts: list[dict], y: float, before: float) -> str:
    """The text that starts the line at height y, left of `before`: a choice's question."""
    row = [t for t in texts if t["y0"] - 4 <= y <= t["y1"] + 4 and t["x0"] < before - 15]
    return min(row, key=lambda t: t["x0"])["text"] if row else ""


# Answering


def _prompt(vault: Path, form: dict, blanks: list[dict], choices: list[dict], person: str) -> str:
    lines = ["## Blanks"]
    for b in blanks:
        line = f"- {b['id']} (page {b['page'] + 1}): {b['label'] or '(no label)'}"
        if b["question"]:
            line += f", on the line: {b['question']}"
        if b["columns"]:
            line += f"; columns: {' | '.join(b['columns'])}"
        lines.append(line)
    lines.append("\n## Choices, each an option of the question it's on")
    for c in choices:
        lines.append(
            f"- {c['id']} (page {c['page'] + 1}): {c['label']}, for: {c['question'] or '(no question)'}"
        )
    lines.append(
        f"\n## {person}'s records that bear on these, newest first\n{_facts(vault, blanks, choices)}"
    )
    return "\n".join(lines)


def _about(vault: Path, person: str, now: datetime) -> str:
    parts = [f"Who {person} is: " + " ".join(f"{k}: {v}" for k, v in _basics().items() if v)]
    identity = vault / "self" / "identity.md"
    if identity.exists():
        parts.append(
            f"<identity>\n{identity.read_text(encoding='utf-8').strip()[:4000]}\n</identity>"
        )
    if notes := told.prompt(vault, person, now):
        parts.append(notes)
    return "\n\n" + _clean("\n\n".join(parts))


def _basics() -> dict[str, str]:
    return {"name": env("FULL_NAME") or env("NAME"), "email": env("EMAILS").split(",")[0].strip()}


def _facts(vault: Path, blanks: list[dict], choices: list[dict]) -> str:
    """The records memory finds for each label and question, each line once, cut to fit."""
    queries = dict.fromkeys(
        q
        for item in [*blanks, *choices]
        for q in (item["label"], item.get("question", ""))
        if len(q) > 2
    )
    lines: list[str] = []
    me = env("NAME", "the user")
    for query in queries:
        also = " ".join(v for k, v in _ALSO.items() if k in query.lower())
        try:
            pool = research._search(vault, f"{query} {also}".strip(), None)[:POOL]
        except Exception:  # noqa: BLE001 - no memory index: the identity alone, then
            pool = []
        pool.sort(key=lambda h: (bool(h.get("from_me")), str(h.get("ts") or "")), reverse=True)
        lines += [research._line(h, me) for h in pool[:MAX_HITS]]
    text = "\n".join(dict.fromkeys(lines))[:FACT_CHARS]
    return _clean(text) or "Nothing found."


def _grounded(value: str, shown: str) -> bool:
    """Whether a value comes from what the model was shown: its words are there, and its
    numbers are (a date in any of its usual forms, an amount with or without commas), or, for a
    monthly amount, twelve times it is."""
    text = shown.lower()
    words = [w for w in re.findall(r"[a-z]{3,}", value.lower()) if w not in ("apt", "suite")]
    flat = re.sub(r"[,\s]", "", text)
    dates = set(re.findall(r"\d[\d/.-]*\d", text))
    for number in re.findall(r"\d[\d,./-]*\d|\d", value):
        bare = number.replace(",", "")
        digits = re.sub(r"\D", "", number)
        if (
            bare in flat
            or _date_forms(number) & dates
            or (len(digits) >= 7 and digits in re.sub(r"\D", "", text))
        ):
            continue
        try:
            yearly = float(bare) * 12
        except ValueError:
            return False
        if not any(f"{yearly:{fmt}}" in flat for fmt in (".0f", ".2f")):
            return False
    return all(w in text for w in words)


def _date_forms(text: str) -> set[str]:
    """A date's other usual spellings: 01/02/1990, 1990-01-02, 01-02-1990."""
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    if not m:
        return set()
    mm, dd, yyyy = m.groups()
    return {f"{mm}/{dd}/{yyyy}", f"{yyyy}-{int(mm):02d}-{int(dd):02d}", f"{mm}-{dd}-{yyyy}"}


def _clean(text: str) -> str:
    """Numbers shaped like an SSN or a card never reach the model."""
    return _CARD.sub("[number]", _SSN.sub("[number]", text))


def _answers(
    answer: dict, blanks: list[dict], choices: list[dict], shown: str = ""
) -> tuple[list[dict], list[dict]]:
    """The model's fills and marks, kept only where they name a blank or choice it was shown,
    say something the records it was shown say too (`_grounded`), and don't land in a private
    column."""
    by_id = {b["id"]: b for b in blanks}
    filled = []
    for item in answer.get("fills") or []:
        if not isinstance(item, dict):
            continue  # a local model's answer in another shape
        blank, value = by_id.get(item.get("id")), " ".join(str(item.get("value") or "").split())
        column = str(item.get("column") or "").strip()
        if not blank or not value or _PRIVATE.search(column) or _SSN.search(value):
            continue
        if shown and not _grounded(value, shown):
            continue  # in nothing it was shown: a guess
        if value.lower() in ("yes", "no") and not re.search(
            r"yes|no", blank["label"], re.IGNORECASE
        ):
            continue  # an answer for a choice, not a blank
        filled.append(
            blank | {"value": value, "column": column, "from": str(item.get("from") or "")}
        )
    by_choice = {c["id"]: c for c in choices}
    marked, questions = [], set()
    for key in answer.get("marks") or []:
        choice = by_choice.get(key.get("id") if isinstance(key, dict) else str(key))
        group = choice and (choice["page"], round(choice.get("y", 0)), choice["question"])
        if choice and group not in questions:
            questions.add(group)  # one option a question
            marked.append(choice)
    return filled, marked


# Writing


def _write(path: Path, out: Path, form: dict, filled: list[dict], marked: list[dict]) -> None:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)
    if form["kind"] == "fields":
        values = {f["field"]: f["value"] for f in filled}
        values |= {c["field"]: c["state"] for c in marked}
        for page in writer.pages:
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
        writer.set_need_appearances_writer(True)
    else:
        texts = _columns_x(path) if any(f["column"] for f in filled) else {}
        for number, page in enumerate(writer.pages):
            ops = [_text(f, texts) for f in filled if f["page"] == number]
            ops += [
                _dot(c["x"], c["y"], min(3.2, c["r"] * 0.6)) for c in marked if c["page"] == number
            ]
            if ops:
                _overlay(writer, page, ops)
    with out.open("wb") as f:
        writer.write(f)


def _columns_x(path: Path) -> dict[tuple[int, str], float]:
    """Where each piece of text starts, by page and text, for a value given a column."""
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams

    found = {}
    params = LAParams(char_margin=1.2, line_margin=0.2, word_margin=0.2)
    for number, page in enumerate(extract_pages(str(path), laparams=params)):
        for t in _shapes(page)[0]:
            found.setdefault((number, t["text"]), t["x0"])
    return found


def _text(f: dict, texts: dict) -> str:
    x = texts.get((f["page"], f["column"]), f["x0"] + 2) if f["column"] else f["x0"] + 2
    width = max((f["x1"] - x) if not f["column"] else 120, 20)
    size = max(6.0, min(FONT, width / (0.5 * max(len(f["value"]), 1))))
    value = f["value"].encode("latin-1", "replace").decode("latin-1")
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 {size:.1f} Tf {INK} rg {x:.1f} {f['y'] + 3:.1f} Td ({escaped}) Tj ET"


def _dot(x: float, y: float, r: float) -> str:
    k = 0.5523 * r
    return (
        f"{INK} rg {x + r:.2f} {y:.2f} m {x + r:.2f} {y + k:.2f} {x + k:.2f} {y + r:.2f} {x:.2f} {y + r:.2f} c "
        f"{x - k:.2f} {y + r:.2f} {x - r:.2f} {y + k:.2f} {x - r:.2f} {y:.2f} c "
        f"{x - r:.2f} {y - k:.2f} {x - k:.2f} {y - r:.2f} {x:.2f} {y - r:.2f} c "
        f"{x + k:.2f} {y - r:.2f} {x + r:.2f} {y - k:.2f} {x + r:.2f} {y:.2f} c f"
    )


def _overlay(writer, page, ops: list[str]) -> None:
    """Draw `ops` over the page, with Helvetica as /F1."""
    from pypdf import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    box = page.mediabox
    over = PageObject.create_blank_page(width=float(box.width), height=float(box.height))
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    over[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("latin-1", "replace"))
    over[NameObject("/Contents")] = writer._add_object(stream)
    page.merge_page(over)


# The command


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path, help="the form, a PDF")
    parser.add_argument("--out", type=Path, help="where the filled copy goes (default: beside it)")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    if not args.path.is_file():
        raise SystemExit(f"form: no such file: {args.path}")
    report = fill(vault, args.path, args.out)
    for item in report["left"]:
        print(
            f"  left for you, page {item['page'] + 1}: {item['label'] or '(a blank)'} ({item['why']})"
        )
    print(f"  filled copy: {report['filled_copy']}", file=sys.stderr)
    return {
        "filled": len(report["filled"]),
        "marked": len(report["marked"]),
        "left": len(report["left"]),
    }
