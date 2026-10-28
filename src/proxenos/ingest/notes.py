"""Notes from Notion and Obsidian exports, and pages saved as PDF.

Reads an unzipped Notion export (Settings, Export, as Markdown & CSV or as PDF) or an Obsidian
vault, plus a folder of PDFs, and writes two streams into vault/raw/notes/: pages and tasks.
Every export is a full snapshot, so each run re-reads one and merges by id.

pages has a record per note, with kind:
- md: a Markdown file. title is its first top-level heading, else the file name. ts is a date in its front
  matter, else a Notion property line under the title ("Created: October 3, 2023 4:15 PM"), else
  the file's modified time, which the importer keeps from the zip.
- csv_row: a row of a Notion database CSV, with every non-empty column under properties. title is
  the first column, which Notion fills with the title property. Only CSVs with a Notion id in the
  name are read, so other CSVs in a vault are left alone. When Notion writes both "X <id>.csv"
  and "X <id>_all.csv", only the _all one is read.
- pdf: a PDF under --pdf-dir, as text. title is the PDF's Title, else the file name. ts is when
  the PDF was made, which for a Notion PDF is the export, else the file's modified time.
For md and csv_row, the date is the first "Date..." field, then the first "Created..." one, that
parses. Notion writes local times without a zone, so those are taken as UTC.

Notion ends names in a 32-hex id ("Papers 90f1...4c.csv"), dropped from titles and collections.
collection is the folder path ("Readings"), and for a CSV row also the database's own name
("Readings/Papers"). In an Obsidian vault (a folder holding .obsidian), the path starts at the
vault's folder. Hidden files and folders and macOS's __MACOSX are skipped. A zip made on a Mac
can store names as UTF-8 read as cp437 ("Alex╬▒ndria"), which is decoded back.

tasks has the database rows with a status or a due date, and every titled row of a database
named Tasks or To-dos: title, status, due, collection and properties. status is a Status (State,
Stage, Progress) column, or a Complete (Done) checkbox read as "Done" or "Not started". due is a
Due, Due Date, Deadline or Do Date column. ts is the due date, else the row's date.

Ids: a page's Notion id, a PDF's Notion id or the UUID Notion puts before a downloaded PDF's
name, or else the file's path in the export. A database row has no id in the export, so it's
keyed by its database and title, with #2, #3, ... for different rows that share both, in
content order. A row whose title is edited becomes a new record, and the old one stays. A task
has its row's id.

A file that can't be read and a line the csv module can't parse are counted as skipped. Empty
files are left out.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from proxenos.store import merge_monthly

_NOTION_ID = re.compile(r"\s+([0-9a-f]{32})(?:_all)?$")
_UUID = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_")
_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^#[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_FIELD = re.compile(r"^([^:\n]{1,40}):[ \t]+(.+)$")
_DAYS = ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y/%m/%d", "%d %B %Y", "%d %b %Y")
_FORMATS = [day + time for day in _DAYS for time in ("", " %I:%M %p", " %H:%M")]
_STATUS = ("status", "state", "stage", "progress")
_CHECKBOX = ("complete", "completed", "done")
_DUE = ("due", "duedate", "dueon", "dueby", "deadline", "dodate")
_TASK_DATABASES = ("tasks", "task", "todos", "todo", "todolist")
_CHECKED = ("yes", "true", "1", "checked")


def read_pages(export: Path) -> list[dict | None]:
    """Every Markdown note. None marks a file that couldn't be read."""
    vaults = _vaults(export)
    paths = _walk(export, ".md", ".markdown")
    return [record for path in paths for record in _read(_page, path, export, vaults)]


def read_rows(export: Path) -> list[dict | None]:
    """Every row of every Notion database CSV. None marks a file or line that couldn't be read."""
    paths = _walk(export, ".csv")
    full = {p.with_name(p.stem.removesuffix("_all") + p.suffix) for p in paths if _is_all(p)}
    keyed: list[tuple[str, dict] | None] = []
    for path in paths:
        if path in full or not _NOTION_ID.search(path.stem):
            continue
        try:
            keyed += _table(path, export)
        except (OSError, csv.Error, UnicodeError):
            keyed.append(None)
    return _with_ids(keyed)


def read_tasks(rows: list[dict | None]) -> list[dict]:
    """The database rows that are tasks, from read_rows."""
    return [task for row in rows if row and (task := _task(row))]


def read_pdfs(folder: Path) -> list[dict | None]:
    """Every PDF's text. None marks a file pypdf couldn't read."""
    return [record for path in _walk(folder, ".pdf") for record in _read(_pdf, path, folder)]


def ingest(vault: Path, export: Path | None = None, pdf_dir: Path | None = None) -> dict[str, int]:
    if export is None and pdf_dir is None:
        raise ValueError("nothing to read: give --export, --pdf-dir or both")
    for folder in (export, pdf_dir):
        if folder is not None and not folder.is_dir():
            raise FileNotFoundError(f"no folder at {folder}")
    pages = read_pages(export) if export else []
    rows = read_rows(export) if export else []
    pdfs = read_pdfs(pdf_dir) if pdf_dir else []
    if not (pages or rows or pdfs):
        raise FileNotFoundError(f"no notes (.md, Notion .csv or .pdf) in {export or pdf_dir}")
    streams = {"pages": pages + rows + pdfs, "tasks": read_tasks(rows)}
    return _merge(streams, vault / "raw" / "notes")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, metavar="DIR", help="an unzipped Notion export or Obsidian vault"
    )
    parser.add_argument(
        "--pdf-dir", type=Path, metavar="DIR", help="a folder of PDFs to read as notes"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    export = args.export.expanduser() if args.export else None
    pdf_dir = args.pdf_dir.expanduser() if args.pdf_dir else None
    return ingest(vault, export, pdf_dir)


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: the same page in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _page(path: Path, export: Path, vaults: list[Path]) -> dict | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        return None
    front = _FRONT_MATTER.match(raw)
    body = raw[front.end() :] if front else raw
    heading = _HEADING.search(body)
    folders = _folders(path, export, vaults)
    notion = _NOTION_ID.search(path.stem)
    when = _dated(_fields(front[1].splitlines()) if front else {})
    when = when or _dated(_properties(body, heading))
    return {
        "id": f"md/{notion[1]}" if notion else "md/" + "/".join([*folders, _clean(path.stem)]),
        "ts": _stamp(when or _mtime(path)),
        "kind": "md",
        "from_me": True,
        "title": heading[1].strip() if heading else _clean(path.stem),
        "collection": "/".join(folders) or None,
        "text": body.strip(),
    }


def _table(path: Path, export: Path) -> list[tuple[str, dict] | None]:
    """(key, record) for each row of a database CSV, None for a line that won't parse."""
    collection = "/".join([*_folders(path, export, []), _clean(path.stem)])
    modified = _mtime(path)
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        lines: list[list[str] | None] = []
        reader = csv.reader(f)
        while True:
            try:
                lines.append(next(reader))
            except StopIteration:
                break
            except csv.Error:
                lines.append(None)
    if not lines or lines[0] is None:
        return [None] if lines else []
    header = [name.strip() for name in lines[0]]
    keyed: list[tuple[str, dict] | None] = []
    for line in lines[1:]:
        if line is None:
            keyed.append(None)
            continue
        if not any(cell.strip() for cell in line):
            continue
        cells = dict(zip(header, (cell.strip() for cell in line), strict=False))
        properties = {name: value for name, value in cells.items() if name and value}
        title = cells.get(header[0]) or None
        record = {
            "ts": _stamp(_dated(properties) or modified),
            "kind": "csv_row",
            "from_me": True,
            "title": title,
            "collection": collection,
            "text": None,
            "properties": properties,
        }
        keyed.append((f"csv/{_hash(collection, title)}", record))
    return keyed


def _task(row: dict) -> dict | None:
    properties, title = row.get("properties") or {}, row.get("title")
    status = _status(properties)
    due_text = next((v for k, v in properties.items() if _squash(k) in _DUE), None)
    due = _when(due_text) if due_text else None
    database = _squash(row["collection"].rsplit("/", 1)[-1])
    if not title or not (status or due_text or database in _TASK_DATABASES):
        return None
    return {
        "id": row["id"],
        "ts": _stamp(due) if due else row["ts"],
        "from_me": True,
        "title": title,
        "status": status,
        "due": _stamp(due) if due else due_text,
        "collection": row["collection"],
        "properties": properties,
    }


def _pdf(path: Path, folder: Path) -> dict | None:
    from pypdf import PdfReader  # only PDFs need it, so it's imported here

    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        return None
    info = reader.metadata
    named = str(info.title or "").strip() if info else ""
    try:
        made = info.creation_date if info else None
    except Exception:  # noqa: BLE001  a malformed date: fall back on the file's time
        made = None
    if made is not None and made.tzinfo is None:
        made = made.replace(tzinfo=UTC)
    notion, download = _NOTION_ID.search(path.stem), _UUID.match(path.stem)
    folders = _folders(path, folder, [])
    stem = _clean(path.stem)
    if download:
        stem = " ".join(stem[download.end() :].replace("_", " ").split())
    key = notion[1] if notion else download[1] if download else "/".join([*folders, stem])
    return {
        "id": f"pdf/{key}",
        "ts": _stamp(made or _mtime(path)),
        "kind": "pdf",
        "from_me": True,
        "title": named or stem,
        "collection": "/".join(folders) or None,
        "text": text,
    }


def _read(make: Callable[..., dict | None], path: Path, *context: Any) -> list[dict | None]:
    """make's record for a file, as a list: [] for an empty file, [None] for one that won't
    parse (counted as skipped)."""
    try:
        record = make(path, *context)
    except Exception:  # noqa: BLE001  a file that won't parse is skipped, not fatal
        return [None]
    return [record] if record else []


def _walk(root: Path, *suffixes: str) -> list[Path]:
    """Files under root with one of the suffixes, leaving out hidden ones and __MACOSX."""
    found = []
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part.startswith(".") or part == "__MACOSX" for part in parts):
            continue
        if path.suffix.lower() in suffixes and path.is_file():
            found.append(path)
    return sorted(found)


def _vaults(export: Path) -> list[Path]:
    return sorted(p.parent for p in export.rglob(".obsidian") if p.is_dir())


def _folders(path: Path, root: Path, vaults: list[Path]) -> list[str]:
    """The cleaned folder names down to a file, from root or from its Obsidian vault's folder."""
    vault = max((v for v in vaults if v in path.parents), key=lambda v: len(v.parts), default=None)
    start = vault.parent if vault else root
    return [_clean(part) for part in path.parent.relative_to(start).parts]


def _clean(name: str) -> str:
    """A name without Notion's id, and with a Mac zip's cp437 garbling undone."""
    try:
        name = name.encode("cp437").decode("utf-8")
    except UnicodeError:
        pass
    return _NOTION_ID.sub("", name.removesuffix("_all")).strip()


def _is_all(path: Path) -> bool:
    return path.stem.endswith("_all") and bool(_NOTION_ID.search(path.stem))


def _fields(lines: list[str]) -> dict[str, str]:
    """'key: value' lines as a dict, quotes taken off the values."""
    fields = {}
    for line in lines:
        if match := _FIELD.match(line.strip()):
            fields[match[1].strip()] = match[2].strip().strip("\"'")
    return fields


def _properties(body: str, heading: re.Match | None) -> dict[str, str]:
    """Notion's property lines: the 'Key: value' block right under the page's title."""
    if heading is None:
        return {}
    lines = body[heading.end() :].lstrip("\r\n").splitlines()
    block = []
    for line in lines:
        if not _FIELD.match(line.strip()):
            break
        block.append(line)
    return _fields(block)


def _dated(fields: dict[str, str]) -> datetime | None:
    """The first Date... field, then the first Created... one, whose value parses."""
    names = [k for k in fields if _squash(k).startswith("date")]
    names += [k for k in fields if _squash(k).startswith("created")]
    return next((when for k in names if (when := _when(fields[k]))), None)


def _status(properties: dict[str, str]) -> str | None:
    if value := next((v for k, v in properties.items() if _squash(k) in _STATUS), None):
        return value
    checked = next((v for k, v in properties.items() if _squash(k) in _CHECKBOX), None)
    if checked is None:
        return None
    return "Done" if checked.lower() in _CHECKED else "Not started"


def _when(text: str) -> datetime | None:
    """A Notion or front-matter date in UTC, or None. A range ("A → B") is its start."""
    text = text.split("→")[0].strip().lstrip("@").strip()
    text = re.sub(r"\s*\([^)]*\)$", "", text)  # a trailing "(EDT)" zone name isn't used
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _FORMATS:
            try:
                when = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _with_ids(keyed: list[tuple[str, dict] | None]) -> list[dict | None]:
    """Records with ids from their keys. Exact copies collapse, and distinct records that share
    a key get #2, #3, ... in content order, so ids don't depend on row order."""
    groups: dict[str, list[dict]] = defaultdict(list)
    out: list[dict | None] = []
    for item in keyed:
        if item is None:
            out.append(None)
        else:
            groups[item[0]].append(item[1])
    for key, group in groups.items():
        unique = {json.dumps(record, sort_keys=True): record for record in group}
        for n, (_, record) in enumerate(sorted(unique.items()), start=1):
            out.append({"id": key if n == 1 else f"{key}#{n}", **record})
    return out


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _hash(*parts: str | None) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
