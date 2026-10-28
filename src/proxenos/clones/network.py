"""Who the user has met, knows of and wants to read, and what they could do with them.

Two steps. The first, in code with no model, indexes people into clones/network/people.json:

- met: people the user exchanged messages with. Everyone in a WhatsApp, Instagram or LinkedIn
  direct chat or Slack DM they wrote in; in groups and channels they wrote in, each member who
  wrote on a day they did; and everyone in a WhatsApp group or Slack channel of at most 15
  people they're in. Email correspondents they wrote to (to or cc, on mail to at most 15
  people) or answered, named by the From name on their own mail, so an address that never wrote
  to the user stays out. People at a meeting of 2 to 15 guests with the user, from the
  calendars. LinkedIn connections.
- know_of: co-authors of the user's papers and authors of papers citing them (raw/mentions),
  authors in their reading notes and their website's CV, and people named in their notes and
  website pages.
- to_read: authors on a reading list, or in a reading collection marked to read (status "to
  read", "not started", ...), and names on note lines that say to read them ("want to read",
  "read up on", "look into"), or in note tasks that start "Read".

Who is who. Each source's people are identities: a WhatsApp jid (a person's phone and lid jids
are one, as raw/whatsapp/groups links them), a Slack user, an email address, a LinkedIn
connection, or, for sources with nothing better, a name. Identities are one person when:
- the user said so in clones/network/aliases.json, which comes before everything else:
  {"same": [[a, b], ...], "different": [[a, b], ...], "hide": [a, ...]}, each a name or an id
  (a ref or person id from people.json, a jid, an address, a Slack user id). The page writes it.
- a source says so: a Slack profile's email is that address's person;
- they go by the same full name, matched by normalized name: case, accents, titles, degrees
  and middle initials don't count, and "Last, First" is "First Last". "J. Smith" and "Jane
  Smith" stay two people;
- one goes by a first name or nickname alone ("Tori", from a small table of nicknames such as
  Tori for Victoria) that fits exactly one full-name person among those who share a group
  with it, or share someone in one (groups of at most 80).
Two different full names are never made one otherwise. The strongest relation wins: met, then
to_read, then know_of. The name shown is the fullest, the one most sources use. The user's own
names (PROXENOS_NAME, PROXENOS_FULL_NAME, the names on their own messages) and ids are left out.
So is any name with a digit or an @ in it, and contexts and topics are scrubbed of addresses and
numbers, so no phone number or email lands in the index; a person's "ref" is a hash of an id.
Twitter DMs and Instagram likes carry only ids and handles, so they add no one.

Connections come in the same pass, as people.json's "edges", "groups" and "clusters". A group
is one context people share: a WhatsApp group the user is in or a Slack channel they're in or
wrote in (everyone in it, from raw/whatsapp/groups and raw/slack/<team>/channels; without those,
those who wrote), an email thread or recipient list (at most 15 addresses, so a mailing list is no
context), a meeting of 2 to 15 guests, the authors of one OpenAlex paper (the user's works and the
works citing them), or an organization (at most 40 people from the index share it, since a
company of thousands says nothing about who knows whom). The user is in all of them, so is left
out and doesn't count towards a group's size. Each group two people share adds 1/log2(size + 1) to
their tie, so a pair alone adds 0.63, a group of 33 0.2 and a channel of 3,000 0.09. Only the
top 600 people (by messages and recency, as top_people picks them) are connected, listed in
"core", and only the strongest 4,000 edges stay. Clusters are communities among them (Louvain
on all their ties), each labelled by the group most of its people are in.

Names in notes come from a strict heuristic: two to four capitalized words in a row (middle
initials allowed), none of them a stopword (days, months, places, institutions, headings, ...)
and none a word the notes also use in lower case, which rules out title-case headings. A name
the index already has from elsewhere skips the lower-case test. Notes are raw/notes/pages
(title, collection, text, kind; Notion-style "Key: value" lines at the top of the text are
read as properties) and raw/notes/tasks. Without them that part is skipped.

The second step is one model call. It reads the self-model, the top 300 people (by messages
and recency, with room kept for people the user knows of or wants to read), their note titles
(empty and unfinished pages are plans) and how they took earlier ideas, and writes
clones/network/ideas.json: projects they could do with what they know, people to reach out to
with a specific ask, and people to read. `--people-only` stops after the index and needs no
model.

The page marks ideas useful, not me or done in clones/network/feedback.jsonl. What the user marked
not me never comes back: not that id, not the same text in other case or punctuation, and for
outreach, not to the same person. What the user marked done goes to the model as context and isn't
suggested again. clones/network/history.json keeps every idea given, so a verdict still counts
after its idea has left ideas.json.
"""

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from proxenos import llm
from proxenos.config import env

RELATIONS = ("met", "know_of", "to_read")
# The relation a person gets when they have several.
_STRONGEST_FIRST = ("met", "to_read", "know_of")
TOP_PEOPLE = 300
QUOTAS = {"met": 150, "know_of": 100, "to_read": 50}  # places kept per relation; leftovers refill
HALF_LIFE_DAYS = 365  # how fast an old conversation stops counting when ranking people
MAX_RECIPIENTS = 15  # mail to more people than this doesn't make them the user's correspondents
MAX_AUTHORS = 15  # a citing paper with more authors keeps its first five and its last
GRAPH_PEOPLE = 600  # people the graph connects
GRAPH_EDGES = 4000  # connections kept, strongest first
MAX_ORG = 40  # an organization with more people in the index than this connects no one
EDGE_CONTEXTS = 5  # shared contexts named on an edge
MIN_EVENT, MAX_EVENT = 2, 15  # guests, the user included, at a meeting that makes a group
CONTEXT_GROUP = 80  # a first name alone is placed only through groups this small
LOUVAIN_LEVELS, LOUVAIN_PASSES = 20, 50
MIN_CLUSTER = 3  # a community of two is a tie, not a cluster
AKA = 5  # other names a person goes by, listed so the page can say which one is someone else
ALIASES = "aliases.json"
TOPICS = 5
CONTEXT_CHARS = 240
TOPIC_CHARS = 80
EMPTY_CHARS = 40  # a page with less text than this, besides title and properties, is empty
NOTE_TITLES = 400
PER_COLLECTION = 40
OPEN_TASKS = 100
LIMITS = {"projects": 8, "outreach": 12, "to_read": 15}
CHANNELS = ("email", "whatsapp", "slack", "linkedin", "instagram", "in_person", "other")
_REACTIONS = ("useful", "not_me", "done")

# Each source, as it reads in a person's context line.
_SOURCES = {
    "whatsapp": "WhatsApp",
    "slack": "Slack",
    "email": "email",
    "linkedin/messages": "LinkedIn messages",
    "instagram": "Instagram",
    "linkedin/connections": "LinkedIn connection",
    "mentions/works": "co-author",
    "mentions/citations": "cited your work",
    "website": "on your website",
    "notes/readings": "author in your readings",
    "notes/pages": "in your notes",
    "notes/tasks": "in your note tasks",
    "calendar": "calendar",
}
# Sources whose interactions are counted on a person's context line, and what each one is.
_COUNTED = {
    "whatsapp": "message",
    "slack": "message",
    "email": "message",
    "linkedin/messages": "message",
    "instagram": "message",
    "calendar": "event",
}

_TITLES = {"dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "miss", "mx", "sir", "dame"}
_DEGREES = {"phd", "md", "mba", "msc", "mphil", "dphil", "esq"}
_GENERIC = {
    "linkedin member",
    "linkedin",
    "unknown",
    "someone",
    "me",
    "you",
    "deleted user",
    "instagram user",
    "facebook user",
    "whatsapp",
    "slackbot",
    "meta ai",
    "anonymous",
}
# Each kind of group, in the order groups are listed: how it reads in an edge's contexts, and
# what a group of that kind is called when it has no name.
_GROUP_KINDS = {
    "whatsapp_group": ("WhatsApp", "a group"),
    "slack_channel": ("Slack", "a channel"),
    "event": ("Calendar", "an event"),
    "paper": ("Paper", "a paper"),
    "email_thread": ("Email", "an email thread"),
    "org": ("Org", "an organization"),
}
GROUP_KINDS = tuple(_GROUP_KINDS)
# Groups whose members met the user just by being in one small enough, and the source they count as.
_GROUP_SOURCES = {"whatsapp_group": "whatsapp", "slack_channel": "slack"}
_RECURRENCE = re.compile(r"/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")  # a moved instance's id
# Common nicknames of first names: a first name alone ("Tori") can be someone whose full name
# starts with the first name it stands for ("Victoria"). Only that way round, so two nicknames
# of one name ("Sasha", "Alex") never match each other.
_NICKNAME_TABLE = """
    alexandra: alex alexa lexi lexie sasha sandra
    alexander: alex lex xander sasha sandy
    alexis: alex lexi lexie
    abigail: abby gail
    andrew: andy drew
    anthony: tony
    benjamin: ben benji
    catherine katherine kathryn: kate katie kathy cathy kat
    christina christine: chris tina
    christopher: chris
    daniel: dan danny
    david: dave
    deborah: deb debbie
    edward: ed eddie ted teddy
    elizabeth: liz lizzie beth betsy betty eliza libby
    gabriel gabriella gabrielle: gabe gabby
    gregory: greg
    isabel isabella: izzy bella
    james: jim jimmy jamie
    jennifer: jen jenny
    jessica: jess jessie
    john: johnny jack
    jonathan: jon
    joseph: joe joey
    joshua: josh
    margaret: maggie meg peggy
    matthew: matt
    maximilian maxwell: max
    megan: meg
    michael: mike mikey
    nathan nathaniel: nate
    nicholas: nick nicky
    nicole: nikki
    patricia: pat patty trish
    patrick: pat
    rebecca rebekah: becky
    richard: rich rick ricky
    robert: rob robbie bob bobby bert
    samantha samuel: sam sammy
    stephen steven: steve
    susan suzanne: sue susie
    thomas: tom tommy
    timothy: tim
    victoria: vicky tori
    william: will bill billy willy liam
    zachary: zach zack
"""
_NICKNAMES: dict[str, frozenset[str]] = {}  # nickname → the first names it stands for
for _line in _NICKNAME_TABLE.strip().splitlines():
    _formal, _short = _line.split(":")
    for _nick in _short.split():
        _NICKNAMES[_nick] = _NICKNAMES.get(_nick, frozenset()) | set(_formal.split())
# What a profile says as its organization when it has none.
_ORG_GENERIC = {
    "self employed",
    "selfemployed",
    "freelance",
    "freelancer",
    "independent",
    "independent consultant",
    "consultant",
    "confidential",
    "stealth",
    "stealth startup",
    "stealth mode",
    "startup",
    "n a",
    "na",
    "none",
    "student",
    "unemployed",
    "retired",
    "private",
    "self",
    "own business",
    "personal",
    "various",
}
_ORG_SUFFIXES = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "gmbh", "plc"}
_WEBMAIL = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "yahoo.co.in",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "protonmail.com",
    "proton.me",
    "gmx.com",
    "ymail.com",
    "rediffmail.com",
    "qq.com",
    "163.com",
}
# Capitalized words that aren't names. Notes are also checked against their own lower-case
# words, so this only needs what that misses: days, months, titles, institutions, places,
# headings, and verbs that open a sentence before a name.
_STOP = frozenset(
    """
    a an the and or but nor of in on at to for from by with without about into onto over under
    after before since until during per via vs versus et al i we you he she they it me us him
    her them my our your his its their this that these those there here what which who whom
    whose when where why how if then than so not no yes also just only very more most some any
    all each every both either neither other another such same new old next last first second
    third is are was were be been being has have had do does did can could will would shall
    should may might must dear hi hello hey thanks thank please best regards cheers re fwd fw
    monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thurs fri sat
    sun january february march april june july august september october november december jan
    feb mar apr jun jul aug sep sept oct nov dec today tomorrow yesterday morning afternoon
    evening night week weekend month year spring summer fall autumn winter christmas easter
    thanksgiving diwali holi eid dr prof professor mr mrs ms miss sir madam mx phd md
    university college institute school department dept faculty lab labs laboratory center
    centre hospital clinic foundation society association journal press conference workshop
    symposium seminar lecture talk meeting meetings group team project projects committee board
    council office company inc corp ltd llc program programme course class north south east
    west central upper lower san santa los las la le el de del da di van von der den du st
    saint mount lake river street road avenue park city county state states united kingdom
    republic america american europe european asia asian africa african abstract introduction
    method methods result results discussion conclusion conclusions summary review notes note
    paper papers data dataset model models analysis figure fig table appendix section chapter
    part experiment experiments study studies task tasks theory hypothesis question questions
    answer answers background related work future directions reference references bibliography
    reading readings todo done draft final version update updates agenda minutes action items
    goal goals plan plans idea ideas list overview neuroscience psychology cognitive
    computational biology physics chemistry science sciences engineering medicine brain memory
    learning neural network networks machine deep artificial intelligence http https www com
    org edu pdf doi arxiv google zoom slack whatsapp gmail email linkedin twitter instagram
    facebook youtube github notion obsidian microsoft apple amazon meta openai python matlab
    met talked spoke asked told called emailed wrote read check see call ask send meet discuss
    follow look find get make use try add need want saw seen went came gave sent texted
    messaged pinged thanked introduced joined visited invited heard learned noticed mentioned
    suggested recommended said says
    """.split()  # noqa: SIM905 (a word list reads better as words)
)
_ARTICLES = {"the", "a", "an"}
_AUTHOR_KEYS = ("author", "authors", "authoryear", "by", "creator", "creators", "writer")
_STATUS_KEYS = ("status", "state", "readingstatus", "progress", "tags", "tag", "shelf", "list")
_TOPIC_KEYS = ("topic", "topics", "field", "area", "subject", "theme")

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_POSSESSIVE = re.compile(r"['’]s$")
_CONTACT = re.compile(r"\d|@")  # in a name: a phone number or an address, never a name
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*")  # with or without a dot after the @
_NUMBER = re.compile(r"\+?\d[\d\s().-]{5,}\d")  # a phone number when it has 7 digits or more
_DATE = re.compile(r"(?:19|20)\d\d[-/.]\d\d?(?:[-/.]\d\d?)?")
_SENTENCE = re.compile(r"(?<=\w\w[.!?;])\s+")  # not after an initial: "Jo Q. Coauthor"
_LINK = re.compile(r"https?://\S+|www\.\S+|\S+@\S+")
_PROPERTY = re.compile(r"([A-Za-z][\w ,/()&-]{0,40}):\s*(.*)")
_READING = re.compile(
    r"\b(readings?|reading list|papers?|literature|books?|bibliograph\w*|references?|zotero"
    r"|articles?|to[- ]?read)\b",
    re.IGNORECASE,
)
_TO_READ_PAGE = re.compile(
    r"\b(to[- ]?read|want[- ]to[- ]read|read[- ]later|reading[- ]list)\b", re.IGNORECASE
)
_TO_READ_STATUS = re.compile(
    r"\b(to[- ]?read|want[- ]to[- ]read|read[- ]later|reading[- ]list|not[- ]started|unread"
    r"|up[- ]next|queued?|backlog|to[- ]?do|wish[- ]?list)\b",
    re.IGNORECASE,
)
_TO_READ_ASK = re.compile(
    r"\b(to[- ]read|want[- ]to[- ]read|read[- ]later|read (?:more )?(?:about|up on|by)"
    r"|look (?:up|into)|check out)\b",
    re.IGNORECASE,
)
_READ_TASK = re.compile(r"\s*(?:read|skim|look (?:up|into)|check out)\b", re.IGNORECASE)
_UNFINISHED = re.compile(
    r"^\s*[-*] \[ \]|\b(?:TODO|TBD|WIP|FIXME)\b|(?:\.\.\.|…)\s*$", re.MULTILINE
)
_DONE = re.compile(r"\b(done|completed?|finished|closed|archived?)\b", re.IGNORECASE)
_DATELIKE = re.compile(r"[\d\s./_-]*")
_SUBJECT_PREFIX = re.compile(r"^\s*(?:(?:re|fwd?|aw|wg)\s*:\s*)+", re.IGNORECASE)
_NO_REPLY = re.compile(
    r"(no-?reply|do-?not-?reply|notifications?|newsletters?|mailer-daemon)\b", re.IGNORECASE
)
_BULK_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
    "SPAM",
    "TRASH",
}
_SLACK_EVENTS = re.compile(
    r"(channel|group)_(join|leave|topic|purpose|name|archive|unarchive)|(un)?pinned_item"
)

_SYSTEM = """\
You help {person}, a researcher, see what their network makes possible. Their digital twin \
keeps a model of them and an index of people: those they've met (messages, LinkedIn), those \
they know of (co-authors, people citing their work, authors they read, names in their notes) \
and those they want to read. You get the self-model, the top of that index, the titles of \
their notes (empty and unfinished pages are plans they haven't got to), and how they took \
earlier ideas.

Return three lists.

projects: five to eight projects {person} could start now with what they know and who they know.
- title: short and specific.
- pitch: two or three sentences: what it is and what comes out of it.
- why_you: why {person} in particular: the skills, notes, data or people it builds on, from \
what you were given.
- people: ids of people from the index who'd help or be natural collaborators, exactly as \
shown in brackets. [] if none.
- first_step: one concrete action for this week.

outreach: eight to twelve people from the index worth contacting now, one entry each.
- person_id: their id from the index, exactly as shown in brackets.
- name: as the index has it.
- why: why them and why now: the shared topic, the paper, the overlap with a project or note, \
how long since they were last in touch.
- ask: the concrete ask in one or two sentences: a question, a call, feedback on a draft, a \
collaboration, an introduction.
- channel: one {person} already uses with them where the index shows one (email, whatsapp, \
slack, linkedin, instagram), else in_person or other.

to_read: up to fifteen people whose work {person} should read: names from the want-to-read \
list worth starting with, and people missing from the index who are central to their \
interests. For each, the name and why: what of theirs to read and how it connects to what \
{person} is doing.

Rules:
- Feasible: projects within reach of what {person} knows and has now, not wishes.
- Specific: name the topic, paper, dataset or note. Nothing that would fit any researcher.
- Grounded: people in projects and outreach come from the index. Never invent people, or \
facts about them beyond what the index says.
- Their reactions come first. Never repeat or reword an idea they marked not_me. Done ideas \
are context: build on them, don't suggest them again.
- Refer to them as {person} and don't assume pronouns. Nothing sensitive about other people."""


def _item(properties: dict, required: list[str]) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


_TEXT = {"type": "string"}
_SCHEMA = {
    "type": "object",
    "properties": {
        "projects": _item(
            {
                "title": _TEXT,
                "pitch": _TEXT,
                "why_you": _TEXT,
                "people": {"type": "array", "items": _TEXT},
                "first_step": _TEXT,
            },
            ["title", "pitch", "why_you", "people", "first_step"],
        ),
        "outreach": _item(
            {
                "person_id": _TEXT,
                "name": _TEXT,
                "why": _TEXT,
                "ask": _TEXT,
                "channel": {"type": "string", "enum": list(CHANNELS)},
            },
            ["person_id", "name", "why", "ask", "channel"],
        ),
        "to_read": _item({"name": _TEXT, "why": _TEXT}, ["name", "why"]),
    },
    "required": ["projects", "outreach", "to_read"],
    "additionalProperties": False,
}


def build(vault: Path, people_only: bool = False, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    out = vault / "clones" / "network"
    profile = None if people_only else read_self(vault / "self")  # fail before the slow part
    book = _read_vault(vault, now)
    people, groups = book.resolve(_aliases(out / ALIASES), _load_json(out / "people.json"))
    core = top_people(people, now, GRAPH_PEOPLE)
    edges, kept = connections(groups, core, now)
    found, named = clusters(kept, core)
    core_ids = {p["id"] for p in core}
    for person in people:
        if person["id"] in core_ids:
            person["cluster"] = found.get(person["id"])
    _write_json(
        out / "people.json",
        {
            "generated": _iso(now),
            "people": people,
            "core": [p["id"] for p in core],
            "edges": edges,
            "groups": kept,
            "clusters": named,
        },
    )
    stats = {"people": len(people)} | {
        r: sum(p["relation"] == r for p in people) for r in RELATIONS
    }
    stats |= {"edges": len(edges), "groups": len(kept), "clusters": len(named)}
    if profile is None:
        return stats
    return stats | ideas(vault, people, profile, now)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--people-only", action="store_true", help="only build the people index; no model"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return build(vault, people_only=args.people_only)


# The people index


def _read_vault(vault: Path, now: datetime | None = None) -> "_Book":
    """Everyone in the vault the user has met, knows of or wants to read, as identities, and the
    groups they share. Messages come first and notes last, so names in notes can match people
    already found; calendars come after mail, which says which addresses are the user's."""
    book = _Book([env("NAME"), env("FULL_NAME")])
    for read in (_whatsapp, _slack, _email, _linkedin, _instagram, _mentions, _writing):
        read(vault, book)
        if read is _email:
            _calendar(vault, book, now or datetime.now(UTC))
    return book


def normalize(name: str) -> str:
    """The name a person is matched by: no case, accents, titles, degrees or middle initials,
    punctuation as spaces, and "Last, First" as "first last"."""
    text = unicodedata.normalize("NFKD", _display(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"['’]", "", text)
    words = re.sub(r"[^\w]|[\d_]", " ", text).split()
    if len(words) >= 3:
        words = [words[0], *(w for w in words[1:-1] if len(w) > 1), words[-1]]
    return " ".join(words)


def person_id(name: str) -> str:
    return _key_id(normalize(name))


def _key_id(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _ref(key: str) -> str:
    """An identity's key as people.json and aliases.json carry it: opaque, so no number or
    address leaves the raw data."""
    return "k:" + hashlib.sha1(key.encode()).hexdigest()[:16]


def _identity() -> dict:
    return {
        "names": Counter(),
        "name_sources": defaultdict(set),
        "relations": set(),
        "sources": Counter(),
        "interactions": 0,
        "first": None,
        "last": None,
        "where": defaultdict(dict),  # source → labels, oldest first, as an ordered set
        "topics": Counter(),
        "orgs": Counter(),
    }


class _Book:
    """Everyone found so far, as identities: a WhatsApp jid (wa:), a Slack user (slack:team:),
    an email address (email:), a LinkedIn connection (li:), or for a source with nothing
    better, a normalized name (name:). Each carries the names it was seen under. resolve()
    decides which identities are one person."""

    def __init__(self, me: Iterable[str]):
        self.me = {key for name in me if (key := normalize(name))}
        self.my_keys: set[str] = set()
        self.my_addresses: set[str] = set()
        self.ids: dict[str, dict] = {}
        self.links: list[tuple[str, str]] = []  # one person, as a source says
        self.jids: dict[str, str] = {}  # a WhatsApp jid → the one it's filed under
        # (kind, key) → what a group is called and who's in it, as identity keys
        self.groups: dict[tuple[str, str], dict] = {}
        self.wrote_in: set[tuple[str, str]] = set()  # groups with a message of the user's

    def mine(self, name: str | None = None, key: str | None = None) -> None:
        """A name or an identity of the user's own, never to be indexed as someone else."""
        if name and (norm := normalize(name)):
            self.me.add(norm)
        if key:
            self.my_keys.add(key)

    def name(self, key: str | None, name: str | None, source: str) -> str | None:
        """Note a name an identity goes by and return its key. Without a key the name is the
        identity; None when there's neither a key nor a name that can be one."""
        norm = _name_key(name)
        key = key or (f"name:{norm}" if norm else None)
        if key is None:
            return None
        ident = self.ids.get(key)
        if ident is None:
            ident = self.ids[key] = _identity()
        if norm:
            display = _display(name or "")
            ident["names"][display] += 1
            ident["name_sources"][display].add(source)
        return key

    def add(
        self,
        name: str | None,
        relation: str,
        source: str,
        *,
        key: str | None = None,
        first: str | None = None,
        last: str | None = None,
        interactions: int = 0,
        where: str | None = None,
        topics: Iterable[str | None] = (),
        org: str | None = None,
    ) -> str | None:
        key = self.name(key, name, source)
        if key is None:
            return None
        person = self.ids[key]
        person["relations"].add(relation)
        person["sources"][source] += interactions
        person["interactions"] += interactions
        for ts in filter(None, (first, last)):
            person["first"] = min(person["first"] or ts, ts)
            person["last"] = max(person["last"] or ts, ts)
        if where and (where := _clip(_scrub(where), TOPIC_CHARS)):
            person["where"][source].pop(where, None)
            person["where"][source][where] = None
        for topic in topics:
            if topic and (topic := _clip(_scrub(topic), TOPIC_CHARS)):
                person["topics"][topic] += 1
        if org and (org := _scrub(org)):
            person["orgs"][org] += 1
        return key

    def link(self, a: str | None, b: str | None) -> None:
        if a and b and a != b:
            self.links.append((a, b))

    def jid(self, jid: str | None) -> str | None:
        """A WhatsApp jid's identity key; a person's phone and lid jids share one."""
        return f"wa:{self.jids.get(jid, jid)}" if jid else None

    def same_jid(self, jid: str | None, other: str | None) -> None:
        if jid and other:
            phone = next((j for j in (jid, other) if j.endswith("@s.whatsapp.net")), None)
            filed = phone or self.jids.get(jid) or self.jids.get(other) or min(jid, other)
            self.jids[jid] = self.jids[other] = filed

    def group(self, kind: str, key: str, label: str | None, members: Iterable[str | None]) -> None:
        """People who share one context, as identity keys: everyone in a group or channel,
        everyone on an email thread or at a meeting, the authors of a paper. They needn't be
        people of the index; they still count towards the group's size."""
        members = {m for m in members if m}
        if members:
            found = self.groups.setdefault((kind, key), {"name": "", "members": set()})
            found["name"] = found["name"] or _clip(_scrub(label or ""), TOPIC_CHARS)
            found["members"] |= members

    def known_names(self) -> set[str]:
        """The normalized names of the people found so far, for names in notes to match."""
        return {normalize(n) for p in self.ids.values() if p["relations"] for n in p["names"]}

    def resolve(self, aliases: dict, previous: dict) -> tuple[list[dict], list[dict]]:
        """People and the groups they share, after deciding who is who:

        1. The user's corrections in aliases.json: pairs kept apart, then pairs made one.
        2. What the sources say: a Slack profile's email is that address.
        3. One full name, one person, whatever the source.
        4. A first name or nickname alone ("Tori") joins the one full-name person whose first
           name it is (or, failing that, whose first name it stands for: Alexandra) among those
           who share a group with it or someone in one; with two such, it stays apart.
        Two different full names are never made one, except by a stable id or by the user. Anyone
        with one of the user's names or ids is the user, and left out; so are those they hid."""
        keys = set(self.ids)
        for group in self.groups.values():
            keys |= group["members"]
        merger = _Merger(keys)
        refs = _Refs(self, keys, previous)
        for n, items in enumerate(aliases["different"]):
            merger.keep_apart(n, [refs.find(item) for item in items])
        for items in aliases["same"]:
            found = [k for item in items for k in refs.find(item)]
            for key in found[1:]:
                merger.union(found[0], key)
        for a, b in self.links:
            merger.union(a, b)
        busiest = sorted(self.ids, key=lambda k: (-self.ids[k]["interactions"], k))
        for key in busiest:
            for display in self.ids[key]["names"]:
                norm = normalize(display)
                if len(norm.split()) >= 2:
                    merger.union(key, f"fullname:{norm}")

        me = {merger.find(k) for k in self.my_keys if k in keys}
        for key, ident in self.ids.items():
            if any(_is_me(normalize(n), self.me) for n in ident["names"]):
                me.add(merger.find(key))
        self._nicknames(merger, me, busiest)

        sets: dict[str, list[str]] = defaultdict(list)
        for key in keys:
            sets[merger.find(key)].append(key)
        me = {merger.find(k) for k in me}
        hidden = {merger.find(k) for item in aliases["hide"] for k in refs.find(item)}
        rosters = {}
        joined: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (kind, key), group in self.groups.items():
            roots = {merger.find(m) for m in group["members"]} - me
            rosters[kind, key] = roots
            source = _GROUP_SOURCES.get(kind)
            if source and len(roots) <= MAX_RECIPIENTS:
                for root in roots:
                    joined[root].append((source, group["name"] or _GROUP_KINDS[kind][1]))

        found = []
        for root, members in sets.items():
            if root in me or root in hidden:
                continue
            person = _merge([self.ids[k] for k in members if k in self.ids])
            for source, label in joined.get(root, ()):
                person["relations"].add("met")
                person["sources"][source] += 0
                person["where"][source].setdefault(label, None)
            if person["relations"] and person["names"]:
                primary = max(
                    (k for k in members if k in self.ids),
                    key=lambda k: (self.ids[k]["interactions"], not k.startswith("name:"), k),
                )
                found.append((root, person, _ref(primary)))

        people, id_of = [], {}
        taken: set[str] = set()
        for root, person, ref in sorted(found, key=lambda f: (-f[1]["interactions"], f[0])):
            entry = _entry(person)
            pid = person_id(entry["name"])
            if pid in taken:
                pid = _key_id(f"{normalize(entry['name'])}\0{root}")
            taken.add(pid)
            id_of[root] = pid
            people.append({"id": pid} | entry | {"ref": ref})
        people.sort(key=lambda e: e["name"].casefold())
        people.sort(key=lambda e: e["last_seen"] or "", reverse=True)
        people.sort(key=lambda e: (RELATIONS.index(e["relation"]), -e["interactions"]))

        groups = []
        for (kind, key), group in self.groups.items():
            roots = rosters[kind, key]
            members = {id_of[r] for r in roots if r in id_of}
            groups.append(_group(kind, key, group["name"], members, len(roots)))
        orgs: dict[str, dict] = {}
        for person in people:
            for org in person.pop("_orgs"):
                if org_key := _org_key(org):
                    named = orgs.setdefault(org_key, {"names": Counter(), "members": set()})
                    named["names"][org] += 1
                    named["members"].add(person["id"])
        for org_key, named in orgs.items():
            if len(named["members"]) <= MAX_ORG:
                name = named["names"].most_common(1)[0][0]
                groups.append(_group("org", org_key, name, named["members"]))
        return people, [g for g in groups if len(g["members"]) >= 2]

    def _nicknames(self, merger: "_Merger", me: set[str], busiest: list[str]) -> None:
        """Step 4 of resolve(): a first name or nickname alone joins the one full-name person
        it can only be."""
        names: dict[str, set[str]] = defaultdict(set)
        weight: Counter = Counter()
        for key in busiest:
            root = merger.find(key)
            names[root] |= {normalize(n) for n in self.ids[key]["names"]}
            weight[root] += self.ids[key]["interactions"]
        groups_of: dict[str, set[int]] = defaultdict(set)
        near: dict[str, set[str]] = defaultdict(set)
        for n, group in enumerate(self.groups.values()):
            roots = {merger.find(m) for m in group["members"]} - me
            if 2 <= len(roots) <= CONTEXT_GROUP:
                for root in roots:
                    groups_of[root].add(n)
                    near[root] |= roots
        by_first: dict[str, set[str]] = defaultdict(set)
        alone = []
        for root, found in names.items():
            if root in me or not found:
                continue
            full = [n for n in found if _full(n)]
            for n in full:
                by_first[n.split()[0]].add(root)
            if not full:
                alone.append(root)

        def shares(a: str, b: str) -> bool:
            return bool(groups_of[a] & groups_of[b] or (near[a] - {a, b}) & (near[b] - {a, b}))

        for root in sorted(alone, key=lambda r: (-weight[r], r)):
            if not groups_of[root]:
                continue
            firsts = {n.split()[0] for n in names[root]}
            exact = {c for f in firsts for c in by_first.get(f, ())}
            nick = {
                c for f in firsts for alt in _NICKNAMES.get(f, ()) for c in by_first.get(alt, ())
            }
            for tier in (exact, nick - exact):
                fits = {c for c in tier if c != root and shares(root, c)}
                if fits:
                    if len(fits) == 1:
                        merger.union(root, fits.pop())
                    break


class _Merger:
    """Union-find over identity keys. Identities the user said are different carry marks, and a
    union that would put two different marks of one correction into one person is refused."""

    def __init__(self, keys: Iterable[str]):
        self.parent = {k: k for k in keys}
        self.marks: dict[str, dict[int, int]] = {}  # root → correction → side

    def find(self, key: str) -> str:
        parent = self.parent.setdefault(key, key)
        root = key
        while parent != root:
            root, parent = parent, self.parent[parent]
        while key != root:
            following = self.parent[key]
            self.parent[key] = root
            key = following
        return root

    def union(self, a: str, b: str) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        ma, mb = self.marks.get(ra, {}), self.marks.get(rb, {})
        if any(mb.get(n, side) != side for n, side in ma.items()):
            return False
        keep, gone = sorted((ra, rb))
        self.parent[gone] = keep
        if ma or mb:
            self.marks[keep] = ma | mb
        self.marks.pop(gone, None)
        return True

    def keep_apart(self, n: int, sides: list[list[str]]) -> None:
        """Correction n: no two of these sides may become one person. A key on two sides
        says nothing and is skipped."""
        count = Counter(k for side in sides for k in set(side))
        for i, side in enumerate(sides):
            for key in side:
                if count[key] == 1:
                    self.marks.setdefault(self.find(key), {})[n] = i


class _Refs:
    """What a correction in aliases.json can name: a ref from people.json ("k:..."), a person
    id from the last people.json, an identity key ("wa:...", "slack:team:U...", "email:...",
    "li:...", "name:..."), a WhatsApp jid, an email address, a Slack user id, or a name (every
    identity seen under it)."""

    def __init__(self, book: _Book, keys: set[str], previous: dict):
        self.book, self.keys = book, keys
        self.hashed = {_ref(k): k for k in keys}
        self.by_name: dict[str, set[str]] = defaultdict(set)
        for key, ident in book.ids.items():
            for display in ident["names"]:
                self.by_name[normalize(display)].add(key)
        listed = previous.get("people") if isinstance(previous.get("people"), list) else []
        self.ids = {p["id"]: p.get("ref") for p in listed if isinstance(p, dict) and p.get("id")}

    def find(self, text: str) -> list[str]:
        text = text.strip()
        if text.startswith("k:"):
            return [self.hashed[text]] if text in self.hashed else []
        if re.fullmatch(r"[0-9a-f]{12}", text):
            return self.find(self.ids[text]) if self.ids.get(text) else []
        if text.split(":", 1)[0] in ("wa", "slack", "email", "li", "name") and text in self.keys:
            return [text]
        if text.endswith(("@s.whatsapp.net", "@lid")):
            key = self.book.jid(text)
            return [key] if key in self.keys else []
        if "@" in text:
            key = f"email:{text.lower()}"
            return [key] if key in self.keys else []
        if re.fullmatch(r"[UW][A-Z0-9]{6,}", text):
            return sorted(k for k in self.keys if k.startswith("slack:") and k.endswith(f":{text}"))
        return sorted(self.by_name.get(normalize(text), ()))


def _aliases(path: Path) -> dict[str, list]:
    """The user's corrections: {"same": [[a, b, ...]], "different": [[a, b, ...]],
    "hide": [a, ...]}, each a name or an id as _Refs reads them. Anything malformed is skipped."""
    data = _load_json(path)

    def texts(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [v for v in value if isinstance(v, str) and v.strip()]

    def sets(value: object) -> list[list[str]]:
        found = [texts(v) for v in value] if isinstance(value, list) else []
        return [v for v in found if len(v) >= 2]

    return {
        "same": sets(data.get("same")),
        "different": sets(data.get("different")),
        "hide": texts(data.get("hide")),
    }


def _merge(identities: list[dict]) -> dict:
    """Identities found to be one person, as one."""
    person = _identity()
    for ident in identities:
        person["names"].update(ident["names"])
        for display, sources in ident["name_sources"].items():
            person["name_sources"][display] |= sources
        person["relations"] |= ident["relations"]
        person["sources"].update(ident["sources"])
        for source in ident["sources"]:
            person["sources"][source] += 0  # a source with no interactions still counts
        person["interactions"] += ident["interactions"]
        for ts in filter(None, (ident["first"], ident["last"])):
            person["first"] = min(person["first"] or ts, ts)
            person["last"] = max(person["last"] or ts, ts)
        for source, labels in ident["where"].items():
            person["where"][source].update(labels)
        person["topics"].update(ident["topics"])
        person["orgs"].update(ident["orgs"])
    return person


def _full(norm: str) -> bool:
    """A normalized name with a first and a last name, neither an initial."""
    words = norm.split()
    return len(words) >= 2 and len(words[0]) > 1 and len(words[-1]) > 1


def _name_key(name: str | None) -> str | None:
    """The normalized name a person is indexed under, or None for a name that can't be one:
    one with a digit or an @ in it, or a WhatsApp blob ("+AbCd...=")."""
    if not name or _CONTACT.search(name) or name.strip().startswith("+"):
        return None
    key = normalize(_display(name))
    return key if _plausible(key) else None


def _group(kind: str, key: str, name: str, members: set[str], size: int | None = None) -> dict:
    return {
        "id": hashlib.sha1(f"{kind}\0{key}".encode()).hexdigest()[:12],
        "name": name or _GROUP_KINDS[kind][1],
        "kind": kind,
        "members": members,
        "size": size if size is not None else len(members),
    }


def _org_key(org: str) -> str | None:
    """An organization as its words, without a company suffix; None for "self-employed" and
    the like, which name no one's organization."""
    words = re.findall(r"\w+", org.casefold())
    while words and words[-1] in _ORG_SUFFIXES:
        words.pop()
    key = " ".join(words)
    return None if not key or key in _ORG_GENERIC else key


def _entry(person: dict) -> dict:
    parts = []
    sources = [source for source, _ in person["sources"].most_common()]
    for source in sources:
        where = list(person["where"].get(source, {}))[::-1]  # newest first
        details = where[:2] + ([f"{len(where) - 2} more"] if len(where) > 2 else [])
        count = person["sources"][source]
        if source in _COUNTED and count:
            details.append(f"{count} {_COUNTED[source]}{'s' if count != 1 else ''}")
        how = _SOURCES[source]
        parts.append(f"{how} ({', '.join(details)})" if details else how)
    orgs = person["orgs"].most_common(1)
    name = _best(person["names"], person["name_sources"])
    aka = {}  # the other names they go by, one way of writing each, the most used first
    for other, _ in person["names"].most_common():
        if (norm := normalize(other)) != normalize(name):
            aka.setdefault(norm, other)
    return {
        "name": name,
        "relation": next(r for r in _STRONGEST_FIRST if r in person["relations"]),
        "sources": sources,
        "interactions": person["interactions"],
        "first_seen": person["first"],
        "last_seen": person["last"],
        "context": _clip("; ".join(parts), CONTEXT_CHARS),
        "topics": [topic for topic, _ in person["topics"].most_common(TOPICS)],
        "org": orgs[0][0] if orgs else None,
        "aka": list(aka.values())[:AKA],
        "_orgs": list(person["orgs"]),
    }


def _chat(direct: bool, label: str, topic: str | None = None, key: str | None = None) -> dict:
    """A conversation as (ts, sender) pairs, where sender is an identity key, None for the user and
    "" for someone unnamed. The key says which conversation it is, for the group it makes."""
    return {
        "direct": direct,
        "label": label,
        "topic": topic,
        "key": key,
        "partners": set(),
        "messages": [],
    }


def _add_chats(
    book: _Book, source: str, chats: Iterable[dict], group_kind: str | None = None
) -> None:
    """Direct chats the user wrote in: the other person, with every message. Groups they wrote in:
    each member who wrote on a day they did, with their messages from those days. With a group_kind,
    everyone who wrote in such a group, on any day, is in it (a source's member list adds
    everyone else)."""
    for chat in chats:
        days = {ts[:10] for ts, sender in chat["messages"] if sender is None}
        if not days:
            continue
        if group_kind and not chat["direct"] and chat["key"]:
            writers = {sender for _, sender in chat["messages"] if sender}
            book.group(group_kind, chat["key"], chat["label"], writers)
            book.wrote_in.add((group_kind, chat["key"]))
        topics = [chat["topic"]]
        if chat["direct"]:
            stamps = [ts for ts, _ in chat["messages"]]
            # Who wrote, by their id; the chat's own name only when they never did.
            partners = {sender for _, sender in chat["messages"] if sender} or chat["partners"]
            found = {key: stamps for key in partners}
        else:
            found = defaultdict(list)
            for ts, sender in chat["messages"]:
                if sender and ts[:10] in days:
                    found[sender].append(ts)
        for key, stamps in found.items():
            book.add(
                None,
                "met",
                source,
                key=key,
                first=min(stamps),
                last=max(stamps),
                interactions=len(stamps),
                where=chat["label"],
                topics=topics,
            )


def _whatsapp(vault: Path, book: _Book) -> None:
    """Chats by jid. raw/whatsapp/groups lists everyone in each group, and links a person's
    phone and lid jids."""
    root = vault / "raw" / "whatsapp"
    rosters = list(_records(root / "groups"))
    for roster in rosters:
        for member in roster.get("members") or []:
            book.same_jid(member.get("jid"), member.get("alt_jid"))
    chats: dict[str, dict] = {}
    for r in _records(root / "messages"):
        kind = r.get("chat_type")
        if kind not in ("direct", "group") or r.get("kind") == "system":
            continue
        chat = chats.get(r["chat_id"])
        if chat is None:
            name = r.get("chat_name")
            if kind == "direct":
                chat = _chat(True, "direct chat")
                # A chat named by its number has no name to go by; the key is never shown.
                partner = book.name(book.jid(r["chat_id"]), name, "whatsapp")
                chat["partners"].update(filter(None, [partner]))
            else:
                chat = _chat(False, name or "a group", name, r["chat_id"])
            chats[r["chat_id"]] = chat
        if r.get("from_me"):
            sender = None
        else:
            jid = r["chat_id"] if kind == "direct" else r.get("sender_id")
            sender = book.name(book.jid(jid), r.get("sender_name"), "whatsapp") or ""
        chat["messages"].append((r["ts"], sender))
    _add_chats(book, "whatsapp", chats.values(), "whatsapp_group")
    for roster in rosters:
        members = []
        for member in roster.get("members") or []:
            key = book.jid(member.get("jid"))
            for name in (member.get("name"), member.get("push_name")):
                book.name(key, name, "whatsapp")
            members.append(key)
        book.group("whatsapp_group", roster["chat_id"], roster.get("chat_name"), members)


def _slack(vault: Path, book: _Book) -> None:
    """Each workspace's messages by user id, and raw/slack/<team>/channels for everyone in a
    channel the user is in or wrote in. A profile's email is that address's person."""
    for folder in sorted(p for p in (vault / "raw" / "slack").glob("*") if p.is_dir()):
        team = folder.name

        def user(uid: str | None, team: str = team) -> str | None:
            return f"slack:{team}:{uid}" if uid else None

        chats: dict[str, dict] = {}
        for r in _records(folder / "messages"):
            uid, subtype = r.get("user_id") or "", r.get("subtype") or ""
            bot = subtype == "bot_message" or uid.startswith("B") or uid == "USLACKBOT"
            if not uid or bot or _SLACK_EVENTS.fullmatch(subtype):
                continue
            if r.get("from_me"):
                book.mine(r.get("user_name"), user(uid))
            chat = chats.get(r["channel_id"])
            if chat is None:
                kind, name = r.get("channel_type"), r.get("channel_name")
                if kind == "dm":
                    chat = _chat(True, f"{team} DM")
                    chat["partners"].update(filter(None, [book.name(None, name, "slack")]))
                else:
                    chat = _chat(False, _channel_label(team, kind, name), name and f"#{name}")
                    chat["key"] = f"{team}/{r['channel_id']}"
                chats[r["channel_id"]] = chat
            if r.get("from_me"):
                sender = None
            else:
                sender = book.name(user(uid), r.get("user_name"), "slack") or ""
            chat["messages"].append((r["ts"], sender))
        _add_chats(book, "slack", chats.values(), "slack_channel")

        for roster in _records(folder / "channels"):
            kind = roster.get("channel_type")
            if kind == "dm" or not roster.get("channel_id"):
                continue
            members = []
            for member in roster.get("members") or []:
                key = user(member.get("id"))
                if member.get("me"):
                    book.mine(member.get("name"), key)
                    continue
                book.name(key, member.get("name"), "slack")
                if email := (member.get("email") or "").strip().lower():
                    book.link(key, f"email:{email}")
                members.append(key)
            group = f"{team}/{roster['channel_id']}"
            if roster.get("joined") or ("slack_channel", group) in book.wrote_in:
                label = _channel_label(team, kind, roster.get("channel_name"))
                book.group("slack_channel", group, label, members)


def _channel_label(team: str, kind: str | None, name: str | None) -> str:
    return f"{team} group DM" if kind == "group_dm" else f"{team} #{name or 'a channel'}"


def _email(vault: Path, book: _Book) -> None:
    """People by address. A correspondent is one the user wrote to (to or cc, on mail to at most
    MAX_RECIPIENTS) or answered, named by the From name on their own mail."""
    mine = {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}
    mail = []
    for account in sorted(p for p in (vault / "raw" / "email").glob("*") if p.is_dir()):
        for r in _records(account):
            sender = (r.get("from_address") or "").lower()
            if r.get("from_me"):
                mine.add(sender)
                book.mine(r.get("from_name"))
            mail.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "from": sender,
                    "name": r.get("from_name"),
                    "mine": bool(r.get("from_me")),
                    "to": {a.lower() for a in [*(r.get("to") or []), *(r.get("cc") or [])]},
                    "parent": r.get("in_reply_to"),
                    "thread": r.get("gmail_thread"),
                    "subject": r.get("subject"),
                    "bulk": _bulk(r),
                }
            )
    mine.discard("")
    book.my_addresses |= mine
    for address in mine:
        book.mine(key=f"email:{address}")
    by_id = {m["id"]: m for m in mail}
    names: dict[str, Counter] = defaultdict(Counter)
    theirs: dict[str, list[str]] = defaultdict(list)
    for m in mail:
        if m["mine"] or m["bulk"] or m["from"] in mine:
            continue
        theirs[m["from"]].append(m["ts"])
        if name := _sender_name(m["name"]):
            names[m["from"]][name] += 1
    for address, known in names.items():
        book.name(f"email:{address}", _usual_name(known), "email")
    wrote: dict[str, dict[str, dict]] = defaultdict(dict)  # address → user's mail to it, by id
    for m in mail:
        if not m["mine"]:
            continue
        recipients = m["to"] - mine
        if len(recipients) <= MAX_RECIPIENTS:
            for address in recipients:
                wrote[address][m["id"]] = m
        parent = by_id.get(m["parent"] or "")
        if parent and not parent["mine"] and parent["from"] not in mine:
            wrote[parent["from"]][m["id"]] = m
    for address, sent in wrote.items():
        if not names.get(address) or _NO_REPLY.match(address.split("@")[0]):
            continue  # unnamed, or a robot: an address alone never goes in the index
        stamps = [m["ts"] for m in sent.values()] + theirs[address]
        book.add(
            None,
            "met",
            "email",
            key=f"email:{address}",
            first=min(stamps),
            last=max(stamps),
            interactions=len(stamps),
            topics=[_subject(m["subject"]) for m in sent.values()],
            org=_org(address),
        )
    _email_threads(book, mail, by_id, mine)


def _email_threads(book: _Book, mail: list[dict], by_id: dict[str, dict], mine: set) -> None:
    """Each thread, or one message with no replies, is a group of every address on it besides
    the user's, unless there are more than MAX_RECIPIENTS of them. Bulk mail has no people to speak
    of. An address that never wrote under a name counts towards the size and is no one."""
    threads: dict[str, dict] = {}
    for m in mail:
        if m["bulk"]:
            continue
        thread = threads.setdefault(_thread_key(m, by_id), {"addresses": set(), "subjects": []})
        thread["addresses"] |= ({m["from"]} | m["to"]) - mine - {""}
        if subject := _subject(m["subject"]):
            thread["subjects"].append(subject)
    for key, thread in threads.items():
        if len(thread["addresses"]) > MAX_RECIPIENTS:
            continue
        subject = thread["subjects"][0] if thread["subjects"] else None
        members = [f"email:{a}" for a in sorted(thread["addresses"])]
        book.group("email_thread", key, subject, members)


def _calendar(vault: Path, book: _Book, now: datetime) -> None:
    """Meetings: each past event of MIN_EVENT to MAX_EVENT guests who didn't decline, with the
    user among them or organizing, is a group of the others, and each of them met the user there. An
    event in two calendars counts once, and a moved instance of a repeating one is the same
    group as the series. A calendar is named after its owner's address (user@example.edu.ics
    is calendar/user-example-edu), so that address is the user's too, even if they never send
    mail from it."""
    streams = sorted(p for p in (vault / "raw" / "calendar").glob("*") if p.is_dir())
    for stream in streams:
        for r in _records(stream):
            for address in [r.get("organizer"), *(g.get("email") for g in r.get("guests") or [])]:
                address = (address or "").lower()
                if "@" in address and re.sub(r"[^\w-]", "-", address) == stream.name:
                    book.my_addresses.add(address)
                    book.mine(key=f"email:{address}")
    mine = book.my_addresses

    def me(guest: dict) -> bool:
        name = normalize(guest.get("name") or "")
        return guest["email"].lower() in mine or (bool(name) and _is_me(name, book.me))

    seen: set[str] = set()
    for stream in streams:
        for r in _records(stream):
            guests = [g for g in r.get("guests") or [] if isinstance(g, dict) and g.get("email")]
            if not guests or r["id"] in seen or (r.get("status") or "").upper() == "CANCELLED":
                continue
            seen.add(r["id"])
            when = _when(r.get("ts"))
            if when is None or when > now:
                continue
            present = [g for g in guests if (g.get("status") or "") != "declined"]
            if not MIN_EVENT <= len(present) <= MAX_EVENT:
                continue
            with_me = any(map(me, present)) or (r.get("organizer") or "").lower() in mine
            if mine and not with_me:
                continue  # someone else's event on a calendar the user can see
            summary = r.get("summary")
            members = []
            for guest in present:
                if me(guest):
                    continue
                key = f"email:{guest['email'].lower()}"
                book.name(key, guest.get("name"), "calendar")
                book.add(
                    None,
                    "met",
                    "calendar",
                    key=key,
                    first=r["ts"],
                    last=r["ts"],
                    interactions=1,
                    where=summary,
                    topics=[summary],
                )
                members.append(key)
            book.group("event", _RECURRENCE.sub("", r["id"]), summary, members)


def _usual_name(known: Counter) -> str:
    """The name an address writes under most, the fuller one on a tie."""
    return max(known, key=lambda n: (known[n], len(n.split())))


def _thread_key(m: dict, by_id: dict[str, dict]) -> str:
    """A message's thread: Gmail's id when it has one, else the oldest message it replies to
    that the user has (or the one it replies to, when that's missing)."""
    if m["thread"]:
        return f"gmail/{m['thread']}"
    root, seen = m, {m["id"]}
    while (parent := root["parent"]) and parent not in seen:
        seen.add(parent)
        if parent not in by_id:
            return f"reply/{parent}"
        root = by_id[parent]
    return f"reply/{root['id']}"


def _linkedin(vault: Path, book: _Book) -> None:
    root = vault / "raw" / "linkedin"
    for r in _records(root / "profile"):
        book.mine(r.get("author"))
    convos: dict[str, dict] = {}
    for r in _records(root / "messages"):
        convo = convos.setdefault(r.get("conversation_id") or r["id"], _chat(False, ""))
        convo["label"] = convo["label"] or r.get("conversation_title") or "a group conversation"
        if r.get("from_me"):
            book.mine(r.get("author"))
            convo["partners"].update(n.strip() for n in (r.get("to") or "").split(",") if n.strip())
            convo["messages"].append((r["ts"], None))
        else:
            convo["messages"].append((r["ts"], r.get("author") or ""))
    source = "linkedin/messages"
    for convo in convos.values():
        others = convo["partners"] | {sender for _, sender in convo["messages"] if sender}
        convo["partners"] = set()
        if len({normalize(n) for n in others} - book.me) <= 1:
            convo["direct"], convo["label"] = True, "direct"
            names = (n for n in others if normalize(n) not in book.me)
            convo["partners"] = {k for n in names if (k := book.name(None, n, source))}
        convo["messages"] = [
            (ts, sender if sender is None else book.name(None, sender, source) or "")
            for ts, sender in convo["messages"]
        ]
    _add_chats(book, source, convos.values())

    for r in _records(root / "connections"):
        role = " at ".join(filter(None, [r.get("position"), r.get("company")]))
        book.add(
            r.get("name"),
            "met",
            "linkedin/connections",
            key=f"li:{r['id']}" if r.get("id") else None,
            first=r["ts"],
            where=", ".join(filter(None, [f"since {r['ts'][:7]}", role])),
            org=r.get("company"),
        )


def _instagram(vault: Path, book: _Book) -> None:
    chats: dict[str, dict] = {}
    for r in _records(vault / "raw" / "instagram" / "messages"):
        chat = chats.get(r["chat_id"])
        if chat is None:
            name = r.get("chat_name")
            direct = r.get("chat_type") == "direct"
            chat = chats[r["chat_id"]] = (
                _chat(True, "direct chat") if direct else _chat(False, name or "a group", name)
            )
        if r.get("from_me"):
            book.mine(r.get("author"))
            sender = None
        else:
            sender = book.name(None, r.get("author"), "instagram") or ""
        chat["messages"].append((r["ts"], sender))
    _add_chats(book, "instagram", chats.values())


def _mentions(vault: Path, book: _Book) -> None:
    for stream, field in (("works", "coauthors"), ("citations", "authors")):
        for r in _records(vault / "raw" / "mentions" / stream):
            authors = r.get(field) or []
            if len(authors) > MAX_AUTHORS:
                authors = authors[:5] + authors[-1:]
            title = r.get("title")
            if key := r.get("id") or title:
                names = (_name_key(name) for name in authors)
                book.group("paper", str(key), title, [f"name:{n}" for n in names if n])
            for name in authors:
                _mention(
                    book, name, "know_of", f"mentions/{stream}", r["ts"], _quoted(title), [title]
                )


def _mention(
    book: _Book,
    name: str,
    relation: str,
    source: str,
    ts: str | None,
    where: str | None,
    topics: Iterable[str | None] = (),
) -> None:
    """One appearance of a name in a paper or a note, which counts as one interaction."""
    book.add(name, relation, source, first=ts, interactions=1, where=where, topics=topics)


def _writing(vault: Path, book: _Book) -> None:
    """Names in what the user wrote: reading notes, other notes, note tasks and their website."""
    pages = [_page(r) for r in _records(vault / "raw" / "notes" / "pages")]
    tasks = list(_records(vault / "raw" / "notes" / "tasks"))
    site = list(_records(vault / "raw" / "website" / "pages"))
    corpus = _corpus(
        [p["body"] for p in pages] + [r.get("text") or "" for r in site] + list(map(_task, tasks))
    )

    # Authors first, so that names in the text can match them.
    for page in pages:
        relation = "to_read" if page["to_read"] else "know_of"
        where = _where(page["title"], page["to_read"])
        for name in page["authors"]:
            _mention(book, name, relation, "notes/readings", page["ts"], where, page["topics"])
    for r in _records(vault / "raw" / "website" / "cv"):
        title = r.get("title")
        for name in _cv_authors(r.get("entry")):
            _mention(book, name, "know_of", "website", r["ts"], _quoted(title), [title])

    known = book.known_names()
    for page in pages:
        for name, relation in _mentioned(page["body"], corpus, known, page["to_read"]):
            where = _where(page["title"], relation == "to_read")
            _mention(book, name, relation, "notes/pages", page["ts"], where, page["topics"])
    for task in tasks:
        title = _task(task)
        reading = bool(_READ_TASK.match(title)) and not _task_done(task)
        for name, relation in _mentioned(title, corpus, known, reading):
            where = _where(title, relation == "to_read")
            _mention(book, name, relation, "notes/tasks", task.get("ts"), where)
    for r in site:
        for name, relation in _mentioned(r.get("text") or "", corpus, known, False):
            _mention(book, name, relation, "website", r["ts"], _quoted(r.get("title")))


def _page(record: dict) -> dict:
    """A notes page with its properties read, its body apart, and what it says about reading."""
    title = _one_line(record.get("title"))
    collection = _one_line(record.get("collection"))
    properties, body = _properties(record.get("text") or "")
    extra = record.get("properties")
    for key, value in (extra if isinstance(extra, dict) else {}).items():
        values = value if isinstance(value, list) else [value]
        properties.setdefault(_squash(key), "; ".join(str(v) for v in values if v))
    authors = [n for key in _AUTHOR_KEYS for n in _split_authors(properties.get(key) or "")]
    reading = bool(_READING.search(collection) or _READING.search(str(record.get("kind") or "")))
    status = " ".join(properties.get(key) or "" for key in _STATUS_KEYS)
    to_read = bool(
        _TO_READ_PAGE.search(title)
        or _TO_READ_PAGE.search(collection)
        or ((reading or authors) and _TO_READ_STATUS.search(status))
    )
    topics = [properties[key] for key in _TOPIC_KEYS if properties.get(key)]
    if not topics and title and not _DATELIKE.fullmatch(title):
        topics = [title]
    if to_read:
        flag = "to read"
    elif reading or authors or record.get("kind") == "csv_row":
        flag = None  # a reading or a database row is often only its properties, and that's fine
    elif len(body.strip()) < EMPTY_CHARS:
        flag = "empty"
    else:
        flag = "unfinished" if _UNFINISHED.search(body) else None
    return {
        "title": title,
        "collection": collection,
        "ts": record.get("ts"),
        "body": body,
        "authors": authors,
        "to_read": to_read,
        "topics": topics,
        "flag": flag,
    }


def _properties(text: str) -> tuple[dict[str, str], str]:
    """Properties at the top of a page ("Author: ..." lines under the title, as Notion exports
    them, or YAML front matter) by squashed key, and the text after them."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
    front = i < len(lines) and lines[i].strip() == "---"
    i += front
    properties: dict[str, str] = {}
    while i < len(lines):
        line = lines[i].strip()
        if front and line == "---":
            i += 1
            break
        match = _PROPERTY.fullmatch(line)
        if match:
            properties.setdefault(_squash(match[1]), match[2].strip().strip("\"'"))
        elif front or (not line and not properties):
            pass  # front matter's lists, or blank lines before the first property
        else:
            break
        i += 1
    return properties, "\n".join(lines[i:])


def _split_authors(value: str) -> list[str]:
    """Full names in an author field: "Jane Doe; Bo Li", "Doe, Jane", "Doe, J., Li, B.".
    A surname alone ("Doe et al., 2020") is no one in particular, so it's left out."""
    value = re.sub(r"\bet\.?\s+al\b\.?", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\(?\b(?:19|20)\d\d[a-z]?\b\)?", " ", value)
    names = []
    for part in re.split(r"\s*(?:;|&|\n|\band\b)\s*", value):
        pieces = [p.strip(" .") for p in part.split(",")]
        pieces = [p for p in pieces if p]
        if len(pieces) == 1:
            names.append(pieces[0])
        elif len(pieces) % 2 == 0 and all(map(_initials, pieces[1::2])):
            names += [f"{given} {last}" for last, given in zip(pieces[::2], pieces[1::2])]
        elif len(pieces) == 2 and value.count(",") == 1 and len(pieces[0].split()) == 1:
            names.append(f"{pieces[1]} {pieces[0]}")  # one "Last, First"
        elif pieces and all(len(p.split()) >= 2 for p in pieces):
            names += pieces
    return [n for n in names if _full_name(n)]


def _cv_authors(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return []
    names = []
    for key in ("authors", "author"):
        value = entry.get(key)
        if isinstance(value, str):
            names += _split_authors(value)
        elif isinstance(value, list):
            names += [n for v in value if isinstance(v, str) for n in _split_authors(v)]
    return names


def _initials(text: str) -> bool:
    words = re.findall(r"[^\W\d_]+", text)
    return bool(words) and all(len(w) <= 2 and w.isupper() for w in words)


def _full_name(name: str) -> bool:
    words = re.findall(r"[^\W\d_]+", name)
    return 2 <= len(words) <= 6 and any(len(w) > 1 for w in words) and not _CONTACT.search(name)


def _corpus(texts: Iterable[str]) -> tuple[Counter, Counter]:
    """How often each word appears in lower case, and capitalized, across all the user's writing."""
    lower, upper = Counter(), Counter()
    for text in texts:
        for word in _WORD.findall(_plain(text)):
            if word.islower():
                lower[word.casefold()] += 1
            elif word[0].isupper():
                upper[_POSSESSIVE.sub("", word).casefold()] += 1
    return lower, upper


def _mentioned(
    text: str, corpus: tuple[Counter, Counter], known: set[str], to_read: bool
) -> list[tuple[str, str]]:
    """Names in a text with their relation: to_read when the whole text is about reading or
    the sentence asks for it, know_of otherwise. One entry per person."""
    found: dict[str, tuple[str, str]] = {}
    for line in _plain(text).splitlines():
        for sentence in _SENTENCE.split(line):
            relation = "to_read" if to_read or _TO_READ_ASK.search(sentence) else "know_of"
            for name in _names_in(sentence, corpus, known):
                key = normalize(name)
                if key not in found or relation == "to_read":
                    found[key] = (name, relation)
    return list(found.values())


def _names_in(line: str, corpus: tuple[Counter, Counter], known: set[str]) -> list[str]:
    """Runs of capitalized words, separated by single spaces ("J. " after an initial), each
    cut into the names it holds. A run remembers the word just before it, for articles."""
    names: list[str] = []
    run: list[str] = []
    before, end = "", 0
    for match in _WORD.finditer(line):
        word = _POSSESSIVE.sub("", match[0])
        gap = line[end : match.start()]
        if run and not (gap == " " or (gap == ". " and len(run[-1]) == 1)):
            names += _split_run(run, corpus, known, before)
            run = []
        if gap != " " and not run:
            before = ""  # punctuation in between: the word before doesn't qualify this one
        if word[0].isupper() and not (len(word) > 1 and word.isupper()):
            run.append(word)
        else:
            if run:
                names += _split_run(run, corpus, known, before)
                run = []
            before = word
        end = match.end()
    return names + _split_run(run, corpus, known, before)


def _split_run(
    run: list[str], corpus: tuple[Counter, Counter], known: set[str], before: str = ""
) -> list[str]:
    """Names in a run of capitalized words: people already known by two to five of them, and
    stretches of name-like words between the words that aren't."""
    if len(run) < 2:
        return []
    names: list[str] = []
    stretch: list[str] = []
    i = 0
    while i < len(run):
        if j := _known_at(run, i, known):
            names += _stretch_name(stretch, before)
            names.append(" ".join(run[i:j]))
            stretch, before, i = [], run[j - 1], j
        elif _name_word(run[i], corpus):
            stretch.append(run[i])
            i += 1
        else:
            names += _stretch_name(stretch, before)
            stretch, before, i = [], run[i], i + 1
    return names + _stretch_name(stretch, before)


def _known_at(run: list[str], i: int, known: set[str]) -> int | None:
    """Where a known person's name starting at run[i] ends, longest first."""
    for j in range(min(len(run), i + 5), i + 1, -1):
        words = run[i:j]
        if not any(w.casefold() in _STOP for w in words) and normalize(" ".join(words)) in known:
            return j
    return None


def _stretch_name(stretch: list[str], before: str) -> list[str]:
    """A stretch of name-like words as a name: initials only inside, two to four full words,
    and no article before it, since "The Selfish Gene" is a title."""
    while stretch and len(stretch[0]) == 1:
        before, stretch = stretch[0], stretch[1:]  # "A Selfish Gene": "A" was an article
    while stretch and len(stretch[-1]) == 1:
        stretch = stretch[:-1]
    full = sum(len(w) > 1 for w in stretch)
    if before.casefold() in _ARTICLES or not 2 <= full <= 4 or len(stretch) > 5:
        return []
    return [" ".join(stretch)]


def _name_word(word: str, corpus: tuple[Counter, Counter]) -> bool:
    if len(word) == 1:
        return word.isupper()  # a middle initial
    folded = word.casefold()
    if folded in _STOP:
        return False
    lower, upper = corpus
    # A word the user's notes also write in lower case is a word, not a name: "Working Memory".
    return not (lower[folded] >= 2 and lower[folded] * 5 >= upper[folded])


def _plain(text: str) -> str:
    """Text without code, link targets or addresses; wiki links as their shown text."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return _LINK.sub(" ", text)


def _task(task: dict) -> str:
    return next((_one_line(task[k]) for k in ("title", "task", "name", "text") if task.get(k)), "")


def _task_done(task: dict) -> bool:
    flags = ("done", "completed", "complete", "checked", "archived", "archive")
    return any(_truthy(task.get(key)) for key in flags) or bool(
        _DONE.search(str(task.get("status") or ""))
    )


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"yes", "true", "done", "x", "1", "checked"}
    return value is True


def _where(title: str, to_read: bool) -> str | None:
    if not title:
        return "marked to read" if to_read else None
    return f"{_quoted(title)}, to read" if to_read else _quoted(title)


def _quoted(title: str | None) -> str | None:
    return f"“{_clip(_one_line(title), 70)}”" if title else None


def _display(name: str) -> str:
    """A name as shown: no brackets, emoji, titles or degrees, and "Last, First" turned round."""
    text = unicodedata.normalize("NFC", name)
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|<[^>]*>", " ", text)
    text = "".join(
        c if c.isalpha() or unicodedata.category(c).startswith("M") or c in ".,'’-" else " "
        for c in text
    )
    if text.count(",") == 1:
        last, first = (part.strip(" .-'’") for part in text.split(","))
        if _squash(first) in _DEGREES:
            text = last
        elif first and last:
            text = f"{first} {last}"
    words = text.replace(",", " ").split()
    while words and _squash(words[0]) in _TITLES:
        words.pop(0)
    while words and _squash(words[-1]) in _DEGREES:
        words.pop()
    return " ".join(w.strip("-'’") for w in words if w.strip(".-'’"))


def _plausible(key: str) -> bool:
    words = key.split()
    return (
        bool(words)
        and key not in _GENERIC
        and any(len(w) > 1 for w in words)
        and len(words) <= 6
        and len(key) <= 60
    )


def _is_me(key: str, me: set[str]) -> bool:
    """One of the user's names, or their first and last name around a middle one, or their
    initial."""
    if key in me:
        return True
    words = key.split()
    if len(words) < 2:
        return False
    for name in me:
        own = name.split()
        initial = len(words[0]) == 1 and own[0].startswith(words[0])
        if len(own) >= 2 and own[-1] == words[-1] and (words[0] == own[0] or initial):
            return True
    return False


def _best(names: Counter, sources: dict[str, set[str]]) -> str:
    """The way of writing a name to show: a full name before a first name alone, then the one
    the most sources use, then mixed case, then most used, then with accents."""
    return max(
        names,
        key=lambda n: (
            _full(normalize(n)),
            len(sources.get(n, ())),
            n != n.lower() and n != n.upper(),
            names[n],
            not n.isascii(),
            len(n),
        ),
    )


def _sender_name(name: str | None) -> str | None:
    """A From name that names the sender: not an address, and not "X via Some List"."""
    name = (name or "").strip().strip("\"'")
    if not name or "@" in name or " via " in name.casefold():
        return None
    return name


def _subject(subject: str | None) -> str | None:
    return _SUBJECT_PREFIX.sub("", subject or "").strip() or None


def _org(address: str) -> str | None:
    domain = address.rpartition("@")[2]
    return domain if domain and domain not in _WEBMAIL else None


def _bulk(record: dict) -> bool:
    labels = {
        label.upper().lstrip("\\").replace(" ", "_") for label in record.get("gmail_labels") or []
    }
    local_part = (record.get("from_address") or "").split("@")[0]
    return bool(labels & _BULK_LABELS) or bool(_NO_REPLY.match(local_part))


# Connections


def closeness(size: int) -> float:
    """What sharing one group of `size` people adds to a tie: a pair alone counts most, and a
    channel of thousands next to nothing."""
    return 1 / math.log2(max(size, 2) + 1)


def connections(
    groups: list[dict], core: list[dict], now: datetime
) -> tuple[list[dict], list[dict]]:
    """Edges between the people in core and the groups that make them, from every group of the
    index (members as sets of ids). Groups keep only their members in core, and those left
    with fewer than two are dropped. Each group two people share adds closeness(its size) to
    their tie, so a few small groups outweigh a big channel; the size is everyone in it (from
    "size", else its members), not just those in core. Only GRAPH_EDGES are kept: heaviest
    first, then the most groups shared, then the more active pair. An edge names its closest
    contexts first."""
    rank = {p["id"]: _score(p, now) for p in core}
    kept = []
    for group in groups:
        members = sorted(set(group["members"]) & rank.keys())
        if len(members) >= 2:
            size = group.get("size") or len(group["members"])
            kept.append(group | {"members": members, "size": size})
    kept.sort(key=lambda g: (GROUP_KINDS.index(g["kind"]), -len(g["members"]), g["name"], g["id"]))

    shared, weight = _pairs(kept)
    order = sorted(
        shared, key=lambda p: (-weight[p], -len(shared[p]), -(rank[p[0]] + rank[p[1]]), p)
    )
    edges = []
    for a, b in order[:GRAPH_EDGES]:
        together = sorted(
            shared[a, b], key=lambda g: (g["size"], GROUP_KINDS.index(g["kind"]), g["name"])
        )
        edges.append(
            {
                "source": a,
                "target": b,
                "weight": round(weight[a, b], 4),
                "shared": len(together),
                "contexts": [
                    _clip(f"{_GROUP_KINDS[g['kind']][0]}: {g['name']}", TOPIC_CHARS)
                    for g in together[:EDGE_CONTEXTS]
                ],
            }
        )
    return edges, kept


def _pairs(groups: list[dict]) -> tuple[dict[tuple[str, str], list[dict]], dict]:
    """Every pair of members who share a group: the groups, and the tie they make."""
    shared: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for group in groups:
        for pair in itertools.combinations(sorted(group["members"]), 2):
            shared[pair].append(group)
    weight = {pair: sum(closeness(g["size"]) for g in found) for pair, found in shared.items()}
    return shared, weight


def clusters(groups: list[dict], core: list[dict]) -> tuple[dict[str, int], list[dict]]:
    """Communities among the people in core: Louvain on every pair that shares a group,
    weighted as edges are (all of them, not only the edges kept). Each community of MIN_CLUSTER
    or more gets an id, biggest first, and a label: the name of the group most of its people are in,
    named groups before unnamed ones, and no label twice. People with no tie are in none."""
    _, weight = _pairs(groups)
    community = _louvain(sorted({p["id"] for p in core}), weight)
    members: dict[str, list[str]] = defaultdict(list)
    for node, label in community.items():
        members[label].append(node)
    found = [sorted(m) for m in members.values() if len(m) >= MIN_CLUSTER]
    found.sort(key=lambda m: (-len(m), m))
    by_person: dict[str, int] = {}
    named, used = [], set()
    for n, people in enumerate(found, 1):
        by_person.update(dict.fromkeys(people, n))
        label = _cluster_label(set(people), groups, used) or f"Cluster {n}"
        named.append({"id": n, "label": label, "size": len(people)})
    return by_person, named


def _cluster_label(people: set[str], groups: list[dict], used: set[str]) -> str | None:
    ranked = []
    for g in groups:
        inside = len(people.intersection(g["members"]))
        if inside >= 2:
            named = g["name"] != _GROUP_KINDS[g["kind"]][1]
            ranked.append((named, inside, inside / len(g["members"]), -g["size"], g["name"]))
    ranked.sort(reverse=True)
    for *_, name in ranked:
        if name not in used:
            used.add(name)
            return name
    return None


def _louvain(nodes: list[str], weight: dict[tuple[str, str], float]) -> dict[str, str]:
    """Each node's community by Louvain's method (Blondel et al. 2008): move each node to the
    neighbouring community that raises modularity most until none moves, make each community
    one node, and repeat until no two merge. Nodes are visited in sorted order, so the same
    graph always gives the same communities. A node with no tie is a community of one."""
    graph: dict[str, dict[str, float]] = {n: {} for n in nodes}
    for (a, b), w in weight.items():
        if a in graph and b in graph:
            graph[a][b] = graph[a].get(b, 0.0) + w
            graph[b][a] = graph[b].get(a, 0.0) + w
    of = {n: n for n in nodes}
    for _ in range(LOUVAIN_LEVELS):
        moved = _louvain_level(graph)
        if len(set(moved.values())) == len(moved):
            break
        of = {n: moved[c] for n, c in of.items()}
        merged: dict[str, dict[str, float]] = {c: {} for c in moved.values()}
        for node, neighbours in graph.items():
            here = merged[moved[node]]
            for other, w in neighbours.items():
                here[moved[other]] = here.get(moved[other], 0.0) + w
        graph = merged
    return of


def _louvain_level(graph: dict[str, dict[str, float]]) -> dict[str, str]:
    """One level of Louvain: each node's community, named by one of its nodes. A self-loop
    (graph[n][n]) is the weight inside a node made of a community."""
    degree = {n: sum(neighbours.values()) for n, neighbours in graph.items()}
    total = sum(degree.values())  # twice the weight of all edges
    community = {n: n for n in graph}
    if total == 0:
        return community
    tot = dict(degree)  # community → the degrees of its nodes
    for _ in range(LOUVAIN_PASSES):
        moved = False
        for node in sorted(graph):
            here, k = community[node], degree[node]
            links: dict[str, float] = defaultdict(float)
            for other, w in graph[node].items():
                if other != node:
                    links[community[other]] += w
            tot[here] -= k
            best, gain = here, links.get(here, 0.0) - tot[here] * k / total
            for c in sorted(links):
                if (g := links[c] - tot[c] * k / total) > gain + 1e-12:
                    best, gain = c, g
            tot[best] += k
            if best != here:
                community[node] = best
                moved = True
        if not moved:
            break
    return community


# Ideas


def ideas(vault: Path, people: list[dict], profile: str, now: datetime) -> dict[str, int]:
    """One model call for projects, outreach and reading, written to ideas.json."""
    out = vault / "clones" / "network"
    history = _load_json(out / "history.json")
    previous = _load_json(out / "ideas.json")
    _remember(history, previous, (previous.get("generated") or _iso(now))[:10])
    reactions = _feedback(out / "feedback.jsonl")
    last_ids = {item["id"] for item in _items(previous)}

    answer = llm.ask(
        prompt(
            profile, people, _notes_text(vault), _history_text(history, reactions, last_ids), now
        ),
        system=_SYSTEM.format(person=env("NAME", "the person")),
        schema=_SCHEMA,
        effort="high",
    )
    result = _accept(answer, people, _blocked(history, reactions))
    _remember(history, result, _iso(now)[:10])
    _write_json(out / "ideas.json", {"generated": _iso(now)} | result)
    _write_json(out / "history.json", history)
    return {
        "projects": len(result["projects"]),
        "outreach": len(result["outreach"]),
        "suggested_reads": len(result["to_read"]),
    }


def prompt(profile: str, people: list[dict], notes: str, history: str, now: datetime) -> str:
    shown = top_people(people, now)
    counts = Counter(p["relation"] for p in people)
    parts = [
        f"Today is {now.astimezone():%A %Y-%m-%d}.",
        f"# Self-model\n\n{profile}",
        (
            f"# People\n\nThe index has {len(people)} people: {counts['met']} met, "
            f"{counts['know_of']} known of, {counts['to_read']} to read. These {len(shown)} "
            "are the most active and recent of each kind. Ids are in brackets; context says how "
            "they know each one, and topics what they share."
        ),
    ]
    heads = {
        "met": "Met: messages exchanged, or a LinkedIn connection",
        "know_of": "Known of: co-authors, people citing their work, authors and names in notes",
        "to_read": "Want to read",
    }
    for relation, head in heads.items():
        lines = [_person_line(p) for p in shown if p["relation"] == relation]
        parts.append(f"## {head}\n\n" + ("\n".join(lines) or "None."))
    parts.append(
        "# Their notes, titles by collection\n\n"
        "[empty] marks a page with a title and little else, [unfinished] one with open "
        "checkboxes or TODOs, [to read] a reading not started. Empty and unfinished pages are "
        "plans they haven't got to.\n\n" + (notes or "None on record.")
    )
    parts.append(f"# Earlier ideas and how they took them\n\n{history}")
    return "\n\n".join(parts)


def top_people(people: list[dict], now: datetime, limit: int = TOP_PEOPLE) -> list[dict]:
    """The people to show the model: the best of each relation by its quota, best first, and
    any places a relation leaves unused go to the next best overall."""
    ranked = sorted(people, key=lambda p: _score(p, now), reverse=True)
    chosen: set[str] = set()
    for relation, quota in QUOTAS.items():
        chosen.update(p["id"] for p in [p for p in ranked if p["relation"] == relation][:quota])
    for p in ranked:
        if len(chosen) >= limit:
            break
        chosen.add(p["id"])
    return [p for p in ranked if p["id"] in chosen][:limit]


def _score(person: dict, now: datetime) -> float:
    """More messages count, logarithmically, and halve in weight for every year since."""
    last = _when(person.get("last_seen"))
    age = max((now - last).days, 0) if last else 10 * 365
    return math.log2(2 + person["interactions"]) * 0.5 ** (age / HALF_LIFE_DAYS)


def _person_line(person: dict) -> str:
    line = f"- [{person['id']}] {person['name']}"
    if person["org"]:
        line += f" ({person['org']})"
    line += f": {person['context']}"
    if person["topics"]:
        line += f". Topics: {'; '.join(person['topics'])}"
    if person["last_seen"]:
        line += f". Last {person['last_seen'][:7]}"
    return line + "."


def _notes_text(vault: Path) -> str:
    pages = [_page(r) for r in _records(vault / "raw" / "notes" / "pages")]
    tasks = [t for t in _records(vault / "raw" / "notes" / "tasks") if _task(t)]
    # A reading list's rows have a status too, but they're listed with the readings.
    tasks = [
        t
        for t in tasks
        if not _task_done(t) and not _READING.search(str(t.get("collection") or ""))
    ]
    by_collection: dict[str, list[dict]] = defaultdict(list)
    for page in pages:
        if page["title"]:
            by_collection[page["collection"] or "(no collection)"].append(page)

    parts, budget = [], NOTE_TITLES
    for collection, group in sorted(by_collection.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        group.sort(key=lambda p: p["ts"] or "", reverse=True)
        group.sort(key=lambda p: p["flag"] is None)  # marked pages first, newest first
        shown = group[: min(PER_COLLECTION, budget)]
        budget -= len(shown)
        marked = sum(p["flag"] is not None for p in group)
        lines = [f"## {collection} ({len(group)} pages{f', {marked} marked' if marked else ''})"]
        lines += [f"- {p['title']}" + (f" [{p['flag']}]" if p["flag"] else "") for p in shown]
        if len(group) > len(shown):
            lines.append(f"- and {len(group) - len(shown)} more")
        parts.append("\n".join(lines))
    if tasks:
        lines = [f"- {_clip(_task(t), 160)}" for t in tasks[-OPEN_TASKS:]]
        parts.append(f"## Open tasks in their notes ({len(tasks)})\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _history_text(history: dict[str, dict], reactions: dict[str, str], last_ids: set) -> str:
    heads = {
        "done": "They did these. Context only: build on them, don't suggest them again.",
        "not_me": "They marked these not them. Never suggest them again, reworded or not.",
        "useful": "They found these useful.",
        None: "Given last time, no reaction yet. Keep one only if it's still among the best.",
    }
    groups: dict[str | None, list[str]] = defaultdict(list)
    for key, item in sorted(history.items(), key=lambda kv: kv[1].get("given") or ""):
        action = reactions.get(key)
        if action is None and key not in last_ids:
            continue
        text = f"{item['name']}: {item['text']}" if item.get("name") else item["text"]
        groups[action].append(f"- [{item['kind']}] {text} (given {item.get('given')})")
    text = "\n\n".join(
        "\n".join([head, *groups[action]]) for action, head in heads.items() if groups[action]
    )
    return text or "None yet."


def _blocked(history: dict[str, dict], reactions: dict[str, str]) -> dict[str, set]:
    """What may not come back: ids marked not me or done, their texts folded, the people of
    outreach marked not me, and the names of reading marked not me."""
    closed = {key for key, action in reactions.items() if action in ("not_me", "done")}
    items = {key: history[key] for key in closed if key in history}
    not_me = {key: item for key, item in items.items() if reactions[key] == "not_me"}
    return {
        "ids": closed,
        "texts": {_fold(item["text"]) for item in items.values()},
        "people": {i.get("person_id") for i in not_me.values() if i["kind"] == "outreach"},
        "names": {normalize(i["text"]) for i in not_me.values() if i["kind"] == "to_read"},
    }


def _accept(answer: dict, people: list[dict], blocked: dict[str, set]) -> dict[str, list]:
    """The model's ideas, checked: people only from the index, nothing closed coming back, no
    duplicates, ids from the text."""
    index = {p["id"]: p for p in people}
    by_name = {normalize(p["name"]): p for p in people}
    me = {normalize(env(name)) for name in ("NAME", "FULL_NAME")}
    me.discard("")
    seen: set[str] = set()  # folded texts of the ideas kept so far

    def fresh(text: str) -> str | None:
        """The idea's id, or None when it's empty, closed, or a repeat in other case."""
        key, folded = idea_id(text), _fold(text)
        if not folded or key in blocked["ids"] or folded in blocked["texts"] | seen:
            return None
        seen.add(folded)
        return key

    projects = []
    for item in answer["projects"]:
        title = _one_line(item["title"])
        if key := fresh(title):
            projects.append(
                {
                    "id": key,
                    "title": title,
                    "pitch": item["pitch"].strip(),
                    "why_you": item["why_you"].strip(),
                    "people": [p for p in dict.fromkeys(item["people"]) if p in index],
                    "first_step": item["first_step"].strip(),
                }
            )
    outreach, reached = [], set()
    for item in answer["outreach"]:
        person = index.get(item["person_id"].strip()) or by_name.get(normalize(item["name"]))
        if person is None or person["id"] in blocked["people"] | reached:
            continue
        ask = _one_line(item["ask"])
        if key := fresh(ask):
            reached.add(person["id"])
            outreach.append(
                {
                    "id": key,
                    "person_id": person["id"],
                    "name": person["name"],
                    "why": item["why"].strip(),
                    "ask": ask,
                    "channel": item["channel"],
                }
            )
    reading = []
    for item in answer["to_read"]:
        name = _one_line(item["name"])
        norm = normalize(name)
        if not norm or norm in blocked["names"] or _is_me(norm, me):
            continue
        if key := fresh(name):
            reading.append({"id": key, "name": name, "why": item["why"].strip()})
    return {
        "projects": projects[: LIMITS["projects"]],
        "outreach": outreach[: LIMITS["outreach"]],
        "to_read": reading[: LIMITS["to_read"]],
    }


def idea_id(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


# Each list in ideas.json: the kind its ideas go by in history, and the field an id hashes.
_MAIN_TEXT = {
    "projects": ("project", "title"),
    "outreach": ("outreach", "ask"),
    "to_read": ("to_read", "name"),
}


def _items(ideas_: dict) -> Iterator[dict]:
    """Every idea in an ideas.json, with its kind, skipping any without an id or main text."""
    for group, (kind, field) in _MAIN_TEXT.items():
        for item in ideas_.get(group) or []:
            if isinstance(item, dict) and item.get("id") and item.get(field):
                yield item | {"kind": kind, "text": item[field]}


def _remember(history: dict[str, dict], ideas_: dict, day: str) -> None:
    """Every idea given, by id, with its main text, so verdicts outlive ideas.json."""
    for item in _items(ideas_):
        entry = {"kind": item["kind"], "text": item["text"], "given": day}
        if item["kind"] == "outreach":
            entry |= {"name": item.get("name"), "person_id": item.get("person_id")}
        history.setdefault(item["id"], entry)


def read_self(self_dir: Path) -> str:
    """Every file of the self-model, identity first. The changelog is history, not the model."""
    paths = sorted(self_dir.glob("*.md"), key=lambda p: (p.stem != "identity", p.stem))
    texts = [(p.stem, p.read_text(encoding="utf-8").strip()) for p in paths]
    texts = [(name, text) for name, text in texts if text and name != "CHANGELOG"]
    if not texts:
        raise SystemExit(
            f"network: there's no self-model yet ({self_dir} is empty). `proxenos master` builds "
            "the profile first; run that, or pass --people-only for just the people index."
        )
    return "\n\n".join(f"<{name}>\n{text}\n</{name}>" for name, text in texts)


def _feedback(path: Path) -> dict[str, str]:
    """The user's latest verdict on each idea from the page: {item_id: action}."""
    if not path.exists():
        return {}
    latest: dict[str, tuple[datetime, str]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
                key, action, when = event["item_id"], event["action"], _when(event["ts"])
            except (ValueError, KeyError, TypeError):
                continue  # the page writes this file, and one bad line shouldn't stop a run
            if action not in _REACTIONS or when is None or not isinstance(key, str):
                continue
            if key not in latest or when >= latest[key][0]:
                latest[key] = (when, action)
    return {key: action for key, (_, action) in latest.items()}


# Small helpers


def _records(directory: Path) -> Iterator[dict]:
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _scrub(text: str) -> str:
    """Text with any email address or phone number taken out. Dates stay."""

    def number(match: re.Match) -> str:
        digits = sum(c.isdigit() for c in match[0])
        return match[0] if digits < 7 or _DATE.fullmatch(match[0].strip()) else " "

    return " ".join(_NUMBER.sub(number, _EMAIL.sub(" ", text)).split())


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _fold(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


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
