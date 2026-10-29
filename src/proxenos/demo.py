"""`proxenos demo [PATH]`: a vault of made-up records, to try the page without your own data.

The vault is Joe Bloggs's, and he doesn't exist: an operations manager at Acme Furniture who goes
to a pottery class on Thursdays, keeps a plot at the community garden and is partway through
sorting out the bill for new glasses. What the ingesters would bring in is written to raw/ in
their formats, dated around today: WhatsApp chats and groups, two mail accounts, two calendars,
walks, listening, notes and LinkedIn connections. What the model would write from them is written
the way each clone writes it: the self-model, a feed, tasks, care, advice, network ideas, drafts
and errands. Then the steps that need no model run on it as they would on a real vault: the
memory index, the people index, today's recall and the outbox's track record.

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
NAME = "Joe Bloggs"
HOME_MAIL = "joe.bloggs@example.com"
WORK_MAIL = "joe.bloggs@acmefurniture.example"
# The settings a real vault's .env would hold, set while the demo is built.
PERSON = {
    "PROXENOS_NAME": NAME,
    "PROXENOS_FULL_NAME": NAME,
    "PROXENOS_EMAILS": f"{HOME_MAIL},{WORK_MAIL}",
}

# Who Joe knows: a mail address each, and a WhatsApp number for the ones he chats with.
ADDRESS = {
    "Ben Ode": "ben.ode@acmefurniture.example",
    "Eli Park": "eli.park@acmefurniture.example",
    "Kai Lund": "kai.lund@acmefurniture.example",
    "Hana Ito": "hana.ito@acmefurniture.example",
    "Nia Cole": "nia.cole@acmefurniture.example",
    "Tom Wu": "tom.wu@acmefurniture.example",
    "Fay Moss": "fay.moss@betacorp.example",
    "Uma Rao": "uma.rao@deltafreight.example",
    "Dee Fay": "dee.fay@example.net",
    "Mei Bloggs": "mei.bloggs@example.net",
    "Leo Bloggs": "leo.bloggs@example.net",
}
JID = {
    name: f"1555555{n:04d}@s.whatsapp.net"
    for n, name in enumerate(
        ["Cy Doe", "Dee Fay", "Gus Hale", "Ivy Chen", "Jon Reyes", "Lia Ruiz", "Max Bell"]
        + ["Mei Bloggs", "Leo Bloggs"],
        start=101,
    )
}
POTTERY = ("120363000000000101@g.us", "Thursday pottery class")
FAMILY = ("120363000000000102@g.us", "Bloggs family")
EYES = ("Cedar Eye Care", "frontdesk@cedareyecare.example")
OPTICAL = ("Juniper Optical", "orders@juniperoptical.example")
BILLING = ("Juniper Optical Billing", "billing@juniperoptical.example")
PLAN = ("Brightline Vision Plan", "claims@brightlinevision.example")


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
    with _as_joe():
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
def _as_joe() -> Iterator[None]:
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
    store.merge_monthly(_walks(c), raw / "strava" / "activities")
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
        "clay": (*POTTERY, "group"),
        "fam": (*FAMILY, "group"),
    }
    said = [  # (chat, when, who wrote it, or None for Joe, text)
        (
            "cy",
            c.at(-9, 19, 12),
            "Cy Doe",
            "Are you still up for the lake trip the weekend after next?",
        ),
        ("cy", c.at(-9, 19, 40), None, "Yes! I'll ask Max to keep an eye on my garden plot"),
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
            "Also Lia wants to know how many pieces you're putting in the holiday sale",
        ),
        (
            "dee",
            c.at(-6, 18, 30),
            "Dee Fay",
            "Mum's birthday dinner Saturday at 7? I can book the Thai place",
        ),
        ("dee", c.at(-6, 21, 2), None, "Saturday works. Book it, I'll bring the cake"),
        ("dee", c.at(-1, 12, 20), "Dee Fay", "Booked for 7! Can you pick up Leo on the way?"),
        (
            "gus",
            c.at(-12, 9, 10),
            "Gus Hale",
            "Your bowls came through the bisque firing! Glaze them on Thursday?",
        ),
        ("gus", c.at(-12, 9, 30), None, "Great news! Yes, I'll bring the blue glaze"),
        (
            "gus",
            c.at(-3, 17, 45),
            "Gus Hale",
            "Could you book the back room at Fern Cafe for the class social next Friday? You know the owner",
        ),
        ("gus", c.at(-3, 18, 2), None, "Sure, I'll call them this week"),
        (
            "clay",
            c.at(-14, 18, 2),
            "Gus Hale",
            "Kiln firing on Sunday: pieces on the drying shelf by the end of Thursday's class",
        ),
        ("clay", c.at(-14, 18, 15), "Ivy Chen", "Mine are on the shelf!"),
        ("clay", c.at(-14, 18, 20), "Jon Reyes", "Mine need one more night to dry"),
        (
            "clay",
            c.at(-14, 19, 0),
            None,
            "Two bowls and a mug on the top shelf",
        ),
        (
            "clay",
            c.at(-7, 18, 5),
            "Gus Hale",
            "The firing went well, pieces are on the shelf. Class social is next Friday, details soon",
        ),
        (
            "clay",
            c.at(-7, 18, 30),
            "Lia Ruiz",
            "Who's putting pieces in the December holiday sale? Gus needs numbers by Friday",
        ),
        ("clay", c.at(-7, 18, 41), "Max Bell", "Me"),
        ("clay", c.at(-7, 19, 3), "Cy Doe", "Me too"),
        ("clay", c.at(-1, 19, 0), "Ivy Chen", "This Thursday's class starts at 6:30, not 7"),
        ("fam", c.at(-10, 19, 0), "Mei Bloggs", "Did you get the new glasses?"),
        ("fam", c.at(-10, 19, 20), None, "Yes! Dark green frames. I'll send a photo"),
        ("fam", c.at(-4, 9, 0), "Leo Bloggs", "Photos from the weekend are in the shared album"),
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
        POTTERY: ["Gus Hale", "Ivy Chen", "Jon Reyes", "Lia Ruiz", "Max Bell", "Cy Doe"],
        FAMILY: ["Dee Fay", "Mei Bloggs", "Leo Bloggs"],
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
    """One message as the mail ingesters write it; `sender` None is Joe's own."""
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
    news = ("Ops Weekly", "news@opsweekly.example")
    issues = [
        "suppliers who are always late",
        "the true cost of a half-empty truck",
        "when to say no to a rush order",
        "warehouse layouts that work",
        "a field guide to the holiday peak",
    ]
    mail = [
        (
            c.at(-38, 9, 0),
            EYES,
            "Time for your eye exam",
            (
                "It's been two years since your last eye exam. Book online or call us; your vision "
                "plan covers one routine exam a year."
            ),
        ),
        (
            c.at(-30, 13, 5),
            EYES,
            "Your new prescription",
            (
                f"Thanks for coming in on {c.said(-30)}. Your exam found a small change in your "
                "prescription, and your new glasses prescription is attached. Take it to any "
                "optical shop."
            ),
        ),
        (
            c.at(-29, 10, 40),
            PLAN,
            "Your vision benefits",
            (
                "You're due for new glasses. At in-network shops such as Juniper Optical, the plan "
                "pays for lenses after a $25 copay and gives a $150 allowance toward frames."
            ),
        ),
        (
            c.at(-24, 13, 20),
            OPTICAL,
            "Your order is in",
            (
                f"Thanks for your order on {c.said(-24)}: dark green frames and single-vision "
                "lenses with an anti-glare coating. We'll email you when they're ready, in about "
                "ten days."
            ),
        ),
        (
            c.at(-14, 11, 0),
            OPTICAL,
            "Your glasses are ready",
            "Your new glasses are ready to pick up. We're open every day but Sunday.",
        ),
        (
            c.at(-12, 14, 0),
            OPTICAL,
            "Thanks for picking up your glasses",
            (
                "New frames can slip or pinch as they settle. Book a free fitting any time and "
                "we'll adjust them."
            ),
        ),
        (
            c.at(-7, 8, 0),
            BILLING,
            "Your statement is ready",
            (
                f"Amount due: $420.00 for frames and lenses picked up on {c.said(-12)}. Payment "
                f"due {c.said(23)}. Questions about this bill? Call billing, Monday to Friday."
            ),
        ),
        (
            c.at(-5, 7, 45),
            PLAN,
            "Your Explanation of Benefits",
            (
                f"Claim processed for Juniper Optical, {c.said(-12)}. Billed $420.00: frames "
                "$220.00, lenses $200.00. Plan paid $325.00. Your share: $95.00 (a $25.00 lens "
                "copay and $70.00 over the frame allowance). This is not a bill."
            ),
        ),
        (
            c.at(-3, 15, 10),
            OPTICAL,
            f"Your fitting is booked: {c.said(1)} at 9:30",
            "Please bring your new glasses and their case. A fitting takes about 15 minutes.",
        ),
        (
            c.at(-16, 9, 5),
            _person("Fay Moss"),
            "Operations lead role at Beta Corp",
            (
                "Hi Joe, I lead hiring for our operations team, and your talk on getting holiday "
                "orders out on time came up twice this week. Would you be open to a chat about "
                "the lead role?"
            ),
        ),
        (
            c.at(-40, 18, 0),
            _person("Uma Rao"),
            "Slides from the meetup",
            (
                "Great to meet you at the supply chain meetup! Here are my slides. Omar Said on "
                "our team keeps the speaker list, if you ever want to give a talk."
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
            f"Re: Your fitting is booked: {c.said(1)} at 9:30",
            "Thanks, see you then. Could you also look at my bill? The plan's statement says my "
            "share is $95.",
            to=[OPTICAL[1]],
        ),
        _mail(
            "personal",
            21,
            c.at(-15, 8, 50),
            None,
            "Re: Operations lead role at Beta Corp",
            "Hi Fay, thanks for reaching out. It's a busy month; could I come back to you at "
            "the end of it?",
            to=[ADDRESS["Fay Moss"]],
        ),
        _mail(
            "personal",
            22,
            c.at(-60, 10, 0),
            None,
            "Application: Senior Operations Manager",
            "Dear hiring team, I'd like to apply for the Senior Operations Manager role. I look "
            "after suppliers, the warehouse and deliveries at Acme Furniture. My CV is attached.",
            to=["jobs@deltafreight.example"],
            attachments=["Joe_Bloggs_CV.pdf"],
        ),
    ]
    records += [
        _mail(
            "personal",
            30 + i,
            c.at(-2 - 7 * i, 6, 30),
            news,
            f"Ops Weekly: {issue}",
            f"This week: {issue}, three reads worth your time, and a chart we can't stop "
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
            "Delivery dates for Thursday",
            (
                "Hi Joe, could you send the delivery dates for the holiday catalog before the "
                "review? Eli wants the oak dining tables on their own, since the supplier is late."
            ),
        ),
        (
            c.at(-2, 16, 48),
            "Ben Ode",
            "Re: Delivery dates for Thursday",
            "Great, thanks. If you can add the warehouse schedule too, even better.",
        ),
        (
            c.at(-5, 9, 0),
            "Eli Park",
            "Q1 budget doc: comments by Friday?",
            (
                "The draft is in the shared folder. Mostly I'd like to know whether the warehouse "
                "staffing line is right."
            ),
        ),
        (
            c.at(-8, 13, 30),
            "Hana Ito",
            "Next lunch-and-learn",
            "We're picking the topic for next month's lunch-and-learn. Want to suggest one?",
        ),
        (
            c.at(-13, 11, 0),
            "Kai Lund",
            "Re: December shifts",
            "I've added a Saturday shift for December, so the holiday orders go out on time.",
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
            "Trade fair reimbursement",
            "Reminder: receipts for the autumn furniture fair are due by the end of the month.",
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
            "Re: Delivery dates for Thursday",
            "Will do, by Wednesday.",
            to=[ADDRESS["Ben Ode"]],
        ),
        _mail(
            "work",
            21,
            c.at(-8, 14, 5),
            None,
            "Re: Next lunch-and-learn",
            "How about Kai showing the new warehouse scanners? Short and useful.",
            to=[ADDRESS["Hana Ito"], ADDRESS["Kai Lund"], ADDRESS["Nia Cole"]],
        ),
        _mail(
            "work",
            22,
            c.at(-13, 11, 40),
            None,
            "Re: December shifts",
            "Thanks Kai, I'll update the warehouse schedule.",
            to=[ADDRESS["Kai Lund"]],
        ),
        _mail(
            "work",
            23,
            c.at(-22, 10, 0),
            None,
            "Re: Trade fair reimbursement",
            "Submitted, thanks Nia!",
            to=[ADDRESS["Nia Cole"]],
        ),
        _mail(
            "work",
            24,
            c.at(-11, 9, 20),
            ("Acme IT", "it-help@acmefurniture.example"),
            "Ticket received: label printer in dispatch",
            "We've received your request and will get back to you within 5 working days.",
        ),
        _mail(
            "work",
            25,
            c.at(-20, 17, 30),
            None,
            "Re: Team offsite next month",
            "Count me in. Could we keep an hour for next year's supplier plan?",
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
        _event("exam", c.at(-30, 10, 0), 30, "Eye exam", EYES[0]),
        _event("frames", c.at(-24, 12, 30), 45, "Choose new frames", OPTICAL[0]),
        _event("pickup", c.at(-12, 12, 30), 15, "Pick up glasses", OPTICAL[0]),
        _event("fitting", c.at(1, 9, 30), 30, "Glasses fitting", OPTICAL[0]),
        _event(
            "dinner",
            c.at(3, 19, 0),
            150,
            "Mum's birthday dinner",
            "Thai Garden",
            ("Dee Fay", "Mei Bloggs", "Leo Bloggs"),
        ),
    ]
    events += [
        _event(f"pottery{-days}", c.at(days, 19, 0), 120, "Pottery class", "The clay studio")
        for days in (-28, -21, -14, -7)
    ]
    return events


def _work_calendar(c: _Clock) -> list[dict]:
    team = ("Ben Ode", "Kai Lund", "Hana Ito")
    events = [
        _event(
            "review", c.at(1, 14, 0), 60, "Holiday catalog review", "Room 3", ("Eli Park", *team)
        ),
        _event(
            "coffee",
            c.soon(3),
            30,
            "Coffee with Hana: next lunch-and-learn",
            "Kitchen",
            ("Hana Ito",),
        ),
        _event(
            "planning",
            c.at(-6, 10, 0),
            90,
            "Q1 budget planning",
            "Room 1",
            ("Eli Park", *team, "Nia Cole"),
        ),
        _event(
            "lunch",
            c.at(-8, 12, 0),
            60,
            "Lunch-and-learn",
            None,
            ("Hana Ito", "Kai Lund", "Nia Cole", "Tom Wu"),
        ),
    ]
    events += [
        _event(f"oneonone{-days}", c.at(days, 11, 0), 30, "1:1 Eli / Joe", None, ("Eli Park",))
        for days in (-19, -12, -5, 2)
    ]
    return events


def _walks(c: _Clock) -> list[dict]:
    done = [  # (days ago, hour, sport, name, km, minutes): fewer lunchtime walks of late
        (44, 12, "Walk", "Lunchtime walk", 3.2, 38),
        (42, 10, "Walk", "Weekend walk by the lake", 8.5, 110),
        (40, 12, "Walk", "Lunchtime walk", 3.0, 36),
        (37, 9, "Walk", "Walk to the community garden", 4.1, 50),
        (35, 10, "Walk", "Weekend walk by the lake", 9.0, 115),
        (33, 12, "Walk", "Lunchtime walk", 3.4, 40),
        (28, 10, "Walk", "Weekend walk by the lake", 8.8, 112),
        (26, 12, "Walk", "Lunchtime walk", 3.1, 37),
        (21, 10, "Walk", "Weekend walk by the lake", 8.2, 104),
        (17, 9, "Walk", "Walk to the community garden", 4.0, 49),
        (14, 10, "Walk", "Weekend walk by the lake", 9.1, 116),
        (7, 10, "Walk", "Weekend walk by the lake", 8.6, 108),
        (3, 12, "Walk", "Lunchtime walk", 3.3, 39),
    ]
    return [
        {
            "id": f"strava:demo{days}",
            "ts": c.at(-days, hour, 0),
            "name": name,
            "sport_type": sport,
            "distance_m": km * 1000,
            "moving_time_s": minutes * 60,
            "elapsed_time_s": minutes * 60 + 120,
        }
        for days, hour, sport, name, km, minutes in done
    ]


def _plays(c: _Clock) -> list[dict]:
    tracks = [
        ("The Lantern Choir", "Porch Lights"),
        ("Mara Vey", "Slow Current"),
        ("Quiet Shore", "Morning Ferry"),
        ("Night Bus Orchestra", "Last Stop"),
        ("Mara Vey", "Folded Boats"),
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
            "glasses",
            c.at(-1, 21, 0),
            "Glasses notes",
            "Health",
            (
                f"{c.said(-30)}: eye exam at Cedar Eye Care. Small change in prescription.\n"
                f"{c.said(-24)}: chose frames at Juniper Optical, dark green, anti-glare lenses.\n"
                f"{c.said(-12)}: picked them up. They slip a little; Juniper offers a free "
                "fitting.\n"
                f"{c.said(-5)}: the plan says my share is $95; Juniper's bill says $420.\n"
                "Questions: Did Juniper apply the plan's allowance? Does the FSA cover the "
                "anti-glare coating? Keep the old pair as a spare?"
            ),
        ),
        (
            "garden",
            c.at(-8, 22, 0),
            "Garden plot",
            "Garden",
            (
                "Garlic in by mid-November. Mulch the beds before the first frost. Ask about "
                "sharing the compost bins. Seeds for spring: beans, chard, sweet peas."
            ),
        ),
        (
            "sale",
            c.at(-50, 20, 0),
            "Pieces for the holiday sale",
            "Pottery",
            (
                "Six mugs, four bowls and a vase by the December sale. Bisque firing every other "
                "Sunday, the glaze firing the week after; the last firing is early December."
            ),
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


# Slack user ids, and the channels Joe is in.
SLACK = {
    "Joe Bloggs": "U0DEMO00",
    "Hana Ito": "U0DEMO01",
    "Kai Lund": "U0DEMO02",
    "Tom Wu": "U0DEMO03",
    "Ben Ode": "U0DEMO04",
}
OPERATIONS = ("C0DEMO01", "operations", "channel")
TOM = ("D0DEMO01", "Tom Wu", "dm")


def _slack(c: _Clock) -> list[dict]:
    said = [  # (channel, when, who, text)
        (
            OPERATIONS,
            c.at(-9, 10, 4),
            "Hana Ito",
            "Lunch-and-learn: topic ideas welcome in the thread",
        ),
        (
            OPERATIONS,
            c.at(-9, 10, 30),
            "Joe Bloggs",
            "Kai's new warehouse scanners? Short and useful",
        ),
        (
            OPERATIONS,
            c.at(-6, 15, 12),
            "Kai Lund",
            "The December Saturday shift is on the rota now",
        ),
        (
            OPERATIONS,
            c.at(-6, 15, 40),
            "Joe Bloggs",
            "Thanks Kai! Updating the warehouse schedule today",
        ),
        (
            OPERATIONS,
            c.at(-2, 11, 0),
            "Ben Ode",
            "Reminder: catalog review Thursday, delivery dates by Wednesday",
        ),
        (
            TOM,
            c.at(-4, 14, 20),
            "Tom Wu",
            "Has IT fixed the label printer yet? Today's shipments are stacking up",
        ),
        (
            TOM,
            c.at(-4, 14, 31),
            "Joe Bloggs",
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
    rosters = {OPERATIONS: list(SLACK), TOM: ["Joe Bloggs", "Tom Wu"]}
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
        ("Ben Ode", "Acme Furniture", "Sales Manager", 3),
        ("Eli Park", "Acme Furniture", "Head of Operations", 3),
        ("Kai Lund", "Acme Furniture", "Warehouse Supervisor", 2),
        ("Hana Ito", "Acme Furniture", "Product Designer", 2),
        ("Nia Cole", "Acme Furniture", "Office Manager", 3),
        ("Tom Wu", "Acme Furniture", "Purchasing Coordinator", 1),
        ("Fay Moss", "Beta Corp", "Talent Partner", 0),
        ("Wes Tran", "Beta Corp", "Head of Operations", 4),
        ("Raj Mehta", "Delta Freight", "Logistics Director", 5),
        ("Uma Rao", "Delta Freight", "Account Manager", 1),
        ("Vic Noor", "Gamma Home", "Buying Director", 4),
        ("Zoe Hart", "Gamma Home", "Store Manager", 2),
        ("Pia Holt", "Willow Interiors", "Interior Designer", 6),
        ("Ivy Chen", "Gamma Home", "Visual Merchandiser", 2),
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

Joe Bloggs is an operations manager at Acme Furniture, a furniture maker, where he looks after
suppliers, the warehouse schedule and deliveries, and works most closely with Ben Ode, Kai Lund
and Hana Ito, for Eli Park. He goes to a pottery class on Thursday evenings and keeps a plot at
the community garden. Family is close: his sister Dee organizes most of it.

- Values: getting the dates right before they're promised; showing up for friends.
- Decides by writing things down first, then asking one trusted person.
- Open now: a recruiter at Beta Corp about a lead role; whether to speak at a meetup.
""",
        "interests": """# Interests

- Suppliers and lead times (high, rising): the oak delay, weekly supplier calls.
- Pottery (high, rising): the Thursday class, pieces for the December holiday sale.
- Gardening (medium, stable): a plot at the community garden.
- Furniture design (medium, stable): flat-pack, packaging.
- Health admin (medium, rising): new glasses, a vision plan claim, an FSA receipt.
""",
        "taste": """# Taste

Reads practical write-ups with photos and real numbers; skips trend pieces. Listens to slow,
warm albums while working and podcasts on walks.
""",
        "voice": """# Voice

- Personal chat: short, warm, exclamation marks, no sign-off. "Saturday works. Book it, I'll
  bring the cake"
- Work chat and email: plain and quick to the point, a date for each promise. "Will do, by
  Wednesday."
- Email to strangers: a greeting, two or three sentences, first name to sign.
""",
        "routines": """# Routines

Work from 9 to 6, supplier calls in the mornings. Pottery class on Thursdays at 7; a lunchtime
walk on good days, and the garden plot on Saturday mornings. Family dinner most Saturdays.
""",
        "open_questions": """# Open questions

- Is the Beta Corp role something he wants, or flattering timing?
- How many pieces can he finish for the holiday sale?
""",
    }
    folder = vault / "self"
    for name, text in files.items():
        work._write(folder / f"{name}.md", text)
    work._write(
        folder / "CHANGELOG.md",
        f"## {c.day(-21)}\n\nFirst self-model.\n\n"
        f"## {c.day(-1)}\n\n"
        "- Pottery moved from medium to high and rising: pieces in every kiln firing, and the "
        "class's holiday sale ahead.\n"
        "- Health admin added as an interest: an eye exam, new glasses and a vision plan claim in "
        "five weeks.\n"
        "- Identity notes the Beta Corp conversation.\n",
    )


def _feed(vault: Path, c: _Clock) -> None:
    latest, earlier = c.ago(5), c.ago(29)
    items = [  # (batch, kind, title, source, authors, score, interest, explore, summary, why)
        (
            latest,
            "paper",
            "Lead times for hardwood furniture, and how makers shorten them",
            "Furniture Trade Journal",
            ["R. Okoye", "M. Lindqvist"],
            0.91,
            "suppliers",
            False,
            (
                "A look at forty workshops: where the weeks go between a timber order and a "
                "delivery, and the habits of the fastest."
            ),
            (
                "Your oak supplier is two weeks behind: this is that problem, and the first fix "
                "is a phone call."
            ),
        ),
        (
            latest,
            "paper",
            "Holiday peaks: staffing a small warehouse for December",
            "Warehouse Practice",
            ["J. Abara", "L. Pinto"],
            0.86,
            "warehouse",
            False,
            "Extra shifts, temporary staff and dispatch cut-offs, with a checklist for each.",
            "Kai just added a Saturday shift for December; this covers the rest of the plan.",
        ),
        (
            latest,
            "post",
            "What we learned from weekly supplier calls",
            "Ops Weekly",
            ["S. Varga"],
            0.74,
            "suppliers",
            False,
            "A year of weekly calls with suppliers: what got better, what didn't, and what to skip.",
            "Close to Eli's budget question on how much time the team spends chasing suppliers.",
        ),
        (
            latest,
            "news",
            "Community garden adds 40 plots and a shared tool shed",
            "City Gazette",
            None,
            0.66,
            "gardening",
            False,
            "The east side garden gets new plots, a tool shed and a rainwater tank.",
            "Your plot is there, and the shared tools save carrying yours.",
        ),
        (
            latest,
            "post",
            "Using an FSA for glasses, explained in one page",
            "Money Basics",
            ["K. Mendes"],
            0.61,
            "health admin",
            True,
            "What counts, which receipts to keep, and what to do when a shop bills before the plan.",
            "Something new: your last month had new glasses, a plan claim and a bill that came early.",
        ),
        (
            latest,
            "paper",
            "Packaging that survives delivery: a guide for furniture makers",
            "Furniture Trade Journal",
            ["D. Ferreira"],
            0.58,
            "furniture design",
            False,
            "Flat-pack boxes and crates tested on real delivery routes, and what broke least.",
            "A way to cut the damaged deliveries Ben hears about every holiday season.",
        ),
        (
            earlier,
            "paper",
            "Designing tables that ship flat",
            "Design Notes",
            ["T. Brandt"],
            0.8,
            "furniture design",
            False,
            "How small makers rework joints so a table ships flat and goes together in minutes.",
            "The holiday catalog's new side table could ship flat; this shows how.",
        ),
        (
            earlier,
            "news",
            "A weekend makers' market opens in the old train depot",
            "City Gazette",
            None,
            0.55,
            "crafts",
            True,
            "Stalls for local makers every Saturday from December.",
            "Something new: a place to sell pottery beyond the class's holiday sale.",
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
            "Send Ben the delivery dates for the holiday catalog",
            (
                "He wants the oak dining tables on their own, since the supplier is late, and the "
                "warehouse schedule if you can, before Thursday's review."
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
            "Comment on Eli's Q1 budget doc",
            "Eli asked mainly whether the warehouse staffing line is right. Comments by Friday.",
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
            "Book the back room at Fern Cafe for the class social",
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
            "Suggest a topic for the lunch-and-learn",
            "You suggested Kai's new warehouse scanners; waiting on Hana to pick.",
            "email",
            "Hana Ito",
            c.at(-8, 13, 30),
            None,
            "low",
            "waiting",
            ["email/work/demo-work-4"],
        ),
        (
            "Label printer in dispatch",
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
            "Send the trade fair receipts to Nia",
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
            "message",
            "Reminder: routine eye exam due",
            "Two years since the last one; the vision plan covers one a year.",
            "Cedar Eye Care",
            [f"{mail}1"],
        ),
        (
            -30,
            "visit",
            "Routine eye exam",
            "A small change in prescription.",
            "Cedar Eye Care",
            ["calendar/personal/demo-exam"],
        ),
        (
            -30,
            "prescription",
            "New glasses prescription",
            "Sent by email, to take to any optical shop.",
            "Cedar Eye Care",
            [f"{mail}2"],
        ),
        (
            -29,
            "message",
            "Vision benefits checked",
            "Lenses after a $25 copay, and $150 toward frames, at in-network shops.",
            "Brightline Vision Plan",
            [f"{mail}3"],
        ),
        (
            -24,
            "visit",
            "Frames and lenses ordered",
            "Dark green frames, single-vision lenses with an anti-glare coating.",
            "Juniper Optical",
            ["calendar/personal/demo-frames", f"{mail}4"],
        ),
        (
            -12,
            "visit",
            "New glasses picked up",
            "They slip a little; the shop offers a free fitting.",
            "Juniper Optical",
            ["calendar/personal/demo-pickup", f"{mail}5", f"{mail}6"],
        ),
        (
            -7,
            "bill",
            "Statement for the glasses: $420 due",
            "Sent without the vision plan's allowance applied.",
            "Juniper Optical (billing)",
            [f"{mail}7"],
        ),
        (
            -5,
            "claim",
            "Claim processed: your share is $95",
            "Billed $420; plan paid $325: lenses less a $25 copay, and $150 toward frames.",
            "Brightline Vision Plan",
            [f"{mail}8"],
        ),
        (
            -3,
            "call",
            "Glasses fitting booked",
            f"For {c.said(1)} at 9:30.",
            "Juniper Optical",
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
            "Get Juniper Optical to rebill through the vision plan",
            "bill",
            "me",
            (
                "Call Juniper billing: the plan's statement says your share is $95, the bill says "
                "$420. Ask them to apply the plan's payment and send a corrected bill."
            ),
            c.day(23),
            "open",
            [f"{mail}7", f"{mail}8"],
        ),
        (
            "Send the itemized receipt to the FSA",
            "claim",
            "provider",
            (
                "Once Juniper has rebilled and you've paid the $95, ask them for an itemized "
                "receipt and send it to the FSA with the plan's statement."
            ),
            None,
            "waiting",
            [f"{mail}8", "email/personal/demo-personal-20"],
        ),
        (
            "Ask whether the FSA covers the anti-glare coating",
            "question",
            "me",
            "Check the FSA's list of eligible expenses, or ask when you send the receipt.",
            None,
            "open",
            ["notes/pages/demo-glasses", f"{mail}4"],
        ),
        (
            "Book a fitting to adjust the new frames",
            "appointment",
            "me",
            "",
            None,
            "done",
            [f"{mail}6", f"{mail}9"],
        ),
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
    rebill, receipt = (i["id"] for i in items[:2])
    scripts = [
        (
            rebill,
            "call",
            "Call Juniper Optical billing",
            (
                "- I'm calling about a statement for glasses picked up on "
                f"{c.said(-12)}; the account number is on the statement.\n"
                "- The statement asks for $420. Brightline Vision Plan processed the claim on "
                f"{c.said(-5)} and says my share is $95.\n"
                "- Could you apply the plan's payment and send a corrected bill?\n"
                "- Once it's paid, could you email an itemized receipt for my FSA?\n"
                "- Note the name of the person you spoke with and the date."
            ),
        ),
        (
            receipt,
            "email",
            "Email Juniper Optical for an itemized receipt",
            (
                f"Hello, once my bill for the glasses I picked up on {c.said(-12)} is corrected to "
                "the $95 Brightline Vision Plan says is mine, could you email me an itemized "
                "receipt showing the frames, the lenses and what I paid? It's for my FSA. Thank "
                "you, Joe Bloggs"
            ),
        ),
        (
            receipt,
            "form",
            "FSA claim: what to fill in",
            (
                "- Expense: prescription glasses, frames and lenses\n"
                "- Provider: Juniper Optical\n"
                f"- Date of service: {c.said(-12)}\n"
                "- Amount: $95.00, your share after the vision plan\n"
                "- Attach: Juniper's itemized receipt and the plan's statement"
            ),
        ),
    ]
    brief = f"""# Visit brief: glasses fitting

**Joe Bloggs** · fitting for new glasses · prepared {c.said(0)}

## What happened
- {c.said(-30)}: routine eye exam at Cedar Eye Care; a small change in prescription.
- {c.said(-24)}: frames and lenses ordered at Juniper Optical, with an anti-glare coating.
- {c.said(-12)}: picked up the new glasses. They slip down a little.
- {c.said(1)}: fitting at Juniper Optical.

## Since then
- Wearing them all day. They slip when looking down, and the left arm presses behind the ear.

## Questions
1. Can the nose pads and arms be adjusted so they stop slipping?
2. Can the bill go through Brightline Vision Plan? The plan says $95 is mine, not $420.
3. Could I have an itemized receipt for my FSA?
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
                f"A routine eye exam at Cedar Eye Care on {c.said(-30)} brought a small change in "
                f"prescription, and new glasses from Juniper Optical were picked up on "
                f"{c.said(-12)}. They slip a little, and the fitting to adjust them is "
                f"{c.said(1)} at 9:30. Juniper's bill asks for $420, while the vision plan's "
                "statement says $95 is yours: the plan's allowance wasn't applied. Once it's "
                "rebilled, the itemized receipt goes to your FSA."
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
            "records": {"email": 10, "calendar": 4, "notes": 1},
        },
    )


def _advice(vault: Path, c: _Clock) -> None:
    found = [  # (area, pattern, suggestion, why, confidence, evidence)
        (
            "routine",
            (
                "Your weekend walks haven't moved, but lunchtime walks have thinned from three a "
                "week to one, and the thin weeks are the ones with late review nights."
            ),
            "Put two lunchtime walks in the calendar, like the Thursday class.",
            "Weekends and Thursdays hold up because they're fixed; the lunchtime walks slip.",
            "medium",
            ["strava", "calendar"],
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
            "He heads operations at Beta Corp, where Fay is hiring for a lead.",
            "Ask how their suppliers and warehouse are set up before you talk to Fay.",
            "linkedin",
        ),
        (
            "Hana Ito",
            "You both want fewer damaged deliveries at Acme.",
            "Propose pairing on flat-pack packaging for the new side table.",
            "email",
        ),
        (
            "Pia Holt",
            "She designs shop interiors and furnishes them from small makers.",
            "Show her the holiday catalog before it goes out.",
            "linkedin",
        ),
    ]
    _write_json(
        vault / "clones" / "network" / "ideas.json",
        {
            "generated": c.ago(30),
            "projects": [
                {
                    "id": key("project", "suppliers"),
                    "title": "A shared supplier tracker",
                    "pitch": "Turn the spreadsheet of supplier dates into one page the team checks.",
                    "why_you": "You chase the dates already, and the lunch-and-learn wants it.",
                    "people": ["Kai Lund", "Hana Ito"],
                    "first_step": "Start with the oak supplier and Kai's delivery dates.",
                },
                {
                    "id": key("project", "kiln"),
                    "title": "A kiln firing planner for the pottery class",
                    "pitch": "Track whose pieces are dry, bisqued and glazed, so each firing is full.",
                    "why_you": "You know the class, and Gus plans the firings by hand.",
                    "people": ["Gus Hale", "Ivy Chen"],
                    "first_step": "Ask Gus what makes the firings hard to plan.",
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
                    "why": "Wrote the piece on lead times at the top of your feed.",
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
            "title": "Reply to Cy about the stove and the holiday sale",
            "kind": "reply",
            "for": "reply",
            "channel": "whatsapp",
            "to": "Cy Doe",
            "created": c.ago(3),
            "status": "draft",
            "found": "",
            "asks": ["How many pieces are you putting in the holiday sale?"],
            "body": "Of course, it's yours for the trip! I'll drop it round on Thursday.\n\n"
            "The sale: a few mugs, I think! Tell Lia I'll know after the next firing",
        },
        {
            "id": "reply-ben-ode",
            "title": "Reply to Ben with the delivery dates plan",
            "kind": "reply",
            "for": "reply",
            "channel": "email",
            "to": "Ben Ode",
            "created": c.ago(20),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "Hi Ben,\n\nYes, I'll add the warehouse schedule. The delivery dates, with the "
            "oak tables on their own, will be in the shared folder by Wednesday evening.\n\nJoe",
        },
        {
            "id": task_ids["Comment on Eli's Q1 budget doc"],
            "title": "Comments on the Q1 budget doc",
            "kind": "doc",
            "for": "task",
            "channel": "email",
            "to": "Eli Park",
            "created": c.ago(9),
            "status": "draft",
            "found": "",
            "asks": ["How many rush orders did the warehouse turn down this quarter?"],
            "body": "Hi Eli,\n\nThe budget looks right to me, with one change:\n\n"
            "- **Warehouse.** One more person on the December shifts covers the holiday orders. "
            "Without them we keep turning down about [N] rush orders a quarter.\n"
            "- **Suppliers.** The oak delay should be in the plan's assumptions.\n"
            "- **Timing.** Hiring in Q1 lines up with the offsite's plans.\n\nJoe",
        },
        {
            "id": "care-receipt",
            "title": "Email: ask Juniper Optical for an itemized receipt",
            "kind": "email",
            "for": "care",
            "channel": "email",
            "to": "Juniper Optical",
            "created": c.ago(7),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": f"Hello, once my bill for the glasses I picked up on {c.said(-12)} is "
            "corrected to the $95 Brightline Vision Plan says is mine, could you email me an "
            "itemized receipt showing the frames, the lenses and what I paid? It's for my FSA."
            "\n\nThank you,\nJoe Bloggs",
        },
        {
            "id": task_ids["Book the back room at Fern Cafe for the class social"],
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
            "20 people\n- Ask about a set menu or a tab\n- Tell Gus in the class chat once booked",
        },
        {
            "id": "outreach-wes-tran",
            "title": "Ask Wes Tran about operations at Beta Corp",
            "kind": "email",
            "for": "outreach",
            "channel": "linkedin",
            "to": "Wes Tran",
            "created": c.ago(30),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "Hi Wes, Fay mentioned the operations lead role on your team. Before we "
            "talk, I'd love to hear how you plan operations today: suppliers, the warehouse, "
            "and what you'd change first. Twenty minutes next week?\n\nJoe",
        },
        {
            "id": "reading-lead-times",
            "title": "Reading note: lead times for hardwood furniture",
            "kind": "doc",
            "for": "reading",
            "channel": "other",
            "to": "",
            "created": c.ago(5),
            "status": "draft",
            "found": "",
            "asks": [],
            "body": "**Claim.** Most of the weeks between a timber order and a delivery are lost "
            "waiting on confirmations, not on making.\n\n**For us.** The oak supplier confirms "
            "once a week. Ask for a confirmation within two days before Thursday's review.",
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
        ("whatsapp", "Mei Bloggs", 0.79),
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
        "name": "Joe_Bloggs_CV.pdf",
        "path": "",
        "made": c.at(-150, 12, 0),
        "where": "~/Documents",
        "notes": ["It says “Operations Manager, 2022 to now”; now: also looks after the warehouse"],
    }
    found = [
        errand(
            2,
            "Reach Fay Moss at Beta Corp about the operations lead role, with my CV",
            [
                (
                    "Read the errand",
                    (
                        "Reach Fay Moss at Beta Corp: say you're interested in the operations lead "
                        "role. By email. With your CV."
                    ),
                ),
                (
                    "Looked them up",
                    (
                        "2 records name them. The network knows them as: LinkedIn connection (Talent "
                        "Partner at Beta Corp). People you know at Beta Corp: Wes Tran, Head of "
                        "Operations."
                    ),
                ),
                (
                    "Looked for a way to reach them",
                    (
                        f"Fay Moss: {fay}, known because they wrote from it ({c.day(-16)}, “Operations "
                        "lead role at Beta Corp”)."
                    ),
                ),
                (
                    "Found your CV",
                    (
                        f"Joe_Bloggs_CV.pdf, made {c.day(-150)}, from ~/Documents: the newest PDF "
                        "named CV or resume with your name in it."
                    ),
                ),
                (
                    "Read how you write these",
                    (
                        f"1 of your earlier emails with a CV attached: “Application: Senior "
                        f"Operations Manager” ({c.day(-60)})."
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
            purpose="Say you're interested in the operations lead role.",
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
                    "Re: Operations lead role at Beta Corp",
                    "Hi Fay,\n\nThank you for your patience. I'd like to hear more about the "
                    "lead role on the operations team. My CV is attached; I look after suppliers, "
                    "the warehouse and deliveries at Acme Furniture.\n\nWould a call next week "
                    "suit you?\n\nBest,\nJoe",
                    evidence=f"they wrote from it ({c.day(-16)}, “Operations lead role at "
                    "Beta Corp”)",
                    attach=True,
                )
            ],
        ),
        errand(
            27,
            "Ask Omar Said at Delta Freight about speaking at the supply chain meetup",
            [
                (
                    "Read the errand",
                    "Reach Omar Said at Delta Freight: offer a talk at the supply chain meetup.",
                ),
                (
                    "Looked them up",
                    (
                        "1 record names them. People you know at Delta Freight: Uma Rao, Account "
                        "Manager; Raj Mehta, Logistics Director."
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
                (
                    "Wrote it",
                    "Uma mentioned Omar keeps the speaker list, so she can introduce you.",
                ),
            ],
            person="Omar Said",
            org="Delta Freight",
            purpose="Offer a talk at the supply chain meetup.",
            channel="any",
            who="Omar Said keeps the meetup's speaker list, as Uma Rao mentioned.",
            why="Uma mentioned Omar keeps the speaker list, so she can introduce you.",
            needs=[],
            cv=None,
            messages=[
                message(
                    "main",
                    "Omar Said",
                    "",
                    "A talk for the supply chain meetup",
                    "Hi Omar,\n\nUma Rao mentioned you keep the meetup's speaker list. I'd be glad "
                    "to give a talk on getting holiday orders out on time: what broke for us at "
                    "Acme Furniture last year and the small fix that held up.\n\nJoe",
                ),
                message(
                    "intro",
                    "Uma Rao",
                    ADDRESS["Uma Rao"],
                    "An introduction to Omar?",
                    "Hi Uma,\n\nYou mentioned Omar keeps the speaker list for the meetup. Would "
                    "you introduce us? I'd like to offer a talk on holiday shipping.\n\n"
                    "Thanks!\nJoe",
                    evidence=f"they wrote from it ({c.day(-40)}, “Slides from the meetup”)",
                ),
            ],
        ),
    ]
    sent = errand(
        52,
        "Send Kai the delivery schedule for the holiday orders",
        [
            (
                "Read the errand",
                "Reach Kai Lund at Acme Furniture: send the holiday delivery schedule.",
            ),
            ("Looked them up", "9 records name them."),
            (
                "Looked for a way to reach them",
                (
                    f"Kai Lund: {ADDRESS['Kai Lund']}, known because they wrote from it "
                    f"({c.day(-13)}, “Re: December shifts”)."
                ),
            ),
            ("Wrote it", "Short, as your work emails to Kai are."),
            ("Stopped one tap short", "Ready to send to Kai Lund: press Send, or edit it first."),
            ("Sent", f"You pressed Send: it went to Kai Lund ({ADDRESS['Kai Lund']})."),
        ],
        person="Kai Lund",
        org="Acme Furniture",
        purpose="Send the holiday delivery schedule.",
        channel="email",
        who="Kai Lund, Warehouse Supervisor at Acme Furniture.",
        why="Short, as your work emails to Kai are.",
        needs=[],
        cv=None,
        messages=[
            message(
                "main",
                "Kai Lund",
                ADDRESS["Kai Lund"],
                "Holiday delivery schedule",
                "Hi Kai,\n\nHere's the delivery schedule for the holiday orders, with your new "
                "Saturday shift. The December dates are on the last tab.\n\nThanks,\nJoe",
                state="sent",
                sent_at=c.ago(51),
            )
        ],
    )
    for record in [*found, sent]:
        _write_json(vault / "clones" / "errands" / f"{record['id']}.json", record)


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]
