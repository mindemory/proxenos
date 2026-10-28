"""Documents in Google Takeout's Drive folder, as text.

Reads Takeout's Drive folder and writes one stream into vault/raw/drive/: docs, a record per
document. Every export is a full snapshot, so each run re-reads one and merges by id. The same
file in several exports (Takeout splits a big Drive across parts) is one record.

Text comes from:
- .docx, .pptx and .xlsx, whose XML is read directly: a Word file's text runs, a deck's slide
  text in slide order, and a workbook's first sheet (shared strings resolved, a row per line,
  cells separated by tabs);
- .pdf, the first 30 pages (pypdf);
- .txt, .md and .json as written, .csv's first 200 rows (cells separated by tabs), .html with
  its tags, scripts and styles stripped, and .rtf with its control words crudely stripped.

Every other file is left out, and so are files over 50 MB, hidden files and folders, Office's
~$ lock files, and dependency folders (node_modules, site-packages, __pycache__). So is a data
dump: where a folder tree (the innermost one) holds more than 10,000 .txt, .csv and .json files,
those files are a dataset, not documents, and are left out. Its Word, PDF and other documents
are kept.

A record has path (relative to the Drive folder, which is also its id), title (the file name
without its extension), ext (lower case, no dot), size in bytes, text (the first 20,000
characters) and words. words counts what was read, which for a large file is its first million
characters, not just the text kept. ts is the file's modified time, which the importer keeps
from the zip.

A file that can't be read (a corrupt or password-protected document, a PDF none of whose pages
pypdf can read) is counted as skipped. A PDF with some unreadable pages keeps the rest.
"""

import argparse
import csv
import io
import logging
import os
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from proxenos.store import merge_monthly

_MAX_BYTES = 50 * 1024 * 1024
_TEXT_CHARS = 20_000
_PDF_PAGES = 30
_CSV_ROWS = 200
_READ_CHARS = 1_000_000  # how much of a document is read before the rest is ignored
_READ_BYTES = 4 * _READ_CHARS
_SKIP_FOLDERS = {"node_modules", "site-packages", "__pycache__", "__macosx"}
_DATA_EXTS = {"txt", "csv", "json"}  # what experiments write by the hundred thousand
_DATASET_FILES = 10_000

_WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_DRAWING = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_BLOCKS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
    "p", "pre", "section", "table", "td", "th", "tr", "ul",
}  # fmt: skip
_RTF_TOKEN = re.compile(
    r"\\([a-zA-Z]+)(-?\d+)? ?"  # a control word and its parameter
    r"|\\'([0-9a-fA-F]{2})"  # a byte in the ANSI code page
    r"|\\([^a-zA-Z])"  # a control symbol: \\ \{ \} \* \~
    r"|([{}])"
    r"|([^\\{}]+)"  # text
)
_RTF_DROPPED = {  # groups holding fonts, colours, styles and the like rather than text
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "headerl", "headerr",
    "footerl", "footerr", "themedata", "colorschememapping", "latentstyles", "datastore",
    "generator", "listtable", "listoverridetable", "rsidtbl", "fldinst", "object", "xmlnstbl",
}  # fmt: skip
_RTF_BREAKS = {"par", "line", "sect", "page", "row"}


def read_docs(export: Path) -> list[dict | None]:
    """Every readable document. None marks a file that couldn't be read."""
    return [_doc(path, export) for path in _files(export)]


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not export.is_dir():
        raise FileNotFoundError(f"no folder at {export}")
    return _merge({"docs": read_docs(export)}, vault / "raw" / "drive")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export", type=Path, required=True, metavar="DIR", help="Takeout's Drive folder"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def _merge(streams: dict[str, list[dict | None]], out: Path) -> dict[str, int]:
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    for stream, records in streams.items():
        stats["skipped"] += sum(r is None for r in records)
        # Keyed by id: a file in two exports is one record, and the last copy wins.
        kept = {r["id"]: r for r in records if r is not None}
        if kept:
            for key, value in merge_monthly(kept.values(), out / stream).items():
                stats[key] += value
    return stats


def _files(export: Path) -> list[Path]:
    """The files worth reading, in path order. Symlinks are never followed."""
    found = []
    for folder, names, files in os.walk(export):
        names[:] = sorted(n for n in names if not _hidden(n) and n.lower() not in _SKIP_FOLDERS)
        for name in files:
            path = Path(folder, name)
            if _hidden(name) or path.is_symlink() or _ext(path) not in _EXTRACTORS:
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    continue
            except OSError:
                pass  # read_docs counts a file that can't even be examined as skipped
            found.append(path)
    datasets = _datasets(found, export)
    if datasets:
        found = [p for p in found if not _in_dataset(p, export, datasets)]
    return sorted(found)


def _datasets(files: list[Path], export: Path) -> set[Path]:
    """The innermost folders whose trees hold more than _DATASET_FILES data files (.txt, .csv,
    .json): output of an experiment rather than writing, and a reader's records would be most
    of the vault."""
    counts: Counter[Path] = Counter()
    for path in files:
        if _ext(path) in _DATA_EXTS:
            folder = path.parent
            while True:
                counts[folder] += 1
                if folder == export or folder == folder.parent:
                    break
                folder = folder.parent
    big = {folder for folder, n in counts.items() if n > _DATASET_FILES}
    return big - {folder.parent for folder in big}  # a folder that holds a bigger one is no dump


def _in_dataset(path: Path, export: Path, datasets: set[Path]) -> bool:
    if _ext(path) not in _DATA_EXTS:
        return False
    folder = path.parent
    while True:
        if folder in datasets:
            return True
        if folder == export or folder == folder.parent:
            return False
        folder = folder.parent


def _hidden(name: str) -> bool:
    return name.startswith((".", "~$"))


def _doc(path: Path, export: Path) -> dict | None:
    """The record for a file, or None when it can't be read."""
    try:
        info = path.stat()
        text = _tidy(_EXTRACTORS[_ext(path)](path))
        rel = _tidy(path.relative_to(export).as_posix())
        return {
            "id": rel,
            "ts": _stamp(datetime.fromtimestamp(info.st_mtime, UTC)),
            "path": rel,
            "title": _tidy(path.stem),
            "ext": _ext(path),
            "size": info.st_size,
            "text": text[:_TEXT_CHARS],
            "words": len(text.split()),
        }
    except Exception:  # noqa: BLE001  a file that won't parse is skipped, not fatal
        return None


def _ext(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _tidy(text: str) -> str:
    """Text with nothing a JSON file or a month's records can't hold: no surrogates left over
    from a bad decode, no NULs."""
    return text.encode("utf-8", "replace").decode("utf-8").replace("\x00", "")


def _raw(path: Path) -> bytes:
    with path.open("rb") as f:
        return f.read(_READ_BYTES)


def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _plain(path: Path) -> str:
    return _decode(_raw(path))[:_READ_CHARS]


def _csv(path: Path) -> str:
    rows = []
    for row in csv.reader(io.StringIO(_decode(_raw(path)), newline="")):
        line = "\t".join(cell.strip() for cell in row).rstrip("\t")
        if line:
            rows.append(line)
        if len(rows) >= _CSV_ROWS:
            break
    return "\n".join(rows)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader  # only PDFs need it, so it's imported here

    logging.getLogger("pypdf").setLevel(logging.CRITICAL)  # damaged files are common; say nothing
    reader = PdfReader(path)
    if reader.is_encrypted:
        reader.decrypt("")  # a PDF locked only against editing opens with an empty password
    pages: list[str] = []
    failure: Exception | None = None
    for n in range(min(len(reader.pages), _PDF_PAGES)):
        try:
            pages.append(reader.pages[n].extract_text() or "")
        except Exception as e:  # noqa: BLE001  one bad page doesn't lose the others
            failure = e
    if failure is not None and not pages:
        raise failure  # no page could be read: the file is skipped
    return "\n".join(pages)


def _xml_text(stream, run: str, paragraph: str, tabs: set[str], breaks: set[str]) -> str:
    """The text runs of an XML stream, a paragraph per line. Reads on only until enough text
    is in, so a huge document costs no more than a small one."""
    lines: list[str] = []
    line: list[str] = []
    total = 0
    for _, el in ElementTree.iterparse(stream, events=("end",)):
        tag = el.tag
        if tag == run:
            line.append(el.text or "")
        elif tag in tabs:
            line.append("\t")
        elif tag in breaks:
            line.append("\n")
        elif tag == paragraph:
            text = "".join(line).strip()
            line = []
            if text:
                lines.append(text)
                total += len(text) + 1
            el.clear()
            if total >= _READ_CHARS:
                break
    return "\n".join(lines)


def _docx(path: Path) -> str:
    with ZipFile(path) as archive, archive.open("word/document.xml") as f:
        return _xml_text(f, _WORD + "t", _WORD + "p", {_WORD + "tab"}, {_WORD + "br", _WORD + "cr"})


def _pptx(path: Path) -> str:
    with ZipFile(path) as archive:
        slides = sorted(
            (int(m[1]), name) for name in archive.namelist() if (m := _SLIDE.match(name))
        )
        texts, total = [], 0
        for _, name in slides:
            with archive.open(name) as f:
                text = _xml_text(f, _DRAWING + "t", _DRAWING + "p", set(), {_DRAWING + "br"})
            if text:
                texts.append(text)
                total += len(text) + 2
            if total >= _READ_CHARS:
                break
    return "\n\n".join(texts)


def _xlsx(path: Path) -> str:
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        shared = _shared_strings(archive) if "xl/sharedStrings.xml" in names else []
        rows, total = [], 0
        with archive.open(_first_sheet(archive, names)) as f:
            cells: list[str] = []
            for _, el in ElementTree.iterparse(f, events=("end",)):
                if el.tag == _SHEET + "c":
                    value = _cell(el, shared)
                    if value:
                        cells.append(value)
                elif el.tag == _SHEET + "row":
                    if cells:
                        rows.append("\t".join(cells))
                        total += len(rows[-1]) + 1
                    cells = []
                    el.clear()
                    if total >= _READ_CHARS:
                        break
    return "\n".join(rows)


def _shared_strings(archive: ZipFile) -> list[str]:
    strings: list[str] = []
    with archive.open("xl/sharedStrings.xml") as f:
        for _, el in ElementTree.iterparse(f, events=("end",)):
            if el.tag == _SHEET + "si":
                # Plain text is <t>; rich text is runs of <r><t>. Phonetic hints (<rPh>) are left out.
                parts = [t.text or "" for t in el.findall(_SHEET + "t")]
                parts += [
                    t.text or "" for r in el.findall(_SHEET + "r") for t in r.findall(_SHEET + "t")
                ]
                strings.append("".join(parts))
                el.clear()
    return strings


def _first_sheet(archive: ZipFile, names: set[str]) -> str:
    """The part holding the workbook's first sheet: the first one it lists, or else sheet1."""
    try:
        with archive.open("xl/workbook.xml") as f:
            sheets = ElementTree.parse(f).getroot().find(_SHEET + "sheets")
            first = sheets[0].get(_REL + "id") if sheets is not None and len(sheets) else None
        with archive.open("xl/_rels/workbook.xml.rels") as f:
            for rel in ElementTree.parse(f).getroot().iter(_PACKAGE_REL + "Relationship"):
                if rel.get("Id") == first:
                    target = rel.get("Target", "")
                    part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
                    if part in names:
                        return part
    except (KeyError, ElementTree.ParseError, IndexError):
        pass
    if "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    parts = sorted(n for n in names if re.fullmatch(r"xl/worksheets/[^/]+\.xml", n))
    if not parts:
        raise KeyError("no worksheet")
    return parts[0]


def _cell(el: ElementTree.Element, shared: list[str]) -> str:
    kind = el.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in el.iter(_SHEET + "t")).strip()
    value = el.findtext(_SHEET + "v") or ""
    if kind == "s":
        return shared[int(value)].strip() if value.strip().isdigit() else ""
    if kind == "b":
        return "TRUE" if value.strip() == "1" else "FALSE"
    if kind == "e":
        return ""
    return value.strip()


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("script", "style"):
            self._hidden += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def _html(path: Path) -> str:
    stripper = _Stripper()
    stripper.feed(_decode(_raw(path))[:_READ_CHARS])
    stripper.close()
    lines = (" ".join(line.split()) for line in "".join(stripper.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _rtf(path: Path) -> str:
    """Plain text from RTF, crudely: groups of fonts, styles and the like dropped, \\par as a
    line break, \\'xx and \\uN as the characters they stand for, every other control word gone."""
    out: list[str] = []
    stack: list[bool] = []  # per open group: is its text being dropped?
    dropped = False
    skip = 0  # characters of a \uN's ANSI fallback still to pass over
    for match in _RTF_TOKEN.finditer(_decode(_raw(path))[:_READ_CHARS]):
        word, number, hexa, symbol, brace, text = match.groups()
        if brace == "{":
            stack.append(dropped)
        elif brace == "}":
            dropped = stack.pop() if stack else False
        elif word:
            if word in _RTF_DROPPED:
                dropped = True
            elif dropped:
                continue
            elif word in _RTF_BREAKS:
                out.append("\n")
            elif word == "tab":
                out.append("\t")
            elif word == "u" and number:
                code = int(number)
                out.append(chr(code + 65536 if code < 0 else code))
                skip = 1
        elif hexa and not dropped:
            if skip:
                skip -= 1
            else:
                out.append(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
        elif symbol:
            if symbol == "*":
                dropped = True  # an optional destination, e.g. {\*\generator ...}
            elif not dropped and symbol in "\\{}":
                out.append(symbol)
            elif not dropped and symbol == "~":
                out.append(" ")
        elif text and not dropped:
            text = text.replace("\r", "").replace("\n", "")
            if skip:
                taken = min(skip, len(text))
                text, skip = text[taken:], skip - taken
            out.append(text)
    lines = (" ".join(line.split()) for line in "".join(out).splitlines())
    return "\n".join(line for line in lines if line)


_EXTRACTORS: dict[str, Callable[[Path], str]] = {
    "docx": _docx,
    "pptx": _pptx,
    "xlsx": _xlsx,
    "pdf": _pdf,
    "txt": _plain,
    "md": _plain,
    "json": _plain,
    "csv": _csv,
    "html": _html,
    "rtf": _rtf,
}


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
