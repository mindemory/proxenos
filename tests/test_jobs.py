"""The jobs clone on a synthetic vault with the model faked out. No network, no model, no real
data: the companies, people and addresses are made up, and links use example domains."""

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from proxenos import ask
from proxenos.clones import jobs, work

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ME = "tess@uni.example"
TYPES = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "types.ts"
ASK_ID = "ask-20261015T090000Z"

ALERT = (
    "Your job alert for research scientist. 2 new jobs match your preferences. "
    "Research Scientist, Memory Systems\nQuillon Labs · Boston, MA (Hybrid)\n"
    "https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc%3D&refId=x1\n"
    "Machine Learning Engineer\nFernway · Remote\n"
    "https://www.linkedin.com/comm/jobs/view/4011223355/?trackingId=def\n"
    "See all jobs https://www.linkedin.com/comm/e/v2?e=redirect\n"
    "Unsubscribe: https://www.linkedin.com/comm/psettings/email-unsubscribe?lipi=abc"
)
RECRUITER = (
    "Hi Tess, I'm a recruiter with TalentBridge. Quillon Labs is hiring a Research Scientist, "
    "Memory Systems in Boston, and your work on working memory fits it well. Would you be open "
    "to a quick chat this week? The base salary is $160k to $190k."
)
WAAS = (
    "Priya Raman, founder of Tallybird (YC W26), sent you a message on Work at a Startup: "
    "Hi Tess, we're hiring a founding research engineer to build memory for our agents, "
    "on-site in San Francisco, $150k to $180k and equity. Interested? "
    "Reply: https://www.workatastartup.com/messages/8812"
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r) + "\n" for r in records))


def mail(key, ts, sender, address, subject, body, to=(ME,), mine=False, bulk=False):
    return {
        "id": key,
        "ts": ts,
        "account": "uni",
        "from_address": ME if mine else address,
        "from_name": "Tess Moreau" if mine else sender,
        "from_me": mine,
        "to": list(to),
        "cc": [],
        "subject": subject,
        "in_reply_to": None,
        "gmail_labels": [],
        "bulk": bulk,
        "body": body,
        "body_new": body,
    }


ALERT_MAIL = mail(
    "alert",
    "2026-10-20T08:00:00Z",
    "LinkedIn Job Alerts",
    "jobalerts-noreply@linkedin.com",
    "Your job alert for research scientist",
    ALERT,
    bulk=True,
)
RECRUITER_MAIL = mail(
    "recruiter",
    "2026-10-22T15:00:00Z",
    "Marco Velli",
    "marco@talentbridge.example",
    "Research Scientist role at Quillon Labs",
    RECRUITER,
)
WAAS_MAIL = mail(
    "waas",
    "2026-10-24T18:00:00Z",
    "Work at a Startup",
    "no-reply@workatastartup.com",
    "Priya Raman from Tallybird sent you a message",
    WAAS,
)
RECEIPT_MAIL = mail(
    "receipt",
    "2026-10-25T10:00:00Z",
    "Fernway Hiring",
    "no-reply@us.greenhouse-mail.io",
    "Thank you for applying to Fernway",
    "Hi Tess, thank you for applying for the Machine Learning Engineer role at Fernway. "
    "We have received your application and will be in touch.",
)
COLLEAGUE_MAIL = mail(
    "colleague",
    "2026-10-23T09:00:00Z",
    "Sam Okafor",
    "sam@uni.example",
    "Re: lab meeting",
    "The role of attention in the position of the probe matters. Are you interested in "
    "presenting next week?",
)
YC_MAIL = mail(
    "yc",
    "2026-10-21T09:00:00Z",
    "Y Combinator",
    "news@ycombinator.com",
    "Demo Day is coming",
    "Watch the founders present live. Register now.",
    bulk=True,
)
SENT_MAIL = mail(
    "sent",
    "2026-10-30T09:00:00Z",
    "",
    "",
    "Re: Research Scientist role at Quillon Labs",
    "Hi Marco, happy to talk. My résumé is attached.",
    to=("marco@talentbridge.example",),
    mine=True,
)

RESUME = {
    "name": "Tess_Moreau_Resume.pdf",
    "path": "/nowhere/Tess_Moreau_Resume.pdf",
    "made": "2026-10-01T00:00:00Z",
    "where": "~/Documents",
    "kind": "résumé",
    "text": "Tess Moreau. Research engineer: memory models in PyTorch.",
}
CV = {
    "name": "Tess_Moreau_CV.pdf",
    "path": "/nowhere/Tess_Moreau_CV.pdf",
    "made": "2026-09-01T00:00:00Z",
    "where": "~/Documents",
    "kind": "academic CV",
    "text": "Tess Moreau. Publications: Working memory capacity in recurrent networks. Teaching.",
}


def find(person):
    return [RESUME, CV]


def postdoc():
    return {
        "id": ask.opening_id("Postdoc in Computational Memory", "Halvorsen Lab"),
        "kind": "postdoc",
        "title": "Postdoc in Computational Memory",
        "org": "Halvorsen Lab",
        "place": "Oslo",
        "mode": "on-site",
        "pay": "",
        "deadline": "2026-12-01",
        "link": "https://halvorsenlab.example/jobs",
        "verdict": "apply",
        "why": "Your models are what the lab builds.",
        "draft": {
            "id": f"{ASK_ID}-o1",
            "step": "message",
            "to": "Ingrid Halvorsen",
            "channel": "linkedin",
            "body": "Hi Ingrid, I saw your post about the postdoc.",
        },
    }


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    v = tmp_path / "vault"
    write(v / "self" / "identity.md", "# Identity\n\nTess studies working memory in networks.")
    write(v / "self" / "interests.md", "- Memory models, research engineering, Boston or remote")
    write(v / "self" / "voice.md", "Short sentences.")
    write_jsonl(
        v / "raw" / "email" / "uni" / "2026-10.jsonl",
        [
            ALERT_MAIL,
            RECRUITER_MAIL,
            WAAS_MAIL,
            RECEIPT_MAIL,
            COLLEAGUE_MAIL,
            YC_MAIL,
            SENT_MAIL,
        ],
    )
    write_jsonl(
        v / "raw" / "linkedin" / "connections" / "2023-04.jsonl",
        [
            {
                "id": "c1",
                "ts": "2023-04-12T00:00:00Z",
                "from_me": False,
                "name": "Owen Park",
                "company": "Quillon Labs",
                "position": "Staff Scientist",
            }
        ],
    )
    write(
        v / "clones" / "network" / "people.json",
        json.dumps(
            {
                "people": [
                    {
                        "name": "Dana Whitlock",
                        "org": "Tallybird",
                        "context": "Slack DM (3 messages); worked together at Brightline",
                        "sources": ["slack"],
                        "interactions": 12,
                    }
                ]
            }
        ),
    )
    cfp = {
        "id": ask.opening_id("Call for abstracts", "Memory Society"),
        "kind": "cfp",
        "title": "Call for abstracts",
        "org": "Memory Society",
        "verdict": "maybe",
        "why": "",
        "draft": None,
    }
    write(
        v / "clones" / "ask" / f"{ASK_ID}.json",
        json.dumps(
            {
                "id": ASK_ID,
                "at": "2026-10-15T09:00:00Z",
                "status": "done",
                "seen": "Ingrid Halvorsen: Our lab is hiring a postdoc in computational memory.",
                "openings": [postdoc(), cfp],
            }
        ),
    )
    ask.keep(v, ASK_ID, postdoc()["id"], NOW)
    return v


def block(prompt, marker):
    """The [r..] ref of the record in an identify prompt that holds `marker`, and its text."""
    for part in re.split(r"(?=\[r\d+\] )", prompt):
        if marker in part and (ref := re.match(r"\[(r\d+)\]", part)):
            return ref[1], part
    return None, ""


def tag_after(part, marker):
    return re.search(r"\[(L\d+)\]", part[part.index(marker) :])[1]


def job(refs, company, role, place="", mode="", pay="", link="", contact=None, reply=""):
    return {
        "refs": refs,
        "company": company,
        "role": role,
        "place": place,
        "mode": mode,
        "pay": pay,
        "deadline": "",
        "link": link,
        "contact": contact or {"name": "", "channel": "", "who": ""},
        "reply_link": reply,
    }


class Model:
    """Answers each of the clone's three calls as a model would, from what its prompt shows."""

    def __init__(self):
        self.calls = []

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", **kw):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        if "List each job they name" in system:
            return {"jobs": self.identify(prompt)}
        if "going through the job leads" in system:
            return {"jobs": self.judge(prompt)}
        assert "You draft the first step on a job" in system
        to = re.search(r"Draft (?:\S+ reply to |a short note to )?(\w+ \w+)", prompt)
        return {
            "title": "First step",
            "to": to[1] if to else "",
            "channel": "email",
            "subject": "Re: Research Scientist role at Quillon Labs",
            "body": "Hi, thanks for writing. I'd be glad to talk.",
            "asks": ["Mention the Boston move?"],
        }

    def identify(self, prompt):
        found = []
        ref, part = block(prompt, "Your job alert")
        if ref:
            found += [
                job(
                    [ref],
                    "Quillon Labs",
                    "Research Scientist, Memory Systems",
                    "Boston, MA",
                    "hybrid",
                    link=tag_after(part, "Quillon Labs"),
                ),
                job(
                    [ref],
                    "Fernway",
                    "Machine Learning Engineer",
                    mode="remote",
                    link=tag_after(part, "Fernway"),
                ),
            ]
        if (ref := block(prompt, "TalentBridge")[0]) is not None:
            marco = {"name": "Marco Velli", "channel": "email", "who": "recruiter at TalentBridge"}
            found.append(
                job(
                    [ref],
                    "Quillon Labs, Inc.",
                    "Research Scientist, Memory Systems (Boston)",
                    pay="$160k to $190k",
                    contact=marco,
                )
            )
        ref, part = block(prompt, "Tallybird")
        if ref:
            priya = {"name": "Priya Raman", "channel": "workatastartup", "who": "founder"}
            found.append(
                job(
                    [ref],
                    "Tallybird",
                    "Founding Research Engineer",
                    "San Francisco",
                    "on-site",
                    "$150k to $180k",
                    contact=priya,
                    reply=tag_after(part, "Reply"),
                )
            )
        if (ref := block(prompt, "Thank you for applying to Fernway")[0]) is not None:
            found.append(job([ref], "Fernway", "Machine Learning Engineer"))
        found.append(job(["r99"], "Nowhere", "Invented role"))  # cites no record: dropped
        found.append(job(["r1"], "Somewhere", ""))  # no role: dropped
        return found

    def judge(self, prompt):
        found = re.findall(r"\[(c\d+)\] (résumé|academic CV)", prompt)
        cvs = {kind: ref for ref, kind in found}
        people = {name: ref for ref, name in re.findall(r"\[(p\d+)\] ([^:\n]+):", prompt)}
        answers = []
        for ref, title in re.findall(r"\[(j\d+)\] (.+)", prompt):
            answer = {
                "ref": ref,
                "verdict": "apply",
                "why": "It builds on your memory models.",
                "rests_on": ["self/identity", "self/nowhere"],
                "route": "reply",
                "route_why": "They wrote to you.",
                "cv": cvs["résumé"],
                "cv_why": "Industry research.",
                "people": [],
                "step": "reply",
            }
            if "Quillon" in title:
                answer["people"] = [people["Owen Park"]]
            elif "Tallybird" in title:
                answer["people"] = [people["Dana Whitlock"], "p99"]
            elif "Fernway" in title:
                answer |= {"verdict": "skip", "why": "Remote ML engineering is away from you."}
                answer |= {"route": "apply", "step": "", "cv": ""}
            elif "Postdoc" in title:
                answer |= {"route": "note", "step": "note", "cv": cvs["academic CV"]}
            answers.append(answer)
        return answers


def load(vault):
    return json.loads((vault / "clones" / "jobs" / "jobs.json").read_text(encoding="utf-8"))


def by_company(vault):
    return {j["company"]: j for j in load(vault)["jobs"]}


def test_each_source_s_mail_is_told_by_its_sender_and_words():
    me = {ME}

    def source(record):
        return jobs.mail_source(
            record, record["from_address"], record["subject"], record["body"], me
        )

    assert source(ALERT_MAIL) == "linkedin"
    assert source(WAAS_MAIL) == "workatastartup"
    assert source(RECRUITER_MAIL) == "recruiter"
    assert source(RECEIPT_MAIL) == "boards"
    assert source(COLLEAGUE_MAIL) == ""  # a colleague's "role" and "position" aren't a lead
    assert source(YC_MAIL) == ""  # YC's own news, not Work at a Startup
    viewed = mail(
        "v",
        "2026-10-01T00:00:00Z",
        "LinkedIn",
        "messages-noreply@linkedin.com",
        "Ana viewed your profile",
        "See who's looking. Jobs | Messaging",
        bulk=True,
    )
    assert source(viewed) == ""
    inmail = mail(
        "i",
        "2026-10-01T00:00:00Z",
        "Lena Ortiz via LinkedIn",
        "inmail-hit-reply@linkedin.com",
        "Lena Ortiz sent you a new message",
        "Hi Tess, we're hiring for a role at Brightwell. Would you be open to a quick chat?",
    )
    assert source(inmail) == "linkedin"
    listed = mail(
        "l",
        "2026-10-01T00:00:00Z",
        "Ana Lee via Comp-neuro",
        "comp-neuro@lists.example",
        "Postdoc position available in the Lee lab",
        "Apply by December.",
        to=("list@x",),
        bulk=True,
    )
    assert source(listed) == "lists"
    password = mail(
        "p",
        "2026-10-01T00:00:00Z",
        "Work at a Startup",
        "no-reply@workatastartup.com",
        "Reset your password",
        "Jobs are waiting.",
    )
    assert source(password) == ""


def test_linkedin_links_lose_their_tracking_and_its_redirects_go():
    clean = jobs.clean_link
    assert (
        clean("https://www.linkedin.com/comm/jobs/view/4011223344/?trackingId=abc&refId=x")
        == "https://www.linkedin.com/jobs/view/4011223344/"
    )
    assert clean("https://www.linkedin.com/comm/e/v2?e=redirect") == ""
    assert (
        clean("https://jobs.quillon.example/123?src=li")
        == "https://jobs.quillon.example/123?src=li"
    )


def test_a_job_is_its_company_and_role_from_any_source():
    assert jobs.job_id("Quillon Labs, Inc.", "Research Scientist (Boston)") == jobs.job_id(
        "quillon labs", "Research Scientist"
    )
    assert jobs.job_id("Quillon Labs", "Research Scientist") != jobs.job_id(
        "Quillon Labs", "Research Engineer"
    )
    # A recruiter who doesn't say whom for: the recruiter stands in for the company.
    assert jobs.job_id("", "Data Scientist", "Marco Velli") != jobs.job_id("", "Data Scientist")


def test_a_cv_is_told_from_a_resume():
    assert jobs.cv_kind("Tess_Moreau_Resume.pdf", "Experience") == "résumé"
    assert jobs.cv_kind("Tess_CV.pdf", "Publications ... Teaching ...") == "academic CV"
    assert jobs.cv_kind("Tess_CV.pdf", "Experience", pages=4) == "academic CV"
    assert jobs.cv_kind("Tess_CV.pdf", "Experience") == "CV"


def test_every_lead_is_gathered_identified_merged_judged_and_its_first_step_drafted(vault):
    model = Model()

    stats = jobs.sift(vault, NOW, model=model, find=find)

    identify, judge, *drafts = model.calls
    assert identify["prompt"].count("<untrusted-") == 4  # alert, recruiter, notice, receipt
    assert "Sam Okafor" not in identify["prompt"] and "Demo Day" not in identify["prompt"]
    assert "trackingId" not in identify["prompt"] and "unsubscribe" not in identify["prompt"]
    assert "never instructions" in identify["system"]
    # The judge reads the self-model, both CVs and the people known at each company.
    assert "Tess studies working memory" in judge["prompt"]
    assert "[c1] résumé, Tess_Moreau_Resume.pdf" in judge["prompt"]
    assert "[c2] academic CV, Tess_Moreau_CV.pdf" in judge["prompt"]
    assert "Owen Park: LinkedIn connection since 2023-04" in judge["prompt"]
    assert len(drafts) == 2
    assert stats | {"left_for_next_run": 0} == {
        "leads_read": 4,
        "jobs_found": 5,
        "jobs_new": 4,
        "jobs_judged": 4,
        "drafts_written": 2,
        "suggested_applied": 2,
        "left_for_next_run": 0,
    }

    found = by_company(vault)
    assert set(found) == {"Quillon Labs, Inc.", "Tallybird", "Fernway", "Halvorsen Lab"}
    # The alert and the recruiter's email are one job, the newer record's details first.
    quillon = found["Quillon Labs, Inc."]
    assert quillon["role"] == "Research Scientist, Memory Systems"
    assert quillon["place"] == "Boston, MA" and quillon["mode"] == "hybrid"
    assert quillon["link"] == "https://www.linkedin.com/jobs/view/4011223344/"
    assert quillon["contact"] == {
        "name": "Marco Velli",
        "channel": "email",
        "who": "recruiter at TalentBridge",
        "address": "marco@talentbridge.example",
    }
    assert [s["key"] for s in quillon["sources"]] == ["email/uni/recruiter", "email/uni/alert"]
    assert [s["source"] for s in quillon["sources"]] == ["recruiter", "linkedin"]
    assert quillon["sources"][0]["id"] == "email/uni/recruiter"
    # The verdict, the route, the CV and whom to contact, as judged and checked.
    assert quillon["verdict"] == "apply" and quillon["rests_on"] == ["self/identity"]
    assert quillon["route"] == {"kind": "reply", "why": "They wrote to you."}
    assert quillon["cv"] == {
        "name": "Tess_Moreau_Resume.pdf",
        "kind": "résumé",
        "made": "2026-10-01T00:00:00Z",
        "why": "Industry research.",
    }
    assert quillon["people"] == [
        {
            "name": "Marco Velli",
            "how": "recruiter at TalentBridge",
            "channel": "email",
            "role": "contact",
        },
        {
            "name": "Owen Park",
            "how": "LinkedIn connection since 2023-04, Staff Scientist at Quillon Labs",
            "channel": "linkedin",
            "role": "known",
        },
    ]
    assert quillon["step"] == {"kind": "reply", "to": "Marco Velli", "channel": "email"}
    assert quillon["draft_id"] == f"job-{quillon['id']}"
    assert quillon["errand"] == (
        "Reach Marco Velli at Quillon Labs, Inc. about the Research Scientist, Memory Systems "
        "role, by email, with my CV"
    )

    # The founder's message on Work at a Startup: a reply to paste there, and no errand.
    tally = found["Tallybird"]
    assert tally["reply_link"] == "https://www.workatastartup.com/messages/8812"
    assert tally["step"] == {"kind": "reply", "to": "Priya Raman", "channel": "other"}
    assert [p["name"] for p in tally["people"]] == ["Priya Raman", "Dana Whitlock"]
    assert tally["people"][1]["how"].startswith("Slack DM")
    assert tally["errand"] == ""

    # Skipped: no step, no draft. Its receipt suggests it was applied for.
    fern = found["Fernway"]
    assert fern["verdict"] == "skip" and fern["step"] is None and fern["draft_id"] is None
    assert fern["suggested"] == {
        "status": "applied",
        "why": "“Thank you for applying to Fernway” came on 2026-10-25.",
        "ts": "2026-10-25T10:00:00Z",
    }
    assert quillon["suggested"]["why"].startswith("You wrote to marco@talentbridge.example on")

    # The post shared to Ask and kept: Ask's draft is its first step, and the call for abstracts
    # stays with Choices.
    lab = found["Halvorsen Lab"]
    assert lab["sources"][0]["label"] == "A post you shared to Ask, 2026-10-15, and you kept it"
    assert lab["contact"]["name"] == "Ingrid Halvorsen" and lab["deadline"] == "2026-12-01"
    assert lab["cv"]["kind"] == "academic CV"
    assert lab["draft_id"] == f"{ASK_ID}-o1"

    # The drafts: in Drafts as job-<id>, for: jobs, never sent.
    out = vault / "clones" / "drafts"
    assert sorted(p.name for p in out.glob("*.md")) == sorted(
        [f"job-{quillon['id']}.md", f"job-{tally['id']}.md"]
    )
    reply = work._front((out / f"job-{quillon['id']}.md").read_text(encoding="utf-8"))
    assert reply["for"] == "jobs" and reply["status"] == "draft" and reply["kind"] == "email"
    assert reply["to"] == "Marco Velli" and reply["channel"] == "email"
    body = (out / f"job-{quillon['id']}.md").read_text(encoding="utf-8")
    assert "Subject: Re: Research Scientist role at Quillon Labs" in body
    pasted = (out / f"job-{tally['id']}.md").read_text(encoding="utf-8")
    assert "Subject:" not in pasted  # answered on the site, where it was asked
    assert "https://www.workatastartup.com/messages/8812" in work._front(pasted)["found"]
    first = next(c for c in drafts if "Marco Velli" in c["prompt"])
    assert "Research engineer: memory models in PyTorch" in first["prompt"]  # the CV chosen
    assert "<untrusted-" in first["prompt"] and "TalentBridge" in first["prompt"]
    assert "No earlier messages" not in first["prompt"]

    path = vault / "clones" / "jobs" / "jobs.json"
    assert os.name == "nt" or stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.name == "nt" or stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_re_run_reads_nothing_twice_and_changes_nothing(vault):
    jobs.sift(vault, NOW, model=Model(), find=find)
    before = load(vault)

    again = Model()
    stats = jobs.sift(vault, NOW.replace(hour=13), model=again, find=find)

    assert again.calls == []
    assert stats["leads_read"] == stats["jobs_new"] == stats["drafts_written"] == 0
    after = load(vault)
    assert after["jobs"] == before["jobs"] and after["read"] == before["read"]
    assert set(after["read"]) == {
        "email/uni/alert",
        "email/uni/recruiter",
        "email/uni/waas",
        "email/uni/receipt",
    }


def test_a_new_message_about_a_job_has_it_judged_and_drafted_again(vault):
    jobs.sift(vault, NOW, model=Model(), find=find)
    path = vault / "raw" / "email" / "uni" / "2026-11.jsonl"
    nudge = mail(
        "waas-2",
        "2026-11-03T13:00:00Z",
        "Work at a Startup",
        "no-reply@workatastartup.com",
        "Priya Raman from Tallybird sent you a message",
        WAAS.replace("Interested?", "Following up: are you still interested?"),
    )
    write_jsonl(path, [nudge])

    model = Model()
    stats = jobs.sift(vault, NOW.replace(hour=14), model=model, find=find)

    assert stats["leads_read"] == 1 and stats["jobs_new"] == 0
    assert stats["jobs_judged"] == 1 and stats["drafts_written"] == 1
    tally = by_company(vault)["Tallybird"]
    assert [s["key"] for s in tally["sources"]] == ["email/uni/waas-2", "email/uni/waas"]
    assert "Following up" in tally["excerpt"]


def test_the_users_status_holds_and_applied_is_only_suggested(vault):
    quillon_id = jobs.job_id("Quillon Labs", "Research Scientist, Memory Systems")
    tally_id = jobs.job_id("Tallybird", "Founding Research Engineer")
    fern_id = jobs.job_id("Fernway", "Machine Learning Engineer")
    write_jsonl(
        vault / "clones" / "jobs" / "status.jsonl",
        [
            {"job_id": tally_id, "action": "interested", "ts": "2026-10-25T00:00:00Z"},
            {"job_id": tally_id, "action": "closed", "ts": "2026-10-26T00:00:00Z"},
            {"job_id": fern_id, "action": "not_applied", "ts": "2026-10-28T00:00:00Z"},
            {"job_id": quillon_id, "action": "sideways", "ts": "2026-10-28T00:00:00Z"},
            {"job_id": 7, "action": "closed", "ts": "2026-10-28T00:00:00Z"},
        ],
    )
    model = Model()

    stats = jobs.sift(vault, NOW, model=model, find=find)

    assert jobs.statuses(vault / "clones" / "jobs" / jobs.STATUS) == {
        tally_id: {"status": "closed", "at": "2026-10-26T00:00:00Z", "not_applied": ""},
        fern_id: {"status": "new", "at": "", "not_applied": "2026-10-28T00:00:00Z"},
    }
    found = {j["id"]: j for j in load(vault)["jobs"]}
    assert "status" not in found[tally_id]  # the user's, in status.jsonl, not here
    # Closed: not judged, nothing drafted.
    assert found[tally_id]["verdict"] == "" and found[tally_id]["draft_id"] is None
    assert not (vault / "clones" / "drafts" / f"job-{tally_id}.md").exists()
    # Set aside after its receipt: no suggestion. Written to since it came: suggested.
    assert found[fern_id]["suggested"] is None
    assert found[quillon_id]["suggested"]["status"] == "applied"
    assert stats["suggested_applied"] == 1


def test_a_linkedin_chat_about_a_role_is_a_lead_with_its_newest_messages(vault):
    write_jsonl(
        vault / "raw" / "linkedin" / "messages" / "2026-10.jsonl",
        [
            {
                "id": "beeper:!lena/1",
                "ts": "2026-10-27T10:00:00Z",
                "conversation_id": "beeper:!lena",
                "conversation_title": "Lena Ortiz",
                "from_me": False,
                "author": "Lena Ortiz",
                "text": "Hi Tess, I'm hiring for a research scientist role at Brightwell. "
                "Would you be open to a quick chat?",
            },
            {
                "id": "beeper:!lena/2",
                "ts": "2026-10-27T11:00:00Z",
                "conversation_id": "beeper:!lena",
                "conversation_title": "Lena Ortiz",
                "from_me": True,
                "author": "Tess Moreau",
                "text": "Sure, what's the team?",
            },
            {
                "id": "beeper:!sam/1",
                "ts": "2026-10-27T10:00:00Z",
                "conversation_id": "beeper:!sam",
                "conversation_title": "Sam",
                "from_me": False,
                "author": "Sam",
                "text": "See you at the talk?",
            },
        ],
    )

    leads = jobs.gather(vault, datetime(2026, 10, 1, tzinfo=UTC), {ME}, NOW)

    (chat,) = [c for c in leads if c["kind"] == "chat"]
    assert chat["key"] == "linkedin/messages/beeper:!lena" and chat["source"] == "linkedin"
    assert chat["ts"] == "2026-10-27T11:00:00Z" and chat["id"] == "linkedin/messages/beeper:!lena/2"
    assert chat["text"].splitlines()[-1] == "[2026-10-27] me: Sure, what's the team?"
    assert chat["sender"] == "Lena Ortiz"


def test_the_jobs_among_the_weeks_choices_are_read_unless_their_record_is(vault):
    def week(evidence):
        return {
            "generated": "2026-11-01T00:00:00Z",
            "take_on": [
                {
                    "id": "c1",
                    "kind": "job",
                    "title": "Apply for the lab manager role",
                    "why": "It fits.",
                    "excerpt": "The Kim lab is hiring a lab manager.",
                    "link": "https://kimlab.example/jobs",
                    "evidence": [{"label": "Email", "id": evidence}],
                },
                {"id": "c2", "kind": "cfp", "title": "A call", "evidence": []},
            ],
        }

    choices_day = vault / "clones" / "choices" / "2026-11-01.json"
    write(choices_day, json.dumps(week("email/uni/kim")))
    since = datetime(2026, 10, 1, tzinfo=UTC)
    (lead,) = [c for c in jobs.gather(vault, since, {ME}, NOW) if c["key"].startswith("choice/")]
    assert lead["source"] == "lists" and "Kim lab is hiring" in lead["text"]
    assert lead["id"] == "email/uni/kim"

    write(choices_day, json.dumps(week("email/uni/alert")))  # read from the mail already
    assert not [c for c in jobs.gather(vault, since, {ME}, NOW) if c["key"].startswith("choice/")]


def test_a_failed_batch_leaves_its_records_to_read_next_time(vault):
    def broken(prompt, *, system=None, **kw):
        if "List each job they name" in system:
            raise RuntimeError("the model is out")
        return Model()(prompt, system=system, **kw)

    stats = jobs.sift(vault, NOW, model=broken, find=find)

    assert stats["failed"] == 1 and stats["leads_read"] == 0
    assert load(vault)["read"] == {}
    assert set(by_company(vault)) == {"Halvorsen Lab"}  # Ask's, which needs no model to read


def test_a_draft_follows_on_from_earlier_messages_with_the_person(vault, monkeypatch):
    def person(vault_, name, me, chat=None):
        if name == "Marco Velli":
            return "Their newest records with Marco Velli elsewhere: asked for your CV by email."
        return ""

    monkeypatch.setattr(jobs.research, "person", person)
    model = Model()

    jobs.sift(vault, NOW, model=model, find=find)

    marco = next(c for c in model.calls if "You draft" in c["system"] and "Marco" in c["prompt"])
    assert "asked for your CV by email" in marco["prompt"]
    assert "never introduce Tess as if they hadn't met" in marco["prompt"]
    priya = next(c for c in model.calls if "You draft" in c["system"] and "Priya" in c["prompt"])
    assert "has written with" not in priya["prompt"]
    quillon = by_company(vault)["Quillon Labs, Inc."]
    text = (vault / "clones" / "drafts" / f"{quillon['draft_id']}.md").read_text(encoding="utf-8")
    assert "It follows on from your earlier messages with Marco Velli." in text
    tally = by_company(vault)["Tallybird"]
    text = (vault / "clones" / "drafts" / f"{tally['draft_id']}.md").read_text(encoding="utf-8")
    assert "Proxenos found no earlier messages with Priya Raman" in text


def test_a_draft_the_user_touched_is_never_written_again(vault):
    jobs.sift(vault, NOW, model=Model(), find=find)
    quillon = by_company(vault)["Quillon Labs, Inc."]
    path = vault / "clones" / "drafts" / f"{quillon['draft_id']}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("status: draft", "status: sent"))
    write_jsonl(
        vault / "raw" / "email" / "uni" / "2026-11.jsonl",
        [
            RECRUITER_MAIL
            | {"id": "recruiter-2", "ts": "2026-11-03T13:00:00Z", "subject": "Re: the role"}
        ],
    )
    model = Model()

    stats = jobs.sift(vault, NOW.replace(hour=14), model=model, find=find)

    assert stats["jobs_judged"] == 1 and stats["drafts_written"] == 0
    assert "status: sent" in path.read_text(encoding="utf-8")


def test_the_page_knows_the_same_statuses():
    shown = re.search(r"export const JOB_STATUSES = \[([^\]]*)\]", TYPES.read_text())[1]
    assert re.findall(r'"(\w+)"', shown) == list(jobs.STATUSES)
    actions = re.search(r"export const JOB_ACTIONS = \[([^\]]*)\]", TYPES.read_text())[1]
    assert re.findall(r'"(\w+)"', actions.replace("...JOB_STATUSES", "")) == ["not_applied"]


def test_only_mail_that_applies_suggests_applied():
    assert jobs._application(SENT_MAIL, SENT_MAIL["subject"])  # "My résumé is attached"
    reply = SENT_MAIL | {"body": "It's a busy month; could I come back to you at its end?"}
    reply["body_new"] = reply["body"]
    assert not jobs._application(reply, reply["subject"])  # answering a recruiter isn't applying
    assert jobs._application(reply | {"attachments": ["Tess_Moreau_CV.pdf"]}, reply["subject"])
