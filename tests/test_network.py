"""Network clone on a synthetic vault with the model faked out. No network, no real data."""

import argparse
import hashlib
import itertools
import json
import math
import re
from datetime import UTC, datetime

import pytest

from proxenos import llm
from proxenos.clones import network

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
GENERATED = "2026-03-10T12:00:00Z"
ME = "tess@example.net"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r) + "\n" for r in records))


def wa(n, chat, ts, sender=None, chat_name=None, chat_type="direct", kind="text"):
    return {
        "id": f"{chat}/{n}",
        "ts": ts,
        "chat_id": chat,
        "chat_name": chat_name,
        "chat_type": chat_type,
        "from_me": sender is None,
        # A direct chat's sender is the chat; in a group, each member has a jid of their own.
        "sender_id": chat if chat_type == "direct" else (f"{sender}@lid" if sender else None),
        "sender_name": sender,
        "kind": kind,
        "text": "hello",
    }


def slack(n, channel, kind, ts, user, name, from_me=False, channel_name=None, subtype=None):
    return {
        "id": f"{channel}/{n}",
        "ts": ts,
        "channel_id": channel,
        "channel_name": channel_name,
        "channel_type": kind,
        "user_id": user,
        "user_name": name,
        "from_me": from_me,
        "text": "hi",
        "subtype": subtype,
    }


def mail(n, ts, sender, to, name=None, subject="Hello", reply_to=None, labels=None):
    return {
        "id": f"m{n}",
        "ts": ts,
        "from_address": sender,
        "from_name": name,
        "from_me": sender == ME,
        "to": to,
        "cc": None,
        "subject": subject,
        "in_reply_to": reply_to,
        "gmail_labels": labels,
    }


def page(n, title, collection, text, ts="2026-01-15T00:00:00Z", **extra):
    return {"id": f"p{n}", "ts": ts, "title": title, "collection": collection, "text": text} | extra


LAB_NOTES = """# Lab notes

Met Ada Placeholder after the Monday Lab Meeting. We talked about working memory and the
working memory model.
Working Memory Load matters.
Want to read Rhea Inkwell next week.
Saw Theo Margin at the poster, with Dr. Tess Wintest.
"""


def make_vault(tmp_path, monkeypatch, notes=True):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_FULL_NAME", "Tess Wintest")
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    vault = tmp_path / "vault"
    raw = vault / "raw"
    write_jsonl(
        raw / "whatsapp" / "messages" / "2026-02.jsonl",
        [
            # A direct chat the user answered: all three messages count.
            wa(1, "c1", "2026-02-01T10:00:00Z", "Ada Placeholder", "Ada Placeholder"),
            wa(2, "c1", "2026-02-01T10:05:00Z", None, "Ada Placeholder"),
            wa(3, "c1", "2026-02-20T09:00:00Z", "Ada Placeholder", "Ada Placeholder"),
            # A group: Bram wrote on a day the user did, Cleo only on another day.
            wa(4, "c2", "2026-02-03T08:00:00Z", None, "Spiral Club", "group"),
            wa(5, "c2", "2026-02-03T09:00:00Z", "Bram Sample", "Spiral Club", "group"),
            wa(6, "c2", "2026-02-03T09:30:00Z", "Bram Sample", "Spiral Club", "group"),
            wa(7, "c2", "2026-02-05T09:00:00Z", "Cleo Example", "Spiral Club", "group"),
            wa(8, "c2", "2026-02-03T09:40:00Z", "", "Spiral Club", "group"),
            wa(9, "c2", "2026-02-03T09:50:00Z", "Gil Joiner", "Spiral Club", "group", "system"),
            # A chat known only by its number, one never written in, and the user's own notes chat.
            wa(10, "c3", "2026-02-04T08:00:00Z", "+1 555 010 0000", "+1 555 010 0000"),
            wa(11, "c3", "2026-02-04T08:01:00Z", None, "+1 555 010 0000"),
            wa(12, "c4", "2026-02-04T08:00:00Z", "Dov Fixture", "Dov Fixture"),
            wa(13, "c5", "2026-02-04T08:00:00Z", None, "Tess Wintest"),
        ],
    )
    write_jsonl(
        raw / "slack" / "acme" / "messages" / "2026-02.jsonl",
        [
            slack(
                1,
                "D1",
                "dm",
                "2026-02-06T10:00:00Z",
                "U2",
                "Esme Mockley",
                channel_name="Esme Mockley",
            ),
            slack(
                2, "D1", "dm", "2026-02-06T10:01:00Z", "U1", "Tess Wintest", True, "Esme Mockley"
            ),
            slack(
                3, "C1", "channel", "2026-02-07T10:00:00Z", "U1", "Tess Wintest", True, "methods"
            ),
            slack(
                4,
                "C1",
                "channel",
                "2026-02-07T11:00:00Z",
                "U3",
                "Finn Stub",
                channel_name="methods",
            ),
            slack(
                5,
                "C1",
                "channel",
                "2026-02-07T11:05:00Z",
                "B9",
                "Build Bot",
                channel_name="methods",
            ),
            slack(
                6,
                "C1",
                "channel",
                "2026-02-07T11:06:00Z",
                "U4",
                "Gil Joiner",
                False,
                "methods",
                "channel_join",
            ),
        ],
    )
    many = [f"r{i}@example.com" for i in range(20)]
    write_jsonl(
        raw / "email" / "personal" / "2026-02.jsonl",
        [
            mail(
                1,
                "2026-02-10T09:00:00Z",
                "ada@example.edu",
                [ME],
                "Placeholder, Ada",
                "Spiral data",
            ),
            mail(
                2,
                "2026-02-10T12:00:00Z",
                ME,
                ["ada@example.edu"],
                "Tess Wintest",
                "Re: Spiral data",
                "m1",
            ),
            mail(
                3, "2026-02-11T09:00:00Z", ME, ["gus@example.org"], "Tess Wintest", "Poster draft"
            ),
            mail(
                4,
                "2026-02-12T09:00:00Z",
                "gus@example.org",
                [ME],
                "Gus Testcase",
                "Re: Poster draft",
            ),
            mail(5, "2026-02-12T10:00:00Z", ME, ["nobody@example.com"], "Tess Wintest"),
            mail(6, "2026-02-12T11:00:00Z", "news@list.example", [ME], "Weekly News"),
            mail(7, "2026-02-13T09:00:00Z", ME, many, "Tess Wintest", "To everyone"),
            mail(8, "2026-02-13T10:00:00Z", "r0@example.com", [ME], "Ray Many", "Re: To everyone"),
            mail(9, "2026-02-14T09:00:00Z", ME, ["noreply@service.example"], "Tess Wintest"),
            mail(10, "2026-02-14T10:00:00Z", "noreply@service.example", [ME], "Service Bot"),
            mail(
                11,
                "2026-02-15T10:00:00Z",
                "promo@shop.example",
                [ME],
                "Pat Promo",
                labels=["CATEGORY_PROMOTIONS"],
            ),
        ],
    )
    linkedin = raw / "linkedin"
    write_jsonl(
        linkedin / "profile" / "2026-01.jsonl",
        [
            {
                "id": "profile/x",
                "ts": "2026-01-01T00:00:00Z",
                "from_me": True,
                "author": "Tess Wintest",
            }
        ],
    )
    write_jsonl(
        linkedin / "messages" / "2026-01.jsonl",
        [
            {
                "id": "L1/a",
                "ts": "2026-01-05T10:00:00Z",
                "conversation_id": "L1",
                "from_me": False,
                "author": "Hana Dummy",
                "to": "Tess Wintest",
            },
            {
                "id": "L1/b",
                "ts": "2026-01-06T10:00:00Z",
                "conversation_id": "L1",
                "from_me": True,
                "author": "Tess Wintest",
                "to": "Hana Dummy",
            },
            {
                "id": "L2/a",
                "ts": "2026-01-07T10:00:00Z",
                "conversation_id": "L2",
                "from_me": False,
                "author": "Rex Recruiter",
                "to": "Tess Wintest",
            },
        ],
    )
    write_jsonl(
        linkedin / "connections" / "2025-06.jsonl",
        [
            {
                "id": "k1",
                "ts": "2025-06-01T00:00:00Z",
                "from_me": False,
                "name": "Ivo Mock",
                "company": "Acme Labs",
                "position": "Scientist",
            },
            {
                "id": "k2",
                "ts": "2025-06-02T00:00:00Z",
                "from_me": False,
                "name": "Hana Dummy",
                "company": None,
                "position": None,
            },
        ],
    )
    write_jsonl(
        raw / "mentions" / "works" / "2025-05.jsonl",
        [
            {
                "id": "W1",
                "ts": "2025-05-01T00:00:00Z",
                "title": "Spirals in the brain",
                "coauthors": ["Jo Coauthor", "Ada Placeholder"],
            }
        ],
    )
    write_jsonl(
        raw / "mentions" / "citations" / "2025-09.jsonl",
        [
            {
                "id": "W2",
                "ts": "2025-09-01T00:00:00Z",
                "title": "More on spirals",
                "authors": ["Kai Citer", "T. Wintest"],
            }
        ],
    )
    write_jsonl(
        raw / "website" / "cv" / "2024-01.jsonl",
        [
            {
                "id": "cv#pubs/a",
                "ts": "2024-01-01T00:00:00Z",
                "title": "A spiral paper",
                "entry": {"authors": "Tess Wintest, Xan Coder"},
            }
        ],
    )
    write_jsonl(
        raw / "website" / "pages" / "2024-01.jsonl",
        [
            {
                "id": "about.md",
                "ts": "2024-01-01T00:00:00Z",
                "title": "About",
                "text": "Thanks to Yara Helper for the figures.",
            }
        ],
    )
    if notes:
        write_jsonl(
            raw / "notes" / "pages" / "2026-01.jsonl",
            [
                page(
                    1,
                    "A Paper On Spirals",
                    "Readings/Papers",
                    "# A Paper On Spirals\n\nAuthor: Lu Reader\nStatus: Not started\n",
                ),
                page(
                    2,
                    "Some Study",
                    "Literature Review",
                    "",
                    properties={"Author, Year": "Moss et al., 2020", "Status": "Read"},
                ),
                page(
                    3,
                    "Another Study",
                    "Literature Review",
                    "# Another Study\n\nAuthor: Doe, Quinn\nStatus: Done\nTopic: spiral coding\n\nGood paper.",
                ),
                page(4, "Lab notes", "research", LAB_NOTES, ts="2026-02-01T00:00:00Z"),
                page(5, "Grant idea: spirals", "research", "# Grant idea: spirals\n"),
                page(
                    6,
                    "Draft outline",
                    "research",
                    "# Draft outline\n\n- [ ] write the methods section of the spiral paper\n",
                ),
                # A database row is only properties, which doesn't make it an empty page.
                page(
                    7,
                    "Sunset photo",
                    "My Space/Gallery",
                    None,
                    kind="csv_row",
                    properties={"Name": "Sunset photo", "Tags": "travel"},
                ),
            ],
        )
        write_jsonl(
            raw / "notes" / "tasks" / "2026-01.jsonl",
            [
                {
                    "id": "t1",
                    "ts": "2026-01-20T00:00:00Z",
                    "title": "Read Uma Quill on spirals",
                    "status": "Not started",
                },
                {
                    "id": "t2",
                    "ts": "2026-01-21T00:00:00Z",
                    "title": "Read Wren Archer review",
                    "status": "Done",
                },
                {
                    "id": "t3",
                    "ts": "2026-01-22T00:00:00Z",
                    "title": "Book the poster printer",
                    "status": "To do",
                },
                {
                    "id": "t4",
                    "ts": "2026-01-23T00:00:00Z",
                    "title": "A Paper On Spirals",
                    "status": "Not started",
                    "collection": "Readings/Papers",
                },
            ],
        )
    return vault


def no_model(*args, **kwargs):
    raise AssertionError("the model must not be called")


def people_by_name(vault):
    data = json.loads((vault / "clones" / "network" / "people.json").read_text(encoding="utf-8"))
    return data, {p["name"]: p for p in data["people"]}


def test_normalize_matches_the_same_person_and_nothing_looser():
    assert network.normalize("Dr. José  Núñez, PhD") == "jose nunez"
    assert network.normalize("Núñez, José") == "jose nunez"
    assert network.normalize("José A. Núñez") == "jose nunez"
    assert network.normalize("O'Brien-Smith, Ann") == "ann obrien smith"
    assert network.person_id("Núñez, José") == network.person_id("jose nunez")
    assert network.person_id("Núñez, José") == hashlib.sha1(b"jose nunez").hexdigest()[:12]
    assert network.normalize("J. Núñez") != network.normalize("José Núñez")


def test_split_authors_keeps_full_names_only():
    assert network._split_authors("Jane Roe; Bo Li and Ann Lee") == ["Jane Roe", "Bo Li", "Ann Lee"]
    assert network._split_authors("Roe, Jane") == ["Jane Roe"]
    assert network._split_authors("Roe, J., Li, B. A.") == ["J Roe", "B. A Li"]
    assert network._split_authors("Roe et al., 2020") == []
    assert network._split_authors("Roe & Li (2019)") == []


def test_name_heuristic_is_strict():
    text = (
        "We talked about working memory and the working memory model.\n"
        "Working Memory Load matters. Met Ada Placeholder at the Monday Lab Meeting.\n"
        "Read The Selfish Gene, then read the Blind Watchmaker and A Brief Lull.\n"
        "Visited New York with Bram Sample. Lunch with Ann Lee Bo Li Cy Wu Ev Xu Ed Yi.\n"
        "Notes From Jo Q. Coauthor's talk. Look into Cal Reed next."
    )
    corpus = network._corpus([text])
    assert dict(network._mentioned(text, corpus, set(), False)) == {
        "Ada Placeholder": "know_of",
        "Bram Sample": "know_of",
        "Jo Q Coauthor": "know_of",
        "Cal Reed": "to_read",
    }
    # A name already known from elsewhere is found even when its words are common ones.
    corpus = network._corpus(["a rose by the hill", "the rose garden on the hill"])
    known = {network.normalize("Rose Hill")}
    assert network._mentioned("Met Rose Hill.", corpus, known, False) == [("Rose Hill", "know_of")]
    assert network._mentioned("Met Rose Hill.", corpus, set(), False) == []


def test_people_index(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "ask", no_model)

    stats = network.build(vault, people_only=True, now=NOW)

    data, people = people_by_name(vault)
    assert data["generated"] == GENERATED
    assert set(people) == {
        "Ada Placeholder",
        "Bram Sample",
        "Cleo Example",
        "Esme Mockley",
        "Finn Stub",
        "Gus Testcase",
        "Hana Dummy",
        "Ivo Mock",
        "Jo Coauthor",
        "Kai Citer",
        "Lu Reader",
        "Quinn Doe",
        "Rhea Inkwell",
        "Theo Margin",
        "Uma Quill",
        "Wren Archer",
        "Xan Coder",
        "Yara Helper",
    }
    relations = {name: p["relation"] for name, p in people.items()}
    assert {n for n, r in relations.items() if r == "met"} == {
        "Ada Placeholder",
        "Bram Sample",
        "Cleo Example",
        "Esme Mockley",
        "Finn Stub",
        "Gus Testcase",
        "Hana Dummy",
        "Ivo Mock",
    }
    assert {n for n, r in relations.items() if r == "to_read"} == {
        "Lu Reader",
        "Rhea Inkwell",
        "Uma Quill",
    }
    assert stats == {
        "people": 18,
        "met": 8,
        "know_of": 7,
        "to_read": 3,
        "edges": 2,
        "groups": 2,
        "clusters": 0,  # pairs only, and a pair is a tie, not a cluster
    }
    # Two contexts of two people each: a paper Ada and Jo wrote (Tess is left out), and the
    # group Bram and Cleo wrote in. Each adds 1/log2(3); the busier pair comes first.
    assert [(e["weight"], e["shared"], e["contexts"]) for e in data["edges"]] == [
        (0.6309, 1, ["Paper: Spirals in the brain"]),
        (0.6309, 1, ["WhatsApp: Spiral Club"]),
    ]
    assert {network.person_id("Ada Placeholder"), network.person_id("Jo Coauthor")} == {
        data["edges"][0]["source"],
        data["edges"][0]["target"],
    }
    assert [(g["kind"], g["name"], g["size"]) for g in data["groups"]] == [
        ("whatsapp_group", "Spiral Club", 2),
        ("paper", "Spirals in the brain", 2),
    ]
    # Cleo only wrote on a day the user didn't, but a group of two is people they've met.
    cleo = people["Cleo Example"]
    assert (cleo["interactions"], cleo["sources"], cleo["context"]) == (
        0,
        ["whatsapp"],
        "WhatsApp (Spiral Club)",
    )
    assert data["clusters"] == []
    assert all(p["cluster"] is None for p in data["people"])  # everyone here is in core
    assert all(re.fullmatch(r"k:[0-9a-f]{16}", p["ref"]) for p in data["people"])

    ada = people["Ada Placeholder"]
    assert ada["id"] == network.person_id("Ada Placeholder")
    assert set(ada["sources"]) == {"whatsapp", "email", "mentions/works", "notes/pages"}
    assert ada["sources"][0] == "whatsapp"  # most interactions first
    # 3 WhatsApp messages, 2 emails, a co-authored paper and a note.
    assert ada["interactions"] == 7
    assert ada["first_seen"] == "2025-05-01T00:00:00Z"
    assert ada["last_seen"] == "2026-02-20T09:00:00Z"
    assert ada["org"] == "example.edu"
    assert ada["context"].startswith("WhatsApp (direct chat, 3 messages); email (2 messages)")
    assert "Spiral data" in ada["topics"]

    bram = people["Bram Sample"]
    assert (bram["interactions"], bram["sources"], bram["topics"]) == (
        2,
        ["whatsapp"],
        ["Spiral Club"],
    )
    assert "Spiral Club" in bram["context"]
    assert people["Finn Stub"]["topics"] == ["#methods"]
    assert people["Esme Mockley"]["interactions"] == 2
    gus = people["Gus Testcase"]
    assert (gus["interactions"], gus["org"], gus["topics"]) == (2, "example.org", ["Poster draft"])
    hana = people["Hana Dummy"]
    assert set(hana["sources"]) == {"linkedin/messages", "linkedin/connections"}
    ivo = people["Ivo Mock"]
    assert (ivo["interactions"], ivo["org"]) == (0, "Acme Labs")
    assert ivo["context"] == "LinkedIn connection (since 2025-06, Scientist at Acme Labs)"

    assert people["Jo Coauthor"]["sources"] == ["mentions/works"]
    assert people["Kai Citer"]["sources"] == ["mentions/citations"]
    assert people["Lu Reader"]["sources"] == ["notes/readings"]
    assert people["Quinn Doe"]["topics"] == ["spiral coding"]
    assert people["Rhea Inkwell"]["sources"] == ["notes/pages"]
    assert people["Uma Quill"]["sources"] == ["notes/tasks"]
    assert people["Wren Archer"]["relation"] == "know_of"  # a done reading task
    assert people["Xan Coder"]["sources"] == ["website"]

    # Sorted by relation, then by interactions.
    order = [p["relation"] for p in data["people"]]
    assert order == sorted(order, key=network.RELATIONS.index)
    assert data["people"][0]["name"] == "Ada Placeholder"


def test_index_never_holds_numbers_or_addresses(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch)
    write_jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa(1, "g9", "2026-03-01T08:00:00Z", None, "Call +44 20 7946 0000 now", "group"),
            wa(2, "g9", "2026-03-01T09:00:00Z", "Zed Number", "Call +44 20 7946 0000 now", "group"),
        ],
    )
    network.build(vault, people_only=True, now=NOW)
    _, people = people_by_name(vault)
    for p in people.values():
        text = " ".join([p["name"], p["context"], p["org"] or "", *p["topics"]])
        assert "@" not in text
        assert not re.search(r"555|7946|0000", text), text  # the numbers, but dates stay
    assert people["Zed Number"]["topics"] == ["Call now"]
    assert people["Ada Placeholder"]["org"] == "example.edu"  # a domain is fine


def test_notes_are_optional(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch, notes=False)
    stats = network.build(vault, people_only=True, now=NOW)
    _, people = people_by_name(vault)
    assert not any(s.startswith("notes/") for p in people.values() for s in p["sources"])
    assert stats["to_read"] == 0
    assert network._notes_text(vault) == ""


def test_run_people_only_from_the_command_line(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "ask", no_model)
    parser = argparse.ArgumentParser()
    network.add_arguments(parser)
    stats = network.run(vault, parser.parse_args(["--people-only"]))
    assert stats["people"] == 18
    assert not (vault / "clones" / "network" / "ideas.json").exists()


def test_without_a_self_model_it_stops(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch)
    write(vault / "self" / "CHANGELOG.md", "## history only")
    monkeypatch.setattr(llm, "ask", no_model)
    with pytest.raises(SystemExit, match="proxenos master"):
        network.build(vault, now=NOW)


def test_top_people_keeps_room_for_each_relation():
    def person(n, relation, interactions):
        return {
            "id": f"{relation}{n}",
            "relation": relation,
            "interactions": interactions,
            "last_seen": "2026-03-01T00:00:00Z",
        }

    people = [person(n, "met", 100) for n in range(10)]
    people += [person(n, "know_of", 1) for n in range(5)]
    people += [person(n, "to_read", 1) for n in range(1)]
    shown = network.top_people(people, NOW, limit=8)
    assert len(shown) == 8
    assert sum(p["relation"] == "met" for p in shown) == 8  # quotas past the limit don't apply

    old = {**person(99, "met", 1000), "last_seen": "2016-03-01T00:00:00Z"}
    ranked = network.top_people([old, person(1, "met", 3)], NOW)
    assert [p["id"] for p in ranked] == ["met1", "met99"]  # ten years ago weighs little


def test_ideas(tmp_path, monkeypatch):
    vault = make_vault(tmp_path, monkeypatch)
    write(vault / "self" / "identity.md", "Studies spiral codes in visual cortex.")
    write(vault / "self" / "CHANGELOG.md", "NOT THE MODEL")
    out = vault / "clones" / "network"
    hana = network.person_id("Hana Dummy")
    ada = network.person_id("Ada Placeholder")
    bram = network.person_id("Bram Sample")
    rejected, finished = network.idea_id("Old rejected idea"), network.idea_id("Finished thing")
    old_ask, blocked_read = network.idea_id("Old ask"), network.idea_id("Blocked Author")
    pending = network.idea_id("Pending Person")
    write(
        out / "ideas.json",
        json.dumps(
            {
                "generated": "2026-03-01T12:00:00Z",
                "projects": [
                    {"id": rejected, "title": "Old rejected idea"},
                    {"id": finished, "title": "Finished thing"},
                ],
                "outreach": [
                    {"id": old_ask, "person_id": hana, "name": "Hana Dummy", "ask": "Old ask"}
                ],
                "to_read": [
                    {"id": blocked_read, "name": "Blocked Author", "why": "."},
                    {"id": pending, "name": "Pending Person", "why": "."},
                ],
            }
        ),
    )
    write(
        out / "feedback.jsonl",
        "\n".join(
            [
                json.dumps({"item_id": rejected, "action": "useful", "ts": "2026-03-02T00:00:00Z"}),
                json.dumps({"item_id": rejected, "action": "not_me", "ts": "2026-03-03T00:00:00Z"}),
                json.dumps({"item_id": finished, "action": "done", "ts": "2026-03-03T00:00:00Z"}),
                json.dumps({"item_id": old_ask, "action": "not_me", "ts": "2026-03-03T00:00:00Z"}),
                json.dumps(
                    {"item_id": blocked_read, "action": "not_me", "ts": "2026-03-03T00:00:00Z"}
                ),
                "not json",
                json.dumps({"item_id": pending, "action": "shrug", "ts": "2026-03-03T00:00:00Z"}),
            ]
        ),
    )
    answer = {
        "projects": [
            {
                "title": "Spiral atlas",
                "pitch": "Map them. ",
                "why_you": "Has the data.",
                "people": [ada, "nobody00000", ada],
                "first_step": "Email Ada.",
            },
            {
                "title": "SPIRAL ATLAS!",
                "pitch": "Again.",
                "why_you": ".",
                "people": [],
                "first_step": ".",
            },
            {
                "title": "old rejected IDEA",
                "pitch": ".",
                "why_you": ".",
                "people": [],
                "first_step": ".",
            },
            {
                "title": "Finished thing",
                "pitch": ".",
                "why_you": ".",
                "people": [],
                "first_step": ".",
            },
        ],
        "outreach": [
            {
                "person_id": ada,
                "name": "Ada Placeholder",
                "why": "Co-author.",
                "ask": "Share the spiral data?",
                "channel": "email",
            },
            {
                "person_id": ada,
                "name": "Ada Placeholder",
                "why": ".",
                "ask": "A second ask",
                "channel": "email",
            },
            {
                "person_id": "",
                "name": "bram  sample",
                "why": "Group.",
                "ask": "Coffee next week?",
                "channel": "whatsapp",
            },
            {
                "person_id": hana,
                "name": "Hana Dummy",
                "why": ".",
                "ask": "A new ask",
                "channel": "linkedin",
            },
            {
                "person_id": "zzzzzzzzzzzz",
                "name": "Nobody Known",
                "why": ".",
                "ask": "Hi?",
                "channel": "other",
            },
        ],
        "to_read": [
            {"name": "Rhea Inkwell", "why": "On the list."},
            {"name": "Tess Wintest", "why": "Self."},
            {"name": "BLOCKED author", "why": "Again."},
        ],
    }
    calls = []

    def fake_ask(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return answer

    monkeypatch.setattr(llm, "ask", fake_ask)
    stats = network.build(vault, now=NOW)

    assert stats == {
        "people": 18,
        "met": 8,
        "know_of": 7,
        "to_read": 3,
        "edges": 2,
        "groups": 2,
        "clusters": 0,  # pairs only, and a pair is a tie, not a cluster
        "projects": 1,
        "outreach": 2,
        "suggested_reads": 1,
    }
    ((prompt, kwargs),) = calls
    assert kwargs["effort"] == "high"
    assert kwargs["schema"] == network._SCHEMA
    assert "Tess" in kwargs["system"]
    assert "Studies spiral codes" in prompt and "NOT THE MODEL" not in prompt
    assert f"[{ada}] Ada Placeholder (example.edu): WhatsApp (direct chat" in prompt
    notes = prompt.split("# Their notes")[1].split("# Earlier ideas")[0]
    assert "- Grant idea: spirals [empty]" in notes
    assert "- Draft outline [unfinished]" in notes
    assert "- A Paper On Spirals [to read]" in notes
    assert "- Lab notes\n" in notes
    assert "- Sunset photo\n" in notes
    # Open note tasks are intent; done ones and reading-list rows aren't tasks.
    tasks = notes.split("## Open tasks in their notes (2)")[1]
    assert "- Read Uma Quill on spirals\n- Book the poster printer" in tasks
    assert "Read Wren Archer review" not in tasks and "A Paper On Spirals" not in tasks
    done_part = prompt.split("They did these")[1].split("\n\n")[0]
    assert "Finished thing" in done_part
    not_me_part = prompt.split("They marked these not them")[1].split("\n\n")[0]
    assert "Old rejected idea" in not_me_part and "Hana Dummy: Old ask" in not_me_part
    assert "Pending Person" in prompt.split("no reaction yet")[1]

    ideas = json.loads((out / "ideas.json").read_text(encoding="utf-8"))
    assert ideas["generated"] == GENERATED
    assert ideas["projects"] == [
        {
            "id": hashlib.sha1(b"Spiral atlas").hexdigest()[:12],
            "title": "Spiral atlas",
            "pitch": "Map them.",
            "why_you": "Has the data.",
            "people": [ada],
            "first_step": "Email Ada.",
        }
    ]
    assert [(o["person_id"], o["name"], o["ask"]) for o in ideas["outreach"]] == [
        (ada, "Ada Placeholder", "Share the spiral data?"),
        (bram, "Bram Sample", "Coffee next week?"),
    ]
    assert ideas["outreach"][0]["id"] == network.idea_id("Share the spiral data?")
    assert ideas["to_read"] == [
        {"id": network.idea_id("Rhea Inkwell"), "name": "Rhea Inkwell", "why": "On the list."}
    ]

    history = json.loads((out / "history.json").read_text(encoding="utf-8"))
    assert history[rejected] == {
        "kind": "project",
        "text": "Old rejected idea",
        "given": "2026-03-01",
    }
    assert history[old_ask]["person_id"] == hana
    assert history[network.idea_id("Spiral atlas")]["given"] == "2026-03-10"

    # A later run still knows what was rejected, though ideas.json has moved on.
    calls.clear()
    network.build(vault, now=NOW)
    ((prompt, _),) = calls
    assert "Old rejected idea" in prompt.split("They marked these not them")[1]
    ideas = json.loads((out / "ideas.json").read_text(encoding="utf-8"))
    assert [p["title"] for p in ideas["projects"]] == ["Spiral atlas"]
    assert hana not in [o["person_id"] for o in ideas["outreach"]]


# Connections


def connected_vault(tmp_path, monkeypatch):
    """People who share groups: Ann and Ben four ways, Ann with Cy, Eve and Fay, and others
    with a company in common. Names are made up; Tess is the user and in every context."""
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_FULL_NAME", "Tess Wintest")
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    vault = tmp_path / "vault"
    raw = vault / "raw"
    write_jsonl(
        raw / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            # Cy only wrote on a day the user didn't, but wrote in a group they're in.
            wa(1, "g1", "2026-03-01T08:00:00Z", None, "Lab Chat", "group"),
            wa(2, "g1", "2026-03-01T09:00:00Z", "Ann Alpha", "Lab Chat", "group"),
            wa(3, "g1", "2026-03-01T09:30:00Z", "Ben Beta", "Lab Chat", "group"),
            wa(4, "g1", "2026-03-05T09:00:00Z", "Cy Gamma", "Lab Chat", "group"),
            # A group the user never wrote in connects no one, and neither does a direct chat.
            wa(5, "g2", "2026-03-02T09:00:00Z", "Dee Delta", "Quiet Club", "group"),
            wa(6, "g2", "2026-03-02T09:10:00Z", "Ann Alpha", "Quiet Club", "group"),
            wa(7, "c1", "2026-03-02T10:00:00Z", "Ann Alpha", "Ann Alpha"),
            wa(8, "c1", "2026-03-02T10:05:00Z", None, "Ann Alpha"),
            # A group named with a phone number.
            wa(9, "g3", "2026-03-03T08:00:00Z", None, "Call +44 20 7946 0000 now", "group"),
            wa(10, "g3", "2026-03-03T09:00:00Z", "Gus Org", "Call +44 20 7946 0000 now", "group"),
            wa(11, "g3", "2026-03-03T09:05:00Z", "Hal Org", "Call +44 20 7946 0000 now", "group"),
        ],
    )
    write_jsonl(
        raw / "slack" / "acme" / "messages" / "2026-03.jsonl",
        [
            slack(
                1, "C1", "channel", "2026-03-02T10:00:00Z", "U1", "Tess Wintest", True, "methods"
            ),
            slack(2, "C1", "channel", "2026-03-02T10:05:00Z", "U2", "Ann Alpha", False, "methods"),
            slack(3, "C1", "channel", "2026-03-02T10:06:00Z", "U3", "Ben Beta", False, "methods"),
            slack(4, "C1", "channel", "2026-03-02T10:07:00Z", "B9", "Build Bot", False, "methods"),
            slack(5, "D1", "dm", "2026-03-02T11:00:00Z", "U2", "Ann Alpha", False, "Ann Alpha"),
            slack(6, "D1", "dm", "2026-03-02T11:01:00Z", "U1", "Tess Wintest", True, "Ann Alpha"),
        ],
    )
    ann, ben, eve = "ann@acme.test", "ben@acme.test", "eve@other.test"
    many = [f"r{i}@example.com" for i in range(16)]
    write_jsonl(
        raw / "email" / "personal" / "2026-03.jsonl",
        [
            # One thread by its replies: Ann, Ben and Eve.
            mail(1, "2026-03-04T09:00:00Z", ME, [ann, ben, eve], "Tess Wintest", "Plan"),
            mail(2, "2026-03-04T10:00:00Z", ann, [ME, ben, eve], "Ann Alpha", "Re: Plan", "m1"),
            mail(3, "2026-03-04T11:00:00Z", ben, [ME, ann, eve], "Ben Beta", "Re: Plan", "m2"),
            mail(4, "2026-03-04T12:00:00Z", eve, [ME], "Eve Epsilon", "Re: Plan", "m1"),
            # One by Gmail's thread id, with no reply header.
            mail(5, "2026-03-05T09:00:00Z", ME, [ann, eve], "Tess Wintest", "Grant")
            | {"gmail_thread": "T9"},
            mail(6, "2026-03-05T10:00:00Z", eve, [ME, ann], "Eve Epsilon", "Re: Grant")
            | {"gmail_thread": "T9"},
            # Mail to eighteen people is no context.
            mail(7, "2026-03-06T09:00:00Z", ME, [*many, ann, ben], "Tess Wintest", "Everyone"),
        ],
    )
    connection = {"from_me": False, "position": None}
    people = [("Cy Gamma", "Solo Co"), ("Dee Delta", None)]
    people += [("Gus Org", "Small Labs Inc"), ("Hal Org", "Small Labs")]
    people += [("Ina Org", "Small Labs"), ("Jon Free", "Self-employed")]
    people += [("Kit Free", "Self-employed")]
    # An organization too big to say who knows whom.
    people += [(f"Worker {chr(65 + i // 26)}{chr(97 + i % 26)}", "Big Corp") for i in range(41)]
    write_jsonl(
        raw / "linkedin" / "connections" / "2025-06.jsonl",
        [
            connection | {"id": f"k{i}", "ts": "2025-06-01T00:00:00Z", "name": n, "company": c}
            for i, (n, c) in enumerate(people)
        ],
    )
    write_jsonl(
        raw / "mentions" / "works" / "2025-05.jsonl",
        [
            {
                "id": "W1",
                "ts": "2025-05-01T00:00:00Z",
                "title": "Spirals in the brain",
                "coauthors": ["Ann Alpha", "Fay Zeta"],
            }
        ],
    )
    write_jsonl(
        raw / "mentions" / "citations" / "2025-09.jsonl",
        [
            {
                "id": "W2",
                "ts": "2025-09-01T00:00:00Z",
                "title": "More on spirals",
                "authors": ["Ann Alpha", "Fay Zeta", "T. Wintest"],
            }
        ],
    )
    return vault


def connections_of(vault):
    data = json.loads((vault / "clones" / "network" / "people.json").read_text(encoding="utf-8"))
    name = {p["id"]: p["name"] for p in data["people"]}
    edges = {
        frozenset((name[e["source"]], name[e["target"]])): (e["weight"], e["contexts"])
        for e in data["edges"]
    }
    return data, name, edges


def pair(a, b):
    return frozenset((a, b))


def test_edges_connect_people_who_share_a_context(tmp_path, monkeypatch):
    vault = connected_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "ask", no_model)

    stats = network.build(vault, people_only=True, now=NOW)

    data, _, edges = connections_of(vault)
    assert (stats["edges"], stats["groups"]) == (len(data["edges"]), len(data["groups"]))
    # A group of two adds 1/log2(3) = 0.6309 to a tie, a group of three 1/log2(4) = 0.5.
    assert edges == {
        # Slack and the domain they both write from (two people each), then WhatsApp and the
        # thread (three each): the closest contexts are named first.
        pair("Ann Alpha", "Ben Beta"): (
            2.2619,
            ["Slack: acme #methods", "Org: acme.test", "WhatsApp: Lab Chat", "Email: Plan"],
        ),
        pair("Ann Alpha", "Cy Gamma"): (0.5, ["WhatsApp: Lab Chat"]),
        pair("Ben Beta", "Cy Gamma"): (0.5, ["WhatsApp: Lab Chat"]),
        pair("Ann Alpha", "Eve Epsilon"): (1.1309, ["Email: Grant", "Email: Plan"]),
        pair("Ben Beta", "Eve Epsilon"): (0.5, ["Email: Plan"]),
        # Two papers, one of them with the user on it: they don't count towards its size.
        pair("Ann Alpha", "Fay Zeta"): (
            1.2619,
            ["Paper: More on spirals", "Paper: Spirals in the brain"],
        ),
        pair("Gus Org", "Hal Org"): (1.1309, ["WhatsApp: Call now", "Org: Small Labs"]),
        pair("Gus Org", "Ina Org"): (0.5, ["Org: Small Labs"]),
        pair("Hal Org", "Ina Org"): (0.5, ["Org: Small Labs"]),
    }
    for edge in data["edges"]:
        assert set(edge) == {"source", "target", "weight", "shared", "contexts"}
        assert edge["source"] < edge["target"]
        assert edge["shared"] >= len(edge["contexts"])
    weights = [e["weight"] for e in data["edges"]]
    assert weights == sorted(weights, reverse=True)  # strongest first
    # Nothing connects the user, a group never written in, a direct chat, or a company with no name.
    me = network.person_id("Tess Wintest")
    assert me not in {i for e in data["edges"] for i in (e["source"], e["target"])}
    assert not any("Quiet Club" in c or "Self" in c for _, cs in edges.values() for c in cs)
    assert pair("Ann Alpha", "Dee Delta") not in edges
    assert pair("Jon Free", "Kit Free") not in edges


def test_groups_list_who_shares_each_context(tmp_path, monkeypatch):
    vault = connected_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "ask", no_model)
    network.build(vault, people_only=True, now=NOW)

    data, name, _ = connections_of(vault)
    groups = {
        (g["kind"], g["name"]): (sorted(name[i] for i in g["members"]), g["size"])
        for g in data["groups"]
    }
    assert groups == {
        ("whatsapp_group", "Lab Chat"): (["Ann Alpha", "Ben Beta", "Cy Gamma"], 3),  # Cy too
        ("whatsapp_group", "Call now"): (["Gus Org", "Hal Org"], 2),  # no number in a name
        ("slack_channel", "acme #methods"): (["Ann Alpha", "Ben Beta"], 2),
        ("paper", "More on spirals"): (["Ann Alpha", "Fay Zeta"], 2),  # T. Wintest is the user
        ("paper", "Spirals in the brain"): (["Ann Alpha", "Fay Zeta"], 2),
        ("email_thread", "Plan"): (["Ann Alpha", "Ben Beta", "Eve Epsilon"], 3),
        ("email_thread", "Grant"): (["Ann Alpha", "Eve Epsilon"], 2),
        ("org", "acme.test"): (["Ann Alpha", "Ben Beta"], 2),
        ("org", "Small Labs"): (["Gus Org", "Hal Org", "Ina Org"], 3),
    }
    kinds = [g["kind"] for g in data["groups"]]
    assert kinds == sorted(kinds, key=network.GROUP_KINDS.index)
    for g in data["groups"]:
        assert set(g) == {"id", "name", "kind", "members", "size"}
        assert re.fullmatch(r"[0-9a-f]{12}", g["id"])
        assert len(g["members"]) >= 2
    assert len({g["id"] for g in data["groups"]}) == len(data["groups"])
    text = json.dumps(data["groups"]) + json.dumps(data["edges"])
    assert not re.search(r"@|7946|0000", text)


def test_mail_to_many_people_is_no_context(tmp_path, monkeypatch):
    vault = connected_vault(tmp_path, monkeypatch)
    network.build(vault, people_only=True, now=NOW)
    data, _, _ = connections_of(vault)
    assert "Everyone" not in {g["name"] for g in data["groups"]}

    # Fifteen others is the most: one fewer and the same mail is a thread.
    path = vault / "raw" / "email" / "personal" / "2026-03.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[-1]["to"] = [f"r{i}@example.com" for i in range(13)] + [
        "ann@acme.test",
        "ben@acme.test",
    ]
    write_jsonl(path, records)
    network.build(vault, people_only=True, now=NOW)
    data, name, _ = connections_of(vault)
    (everyone,) = (g for g in data["groups"] if g["name"] == "Everyone")
    assert sorted(name[i] for i in everyone["members"]) == ["Ann Alpha", "Ben Beta"]


def test_only_the_top_people_are_connected(tmp_path, monkeypatch):
    vault = connected_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(network, "GRAPH_PEOPLE", 4)
    network.build(vault, people_only=True, now=NOW)

    data, _, edges = connections_of(vault)
    core = data["core"]
    assert len(core) == len(set(core)) == 4
    assert core == [p["id"] for p in network.top_people(data["people"], NOW, 4)]
    assert len(data["people"]) > 50  # the list keeps everyone
    assert edges
    for edge in data["edges"]:
        assert {edge["source"], edge["target"]} <= set(core)
    for group in data["groups"]:
        assert set(group["members"]) <= set(core)
        assert len(group["members"]) >= 2


def test_strongest_edges_are_kept(tmp_path, monkeypatch):
    vault = connected_vault(tmp_path, monkeypatch)
    monkeypatch.setattr(network, "GRAPH_EDGES", 3)
    stats = network.build(vault, people_only=True, now=NOW)

    _, _, edges = connections_of(vault)
    assert stats["edges"] == 3
    # The most contexts first. Of the pairs with two, Ann and Fay share two papers of two
    # people, closer than Ann and Eve's thread of three and thread of two.
    assert set(edges) == {
        pair("Ann Alpha", "Ben Beta"),
        pair("Ann Alpha", "Fay Zeta"),
        pair("Ann Alpha", "Eve Epsilon"),
    }


def ranked_people(n):
    """n people as the index lists them, the first the most active."""
    return [
        {"id": f"p{i:02}", "relation": "met", "interactions": 100 - i, "last_seen": None}
        for i in range(n)
    ]


def test_small_groups_beat_big_ones_at_the_same_weight():
    people = ranked_people(12)
    crowd = {
        "id": "big",
        "name": "Crowd",
        "kind": "slack_channel",
        "members": {p["id"] for p in people[:10]},
    }
    pair_ = {"id": "duo", "name": "Duo", "kind": "paper", "members": {"p10", "p11"}}

    edges, groups = network.connections([crowd, pair_], people, NOW)

    # The pair adds 1/log2(3), each pair in the crowd of ten 1/log2(11).
    assert (edges[0]["source"], edges[0]["target"], edges[0]["weight"]) == ("p10", "p11", 0.6309)
    assert edges[1]["weight"] == 0.2891
    assert len(edges) == 1 + 45
    assert [g["name"] for g in groups] == ["Crowd", "Duo"]  # by kind, as the page lists them
    assert sum(len(g["members"]) for g in groups) == 12
    # A group with one person in the top is no group.
    edges, groups = network.connections([crowd, pair_], people[:1] + people[10:11], NOW)
    assert (edges, groups) == ([], [])


def test_a_big_group_stays_big_when_few_of_it_are_connected():
    people = ranked_people(12)
    crowd = {
        "id": "big",
        "name": "Crowd",
        "kind": "slack_channel",
        "members": {p["id"] for p in people[:10]},
    }
    pair_ = {"id": "duo", "name": "Duo", "kind": "paper", "members": {"p10", "p11"}}
    # Only two of the crowd are among the top, and they're the most active pair. The crowd is
    # still a channel of ten, so the two who wrote a paper together are closer.
    core = people[:2] + people[10:]
    edges, groups = network.connections([crowd, pair_], core, NOW)
    assert [(e["source"], e["target"]) for e in edges] == [("p10", "p11"), ("p00", "p01")]
    assert [len(g["members"]) for g in groups] == [2, 2]  # listed with who's in the top


def test_papers_with_no_id_or_title_are_no_group(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess Wintest")
    vault = tmp_path / "vault"
    write_jsonl(
        vault / "raw" / "mentions" / "works" / "2025-05.jsonl",
        [
            {"id": None, "ts": "2025-05-01T00:00:00Z", "title": None, "coauthors": authors}
            for authors in (["Ann Alpha", "Ben Beta"], ["Cy Gamma", "Dee Delta"])
        ],
    )
    network.build(vault, people_only=True, now=NOW)
    data, _, edges = connections_of(vault)
    assert len(data["people"]) == 4
    assert (data["groups"], edges) == ([], {})


# Who is who, and every member of a group


def member(jid, name=None, push=None, alt=None, active=True):
    return {"jid": jid, "alt_jid": alt, "name": name, "push_name": push, "active": active}


def roster(chat, name, members):
    return {"id": chat, "chat_id": chat, "chat_name": name, "members": members}


def channel(cid, name, members, joined=True):
    return {
        "id": cid,
        "channel_id": cid,
        "channel_name": name,
        "channel_type": "channel",
        "joined": joined,
        "members": [
            {"id": uid, "name": n, "email": email, "me": uid == "U0"} for uid, n, email in members
        ],
    }


def identity_vault(tmp_path, monkeypatch, cohort_extra=()):
    """A lab group on WhatsApp where Tori goes by her first name, a cohort channel on Slack
    where she has her full name, and a flatmate saved as "Raj Flatmate" on one jid who writes as
    Raj Tester on the other and by email. All made up; Tess is the user."""
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_FULL_NAME", "Tess Wintest")
    monkeypatch.setenv("PROXENOS_EMAILS", ME)
    vault = tmp_path / "vault"
    raw = vault / "raw"
    me = [member("900@lid", push="Tess Wintest", alt="900@s.whatsapp.net")]
    me.append(member("900@s.whatsapp.net", name="Tess US", active=False))
    write_jsonl(
        raw / "whatsapp" / "groups" / "snapshot.jsonl",
        [
            roster(
                "g1@g.us",
                "Spiral Lab",
                me
                + [
                    member("100@lid", name="Tori", push="Tori"),
                    member("101@lid", push="Mo Ample"),
                    member("102@lid", push="Nia Quiet"),  # never wrote
                    member("103@lid", push="Oz Kettle"),
                ],
            ),
            roster(
                "g2@g.us",
                "Flat 4B",
                me
                + [
                    member(
                        "200@lid", name="Raj Flatmate", push="Raj Tester", alt="200@s.whatsapp.net"
                    )
                ],
            ),
        ],
    )
    write_jsonl(
        raw / "whatsapp" / "messages" / "2026-03.jsonl",
        [wa(n, "100@lid", f"2026-03-0{n}T10:00:00Z", "Tori", "Tori") for n in range(1, 6)]
        + [wa(6, "100@lid", "2026-03-06T10:00:00Z", None, "Tori")]
        + [
            wa(n, "200@s.whatsapp.net", f"2026-03-0{n}T11:00:00Z", "Raj Flatmate", "Raj Flatmate")
            for n in range(1, 4)
        ]
        + [wa(4, "200@s.whatsapp.net", "2026-03-04T12:00:00Z", None, "Raj Flatmate")],
    )
    cohort = [("U0", "Tess Wintest", ME), ("U1", "Tori Vantor", "tori@cohort.test")]
    cohort += [("U2", "Mo Ample", None), ("U3", "Pia Far", None), *cohort_extra]
    write_jsonl(
        raw / "slack" / "summer" / "channels" / "snapshot.jsonl",
        [
            channel("C1", "cohort", cohort),
            channel(
                "C2", "random", [("U1", "Tori Vantor", None), ("U4", "Quin Away", None)], False
            ),
        ],
    )
    write_jsonl(
        raw / "slack" / "summer" / "messages" / "2026-03.jsonl",
        [slack(1, "C1", "channel", "2026-03-02T10:00:00Z", "U3", "Pia Far", channel_name="cohort")],
    )
    write_jsonl(
        raw / "email" / "personal" / "2026-03.jsonl",
        [
            mail(1, "2026-03-03T09:00:00Z", "raj@uni.test", [ME], "Raj Tester", "Rent"),
            mail(2, "2026-03-03T10:00:00Z", ME, ["raj@uni.test"], "Tess Wintest", "Re: Rent", "m1"),
            # Tori writes from the address on her Slack profile, as initial and surname.
            mail(3, "2026-03-04T09:00:00Z", "tori@cohort.test", [ME], "T. Vantor", "Notes"),
            mail(
                4,
                "2026-03-04T10:00:00Z",
                ME,
                ["tori@cohort.test"],
                "Tess Wintest",
                "Re: Notes",
                "m3",
            ),
        ],
    )
    write_jsonl(
        raw / "linkedin" / "connections" / "2025-06.jsonl",
        [
            {
                "id": "k1",
                "ts": "2025-06-01T00:00:00Z",
                "name": "Tori Other",
                "company": "Elsewhere",
            },
            {"id": "k2", "ts": "2025-06-01T00:00:00Z", "name": "Pia Far", "company": None},
        ],
    )
    return vault


def built(vault, now=NOW):
    network.build(vault, people_only=True, now=now)
    return people_by_name(vault)


def test_one_person_across_jids_sources_and_a_first_name(tmp_path, monkeypatch):
    data, people = built(identity_vault(tmp_path, monkeypatch))
    names = set(people)
    # "Tori" on WhatsApp is the cohort's Tori Vantor: they share Mo, and no other Tori does.
    # Her Slack profile's address makes her the "T. Vantor" who emails.
    assert "Tori" not in names and "T. Vantor" not in names
    tori = people["Tori Vantor"]
    assert set(tori["sources"]) == {"whatsapp", "email", "slack"}
    assert tori["interactions"] == 6 + 2
    assert sorted(tori["aka"]) == ["T. Vantor", "Tori"]  # names only, never an id
    # The flatmate's two jids are one, and his push name is his email name.
    assert "Raj Flatmate" not in names
    raj = people["Raj Tester"]
    assert set(raj["sources"]) == {"whatsapp", "email"}
    assert raj["interactions"] == 4 + 2
    # A different full name is never merged, whoever shares what.
    assert people["Tori Other"]["sources"] == ["linkedin/connections"]
    # Nothing of the user's: not their push name, not their own contact card.
    assert not names & {"Tess Wintest", "Tess US", "Tess"}
    text = json.dumps(data)
    assert not re.search(r"@|900|200|lid|whatsapp\.net", text.replace("whatsapp_group", ""))


def test_every_member_of_a_group_counts_with_its_size(tmp_path, monkeypatch):
    data, people = built(identity_vault(tmp_path, monkeypatch))
    name = {p["id"]: p["name"] for p in data["people"]}
    groups = {g["name"]: g for g in data["groups"]}
    # Everyone in the lab group, writers or not, and the user doesn't count towards its size.
    lab = groups["Spiral Lab"]
    assert sorted(name[i] for i in lab["members"]) == [
        "Mo Ample",
        "Nia Quiet",
        "Oz Kettle",
        "Tori Vantor",
    ]
    assert (lab["kind"], lab["size"]) == ("whatsapp_group", 4)
    assert groups["summer #cohort"]["size"] == 3
    assert "summer #random" not in groups  # a channel the user isn't in
    # A silent member of a small group is someone the user has met.
    nia = people["Nia Quiet"]
    assert (nia["relation"], nia["interactions"], nia["sources"]) == ("met", 0, ["whatsapp"])
    edges = {frozenset((name[e["source"]], name[e["target"]])): e for e in data["edges"]}
    both = edges[frozenset(("Tori Vantor", "Mo Ample"))]
    # 1/log2(4 + 1) for the lab group and 1/log2(3 + 1) for the channel.
    assert both["weight"] == round(1 / math.log2(5) + 1 / math.log2(4), 4) == 0.9307
    assert both["shared"] == 2
    assert both["contexts"] == ["Slack: summer #cohort", "WhatsApp: Spiral Lab"]
    assert edges[frozenset(("Nia Quiet", "Oz Kettle"))]["weight"] == 0.4307


def test_a_first_name_two_people_could_have_stays_apart(tmp_path, monkeypatch):
    vault = identity_vault(tmp_path, monkeypatch, [("U5", "Tori Second", None)])
    _, people = built(vault)
    assert {"Tori", "Tori Vantor", "Tori Second"} <= set(people)
    assert people["Tori"]["sources"] == ["whatsapp"]


def test_a_nickname_finds_the_full_name_it_stands_for(tmp_path, monkeypatch):
    vault = identity_vault(tmp_path, monkeypatch, [("U6", "Alexandra Pole", None)])
    path = vault / "raw" / "whatsapp" / "groups" / "snapshot.jsonl"
    groups = [json.loads(line) for line in path.read_text().splitlines()]
    groups[0]["members"].append(member("104@lid", name="Sasha"))
    write_jsonl(path, groups)
    _, people = built(vault)
    assert "Sasha" not in people
    assert set(people["Alexandra Pole"]["sources"]) == {"slack", "whatsapp"}
    assert "Tori Vantor" in people  # her own first name still wins over the nickname


def test_corrections_come_first(tmp_path, monkeypatch):
    vault = identity_vault(tmp_path, monkeypatch)
    data, people = built(vault)
    aliases = vault / "clones" / "network" / "aliases.json"
    oz, pia = people["Oz Kettle"], people["Pia Far"]
    write(
        aliases,
        json.dumps(
            {
                "different": [["Tori", "Tori Vantor"]],
                "same": [[oz["ref"], pia["id"]]],  # a ref and an id from the last build
                "hide": ["Nia Quiet", people["Tori Other"]["id"], 42],
            }
        ),
    )
    data, people = built(vault)
    assert people["Tori"]["sources"] == ["whatsapp"]  # kept apart from Tori Vantor
    assert "Tori" not in people["Tori Vantor"]["context"]
    merged = people["Oz Kettle"] if "Oz Kettle" in people else people["Pia Far"]
    assert {"Oz Kettle", "Pia Far"} - set(people) and set(merged["sources"]) >= {
        "whatsapp",
        "slack",
    }
    assert not {"Nia Quiet", "Tori Other"} & set(people)
    ids = {p["id"] for p in data["people"]}
    assert all(set(g["members"]) <= ids for g in data["groups"])

    # A broken file is no correction at all.
    write(aliases, "{not json")
    _, people = built(vault)
    assert "Tori" not in people and "Nia Quiet" in people


def test_meetings_are_groups_of_who_came(tmp_path, monkeypatch):
    vault = identity_vault(tmp_path, monkeypatch)

    def event(uid, ts, guests, summary, organizer=ME):
        return {
            "id": uid,
            "ts": ts,
            "summary": summary,
            "status": "CONFIRMED",
            "organizer": organizer,
            "guests": [{"name": n, "email": e, "status": s} for n, e, s in guests],
        }

    me = ("Tess Wintest", ME, "accepted")
    gil, hal = ("Gil Meet", "gil@x.test", "accepted"), ("Hal Meet", "hal@x.test", None)
    crowd = [(f"Crowd {chr(65 + i)}", f"c{i}@x.test", "accepted") for i in range(16)]
    write_jsonl(
        vault / "raw" / "calendar" / "work" / "2026-02.jsonl",
        [
            event(
                "e1",
                "2026-02-02T15:00:00Z",
                [me, gil, hal, ("Ivy No", "ivy@x.test", "declined")],
                "Kickoff",
            ),
            # A moved instance of it is the same meeting.
            event("e1/2026-02-09T15:00:00Z", "2026-02-10T15:00:00Z", [me, gil, hal], "Kickoff"),
            event("e2", "2026-02-03T15:00:00Z", [me, *crowd], "All hands"),  # too big
            event("e3", "2026-02-04T15:00:00Z", [gil, hal], "Not mine", "gil@x.test"),
            event(
                "e4", "2026-04-01T15:00:00Z", [me, gil, ("Jo Later", "jo@x.test", None)], "Later"
            ),
        ],
    )
    # A calendar named after an address the user never sends mail from: that address is theirs.
    write_jsonl(
        vault / "raw" / "calendar" / "tess-lab-test" / "2026-02.jsonl",
        [
            event(
                "e5",
                "2026-02-05T15:00:00Z",
                [(None, "tess@lab.test", "accepted"), gil, ("Kim Lab", "kim@lab.test", None)],
                "Lab sync",
                "kim@lab.test",
            )
        ],
    )
    data, people = built(vault)
    events = {g["name"]: g for g in data["groups"] if g["kind"] == "event"}
    assert {name: g["size"] for name, g in events.items()} == {"Kickoff": 2, "Lab sync": 2}
    gil_ = people["Gil Meet"]
    assert (gil_["relation"], gil_["sources"], gil_["interactions"]) == ("met", ["calendar"], 3)
    assert "Lab sync" in gil_["context"] and gil_["context"].endswith("3 events)")
    assert people["Kim Lab"]["sources"] == ["calendar"]
    assert not {"Ivy No", "Jo Later", "Crowd A"} & set(people)


def test_clusters_split_the_lab_from_the_flat(tmp_path, monkeypatch):
    vault = identity_vault(tmp_path, monkeypatch)
    path = vault / "raw" / "whatsapp" / "groups" / "snapshot.jsonl"
    groups = [json.loads(line) for line in path.read_text().splitlines()]
    groups[1]["members"] += [member("201@lid", push="Una Flat"), member("202@lid", push="Vic Flat")]
    write_jsonl(path, groups)
    data, people = built(vault)
    clusters = {c["id"]: c for c in data["clusters"]}
    assert [c["id"] for c in data["clusters"]] == list(range(1, len(clusters) + 1))
    lab = people["Tori Vantor"]["cluster"]
    assert people["Mo Ample"]["cluster"] == people["Oz Kettle"]["cluster"] == lab
    flat = people["Raj Tester"]["cluster"]
    assert people["Una Flat"]["cluster"] == flat != lab
    assert clusters[flat]["label"] == "Flat 4B"
    assert clusters[lab]["label"] in {"Spiral Lab", "summer #cohort"}
    assert sum(c["size"] for c in clusters.values()) == sum(
        p.get("cluster") is not None for p in data["people"]
    )
    assert "cluster" not in people["Tori Other"] or people["Tori Other"]["cluster"] is None


def test_louvain_finds_two_cliques_joined_by_one_tie():
    a = [f"a{i}" for i in range(4)]
    b = [f"b{i}" for i in range(4)]
    weight = {(x, y): 1.0 for group in (a, b) for x, y in itertools.combinations(group, 2)}
    weight["a0", "b0"] = 0.1
    found = network._louvain(sorted(a + b + ["loner"]), weight)
    assert len({found[n] for n in a}) == len({found[n] for n in b}) == 1
    assert found["a1"] != found["b1"]
    assert found["loner"] == "loner"
