"""`proxenos demo`: a made-up vault every view can show, with no model and nothing read from this
computer, that nothing is ever sent from."""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from proxenos import cli, demo, memory, outbox, think, webapp
from proxenos.clones import errands, life, work

NOW = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "demo"
    demo.build(v, NOW)
    return v


def read(vault, rel):
    return json.loads((vault / rel).read_text(encoding="utf-8"))


def test_every_view_has_something_current_to_show(vault):
    tasks = read(vault, "clones/tasks/tasks.json")["tasks"]
    assert {t["status"] for t in tasks} == {"open", "waiting", "done"}
    assert any(t["due"] for t in tasks if t["status"] == "open")

    care = read(vault, "clones/care/care.json")
    assert {i["status"] for i in care["open_items"]} == {"open", "waiting", "done"}
    assert care["timeline"] and care["scripts"] and care["visit_brief"].startswith("# Visit brief")
    live = {i["id"] for i in care["open_items"] if i["status"] != "done"}
    assert {s["item_id"] for s in care["scripts"]} <= live
    # Evidence opens real records: each one cited is in the memory index, from when it says.
    cited = care["cited"]
    found = memory.records(cited, vault=vault)
    assert found.keys() == cited.keys()
    assert all(found[i]["ts"] == c["ts"] for i, c in cited.items())

    drafts = list((vault / "clones/drafts").glob("*.md"))
    fronts = [work._front(p.read_text(encoding="utf-8")) for p in drafts]
    assert all(fronts) and len(fronts) >= 6
    assert {f["for"] for f in fronts} >= {"reply", "task", "care", "outreach", "reading"}
    assert {f["id"] for f in fronts} >= {t["id"] for t in tasks if t["title"].startswith("Book")}

    (week,) = (vault / "clones/choices").glob("*.json")
    chosen = json.loads(week.read_text(encoding="utf-8"))
    assert chosen["take_on"] and chosen["skip"]
    assert {i["step"]["kind"] for i in chosen["take_on"]} == {"draft", "errand"}
    # Each choice's evidence opens a real record, and each draft it names was written.
    ids = [e["id"] for i in chosen["take_on"] + chosen["skip"] for e in i["evidence"] if e["id"]]
    assert ids and memory.records(ids, vault=vault).keys() == set(ids)
    named = {i["draft_id"] for i in chosen["take_on"] + chosen["skip"] if i["draft_id"]}
    assert named and named <= {f["id"] for f in fronts if f["for"] == "choice"}

    listed = errands.listed(vault)
    assert {e["status"] for e in listed} == {"ready", "sent"}
    fay = next(e for e in listed if e["person"] == "Fay Moss")
    assert fay["messages"][0]["address"] == "fay.moss@betacorp.example"
    assert fay["steps"][-1]["title"] == "Stopped one tap short"
    assert fay["summary"] == errands.summary(fay)

    (listed_thread,) = think.threads(vault)
    thread = think.show(vault, listed_thread["id"])
    assert listed_thread["turns"] == 2 and thread["status"] == "done"
    # What matters in it opens real records.
    answers = [m for m in thread["messages"] if m["role"] == "proxenos"]
    ids = [x["record"] for m in answers for x in m["parts"]["matters"] if x["record"]]
    assert ids and memory.records(ids, vault=vault).keys() == set(ids)

    events = read(vault, "clones/recall/today.json")["events"]
    assert "Glasses fitting" in [e["title"] for e in events]
    people = read(vault, "clones/network/people.json")["people"]
    assert {"Ben Ode", "Dee Fay", "Gus Hale"} <= {p["name"] for p in people}
    assert "Joe Bloggs" not in {p["name"] for p in people}  # the owner is never one of his people
    assert (vault / "self/identity.md").exists()
    assert (vault / "tracker/items/2026-10.jsonl").exists()


def test_the_life_view_has_months_told_and_their_days(vault):
    stories = life.stories(vault)
    assert list(stories) == ["2026-09", "2026-10"]  # August has one moment: left to write
    for month, story in stories.items():
        assert story["summary"] and 3 <= len(story["highlights"]) <= 5
        days = [e["day"] for e in story["entries"]]
        assert days == sorted(set(days)) and all(d.startswith(month) for d in days)
        assert story["days_with_records"] == len(life.days(vault, month)) > 0
    assert any("Juniper" in e["text"] for e in stories["2026-10"]["entries"])
    assert not any(" you" in f" {e['text']}".lower() for e in stories["2026-10"]["entries"])
    assert life.months(vault, NOW.date())["2026-10"]["days"] > 10  # counted for the page


def test_the_rhythms_view_has_months_of_weeks_to_compare(vault):
    found = read(vault, "clones/rhythms/weeks.json")
    weeks = found["weeks"]
    assert len(weeks) >= 26 and weeks[-1]["start"] == "2026-10-26"
    assert set(found["channels"]) == {"WhatsApp", "Email", "Slack"}
    assert 0.8 < found["coverage"]["share"] < 1  # all but one artist labelled
    assert sum(w["movement"]["rides"]["count"] for w in weeks) >= 10
    assert all(w["listening"]["hours"] > 0 for w in weeks[1:])
    # Summer's rides and energetic listening, then calmer weeks: something to say on each.
    kinds = [line["kind"] for line in found["stands_out"]["1y"]["1w"]]
    assert kinds == ["listening", "riding", "messages", "mood"]
    shift = found["stands_out"]["3m"]["1w"][-1]["text"]
    assert shift.startswith("Your top mood went from energetic")


def test_everything_in_it_is_made_up(vault):
    texts = [
        p.read_text(encoding="utf-8")
        for p in vault.rglob("*")
        if p.is_file() and p.suffix in (".json", ".jsonl", ".md")
    ]
    everything = "\n".join(texts)
    assert str(Path.home()) not in everything
    for address in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", everything):
        if "@s.whatsapp.net" in address or "@g.us" in address:
            assert address.startswith(("1555555", "120363000000000")), address
        else:
            assert address.endswith((".example", "@example.com", "@example.net")), address
    for link in re.findall(r"https?://[^\s\"']+", everything):
        assert link.startswith("https://example.org/"), link


def test_its_settings_are_set_only_while_it_is_built(vault):
    assert not any(key in os.environ for key in demo.PERSON)


def test_nothing_is_sent_from_it(vault):
    assert outbox.is_demo(vault)
    sent = []
    fay = next(e for e in errands.listed(vault) if e["person"] == "Fay Moss")

    with pytest.raises(SystemExit, match="demo"):
        errands.send(vault, fay["id"], 0, {}, NOW, lambda message, cv: sent.append(message))

    assert sent == []
    assert outbox.run(vault, NOW)["outbox_sent"] == 0
    assert read(vault, "clones/outbox/state.json")["routes"] == {}


def test_a_plan_for_later_today_never_falls_at_night():
    def soon(hour, minute=0):
        local = datetime(2026, 6, 10, hour, minute).astimezone()  # this computer's time zone
        return datetime.fromisoformat(demo._Clock(local).soon(3)).astimezone()

    assert soon(13, 10).replace(tzinfo=None) == datetime(2026, 6, 10, 16, 30)
    assert soon(0, 47).replace(tzinfo=None) == datetime(2026, 6, 10, 10, 0)  # built after midnight
    assert soon(19, 0).replace(tzinfo=None) == datetime(2026, 6, 11, 10, 0)  # built in the evening


def test_it_never_lands_on_a_folder_that_isnt_a_demo(tmp_path):
    folder = tmp_path / "vault"
    (folder / "raw").mkdir(parents=True)
    (folder / "raw" / "mine.jsonl").write_text("{}\n")

    with pytest.raises(SystemExit, match="isn't empty"):
        demo.build(folder, NOW)

    assert [p.name for p in folder.rglob("*")] == ["raw", "mine.jsonl"]


def test_an_earlier_demo_is_written_again_from_scratch(vault):
    (vault / "clones" / "stray.json").write_text("{}")
    demo.build(vault, NOW)
    assert not (vault / "clones" / "stray.json").exists()
    assert outbox.is_demo(vault)


def test_the_command_says_how_to_open_the_page_on_it(tmp_path, capsys):
    cli.main(["demo", str(tmp_path / "demo")])

    out = capsys.readouterr().out
    if os.name == "nt":
        assert f'$env:PROXENOS_VAULT="{tmp_path / "demo"}"' in out
    else:
        assert f"PROXENOS_VAULT={tmp_path / 'demo'} " in out
    assert f"proxenos web --port {demo.PORT}" in out
    assert demo.PORT != webapp.PORT


def test_the_page_starts_on_the_port_given(monkeypatch):
    ports = []
    monkeypatch.setattr(webapp, "serve", ports.append)
    cli.main(["web", "--port", "4848"])
    cli.main(["web"])
    assert ports == [4848, webapp.PORT]
