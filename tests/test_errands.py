"""Errands, with the model and every sender faked out, on a synthetic vault. No model, no real
data, and nothing is ever sent."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import llm, memory
from proxenos.clones import errands

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def write_month(vault, folder, month, records):
    path = vault / "raw" / folder / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in records))


def mail(n, **fields):
    return {
        "id": f"m{n}",
        "ts": f"2026-09-{n:02d}T10:00:00Z",
        "account": "tess",
        "from_address": "tess@x.org",
        "from_name": "Tess Ray",
        "from_me": False,
        "to": ["tess@x.org"],
        "cc": None,
        "subject": "Hello",
        "in_reply_to": None,
        "attachments": None,
        "body_new": "Hi.",
    } | fields


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess Ray")
    monkeypatch.setenv("PROXENOS_EMAILS", "tess@x.org")
    v = tmp_path / "vault"
    write_month(
        v,
        "email/tess",
        "2026-09",
        [
            mail(1, from_address="ana.lee@acme.org", from_name="Ana Lee", subject="The data"),
            mail(2, from_address="ana.lee@acme.org", from_name="Ana Lee", subject="Re: The data"),
            mail(
                3,
                from_address="notifications-noreply@linkedin.com",
                from_name="Ana Lee via LinkedIn",
            ),
            mail(
                4,
                from_me=True,
                to=["hiring@beta.com"],
                subject="Interest in the Beta role",
                attachments=["TessRayCV.pdf"],
                body_new="Dear team, I'm interested in the open role. My CV is attached.",
            ),
            mail(
                5,
                from_me=True,
                to=["office@school.edu"],
                subject="Signed forms",
                attachments=["forms.pdf", "Tess_Ray_CV.pdf"],
                body_new="Here are the forms.",
            ),
        ],
    )
    write_month(
        v,
        "linkedin/messages",
        "2026-09",
        [
            {
                "id": "beeper:!ben/1",
                "ts": "2026-09-20T10:00:00Z",
                "from_me": False,
                "text": "Good to meet you",
                "conversation_id": "beeper:!ben",
                "conversation_title": "Ben Ode",
                "author": "Ben Ode",
                "folder": "INBOX",
            },
            {  # a group chat Ben is in: never a way to reach him alone
                "id": "beeper:!group/1",
                "ts": "2026-09-21T10:00:00Z",
                "from_me": False,
                "text": "Hi all",
                "conversation_id": "beeper:!group",
                "conversation_title": "Lab alumni",
                "author": "Ben Ode",
                "folder": "INBOX",
            },
        ],
    )
    people = v / "clones" / "network" / "people.json"
    people.parent.mkdir(parents=True)
    people.write_text(
        json.dumps(
            {
                "people": [
                    {
                        "name": "Ben Ode",
                        "org": "Acme Labs, Inc.",
                        "context": "LinkedIn connection (CTO at Acme Labs)",
                        "sources": ["linkedin/connections"],
                        "interactions": 1,
                    },
                    {"name": "Dee Fay", "org": "Beta Corp", "sources": ["email"]},
                ]
            }
        )
    )
    memory.build(v)
    monkeypatch.setattr(
        errands,
        "find_cv",
        lambda person, roots=None: {
            "name": "TessRayCV.pdf",
            "path": str(tmp_path / "TessRayCV.pdf"),
            "made": "2026-09-01T00:00:00Z",
            "where": "~/Documents",
            "text": "Tess Ray. Expected graduation May 2026.",
        },
    )
    (tmp_path / "TessRayCV.pdf").write_bytes(b"%PDF-1.4")
    return v


class Model:
    def __init__(self, person, org, intro_to=""):
        self.person, self.org, self.intro_to = person, org, intro_to
        self.calls = []

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", **kw):
        self.calls.append({"prompt": prompt, "system": system, "effort": effort})
        if "You read an errand" in system:
            return {
                "person": self.person,
                "org": self.org,
                "purpose": "Ask about the open role.",
                "channel": "email",
                "cv": True,
            }
        return {
            "who": "",
            "subject": '""' if self.intro_to else "The open role at Acme",
            "body": f"Hi {self.person.split()[0]},\n\nI'm writing about the open role.\n\nTess",
            "cv_notes": [
                {"says": "Expected graduation May 2026", "now": "Graduated May 2026"},
                {"says": "Analyst, Acme", "now": "Analyst, Acme."},  # nothing changed: left out
                {"says": "BA, May 2021", "now": "BA (completed May 2021)"},  # only added to
                "not a pair",
            ],
            "needs": ["Mention the thesis?"],
            "intro": {
                "to": self.intro_to,
                "subject": "",
                "body": "Hi Ben, could you introduce me?" if self.intro_to else "",
            },
            "why": "It follows your earlier reach-out.",
        }


def test_a_way_to_reach_them_is_an_address_they_wrote_from_never_a_noreply(vault):
    routes = errands.reach(vault, "Ana Lee")

    assert [(r["channel"], r["address"], r["seen"]) for r in routes] == [
        ("email", "ana.lee@acme.org", 2)
    ]
    assert routes[0]["how"].startswith("they wrote from it (2026-09-02")


def test_a_chat_with_them_alone_through_beeper_is_a_way_to_reach_them(vault):
    (route,) = errands.reach(vault, "Ben Ode")

    assert route["channel"] == "linkedin"
    assert route["chat"] == {"source": "linkedin", "chat": "beeper:!ben", "last": "beeper:!ben/1"}


def test_the_pattern_is_the_users_reach_outs_with_a_cv_not_any_mail_with_one(vault):
    assert [e["subject"] for e in errands.earlier_emails(vault)] == ["Interest in the Beta role"]


def test_a_cv_is_known_by_its_name_and_dated_by_what_it_says(tmp_path):
    names = [
        "TessRayCV.pdf",
        "Tess_Ray_CV.pdf",
        "resume (1).pdf",
        "cv.pdf",
        "CVPR2024.pdf",
        "scv.pdf",
    ]
    assert [n for n in names if errands._CV_NAME.search(n)] == names[:4]

    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF")  # its file time is now: a download's
    assert errands._made(pdf, None, "BA, 2019 - 2024") == datetime(2024, 12, 31, tzinfo=UTC)
    made = datetime(2025, 5, 1, tzinfo=UTC)
    assert errands._made(pdf, made, "2019 - 2024") == made


def test_an_errand_goes_as_far_as_it_can_and_stops_one_tap_short(vault):
    model = Model("Ana Lee", "Acme Labs")

    errand = errands.start(vault, "Reach Ana Lee at Acme about the role, with my CV", NOW, model)

    assert errand["status"] == "ready"
    (message,) = errand["messages"]
    assert message | {"body": ""} == {
        "role": "main",
        "to": "Ana Lee",
        "channel": "email",
        "address": "ana.lee@acme.org",
        "via": "apple_mail",
        "chat": None,
        "evidence": message["evidence"],
        "subject": "The open role at Acme",
        "body": "",
        "attach": True,
        "state": "ready",
        "sent_at": "",
    }
    assert [s["title"] for s in errand["steps"]] == [
        "Read the errand",
        "Looked them up",
        "Looked for a way to reach them",
        "Found your CV",
        "Read how you write these",
        "Wrote it",
        "Checked the CV",
        "Stopped one tap short",
    ]
    assert errand["summary"].startswith(
        "Ready to send to Ana Lee at ana.lee@acme.org, with TessRayCV"
    )
    assert errand["cv"]["notes"] == [
        "It says “Expected graduation May 2026”; now: Graduated May 2026"
    ]
    assert [c["effort"] for c in model.calls] == ["low", "medium"]
    prompt = model.calls[1]["prompt"]
    assert "ana.lee@acme.org" in prompt and "Interest in the Beta role" in prompt
    assert "Expected graduation May 2026" in prompt
    saved = errands.load(vault, errand["id"])
    assert saved["status"] == "ready" and saved["summary"] == errand["summary"]
    assert not (vault / "state" / "asking").exists()  # the foreground mark is gone again
    assert not (vault / "clones" / "outbox" / "log.jsonl").exists()  # nothing went out


def test_with_no_way_to_reach_them_it_waits_and_asks_someone_there_to_introduce(vault):
    model = Model("Cy Doe", "Acme Labs", intro_to="Ben Ode")

    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, model)

    main, intro = errand["messages"]
    assert (main["state"], main["address"], main["via"]) == ("waiting", "", "")
    assert main["subject"] == ""  # the model's "" is no subject
    assert (intro["to"], intro["channel"], intro["via"], intro["state"]) == (
        "Ben Ode",
        "linkedin",
        "beeper",
        "ready",
    )
    assert intro["attach"] is False
    assert "Ben Ode, LinkedIn connection" in errand["steps"][1]["detail"]
    assert "Ben Ode (by linkedin)" in model.calls[1]["prompt"]
    assert errand["summary"].startswith("No way to reach Cy Doe in your records")
    assert "Ready instead: a note to Ben Ode" in errand["summary"]


def test_an_errand_that_fails_says_so_and_fails(vault):
    def broken(prompt, **kw):
        raise llm.ModelError("the model fell over")

    with pytest.raises(llm.ModelError):
        errands.start(vault, "Reach Ana Lee", NOW, broken)

    (saved,) = errands.listed(vault)
    assert saved["status"] == "failed" and "fell over" in saved["error"]
    assert saved["steps"][-1]["title"] == "Stopped"


def test_send_sends_that_one_message_as_edited_and_only_once(vault):
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, Model("Cy Doe", "Acme Labs"))
    sent = []

    def sender(message, cv):
        sent.append((message["via"], message["address"], message["subject"], message["body"], cv))

    with pytest.raises(SystemExit, match="no way to send it"):
        errands.send(vault, errand["id"], 0, {}, NOW, sender)
    with pytest.raises(SystemExit, match="isn't an email address"):
        errands.send(vault, errand["id"], 0, {"address": "cy at acme"}, NOW, sender)
    with pytest.raises(SystemExit, match="placeholder"):
        errands.send(
            vault, errand["id"], 0, {"address": "cy@acme.org", "body": "Hi [name]"}, NOW, sender
        )
    with pytest.raises(SystemExit, match="subject"):
        errands.send(vault, errand["id"], 0, {"address": "cy@acme.org", "subject": ""}, NOW, sender)
    assert sent == []

    edits = {"address": "cy@acme.org", "subject": "The role", "body": "Hi Cy, the role."}
    after = errands.send(vault, errand["id"], 0, edits, NOW, sender)

    assert len(sent) == 1
    via, address, subject, body, cv = sent[0]
    assert (via, address, subject, body, cv["name"]) == (
        "apple_mail",
        "cy@acme.org",
        "The role",
        "Hi Cy, the role.",
        "TessRayCV.pdf",
    )
    assert after["status"] == "sent" and after["messages"][0]["sent_at"]
    assert after["steps"][-1]["title"] == "Sent"
    (logged,) = [
        json.loads(line) for line in (vault / "clones/outbox/log.jsonl").read_text().splitlines()
    ]
    assert logged["draft_id"] == f"{errand['id']}/0" and logged["ok"] is True
    with pytest.raises(SystemExit, match="sent already"):
        errands.send(vault, errand["id"], 0, {}, NOW, sender)
    assert len(sent) == 1


def test_each_night_a_waiting_errand_looks_again_for_a_way_to_reach_them(vault):
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, Model("Cy Doe", "Acme Labs"))
    assert errands.night(vault, NOW) == {"errands_checked": 1, "errands_ready": 0}

    write_month(
        vault, "email/tess", "2026-09", [mail(20, from_address="cy@acme.org", from_name="Cy Doe")]
    )
    memory.build(vault)

    assert errands.night(vault, NOW) == {"errands_checked": 1, "errands_ready": 1}
    again = errands.load(vault, errand["id"])
    assert again["status"] == "ready"
    assert (again["messages"][0]["address"], again["messages"][0]["via"]) == (
        "cy@acme.org",
        "apple_mail",
    )
    assert again["steps"][-1]["title"] == "Found a way to reach them"
    assert errands.night(vault, NOW) == {"errands_checked": 0, "errands_ready": 0}


def test_a_dropped_errand_is_left_alone(vault):
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, Model("Cy Doe", "Acme Labs"))
    errands.drop(vault, errand["id"])
    assert errands.load(vault, errand["id"])["status"] == "dropped"
    assert errands.night(vault, NOW)["errands_checked"] == 0


def test_the_pages_requests_are_checked(vault):
    good = errands._request(
        json.dumps({"send": "errand-20261001T090000Z", "index": 0, "body": "Hi"})
    )
    assert good["index"] == 0
    for bad in (
        "not json",
        "[1]",
        json.dumps({"send": 3, "index": 0}),
        json.dumps({"send": "errand-20261001T090000Z", "index": True}),
        json.dumps({"send": "errand-20261001T090000Z", "index": 0, "body": 5}),
        json.dumps({"drop": ["x"]}),
        json.dumps({"goal": 5}),
    ):
        with pytest.raises(SystemExit):
            errands._request(bad)
    with pytest.raises(SystemExit, match="isn't an errand's id"):
        errands.load(vault, "../../etc/passwd")
