"""Notes ingester against synthetic Notion, Obsidian and PDF exports. No real data lives here."""

import json
import os
from datetime import UTC, datetime

import pytest

from twin.ingest import notes

HEX = "0123456789abcdef0123456789abcdef"
HEX2 = "fedcba9876543210fedcba9876543210"
UUID = "12345678-9abc-def0-1234-56789abcdef0"


def seconds(*args):
    return datetime(*args, tzinfo=UTC).timestamp()


def write(path, text, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def make_pdf(path, text, title=None, created="D:20250102030405+00'00'"):
    """A one-page PDF with a line of Helvetica text, written by hand so tests need no PDF tool."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    info = f"/CreationDate ({created})" + (f" /Title ({title})" if title else "")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< {info} >>".encode(),
    ]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\n" % (len(objects) + 1)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def make_notion(root):
    write(
        root / f"Readings {HEX}.md",
        "# Readings\n\nCreated: March 5, 2024 4:15 PM\nTags: papers\n\nWhat I read this term.\n",
    )
    write(
        root / "Readings" / f"Untitled {HEX2}.md",
        "# Untitled\n\nDate: 2024/04/01\n\nA stub.\n",
        mtime=seconds(2024, 6, 1),
    )
    header = "Name,Author,Created,Status,Year\n"
    write(
        root / "Readings" / f"Papers {HEX2}.csv",
        "\ufeff" + header + 'Old view only,A,"March 1, 2024 9:00 AM",,2020\n',
    )
    write(
        root / "Readings" / f"Papers {HEX2}_all.csv",
        "\ufeff"
        + header
        + 'Working memory,"Sample, A",March 1 2024,Read,2020\n'
        + 'Working memory,"Other, B","March 2, 2024 10:30 AM",,2021\n'
        + ",,,,\n"
        + 'Attention,C,"March 3, 2024",To read,2022\n',
        mtime=seconds(2024, 9, 9),
    )
    write(
        root / f"Tasks {HEX}.csv",
        "Task,Archive,Complete,Importance,Due\n"
        'Write draft,0,No,Important,"May 1, 2024"\n'
        "Book flights,1,Yes,Not Important,\n"
        ",0,No,,\n",
        mtime=seconds(2024, 10, 1),
    )
    write(root / "Other.csv", "Name,Status\nNot Notion,Done\n")
    return root


def make_obsidian(root):
    vault = root / "obsidian" / "research"
    write(vault / ".obsidian" / "app.json", "{}")
    write(
        vault / "Kernel Methods.md", "Some notes on kernels.\n## A section\n", seconds(2024, 7, 2)
    )
    write(
        vault / "Lab" / "Plan.md",
        "---\ntitle: ignored\ndate: 2024-02-03\n---\n# The plan\n\nSteps.\n",
        seconds(2024, 9, 9),
    )
    # A Mac zip stores "Alexαndria" as UTF-8 read as cp437.
    write(vault / "Alexαndria.md".encode().decode("cp437"), "Library notes.\n", seconds(2024, 8, 1))
    write(vault / "Empty.md", "  \n")
    write(root / "__MACOSX" / "obsidian" / "research" / "._Plan.md", "junk")
    return root


def by_title(records):
    return {r["title"]: r for r in records if r}


def stream(vault, name):
    out = vault / "raw" / "notes" / name
    lines = [line for path in sorted(out.glob("*.jsonl")) for line in path.read_text().splitlines()]
    return [json.loads(line) for line in lines]


def test_notion_markdown_takes_title_and_dates_from_its_properties(tmp_path):
    pages = by_title(notes.read_pages(make_notion(tmp_path / "e")))
    assert set(pages) == {"Readings", "Untitled"}

    readings = pages["Readings"]
    assert readings["id"] == f"md/{HEX}"
    assert readings["ts"] == "2024-03-05T16:15:00Z"
    assert (readings["kind"], readings["collection"], readings["from_me"]) == ("md", None, True)
    assert readings["text"].endswith("What I read this term.")

    stub = pages["Untitled"]
    assert (stub["id"], stub["ts"], stub["collection"]) == (
        f"md/{HEX2}",
        "2024-04-01T00:00:00Z",
        "Readings",
    )


def test_database_rows_keep_their_properties_and_prefer_the_all_csv(tmp_path):
    rows = [r for r in notes.read_rows(make_notion(tmp_path / "e")) if r]
    papers = [r for r in rows if r["collection"] == "Readings/Papers"]
    assert sorted(r["title"] for r in papers) == ["Attention", "Working memory", "Working memory"]

    attention = by_title(papers)["Attention"]
    assert attention["kind"] == "csv_row"
    assert attention["properties"] == {
        "Name": "Attention",
        "Author": "C",
        "Created": "March 3, 2024",
        "Status": "To read",
        "Year": "2022",
    }
    assert attention["ts"] == "2024-03-03T00:00:00Z"

    # Two rows with one title get #2, and a date that won't parse falls back on the file's time.
    twins = sorted((r for r in papers if r["title"] == "Working memory"), key=lambda r: r["id"])
    assert twins[1]["id"] == twins[0]["id"] + "#2"
    assert {r["ts"] for r in twins} == {"2024-03-02T10:30:00Z", "2024-09-09T00:00:00Z"}
    # A CSV without a Notion id isn't a database export.
    assert not [r for r in rows if r["title"] == "Not Notion"]


def test_tasks_are_rows_with_a_status_or_due_date_or_in_a_tasks_database(tmp_path):
    rows = notes.read_rows(make_notion(tmp_path / "e"))
    tasks = by_title(notes.read_tasks(rows))
    assert set(tasks) == {"Write draft", "Book flights", "Working memory", "Attention"}

    draft = tasks["Write draft"]
    assert (draft["status"], draft["due"], draft["ts"], draft["collection"]) == (
        "Not started",
        "2024-05-01T00:00:00Z",
        "2024-05-01T00:00:00Z",
        "Tasks",
    )
    assert draft["properties"]["Importance"] == "Important"
    assert draft["id"] == next(r["id"] for r in rows if r and r["title"] == "Write draft")

    flights = tasks["Book flights"]
    assert (flights["status"], flights["due"], flights["ts"]) == (
        "Done",
        None,
        "2024-10-01T00:00:00Z",
    )
    assert tasks["Attention"]["status"] == "To read"


def test_obsidian_notes_are_collected_from_the_vault_folder(tmp_path):
    pages = by_title(notes.read_pages(make_obsidian(tmp_path / "e")))
    assert set(pages) == {"Kernel Methods", "The plan", "Alexαndria"}

    kernels = pages["Kernel Methods"]  # no top-level heading: the file name
    assert (kernels["id"], kernels["ts"], kernels["collection"]) == (
        "md/research/Kernel Methods",
        "2024-07-02T00:00:00Z",
        "research",
    )
    plan = pages["The plan"]
    assert (plan["id"], plan["ts"], plan["collection"]) == (
        "md/research/Lab/Plan",
        "2024-02-03T00:00:00Z",
        "research/Lab",
    )
    assert plan["text"] == "# The plan\n\nSteps."
    assert pages["Alexαndria"]["id"] == "md/research/Alexαndria"


def test_pdfs_are_read_with_their_title_and_creation_date(tmp_path):
    folder = tmp_path / "pdfs"
    make_pdf(folder / f"{UUID}_Road_Trip_Plan.pdf", "Pack the tent", title="Road Trip (Plan)")
    make_pdf(folder / "Lab" / f"Meeting {HEX}.pdf", "Next steps", created="D:20240102")
    (folder / "broken.pdf").write_bytes(b"%PDF-1.4 not really")

    records = notes.read_pdfs(folder)
    assert records.count(None) == 1
    pdfs = by_title(records)
    trip = pdfs["Road Trip (Plan)"]
    assert (trip["id"], trip["ts"], trip["kind"], trip["collection"]) == (
        f"pdf/{UUID}",
        "2025-01-02T03:04:05Z",
        "pdf",
        None,
    )
    assert "Pack the tent" in trip["text"]
    meeting = pdfs["Meeting"]  # no Title: the file name without its Notion id
    assert (meeting["id"], meeting["ts"], meeting["collection"]) == (
        f"pdf/{HEX}",
        "2024-01-02T00:00:00Z",
        "Lab",
    )


def test_ingest_writes_pages_and_tasks_and_reruns_are_no_ops(tmp_path):
    export = make_notion(tmp_path / "e")
    make_pdf(tmp_path / "pdfs" / "Loose.pdf", "Hello", title="Loose")
    vault = tmp_path / "vault"
    first = notes.ingest(vault, export, tmp_path / "pdfs")
    assert first["skipped"] == 0
    assert first["added"] == len(stream(vault, "pages")) + len(stream(vault, "tasks"))
    assert {r["kind"] for r in stream(vault, "pages")} == {"md", "csv_row", "pdf"}
    assert len(stream(vault, "tasks")) == 4

    again = notes.ingest(vault, export, tmp_path / "pdfs")
    assert (again["added"], again["updated"], again["months_written"]) == (0, 0, 0)


def test_ingest_needs_something_to_read(tmp_path):
    with pytest.raises(ValueError):
        notes.ingest(tmp_path / "vault")
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        notes.ingest(tmp_path / "vault", tmp_path / "empty")
