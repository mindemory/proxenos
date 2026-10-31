"""FHIR health records reader, its import route and the care clone reading what it writes.

Every resource here is written by hand, shaped like the FHIR R4 output of Synthea, the open-source
synthetic patient generator (github.com/synthetichealth/synthea, Apache-2.0); none is copied from
it. The patient, clinicians, clinics and numbers are made up, and the model is faked out."""

import argparse
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import importer, llm, observe
from proxenos.clones import care
from proxenos.ingest import healthrecords

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
CVX = "http://hl7.org/fhir/sid/cvx"
CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
UCUM = "http://unitsofmeasure.org"


def uid(n):
    return f"5f0c1a2e-0000-4000-8000-{n:012d}"


PATIENT = uid(1)
SUBJECT = {"reference": f"urn:uuid:{PATIENT}", "display": "Ms. Alex Example"}
CLINICIAN = {"reference": "Practitioner?identifier=x|1", "display": "Dr. Jordan Example"}
CLINIC = {"reference": "Location?identifier=x|2", "display": "EXAMPLE FAMILY CLINIC"}


def coded(system, code, display):
    return {"coding": [{"system": system, "code": code, "display": display}], "text": display}


def patient():
    return {
        "resourceType": "Patient",
        "id": PATIENT,
        "name": [{"use": "official", "family": "Example", "given": ["Alex"], "prefix": ["Ms."]}],
        "birthDate": "1990-01-01",
    }


def observation(n, when, code, name, *, category="laboratory", status="final", **value):
    return {
        "resourceType": "Observation",
        "id": uid(n),
        "status": status,
        "category": [{"coding": [{"system": CATEGORY, "code": category, "display": category}]}],
        "code": coded(LOINC, code, name),
        "subject": SUBJECT,
        "encounter": {"reference": f"urn:uuid:{uid(10)}"},
        "effectiveDateTime": when,
        "issued": when,
        **value,
    }


def quantity(value, unit):
    return {"value": value, "unit": unit, "system": UCUM, "code": unit}


def encounter(n, start, end, *, kind="AMB", name="General examination of patient (procedure)"):
    return {
        "resourceType": "Encounter",
        "id": uid(n),
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": kind},
        "type": [coded(SNOMED, "162673000", name)],
        "subject": SUBJECT,
        "participant": [{"individual": CLINICIAN}],
        "period": {"start": start, "end": end},
        "location": [{"location": CLINIC}],
        "serviceProvider": {
            "reference": "Organization?identifier=x|3",
            "display": "EXAMPLE HEALTH",
        },
    }


def condition(n, onset, name, *, status="active", abated=None):
    resource = {
        "resourceType": "Condition",
        "id": uid(n),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": status,
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "category": [
            coded(
                "http://terminology.hl7.org/CodeSystem/condition-category",
                "encounter-diagnosis",
                "Encounter Diagnosis",
            )
        ],
        "code": coded(SNOMED, "59621000", name),
        "subject": SUBJECT,
        "onsetDateTime": onset,
        "recordedDate": onset,
    }
    if abated:
        resource["abatementDateTime"] = abated
    return resource


def bundle(*resources):
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{r['id']}",
                "resource": r,
                "request": {"method": "POST", "url": r["resourceType"]},
            }
            for r in resources
        ],
    }


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


VISIT = "2024-03-05T09:30:00-05:00"
VISIT_UTC = "2024-03-05T14:30:00Z"


def synthea_bundle():
    return bundle(
        patient(),
        encounter(10, VISIT, "2024-03-05T10:15:00-05:00"),
        observation(
            11,
            VISIT,
            "4548-4",
            "Hemoglobin A1c/Hemoglobin.total in Blood",
            valueQuantity=quantity(6.1, "%"),
            referenceRange=[{"low": quantity(4.0, "%"), "high": quantity(5.6, "%")}],
            interpretation=[
                coded(
                    "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                    "H",
                    "High",
                )
            ],
        ),
        observation(
            12,
            VISIT,
            "85354-9",
            "Blood pressure panel with all children optional",
            category="vital-signs",
            component=[
                {
                    "code": coded(LOINC, "8480-6", "Systolic Blood Pressure"),
                    "valueQuantity": quantity(128, "mm[Hg]"),
                },
                {
                    "code": coded(LOINC, "8462-4", "Diastolic Blood Pressure"),
                    "valueQuantity": quantity(84, "mm[Hg]"),
                },
            ],
        ),
        observation(
            13,
            VISIT,
            "72166-2",
            "Tobacco smoking status",
            category="survey",
            valueCodeableConcept=coded(SNOMED, "266919005", "Never smoked tobacco (finding)"),
        ),
        condition(20, VISIT, "Essential hypertension (disorder)"),
        condition(
            21,
            "2024-01-10T08:00:00-05:00",
            "Acute viral pharyngitis (disorder)",
            status="resolved",
            abated="2024-01-20T08:00:00-05:00",
        ),
        {
            "resourceType": "Medication",
            "id": uid(30),
            "code": coded(RXNORM, "314076", "lisinopril 10 MG Oral Tablet"),
            "status": "active",
        },
        {
            "resourceType": "MedicationRequest",
            "id": uid(31),
            "status": "active",
            "intent": "order",
            "medicationReference": {"reference": f"urn:uuid:{uid(30)}"},
            "subject": SUBJECT,
            "authoredOn": VISIT,
            "requester": CLINICIAN,
            "reasonReference": [{"reference": f"urn:uuid:{uid(20)}"}],
            "dosageInstruction": [
                {
                    "sequence": 1,
                    "text": "Take 1 tablet by mouth once a day",
                    "timing": {"repeat": {"frequency": 1, "period": 1.0, "periodUnit": "d"}},
                    "asNeededBoolean": False,
                }
            ],
        },
        {
            "resourceType": "DiagnosticReport",
            "id": uid(40),
            "status": "final",
            "category": [coded("http://terminology.hl7.org/CodeSystem/v2-0074", "LAB", "LAB")],
            "code": coded(LOINC, "4548-4", "Hemoglobin A1c panel"),
            "subject": SUBJECT,
            "effectiveDateTime": VISIT,
            "issued": VISIT,
            "performer": [CLINICIAN],
            "result": [{"reference": f"urn:uuid:{uid(11)}"}],
        },
        {
            "resourceType": "AllergyIntolerance",
            "id": uid(50),
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "verificationStatus": {"coding": [{"code": "confirmed"}]},
            "type": "allergy",
            "category": ["food"],
            "criticality": "low",
            "code": coded(SNOMED, "256349002", "Peanut (substance)"),
            "patient": SUBJECT,
            "recordedDate": VISIT,
            "reaction": [
                {
                    "manifestation": [coded(SNOMED, "247472004", "Wheal (finding)")],
                    "severity": "mild",
                }
            ],
        },
        {
            "resourceType": "Immunization",
            "id": uid(60),
            "status": "completed",
            "vaccineCode": coded(CVX, "140", "Influenza, seasonal, injectable, preservative free"),
            "patient": SUBJECT,
            "occurrenceDateTime": VISIT,
            "primarySource": True,
            "location": CLINIC,
        },
        {
            "resourceType": "Procedure",
            "id": uid(70),
            "status": "completed",
            "code": coded(SNOMED, "430193006", "Medication reconciliation (procedure)"),
            "subject": SUBJECT,
            "performedPeriod": {"start": VISIT, "end": "2024-03-05T09:45:00-05:00"},
            "location": CLINIC,
        },
        {
            "resourceType": "DocumentReference",
            "id": uid(80),
            "status": "current",
            "type": coded(LOINC, "34117-2", "History and physical note"),
            "subject": SUBJECT,
            "date": "2024-03-05T09:30:00.000-05:00",
            "author": [CLINICIAN],
            "content": [
                {
                    "attachment": {
                        "contentType": "text/plain; charset=utf-8",
                        "data": "UGF0aWVudCBBbGV4IEV4YW1wbGU=",
                    }
                }
            ],
            "context": {"period": {"start": VISIT, "end": "2024-03-05T10:15:00-05:00"}},
        },
    )


# ── Reading ─────────────────────────────────────────────────────────────────


def test_a_synthea_style_bundle_becomes_one_plain_record_per_resource(tmp_path):
    put(tmp_path / "portal" / "fhir" / "Alex_Example.json", synthea_bundle())
    streams, counts = healthrecords.read_records(tmp_path / "portal")
    records = {r["id"]: r for stream in streams.values() for r in stream}

    assert counts == {"skipped": 0, "other": 2}  # the Patient and the Medication
    assert {s: len(rs) for s, rs in streams.items()} == {
        "encounters": 1,
        "observations": 3,
        "conditions": 2,
        "medications": 1,
        "reports": 1,
        "allergies": 1,
        "immunizations": 1,
        "procedures": 1,
        "documents": 1,
    }
    assert records[f"Observation/{uid(11)}"] == {
        "id": f"Observation/{uid(11)}",
        "ts": VISIT_UTC,
        "type": "Observation",
        "from_me": False,
        "name": "Hemoglobin A1c/Hemoglobin.total in Blood",
        "category": "laboratory",
        "status": "final",
        "value": 6.1,
        "unit": "%",
        "low": 4.0,
        "high": 5.6,
        "range": "4.0 to 5.6 %",
        "flag": "high",
        "components": None,
        "text": "Hemoglobin A1c/Hemoglobin.total in Blood: 6.1 % (reference 4.0 to 5.6 %), high",
    }
    pressure = records[f"Observation/{uid(12)}"]
    assert pressure["value"] is None and pressure["components"] == [
        {"name": "Systolic Blood Pressure", "value": 128, "unit": "mm[Hg]"},
        {"name": "Diastolic Blood Pressure", "value": 84, "unit": "mm[Hg]"},
    ]
    assert pressure["text"] == (
        "Blood pressure panel with all children optional: Systolic Blood Pressure 128 mm[Hg]; "
        "Diastolic Blood Pressure 84 mm[Hg]"
    )
    assert healthrecords.label(pressure) == "vital sign"
    smoking = records[f"Observation/{uid(13)}"]
    assert smoking["text"] == "Tobacco smoking status: Never smoked tobacco (finding)"

    resolved = records[f"Condition/{uid(21)}"]
    assert resolved["status"] == "resolved" and resolved["abated"] == "2024-01-20"
    assert resolved["text"] == "Acute viral pharyngitis (disorder) (resolved). Ended 2024-01-20"
    # The medication and the reason are named through the references Synthea uses.
    assert records[f"MedicationRequest/{uid(31)}"] == {
        "id": f"MedicationRequest/{uid(31)}",
        "ts": VISIT_UTC,
        "type": "MedicationRequest",
        "from_me": False,
        "name": "lisinopril 10 MG Oral Tablet",
        "status": "active",
        "intent": "order",
        "dosage": "Take 1 tablet by mouth once a day",
        "reason": "Essential hypertension (disorder)",
        "text": "lisinopril 10 MG Oral Tablet (active). Dosage: Take 1 tablet by mouth once a "
        "day. Reason: Essential hypertension (disorder)",
    }
    visit = records[f"Encounter/{uid(10)}"]
    assert visit["class"] == "ambulatory" and visit["location"] == "EXAMPLE FAMILY CLINIC"
    assert visit["end"] == "2024-03-05T15:15:00Z"
    report = records[f"DiagnosticReport/{uid(40)}"]
    assert report["results"] == ["Hemoglobin A1c/Hemoglobin.total in Blood"]
    allergy = records[f"AllergyIntolerance/{uid(50)}"]
    assert (
        allergy["text"]
        == "Peanut (substance) (active, low criticality, food). Reactions: Wheal (finding)"
    )
    assert records[f"Immunization/{uid(60)}"]["text"] == (
        "Influenza, seasonal, injectable, preservative free (completed)"
    )
    assert records[f"Procedure/{uid(70)}"]["location"] == "EXAMPLE FAMILY CLINIC"
    # A document is its title and date only.
    assert records[f"DocumentReference/{uid(80)}"] == {
        "id": f"DocumentReference/{uid(80)}",
        "ts": VISIT_UTC,
        "type": "DocumentReference",
        "from_me": False,
        "title": "History and physical note",
        "status": "current",
        "text": "History and physical note",
    }
    # No one is named: not the patient, not the clinician, and no document's content is kept.
    everything = json.dumps(records)
    for name in ("Alex", "Jordan", "UGF0aWVudCBBbGV4IEV4YW1wbGU"):
        assert name not in everything


def test_apple_healths_export_zip_is_read_in_place_and_reruns_change_nothing(tmp_path):
    # Apple's clinical-records hold one resource per file, R4 or (older connections) DSTU2.
    lab = observation(
        90,
        "2024-06-01T08:15:00-04:00",
        "2345-7",
        "Glucose [Mass/volume] in Serum or Plasma",
        valueQuantity=quantity(92, "mg/dL"),
        referenceRange=[{"text": "70 - 99 mg/dL"}],
        interpretation=[{"coding": [{"code": "N"}]}],
    )
    flu = {
        "resourceType": "Immunization",
        "id": "dstu2-flu",
        "status": "completed",
        "date": "2023-10-02",
        "vaccineCode": {"coding": [{"system": CVX, "code": "140"}], "text": "Influenza vaccine"},
    }
    order = {
        "resourceType": "MedicationOrder",
        "id": "dstu2-order",
        "status": "active",
        "dateWritten": "2023-10",
        "medicationCodeableConcept": {"text": "cetirizine 10 mg tablet"},
        "dosageInstruction": [{"text": "1 tablet daily as needed"}],
    }
    export = tmp_path / "export.zip"
    with zipfile.ZipFile(export, "w") as z:
        z.writestr("apple_health_export/export.xml", "<HealthData/>")
        z.writestr("apple_health_export/workout-routes/route_2024-06-01.gpx", "<gpx/>")
        for resource in (lab, flu, order):
            name = f"{resource['resourceType']}-{resource['id'].upper()}.json"
            z.writestr(f"apple_health_export/clinical-records/{name}", json.dumps(resource))
        z.writestr("__MACOSX/apple_health_export/clinical-records/._Observation.json", "\x00\x05")

    vault = tmp_path / "vault"
    stats = healthrecords.ingest(vault, export)
    assert stats == {
        "read": 3,
        "added": 3,
        "updated": 0,
        "months_written": 3,
        "skipped": 0,
        "other": 0,
    }
    root = vault / "raw" / "healthrecords"
    [glucose] = [json.loads(line) for line in (root / "observations" / "2024-06.jsonl").open()]
    assert glucose["ts"] == "2024-06-01T12:15:00Z"
    assert glucose["range"] == "70 - 99 mg/dL" and glucose["flag"] == "normal"
    [shot] = [json.loads(line) for line in (root / "immunizations" / "2023-10.jsonl").open()]
    assert shot["ts"] == "2023-10-02T12:00:00Z"  # a date alone is noon UTC: the same day anywhere
    [pills] = [json.loads(line) for line in (root / "medications" / "2023-10.jsonl").open()]
    assert pills["ts"] == "2023-10-01T12:00:00Z" and pills["dosage"] == "1 tablet daily as needed"

    again = healthrecords.ingest(vault, export)
    assert again["added"] == again["updated"] == again["months_written"] == 0


def test_ndjson_downloads_and_what_cant_be_read_are_counted(tmp_path):
    folder = tmp_path / "bulk"
    hemoglobin = observation(
        91, "2025-02-03T10:00:00Z", "718-7", "Hemoglobin", valueQuantity=quantity(13.9, "g/dL")
    )
    lines = [
        json.dumps(hemoglobin),
        "{not json",
        "",
        json.dumps(
            observation(
                92,
                "2025-02-03T10:00:00Z",
                "5195-3",
                "Hepatitis B surface Ag",
                valueQuantity={"value": 0.5, "comparator": "<", "unit": "IU/mL"},
            )
        ),
    ]
    put(folder / "Observation.ndjson", "\n".join(lines) + "\n")
    put(folder / "Patient.ndjson", json.dumps(patient()) + "\n")
    undated = {"resourceType": "Condition", "id": "c1", "code": {"text": "Asthma"}}
    put(folder / "Condition.ndjson", json.dumps(undated) + "\n")
    put(folder / "broken.json", '{"resourceType": "Bundle", "entry": [')
    put(folder / "notes.txt", "not a FHIR file")

    vault = tmp_path / "vault"
    stats = healthrecords.ingest(vault, folder)
    # One bad line, one condition with no date, one broken file; the Patient isn't kept.
    assert stats["read"] == 2 and stats["skipped"] == 3 and stats["other"] == 1
    month = vault / "raw" / "healthrecords" / "observations" / "2025-02.jsonl"
    texts = [json.loads(line)["text"] for line in month.open()]
    assert texts == ["Hemoglobin: 13.9 g/dL", "Hepatitis B surface Ag: <0.5 IU/mL"]

    with pytest.raises(FileNotFoundError):
        healthrecords.ingest(vault, tmp_path / "missing")


def test_the_cli_reads_one_bundle_file(tmp_path):
    bundle_file = put(tmp_path / "Alex.json", synthea_bundle())
    parser = argparse.ArgumentParser()
    healthrecords.add_arguments(parser)
    stats = healthrecords.run(tmp_path / "vault", parser.parse_args(["--export", str(bundle_file)]))
    assert stats["read"] == 12 and stats["other"] == 2
    assert healthrecords.__doc__.splitlines()[0].startswith("Medical records in FHIR")


# ── The import route ────────────────────────────────────────────────────────


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_apple_health_and_portal_downloads_are_routed_and_other_exports_are_not(tmp_path):
    vault = tmp_path / "vault"
    inbox = vault / "inbox"
    inbox.mkdir(parents=True)
    lab = json.dumps(
        observation(93, VISIT, "2345-7", "Glucose", valueQuantity=quantity(92, "mg/dL"))
    )
    make_zip(
        inbox / "export.zip",
        {
            "apple_health_export/export.xml": "<HealthData/>",
            "apple_health_export/clinical-records/Observation-A1.json": lab,
        },
    )
    put(inbox / "portal-download" / "fhir" / "Alex_Example.json", synthea_bundle())
    put(inbox / "portal-download" / "fhir" / "Patient.ndjson", json.dumps(patient()) + "\n")
    # Another export's JSON is never opened, even with a FHIR file in it...
    make_zip(inbox / "twitter-1.zip", {"data/manifest.js": "x", "data/fhir.json": lab})
    # ...and a JSON file that only mentions FHIR in its text isn't FHIR.
    make_zip(inbox / "mystery.zip", {"data.json": json.dumps({"note": lab})})

    calls = []
    stats = importer.run(vault, ingest=lambda v, source, argv: calls.append((source, argv)))
    exports = vault / "exports"
    assert sorted(calls) == [
        (
            "healthrecords",
            ["--export", str(exports / "export" / "apple_health_export" / "clinical-records")],
        ),
        ("healthrecords", ["--export", str(exports / "portal-download" / "fhir")]),
        ("twitter", ["--export", str(exports / "twitter-1")]),
    ]
    assert stats == {"healthrecords_imported": 2, "twitter_imported": 1, "unrecognized": 1}
    assert (vault / "downloads" / "healthrecords" / "export.zip").exists()
    assert [p.name for p in inbox.iterdir()] == ["mystery.zip"]


# ── Care ────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def portal_records():
    """A patient portal download as of NOW: recent results, a visit, an old active condition,
    and history care leaves out."""
    return bundle(
        patient(),
        observation(
            101,
            ago(days=10),
            "777-3",
            "Platelets [#/volume] in Blood by Automated count",
            valueQuantity=quantity(250000, "/uL"),
            referenceRange=[{"low": quantity(150000, "/uL"), "high": quantity(450000, "/uL")}],
        ),
        observation(
            102,
            ago(days=10),
            "29463-7",
            "Body Weight",
            category="vital-signs",
            valueQuantity=quantity(77.80123456, "kg"),
        ),
        {
            "resourceType": "DiagnosticReport",
            "id": uid(103),
            "status": "final",
            "code": coded(LOINC, "58410-2", "CBC panel - Blood by Automated count"),
            "effectiveDateTime": ago(days=10),
            "result": [{"reference": f"urn:uuid:{uid(101)}"}],
            "conclusion": "Specimen 12345678 received; questions to 555-123-4567. "
            "Platelet count within the reference range.",
        },
        condition(104, ago(days=800), "Essential hypertension (disorder)"),
        condition(105, ago(days=400), "Sprain of ankle", status="resolved", abated=ago(days=390)),
        observation(106, ago(days=200), "718-7", "Hemoglobin", valueQuantity=quantity(14, "g/dL")),
        observation(
            107,
            ago(days=5),
            "718-7",
            "Hemoglobin",
            status="entered-in-error",
            valueQuantity=quantity(1, "g/dL"),
        ),
        encounter(108, ago(days=10), ago(days=10, hours=-3), kind="EMER", name="Emergency visit"),
        {
            "resourceType": "MedicationRequest",
            "id": uid(109),
            "status": "stopped",
            "intent": "order",
            "medicationCodeableConcept": coded(RXNORM, "1", "amoxicillin 500 MG Oral Capsule"),
            "authoredOn": ago(days=500),
        },
    )


@pytest.fixture
def model(monkeypatch):
    prompts = []

    def ask(prompt, *, system=None, schema=None, effort="medium", **_):
        prompts.append(prompt)
        return {"summary": "", "timeline": [], "open_items": [], "scripts": [], "visit_brief": ""}

    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setattr(llm, "ask", ask)
    monkeypatch.setenv("PROXENOS_NAME", "Sam Rivera")
    return prompts


def portal_vault(tmp_path):
    vault = tmp_path / "vault"
    healthrecords.ingest(vault, put(tmp_path / "portal" / "Alex.json", portal_records()))
    return vault


def test_care_keeps_every_recent_medical_record_without_scoring_and_active_ones_however_old(
    tmp_path,
):
    vault = portal_vault(tmp_path)
    found = care.gather(vault, NOW - timedelta(days=120), NOW, NOW + timedelta(days=60))
    by_id = {r["id"]: r for r in found}

    assert set(by_id) == {
        f"healthrecords/observations/Observation/{uid(101)}",
        f"healthrecords/observations/Observation/{uid(102)}",
        f"healthrecords/reports/DiagnosticReport/{uid(103)}",
        f"healthrecords/conditions/Condition/{uid(104)}",  # 800 days old, still active
        f"healthrecords/encounters/Encounter/{uid(108)}",
    }
    # Left behind: a resolved condition, a stopped prescription and a result from before the
    # window, and a result entered in error.
    platelets = by_id[f"healthrecords/observations/Observation/{uid(101)}"]
    assert care.score(platelets["text"])[0] < care.THRESHOLD  # its words alone wouldn't pass
    assert all(r["score"] == care.MEDICAL_SCORE and r["source"] == "healthrecords" for r in found)
    assert platelets["where"] == "medical record, lab result"
    hypertension = by_id[f"healthrecords/conditions/Condition/{uid(104)}"]
    assert hypertension["current"] and not platelets["current"]

    # Still active, it ranks as if from today: under a cap that fits one record, it stays.
    _, refs, cut = care.render(found, NOW, limit=len(care._entry("r00000", hypertension)) + 2)
    assert cut and [ref["id"] for ref in refs.values()] == [hypertension["id"]]


def test_care_sends_results_whole_and_blanks_identifiers_in_the_words(tmp_path, model):
    vault = portal_vault(tmp_path)
    stats = care.care(vault, now=NOW)

    [prompt] = model
    assert stats["records"] == 5
    assert (
        "Platelets [#/volume] in Blood by Automated count: 250000 /uL "
        "(reference 150000 to 450000 /uL)" in prompt
    )
    assert "Body Weight: 77.80123456 kg" in prompt
    assert "Essential hypertension (disorder) (active)" in prompt
    assert "Emergency visit (emergency). At EXAMPLE FAMILY CLINIC" in prompt
    assert "Results: Platelets [#/volume] in Blood by Automated count" in prompt
    assert "Specimen [number] received; questions to [phone]." in prompt
    left_out = ("Sprain", "amoxicillin", "Hemoglobin")  # resolved, stopped, old, in error
    for secret in ("12345678", "555-123-4567", "Alex", "Jordan", *left_out):
        assert secret not in prompt
    saved = json.loads((vault / "clones" / "care" / "care.json").read_text())
    assert saved["records"] == {"healthrecords": 5}


def test_observers_leave_medical_records_alone(tmp_path):
    vault = portal_vault(tmp_path)
    month = ago(days=10)[:7]
    assert ("healthrecords", month) in {(name, m) for name, m, _ in observe.pending(vault)}
    # Clinicians wrote them, not the user, so an observer has nothing of the user's to read.
    assert observe.render(vault, "healthrecords", month) == ""
