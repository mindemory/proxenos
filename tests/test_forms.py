"""Filling a synthetic PDF form, with the model and memory faked out. No network, no real data."""

import json
import re

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from proxenos import cli, forms, llm, research


def circle(x, y, r=4):
    k = 0.5523 * r
    return (
        f"{x + r} {y} m {x + r} {y + k} {x + k} {y + r} {x} {y + r} c "
        f"{x - k} {y + r} {x - r} {y + k} {x - r} {y} c {x - r} {y - k} {x - k} {y - r} {x} {y - r} c "
        f"{x + k} {y - r} {x + r} {y - k} {x + r} {y} c S"
    )


def label(x, y, text):
    return f"BT /F1 9 Tf {x} {y} Td ({text}) Tj ET"


def make_form(path):
    ops = [
        "0.5 w 36 639 m 576 639 l S",  # labels under the line: one blank each
        label(36, 629, "Last Name"),
        label(180, 629, "First Name"),
        label(324, 629, "SSN#"),
        label(430, 629, "Date of Birth"),
        label(36, 600, "Employer:"),  # a label left of its line
        "100 600 m 300 600 l S",
        label(47, 570, "Single"),
        circle(40.5, 573.5),
        label(110, 570, "Married"),
        circle(103.5, 573.5),
        label(36, 540, "Are you a veteran?"),
        label(200, 540, "Yes"),
        circle(193.5, 543.5),
        label(240, 540, "No"),
        circle(233.5, 543.5),
        "36 100 m 576 100 l S",
        label(36, 90, "Applicant Signature"),
        label(300, 90, "Date"),
    ]
    page = PageObject.create_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    writer = PdfWriter()
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_page(page)
    with path.open("wb") as f:
        writer.write(f)


def test_a_form_is_filled_from_records_and_the_private_lines_are_left(tmp_path, monkeypatch):
    vault, form = tmp_path / "vault", tmp_path / "application.pdf"
    make_form(form)
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    record = {
        "id": "r1", "ts": "2026-03-01T00:00:00Z", "source": "notes", "where_": "notes",
        "from_me": True, "who": "", "title": "",
        "snippet": "Tess Lee, born 01/02/1990, SSN 123-45-6789, works at Acme Labs",
    }  # fmt: skip
    monkeypatch.setattr(research, "_search", lambda vault, query, who: [record])
    calls = []

    def ask(prompt, *, system=None, schema=None, **kw):
        calls.append(prompt)
        ids = dict(re.findall(r"^- (b\d+) \(page 1\): ([^,\n;]+)", prompt, re.MULTILINE))
        blank = {name: key for key, name in ids.items()}
        choice = {
            (name, question): key
            for key, name, question in re.findall(
                r"^- (c\d+) \(page 1\): (\w+), for: (.*)$", prompt, re.MULTILINE
            )
        }
        return {
            "fills": [
                {"id": blank["Last Name"], "value": "Lee", "column": "", "from": "notes"},
                {"id": blank["First Name"], "value": "Tess", "column": "", "from": "notes"},
                {
                    "id": blank["Date of Birth"],
                    "value": "01/02/1990",
                    "column": "",
                    "from": "notes",
                },
                {"id": blank["Employer"], "value": "Acme Labs", "column": "", "from": "notes"},
                {"id": "b99", "value": "nowhere", "column": "", "from": ""},
            ],
            "marks": [
                choice[("Single", "(no question)")],
                choice[("No", "Are you a veteran?")],
                choice[("Yes", "Are you a veteran?")],  # a second option for the same question
            ],
        }

    monkeypatch.setattr(llm, "ask", ask)
    report = forms.fill(vault, form)

    [prompt] = calls
    asked = prompt.split("## Choices")[0]
    assert "SSN#" not in asked and "Signature" not in asked  # never asked about
    assert "Date of Birth" in asked
    assert "123-45-6789" not in prompt and "[number]" in prompt
    out = tmp_path / "application-filled.pdf"
    assert report["filled_copy"] == str(out)
    text = PdfReader(out).pages[0].extract_text()
    for value in ("Lee", "Tess", "01/02/1990", "Acme Labs"):
        assert value in text
    assert [(m["question"], m["option"]) for m in report["marked"]] == [
        ("", "Single"),
        ("Are you a veteran?", "No"),
    ]
    left = {(item["label"], item["why"]) for item in report["left"]}
    assert ("SSN#", "yours to write") in left
    assert ("Applicant Signature", "yours to write") in left and ("Date", "yours to write") in left
    saved = json.loads((vault / "clones" / "forms" / "application.json").read_text())
    assert saved["filled"][0] == {"page": 0, "label": "Last Name", "value": "Lee", "from": "notes"}


def test_a_fillable_pdf_s_own_fields_are_read_by_their_names():
    fields = {
        "applicant_name": {"/FT": "/Tx", "/TU": "Full name"},
        "ssn": {"/FT": "/Tx", "/TU": "Social Security Number"},
        "veteran": {"/FT": "/Btn", "/_States_": ["/Yes", "/Off"], "/TU": "Veteran?"},
    }

    form = forms._fields(fields)

    assert [(b["label"], b["private"]) for b in form["blanks"]] == [
        ("Full name", False),
        ("Social Security Number", True),
    ]
    assert [(c["label"], c["question"], c["state"]) for c in form["choices"]] == [
        ("Yes", "Veteran?", "/Yes")
    ]


def test_the_command_fills_a_form_and_says_what_is_left(tmp_path, monkeypatch, capsys):
    form = tmp_path / "f.pdf"
    make_form(form)
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    monkeypatch.setattr(research, "_search", lambda vault, query, who: [])
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: {"fills": [], "marks": []})

    cli.main(["form", str(form)])

    out = capsys.readouterr().out
    assert "left for you, page 1: SSN# (yours to write)" in out
    assert out.strip().endswith("form: 0 filled, 0 marked, 9 left")


def test_only_what_the_records_say_is_kept():
    shown = "DOB 01/02/1990, phone 555-010-0199, an annualized salary of $60,000, Riverton"
    assert forms._grounded("01/02/1990", shown) and not forms._grounded("01/05/1990", shown)
    assert forms._grounded("(555) 010-0199", shown)
    assert forms._grounded("5,000.00", shown)  # a twelfth of the yearly figure
    assert forms._grounded("Riverton", shown) and not forms._grounded("Lakeside", shown)


def test_a_local_model_echoing_its_schema_still_gives_its_answer():
    answer = {"fills": [{"id": "b1", "value": "x", "column": "", "from": "y"}], "marks": ["c1"]}
    text = f"```json\n{json.dumps(forms._SCHEMA)}\n{json.dumps(answer)}\n```"
    assert llm._object(text, forms._SCHEMA) == answer
    assert llm._object("no json here", forms._SCHEMA) is None
