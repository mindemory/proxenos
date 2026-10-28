"""Where the user's health care stands: a timeline, what's open, what to say, and a visit brief.

Each run reads the last 120 days (`--days`) of the user's own records and keeps, in code, only
the ones about getting care: email from every account, calendar events (also the next 60 days),
WhatsApp (their note-to-self chat too, where they log things), notes, Drive documents, Keep,
Google Tasks and Slack direct messages. A record is kept when its words, the first 6,000
characters of a long one, score high enough on a table of health-admin terms: visits, tests,
referrals, insurance, bills, prescriptions, records, portals, forms and symptoms.

- Terms just as common in research or daily life (MRI, lab, a Department of Neurology, patients,
  a referral, a statement) count only when the record doesn't read as research: a paper's
  affiliations name hospitals, but most of its words are research.
- Symptoms count in the user's own words (their messages, mail, log, Keep, tasks, calendar),
  and in anyone else's only as an ambiguous term.
- The user's own messages, logs and calendar need a score of 2, everything else 3. Promotions
  and social mail need more, mail from a health organization less; spam and trash are skipped.
- A chat message that clears the bar with a strong match brings the few messages right around
  it in the same chat, within half an hour: the question it answers, the answer to it.

Only those records go to the model, oldest first, up to about 300k characters. When there are
more, relevance (the score, halved with each month of age) decides what stays, so the weeks
that matter now always fit. Before they go, people in chats become "contact 1", "contact 2";
phone numbers, long account, member and claim numbers, email addresses and links are blanked;
and a long text is cut to the passages around its health terms. One request, at high effort,
returns what clones/care/care.json holds:

- summary: three to five sentences on where things stand;
- timeline: dated events (symptom, visit, test, result, referral, call, message, bill, claim,
  records, prescription), each with the organization or role involved and its evidence;
- open_items: what is unresolved, who it's waiting on, the next step and any due date;
- scripts: what to say on a call, in an email, a portal message or a form, for open items;
- visit_brief: one printable page of markdown for the next clinician.

The model is told to state only what the records say, never diagnose or speculate, mark what's
uncertain, and name other people only by role or organization. Numbers are blanked again in what
it returns. Evidence is kept as memory-index ids ("email/<account>/<message id>"), and `cited`
gives the source and time of each, so the page can show and open them without their text.
`records` counts what was sent from each source. The file is 0600 in a 0700 folder.

The page marks items done, waiting or not relevant in clones/care/feedback.jsonl. Done and not
relevant close an item for good, as the tasks clone does: closed.json remembers them, the model is
told not to bring them back, and anything that comes back anyway is dropped. Waiting holds an item
as waiting until a record newer than the mark is cited for it. Done items leave the list 30 days
later. `--dry-run` counts what would be sent, by source, without the model or any file.
"""

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from proxenos import llm
from proxenos.config import env

DAYS = 120
AHEAD_DAYS = 60  # calendar events this far ahead count too: the appointments still to come
MAX_CHARS = 300_000  # about 75k tokens of records; past this the least relevant are cut
CHAT_CHARS = 1500
MAIL_CHARS = 4000
DOC_CHARS = 8000
EXCERPT_RADIUS = 400  # characters kept on each side of a matched term in a long text
THRESHOLD = 3  # the score a record needs to be sent
OWN_THRESHOLD = 2  # for the user's own notes, logs, chats and calendar
NEAR_MINUTES = 30  # chat messages this close to a strong match come along with it
NEAR_BEFORE, NEAR_AFTER = 2, 3
HALF_LIFE_DAYS = 30  # under the cap, a record's relevance halves with each month of age
DONE_KEEP = timedelta(days=30)  # how long a done item stays on the list
CLOSED_KEEP = timedelta(days=180)  # how long a closed item is remembered, at least

SOURCES = ("email", "calendar", "whatsapp", "slack", "notes", "keep", "gtasks", "drive")
TIMELINE_KINDS = (
    "symptom",
    "visit",
    "test",
    "result",
    "referral",
    "call",
    "message",
    "bill",
    "claim",
    "records",
    "prescription",
)
ITEM_KINDS = (
    "appointment",
    "referral",
    "bill",
    "claim",
    "records",
    "prescription",
    "form",
    "follow_up",
    "question",
)
WAITING_ON = ("me", "provider", "insurer", "other")
STATUSES = ("open", "waiting", "done")
SCRIPT_KINDS = ("call", "email", "portal_message", "form")
ACTIONS = ("done", "waiting", "not_relevant")
_CLOSING = ("done", "not_relevant")
_MARKED = {"done": "done", "not_relevant": "not relevant"}
SELF_FILES = ("identity", "voice")

# ── The filter ──────────────────────────────────────────────────────────────
#
# (pattern, weight, ambiguous). Each term counts once per record. An ambiguous term is as common
# in research or everyday life as in care (an MRI session, a Department of Neurology, a lab, a
# job referral, a credit card statement), so it counts only when the record doesn't read as
# research. None marks a symptom: certain in the user's own words, ambiguous in anyone else's.
# Patterns are matched without case unless they start with (?-i): abbreviations such as ER, ENT,
# CT and PCP count only in capitals.

_TERMS: list[tuple[str, int, bool | None]] = [
    # Where care happens
    (r"urgent[ -]?care", 3, False),
    (r"emergency (room|department|dept)", 3, False),
    (r"(?-i:\b(the|to|in|at|from) ER\b)|\bER (visit|doctor|nurse|bill)", 3, False),
    (r"(?-i:\bER\b)", 2, True),
    (r"primary[ -]care", 3, False),
    (r"(?-i:\bPCPs?\b)", 3, False),
    (r"\bneurologist\b|\bneuro (appt|appointment|consult|visit|referral)", 3, False),
    (r"\bneurolog(y|ists|ical)\b", 2, True),
    (r"(?-i:\bENT\b)|otolaryngolog|ear,? nose,? (and|&) throat", 3, True),
    (r"cardiolog|\bcardiac\b|audiolog|\bhearing test|\bvestibular\b", 2, True),
    (r"ophthalmolog|optometrist|\beye exam|endocrinolog|dermatolog|gastroenterolog", 2, True),
    (r"rheumatolog|psychiatrist|\bradiolog|\bphysical therap|\bphysiotherap", 2, True),
    (r"\bdentist|\bdental\b", 2, True),
    (r"\bclinic\b|\bclinics\b|\bhospital\b|\bhospitali[sz]ed\b", 2, True),
    (r"\bdoctors?\b|\bphysicians?\b|\bdoc's\b|\bnurses?\b|\bnurse practitioner", 2, True),
    (r"(?-i:\bDr\.? [A-Z][a-z]+)", 2, True),
    (r"\bspecialists?\b|\bpatients?\b", 2, True),
    (r"\bnew patient\b|\bpatient (intake|registration|account)", 3, False),
    (r"(your|my|the) (care team|provider's office|doctor's office)", 3, False),
    (r"telehealth|telemedicine|video visit|\be-?visit\b|teladoc|zocdoc|one medical", 3, False),
    (r"\bnurse (line|advice)", 3, False),
    # Visits and appointments
    (r"\bappointments?\b|\bappts?\b", 1, True),
    (r"follow[- ]up (appointment|visit|appt)", 3, False),
    (r"after[- ]visit summary|visit summary|discharge (summary|instructions|papers)", 3, False),
    (r"\bcheck-?up\b|\bphysical exam|\bannual physical", 2, True),
    (r"\bwait ?list(ed)?\b|\bwaiting list\b", 1, True),
    # Tests and results
    (r"\bmri\b", 3, True),
    (r"\bmy mri\b|\bmri (report|results?|order|appointment)|\bmri with(out)? contrast", 3, False),
    (r"(?-i:\bCT\b) (scan|of the|of my)|\bcat scan\b|\bct scan\b", 3, False),
    (r"\bx-?rays?\b|\bultrasound\b", 2, True),
    (r"\bblood ?work\b|\bblood (test|draw|panel)s?\b", 3, False),
    (r"\blab (work|results?|orders?|tests?)\b|\blabs\b", 2, True),
    (r"(?-i:\b(CBC|TSH|A1C|HbA1c)\b)|\bvitamin (b12|d) (level|test)|\bferritin\b", 3, True),
    (r"(?-i:\b(ECG|EKG)\b)|electrocardiogram|echocardiogram|\bholter\b", 2, True),
    (r"tilt[- ]table|orthostatic|blood pressure", 2, True),
    (r"\btest results?\b|\bresults? (are|were|came) (in|back)", 2, True),
    (r"\bdiagnos(is|ed|tic)\b|\bruled out\b|\brule out\b", 2, True),
    (r"\bscan\b", 1, True),
    # Referrals
    (r"\breferrals?\b|\breferred (me|you|to)\b|\brefer (me|you) to\b", 2, True),
    # Insurance and benefits
    (r"\binsurance\b|\binsurer\b|\bpolicyholder\b|\bmember services\b", 2, True),
    (r"health (insurance|plan|benefits)|medical (insurance|plan|coverage)", 3, False),
    (r"(?-i:\bEOBs?\b)|explanation of benefits", 3, False),
    (r"\bco-?pays?\b|\bco-?payments?\b|\bcoinsurance\b|\bdeductibles?\b|out-of-pocket", 3, False),
    (r"\bin-network\b|\bout-of-network\b", 3, False),
    (r"prior auth|pre-?authori[sz]ation|pre-?certification", 3, False),
    (r"\bclaims?\b", 1, True),
    (r"(insurance|medical) claim|claim (number|was denied|was approved|has been)", 3, False),
    (r"\baetna\b|\bcigna\b|united ?healthcare|blue cross|blue shield|\bbcbs\b", 3, False),
    (r"anthem (blue|health|insurance)|oscar health|harvard pilgrim|emblem ?health", 3, False),
    (r"\boptum\b|express scripts|caremark|oxford health|\bwellfleet\b", 3, False),
    (r"\bhumana\b|\bkaiser\b|\bmedicaid\b|\bmedicare\b|\buhc\b", 2, True),
    (r"open enrollment|benefits enrollment|health savings account", 3, False),
    (r"(?-i:\b(HSA|FSA)\b)", 2, True),
    (r"\bbenefits\b|\bappeals?\b", 1, True),
    # Bills
    (r"medical bill|hospital bill|itemi[sz]ed (bill|statement)|\bsuperbill\b", 3, False),
    (r"\bguarantor\b|dates? of service|patient (balance|statement)", 3, False),
    (r"financial assistance|charity care|payment plan", 2, True),
    (r"\bbills?\b|\bbilling\b|\binvoices?\b|\bstatements?\b", 1, True),
    (r"(balance|amount|payment) (due|owed)|\bpay (your|my) bill\b", 1, True),
    # Prescriptions
    (r"\bprescriptions?\b|\bprescribed\b|\bpharmacy\b|\bpharmacist\b|\brefills?\b", 3, True),
    (r"(?-i:\bRx\b)|\bmedications?\b|\bmeds\b|\b\d+ ?mg\b|\bdosage\b", 2, True),
    (r"\bcvs\b|\bwalgreens\b|rite ?aid|\bduane reade\b", 2, True),
    # Records, forms and portals
    (r"mychart|my chart|patient portal|follow ?my ?health|healthelife", 3, False),
    (r"medical records?|records request|release of information", 3, False),
    (r"authori[sz]ation (to|for) (release|disclose)|\bhipaa (form|authori[sz]ation)", 3, False),
    (r"health records?|release form|request(ing)? (my|the) records|\bhipaa\b", 2, True),
    (r"\bfax(ed|es|ing)?\b", 2, True),
    (r"\bforms?\b", 1, True),
    (r"(doctor's|doctors|medical) note|sick (leave|day|note)|medical leave|out sick", 3, False),
    # Wellness and coaching
    (r"health coach|wellness coach|health coaching", 3, False),
    (r"\bwellness\b|employee assistance", 1, True),
    # Symptoms and how the user is
    (r"\bdizz(y|iness)\b|\bvertigo\b|light-? ?headed|\bwoozy\b|off[- ]balance", 3, None),
    (r"\bpresyncope\b|\bsyncope\b|\bfaint(ed|ing)\b|\bfelt faint\b|\bpassed out\b", 3, None),
    (r"\bnystagmus\b|\bbppv\b|meniere|\btinnitus\b|\bear (pressure|ringing|fullness)", 3, None),
    (r"brain fog|blurr?(y|ed) vision|double vision|palpitations|chest pain", 3, None),
    (r"health (issue|issues|problem|problems|scare|stuff|update)", 3, None),
    (r"medical (issue|issues|reasons|emergency|appointment|stuff)", 3, None),
    (r"\bmigraines?\b|\bheadaches?\b|\bnause(a|ous|ated)\b|\bvomit", 2, None),
    (r"\bfatigue\b|\bfatigued\b|\bexhaust(ed|ion)\b|\bnumbness\b|\btingling\b", 2, None),
    (r"\bsymptoms?\b", 2, None),
    (r"(feel|feeling|felt) (sick|unwell|awful|terrible|weak|off|worse|better)", 2, None),
    (r"not feeling (well|great|good)|under the weather", 2, None),
    (r"get well|feel better soon|hope you('re| are) feeling", 2, None),
    (r"\bsick\b|\bunwell\b|\bspinning\b|\bimbalance\b|\btired\b", 1, None),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), w, a) for p, w, a in _TERMS]
# For scoring, the same patterns run on the text lowered once, which is faster than matching
# without case. Those that need capitals keep running on the text as written.
_CASED = [("(?-i:" in p, re.compile(p, re.IGNORECASE if "(?-i:" in p else 0)) for p, _, _ in _TERMS]

# Words that mark research and academic writing, where scans, labs, departments, patients and
# referrals mean something else. A record reads as research when it has at least two different
# ones and no fewer than it has health terms: a paper's affiliations name hospitals and
# departments, but its words are mostly research, while "missed lab meeting, I was at urgent
# care" is not a paper.
_RESEARCH = re.compile(
    r"\b(f-?mri|bold signal|voxels?|participants?|subjects|scanner|scanning session|irb|"
    r"protocol|datasets?|preprint|manuscript|grants?|conference|poster|lab meeting|lab|"
    r"seminar|journal club|journal|reviewers?|arxiv|cortex|cortical|neurons?|neural|eeg|"
    r"stimul(us|i)|experiment(s|al)?|analys(is|es)|pilot|recruit(ing|ment)?|cohort|"
    r"abstract|hypothes(is|es)|postdoc(toral)?|faculty|professor|students?|thesis|"
    r"dissertation|papers?|models?|modeling|simulations?|et al|doi|universit(y|ies)|"
    r"proceedings|references|figure|fig|supplementary|methods|neuroscience|cognitive|"
    r"psycholog(y|ical)|behaviou?ral|significant(ly)?|correlat(ed|ion|ions)|regression|"
    r"trials?|department of|school of medicine|phd|syllabus|lecture|code|github|python|"
    r"matlab|network models?|working memory|fellowship)\b",
    re.IGNORECASE,
)
_RESEARCH_HITS = 2
SCORE_CHARS = 6000  # a long text is scored on its start: what a document or mail is about
# Labels on mail that isn't to the user as a person. Spam and trash are never read; promotions,
# social and forum mail need a strong match.
_SKIP_LABELS = {"SPAM", "TRASH"}
_BULK_PENALTY = {"CATEGORY_PROMOTIONS": 3, "CATEGORY_SOCIAL": 2, "CATEGORY_FORUMS": 2}
# A sender whose name or domain says it's a health organization.
_HEALTH_SENDER = re.compile(
    r"health|medical|medicine|hospital|clinic|pharmacy|mychart|physicians|radiology|"
    r"\blabs?\b|quest ?diagnostics|labcorp|insurance|benefits",
    re.IGNORECASE,
)
_SLACK_EVENTS = re.compile(
    r"(channel|group)_(join|leave|topic|purpose|name|archive|unarchive)|(un)?pinned_item"
)
_MENTION = re.compile(r"<@(\w+)(?:\|[^>]*)?>")

# What never leaves in a record or comes back in an answer: phone and fax numbers, long account,
# member, claim and record numbers, card and social security numbers, email addresses and links.
_URL = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+(?:\.[\w-]+)+)\b")
_PHONE = re.compile(r"(?<![\w.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?![\w])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d{4}[ -]){2,3}\d{4}\b")
_LONG_NUMBER = re.compile(r"\b[A-Za-z]{0,4}-?\d{6,}[A-Za-z]{0,3}\b")
_CONTACT = re.compile(r"\bcontacts? \d+\b", re.IGNORECASE)

_REF = re.compile(r"r\d+")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_NEW = re.compile(r"new-?\d*", re.IGNORECASE)

_SYSTEM = """\
You help {person} get through the health-care system: appointments, referrals, tests, \
results, bills, insurance claims, prescriptions, records requests, forms, phone calls and \
faxes. You get the health-related records from their own mail, calendar, chats, notes and \
documents over the last {days} days (and calendar events still to come), picked out by \
keyword, and their list of open items as it stood after the last run. Return where things \
stand, all of it, as JSON.

- summary: three to five plain sentences: where things stand now, what is pending and on whom, \
and what {person} needs to do next.
- timeline: what happened, oldest first, one entry per event: a symptom they noted, a visit, \
a test, a result, a referral, a call, a message, a bill, a claim, a records request, a \
prescription. date: YYYY-MM-DD, the day it happened (or will, for an appointment booked ahead). \
title: a few words. detail: one or two sentences of what the records say about it. with: the \
clinic, organization or role involved ("urgent care clinic", "emergency department", "primary \
care office", "insurer", "pharmacy"), or "". evidence: the [r..] refs that show it.
- open_items: everything still unresolved: an appointment to book or keep, a referral to chase, \
a bill to pay or question, a claim, a records request, a prescription, a form, a follow-up, a \
question that needs an answer. id: its id from the current list if it's there, else "new-1", \
"new-2", and so on. title: a short imperative ("Get the MRI report sent to primary care"). \
waiting_on: me when the next move is {person}'s, provider when a clinic or office owes them \
something, insurer, or other. next_step: the one concrete next action. due: YYYY-MM-DD only \
when the records state or clearly imply a date, else "". status: open; waiting when they've done \
their part; done when the records show it settled. evidence: the [r..] refs.
- scripts: for open items that need a call, an email, a patient portal message or a form, what \
to say. item_id: the item's id (as given in open_items). kind: call, email, portal_message or \
form. title: a few words. body: ready to use as written, in {person}'s voice: short, polite and \
specific. Who they are, what happened and when, and exactly what they're asking for. A call \
script is what to say, then the questions to ask. Leave [placeholders in brackets] for what \
the records don't give: date of birth, member ID, claim number, a name.
- visit_brief: markdown for one printed page that {person} can hand to the next clinician, \
written in the first person as {person}. No title line; ## headings for: Presenting problem \
(two lines at most: what, since when); Timeline (dated bullets: onset, visits, tests); Tests \
and results (each with its date and the result exactly as their records state it, or "result \
not in my records"); Ruled out (only what a clinician is recorded as having ruled out, else \
"Nothing recorded"); Current symptoms and how they affect daily life and work; Medications \
(only those the records mention, else "None recorded"); Questions to ask (three to six). Keep \
it to one page.

Rules:
- State only what the records say. Never diagnose, never say what a symptom or result might \
mean, never suggest a cause or a treatment. Report results in the records' own words.
- Mark anything uncertain in place: "(unclear from the records)", "(date not confirmed)".
- No phone or fax numbers, no account, member, policy, claim or record numbers, and no street \
addresses anywhere in the answer. Use [placeholders].
- Other people appear only as roles or organizations ("the neurologist", "a family member", \
"the billing office"), never by name. People in chats are shown as "contact 1", "contact 2": \
never repeat those labels either; say "a contact" or their role if the records make it clear.
- Some records match by accident: research (scans, labs, participants), newsletters, ads, \
someone else's health. Leave out anything that isn't about {person}'s own care.
- Every item on the current list comes back, changed or not. Never bring back an item \
{person} closed, however it's worded.
- Refer to them as {person} and don't assume pronouns."""

_PROMPT = """\
Today is {today}. Times are local.

## Open items as they stood after the last run
{current}
{closed}
## Records, oldest first
From the last {days} days, and calendar events up to {ahead} days ahead. Each starts with its \
[r..] ref, the time, where it's from and who wrote it ("me" is {person}).
{cut}
{records}"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "kind": {"type": "string", "enum": list(TIMELINE_KINDS)},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "with": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["date", "kind", "title", "detail", "with", "evidence"],
                "additionalProperties": False,
            },
        },
        "open_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": list(ITEM_KINDS)},
                    "waiting_on": {"type": "string", "enum": list(WAITING_ON)},
                    "next_step": {"type": "string"},
                    "due": {"type": "string"},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "title",
                    "kind",
                    "waiting_on",
                    "next_step",
                    "due",
                    "status",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "scripts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "kind": {"type": "string", "enum": list(SCRIPT_KINDS)},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["item_id", "kind", "title", "body"],
                "additionalProperties": False,
            },
        },
        "visit_brief": {"type": "string"},
    },
    "required": ["summary", "timeline", "open_items", "scripts", "visit_brief"],
    "additionalProperties": False,
}


# ── The run ─────────────────────────────────────────────────────────────────


def care(
    vault: Path, days: float = DAYS, now: datetime | None = None, dry_run: bool = False
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = vault / "clones" / "care"
    found = gather(vault, now - timedelta(days=days), now, now + timedelta(days=AHEAD_DAYS))
    text, refs, cut = render(found, now)
    by_source = Counter(r["source"] for r in refs.values())
    if dry_run:
        return {**{s: by_source[s] for s in SOURCES}, "records": len(refs), "chars": len(text)}

    doc = _load(out / "care.json")
    items = {i["id"]: i for i in doc.get("open_items") or [] if _valid_item(i)}
    closed = _load_closed(out / "closed.json")
    verdicts = _feedback(out / "feedback.jsonl")
    # What the user closed on the page is closed for good, whatever the records say. Marking an
    # item waiting after closing it opens it again.
    for key, (action, ts) in verdicts.items():
        if action == "waiting":
            if key in closed and closed[key]["action"] and closed[key]["closed_at"] <= ts:
                del closed[key]
        elif key in items:
            closed[key] = _closed_entry(items[key], action, ts)
        elif key in closed:
            closed[key] |= {"action": action, "closed_at": ts}
    mine = {k for k, entry in closed.items() if entry["action"]}

    result = {
        "summary": doc.get("summary") or "",
        "timeline": doc.get("timeline") or [],
        "scripts": doc.get("scripts") or [],
        "visit_brief": doc.get("visit_brief") or "",
    }
    cited = dict(doc.get("cited") or {})
    new = 0
    if refs:
        shown = {k: item for k, item in items.items() if k not in mine}
        answer = llm.ask(
            _PROMPT.format(
                today=now.astimezone().strftime("%A %Y-%m-%d, %H:%M (UTC%z)"),
                current="\n".join(map(_item_line, shown.values())) or "Empty: nothing yet.",
                closed=_closed_text({k: closed[k] for k in mine if k in closed}),
                days=f"{days:g}",
                ahead=AHEAD_DAYS,
                person=env("NAME", "the person"),
                cut="(Only the most relevant and recent fit; the rest were left out.)\n"
                if cut
                else "",
                records=text,
            ),
            system=_system(vault / "self", days),
            schema=_SCHEMA,
            effort="high",
        )
        result, updated, new = apply(answer, shown, refs, _closed_keys(closed, mine))
        items = {k: item for k, item in items.items() if k in mine} | updated
        cited = {ref["id"]: {"source": ref["source"], "ts": ref["ts"]} for ref in refs.values()} | {
            k: v for k, v in cited.items() if isinstance(v, dict)
        }

    items = _settle(items, closed, verdicts, cited, now)
    live = {k for k, i in items.items() if i["status"] != "done"}
    scripts = [s for s in result["scripts"] if s.get("item_id") in live]
    used = {e for i in items.values() for e in i["evidence"]}
    used |= {e for t in result["timeline"] for e in t.get("evidence", [])}
    remember = max(CLOSED_KEEP, timedelta(days=days) + DONE_KEEP)
    closed = {k: e for k, e in closed.items() if e["closed_at"] >= _iso(now - remember)}
    _write_json(
        out / "care.json",
        {
            "generated": _iso(now),
            "summary": result["summary"],
            "timeline": result["timeline"],
            "open_items": _sorted(items.values()),
            "scripts": scripts,
            "visit_brief": result["visit_brief"],
            "cited": {k: v for k, v in cited.items() if k in used},
            "records": {s: by_source[s] for s in SOURCES if by_source[s]},
        },
    )
    _write_json(out / "closed.json", closed)
    counts = {s: sum(i["status"] == s for i in items.values()) for s in STATUSES}
    return {
        "records": len(refs),
        "timeline_events": len(result["timeline"]),
        **counts,
        "new": new,
        "scripts": len(scripts),
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--days", type=float, default=DAYS, help="how many days back to read (default 120)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="count what would be sent; no model, no files"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return care(vault, days=args.days, dry_run=getattr(args, "dry_run", False))


# ── Gathering ───────────────────────────────────────────────────────────────


def gather(vault: Path, start: datetime, now: datetime, end: datetime) -> list[dict]:
    """Every health-admin record from `start` to `now`, and calendar events up to `end`, each
    {id, source, ts, where, sender, title, text, score, terms, own}. id is the memory index's
    id for it ("<raw folder>/<record id>"). A chat message near a strong match comes along with
    `near` set to the match's id."""
    since, today, until = _iso(start), _iso(now), _iso(end)
    people, groups = _Names("contact"), _Names("group")
    return [
        *_email(vault, since, today),
        *_calendar(vault, since, until),
        *_whatsapp(vault, since, today, people, groups),
        *_slack(vault, since, today, people),
        *_documents(vault, since, today),
    ]


def score(text: str, *, own: bool = False, penalty: int = 0) -> tuple[int, list[str]]:
    """How strongly a record's words say it's about getting care, and the terms that counted.
    Ambiguous terms count only when the record doesn't read as research, and symptoms count
    as ambiguous except in the user's own words."""
    hits = []
    lowered = text.lower()
    for (cased, pattern), (_, weight, ambiguous) in zip(_CASED, _TERMS, strict=True):
        if match := pattern.search(text if cased else lowered):
            hits.append((weight, (not own) if ambiguous is None else ambiguous, match[0].lower()))
    if not hits:
        return -penalty, []
    research = {match[0].lower() for match in _RESEARCH.finditer(text)}
    as_research = len(research) >= max(_RESEARCH_HITS, len(hits))
    counted = [
        (weight, term) for weight, ambiguous, term in hits if not (ambiguous and as_research)
    ]
    return sum(weight for weight, _ in counted) - penalty, [term for _, term in counted]


def keep(record: dict) -> bool:
    return record["score"] >= (OWN_THRESHOLD if record["own"] else THRESHOLD)


class _Names:
    """Stable stand-ins for the people (or groups) in chats: "contact 1", "contact 2", in order
    of first appearance. The model never sees a chat partner's name or number."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.ids: dict[str, int] = {}

    def __call__(self, key: str | None) -> str:
        if not key:
            return f"a {self.label}"
        return f"{self.label} {self.ids.setdefault(key, len(self.ids) + 1)}"


def _email(vault: Path, since: str, until: str) -> list[dict]:
    found = []
    for account in sorted(p for p in (vault / "raw" / "email").glob("*") if p.is_dir()):
        for r in _records(account, since, until):
            labels = {
                str(label).upper().lstrip("\\").replace(" ", "_")
                for label in r.get("gmail_labels") or []
            }
            if labels & _SKIP_LABELS:
                continue
            body = r.get("body_new") or r.get("body") or ""
            subject = r.get("subject") or ""
            if not (body or subject):
                continue
            own = bool(r.get("from_me"))
            if own:
                to = sorted({d for a in r.get("to") or [] if (d := _domain(a))})
                sender = "me" + (f" (to {', '.join(to[:4])})" if to else "")
            else:
                name = " ".join(str(r.get("from_name") or "").split())
                domain = _domain(r.get("from_address"))
                sender = f"{name} ({domain})" if name and domain else name or domain or "unknown"
            penalty = max((_BULK_PENALTY.get(label, 0) for label in labels), default=0)
            if not own and _HEALTH_SENDER.search(sender):
                penalty -= 2
            record = _record(
                f"email/{account.name}/{r['id']}",
                "email",
                r["ts"],
                f"email ({account.name})",
                sender,
                subject,
                body,
                own,
                MAIL_CHARS,
                penalty,
            )
            if record:
                found.append(record)
    return found


def _calendar(vault: Path, since: str, until: str) -> list[dict]:
    found = []
    for stream in sorted(p for p in (vault / "raw" / "calendar").glob("*") if p.is_dir()):
        for r in _records(stream, since, until):
            parts = []
            if str(r.get("status") or "").upper() == "CANCELLED":
                parts.append("(cancelled)")
            if r.get("all_day"):
                parts.append(f"All day, {r.get('start') or r['ts'][:10]}.")
            if r.get("location"):
                parts.append(f"Where: {r['location']}")
            parts.append(r.get("description") or "")
            record = _record(
                f"calendar/{stream.name}/{r['id']}",
                "calendar",
                r["ts"],
                "calendar event",
                "",
                r.get("summary") or "",
                "\n".join(p for p in parts if p),
                True,
                CHAT_CHARS,
            )
            if record:
                found.append(record)
    return found


def _whatsapp(vault: Path, since: str, until: str, people: _Names, groups: _Names) -> list[dict]:
    chats: dict[str, list[dict]] = defaultdict(list)
    for r in _records(vault / "raw" / "whatsapp" / "messages", since, until):
        if r.get("text") or r.get("caption"):
            chats[r["chat_id"]].append(r)
    person = env("NAME", "").strip().casefold()
    found = []
    for chat_id, messages in chats.items():
        direct = messages[0].get("chat_type") == "direct"
        chat_name = str(messages[0].get("chat_name") or "").strip().casefold()
        only_mine = all(m.get("from_me") for m in messages)
        noted = direct and (
            bool(person and chat_name == person)
            or "(you)" in chat_name
            or (only_mine and len(messages) >= 3)
        )
        if noted:
            where = "WhatsApp, note to self"
        elif direct:
            where = f"WhatsApp, chat with {people('wa:' + chat_id)}"
        else:
            where = f"WhatsApp, {groups('wa:' + chat_id)}"
        rows = []
        for m in messages:
            own = bool(m.get("from_me")) or noted
            if own:
                sender = "me"
            elif direct:
                sender = people("wa:" + chat_id)
            else:
                sender = people("wa:" + str(m.get("sender_id") or m.get("sender_name") or ""))
            text = m.get("text") or m.get("caption")
            key = f"whatsapp/messages/{m['id']}"
            rows.append(
                _record(
                    key, "whatsapp", m["ts"], where, sender, "", text, own, CHAT_CHARS, chat=True
                )
            )
        found += _with_neighbours(rows)
    return found


def _slack(vault: Path, since: str, until: str, people: _Names) -> list[dict]:
    found = []
    for directory in sorted((vault / "raw" / "slack").glob("*/messages")):
        team = directory.parent.name
        channels: dict[str, list[dict]] = defaultdict(list)
        for r in _records(directory, since, until):
            if r.get("channel_type") not in ("dm", "group_dm") or not r.get("text"):
                continue
            if not _SLACK_EVENTS.fullmatch(r.get("subtype") or ""):
                channels[r["channel_id"]].append(r)

        def mention(match: re.Match) -> str:
            return "@" + people("sl:" + match[1])

        for channel_id, messages in channels.items():
            direct = messages[0].get("channel_type") == "dm"
            partner = next((m.get("user_id") for m in messages if not m.get("from_me")), None)
            label = f"direct messages with {people('sl:' + str(partner or channel_id))}"
            where = f"Slack ({team}), " + (label if direct else "group direct message")
            rows = []
            for m in messages:
                own = bool(m.get("from_me"))
                sender = "me" if own else people("sl:" + str(m.get("user_id") or channel_id))
                text = _MENTION.sub(mention, m["text"])
                key = f"slack/{team}/messages/{m['id']}"
                rows.append(
                    _record(
                        key, "slack", m["ts"], where, sender, "", text, own, CHAT_CHARS, chat=True
                    )
                )
            found += _with_neighbours(rows)
    return found


def _documents(vault: Path, since: str, until: str) -> list[dict]:
    """Notion and Obsidian pages and tasks, Keep notes, Google Tasks and Drive documents."""
    raw = vault / "raw"
    found = []
    streams = [
        ("notes", raw / "notes" / "pages", "note", False),
        ("notes", raw / "notes" / "tasks", "Notion task", True),
        ("keep", raw / "keep" / "notes", "Keep note", True),
        ("gtasks", raw / "gtasks" / "tasks", "Google task", True),
        ("drive", raw / "drive" / "docs", "Drive document", False),
    ]
    for source, directory, where, own in streams:
        folder = directory.relative_to(raw).as_posix()
        for r in _records(directory, since, until):
            if r.get("trashed"):
                continue
            title, text = str(r.get("title") or ""), _document_text(source, r)
            key = f"{folder}/{r['id']}"
            record = _record(key, source, r["ts"], where, "", title, text, own, DOC_CHARS)
            if record:
                found.append(record)
    return found


def _document_text(source: str, r: dict) -> str:
    if source == "gtasks":
        state = [f"list {r['list']}" if r.get("list") else "", str(r.get("status") or "")]
        if r.get("due"):
            state.append(f"due {str(r['due'])[:10]}")
        state = [s for s in state if s]
        return "\n".join(
            p for p in (r.get("notes") or "", f"({'; '.join(state)})" if state else "") if p
        )
    if source == "keep":
        labels = ", ".join(map(str, r.get("labels") or []))
        return str(r.get("text") or "") + (f"\n(labels: {labels})" if labels else "")
    parts = [str(r.get("text") or "")]
    properties = r.get("properties")
    if isinstance(properties, dict):
        parts.append("; ".join(f"{k}: {v}" for k, v in properties.items() if v not in (None, "")))
    if source == "notes" and (r.get("status") or r.get("due")):
        parts.append(f"(status: {r.get('status') or 'none'}; due: {r.get('due') or 'none'})")
    return "\n".join(p for p in parts if p)


def _record(
    key: str,
    source: str,
    ts: str,
    where: str,
    sender: str,
    title: object,
    text: object,
    own: bool,
    limit: int,
    penalty: int = 0,
    chat: bool = False,
) -> dict | None:
    """One record as the prompt shows it, scored, or None when it doesn't clear the bar. A
    chat message is always returned, since it may come along as context for one that does."""
    title = " ".join(str(title or "").split())
    text = str(text or "").strip()
    if not (title or text):
        return None
    scored = f"{title}\n{text[:SCORE_CHARS]}" + (f"\n{sender}" if source == "email" else "")
    points, terms = score(scored, own=own, penalty=penalty)
    record = {
        "id": key,
        "source": source,
        "ts": ts,
        "where": where,
        "sender": sender,
        "own": own,
        "score": points,
        "terms": terms,
    }
    if not chat and not keep(record):
        return None
    return record | {"title": _redact(title)[:300], "text": _excerpt(_redact(text), limit)}


def _with_neighbours(rows: list[dict | None]) -> list[dict]:
    """The messages of one chat that clear the bar, and the few right around each strong one,
    within NEAR_MINUTES: the question a reply answers, the answer to a question."""
    found = sorted((r for r in rows if r), key=lambda r: (r["ts"], r["id"]))
    picked: dict[int, dict] = {}
    window = timedelta(minutes=NEAR_MINUTES)
    for n, row in enumerate(found):
        if not keep(row):
            continue
        picked[n] = row
        if row["score"] < THRESHOLD:
            continue
        at = _time(row["ts"])
        around = [
            *range(max(0, n - NEAR_BEFORE), n),
            *range(n + 1, min(len(found), n + 1 + NEAR_AFTER)),
        ]
        for m in around:
            if m not in picked and abs(_time(found[m]["ts"]) - at) <= window:
                picked[m] = {**found[m], "near": row["id"]}
    return [picked[n] for n in sorted(picked)]


# ── The prompt ──────────────────────────────────────────────────────────────


def render(
    records: list[dict], now: datetime, limit: int = MAX_CHARS
) -> tuple[str, dict[str, dict], bool]:
    """The records as prompt text, oldest first, the record behind each [r..] ref, and whether
    any were left out. Over `limit` characters, the least relevant go first. Relevance is the
    score, halved for every HALF_LIFE_DAYS of age, so the weeks that matter now always fit
    before older history; upcoming events count as today. A chat message kept for context
    ranks just below its match."""
    by_id = {r["id"]: r for r in records}

    def weight(r: dict) -> float:
        anchor = by_id.get(r.get("near") or "", r)
        age = max(0.0, (now - _time(r["ts"])).total_seconds() / 86400)
        points = min(max(anchor["score"], 1), 12)
        return points * 0.5 ** (age / HALF_LIFE_DAYS) - (0.01 if r.get("near") else 0.0)

    ranked = sorted(records, key=lambda r: (weight(r), r["ts"]), reverse=True)
    kept, used, cut = [], 0, False
    for r in ranked:
        cost = len(_entry("r00000", r)) + 2
        if used + cost > limit:
            cut = True
            continue
        used += cost
        kept.append(r)

    parts, refs = [], {}
    for r in sorted(kept, key=lambda r: (r["ts"], r["id"])):
        ref = f"r{len(refs) + 1}"
        refs[ref] = {"id": r["id"], "source": r["source"], "ts": r["ts"]}
        parts.append(_entry(ref, r))
    return "\n\n".join(parts), refs, cut


def _entry(ref: str, r: dict) -> str:
    when = _time(r["ts"]).astimezone().strftime("%Y-%m-%d %a %H:%M")
    head = [f"[{ref}] {when}", r["where"]]
    if r["sender"]:
        head.append(f"from {r['sender']}")
    lines = [" · ".join(head)]
    if r["title"]:
        lines.append(f"Title: {r['title']}")
    if r["text"]:
        lines.append(r["text"])
    return "\n".join(lines)


def _system(self_dir: Path, days: float) -> str:
    person = env("NAME", "the person")
    system = _SYSTEM.format(person=person, days=f"{days:g}")
    parts = []
    for name in SELF_FILES:
        path = self_dir / f"{name}.md"
        if path.exists() and (text := path.read_text(encoding="utf-8").strip()):
            parts.append(f"<{name}>\n{text}\n</{name}>")
    if parts:
        system += f"\n\nWho {person} is and how they write, from their self-model:\n"
        system += "\n".join(parts)
    return system


def _item_line(item: dict) -> str:
    state = [item["status"], f"waiting on {item['waiting_on']}"]
    if item.get("due"):
        state.append(f"due {item['due']}")
    step = f" Next: {item['next_step']}" if item.get("next_step") else ""
    return f"- id {item['id']} [{item['kind']}; {', '.join(state)}] {item['title']}.{step}"


def _closed_text(closed: dict[str, dict]) -> str:
    if not closed:
        return ""
    lines = ["\n## Closed by them on their own. Never add these back, however they're worded"]
    for entry in sorted(closed.values(), key=lambda e: e["closed_at"]):
        lines.append(f"- {entry['title']} ({entry['kind']}): {_MARKED[entry['action']]}")
    return "\n".join(lines) + "\n"


# ── The answer ──────────────────────────────────────────────────────────────


def apply(
    answer: dict, shown: dict[str, dict], refs: dict[str, dict], closed_keys: set
) -> tuple[dict, dict[str, dict], int]:
    """The model's answer, checked and given stable ids: the summary, timeline, scripts and
    brief, the open items it was shown updated with what it found, and how many it added.
    Shown items it left out stay as they were, and new ones matching a closed item are
    dropped."""
    items = dict(shown)
    renamed: dict[str, str] = {}  # the model's ids ("new-1", a shown id) to the stored ones
    new = 0
    for raw in answer.get("open_items") or []:
        title = _clean(raw.get("title"))
        if not title or raw.get("id") in closed_keys:
            continue
        kind = raw.get("kind") if raw.get("kind") in ITEM_KINDS else "follow_up"
        cited = _cited(raw.get("evidence"), refs)
        first = min((ts for _, ts in cited), default=None)
        given = str(raw.get("id") or "")
        key = given if given in shown else item_id(title, kind, first)
        old = items.get(key)
        if old is None:
            if key in closed_keys or _fold(title) in closed_keys:
                continue
            new += 1
        before = old or {}
        items[key] = {
            "id": key,
            "title": title,
            "kind": kind,
            "waiting_on": raw.get("waiting_on") if raw.get("waiting_on") in WAITING_ON else "me",
            "next_step": _clean(raw.get("next_step")),
            "due": _due(raw.get("due")),
            "status": raw.get("status") if raw.get("status") in STATUSES else "open",
            "evidence": list(dict.fromkeys([*before.get("evidence", []), *(i for i, _ in cited)])),
        }
        renamed[given] = key
        renamed.setdefault(key, key)

    timeline: dict[str, dict] = {}
    for raw in answer.get("timeline") or []:
        title = _clean(raw.get("title"))
        kind = raw.get("kind")
        if not title or kind not in TIMELINE_KINDS:
            continue
        cited = _cited(raw.get("evidence"), refs)
        day = _due(raw.get("date")) or (_local_day(min(ts for _, ts in cited)) if cited else None)
        if not day:
            continue
        key = event_id(day, kind, title)
        timeline[key] = {
            "id": key,
            "date": day,
            "kind": kind,
            "title": title,
            "detail": _clean(raw.get("detail")),
            "with": _clean(raw.get("with")),
            "evidence": [i for i, _ in cited],
        }

    scripts: dict[str, dict] = {}
    for raw in answer.get("scripts") or []:
        target = renamed.get(str(raw.get("item_id") or ""))
        body = _scrub(str(raw.get("body") or "").strip())
        kind = raw.get("kind")
        if not target or not body or kind not in SCRIPT_KINDS:
            continue
        title = _clean(raw.get("title")) or items[target]["title"]
        key = script_id(target, kind, title)
        scripts[key] = {"id": key, "item_id": target, "kind": kind, "title": title, "body": body}

    result = {
        "summary": _clean(answer.get("summary")),
        "timeline": sorted(timeline.values(), key=lambda e: (e["date"], e["title"])),
        "scripts": list(scripts.values()),
        "visit_brief": _scrub(str(answer.get("visit_brief") or "").strip()),
    }
    return result, items, new


def item_id(title: str, kind: str, first_seen: str | None) -> str:
    return _hash(_fold(title), kind, first_seen or "")


def event_id(day: str, kind: str, title: str) -> str:
    return _hash(day, kind, _fold(title))


def script_id(item: str, kind: str, title: str) -> str:
    return _hash(item, kind, _fold(title))


def _hash(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:12]


def _cited(evidence: object, refs: dict[str, dict]) -> list[tuple[str, str]]:
    """The records behind the [r..] refs the model cited, as (id, ts), each once."""
    found: dict[str, str] = {}
    for value in evidence if isinstance(evidence, list) else []:
        match = _REF.search(str(value))
        if match and (ref := refs.get(match[0])):
            found.setdefault(ref["id"], ref["ts"])
    return list(found.items())


def _settle(
    items: dict[str, dict],
    closed: dict[str, dict],
    verdicts: dict[str, tuple[str, str]],
    cited: dict[str, dict],
    now: datetime,
) -> dict[str, dict]:
    """The user's verdicts applied, done items dated in `closed`, and the long-done ones dropped.
    An item marked waiting stays waiting until a record newer than the mark is cited for it."""
    settled = {}
    for key, item in items.items():
        action, marked = verdicts.get(key, (None, ""))
        action = action or (closed.get(key) or {}).get("action")
        if action == "not_relevant":
            continue
        if action == "done":
            item = {**item, "status": "done"}
        elif action == "waiting":
            ts = [str((cited.get(e) or {}).get("ts") or "") for e in item["evidence"]]
            if max(ts, default="") <= marked:
                item = {**item, "status": "waiting"}
        if item["status"] == "done":
            if key not in closed:
                closed[key] = _closed_entry(item, None, _iso(now))
            if closed[key]["closed_at"] < _iso(now - DONE_KEEP):
                continue
        elif key in closed and not closed[key]["action"]:
            del closed[key]  # the records reopened it
        settled[key] = item
    return settled


def _closed_entry(item: dict, action: str | None, closed_at: str) -> dict:
    return {
        "title": item["title"],
        "kind": item["kind"],
        "action": action,  # None when the records showed it done, not the user
        "closed_at": closed_at,
    }


def _closed_keys(closed: dict[str, dict], mine: set[str]) -> set:
    """What a new item can match a closed one by: its id, or its title in any case and
    spacing."""
    keys: set = set(mine)
    for key in mine & closed.keys():
        keys.add(_fold(closed[key]["title"]))
    return keys


def _sorted(items: Iterable[dict]) -> list[dict]:
    """Open first, then waiting, then done; waiting on the user first, then by due date."""
    return sorted(
        items,
        key=lambda i: (
            STATUSES.index(i["status"]),
            WAITING_ON.index(i["waiting_on"]),
            i.get("due") or "9999",
            i["title"],
        ),
    )


def _feedback(path: Path) -> dict[str, tuple[str, str]]:
    """The user's latest verdict on each item from the page: {item_id: (action, ts)}."""
    verdicts: dict[str, tuple[str, str]] = {}
    for event in _jsonl(path):
        item, action, when = event.get("item_id"), event.get("action"), _when(event.get("ts"))
        if action not in ACTIONS or when is None or not isinstance(item, str):
            continue
        if item not in verdicts or _iso(when) >= verdicts[item][1]:
            verdicts[item] = (action, _iso(when))
    return verdicts


# ── Scrubbing and small helpers ─────────────────────────────────────────────


def _redact(text: str) -> str:
    """A record's text with links cut to their host, email addresses to their domain, and
    phone, card, social security and long account numbers blanked."""
    text = _URL.sub(lambda m: f"[link: {_host(m[0])}]", text)
    text = _EMAIL.sub(lambda m: f"[address at {m[1].lower()}]", text)
    return _numbers(text)


def _scrub(text: str) -> str:
    """What the model wrote, with any number that slipped through blanked, and the chat
    stand-ins it was told not to repeat replaced."""
    text = _EMAIL.sub("[email address]", text)
    return _CONTACT.sub("a contact", _numbers(text))


def _numbers(text: str) -> str:
    text = _SSN.sub("[number]", text)
    text = _CARD.sub("[number]", text)
    text = _PHONE.sub("[phone]", text)
    return _LONG_NUMBER.sub("[number]", text)


def _excerpt(text: str, limit: int) -> str:
    """The whole text when it fits, else the passages around its health terms, joined by
    "…", up to `limit` characters. With no term in it, its start."""
    if len(text) <= limit:
        return text
    spans: list[list[int]] = []
    for pattern, _, _ in _COMPILED:
        for match in pattern.finditer(text):
            spans.append([max(0, match.start() - EXCERPT_RADIUS), match.end() + EXCERPT_RADIUS])
    if not spans:
        return _clip(text, limit)
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces, used = [], 0
    for start, end in merged:
        piece = " ".join(text[start:end].split())
        if used + len(piece) > limit:
            piece = _clip(piece, limit - used)
        if piece:
            pieces.append(piece)
            used += len(piece) + 3
        if used >= limit:
            break
    lead = "… " if merged[0][0] > 0 else ""
    tail = " …" if merged[-1][1] < len(text) or used >= limit else ""
    return lead + " … ".join(pieces) + tail


def _records(directory: Path, since: str, until: str) -> Iterator[dict]:
    for path in sorted(directory.glob("*.jsonl")):
        if since[:7] <= path.stem <= until[:7]:
            for r in _jsonl(path):
                ts = r.get("ts")
                if isinstance(ts, str) and since <= ts <= until and r.get("id") is not None:
                    yield r


def _jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                record = json.loads(line)
            except ValueError:
                continue  # the page writes some of these, and one bad line shouldn't stop a run
            if isinstance(record, dict):
                yield record


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"care: {path} isn't valid JSON ({e}). Fix or delete it.") from None
    return data if isinstance(data, dict) else {}


def _load_closed(path: Path) -> dict[str, dict]:
    data = _load(path)
    return {k: v for k, v in data.items() if isinstance(v, dict) and "closed_at" in v}


def _valid_item(item: object) -> bool:
    """An open item as this module writes them; anything else in care.json is left behind."""
    return (
        isinstance(item, dict)
        and all(isinstance(item.get(k), str) for k in ("id", "title", "next_step"))
        and item.get("kind") in ITEM_KINDS
        and item.get("waiting_on") in WAITING_ON
        and item.get("status") in STATUSES
        and isinstance(item.get("evidence"), list)
    )


def _write_json(path: Path, data: object) -> None:
    """Swap the file in whole, private to the user (0600, in a 0700 folder)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _domain(address: object) -> str:
    text = str(address or "")
    return text.rsplit("@", 1)[1].lower() if "@" in text else ""


def _host(url: str) -> str:
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/", 1)[0]
    return host.split("@")[-1].split(":")[0].lower().removeprefix("www.")


def _clean(text: object) -> str:
    return _scrub(" ".join(str(text or "").split()))


def _due(text: object) -> str | None:
    value = str(text or "").strip()
    if not _DAY.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _fold(title: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", title.casefold()).split())


def _time(ts: str) -> datetime:
    when = datetime.fromisoformat(ts)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _local_day(ts: str) -> str:
    return _time(ts).astimezone().strftime("%Y-%m-%d")


def _when(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return ""
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
