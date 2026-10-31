"""Medical records in FHIR: Apple Health's clinical records and patient portal downloads.

Reads FHIR R4 JSON: Apple Health's export.zip (or the folder it unzips to), whose
apple_health_export/clinical-records/ holds one resource per file for every account connected
under Health Records, and any FHIR Bundle (.json) or NDJSON file that a patient portal or app
lets the user download. `--export` takes a zip, a folder (searched all the way down) or one
file. Bundles are opened, and the DSTU2 records some older Apple Health connections hold are read
wherever their fields match R4's.

Each resource of a kind it knows becomes one plain record, in a stream of
vault/raw/healthrecords/:
- observations (Observation: labs and vitals): name, category, value, unit, low and high (the
  reference range's ends), range (the reference range as written, else built from low and
  high), flag (the record's own interpretation, such as "high"; never worked out here) and
  components (each part of a blood pressure, say), each {name, value, unit};
- conditions (Condition): name, category, verification and abated (the day it ended);
- medications (MedicationRequest, MedicationStatement, and DSTU2's MedicationOrder): name,
  intent, dosage (the instructions as written) and reason;
- encounters (Encounter): name (the kind of visit), class (ambulatory, emergency, inpatient
  and so on), reason, location (the place or organization) and end;
- reports (DiagnosticReport): name, category, results (the names of what it reports) and
  conclusion;
- allergies (AllergyIntolerance): name, category, criticality, verification and reactions;
- immunizations (Immunization): name; procedures (Procedure): name, reason and location;
- documents (DocumentReference): title only. The document itself is never kept.

Every record also has type (the resource type), status (a condition's or allergy's clinical
status, else the record's own, such as "final" or "active"), from_me and text: one plain line
of what it says, for search. from_me is False: clinicians write these, so the observers, which
read only the user's own words, leave them alone. No one is named in them. The patient,
practitioners and authors are left out; only organizations and places stay. A value is kept as
the record gives it: a number stays a number, and a comparator stays with it ("<0.5").

ts is when it happened: an observation's or report's effective time (else when it was issued),
a condition's or allergy's onset (else when it was recorded), a prescription's authored date,
a medication statement's effective time, a visit's period, an immunization's date, a
procedure's performed time, a document's period of care (else its date). A date with no time
is read as noon UTC, so it falls on the same day in nearly every time zone.

The id is "<resource type>/<its id>", so the same resource read twice, from Apple Health and
from the same provider's download, or from two exports, is one record; a resource without an id
is keyed by a hash of its content. A resource marked entered-in-error is kept with that status,
so it replaces the copy read before. Other resource types (Patient, Practitioner, Organization,
Medication, Claim and so on) are counted as other and not kept. A file that won't parse, or a
resource of a kind it knows with no time it can read, is counted as skipped.
"""

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from proxenos.store import merge_monthly

STREAMS = {
    "Observation": "observations",
    "Condition": "conditions",
    "MedicationRequest": "medications",
    "MedicationStatement": "medications",
    "MedicationOrder": "medications",  # DSTU2's prescription
    "Encounter": "encounters",
    "DiagnosticReport": "reports",
    "AllergyIntolerance": "allergies",
    "Immunization": "immunizations",
    "Procedure": "procedures",
    "DocumentReference": "documents",
}

# Where each kind of resource says when it happened, in the order they're tried. A Period counts
# from its start.
_WHEN = {
    "Observation": ("effectiveDateTime", "effectiveInstant", "effectivePeriod", "issued"),
    "Condition": ("onsetDateTime", "onsetPeriod", "recordedDate", "dateRecorded"),
    "MedicationRequest": ("authoredOn",),
    "MedicationStatement": ("effectiveDateTime", "effectivePeriod", "dateAsserted"),
    "MedicationOrder": ("dateWritten",),
    "Encounter": ("period",),
    "DiagnosticReport": ("effectiveDateTime", "effectivePeriod", "issued"),
    "AllergyIntolerance": ("onsetDateTime", "onsetPeriod", "recordedDate", "onset"),
    "Immunization": ("occurrenceDateTime", "date", "recorded"),
    "Procedure": ("performedDateTime", "performedPeriod"),
    "DocumentReference": ("context.period", "date", "indexed"),
}

_LABELS = {
    "Observation": "observation",
    "Condition": "condition",
    "MedicationRequest": "prescription",
    "MedicationOrder": "prescription",
    "MedicationStatement": "medication",
    "Encounter": "visit",
    "DiagnosticReport": "report",
    "AllergyIntolerance": "allergy",
    "Immunization": "immunization",
    "Procedure": "procedure",
    "DocumentReference": "document",
}

# Words for the codes a record may give without a display: HL7's interpretation flags and
# encounter classes.
_FLAGS = {
    "H": "high",
    "HH": "critically high",
    "L": "low",
    "LL": "critically low",
    "A": "abnormal",
    "AA": "critically abnormal",
    "N": "normal",
    "POS": "positive",
    "NEG": "negative",
}
_CLASSES = {
    "AMB": "ambulatory",
    "EMER": "emergency",
    "IMP": "inpatient",
    "ACUTE": "inpatient",
    "NONAC": "inpatient",
    "OBSENC": "observation",
    "SS": "short stay",
    "VR": "virtual",
    "HH": "home health",
}
# Statuses that say nothing a reader needs: the record is simply done.
_ROUTINE = {"final", "finished", "current", "confirmed"}

_DATE_ONLY = re.compile(r"\d{4}(-\d{2}(-\d{2})?)?")
_COMPARED = re.compile(r"(<=|>=|<|>)\s*-?\d+(\.\d+)?")


def read_records(export: Path) -> tuple[dict[str, list[dict]], Counter]:
    """Every record in an export, by stream, and how many were skipped or of other types."""
    resources, unreadable = _read(export)
    index = _index(resources)
    streams: dict[str, list[dict]] = defaultdict(list)
    counts = Counter(skipped=unreadable, other=0)
    for resource in resources:
        stream = STREAMS.get(resource["resourceType"])
        if stream is None:
            counts["other"] += 1
            continue
        try:
            record = _record(resource, index)
        except (KeyError, TypeError, ValueError, AttributeError):
            record = None
        if record is None:
            counts["skipped"] += 1
        else:
            streams[stream].append(record)
    return streams, counts


def ingest(vault: Path, export: Path) -> dict[str, int]:
    if not export.exists():
        raise FileNotFoundError(f"no file or folder at {export}")
    streams, counts = read_records(export)
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, **counts}
    out = vault / "raw" / "healthrecords"
    for stream, records in sorted(streams.items()):
        # Keyed by id: a resource in two files is one record, and the last copy wins.
        kept = {r["id"]: r for r in records}
        for key, value in merge_monthly(kept.values(), out / stream).items():
            stats[key] += value
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export",
        type=Path,
        required=True,
        metavar="PATH",
        help="Apple Health's export.zip, or a FHIR folder, Bundle or NDJSON file",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.export.expanduser())


def label(record: dict) -> str:
    """What kind of record it is, in plain words: "lab result", "visit", "prescription"."""
    if record.get("type") == "Observation":
        category = str(record.get("category") or "").lower()
        if "vital" in category:
            return "vital sign"
        if "lab" in category:
            return "lab result"
    return _LABELS.get(str(record.get("type")), "record")


def describe(record: dict, clean: Callable[[str], str] = str) -> str:
    """One plain line of what a record says. `clean` runs over its words (names, reasons,
    places, conclusions, a result written as words), never over a measured value, its unit or
    its reference range: a result is not an identifier, whatever its digits."""
    kind = record.get("type")
    name = clean(str(record.get("name") or record.get("title") or label(record)))
    if kind == "DocumentReference":
        return name
    status = record.get("status")
    status = None if status in _ROUTINE else status
    if kind == "Observation":
        results = []
        if record.get("value") is not None:
            results.append(_result(record["value"], record.get("unit"), clean))
        for part in record.get("components") or []:
            if part.get("value") is not None:
                shown = _result(part["value"], part.get("unit"), clean)
                results.append(f"{clean(str(part.get('name') or ''))} {shown}".strip())
        line = name + (f": {'; '.join(results)}" if results else "")
        if record.get("range"):
            line += f" (reference {record['range']})"
        for word in (record.get("flag"), status):
            if word:
                line += f", {clean(word)}"
        return line

    details = [record.get("class"), status]
    if record.get("verification") not in (None, *_ROUTINE):
        details.append(record["verification"])
    if record.get("criticality"):
        details.append(f"{record['criticality']} criticality")
    if kind == "AllergyIntolerance":
        details.append(record.get("category"))
    details = [clean(str(d)) for d in details if d]
    line = name + (f" ({', '.join(details)})" if details else "")
    sentences = [line]
    end = record.get("end")
    if end and end[:10] != str(record.get("ts"))[:10]:
        sentences.append(f"Until {end[:10]}")
    for key, title in (
        ("abated", "Ended"),
        ("location", "At"),
        ("dosage", "Dosage:"),
        ("reason", "Reason:"),
        ("results", "Results:"),
        ("reactions", "Reactions:"),
        ("conclusion", "Conclusion:"),
    ):
        value = record.get(key)
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        if value:
            sentences.append(f"{title} {clean(str(value))}")
    return ". ".join(sentences)


# ── Reading ─────────────────────────────────────────────────────────────────


def _read(export: Path) -> tuple[list[dict], int]:
    """Every resource in the export, and how many files (or NDJSON lines) wouldn't parse."""
    resources, unreadable = [], 0
    for name, load in _files(export):
        try:
            text = load()
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            unreadable += 1
            continue
        for value in _values(text, name.lower().endswith(".ndjson")):
            if value is None:
                unreadable += 1
            else:
                resources.extend(_resources(value))
    return resources, unreadable


def _files(export: Path) -> Iterator[tuple[str, Callable[[], str]]]:
    """(name, a function that reads it) for each JSON or NDJSON file in a folder or zip, or for
    the one file given."""
    if export.is_dir():
        for path in sorted(export.rglob("*")):
            if _wanted(path.relative_to(export).as_posix()) and path.is_file():
                yield path.name, lambda path=path: path.read_text("utf-8-sig", errors="replace")
    elif zipfile.is_zipfile(export):
        # Read in place: Apple's zip also holds export.xml, which can be gigabytes.
        with zipfile.ZipFile(export) as archive:
            for info in archive.infolist():
                if not info.is_dir() and _wanted(info.filename):
                    yield (
                        info.filename,
                        lambda info=info: archive.read(info).decode("utf-8-sig", errors="replace"),
                    )
    else:
        yield export.name, lambda: export.read_text("utf-8-sig", errors="replace")


def _wanted(name: str) -> bool:
    parts = name.split("/")
    return (
        name.lower().endswith((".json", ".ndjson"))
        and "__MACOSX" not in parts
        and not any(part.startswith(".") for part in parts)
    )


def _values(text: str, ndjson: bool) -> list[object | None]:
    """The JSON in a file: one value, or one per line for NDJSON (which some downloads name
    .json). None stands for a file, or a line, that won't parse."""
    if not ndjson:
        try:
            return [json.loads(text)]
        except ValueError:
            pass
    values = [_loads(line) for line in text.splitlines() if line.strip()]
    if not any(isinstance(v, dict) for v in values):
        return [None]
    return values


def _loads(line: str) -> object | None:
    try:
        return json.loads(line)
    except ValueError:
        return None


def _resources(value: object) -> Iterator[dict]:
    """The resources in what a file held: itself, a Bundle's entries (Bundles in it too) or a
    JSON array of them."""
    if isinstance(value, list):
        for item in value:
            yield from _resources(item)
    elif isinstance(value, dict) and isinstance(value.get("resourceType"), str):
        if value["resourceType"] == "Bundle":
            for entry in value.get("entry") or []:
                if isinstance(entry, dict):
                    yield from _resources(entry.get("resource"))
        else:
            yield value


def _index(resources: list[dict]) -> dict[str, dict]:
    """Resources by the references that point at them: "Type/id", and "urn:uuid:id" as a
    Bundle's entries (Synthea's among them) refer to each other."""
    index = {}
    for r in resources:
        if r.get("id"):
            index[f"{r['resourceType']}/{r['id']}"] = r
            index[f"urn:uuid:{r['id']}"] = r
    return index


# ── Records ─────────────────────────────────────────────────────────────────


def _record(resource: dict, index: dict[str, dict]) -> dict | None:
    kind = resource["resourceType"]
    ts = next((t for path in _WHEN[kind] if (t := _stamp(_at(resource, path)))), None)
    if ts is None:
        return None
    rid = resource.get("id")
    record = {
        "id": f"{kind}/{rid}" if rid else f"{kind}/{_hash(resource)}",
        "ts": ts,
        "type": kind,
        "from_me": False,
        **_FIELDS[STREAMS[kind]](resource, index),
    }
    record["text"] = describe(record)
    return record


def _observation(r: dict, index: dict) -> dict:
    value, unit = _value(r)
    low, high, written = _range(r.get("referenceRange"))
    components = []
    for part in _list(r.get("component")):
        if isinstance(part, dict):
            part_value, part_unit = _value(part)
            components.append(
                {"name": _concept(part.get("code")) or None, "value": part_value, "unit": part_unit}
            )
    return {
        "name": _concept(r.get("code")) or None,
        "category": _concept(r.get("category")) or None,
        "status": _code(r.get("status")),
        "value": value,
        "unit": unit,
        "low": low,
        "high": high,
        "range": written,
        "flag": _concept(r.get("interpretation"), _FLAGS).lower() or None,
        "components": components or None,
    }


def _condition(r: dict, index: dict) -> dict:
    return {
        "name": _concept(r.get("code")) or None,
        "category": _concept(r.get("category")) or None,
        "status": _code(r.get("clinicalStatus")),
        "verification": _code(r.get("verificationStatus")),
        "abated": _day(r.get("abatementDateTime") or r.get("abatementPeriod")),
    }


def _medication(r: dict, index: dict) -> dict:
    name = _concept(r.get("medicationCodeableConcept"))
    instructions = _list(r.get("dosageInstruction")) or _list(r.get("dosage"))
    dosage = next(
        (
            " ".join(str(d.get("text") or d.get("patientInstruction")).split())
            for d in instructions
            if isinstance(d, dict) and (d.get("text") or d.get("patientInstruction"))
        ),
        None,
    )
    return {
        "name": name or _referenced(r.get("medicationReference"), r, index) or None,
        "status": _code(r.get("status")),
        "intent": _code(r.get("intent")),
        "dosage": dosage,
        "reason": _reasons(r, index),
    }


def _encounter(r: dict, index: dict) -> dict:
    places = [p.get("location") for p in _list(r.get("location")) if isinstance(p, dict)]
    location = next((n for p in places if (n := _referenced(p, r, index))), "")
    period = r.get("period") if isinstance(r.get("period"), dict) else {}
    return {
        "name": _concept(r.get("type")) or None,
        "class": _concept(r.get("class"), _CLASSES).lower() or None,
        "status": _code(r.get("status")),
        "reason": _reasons(r, index),
        "location": location or _referenced(r.get("serviceProvider"), r, index) or None,
        "end": _stamp(period.get("end")),
    }


def _report(r: dict, index: dict) -> dict:
    results = [_referenced(ref, r, index) for ref in _list(r.get("result"))]
    conclusion = " ".join(str(r.get("conclusion") or "").split())
    if not conclusion:
        conclusion = "; ".join(c for c in map(_concept, _list(r.get("conclusionCode"))) if c)
    return {
        "name": _concept(r.get("code")) or None,
        "category": _concept(r.get("category")) or None,
        "status": _code(r.get("status")),
        "results": list(dict.fromkeys(n for n in results if n)) or None,
        "conclusion": conclusion or None,
    }


def _allergy(r: dict, index: dict) -> dict:
    reactions = [
        _concept(m)
        for reaction in _list(r.get("reaction"))
        if isinstance(reaction, dict)
        for m in _list(reaction.get("manifestation"))
    ]
    categories = [str(c) for c in _list(r.get("category")) if isinstance(c, str)]
    return {
        "name": _concept(r.get("code")) or _concept(r.get("substance")) or None,
        "category": ", ".join(categories) or None,
        "status": _code(r.get("clinicalStatus")) or _code(r.get("status")),
        "verification": _code(r.get("verificationStatus")),
        "criticality": _code(r.get("criticality")),
        "reactions": list(dict.fromkeys(n for n in reactions if n)) or None,
    }


def _immunization(r: dict, index: dict) -> dict:
    return {"name": _concept(r.get("vaccineCode")) or None, "status": _code(r.get("status"))}


def _procedure(r: dict, index: dict) -> dict:
    return {
        "name": _concept(r.get("code")) or None,
        "status": _code(r.get("status")),
        "reason": _reasons(r, index),
        "location": _referenced(r.get("location"), r, index) or None,
    }


def _document(r: dict, index: dict) -> dict:
    attachments = [c.get("attachment") for c in _list(r.get("content")) if isinstance(c, dict)]
    titles = [a.get("title") for a in attachments if isinstance(a, dict) and a.get("title")]
    title = r.get("description") or next(iter(titles), None) or _concept(r.get("type"))
    return {"title": " ".join(str(title or "").split()) or None, "status": _code(r.get("status"))}


_FIELDS: dict[str, Callable[[dict, dict], dict]] = {
    "observations": _observation,
    "conditions": _condition,
    "medications": _medication,
    "encounters": _encounter,
    "reports": _report,
    "allergies": _allergy,
    "immunizations": _immunization,
    "procedures": _procedure,
    "documents": _document,
}


# ── FHIR's data types ───────────────────────────────────────────────────────


def _concept(value: object, words: dict[str, str] | None = None) -> str:
    """A CodeableConcept (or Coding, or a list of either) in words: its text, else the first
    display, else a code, in `words` when it's there."""
    if isinstance(value, list):
        value = next((v for v in value if v), None)
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, dict):
        return ""
    if value.get("text"):
        return " ".join(str(value["text"]).split())
    codings = [c for c in _list(value.get("coding")) if isinstance(c, dict)] or [value]
    for coding in codings:
        if coding.get("display"):
            return " ".join(str(coding["display"]).split())
    for coding in codings:
        if coding.get("code"):
            code = str(coding["code"])
            return (words or {}).get(code, code)
    return ""


def _code(value: object) -> str | None:
    """A status or other code: as written, or a CodeableConcept's first code, lowercased."""
    if isinstance(value, list):
        value = next(iter(value), None)
    if isinstance(value, dict):
        codes = [
            c["code"] for c in _list(value.get("coding")) if isinstance(c, dict) and c.get("code")
        ]
        value = codes[0] if codes else value.get("code") or value.get("text")
    text = str(value or "").strip().lower()
    return text or None


def _referenced(reference: object, owner: dict, index: dict[str, dict]) -> str:
    """What a Reference names: its display, else the name of the resource it points at, when
    that's in the export or contained in its owner."""
    if not isinstance(reference, dict):
        return ""
    if reference.get("display"):
        return " ".join(str(reference["display"]).split())
    target = str(reference.get("reference") or "")
    if target.startswith("#"):
        contained = [c for c in _list(owner.get("contained")) if isinstance(c, dict)]
        found = next((c for c in contained if c.get("id") == target[1:]), None)
    else:
        found = index.get(target) or index.get("/".join(target.split("/")[-2:]))
    if not found:
        return ""
    name = found.get("name")
    return _concept(found.get("code")) or (" ".join(name.split()) if isinstance(name, str) else "")


def _reasons(r: dict, index: dict) -> str | None:
    concepts = [
        *_list(r.get("reasonCode")),
        *_list(r.get("reasonCodeableConcept")),  # DSTU2's MedicationOrder
        *_list(r.get("reason")),  # DSTU2's Encounter
    ]
    names = [_concept(c) for c in concepts]
    names += [_referenced(ref, r, index) for ref in _list(r.get("reasonReference"))]
    return "; ".join(dict.fromkeys(n for n in names if n)) or None


def _value(holder: dict) -> tuple[object, str | None]:
    """A result and its unit: a Quantity's number (with its comparator, as "<0.5"), a coded
    answer's words, or a string, integer or yes/no as given."""
    quantity = holder.get("valueQuantity")
    if isinstance(quantity, dict) and quantity.get("value") is not None:
        value = quantity["value"]
        if quantity.get("comparator"):
            value = f"{quantity['comparator']}{value}"
        return value, _unit(quantity)
    for key in ("valueString", "valueInteger", "valueBoolean", "valueDateTime", "valueTime"):
        if holder.get(key) is not None and not isinstance(holder[key], (dict, list)):
            return holder[key], None
    return _concept(holder.get("valueCodeableConcept")) or None, None


def _range(ranges: object) -> tuple[object, object, str | None]:
    """A reference range's low and high, and how it reads: as written, else from its ends."""
    first = next((r for r in _list(ranges) if isinstance(r, dict)), None)
    if first is None:
        return None, None, None
    low, high = _quantity(first.get("low")), _quantity(first.get("high"))
    written = " ".join(str(first.get("text") or "").split())
    if not written and (low is not None or high is not None):
        if low is not None and high is not None:
            written = f"{low} to {high}"
        else:
            written = f">={low}" if low is not None else f"<={high}"
        unit = _unit(first.get("low")) or _unit(first.get("high"))
        written += f" {unit}" if unit else ""
    return low, high, written or None


def _result(value: object, unit: object, clean: Callable[[str], str]) -> str:
    if isinstance(value, bool):
        shown = "yes" if value else "no"
    elif isinstance(value, (int, float)) or _COMPARED.fullmatch(str(value)):
        shown = str(value)
    else:
        shown = clean(" ".join(str(value).split()))
    return f"{shown} {unit}" if unit else shown


def _quantity(value: object) -> object:
    return value.get("value") if isinstance(value, dict) else None


def _unit(quantity: object) -> str | None:
    if not isinstance(quantity, dict):
        return None
    unit = quantity.get("unit") or quantity.get("code")
    return str(unit) if unit else None


def _list(value: object) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def _at(resource: dict, path: str) -> object:
    value: object = resource
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _stamp(value: object) -> str | None:
    """A FHIR date, dateTime, instant or Period (its start, else its end) as UTC ISO."""
    if isinstance(value, dict):
        return _stamp(value.get("start")) or _stamp(value.get("end"))
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _DATE_ONLY.fullmatch(text):
        text = (text + "-01-01")[:10] + "T12:00:00+00:00"
    try:
        when = datetime.fromisoformat(text)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return None


def _day(value: object) -> str | None:
    """The day a date, dateTime or Period starts, as written (YYYY-MM-DD, or less)."""
    if isinstance(value, dict):
        value = value.get("start") or value.get("end")
    if not isinstance(value, str):
        return None
    match = _DATE_ONLY.match(value.strip())
    return match[0] if match else None


def _hash(resource: dict) -> str:
    return hashlib.sha256(json.dumps(resource, sort_keys=True).encode()).hexdigest()[:16]
