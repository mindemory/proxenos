"""Care clone on a synthetic vault with the model faked out. No network, no real data: every
person, clinic, number and message here is made up."""

import json
import os
import re
import stat
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import llm, voice
from proxenos.clones import care, work

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
GENERATED = "2026-10-20T15:00:00Z"


def ago(**delta):
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ahead(**delta):
    return (NOW + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_stream(directory, records):
    by_month = defaultdict(list)
    for r in records:
        by_month[r["ts"][:7]].append(r)
    directory.mkdir(parents=True, exist_ok=True)
    for month, rs in by_month.items():
        rs.sort(key=lambda r: (r["ts"], r["id"]))
        (directory / f"{month}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs))


def em(key, ts, subject, body, *, sender="news@example.org", name="Example", me=False, **extra):
    return {
        "id": key,
        "ts": ts,
        "account": "personal",
        "from_address": "sam@example.com" if me else sender,
        "from_name": None if me else name,
        "from_me": me,
        "to": extra.pop("to", ["sam@example.com"]),
        "cc": None,
        "subject": subject,
        "in_reply_to": None,
        "gmail_labels": extra.pop("labels", None),
        "gmail_thread": None,
        "attachments": None,
        "body": body,
        "body_new": body,
    }


def wa(key, ts, chat, text, *, me=False, sender=None, group=False, phone="15550001111"):
    chat_id = f"{chat}@g.us" if group else f"{phone}@s.whatsapp.net"
    return {
        "id": f"{chat_id}/{key}",
        "ts": ts,
        "chat_id": chat_id,
        "chat_name": chat,
        "chat_type": "group" if group else "direct",
        "from_me": me,
        "sender_id": None if me else f"{phone}@s.whatsapp.net",
        "sender_name": None if me else sender or chat,
        "kind": "text",
        "wa_type": 0,
        "text": text,
        "caption": None,
    }


def sl(key, ts, channel, text, *, kind="dm", me=False, user="Dana"):
    return {
        "id": f"{channel}/{key}",
        "ts": ts,
        "slack_ts": "1",
        "channel_id": channel,
        "channel_name": user if kind == "dm" else "general",
        "channel_type": kind,
        "user_id": "U0ME" if me else f"U{user.upper()}",
        "user_name": "Sam" if me else user,
        "from_me": me,
        "text": text,
        "thread_ts": None,
        "is_reply": False,
        "subtype": None,
        "files": None,
    }


def event(key, ts, summary, *, location=None, description=None):
    return {
        "id": key,
        "ts": ts,
        "start": ts,
        "end": ts,
        "all_day": False,
        "summary": summary,
        "location": location,
        "description": description,
        "status": "CONFIRMED",
    }


RESEARCH_PAPER = (
    "Abstract. We recorded skin conductance from participants at the Department of Radiology and "
    "the Department of Dermatology, University Hospital, while they performed a reading task. "
    "Methods: the MRI scanner protocol, voxel analysis and regression models are described in "
    "the supplementary figures. Patients with skin disorders were excluded. et al. 2025."
)


SELF = {"me": True, "phone": "15559990000"}  # the note-to-self chat


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    raw = vault / "raw"
    write_stream(
        raw / "email" / "personal",
        [
            em(
                "mychart@example",
                ago(days=12),
                "New message from your care team",
                "You have a new message in MyChart about your visit. Your MRI results are "
                "available. Call 555-123-4567 with questions. Member ID W123456789. "
                "Log in at https://mychart.example.org/visit?token=abc123",
                sender="noreply@mychart.example.org",
                name="Example Health MyChart",
            ),
            em(
                "eob@example",
                ago(days=6),
                "Your Explanation of Benefits is ready",
                "An explanation of benefits for your emergency room visit is ready. Your "
                "deductible applies.",
                sender="claims@insurer.example.com",
                name="Insurer",
                labels=["CATEGORY_UPDATES"],
            ),
            em(
                "records@example",
                ago(days=4),
                "Records request",
                "Hello, I'd like to request my medical records from my urgent care visit. "
                "Please fax them to my new primary care office.",
                me=True,
                to=["records@clinic.example.org"],
            ),
            em(
                "promo@example",
                ago(days=3),
                "Save 30% at the pharmacy",
                "Deals on vitamins and your prescription refills this week.",
                sender="deals@pharmacy.example.com",
                name="Pharmacy Deals",
                labels=["CATEGORY_PROMOTIONS"],
            ),
            em(
                "spam@example",
                ago(days=3),
                "Cheap prescriptions, urgent care, MRI",
                "Lowest copay ever.",
                labels=["SPAM"],
            ),
            em(
                "pilot@example",
                ago(days=5),
                "fMRI pilot this week",
                "We'll scan two participants in the MRI on Thursday for the pilot. The lab "
                "meeting moves to Friday so we can discuss the analysis.",
                sender="pi@uni.example.edu",
                name="Prof Example",
            ),
            em(
                "card@example",
                ago(days=2),
                "Your statement is ready",
                "Your credit card statement is ready. Payment due on the 15th.",
                sender="alerts@bank.example.com",
                name="Bank",
            ),
            em(
                "old@example",
                ago(days=200),
                "Urgent care visit summary",
                "Your after visit summary from urgent care.",
                sender="noreply@clinic.example.org",
                name="Clinic",
            ),
        ],
    )
    write_stream(
        raw / "calendar" / "personal",
        [
            event("derm", ahead(days=9), "Dermatologist appointment", location="Example Clinic"),
            event("pcp", ago(days=8), "PCP visit"),
            event("labmeeting", ago(days=2), "Lab meeting", description="Discuss the analysis"),
        ],
    )
    write_stream(
        raw / "whatsapp" / "messages",
        [
            wa(
                "n1",
                ago(days=20),
                "Sam Rivera",
                "the rash is back this morning, itchy all over",
                **SELF,
            ),
            wa("n2", ago(days=15), "Sam Rivera", "groceries: rice, lentils", **SELF),
            wa("n3", ago(days=10), "Sam Rivera", "ER visit tonight, they did a CT scan", **SELF),
            wa("a1", ago(days=11, minutes=5), "Asha", "How did the scan go? Any test results yet?"),
            wa("a2", ago(days=11), "Asha", "Fine, they said a week", me=True),
            wa("a3", ago(days=11, minutes=-5), "Asha", "ok keep me posted"),
            wa("a4", ago(days=9), "Asha", "Dinner on Friday?"),
            wa("g1", ago(days=7), "Climbing", "Who books the wall?", sender="Cy", group=True),
        ],
    )
    write_stream(
        raw / "slack" / "lab" / "messages",
        [
            sl("1", ago(days=5), "D1", "Out sick today, have a dermatologist appointment", me=True),
            sl("2", ago(days=5, minutes=-3), "D1", "Feel better soon!"),
            sl("3", ago(days=4), "D1", "Can you review my poster?"),
            sl("4", ago(days=3), "C1", "Urgent care is next to the lab", kind="channel"),
        ],
    )
    write_stream(
        raw / "notes" / "pages",
        [
            {
                "id": "md/paper-notes",
                "ts": ago(days=14),
                "kind": "md",
                "from_me": True,
                "title": "Reading notes",
                "collection": None,
                "text": RESEARCH_PAPER,
            },
        ],
    )
    write_stream(
        raw / "keep" / "notes",
        [
            {
                "id": "questions",
                "ts": ago(days=3),
                "from_me": True,
                "title": "Questions for the dermatologist",
                "text": "Why the rash? Do I need a referral for allergy testing?",
                "labels": [],
                "trashed": False,
            },
            {
                "id": "trash",
                "ts": ago(days=3),
                "from_me": True,
                "title": "Old rash note",
                "text": "rash",
                "labels": [],
                "trashed": True,
            },
        ],
    )
    write_stream(
        raw / "gtasks" / "tasks",
        [
            {
                "id": "t1",
                "ts": ago(days=2),
                "from_me": True,
                "list": "My Tasks",
                "title": "Call insurance about the ER claim",
                "notes": None,
                "status": "needsAction",
                "due": None,
                "completed": None,
            }
        ],
    )
    write_stream(
        raw / "drive" / "docs",
        [
            {
                "id": "papers/dermatitis.pdf",
                "ts": ago(days=30),
                "path": "papers/dermatitis.pdf",
                "title": "dermatitis",
                "ext": "pdf",
                "size": 1,
                "text": RESEARCH_PAPER,
                "words": 60,
            },
            {
                "id": "health/log.docx",
                "ts": ago(days=1),
                "path": "health/log.docx",
                "title": "Symptom log",
                "ext": "docx",
                "size": 1,
                "text": "Sep 2: rash on both arms, fatigue all day. Sep 5: urgent care.",
                "words": 12,
            },
        ],
    )
    (vault / "self").mkdir(parents=True)
    (vault / "self" / "identity.md").write_text("A researcher.\n")
    (vault / "self" / "voice.md").write_text("Short, warm, direct.\n")
    return vault


class FakeModel:
    """Answers with `make(prompt)`, by default an empty status, and logs every call."""

    def __init__(self):
        self.calls = []
        self.make = lambda prompt: answer()

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", **_):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        return self.make(prompt)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setenv("PROXENOS_NAME", "Sam Rivera")


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def answer(*, summary="Waiting on results.", timeline=(), items=(), scripts=(), brief="## Brief"):
    return {
        "summary": summary,
        "timeline": list(timeline),
        "open_items": list(items),
        "scripts": list(scripts),
        "visit_brief": brief,
    }


def entry(title, *, id="new-1", kind="records", waiting_on="me", status="open", **fields):
    return {
        "id": id,
        "title": title,
        "kind": kind,
        "waiting_on": waiting_on,
        "next_step": fields.get("next_step", "Call the office."),
        "due": fields.get("due", ""),
        "status": status,
        "evidence": list(fields.get("evidence", ())),
    }


def ref(prompt, text):
    """The [r..] ref of the record whose entry contains `text`."""
    for block in re.split(r"\n\n(?=\[r\d+\])", prompt):
        if text in block:
            return re.match(r"\[(r\d+)\]", block.strip())[1]
    raise AssertionError(f"{text!r} not in the prompt")


def saved(vault):
    return json.loads((vault / "clones" / "care" / "care.json").read_text())


def feedback(vault, *lines):
    path = vault / "clones" / "care" / "feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


# ── The filter ──────────────────────────────────────────────────────────────


def test_the_filter_keeps_health_records_from_every_source_and_nothing_else(tmp_path):
    vault = make_vault(tmp_path)
    found = care.gather(vault, NOW - timedelta(days=120), NOW, NOW + timedelta(days=60))
    ids = {r["id"] for r in found}

    assert ids == {
        "email/personal/mychart@example",
        "email/personal/eob@example",
        "email/personal/records@example",
        "calendar/personal/derm",  # nine days ahead
        "calendar/personal/pcp",
        "whatsapp/messages/15559990000@s.whatsapp.net/n1",
        "whatsapp/messages/15559990000@s.whatsapp.net/n3",
        "whatsapp/messages/15550001111@s.whatsapp.net/a1",
        "whatsapp/messages/15550001111@s.whatsapp.net/a2",  # the answer comes along
        "whatsapp/messages/15550001111@s.whatsapp.net/a3",  # and what was said to it
        "slack/lab/messages/D1/1",
        "slack/lab/messages/D1/2",
        "keep/notes/questions",
        "gtasks/tasks/t1",
        "drive/docs/health/log.docx",
    }
    # Left behind: a pharmacy ad, spam, a research email about an MRI pilot, a credit card
    # statement, mail from before the window, a lab meeting, a grocery list, dinner plans, a
    # group chat, a Slack channel, research notes and a paper full of hospital departments.
    near = {r["id"].rsplit("/", 1)[1]: r.get("near") for r in found if r["source"] == "whatsapp"}
    asked = "whatsapp/messages/15550001111@s.whatsapp.net/a1"
    assert near == {"n1": None, "n3": None, "a1": None, "a2": asked, "a3": asked}


def test_the_note_to_self_chat_is_the_users_own_log(tmp_path):
    vault = make_vault(tmp_path)
    found = care.gather(vault, NOW - timedelta(days=120), NOW, NOW + timedelta(days=60))
    log = [r for r in found if r["where"] == "WhatsApp, note to self"]
    assert {r["text"] for r in log} == {
        "the rash is back this morning, itchy all over",
        "ER visit tonight, they did a CT scan",
    }
    assert all(r["own"] and r["sender"] == "me" for r in log)


def test_research_words_turn_ambiguous_terms_off_but_not_clear_ones():
    paper, _ = care.score(RESEARCH_PAPER)
    assert paper < care.THRESHOLD
    busy, terms = care.score("Missed lab meeting and the analysis review: I was at urgent care")
    assert busy >= care.THRESHOLD and "urgent care" in terms
    # Symptoms count in the user's own words, but someone else's mention needs more.
    assert care.score("the rash is back today", own=True)[0] >= care.OWN_THRESHOLD
    assert care.score("A rash is a common side effect in this trial cohort paper")[0] < 3


def test_what_reaches_the_model_has_no_names_numbers_addresses_or_links(tmp_path, model):
    vault = make_vault(tmp_path)
    care.care(vault, now=NOW)

    [call] = model.calls
    prompt = call["prompt"]
    secrets = ("555-123-4567", "W123456789", "abc123", "Asha", "15550001111", "15559990000")
    for secret in (*secrets, "Dana", "Climbing"):
        assert secret not in prompt
    assert "records@clinic" not in prompt and "sam@example.com" not in prompt
    assert "[phone]" in prompt and "[number]" in prompt
    assert "[link: mychart.example.org]" in prompt
    assert "WhatsApp, chat with contact 1" in prompt
    assert "from Example Health MyChart (mychart.example.org)" in prompt
    assert "from me (to clinic.example.org)" in prompt
    # The research email, the ad and the grocery list never left.
    for left_out in ("fMRI pilot", "Save 30%", "groceries", "Dinner on Friday"):
        assert left_out not in prompt


def test_the_cap_keeps_the_newest_and_strongest_and_says_it_cut():
    def record(key, days, points, text, **extra):
        return {
            "id": key,
            "source": "whatsapp",
            "ts": ago(days=days),
            "where": "WhatsApp, note to self",
            "sender": "me",
            "title": "",
            "text": text,
            "own": True,
            "score": points,
            "terms": [],
            **extra,
        }

    records = [
        record("old-strong", 100, 12, "x" * 200),
        record("new-weak", 2, 2, "y" * 200),
        record("new-strong", 1, 9, "z" * 200),
        record("context", 1, 0, "w" * 200, near="new-strong"),
        record("mid", 40, 6, "v" * 200),
    ]
    one = len(care._entry("r00000", records[0])) + 2
    text, refs, cut = care.render(records, NOW, limit=3 * one)
    kept = [ref["id"] for ref in refs.values()]
    assert cut
    assert set(kept) == {"new-strong", "context", "mid"}  # mid's score outweighs its month
    assert kept == sorted(kept, key=lambda k: next(r["ts"] for r in records if r["id"] == k))
    assert len(text) <= 3 * one

    text, refs, cut = care.render(records, NOW)
    assert not cut and len(refs) == 5


def test_long_texts_are_cut_to_the_passages_around_their_terms():
    text = "filler " * 2000 + "my copay was wrong " + "filler " * 2000
    cut = care._excerpt(text, 1000)
    assert len(cut) <= 1010
    assert "copay" in cut and cut.startswith("… ") and cut.endswith(" …")
    assert care._excerpt("short note", 1000) == "short note"


# ── The answer ──────────────────────────────────────────────────────────────


def full_answer(prompt):
    mychart = ref(prompt, "MyChart about your visit")
    log = ref(prompt, "the rash is back this morning")
    er = ref(prompt, "ER visit tonight")
    records = ref(prompt, "request my medical records")
    return answer(
        summary="Sam went to the ER on Sep 12. Call 415-555-0199 for the scan. contact 1 helped.",
        timeline=[
            {
                "date": "2026-09-30",
                "kind": "symptom",
                "title": "Rash in the morning",
                "detail": "Logged the rash.",
                "with": "",
                "evidence": [f"[{log}]"],
            },
            {
                "date": "",
                "kind": "visit",
                "title": "Emergency department visit",
                "detail": "CT scan done.",
                "with": "emergency department",
                "evidence": [er],
            },
            {
                "date": "2026-10-08",
                "kind": "diagnosis",  # not a kind: dropped
                "title": "Bad kind",
                "detail": "",
                "with": "",
                "evidence": [],
            },
        ],
        items=[
            entry(
                "Get the MRI report sent to primary care",
                id="new-1",
                waiting_on="provider",
                due="2026-10-25",
                evidence=[mychart, "r9999"],
            ),
            entry("Follow up on the records request", id="new-2", due="soon", evidence=[records]),
            entry("", id="new-3"),  # no title: dropped
        ],
        scripts=[
            {
                "item_id": "new-1",
                "kind": "portal_message",
                "title": "Ask for the MRI report",
                "body": "Hello, please send my MRI report to my primary care office. "
                "My member ID is W987654321.",
            },
            {"item_id": "new-9", "kind": "call", "title": "Unknown item", "body": "Hi."},
            {"item_id": "new-2", "kind": "call", "title": "Call records", "body": "Hello."},
        ],
        brief="## Presenting problem\nA rash since late August. Fax 212-555-0100.",
    )


def test_one_high_effort_call_with_the_schema_and_the_self_model(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = full_answer
    stats = care.care(vault, now=NOW)

    [call] = model.calls
    assert call["effort"] == "high"
    assert call["schema"] is care._SCHEMA
    assert "<identity>\nA researcher.\n</identity>" in call["system"]
    assert "<voice>\nShort, warm, direct.\n</voice>" in call["system"]
    assert "Never diagnose" in call["system"] and "Sam Rivera" in call["system"]
    assert (
        "The scripts go out as Sam Rivera's own words. " + voice.rules("Sam Rivera")
        in call["system"]
    )
    assert stats == {
        "records": 15,
        "timeline_events": 2,
        "open": 2,
        "waiting": 0,
        "done": 0,
        "new": 2,
        "scripts": 2,
    }


def test_the_answer_is_checked_scrubbed_and_given_stable_ids(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = full_answer
    care.care(vault, now=NOW)

    doc = saved(vault)
    assert doc["generated"] == GENERATED
    assert "415-555-0199" not in doc["summary"] and "[phone]" in doc["summary"]
    assert "contact 1" not in doc["summary"] and "a contact helped" in doc["summary"]
    assert "212-555-0100" not in doc["visit_brief"]
    assert doc["visit_brief"].startswith("## Presenting problem")

    first, second = doc["timeline"]
    assert first["date"] == "2026-09-30" and first["kind"] == "symptom"
    assert first["id"] == care.event_id("2026-09-30", "symptom", "Rash in the morning")
    assert first["evidence"] == ["whatsapp/messages/15559990000@s.whatsapp.net/n1"]
    assert second["date"] == "2026-10-10"  # no date given: the day of its evidence

    items = {i["title"]: i for i in doc["open_items"]}
    mri = items["Get the MRI report sent to primary care"]
    assert mri["evidence"] == ["email/personal/mychart@example"]  # r9999 isn't a record
    assert mri["id"] == care.item_id(mri["title"], "records", ago(days=12))
    assert mri["due"] == "2026-10-25" and mri["waiting_on"] == "provider"
    assert items["Follow up on the records request"]["due"] is None

    by_kind = {s["kind"]: s for s in doc["scripts"]}
    assert set(by_kind) == {"portal_message", "call"}
    assert by_kind["portal_message"]["item_id"] == mri["id"]
    assert "W987654321" not in by_kind["portal_message"]["body"]
    assert doc["cited"]["email/personal/mychart@example"] == {
        "source": "email",
        "ts": ago(days=12),
    }
    assert set(doc["cited"]) == {e for i in doc["open_items"] for e in i["evidence"]} | {
        e for t in doc["timeline"] for e in t["evidence"]
    }
    assert doc["records"]["email"] == 3 and doc["records"]["whatsapp"] == 5


def test_care_json_is_private(tmp_path, model):
    vault = make_vault(tmp_path)
    care.care(vault, now=NOW)
    folder = vault / "clones" / "care"
    assert os.name == "nt" or stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert os.name == "nt" or stat.S_IMODE((folder / "care.json").stat().st_mode) == 0o600
    assert not list(folder.glob(".*.tmp"))


def test_a_second_run_keeps_ids_and_items_the_model_left_out(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = full_answer
    care.care(vault, now=NOW)
    before = {i["title"]: i["id"] for i in saved(vault)["open_items"]}
    mri = before["Get the MRI report sent to primary care"]

    model.make = lambda prompt: answer(
        items=[entry("Get the MRI report to primary care, reworded", id=mri, status="waiting")]
    )
    care.care(vault, now=NOW + timedelta(days=1))

    assert (
        f"- id {mri} [records; open, waiting on provider, due 2026-10-25]"
        in (model.calls[1]["prompt"])
    )
    after = {i["id"]: i for i in saved(vault)["open_items"]}
    assert set(after) == set(before.values())
    assert after[mri]["title"] == "Get the MRI report to primary care, reworded"
    assert after[mri]["status"] == "waiting"
    assert after[mri]["evidence"] == ["email/personal/mychart@example"]  # kept from before


def test_nothing_found_means_no_model_call(tmp_path, model):
    vault = tmp_path / "vault"
    write_stream(vault / "raw" / "whatsapp" / "messages", [wa("x", ago(days=1), "Bo", "hi")])
    stats = care.care(vault, now=NOW)
    assert model.calls == []
    assert stats["records"] == 0
    assert saved(vault)["open_items"] == [] and saved(vault)["summary"] == ""


def test_a_dry_run_counts_without_the_model_or_files(tmp_path, model):
    vault = make_vault(tmp_path)
    stats = care.care(vault, now=NOW, dry_run=True)
    assert model.calls == []
    assert not (vault / "clones" / "care").exists()
    assert stats["email"] == 3 and stats["whatsapp"] == 5 and stats["records"] == 15
    assert stats["chars"] > 0


# ── Feedback ────────────────────────────────────────────────────────────────


def two_items(prompt):
    return answer(
        items=[
            entry("Pay the urgent care bill", id="new-1", kind="bill"),
            entry("Book the dermatology follow-up", id="new-2", kind="appointment"),
            entry("Ask about the allergy referral", id="new-3", kind="referral"),
        ]
    )


def test_done_and_not_relevant_stay_closed_and_waiting_holds(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = two_items
    care.care(vault, now=NOW)
    ids = {i["title"]: i["id"] for i in saved(vault)["open_items"]}
    bill, derm = ids["Pay the urgent care bill"], ids["Book the dermatology follow-up"]
    referral = ids["Ask about the allergy referral"]

    marked = (NOW + timedelta(hours=1)).isoformat()
    feedback(
        vault,
        {"item_id": bill, "action": "done", "ts": marked},
        {"item_id": derm, "action": "not_relevant", "ts": marked},
        {"item_id": referral, "action": "waiting", "ts": marked},
        "not json",
        {"item_id": referral, "action": "explode", "ts": marked},
    )
    # The model brings everything back, the closed ones reworded only in case.
    model.make = lambda prompt: answer(
        items=[
            entry("PAY THE URGENT CARE BILL", id="new-1", kind="bill"),
            entry("Book the dermatology follow-up", id="new-2", kind="appointment"),
            entry("Ask about the allergy referral", id=referral, kind="referral"),
        ],
        scripts=[
            {"item_id": referral, "kind": "email", "title": "Nudge", "body": "Hello."},
            {"item_id": "new-1", "kind": "call", "title": "Bill", "body": "Hello."},
        ],
    )
    care.care(vault, now=NOW + timedelta(days=1))

    prompt = model.calls[1]["prompt"]
    assert bill not in prompt.split("## Closed")[0] and derm not in prompt
    assert "- Pay the urgent care bill (bill): done" in prompt
    assert "- Book the dermatology follow-up (appointment): not relevant" in prompt
    doc = saved(vault)
    items = {i["id"]: i for i in doc["open_items"]}
    assert set(items) == {bill, referral}
    assert items[bill]["status"] == "done"
    assert items[referral]["status"] == "waiting"  # nothing newer than the mark
    assert [s["item_id"] for s in doc["scripts"]] == [referral]
    closed = json.loads((vault / "clones" / "care" / "closed.json").read_text())
    assert closed[bill]["action"] == "done" and closed[derm]["action"] == "not_relevant"


def test_waiting_ends_when_a_newer_record_is_cited(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = two_items
    care.care(vault, now=NOW)
    referral = next(i["id"] for i in saved(vault)["open_items"] if i["kind"] == "referral")
    feedback(vault, {"item_id": referral, "action": "waiting", "ts": ago(days=3)})

    def reopened(prompt):
        newer = ref(prompt, "Call insurance about the ER claim")  # two days ago
        return answer(
            items=[
                entry(
                    "Ask about the allergy referral",
                    id=referral,
                    kind="referral",
                    evidence=[newer],
                )
            ]
        )

    model.make = reopened
    care.care(vault, now=NOW + timedelta(days=1))
    assert {i["id"]: i for i in saved(vault)["open_items"]}[referral]["status"] == "open"


def test_done_items_leave_the_list_after_thirty_days(tmp_path, model):
    vault = make_vault(tmp_path)
    model.make = two_items
    care.care(vault, now=NOW)
    bill = next(i["id"] for i in saved(vault)["open_items"] if i["kind"] == "bill")
    feedback(vault, {"item_id": bill, "action": "done", "ts": NOW.isoformat()})

    model.make = lambda prompt: answer()
    care.care(vault, now=NOW + timedelta(days=5))
    assert bill in {i["id"] for i in saved(vault)["open_items"]}
    care.care(vault, now=NOW + timedelta(days=31))
    assert bill not in {i["id"] for i in saved(vault)["open_items"]}


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_the_command_line_reads_days_and_dry_run(tmp_path, model, monkeypatch, capsys):
    from proxenos import cli

    vault = make_vault(tmp_path)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    seen = {}

    def fake(vault, days, dry_run):
        seen.update(days=days, dry=dry_run)
        return {"records": 1}

    monkeypatch.setattr(care, "care", fake)
    cli.main(["clone", "care", "--days", "30", "--dry-run"])
    assert seen == {"days": 30.0, "dry": True}
    assert capsys.readouterr().out.strip() == "care: 1 records"
    assert cli.NIGHT_CLONES.index("care") == cli.NIGHT_CLONES.index("tasks") + 1


def test_the_work_clone_drafts_care_emails_and_portal_messages(tmp_path, model):
    vault = tmp_path / "vault"
    doc = {
        "open_items": [
            {
                "id": "aaa",
                "title": "Get the MRI report",
                "kind": "records",
                "status": "open",
                "waiting_on": "provider",
                "next_step": "Ask the clinic.",
                "due": None,
            },
            {
                "id": "bbb",
                "title": "Pay the bill",
                "kind": "bill",
                "status": "done",
                "waiting_on": "me",
                "next_step": "",
                "due": None,
            },
            {
                "id": "ccc",
                "title": "Chase referral",
                "kind": "referral",
                "status": "open",
                "waiting_on": "provider",
                "next_step": "",
                "due": None,
            },
        ],
        "scripts": [
            {
                "id": "s1",
                "item_id": "aaa",
                "kind": "portal_message",
                "title": "Ask for report",
                "body": "Please send my MRI report to [primary care office].",
            },
            {"id": "s2", "item_id": "aaa", "kind": "call", "title": "Call", "body": "Hi."},
            {"id": "s3", "item_id": "bbb", "kind": "email", "title": "Bill", "body": "Hi."},
            {"id": "s4", "item_id": "ccc", "kind": "email", "title": "Referral", "body": "Hi."},
        ],
    }
    (vault / "clones" / "care").mkdir(parents=True)
    (vault / "clones" / "care" / "care.json").write_text(json.dumps(doc))
    feedback(vault, {"item_id": "ccc", "action": "waiting", "ts": NOW.isoformat()})

    jobs = list(work._jobs(vault, NOW))
    assert [(j["id"], j["for"]) for j in jobs] == [("care-aaa-portal_message", "care")]
    assert "a patient portal message" in jobs[0]["prompt"]
    assert "[primary care office]" in jobs[0]["prompt"]
    assert "nothing added" in jobs[0]["prompt"]
