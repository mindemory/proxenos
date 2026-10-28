"""Drive ingester against synthetic Takeout documents. No real data lives here."""

import json
import os
import zipfile
from datetime import UTC, datetime

from proxenos.ingest import drive

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RELS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'

MTIME = datetime(2024, 3, 5, 12, 0, tzinfo=UTC).timestamp()


def put(path, data, mtime=MTIME):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


def make_zip(path, parts, mtime=MTIME):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
    os.utime(path, (mtime, mtime))
    return path


def docx(path):
    body = (
        f"<w:document {W}><w:body>"
        "<w:p><w:r><w:t>Project</w:t></w:r><w:r><w:t xml:space='preserve'> plan</w:t></w:r></w:p>"
        "<w:p></w:p>"
        "<w:p><w:r><w:t>Step one</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>due Friday</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell text</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )
    return make_zip(path, {"word/document.xml": body})


def pptx(path):
    def slide(*lines):
        paragraphs = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines)
        return f"<p:sld {A}><a:txBody>{paragraphs}</a:txBody></p:sld>"

    return make_zip(
        path,
        {
            # Out of order in the zip: slide 2 is named first and must still come second.
            "ppt/slides/slide10.xml": slide("Thanks"),
            "ppt/slides/slide2.xml": slide("Results", "Two bullet points"),
            "ppt/slides/slide1.xml": slide("Title slide"),
            "ppt/notesSlides/notesSlide1.xml": slide("Speaker notes are not slide text"),
        },
    )


def xlsx(path):
    shared = (
        f"<sst {S}><si><t>Name</t></si><si><r><t>Rich </t></r><r><t>text</t></r></si>"
        "<si><t>Hidden sheet text</t></si></sst>"
    )
    workbook = (
        f"<workbook {S} {R}><sheets>"
        '<sheet name="Data" sheetId="2" r:id="rId7"/><sheet name="Other" sheetId="1" r:id="rId8"/>'
        "</sheets></workbook>"
    )
    rels = (
        f"<Relationships {RELS}>"
        '<Relationship Id="rId7" Type="x" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId8" Type="x" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    first = (
        f"<worksheet {S}><sheetData>"
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2"><v>42</v></c><c r="B2" t="inlineStr"><is><t>inline</t></is></c>'
        '<c r="C2" t="b"><v>1</v></c></row>'
        '<row r="3"><c r="A3"/></row>'
        "</sheetData></worksheet>"
    )
    other = f'<worksheet {S}><sheetData><row r="1"><c r="A1" t="s"><v>2</v></c></row></sheetData></worksheet>'
    return make_zip(
        path,
        {
            "xl/sharedStrings.xml": shared,
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": rels,
            "xl/worksheets/sheet2.xml": first,
            "xl/worksheets/sheet1.xml": other,
        },
    )


def pdf(path, text):
    """A one-page PDF with a line of Helvetica text, written by hand so tests need no PDF tool."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return put(path, out)


RTF = (
    r"{\rtf1\ansi\deff0{\fonttbl{\f0 Times;}}{\colortbl;\red0\green0\blue0;}"
    r"{\*\generator Some Editor;}\pard Caf\'e9 notes\par Second \u8364? line\tab end\par}"
)


def make_drive(root):
    drive_dir = root / "Drive"
    docx(drive_dir / "Work" / "Plan.docx")
    pptx(drive_dir / "Work" / "Talk.PPTX")
    xlsx(drive_dir / "Budget.xlsx")
    pdf(drive_dir / "Papers" / "Paper.pdf", "Findings in brief")
    put(drive_dir / "todo.txt", "buy milk\nwrite thesis\n")
    put(drive_dir / "Notes" / "ideas.md", "# Ideas\n\nA few words.\n")
    put(drive_dir / "data.json", '{"key": "value"}')
    rows = "id,name\n" + "".join(f"{n},row{n}\n" for n in range(1, 300))
    put(drive_dir / "table.csv", rows)
    put(
        drive_dir / "page.html",
        "<html><head><style>p{color:red}</style><script>var x = 1;</script></head>"
        "<body><h1>Heading</h1><p>Some &amp; text</p><p>Next<br>line</p></body></html>",
    )
    put(drive_dir / "letter.rtf", RTF)
    return drive_dir


def by_path(records):
    return {r["path"]: r for r in records if r is not None}


def test_every_format_is_read_as_text(tmp_path):
    export = make_drive(tmp_path)
    docs = by_path(drive.read_docs(export))

    assert docs["Work/Plan.docx"]["text"] == "Project plan\nStep one\tdue Friday\nCell text"
    assert docs["Work/Talk.PPTX"]["text"] == "Title slide\n\nResults\nTwo bullet points\n\nThanks"
    assert docs["Budget.xlsx"]["text"] == "Name\tRich text\n42\tinline\tTRUE"
    assert docs["Papers/Paper.pdf"]["text"].strip() == "Findings in brief"
    assert docs["todo.txt"]["text"] == "buy milk\nwrite thesis\n"
    assert docs["Notes/ideas.md"]["text"] == "# Ideas\n\nA few words.\n"
    assert docs["data.json"]["text"] == '{"key": "value"}'
    assert docs["page.html"]["text"] == "Heading\nSome & text\nNext\nline"
    assert docs["letter.rtf"]["text"] == "Café notes\nSecond \u20ac line end"

    csv_text = docs["table.csv"]["text"].splitlines()
    assert len(csv_text) == 200  # the header and 199 rows
    assert csv_text[:2] == ["id\tname", "1\trow1"]


def test_a_record_has_its_path_size_and_modified_time(tmp_path):
    export = make_drive(tmp_path)
    record = by_path(drive.read_docs(export))["Work/Plan.docx"]
    assert record == {
        "id": "Work/Plan.docx",
        "ts": "2024-03-05T12:00:00Z",
        "path": "Work/Plan.docx",
        "title": "Plan",
        "ext": "docx",
        "size": (export / "Work" / "Plan.docx").stat().st_size,
        "text": "Project plan\nStep one\tdue Friday\nCell text",
        "words": 8,
    }
    assert by_path(drive.read_docs(export))["Work/Talk.PPTX"]["ext"] == "pptx"


def test_text_is_cut_at_20000_characters_but_words_count_all_of_it(tmp_path):
    export = tmp_path / "Drive"
    put(export / "long.txt", "word " * 10_000)
    (record,) = drive.read_docs(export)
    assert len(record["text"]) == 20_000
    assert record["words"] == 10_000


def test_pdfs_stop_at_thirty_pages(tmp_path, monkeypatch):
    export = tmp_path / "Drive"
    pdf(export / "long.pdf", "Only page")
    extracted = []

    class Page:
        def __init__(self, n):
            self.n = n

        def extract_text(self):
            extracted.append(self.n)
            return f"p{self.n}"

    class Reader:
        def __init__(self, path):
            self.is_encrypted = False
            self.pages = [Page(n) for n in range(45)]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    (record,) = drive.read_docs(export)
    assert extracted == list(range(30))
    assert record["words"] == 30


def test_a_pdf_with_some_unreadable_pages_keeps_the_rest(tmp_path, monkeypatch):
    export = tmp_path / "Drive"
    pdf(export / "damaged.pdf", "Only page")
    pdf(export / "hopeless.pdf", "Only page")

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            if self.text is None:
                raise ValueError("bad content stream")
            return self.text

    class Reader:
        def __init__(self, path):
            self.is_encrypted = False
            good = path.name == "damaged.pdf"
            self.pages = [Page("first"), Page(None), Page("third")] if good else [Page(None)]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    records = drive.read_docs(export)
    assert [r["text"] if r else None for r in records] == ["first\nthird", None]


def test_things_that_are_not_documents_are_left_out(tmp_path):
    export = make_drive(tmp_path)
    put(export / "code.py", "print('hi')")
    put(export / "model.mat", b"\x00\x01")
    put(export / "~$Plan.docx", b"lock file")
    put(export / ".hidden.txt", "secret")
    put(export / ".git" / "notes.txt", "internal")
    put(export / "node_modules" / "pkg" / "readme.md", "dependency")
    put(export / "report.doc", b"old binary word")
    records = drive.read_docs(export)
    assert None not in records
    assert sorted(by_path(records)) == sorted(
        [
            "Work/Plan.docx",
            "Work/Talk.PPTX",
            "Budget.xlsx",
            "Papers/Paper.pdf",
            "todo.txt",
            "Notes/ideas.md",
            "data.json",
            "table.csv",
            "page.html",
            "letter.rtf",
        ]
    )


def test_files_over_50_mb_are_left_out(tmp_path, monkeypatch):
    export = tmp_path / "Drive"
    put(export / "small.txt", "fits")
    put(export / "big.txt", "x" * 100)
    monkeypatch.setattr(drive, "_MAX_BYTES", 50)
    records = drive.read_docs(export)
    assert [r["path"] for r in records] == ["small.txt"]


def test_a_dump_of_data_files_is_left_out_but_documents_beside_it_are_kept(tmp_path, monkeypatch):
    export = tmp_path / "Drive"
    for run in ("run1", "run2"):
        for n in range(2):
            put(export / "Lab" / "Runs" / run / f"out{n}.txt", "0.1 0.2 0.3")
    put(export / "Lab" / "Runs" / "table.csv", "a,b\n1,2\n")
    docx(export / "Lab" / "Runs" / "Summary.docx")
    put(export / "Lab" / "Runs" / "README.md", "how the runs were made")
    put(export / "Lab" / "Notes" / "todo.txt", "write up")
    put(export / "Lab" / "Notes" / "later.json", "{}")
    monkeypatch.setattr(drive, "_DATASET_FILES", 4)
    # Runs holds five data files, more than 4; Lab and the whole Drive hold seven, but the
    # innermost folder over the limit is the dump, so Notes is untouched.
    assert [r["path"] for r in drive.read_docs(export)] == [
        "Lab/Notes/later.json",
        "Lab/Notes/todo.txt",
        "Lab/Runs/README.md",
        "Lab/Runs/Summary.docx",
    ]
    monkeypatch.setattr(drive, "_DATASET_FILES", 10)
    assert len(drive.read_docs(export)) == 9


def test_unreadable_files_are_skipped_not_fatal(tmp_path):
    export = tmp_path / "Drive"
    put(export / "good.txt", "fine")
    put(export / "broken.docx", b"not a zip")
    put(export / "empty-doc.pptx", b"")
    make_zip(export / "no-document.docx", {"word/other.xml": "<x/>"})
    make_zip(export / "bad-xml.docx", {"word/document.xml": "<w:document"})
    put(export / "broken.pdf", b"%PDF-1.4 not really")
    records = drive.read_docs(export)
    assert [r["path"] for r in records if r] == ["good.txt"]
    assert records.count(None) == 5


def test_ingest_writes_the_docs_stream_and_reruns_are_no_ops(tmp_path):
    export = make_drive(tmp_path)
    put(export / "broken.docx", b"not a zip")
    vault = tmp_path / "vault"

    first = drive.ingest(vault, export)
    assert first == {"read": 10, "added": 10, "updated": 0, "months_written": 1, "skipped": 1}
    lines = (vault / "raw" / "drive" / "docs" / "2024-03.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 10
    assert all(r["ts"].endswith("Z") and r["id"] == r["path"] for r in records)

    again = drive.ingest(vault, export)
    assert again["added"] == 0 and again["updated"] == 0 and again["months_written"] == 0

    put(export / "todo.txt", "buy milk\n")
    changed = drive.ingest(vault, export)
    assert changed["updated"] == 1 and changed["added"] == 0


def test_the_same_file_in_two_takeouts_is_one_record(tmp_path):
    first, second = tmp_path / "a" / "Drive", tmp_path / "b" / "Drive"
    put(first / "shared.txt", "same")
    put(second / "shared.txt", "same")
    vault = tmp_path / "vault"
    drive.ingest(vault, first)
    stats = drive.ingest(vault, second)
    assert stats["added"] == 0 and stats["months_written"] == 0


def test_a_missing_folder_is_an_error(tmp_path):
    try:
        drive.ingest(tmp_path / "vault", tmp_path / "nowhere")
    except FileNotFoundError as e:
        assert "nowhere" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")
