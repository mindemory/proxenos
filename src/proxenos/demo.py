"""`proxenos demo [PATH]`: a vault of made-up records, to try the page without your own data.

The vault is Tess Ray's, and she doesn't exist: a data scientist at Acme Labs who runs with a
Sunday club and is partway through getting a sore knee seen to. What the ingesters would bring in
is written to raw/ in their formats, dated around today: WhatsApp chats and groups, two mail
accounts, two calendars, runs, listening, notes and LinkedIn connections. What the model would
write from them is written the way each clone writes it: the self-model, a feed, tasks, care,
advice, network ideas, drafts and errands. Then the steps that need no model run on it as they
would on a real vault: the memory index, the people index, today's recall and the outbox's
track record.

No model is called, and nothing on this computer is read. The people and organizations are made
up, phone numbers are 555-01xx (kept for fiction), and addresses and links use the reserved
example domains. The vault holds outbox.DEMO, and nothing is sent from a vault that has it, so an
errand's Send there only says so. PATH has to be new, empty or an earlier demo, which is written
again from scratch: a demo never lands on top of real data.
"""

import json
import os
import re
import shlex
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from proxenos import memory, outbox, store
from proxenos.clones import advisor, care, errands, network, recall, tasks, tracker, work
from proxenos.config import REPO_ROOT

PORT = 4848  # the demo's page, so it can run beside your own on 4747
NAME = "Tess Ray"
HOME_MAIL = "tess.ray@example.com"
WORK_MAIL = "tess.ray@acmelabs.example"
# The settings a real vault's .env would hold, set while the demo is built.
PERSON = {
    "PROXENOS_NAME": NAME,
    "PROXENOS_FULL_NAME": NAME,
    "PROXENOS_EMAILS": f"{HOME_MAIL},{WORK_MAIL}",
}

# Who Tess knows: a mail address each, and a WhatsApp number for the ones she chats with.
ADDRESS = {
    "Ben Ode": "ben.ode@acmelabs.example",
    "Eli Park": "eli.park@acmelabs.example",
    "Kai Lund": "kai.lund@acmelabs.example",
    "Hana Ito": "hana.ito@acmelabs.example",
    "Nia Cole": "nia.cole@acmelabs.example",
    "Tom Wu": "tom.wu@acmelabs.example",
    "Fay Moss": "fay.moss@betacorp.example",
    "Uma Rao": "uma.rao@deltaanalytics.example",
    "Dee Fay": "dee.fay@example.net",
    "Mei Ray": "mei.ray@example.net",
    "Leo Ray": "leo.ray@example.net",
}
JID = {
    name: f"1555555{n:04d}@s.whatsapp.net"
    for n, name in enumerate(
        ["Cy Doe", "Dee Fay", "Gus Hale", "Ivy Chen", "Jon Reyes", "Lia Ruiz", "Max Bell"]
        + ["Mei Ray", "Leo Ray"],
        start=101,
    )
}
RUNNERS = ("120363000000000101@g.us", "Sunday Runners")
FAMILY = ("120363000000000102@g.us", "Ray family")
CLINIC = ("Northside Clinic", "portal@northside-clinic.example")
IMAGING = ("Lakeview Imaging", "appointments@lakeview-imaging.example")
BILLING = ("Lakeview Imaging Billing", "billing@lakeview-imaging.example")
PLAN = ("Harbor Health Plan", "claims@harborhealth.example")
PT = ("Riverside Physical Therapy", "frontdesk@riverside-pt.example")


def run(path: Path | None, now: datetime | None = None) -> str:
    """Build the demo at `path`, or in a new temporary folder, and say how to open it."""
    vault = Path(path).expanduser() if path else Path(tempfile.mkdtemp(prefix="proxenos-demo-"))
    vault = vault.resolve()
    stats = build(vault, now)
    return (
        f"demo: a made-up vault for {NAME} is at {vault} ({stats['records']} records, "
        f"{stats['people']} people).\n"
        f"Open the page on it, on port {PORT} so it can run beside your own:\n\n"
        f"  PROXENOS_VAULT={shlex.quote(str(vault))} PROXENOS_NAME={shlex.quote(NAME)} "
        f"proxenos web --port {PORT}\n\n"
        "Nothing is sent from it. Delete the folder when you're done."
    )


def build(vault: Path, now: datetime | None = None) -> dict[str, int]:
    """Write the demo vault, then index it. Counts of what it holds."""
    if vault.is_relative_to(REPO_ROOT):
        raise SystemExit(f"demo: {vault} is inside the public repo; put it elsewhere")
    if vault.exists():
        if outbox.is_demo(vault):
            shutil.rmtree(vault)
        elif not vault.is_dir() or any(vault.iterdir()):
            raise SystemExit(f"demo: {vault} isn't empty or an earlier demo; give a new folder")
    vault.mkdir(mode=0o700, parents=True, exist_ok=True)
    (vault / outbox.DEMO).write_text(
        "A made-up vault, written by `proxenos demo`. Nothing is ever sent from it.\n",
        encoding="utf-8",
    )
    c = _Clock(now or datetime.now(UTC))
    with _as_tess():
        _raw(vault, c)
        _self(vault, c)
        _feed(vault, c)
        _tasks(vault, c)
        _care(vault, c)
        _advice(vault, c)
        _ideas(vault, c)
        _drafts(vault, c)
        _errands(vault, c)
        indexed = memory.build(vault)
        people = network.build(vault, people_only=True, now=c.now)
        recalled = recall.recall(vault, now=c.now)
        outbox.run(vault, c.now)  # its track record for the page; a demo has no way to send
    return {
        "records": indexed.get("records_total", 0),
        "people": people.get("people", 0),
        "memories": recalled["memories"],
    }


@contextmanager
def _as_tess() -> Iterator[None]:
    """The demo's settings in place of any in the environment, for as long as it's built."""
    saved = {key: os.environ.get(key) for key in PERSON}
    os.environ.update(PERSON)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _Clock:
    """Times around now, so the demo is always current. Days count from today, in local time."""

    def __init__(self, now: datetime):
        self.now = now.astimezone(UTC)
        self.local = now.astimezone()

    def at(self, days: int, hour: int, minute: int = 0) -> str:
        """`hour:minute` local time, `days` from today (negative: before), as a UTC time."""
        when = self.local + timedelta(days=days)
        return _iso(when.replace(hour=hour, minute=minute, second=0, microsecond=0))

    def ago(self, hours: float) -> str:
        return _iso(self.now - timedelta(hours=hours))

    def soon(self, hours: float) -> str:
        """`hours` from now, on the next half hour: something later today."""
        when = self.now + timedelta(hours=hours)
        return _iso(when + timedelta(minutes=-when.minute % 30, seconds=-when.second))

    def day(self, days: int) -> str:
        return (self.local + timedelta(days=days)).date().isoformat()

    def said(self, days: int) -> str:
        """The day as a person writes it: "Oct 17"."""
        when = self.local + timedelta(days=days)
        return f"{when:%b} {when.day}"


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data: object) -> None:
    work._write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ── raw/: what the ingesters would have brought in ──────────────────────────


def _raw(vault: Path, c: _Clock) -> None:
    raw = vault / "raw"
    store.merge_monthly(_whatsapp(c), raw / "whatsapp" / "messages")
    store.merge_snapshot(_groups(), raw / "whatsapp" / "groups")
    store.merge_monthly(_home_mail(c), raw / "email" / "personal")
    store.merge_monthly(_work_mail(c), raw / "email" / "work")
    store.merge_monthly(_home_calendar(c), raw / "calendar" / "personal")
    store.merge_monthly(_work_calendar(c), raw / "calendar" / "work")
    store.merge_monthly(_runs(c), raw / "strava" / "activities")
    store.merge_monthly(_plays(c), raw / "spotify" / "plays")
    store.merge_monthly(_notes(c), raw / "notes" / "pages")
    store.merge_monthly(_connections(c), raw / "linkedin" / "connections")
    store.merge_monthly(_slack(c), raw / "slack" / "acme" / "messages")
    store.merge_snapshot(_channels(), raw / "slack" / "acme" / "channels")


def _whatsapp(c: _Clock) -> list[dict]:
    chats = {
        "cy": (JID["Cy Doe"], "Cy Doe", "direct"),
        "dee": (JID["Dee Fay"], "Dee Fay", "direct"),
        "gus": (JID["Gus Hale"], "Gus Hale", "direct"),
        "run": (*RUNNERS, "group"),
        "fam": (*FAMILY, "group"),
    }
    said = [  # (chat, when, who wrote it, or None for Tess, text)
        (
            "cy",
            c.at(-9, 19, 12),
            "Cy Doe",
            "Are you still up for the lake trip the weekend after next?",
        ),
        ("cy", c.at(-9, 19, 40), None, "Yes! As long as the knee behaves. I'll know more after PT"),
        (
            "cy",
            c.at(-2, 20, 5),
            "Cy Doe",
            "Can I borrow your camping stove for it? Mine finally died",
        ),
        (
            "cy",
            c.at(-2, 20, 6),
            "Cy Doe",
            "Also Lia wants to know if you're doing the November 10k with us",
        ),
        (
            "dee",
            c.at(-6, 18, 30),
            "Dee Fay",
            "Mum's birthday dinner Saturday at 7? I can book the Thai place",
        ),
        ("dee", c.at(-6, 21, 2), None, "Saturday works. Book it, I'll bring the cake"),
        ("dee", c.at(-1, 12, 20), "Dee Fay", "Booked for 7! Can you pick up Leo on the way?"),
        ("gus", c.at(-12, 8, 10), "Gus Hale", "How's the knee? Saw you skipped Sunday"),
        ("gus", c.at(-12, 8, 30), None, "MRI today, then PT. Walking is fine, running isn't yet"),
        (
            "gus",
            c.at(-3, 17, 45),
            "Gus Hale",
            "Could you book the back room at Fern Cafe for the club social next Friday? You know the owner",
        ),
        ("gus", c.at(-3, 18, 2), None, "Sure, I'll call them this week"),
        (
            "run",
            c.at(-14, 7, 2),
            "Gus Hale",
            "Long run Sunday: 16 km from the boathouse, 7:30 sharp",
        ),
        ("run", c.at(-14, 7, 15), "Ivy Chen", "In!"),
        ("run", c.at(-14, 7, 20), "Jon Reyes", "In, slower group please"),
        (
            "run",
            c.at(-14, 8, 0),
            None,
            "Sitting this one out, knee. I'll bring coffee to the finish",
        ),
        (
            "run",
            c.at(-7, 7, 5),
            "Gus Hale",
            "Route for Sunday is up. Club social is next Friday, details soon",
        ),
        ("run", c.at(-7, 7, 30), "Lia Ruiz", "Who's doing the November 10k? Signups close Friday"),
        ("run", c.at(-7, 7, 41), "Max Bell", "Me"),
        ("run", c.at(-7, 8, 3), "Cy Doe", "Me too"),
        ("run", c.at(-1, 19, 0), "Ivy Chen", "Track session Wednesday moved to 6:30"),
        ("fam", c.at(-10, 19, 0), "Mei Ray", "Did the knee doctor say anything?"),
        ("fam", c.at(-10, 19, 20), None, "Waiting on the MRI, then physio. Don't worry!"),
        ("fam", c.at(-4, 9, 0), "Leo Ray", "Photos from the weekend are in the shared album"),
        ("fam", c.at(-4, 9, 30), None, "Love the one by the lake"),
    ]
    records = []
    for n, (chat, ts, who, text) in enumerate(said, start=1):
        jid, title, kind = chats[chat]
        sender = None if who is None else (jid if kind == "direct" else JID[who])
        records.append(
            {
                "id": f"{jid}/DEMO{n:04d}",
                "ts": ts,
                "chat_id": jid,
                "chat_name": title,
                "chat_type": kind,
                "from_me": who is None,
                "sender_id": sender,
                "sender_name": who,
                "kind": "text",
                "wa_type": 0,
                "text": text,
                "caption": None,
            }
        )
    return records


def _groups() -> list[dict]:
    members = {
        RUNNERS: ["Gus Hale", "Ivy Chen", "Jon Reyes", "Lia Ruiz", "Max Bell", "Cy Doe"],
        FAMILY: ["Dee Fay", "Mei Ray", "Leo Ray"],
    }
    return [
        {
            "id": jid,
            "chat_id": jid,
            "chat_name": title,
            "members": [
                {"jid": JID[n], "alt_jid": None, "name": n, "push_name": n, "active": True}
                for n in names
            ],
        }
        for (jid, title), names in members.items()
    ]


def _mail(
    account: str,
    n: int,
    ts: str,
    sender: tuple[str, str] | None,
    subject: str,
    body: str,
    to: list[str] | None = None,
    attachments: list[str] | None = None,
) -> dict:
    """One message as the mail ingesters write it; `sender` None is Tess's own."""
    mine = HOME_MAIL if account == "personal" else WORK_MAIL
    return {
        "id": f"demo-{account}-{n}",
        "ts": ts,
        "account": account,
        "from_address": sender[1] if sender else mine,
        "from_name": sender[0] if sender else NAME,
        "from_me": sender is None,
        "to": to or [mine],
        "cc": None,
        "subject": subject,
        "in_reply_to": None,
        "attachments": attachments,
        "body_new": body,
    }


def _person(name: str) -> tuple[str, str]:
    return name, ADDRESS[name]


def _home_mail(c: _Clock) -> list[dict]:
    news = ("The Data Desk", "news@datadesk.example")
    issues = [
        "forecasting with too little history",
        "the quiet cost of feature drift",
        "when to stop tuning",
        "dashboards nobody opens",
        "a field guide to survival models",
    ]
    mail = [
        (
            c.at(-30, 13, 5),
            CLINIC,
            "Your visit summary is ready",
            (
                f"Your visit summary from {c.said(-30)} is in the patient portal. Orders placed: MRI of "
                "the right knee at Lakeview Imaging, and a referral to physical therapy."
            ),
        ),
        (
            c.at(-29, 10, 40),
            IMAGING,
            "We received your MRI referral",
            (
                "Your referral from Northside Clinic arrived. Your plan needs prior authorization for "
                "this scan; we have asked Harbor Health Plan and will be in touch to schedule."
            ),
        ),
        (
            c.at(-24, 9, 15),
            PLAN,
            "Prior authorization request received",
            (
                "We received a prior authorization request from Lakeview Imaging for an MRI. Most "
                "decisions take 3 to 5 business days."
            ),
        ),
        (
            c.at(-19, 16, 0),
            PLAN,
            "Prior authorization approved",
            "Approved: one MRI of the right knee at Lakeview Imaging, valid for 60 days.",
        ),
        (
            c.at(-17, 11, 20),
            IMAGING,
            f"Appointment confirmed: MRI on {c.said(-12)} at 8:15",
            "Please arrive 20 minutes early with your insurance card. Wear clothes with no metal.",
        ),
        (
            c.at(-9, 14, 30),
            CLINIC,
            "New result in your patient portal",
            (
                "Your MRI report is ready to view in the patient portal. Your clinician asks you to "
                "book a follow-up visit to go over it."
            ),
        ),
        (
            c.at(-7, 8, 0),
            BILLING,
            "Your statement is ready",
            (
                f"Amount due: $1,240.00 for MRI on {c.said(-12)}. Payment due {c.said(23)}. Questions "
                "about this bill? Call billing, Monday to Friday."
            ),
        ),
        (
            c.at(-5, 7, 45),
            PLAN,
            "Your Explanation of Benefits",
            (
                f"Claim processed for Lakeview Imaging, {c.said(-12)}. Billed $1,240.00. Plan discount "
                "$810.00. Plan paid $245.00. Your responsibility: $185.00. This is not a bill."
            ),
        ),
        (
            c.at(-3, 15, 10),
            PT,
            f"Your intake is booked: {c.said(1)} at 9:30",
            (
                "Please bring your insurance card and any imaging reports, or have them sent to us "
                "ahead of the visit. New-patient forms are attached."
            ),
        ),
        (
            c.at(-16, 9, 5),
            _person("Fay Moss"),
            "Data science lead role at Beta Corp",
            (
                "Hi Tess, I lead hiring for our forecasting team, and your talk on churn calibration "
                "came up twice this week. Would you be open to a chat about the lead role?"
            ),
        ),
        (
            c.at(-40, 18, 0),
            _person("Uma Rao"),
            "Slides from the meetup",
            (
                "Great to meet you at the forecasting meetup! Here are my slides. Omar Said on our "
                "team runs the speaker list, if you ever want to give a talk."
            ),
        ),
    ]
    records = [
        _mail("personal", n, ts, sender, subject, body)
        for n, (ts, sender, subject, body) in enumerate(mail, start=1)
    ]
    records += [
        _mail(
            "personal",
            20,
            c.at(-3, 15, 40),
            None,
            f"Re: Your intake is booked: {c.said(1)} at 9:30",
            "Thanks, see you then. I'll have the MRI report sent over before.",
            to=[PT[1]],
        ),
        _mail(
            "personal",
            21,
            c.at(-15, 8, 50),
            None,
            "Re: Data science lead role at Beta Corp",
            "Hi Fay, thanks for reaching out. It's a busy month; could I come back to you at "
            "the end of it?",
            to=[ADDRESS["Fay Moss"]],
        ),
        _mail(
            "personal",
            22,
            c.at(-60, 10, 0),
            None,
            "Application: Senior Data Scientist",
            "Dear hiring team, I'd like to apply for the Senior Data Scientist role. I build "
            "churn and demand forecasts at Acme Labs. My CV is attached.",
            to=["jobs@deltaanalytics.example"],
            attachments=["Tess_Ray_CV.pdf"],
        ),
    ]
    records += [
        _mail(
            "personal",
            30 + i,
            c.at(-2 - 7 * i, 6, 30),
            news,
            f"The Data Desk: {issue}",
            f"This week: {issue}, three papers worth your time, and a chart we can't stop "
            "looking at.",
        )
        for i, issue in enumerate(issues)
    ]
    return records


def _work_mail(c: _Clock) -> list[dict]:
    team = [ADDRESS[n] for n in ("Ben Ode", "Kai Lund", "Hana Ito", "Nia Cole")]
    mail = [
        (
            c.at(-4, 10, 12),
            "Ben Ode",
            "Slides for Thursday",
            (
                "Hi Tess, could you send the churn model slides with the cohort breakdown before the "
                "review? Eli wants to see the November cohort on its own."
            ),
        ),
        (
            c.at(-2, 16, 48),
            "Ben Ode",
            "Re: Slides for Thursday",
            "Great, thanks. If you can add the calibration plot too, even better.",
        ),
        (
            c.at(-5, 9, 0),
            "Eli Park",
            "Q4 planning doc: comments by Friday?",
            (
                "The draft is in the shared folder. Mostly I'd like to know whether the forecasting "
                "headcount ask is right."
            ),
        ),
        (
            c.at(-8, 13, 30),
            "Hana Ito",
            "Forecasting reading group",
            "We're picking the next paper. Want to suggest one?",
        ),
        (
            c.at(-13, 11, 0),
            "Kai Lund",
            "Re: cohort definitions",
            "I've pushed the new definitions; the November cohort leaves out trial users now.",
        ),
        (
            c.at(-20, 17, 0),
            "Eli Park",
            "Team offsite next month",
            "Save the date: a day out of the office to plan next year. Ideas welcome.",
        ),
        (
            c.at(-25, 9, 30),
            "Nia Cole",
            "Conference reimbursement",
            "Reminder: receipts for the autumn conference are due by the end of the month.",
        ),
    ]
    records = [
        _mail("work", n, ts, _person(who), subject, body)
        for n, (ts, who, subject, body) in enumerate(mail, start=1)
    ]
    records += [
        _mail(
            "work",
            20,
            c.at(-4, 11, 2),
            None,
            "Re: Slides for Thursday",
            "Will do, by Wednesday.",
            to=[ADDRESS["Ben Ode"]],
        ),
        _mail(
            "work",
            21,
            c.at(-8, 14, 5),
            None,
            "Re: Forecasting reading group",
            "How about the survey on conformal prediction? It's long but readable.",
            to=[ADDRESS["Hana Ito"], ADDRESS["Kai Lund"], ADDRESS["Nia Cole"]],
        ),
        _mail(
            "work",
            22,
            c.at(-13, 11, 40),
            None,
            "Re: cohort definitions",
            "Thanks Kai, I'll rerun the model on them.",
            to=[ADDRESS["Kai Lund"]],
        ),
        _mail(
            "work",
            23,
            c.at(-22, 10, 0),
            None,
            "Re: Conference reimbursement",
            "Submitted, thanks Nia!",
            to=[ADDRESS["Nia Cole"]],
        ),
        _mail(
            "work",
            24,
            c.at(-11, 9, 20),
            ("Acme IT", "it-help@acmelabs.example"),
            "Ticket received: GPU quota increase",
            "We've received your request and will get back to you within 5 working days.",
        ),
        _mail(
            "work",
            25,
            c.at(-20, 17, 30),
            None,
            "Re: Team offsite next month",
            "Count me in. Could we keep an hour for the forecasting roadmap?",
            to=[ADDRESS["Eli Park"], *team],
        ),
    ]
    return records


def _event(
    n: str,
    start: str,
    minutes: int,
    title: str,
    where: str | None = None,
    guests: tuple[str, ...] = (),
) -> dict:
    end = datetime.fromisoformat(start) + timedelta(minutes=minutes)
    people = [{"name": g, "email": ADDRESS.get(g), "status": "accepted"} for g in guests]
    return {
        "id": f"demo-{n}",
        "ts": start,
        "start": start,
        "end": _iso(end),
        "all_day": False,
        "timezone": None,
        "summary": title,
        "location": where,
        "description": None,
        "rrule": None,
        "status": "CONFIRMED",
        "organizer": None,
        "attendees": len(people),
        "guests": people,
    }


def _home_calendar(c: _Clock) -> list[dict]:
    events = [
        _event("visit", c.at(-30, 10, 0), 30, "Primary care visit", CLINIC[0]),
        _event("mri", c.at(-12, 8, 15), 45, "MRI, right knee", IMAGING[0]),
        _event("pt", c.at(1, 9, 30), 60, "Physical therapy intake", PT[0]),
        _event(
            "dinner",
            c.at(3, 19, 0),
            150,
            "Mum's birthday dinner",
            "Thai Garden",
            ("Dee Fay", "Mei Ray", "Leo Ray"),
        ),
    ]
    events += [
        _event(f"run{-days}", c.at(days, 7, 30), 90, "Sunday Runners long run", "The boathouse")
        for days in (-28, -21, -14, -7)
    ]
    return events


def _work_calendar(c: _Clock) -> list[dict]:
    team = ("Ben Ode", "Kai Lund", "Hana Ito")
    events = [
        _event("review", c.at(1, 14, 0), 60, "Churn model review", "Room 3", ("Eli Park", *team)),
        _event(
            "coffee",
            c.soon(3),
            30,
            "Coffee with Hana: next reading group paper",
            "Kitchen",
            ("Hana Ito",),
        ),
        _event(
            "planning",
            c.at(-6, 10, 0),
            90,
            "Q4 planning",
            "Room 1",
            ("Eli Park", *team, "Nia Cole"),
        ),
        _event(
            "reading",
            c.at(-8, 16, 0),
            60,
            "Forecasting reading group",
            None,
            ("Hana Ito", "Kai Lund", "Nia Cole", "Tom Wu"),
        ),
    ]
    events += [
        _event(f"oneonone{-days}", c.at(days, 11, 0), 30, "1:1 Eli / Tess", None, ("Eli Park",))
        for days in (-19, -12, -5, 2)
    ]
    return events


def _runs(c: _Clock) -> list[dict]:
    done = [  # (days ago, sport, name, km, minutes): running until the knee, then walks and rides
        (45, "Run", "Easy morning run", 7.2, 41),
        (43, "Run", "Track intervals", 8.0, 44),
        (41, "Run", "Tempo by the river", 10.1, 52),
        (38, "Run", "Long run, boathouse loop", 18.2, 104),
        (33, "Run", "Short shakeout (knee sore)", 3.1, 20),
        (24, "Walk", "Evening walk", 4.5, 55),
        (18, "Walk", "Walk to the market", 5.2, 62),
        (13, "VirtualRide", "Easy spin", 15.0, 35),
        (8, "VirtualRide", "Easy spin", 18.0, 40),
        (6, "Walk", "Lake loop walk", 6.0, 72),
        (2, "Walk", "Evening walk", 4.8, 58),
    ]
    return [
        {
            "id": f"strava:demo{days}",
            "ts": c.at(-days, 7, 0),
            "name": name,
            "sport_type": sport,
            "distance_m": km * 1000,
            "moving_time_s": minutes * 60,
            "elapsed_time_s": minutes * 60 + 120,
        }
        for days, sport, name, km, minutes in done
    ]


def _plays(c: _Clock) -> list[dict]:
    tracks = [
        ("The Lantern Choir", "Harbour Lights"),
        ("Mara Vey", "Slow Current"),
        ("Quiet Harbor", "Morning Ferry"),
        ("Night Bus Orchestra", "Last Stop"),
        ("Mara Vey", "Paper Boats"),
    ]
    plays = []
    for days in range(30):
        for k in range(3):
            artist, track = tracks[(days + k) % len(tracks)]
            plays.append(
                {
                    "id": f"spotify:demo{days}-{k}",
                    "ts": c.at(-days - 1, 8 + 4 * k, 15),
                    "kind": "track",
                    "track": track,
                    "artist": artist,
                    "album": None,
                    "ms_played": 200_000 + 9_000 * k,
                }
            )
    return plays


def _notes(c: _Clock) -> list[dict]:
    pages = [
        (
            "knee",
            c.at(-1, 21, 0),
            "Knee log",
            "Health",
            (
                f"{c.said(-38)}: right knee sore after the 18 km long run, outside edge.\n"
                f"{c.said(-33)}: still sore on stairs. Stopped running.\n"
                f"{c.said(-30)}: primary care at Northside. MRI and physio referral.\n"
                f"{c.said(-12)}: MRI at Lakeview.\n"
                f"{c.said(-5)}: the plan says I owe $185; Lakeview's bill says $1,240.\n"
                "Questions for PT: when can I run again? What to do on the bike?"
            ),
        ),
        (
            "reading",
            c.at(-8, 22, 0),
            "Reading list",
            "Reading",
            (
                "Want to read: Hana Ito on calibrated forecasts. Look into conformal prediction for "
                "churn. The survival models field guide from The Data Desk."
            ),
        ),
        (
            "half",
            c.at(-50, 20, 0),
            "Spring half marathon plan",
            "Running",
            "Build to 18 km long runs by March. One track night, one tempo, one long run a week.",
        ),
    ]
    return [
        {
            "id": f"demo-{key}",
            "ts": ts,
            "title": title,
            "collection": where,
            "text": text,
            "kind": "page",
        }
        for key, ts, title, where, text in pages
    ]


# Slack user ids, and the channels Tess is in.
SLACK = {
    "Tess Ray": "U0DEMO00",
    "Hana Ito": "U0DEMO01",
    "Kai Lund": "U0DEMO02",
    "Tom Wu": "U0DEMO03",
    "Ben Ode": "U0DEMO04",
}
FORECASTING = ("C0DEMO01", "forecasting", "channel")
TOM = ("D0DEMO01", "Tom Wu", "dm")


def _slack(c: _Clock) -> list[dict]:
    said = [  # (channel, when, who, text)
        (
            FORECASTING,
            c.at(-9, 10, 4),
            "Hana Ito",
            "Reading group: paper ideas welcome in the thread",
        ),
        (
            FORECASTING,
            c.at(-9, 10, 30),
            "Tess Ray",
            "Conformal prediction survey? Long but readable",
        ),
        (
            FORECASTING,
            c.at(-6, 15, 12),
            "Kai Lund",
            "New cohort definitions are merged. Trial users are out",
        ),
        (
            FORECASTING,
            c.at(-6, 15, 40),
            "Tess Ray",
            "Thanks Kai! Rerunning the churn model on them today",
        ),
        (
            FORECASTING,
            c.at(-2, 11, 0),
            "Ben Ode",
            "Reminder: churn review Thursday, slides by Wednesday",
        ),
        (
            TOM,
            c.at(-4, 14, 20),
            "Tom Wu",
            "Is the GPU quota through yet? My training job is queued",
        ),
        (
            TOM,
            c.at(-4, 14, 31),
            "Tess Ray",
            "Not yet, IT said five working days. I'll ping them Friday",
        ),
    ]
    records = []
    for (channel, name, kind), ts, who, text in said:
        stamp = f"{datetime.fromisoformat(ts).timestamp():.6f}"
        records.append(
            {
                "id": f"{channel}/{stamp}",
                "ts": ts,
                "slack_ts": stamp,
                "channel_id": channel,
                "channel_name": name,
                "channel_type": kind,
                "user_id": SLACK[who],
                "user_name": who,
                "from_me": who == NAME,
                "text": text,
                "thread_ts": None,
                "is_reply": False,
                "subtype": None,
            }
        )
    return records


def _channels() -> list[dict]:
    rosters = {FORECASTING: list(SLACK), TOM: ["Tess Ray", "Tom Wu"]}
    return [
        {
            "id": channel,
            "channel_id": channel,
            "channel_name": name,
            "channel_type": kind,
            "joined": True,
            "members": [
                {"id": SLACK[n], "name": n, "email": ADDRESS.get(n), "me": n == NAME} for n in names
            ],
        }
        for (channel, name, kind), names in rosters.items()
    ]


def _connections(c: _Clock) -> list[dict]:
    people = [  # (name, company, position, years ago)
        ("Ben Ode", "Acme Labs", "Senior Data Scientist", 3),
        ("Eli Park", "Acme Labs", "Head of Analytics", 3),
        ("Kai Lund", "Acme Labs", "Data Engineer", 2),
        ("Hana Ito", "Acme Labs", "Research Scientist", 2),
        ("Nia Cole", "Acme Labs", "Operations Manager", 3),
        ("Tom Wu", "Acme Labs", "ML Engineer", 1),
        ("Fay Moss", "Beta Corp", "Talent Partner", 0),
        ("Wes Tran", "Beta Corp", "Forecasting Lead", 4),
        ("Raj Mehta", "Delta Analytics", "Principal Scientist", 5),
        ("Uma Rao", "Delta Analytics", "Data Scientist", 1),
        ("Vic Noor", "Gamma Health", "Product Lead", 4),
        ("Zoe Hart", "Gamma Health", "Analytics Engineer", 2),
        ("Pia Holt", "Northfield University", "Associate Professor", 6),
        ("Ivy Chen", "Gamma Health", "Physiotherapist", 2),
    ]
    return [
        {
            "id": f"demo-li-{n}",
            "ts": c.at(-365 * years - 20 * n, 12, 0),
            "from_me": False,
            "name": name,
            "company": company,
            "position": position,
        }
        for n, (name, company, position, years) in enumerate(people)
    ]


# ── What the model would have written ───────────────────────────────────────


def _self(vault: Path, c: _Clock) -> None:
    files = {
        "identity": """# Identity

Tess Ray is a data scientist at Acme Labs, where she builds churn and demand forecasts and works
most closely with Ben Ode, Kai Lund and Hana Ito, for Eli Park. She runs with the Sunday Runners
and was training for a spring half marathon until a knee injury five weeks ago. Family is close:
her sister Dee organizes most of it.

- Values: getting the numbers right before they're presented; showing up for friends.
- Decides by writing things down first, then asking one trusted person.
- Open now: a recruiter at Beta Corp about a lead role; whether to speak at a meetup.
""",
        "interests": """# Interests

- Forecasting and calibration (high, rising): churn cohorts, conformal prediction.
- Running (high, fading for now): half marathon training on hold, cycling instead.
- Survival models (medium, stable).
- Health admin (medium, rising): referrals, prior authorization, bills.
""",
        "taste": """# Taste

Reads applied papers with code and a clear evaluation; skips benchmark-only work. Listens to
slow, warm albums while working and podcasts on walks.
""",
        "voice": """# Voice

- Personal chat: short, warm, exclamation marks, no sign-off. "Saturday works. Book it, I'll
  bring the cake"
- Work chat and email: plain and quick to the point, a date for each promise. "Will do, by
  Wednesday."
- Email to strangers: a greeting, two or three sentences, first name to sign.
""",
        "routines": """# Routines

Work from 9 to 6, deep work in the mornings. Long run on Sundays at 7:30 (paused); an easy spin
or a walk most evenings for now. Family dinner most Saturdays.
""",
        "open_questions": """# Open questions

- Is the Beta Corp role something she wants, or flattering timing?
- How much running does she want back, and how soon?
""",
    }
    folder = vault / "self"
    for name, text in files.items():
        work._write(folder / f"{name}.md", text)
    work._write(
        folder / "CHANGELOG.md",
        f"## {c.day(-21)}\n\nFirst self-model.\n\n"
        f"## {c.day(-1)}\n\n"
        "- Running moved from high and stable to high and fading: no runs since the knee, "
        "walks and rides instead.\n"
        "- Health admin added as an interest: a referral, a prior authorization and a bill in "
        "five weeks.\n"
        "- Identity notes the Beta Corp conversation.\n",
    )


def _feed(vault: Path, c: _Clock) -> None:
    latest, earlier = c.ago(5), c.ago(29)
    items = [  # (batch, kind, title, source, authors, score, interest, explore, summary, why)
        (
            latest,
            "paper",
            "Calibrated churn forecasts when cohorts shift",
            "Applied ML Review",
            ["R. Okoye", "M. Lindqvist"],
            0.91,
            "forecasting",
            False,
            (
                "Recalibrates a churn model per cohort with a small held-out set, and shows when it "
                "beats retraining."
            ),
            (
                "Your November cohort changed when trial users were left out: this is that problem, "
                "and the fix is an afternoon's work."
            ),
        ),
        (
            latest,
            "paper",
            "Conformal intervals for survival models on tabular data",
            "Stats Notes",
            ["J. Abara", "L. Pinto"],
            0.86,
            "calibration",
            False,
            "Distribution-free intervals for time-to-event predictions, with code.",
            (
                "You suggested conformal prediction for the reading group; this applies it to the "
                "models you build."
            ),
        ),
        (
            latest,
            "post",
            "What we learned retraining a demand model every week",
            "The Data Desk",
            ["S. Varga"],
            0.74,
            "forecasting",
            False,
            "A team's year of weekly retrains: what drifted, what didn't, and what they'd skip.",
            "Close to your Q4 planning question on how much forecasting work the team needs.",
        ),
        (
            latest,
            "news",
            "Riverton opens a 12 km riverside loop for runners and riders",
            "Riverton Gazette",
            None,
            0.66,
            "running",
            False,
            "The new path links the boathouse to the lake, with mile markers and lights.",
            "Your club's long runs start at the boathouse, and it's flat enough for the bike now.",
        ),
        (
            latest,
            "post",
            "Prior authorization, explained in one page",
            "Health Admin Notes",
            ["K. Mendes"],
            0.61,
            "health admin",
            True,
            "Who asks for it, how long it takes, and what to do when a bill arrives first.",
            "Something new: your last month had a prior authorization and a bill that came early.",
        ),
        (
            latest,
            "paper",
            "Hierarchical forecasts for subscription businesses",
            "Applied ML Review",
            ["D. Ferreira"],
            0.58,
            "forecasting",
            False,
            "Reconciles forecasts across plans, regions and cohorts so they add up.",
            "A way to make cohort forecasts add up to the totals Eli reports.",
        ),
        (
            earlier,
            "paper",
            "Gradient-boosted hazards at scale",
            "Stats Notes",
            ["T. Brandt"],
            0.8,
            "survival models",
            False,
            "Survival models trained like boosted trees, on millions of rows.",
            "The churn model is a survival model at heart; this scales it.",
        ),
        (
            earlier,
            "news",
            "City data portal adds weekly transit ridership",
            "Riverton Gazette",
            None,
            0.55,
            "open data",
            True,
            "Weekly counts by line, back to 2019.",
            "Something new: a clean public time series to try forecasting ideas on.",
        ),
    ]
    records = []
    for batch, kind, title, source, authors, score, interest, explore, summary, why in items:
        url = "https://example.org/demo/" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        records.append(
            {
                "id": tracker.item_id(url),
                "ts": batch,
                "batch": batch,
                "url": url,
                "title": title,
                "source": source,
                "kind": kind,
                "published": batch[:10] + "T00:00:00Z",
                "authors": authors,
                "summary": summary,
                "score": score,
                "why": why,
                "interest": interest,
                "explore": explore,
                "by": "proxenos",
            }
        )
    store.merge_monthly(records, vault / "tracker" / "items")
    saved = records[6]["id"]
    work._write(
        vault / "tracker" / "feedback.jsonl",
        json.dumps({"item_id": saved, "action": "save", "ts": c.ago(26)}) + "\n",
    )


def _tasks(vault: Path, c: _Clock) -> None:
    found = [  # (title, detail, source, with, asked, due, priority, status, evidence)
        (
            "Send Ben the churn slides with the cohort breakdown",
            (
                "He wants the November cohort on its own, and the calibration plot if you can, before "
                "Thursday's review."
            ),
            "email",
            "Ben Ode",
            c.at(-4, 10, 12),
            c.day(1),
            "high",
            "open",
            ["email/work/demo-work-1", "email/work/demo-work-2"],
        ),
        (
            "Comment on Eli's Q4 planning doc",
            "Eli asked mainly whether the forecasting headcount ask is right. Comments by Friday.",
            "email",
            "Eli Park",
            c.at(-5, 9, 0),
            c.day(3),
            "medium",
            "open",
            ["email/work/demo-work-3"],
        ),
        (
            "Pick up Leo on the way to Mum's birthday dinner",
            "Dee booked the Thai place for 7 on Saturday and asked you to collect Leo.",
            "whatsapp",
            "Dee Fay",
            c.at(-1, 12, 20),
            c.day(3),
            "medium",
            "open",
            [f"whatsapp/messages/{JID['Dee Fay']}/DEMO0007"],
        ),
        (
            "Book the back room at Fern Cafe for the club social",
            "Gus asked; you said you'd call them this week. The social is next Friday.",
            "whatsapp",
            "Gus Hale",
            c.at(-3, 17, 45),
            c.day(4),
            "medium",
            "open",
            [f"whatsapp/messages/{JID['Gus Hale']}/DEMO0010"],
        ),
        (
            "Lend Cy the camping stove for the lake trip",
            "",
            "whatsapp",
            "Cy Doe",
            c.at(-2, 20, 5),
            None,
            "low",
            "open",
            [f"whatsapp/messages/{JID['Cy Doe']}/DEMO0003"],
        ),
        (
            "Suggest a paper for the reading group",
            "You suggested the conformal prediction survey; waiting on Hana to pick.",
            "email",
            "Hana Ito",
            c.at(-8, 13, 30),
            None,
            "low",
            "waiting",
            ["email/work/demo-work-4"],
        ),
        (
            "GPU quota increase",
            "Acme IT said 5 working days.",
            "email",
            "Acme IT",
            c.at(-11, 9, 20),
            None,
            "medium",
            "waiting",
            ["email/work/demo-work-24"],
        ),
        (
            "Send the conference receipts to Nia",
            "",
            "email",
            "Nia Cole",
            c.at(-25, 9, 30),
            None,
            "low",
            "done",
            ["email/work/demo-work-23"],
        ),
    ]
    listed = [
        {
            "id": tasks.task_id(title, source, asked),
            "title": title,
            "detail": detail,
            "source": source,
            "with": who,
            "asked_at": asked,
            "due": due,
            "priority": priority,
            "status": status,
            "evidence": evidence,
        }
        for title, detail, source, who, asked, due, priority, status, evidence in found
    ]
    _write_json(vault / "clones" / "tasks" / "tasks.json", {"generated": c.ago(6), "tasks": listed})


def _care(vault: Path, c: _Clock) -> None:
    mail = "email/personal/demo-personal-"
    timeline = [  # (days, kind, title, detail, with, evidence)
        (
            -38,
            "symptom",
            "Right knee sore after a long run",
            "Outside of the knee, worse on stairs; running stopped five days later.",
            "",
            ["notes/pages/demo-knee"],
        ),
        (
            -30,
            "visit",
            "Primary care visit",
            "MRI of the right knee and physical therapy ordered.",
            "Northside Clinic (primary care)",
            ["calendar/personal/demo-visit", f"{mail}1"],
        ),
        (
            -29,
            "referral",
            "MRI referral received",
            "The imaging center asked the plan for prior authorization before scheduling.",
            "Lakeview Imaging",
            [f"{mail}2"],
        ),
        (-24, "claim", "Prior authorization requested", "", "Harbor Health Plan", [f"{mail}3"]),
        (
            -19,
            "claim",
            "Prior authorization approved",
            "One MRI, valid for 60 days.",
            "Harbor Health Plan",
            [f"{mail}4"],
        ),
        (
            -12,
            "test",
            "MRI of the right knee",
            "",
            "Lakeview Imaging",
            ["calendar/personal/demo-mri", f"{mail}5"],
        ),
        (
            -9,
            "result",
            "MRI report released to the portal",
            "The clinic asked for a follow-up visit to go over it.",
            "Northside Clinic",
            [f"{mail}6"],
        ),
        (
            -7,
            "bill",
            "Statement for the MRI: $1,240 due",
            "Sent before the plan had processed the claim.",
            "Lakeview Imaging (billing)",
            [f"{mail}7"],
        ),
        (
            -5,
            "claim",
            "Claim processed: your share is $185",
            "Billed $1,240; plan discount $810; plan paid $245.",
            "Harbor Health Plan",
            [f"{mail}8"],
        ),
        (
            -3,
            "call",
            "Physical therapy intake booked",
            f"For {c.said(1)} at 9:30.",
            "Riverside Physical Therapy",
            [f"{mail}9", "email/personal/demo-personal-20"],
        ),
    ]
    events = [
        {
            "id": care.event_id(c.day(days), kind, title),
            "date": c.day(days),
            "kind": kind,
            "title": title,
            "detail": detail,
            "with": who,
            "evidence": evidence,
        }
        for days, kind, title, detail, who, evidence in timeline
    ]
    open_items = [  # (title, kind, waiting on, next step, due, status, evidence)
        (
            "Send the MRI report to Riverside PT before the intake",
            "records",
            "me",
            (
                "Ask Northside through the portal to send the report, or download it and email it to "
                "the front desk."
            ),
            c.day(1),
            "open",
            [f"{mail}9", f"{mail}6"],
        ),
        (
            "Lakeview's bill doesn't match the plan's statement",
            "bill",
            "me",
            (
                "Call Lakeview billing: the plan's statement says you owe $185, the bill says $1,240. "
                "Ask them to apply the plan's adjustment and send a new statement."
            ),
            c.day(23),
            "open",
            [f"{mail}7", f"{mail}8"],
        ),
        (
            "Book the follow-up visit to go over the MRI",
            "appointment",
            "me",
            "Book through the portal; ask for a slot after the first PT session.",
            c.day(10),
            "open",
            [f"{mail}6"],
        ),
        (
            "Check the plan has the PT referral on file",
            "referral",
            "provider",
            "Northside sends the referral to Harbor; ask Riverside at the intake whether it shows.",
            None,
            "waiting",
            [f"{mail}1", f"{mail}9"],
        ),
        ("Prior authorization for the MRI", "claim", "insurer", "", None, "done", [f"{mail}4"]),
    ]
    items = []
    for title, kind, waiting, step, due, status, evidence in open_items:
        items.append(
            {
                "id": care.item_id(title, kind, None),
                "title": title,
                "kind": kind,
                "waiting_on": waiting,
                "next_step": step,
                "due": due,
                "status": status,
                "evidence": evidence,
            }
        )
    report, bill, follow_up = (i["id"] for i in items[:3])
    scripts = [
        (
            report,
            "portal_message",
            "Portal message to Northside Clinic",
            (
                f"Hello, could you send my MRI report from {c.said(-12)} to Riverside Physical Therapy "
                f"before my intake there on {c.said(1)}? Their front desk takes records by email or "
                "fax. Thank you, Tess Ray"
            ),
        ),
        (
            bill,
            "call",
            "Call Lakeview Imaging billing",
            (
                "- I'm calling about a statement for an MRI on "
                f"{c.said(-12)}; the account number is on the statement.\n"
                "- The statement asks for $1,240. Harbor Health Plan processed the claim on "
                f"{c.said(-5)} and says my share is $185.\n"
                "- Could you apply the plan's adjustment and send a corrected statement?\n"
                "- Until then, can the account be held so it doesn't go to collections?\n"
                "- Note the name of the person you spoke with and the date."
            ),
        ),
        (
            follow_up,
            "portal_message",
            "Ask for a follow-up appointment",
            (
                "Hello, I'd like to book a follow-up visit to go over my knee MRI. Mornings suit me "
                "best, ideally after my first physical therapy session. Thank you, Tess Ray"
            ),
        ),
    ]
    brief = f"""# Visit brief: right knee

**Tess Ray** · follow-up after MRI · prepared {c.said(0)}

## What happened
- {c.said(-38)}: right knee sore after an 18 km run, outside of the knee, worse on stairs.
- {c.said(-30)}: primary care at Northside Clinic; MRI and physical therapy ordered.
- {c.said(-12)}: MRI of the right knee at Lakeview Imaging. Report in the portal since
  {c.said(-9)}.
- {c.said(1)}: physical therapy intake at Riverside PT.

## Since then
- No running since {c.said(-33)}. Walking is fine; easy indoor cycling 2 to 3 times a week.

## Questions
1. What does the MRI report mean for getting back to running?
2. Is cycling fine in the meantime, and how hard?
3. Does anything in the report change the physical therapy plan?
"""
    # Each record cited, by its memory id (its raw folder, then its own id), with when it's from.
    when = {
        f"{folder}/{r['id']}": r["ts"]
        for folder, records in (
            ("email/personal", _home_mail(c)),
            ("calendar/personal", _home_calendar(c)),
            ("notes/pages", _notes(c)),
        )
        for r in records
    }
    cited = {
        ref: {"source": ref.split("/")[0], "ts": when[ref]}
        for listed in (*(e["evidence"] for e in events), *(i["evidence"] for i in items))
        for ref in listed
    }
    _write_json(
        vault / "clones" / "care" / "care.json",
        {
            "generated": c.ago(7),
            "summary": (
                f"Right-knee pain since a long run on {c.said(-38)} led to a primary care visit, "
                "an MRI at Lakeview Imaging and a referral to physical therapy. The MRI report is "
                "in the portal, and the clinic wants a follow-up visit to go over it. The "
                f"physical therapy intake is {c.said(1)} at 9:30, and they'd like the report "
                "first. Lakeview's bill asks for $1,240, while the plan's statement says $185 is "
                "yours."
            ),
            "timeline": events,
            "open_items": items,
            "scripts": [
                {
                    "id": care.script_id(item, kind, title),
                    "item_id": item,
                    "kind": kind,
                    "title": title,
                    "body": body,
                }
                for item, kind, title, body in scripts
            ],
            "visit_brief": brief,
            "cited": cited,
            "records": {"email": 11, "calendar": 3, "notes": 1},
        },
    )


def _advice(vault: Path, c: _Clock) -> None:
    found = [  # (area, pattern, suggestion, why, confidence, evidence)
        (
            "routine",
            (
                "Your runs were mornings; since the knee, your rides and walks have drifted to late "
                "evenings, and on those days you message later at night."
            ),
            "Move two of the week's rides back to before work.",
            "Mornings were when your training held up; evenings now push into sleep.",
            "medium",
            ["strava", "whatsapp"],
        ),
        (
            "work",
            (
                "Review requests from Eli and Ben arrive early in the week, and you answer them the "
                "night before they're due."
            ),
            "Keep 45 minutes on Tuesday mornings for reviews.",
            "Three of the last four reviews went out after 10 pm.",
            "high",
            ["email", "calendar"],
        ),
        (
            "people",
            "Plans with Dee and the family are mostly made in the 24 hours before.",
            "Suggest a standing first-Saturday dinner to Dee.",
            "Dee organizes most of it; a fixed date takes that off her.",
            "low",
            ["whatsapp"],
        ),
    ]
    suggestions = [
        {
            "id": advisor.suggestion_id(area, suggestion),
            "area": area,
            "pattern": pattern,
            "suggestion": suggestion,
            "why": why,
            "confidence": confidence,
            "evidence": evidence,
        }
        for area, pattern, suggestion, why, confidence, evidence in found
    ]
    _write_json(
        vault / "clones" / "advisor" / f"{c.day(0)}.json",
        {"generated": c.ago(8), "suggestions": suggestions},
    )


def _ideas(vault: Path, c: _Clock) -> None:
    def key(*parts: str) -> str:
        return tracker.item_id("https://example.org/demo/idea/" + "/".join(parts))

    outreach = [
        (
            "Wes Tran",
            "He leads forecasting at Beta Corp, where Fay is hiring for a lead.",
            "Ask what their forecasting stack and team look like before you talk to Fay.",
            "linkedin",
        ),
        (
            "Hana Ito",
            "You both want calibrated forecasts in production at Acme.",
            "Propose pairing on cohort recalibration for the churn model.",
            "email",
        ),
        (
            "Pia Holt",
            "She teaches forecasting at Northfield and invites practitioners.",
            "Offer a guest session on churn models in production.",
            "linkedin",
        ),
    ]
    _write_json(
        vault / "clones" / "network" / "ideas.json",
        {
            "generated": c.ago(30),
            "projects": [
                {
                    "id": key("project", "calibration"),
                    "title": "Open-source the cohort calibration notebook",
                    "pitch": "Turn the churn model's recalibration step into a small library.",
                    "why_you": "You've done it once already, and the reading group wants it.",
                    "people": ["Kai Lund", "Hana Ito"],
                    "first_step": "Write the README with Kai's cohort definitions as the example.",
                },
                {
                    "id": key("project", "pace"),
                    "title": "A pace-group planner for the Sunday Runners",
                    "pitch": "Suggest groups and routes from each runner's recent pace.",
                    "why_you": "You know the club and the data, and Gus plans it by hand.",
                    "people": ["Gus Hale", "Ivy Chen"],
                    "first_step": "Ask Gus what makes the groups hard to plan.",
                },
            ],
            "outreach": [
                {
                    "id": key("outreach", name),
                    "person_id": network.person_id(name),
                    "name": name,
                    "why": why,
                    "ask": ask,
                    "channel": channel,
                }
                for name, why, ask, channel in outreach
            ],
            "to_read": [
                {
                    "id": key("read", "okoye"),
                    "name": "R. Okoye",
                    "why": "Wrote the cohort calibration paper at the top of your feed.",
                }
            ],
        },
    )


def _drafts(vault: Path, c: _Clock) -> None:
    folder = vault / "clones" / "drafts"
    task_ids = {t["title"]: t["id"] for t in _load(vault / "clones" / "tasks" / "tasks.json")}
    drafts = [
        {
            "id": "reply-cy-doe",
            "title": "Reply to Cy about the stove and the 10k",
            "kind": "reply",
            "for": "reply",
            "channel": "whatsapp",
            "to": "Cy Doe",
            "created": c.ago(3),
            "status": "draft",
            "found": "",
            "asks": ["Are you signing up for the November 10k?"],
            "body": "Of course, it's yours for the trip! I'll drop it round on Thursday.\n\n"
            "The 10k depends on what the physio says tomorrow. Tell Lia I'll know by Friday",
        },
        {
            "id": "reply-ben-ode",
            "title": "Reply to Ben with the slides plan",
            "kind": "reply",
            "for": "reply",
            "channel": "email",
            "to": "Ben Ode",
            "created": c.ago(20),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "Hi Ben,\n\nYes, I'll add the calibration plot. The deck with the November "
            "cohort on its own will be in the shared folder by Wednesday evening.\n\nTess",
        },
        {
            "id": task_ids["Comment on Eli's Q4 planning doc"],
            "title": "Comments on the Q4 planning doc",
            "kind": "doc",
            "for": "task",
            "channel": "email",
            "to": "Eli Park",
            "created": c.ago(9),
            "status": "draft",
            "found": "",
            "asks": ["How many forecasting requests did the team turn down this quarter?"],
            "body": "Hi Eli,\n\nThe headcount ask looks right to me, with one change:\n\n"
            "- **Forecasting.** One more person covers the weekly retrains the product teams "
            "keep asking for. Without them we keep saying no to about [N] requests a quarter.\n"
            "- **Cohorts.** Kai's new definitions should be in the plan's assumptions.\n"
            "- **Timing.** Hiring in Q1 lines up with the offsite's roadmap.\n\nTess",
        },
        {
            "id": "care-portal-report",
            "title": "Portal message: send the MRI report to Riverside PT",
            "kind": "email",
            "for": "care",
            "channel": "other",
            "to": "Northside Clinic",
            "created": c.ago(7),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": f"Hello, could you send my MRI report from {c.said(-12)} to Riverside "
            f"Physical Therapy before my intake there on {c.said(1)}? Their front desk takes "
            "records by email or fax.\n\nThank you,\nTess Ray",
        },
        {
            "id": task_ids["Book the back room at Fern Cafe for the club social"],
            "title": "Book the back room at Fern Cafe",
            "kind": "checklist",
            "for": "task",
            "channel": "in_person",
            "to": "Fern Cafe",
            "created": c.ago(9),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "- Call Fern Cafe before Wednesday\n- Back room, next Friday from 7, about "
            "20 people\n- Ask about a set menu or a tab\n- Tell Gus in the club chat once booked",
        },
        {
            "id": "outreach-wes-tran",
            "title": "Ask Wes Tran about forecasting at Beta Corp",
            "kind": "email",
            "for": "outreach",
            "channel": "linkedin",
            "to": "Wes Tran",
            "created": c.ago(30),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "Hi Wes, Fay mentioned the forecasting lead role on your team. Before we "
            "talk, I'd love to hear how you run forecasting today: what's in production, and "
            "what you'd change first. Twenty minutes next week?\n\nTess",
        },
        {
            "id": "reading-calibrated-churn",
            "title": "Reading note: calibrated churn forecasts",
            "kind": "doc",
            "for": "reading",
            "channel": "other",
            "to": "",
            "created": c.ago(5),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "**Claim.** Per-cohort recalibration on a small held-out set beats a full "
            "retrain when only the base rate moves.\n\n**For us.** The November cohort lost "
            "its trial users, which moves the base rate. Try it before Thursday's review.",
        },
        {
            "id": "reply-dee-fay",
            "title": "Reply to Dee about Saturday",
            "kind": "reply",
            "for": "reply",
            "channel": "whatsapp",
            "to": "Dee Fay",
            "created": c.ago(26),
            "status": "sent",
            "found": "",
            "asks": [],
            "body": "Yes! I'll get Leo at 6:30",
        },
    ]
    for draft in drafts:
        work._write(folder / f"{draft['id']}.md", work.render(draft | {"thread": None}))
    # Two weeks of reviews, of drafts since replaced: (draft, its actions, hours ago).
    reviewed = [
        ("demo-1", ("approve", "sent"), 300),
        ("demo-2", ("edit", "sent"), 280),
        ("demo-3", ("discard",), 250),
        ("demo-4", ("approve", "sent"), 200),
        ("demo-5", ("copy",), 190),
        ("demo-6", ("approve", "sent"), 150),
        ("demo-7", ("edit", "approve"), 120),
        ("demo-8", ("approve", "sent"), 90),
        ("demo-9", ("discard",), 60),
        ("demo-10", ("approve", "sent"), 40),
        ("reply-dee-fay", ("sent",), 25),
    ]
    work._write(
        folder / "feedback.jsonl",
        "".join(
            json.dumps({"draft_id": draft, "action": action, "ts": c.ago(hours - k / 60)}) + "\n"
            for draft, actions, hours in reviewed
            for k, action in enumerate(actions)
        ),
    )
    measured = [  # (source, to, closeness)
        ("whatsapp", "Dee Fay", 1.0),
        ("whatsapp", "Cy Doe", 0.92),
        ("whatsapp", "Gus Hale", 0.88),
        ("whatsapp", "Dee Fay", 0.97),
        ("email", "Ben Ode", 0.71),
        ("email", "Kai Lund", 0.84),
        ("whatsapp", "Mei Ray", 0.79),
    ]
    by_source: dict[str, list[float]] = {}
    for source, _, closeness in measured:
        by_source.setdefault(source, []).append(closeness)
    _write_json(
        folder / "fidelity.json",
        {
            "generated": c.ago(1),
            "by_source": {
                s: {"n": len(v), "mean": round(sum(v) / len(v), 3)} for s, v in by_source.items()
            },
            "drafts": [
                {
                    "id": f"demo-m{n}",
                    "source": source,
                    "to": to,
                    "drafted": c.ago(30 + 20 * n),
                    "sent": c.ago(29 + 20 * n),
                    "closeness": closeness,
                }
                for n, (source, to, closeness) in enumerate(measured)
            ],
        },
    )


def _errands(vault: Path, c: _Clock) -> None:
    def errand(start_hours: float, goal: str, steps: list[tuple[str, str]], **fields) -> dict:
        """An errand as errands.py saves it: carried as far as it went, a step every few
        seconds, and stopped one tap short unless it has been sent."""
        began = c.now - timedelta(hours=start_hours)
        record = {"id": f"errand-{began:%Y%m%dT%H%M%SZ}", "goal": goal, "created": _iso(began)}
        record |= fields
        record["status"] = errands._status(record)
        record["summary"] = errands.summary(record)
        if record["status"] != "sent":
            steps = [*steps, ("Stopped one tap short", record["summary"])]
        record["steps"] = [
            {"at": _iso(began + timedelta(seconds=9 * k)), "title": title, "detail": detail}
            for k, (title, detail) in enumerate(steps)
        ]
        record["updated"] = record["steps"][-1]["at"]
        return record

    def message(role: str, to: str, address: str, subject: str, body: str, **more) -> dict:
        return {
            "role": role,
            "to": to,
            "channel": "email",
            "address": address,
            "via": "apple_mail" if address else "",
            "chat": None,
            "evidence": more.pop("evidence", ""),
            "subject": subject,
            "body": body,
            "attach": False,
            "state": "ready" if address else "waiting",
            "sent_at": "",
        } | more

    fay = ADDRESS["Fay Moss"]
    cv = {
        "name": "Tess_Ray_CV.pdf",
        "path": "",
        "made": c.at(-150, 12, 0),
        "where": "~/Documents",
        "notes": ["It says “Senior Data Scientist, 2022 to now”; now: leads the forecasting work"],
    }
    found = [
        errand(
            2,
            "Reach Fay Moss at Beta Corp about the data science lead role, with my CV",
            [
                (
                    "Read the errand",
                    (
                        "Reach Fay Moss at Beta Corp: say you're interested in the data science lead "
                        "role. By email. With your CV."
                    ),
                ),
                (
                    "Looked them up",
                    (
                        "2 records name them. The network knows them as: LinkedIn connection (Talent "
                        "Partner at Beta Corp). People you know at Beta Corp: Wes Tran, Forecasting "
                        "Lead."
                    ),
                ),
                (
                    "Looked for a way to reach them",
                    (
                        f"Fay Moss: {fay}, known because they wrote from it ({c.day(-16)}, “Data "
                        "science lead role at Beta Corp”)."
                    ),
                ),
                (
                    "Found your CV",
                    (
                        f"Tess_Ray_CV.pdf, made {c.day(-150)}, from ~/Documents: the newest PDF named CV "
                        "or resume with your name in it."
                    ),
                ),
                (
                    "Read how you write these",
                    (
                        f"1 of your earlier emails with a CV attached: “Application: Senior Data "
                        f"Scientist” ({c.day(-60)})."
                    ),
                ),
                (
                    "Wrote it",
                    "It answers her note from two weeks ago, which you said you'd come back to.",
                ),
                ("Checked the CV", "Out of date: " + cv["notes"][0]),
            ],
            person="Fay Moss",
            org="Beta Corp",
            purpose="Say you're interested in the data science lead role.",
            channel="email",
            who="Fay Moss, Talent Partner at Beta Corp, who wrote to you about the role.",
            why="It answers her note from two weeks ago, which you said you'd come back to.",
            needs=["Say when you're free for a call?"],
            cv=cv,
            messages=[
                message(
                    "main",
                    "Fay Moss",
                    fay,
                    "Re: Data science lead role at Beta Corp",
                    "Hi Fay,\n\nThank you for your patience. I'd like to hear more about the "
                    "lead role on the forecasting team. My CV is attached; I lead the churn and "
                    "demand forecasting work at Acme Labs.\n\nWould a call next week suit you?"
                    "\n\nBest,\nTess",
                    evidence=f"they wrote from it ({c.day(-16)}, “Data science lead role at "
                    "Beta Corp”)",
                    attach=True,
                )
            ],
        ),
        errand(
            27,
            "Ask Omar Said at Delta Analytics about speaking at the forecasting meetup",
            [
                (
                    "Read the errand",
                    "Reach Omar Said at Delta Analytics: offer a talk at the forecasting meetup.",
                ),
                (
                    "Looked them up",
                    (
                        "1 record names them. People you know at Delta Analytics: Uma Rao, Data "
                        "Scientist; Raj Mehta, Principal Scientist."
                    ),
                ),
                (
                    "Looked for a way to reach them",
                    (
                        "No email from or to Omar Said in your mail, and no chat with them through "
                        "Beeper. An address isn't guessed, so the message waits for one."
                    ),
                ),
                (
                    "Read how you write these",
                    "None of your emails had a CV attached, so it follows your voice alone.",
                ),
                ("Wrote it", "Uma mentioned Omar runs the speaker list, so she can introduce you."),
            ],
            person="Omar Said",
            org="Delta Analytics",
            purpose="Offer a talk at the forecasting meetup.",
            channel="any",
            who="Omar Said runs the meetup's speaker list, as Uma Rao mentioned.",
            why="Uma mentioned Omar runs the speaker list, so she can introduce you.",
            needs=[],
            cv=None,
            messages=[
                message(
                    "main",
                    "Omar Said",
                    "",
                    "A talk for the forecasting meetup",
                    "Hi Omar,\n\nUma Rao mentioned you run the meetup's speaker list. I'd be glad "
                    "to give a talk on calibrating churn forecasts when cohorts shift: what broke "
                    "for us at Acme Labs and the small fix that held up.\n\nTess",
                ),
                message(
                    "intro",
                    "Uma Rao",
                    ADDRESS["Uma Rao"],
                    "An introduction to Omar?",
                    "Hi Uma,\n\nYou mentioned Omar runs the speaker list for the meetup. Would "
                    "you introduce us? I'd like to offer a talk on churn calibration.\n\n"
                    "Thanks!\nTess",
                    evidence=f"they wrote from it ({c.day(-40)}, “Slides from the meetup”)",
                ),
            ],
        ),
    ]
    sent = errand(
        52,
        "Send Kai the notebook for the cohort rerun",
        [
            ("Read the errand", "Reach Kai Lund at Acme Labs: send the cohort rerun notebook."),
            ("Looked them up", "9 records name them."),
            (
                "Looked for a way to reach them",
                (
                    f"Kai Lund: {ADDRESS['Kai Lund']}, known because they wrote from it "
                    f"({c.day(-13)}, “Re: cohort definitions”)."
                ),
            ),
            ("Wrote it", "Short, as your work emails to Kai are."),
            ("Stopped one tap short", "Ready to send to Kai Lund: press Send, or edit it first."),
            ("Sent", f"You pressed Send: it went to Kai Lund ({ADDRESS['Kai Lund']})."),
        ],
        person="Kai Lund",
        org="Acme Labs",
        purpose="Send the cohort rerun notebook.",
        channel="email",
        who="Kai Lund, Data Engineer at Acme Labs.",
        why="Short, as your work emails to Kai are.",
        needs=[],
        cv=None,
        messages=[
            message(
                "main",
                "Kai Lund",
                ADDRESS["Kai Lund"],
                "Cohort rerun notebook",
                "Hi Kai,\n\nHere's the notebook for the rerun on your new cohort definitions. "
                "The November numbers are in the last cell.\n\nThanks,\nTess",
                state="sent",
                sent_at=c.ago(51),
            )
        ],
    )
    for record in [*found, sent]:
        _write_json(vault / "clones" / "errands" / f"{record['id']}.json", record)


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]
