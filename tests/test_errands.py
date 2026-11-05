"""Errands, with the model and every sender faked out, on a synthetic vault. No model, no real
data, and nothing is ever sent."""

import json
from datetime import UTC, datetime

import pytest

from proxenos import llm, lookup, memory, voice
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
        "account": "joe",
        "from_address": "joe@x.org",
        "from_name": "Joe Bloggs",
        "from_me": False,
        "to": ["joe@x.org"],
        "cc": None,
        "subject": "Hello",
        "in_reply_to": None,
        "attachments": None,
        "body_new": "Hi.",
    } | fields


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Joe Bloggs")
    monkeypatch.setenv("PROXENOS_EMAILS", "joe@x.org")
    v = tmp_path / "vault"
    write_month(
        v,
        "email/joe",
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
                attachments=["JoeBloggsCV.pdf"],
                body_new="Dear team, I'm interested in the open role. My CV is attached.",
            ),
            mail(
                5,
                from_me=True,
                to=["office@school.edu"],
                subject="Signed forms",
                attachments=["forms.pdf", "Joe_Bloggs_CV.pdf"],
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
            "name": "JoeBloggsCV.pdf",
            "path": str(tmp_path / "JoeBloggsCV.pdf"),
            "made": "2026-09-01T00:00:00Z",
            "where": "~/Documents",
            "text": "Joe Bloggs. Operations manager since 2022; CV updated 2026.",
        },
    )
    (tmp_path / "JoeBloggsCV.pdf").write_bytes(b"%PDF-1.4")
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
            "body": f"Hi {self.person.split()[0]},\n\nI'm writing about the open role.\n\nJoe",
            "cv_notes": [
                {"says": "Operations manager since 2022", "now": "Operations manager, 2022 to now"},
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
        "JoeBloggsCV.pdf",
        "Joe_Bloggs_CV.pdf",
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
        "copied": False,
        "state": "ready",
        "sent_at": "",
        "from_account": "joe",  # the mailbox they last wrote with Ana Lee in
        "from_address": "joe@x.org",
        "from_for": "ana.lee@acme.org",
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
        "Ready to send to Ana Lee at ana.lee@acme.org, with JoeBloggsCV"
    )
    assert errand["cv"]["notes"] == [
        "It says “Operations manager since 2022”; now: Operations manager, 2022 to now"
    ]
    assert [c["effort"] for c in model.calls] == ["low", "medium"]
    prompt = model.calls[1]["prompt"]
    assert "ana.lee@acme.org" in prompt and "Interest in the Beta role" in prompt
    assert "Operations manager since 2022" in prompt
    saved = errands.load(vault, errand["id"])
    assert saved["status"] == "ready" and saved["summary"] == errand["summary"]
    assert not (vault / "state" / "asking").exists()  # the foreground mark is gone again
    assert not (vault / "clones" / "outbox" / "log.jsonl").exists()  # nothing went out


def test_the_message_follows_the_rules_and_the_email_i_send(vault):
    body = "Hi Dee, quick one, I think the numbers are kind of off for Q3, can we talk. " * 3
    write_month(
        vault, "email/joe", "2026-09", [mail(6, from_me=True, to=["dee@beta.com"], body_new=body)]
    )
    model = Model("Ana Lee", "Acme Labs")

    errands.start(vault, "Reach Ana Lee at Acme about the role, with my CV", NOW, model)

    write = model.calls[1]
    assert voice.rules("Joe Bloggs") in write["system"]
    assert '<example kind="email" date="2026-09-06" title="Hello">' in write["prompt"]
    assert "the numbers are kind of off" in write["prompt"]


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


def test_a_wechat_message_is_written_to_copy_there_never_sent_another_way(vault):
    class WeChat(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            return answer | {"channel": "wechat", "cv": False} if "person" in answer else answer

    model = WeChat("Ana Lee", "Acme Labs")

    errand = errands.start(vault, "Message Ana Lee on WeChat about my paper", NOW, model)

    (message,) = errand["messages"]  # her email address is known, and isn't used
    assert (message["channel"], message["address"], message["state"]) == ("wechat", "", "waiting")
    assert "in their WeChat chat, where" in model.calls[1]["prompt"]
    assert errand["summary"] == "Written for Ana Lee: copy it into your WeChat chat with them."
    assert errands.recheck(vault, errand, NOW) is False


def dm(n, **fields):
    """A message in a Slack DM with John Murray, as proxenos.ingest.slack writes one."""
    return {
        "id": f"D1/17000000{n:02d}.000100",
        "ts": f"2026-09-{n:02d}T15:00:00Z",
        "slack_ts": f"17000000{n:02d}.000100",
        "channel_id": "D1",
        "channel_name": "John Murray",
        "channel_type": "dm",
        "user_id": "U2",
        "user_name": "John Murray",
        "from_me": False,
        "text": "Sure, send it over",
        "thread_ts": None,
        "is_reply": False,
        "subtype": None,
        "files": None,
    } | fields


def test_a_slack_errand_is_written_like_my_dms_with_them_to_copy_there_never_sent(vault):
    joe = {"from_me": True, "user_id": "U1", "user_name": "Joe Bloggs"}
    write_month(
        vault,
        "slack/acme-lab/messages",
        "2026-09",
        [
            dm(10, **joe, text="hey john got a sec this week to look at the fig 3 draft?"),
            dm(11),
            dm(12, **joe, text="sent! no rush, thursday is fine"),
            dm(  # John in a channel: not the DM
                13,
                id="C1/1700000013.000100",
                channel_id="C1",
                channel_name="general",
                channel_type="channel",
                text="Lab meeting moved to 3pm",
            ),
        ],
    )
    john = {"from_address": "john.murray@uni.edu", "from_name": "John Murray"}
    write_month(vault, "email/joe", "2026-09", [mail(21, **john, subject="Reading group")])
    memory.build(vault)

    class Slack(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            if "person" in answer:
                return answer | {"org": "", "channel": "slack", "cv": False}
            signed = (
                "Hi John,\n\nWould you read my paper draft this week?\n\nBest,\nJoe Bloggs, PhD"
            )
            return answer | {"subject": "My paper", "body": signed}

    model = Slack("John Murray", "")
    errand = errands.start(vault, "Message John Murray on Slack about my paper", NOW, model)

    (message,) = errand["messages"]  # his email address is known, and isn't used
    assert message | {"body": ""} == {
        "role": "main",
        "to": "John Murray",
        "channel": "slack",
        "address": "",
        "via": "",
        "chat": None,
        "evidence": "your Slack DM with them in acme-lab, 3 messages, the last on 2026-09-12",
        "subject": "",
        "body": "",
        "attach": False,
        "copied": True,
        "state": "waiting",
        "sent_at": "",
    }
    assert message["body"] == "Hi John,\n\nWould you read my paper draft this week?"
    assert errand["summary"] == "Written for John Murray: copy it into your Slack chat with them."
    steps = {s["title"]: s["detail"] for s in errand["steps"]}
    assert steps["Read the errand"].endswith("By Slack.")
    assert (
        "never posts in it. John Murray: your Slack DM" in steps["Looked for a way to reach them"]
    )
    assert steps["Read how you write these"].startswith("It goes in a Slack chat")
    prompt = model.calls[1]["prompt"]
    own = "In this conversation:\n- sent! no rush, thursday is fine\n- hey john got a sec"
    assert own in prompt and "DM in the acme-lab workspace" in prompt
    assert "Interest in the Beta role" not in prompt  # no reach-out emails as the pattern

    sent = []
    with pytest.raises(SystemExit, match="no way to send it"):
        errands.send(vault, errand["id"], 0, {}, NOW, lambda m, cv: sent.append(m))
    assert sent == [] and errands.recheck(vault, errand, NOW) is False
    assert not (vault / "clones" / "outbox" / "log.jsonl").exists()  # nothing went out

    # A DM in another workspace whose name Slack didn't resolve is known by who wrote in it, and
    # the newest one is where the next goes.
    later = dm(1, id="D9/1", channel_id="D9", channel_name=None, ts="2026-10-02T09:00:00Z")
    write_month(vault, "slack/other-lab/messages", "2026-10", [later])
    assert errands.slack_dm(vault, "John Murray")["chat"]["chat"] == "other-lab/D9"
    assert errands.slack_dm(vault, "Ana Lee") is None


def test_a_chat_message_loses_the_signature_an_email_would_have(vault):
    class Signed(Model):
        def __call__(self, prompt, **kw):
            answer = super().__call__(prompt, **kw)
            if "body" in answer:
                answer["body"] += ", PhD\nOperations Manager\nAcme Labs"
            return answer

    errand = errands.start(vault, "Reach Ben Ode", NOW, Signed("Ben Ode", "Acme Labs"))

    (message,) = errand["messages"]
    assert message["channel"] == "linkedin"
    assert message["body"] == "Hi Ben,\n\nI'm writing about the open role."
    assert errands._chat_body("Can you read it?\n\nThanks!\nJoe", "Joe Bloggs") == (
        "Can you read it?\n\nThanks!"
    )
    kept = "Hey Ben!\nJoe here, I wrote a paper.\nCan you read it?"
    assert errands._chat_body(kept, "Joe Bloggs") == kept


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
        "JoeBloggsCV.pdf",
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


def test_with_no_address_in_the_records_one_on_their_places_own_pages_is_used(vault, monkeypatch):
    page = "https://people.acmelabs.org/cy-doe"
    search = f'<a class="result__a" href="{page}">Cy Doe | Acme Labs</a>'
    asked = []

    def web(url, headers):
        asked.append(url)
        if url.startswith(lookup.DUCKDUCKGO):
            return "text/html", search.encode()
        if url == page:
            return "text/html", b"<h1>Cy Doe</h1><p>Write to cy.doe [at] acmelabs.org</p>"
        raise OSError("not found")

    monkeypatch.setattr(lookup, "_fetch", web)
    model = Model("Cy Doe", "Acme Labs")

    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, model)

    assert errand["status"] == "ready"
    (message,) = errand["messages"]  # reachable now, so no note asking for an introduction
    assert (message["address"], message["via"], message["state"]) == (
        "cy.doe@acmelabs.org",
        "apple_mail",
        "ready",
    )
    assert (message["found"], message["sources"]) == ("web", [page])
    assert message["evidence"] == "it's on 1 page of acmelabs.org's own"
    step = next(s for s in errand["steps"] if s["title"] == "Looked on the web")
    assert page in step["detail"] and "Check it's theirs" in step["detail"]
    assert "cy.doe@acmelabs.org, known because it's on 1 page" in model.calls[1]["prompt"]
    assert errand["summary"].startswith("Ready to send to Cy Doe at cy.doe@acmelabs.org")
    # Only the name and the place went to the search engine; nothing about Joe.
    query = asked[0].split("?q=", 1)[1]
    assert query == "%22Cy+Doe%22+Acme+Labs+email"
    assert not (vault / "clones" / "outbox" / "log.jsonl").exists()  # nothing went out

    sent = []
    errands.send(vault, errand["id"], 0, {}, NOW, lambda m, cv: sent.append(m["address"]))
    assert sent == ["cy.doe@acmelabs.org"]


def test_with_lookups_off_or_none_found_an_errand_waits_as_before(vault, monkeypatch):
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, Model("Cy Doe", "Acme Labs"))
    step = next(s for s in errand["steps"] if s["title"] == "Looked on the web")
    assert "the search failed" in step["detail"] and "isn't guessed" in step["detail"]
    assert errand["messages"][0]["state"] == "waiting"

    monkeypatch.setenv("PROXENOS_LOOKUP", "off")
    later = datetime(2026, 10, 1, 9, 5, tzinfo=UTC)
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", later, Model("Cy Doe", "Acme Labs"))
    assert "Looked on the web" not in [s["title"] for s in errand["steps"]]
    assert errand["steps"][2]["detail"].endswith("so the message waits for one.")
    assert "found" not in errand["messages"][0]


def test_each_night_a_waiting_errand_looks_again_for_a_way_to_reach_them(vault):
    errand = errands.start(vault, "Reach Cy Doe at Acme Labs", NOW, Model("Cy Doe", "Acme Labs"))
    assert errands.night(vault, NOW) == {"errands_checked": 1, "errands_ready": 0}

    write_month(
        vault, "email/joe", "2026-09", [mail(20, from_address="cy@acme.org", from_name="Cy Doe")]
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
