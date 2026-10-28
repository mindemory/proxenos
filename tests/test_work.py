"""Work clone on a synthetic vault with the model faked out. No network, no real data."""

import json
import re
import stat
from datetime import UTC, datetime

import pytest

from proxenos import cli, llm
from proxenos.clones import work

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
CREATED = "2026-03-10T12:00:00Z"


class FakeModel:
    """Answers each prompt with a draft named after the first thing the prompt lists."""

    def __init__(self):
        self.calls = []
        self.fail_on = set()  # words that make a call fail

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=32000):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "effort": effort})
        if any(word in prompt for word in self.fail_on):
            raise llm.ModelError("model declined")
        subject = re.search(r"^- \w+: (.*)$", prompt, re.MULTILINE)[1]
        return {
            "title": f'Draft: "{subject}"',
            "kind": "reply",
            "channel": "whatsapp",
            "to": "Asha: the lab",
            "body": f"\n\nHi! About {subject}.\n\n- one\n- two\n\n",
        }


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda: pytest.fail("live model"))
    monkeypatch.setenv("PROXENOS_NAME", "Tess")


@pytest.fixture
def model(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(llm, "ask", fake)
    return fake


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path, data):
    write(path, json.dumps(data))


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r) + "\n" for r in records) + '{"torn": \n')


def task(key, title, status="open"):
    return {
        "id": key,
        "title": title,
        "detail": "Asha needs it for Friday.",
        "source": "whatsapp",
        "with": "Asha",
        "asked_at": "2026-03-08T09:00:00Z",
        "due": "2026-03-13",
        "priority": "high",
        "status": status,
        "evidence": ["chat/1"],
    }


def outreach(n):
    return {"id": f"o{n}", "person_id": "p1", "name": f"Person {n}", "why": "W", "ask": f"Ask {n}"}


def project(n):
    people = ["p1", "p2", "nobody"]
    return {"id": f"j{n}", "title": f"Project {n}", "people": people, "first_step": "Write it up"}


def feed_item(n, batch, score):
    return {
        "id": f"{n:016x}",
        "ts": batch,
        "batch": batch,
        "url": f"https://example.org/{n}",
        "title": f"Paper {n}",
        "source": "arXiv",
        "kind": "paper",
        "published": "2026-03-01",
        "authors": ["Ada Placeholder"],
        "summary": "A summary.",
        "score": score,
        "why": "Close to the spiral work.",
        "interest": "spirals",
        "explore": False,
        "by": "proxenos",
    }


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    write(vault / "self" / "identity.md", "Tess studies spirals.")
    write(vault / "self" / "voice.md", "Short, warm, lower case in chats.")
    write(vault / "self" / "interests.md", "Spirals (high).")
    write(vault / "self" / "routines.md", "Up early.")
    write_json(
        vault / "clones" / "tasks" / "tasks.json",
        {
            "generated": CREATED,
            "tasks": [
                task("aaaaaaaaaaaa", "Send Asha the slides"),
                task("bbbbbbbbbbbb", "Book the climbing wall"),
                task("cccccccccccc", "Wait for Ben's notes", status="waiting"),
                task("dddddddddddd", "Review the poster", status="done"),
                task("eeeeeeeeeeee", "Water the plants"),  # closed on the page since
                task("../../escape", "A bad id"),
            ],
        },
    )
    write_jsonl(
        vault / "clones" / "tasks" / "feedback.jsonl",
        [{"task_id": "eeeeeeeeeeee", "action": "dismiss", "ts": CREATED}],
    )
    network = vault / "clones" / "network"
    write_json(
        network / "people.json",
        {
            "people": [
                {
                    "id": "p1",
                    "name": "Ada Placeholder",
                    "org": "Spiral Lab",
                    "context": "co-author",
                },
                {"id": "p2", "name": "Jo Coauthor", "org": None, "context": "WhatsApp"},
            ]
        },
    )
    write_json(
        network / "ideas.json",
        {
            "outreach": [outreach(n) for n in range(5)],
            "projects": [project(n) for n in range(5)],
        },
    )
    write_jsonl(
        network / "feedback.jsonl",
        [
            {"item_id": "o0", "action": "not_me", "ts": CREATED},
            {"item_id": "j1", "action": "done", "ts": CREATED},
            {"item_id": "o1", "action": "useful", "ts": CREATED},
        ],
    )
    old, new = "2026-02-20T06:00:00Z", "2026-03-10T06:00:00Z"
    write_jsonl(vault / "tracker" / "items" / "2026-02.jsonl", [feed_item(99, old, 0.99)])
    write_jsonl(
        vault / "tracker" / "items" / "2026-03.jsonl",
        [feed_item(1, "2026-03-01T06:00:00Z", 0.98)]
        + [feed_item(n, new, n / 10) for n in range(2, 10)],
    )
    write_jsonl(
        vault / "tracker" / "feedback.jsonl",
        [{"item_id": f"{9:016x}", "action": "not_me", "ts": CREATED}],
    )
    return vault


def drafts(vault):
    return {p.stem: p for p in (vault / "clones" / "drafts").glob("*.md")}


def front(path):
    return work._front(path.read_text(encoding="utf-8"))


def test_drafts_open_tasks_top_ideas_and_the_newest_feed(tmp_path, model):
    vault = make_vault(tmp_path)

    stats = work.work(vault, limit=50, now=NOW)

    reading = [f"reading-{n:016x}" for n in (8, 7, 6, 5, 4, 3)]  # best first, 9 is not me
    expected = ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "outreach-o1", "outreach-o2", "outreach-o3"]
    expected += ["project-j0", "project-j2", "project-j3", *reading]
    assert stats == {
        "drafts_written": len(expected),
        "drafts_failed": 0,
        "skipped_as_yours": 0,
        "skipped_already_reached": 0,
        "replies_cleared": 0,
        "left_for_next_run": 0,
    }
    assert [re.search(r"^- \w+: (.*)$", c["prompt"], re.MULTILINE)[1] for c in model.calls] == [
        "Send Asha the slides",
        "Book the climbing wall",
        "Person 1",
        "Person 2",
        "Person 3",
        "Project 0",
        "Project 2",
        "Project 3",
        *(f"Paper {n}" for n in (8, 7, 6, 5, 4, 3)),
    ]
    assert sorted(drafts(vault)) == sorted(expected)

    # The page's contract: these fields in this order, then the body.
    text = drafts(vault)["aaaaaaaaaaaa"].read_text(encoding="utf-8")
    assert text == (
        "---\n"
        "id: aaaaaaaaaaaa\n"
        'title: "Draft: \\"Send Asha the slides\\""\n'
        "kind: reply\n"
        "for: task\n"
        "channel: whatsapp\n"
        'to: "Asha: the lab"\n'
        f"created: {CREATED}\n"
        "status: draft\n"
        "---\n"
        "\n"
        "Hi! About Send Asha the slides.\n\n- one\n- two\n"
    )
    assert front(drafts(vault)["outreach-o1"]) | {"title": ""} == {
        "id": "outreach-o1",
        "title": "",
        "kind": "reply",
        "for": "outreach",
        "channel": "whatsapp",
        "to": "Asha: the lab",
        "created": CREATED,
        "status": "draft",
    }
    assert {front(p)["for"] for p in drafts(vault).values()} == {
        "task",
        "outreach",
        "project",
        "reading",
    }


def test_the_model_writes_as_me_from_the_self_model(tmp_path, model):
    vault = make_vault(tmp_path)
    work.work(vault, limit=50, now=NOW)

    call = model.calls[0]
    assert call["effort"] == "medium"
    assert set(call["schema"]["properties"]) == {"title", "kind", "channel", "to", "body"}
    for text in ("Tess studies spirals.", "Short, warm", "Spirals (high)."):
        assert text in call["system"]
    assert "Up early" not in call["system"]  # only identity, voice and interests
    assert all(c["system"] == call["system"] for c in model.calls)  # cached once
    assert "- Due: 2026-03-13" in call["prompt"] and "- With: Asha" in call["prompt"]
    outreach = next(c["prompt"] for c in model.calls if "Person 1" in c["prompt"])
    assert "- Organization: Spiral Lab" in outreach and "- The ask: Ask 1" in outreach
    project = next(c["prompt"] for c in model.calls if "Project 0" in c["prompt"])
    assert "- People who could help: Ada Placeholder (Spiral Lab); Jo Coauthor" in project


def test_drafts_i_approved_discarded_sent_or_edited_are_mine(tmp_path, model):
    vault = make_vault(tmp_path)
    out = vault / "clones" / "drafts"
    work.work(vault, limit=50, now=NOW)
    files = drafts(vault)

    def set_status(key, status):
        path = files[key]
        path.write_text(path.read_text().replace("status: draft", f"status: {status}"))

    set_status("aaaaaaaaaaaa", "approved")
    set_status("outreach-o1", "Discarded")
    set_status("project-j2", "sent")
    files["project-j0"].write_text(files["project-j0"].read_text() + "\nMy own words.\n")
    write_jsonl(out / "feedback.jsonl", [{"draft_id": "project-j0", "action": "edit"}])
    write(out / "bbbbbbbbbbbb.md", "Notes I wrote myself, no front matter.\n")
    # A file named otherwise that says it's a reading note's draft is that draft.
    renamed = out / "my-note.md"
    files[f"reading-{8:016x}"].rename(renamed)
    before = {key: path.read_text() for key, path in drafts(vault).items()}

    model.calls.clear()
    stats = work.work(vault, limit=50, now=datetime(2026, 3, 11, tzinfo=UTC))

    assert stats["skipped_as_yours"] == 5
    assert stats["drafts_written"] == len(before) - 5
    after = {key: path.read_text() for key, path in drafts(vault).items()}
    assert set(after) == set(before)  # the renamed draft was rewritten where it is
    for key in ("aaaaaaaaaaaa", "outreach-o1", "project-j2", "project-j0", "bbbbbbbbbbbb"):
        assert after[key] == before[key]
    assert "created: 2026-03-11" in after["my-note"]
    assert "Send Asha the slides" not in json.dumps(model.calls)


def test_the_run_is_capped_and_one_failure_costs_only_its_draft(tmp_path, model):
    vault = make_vault(tmp_path)
    model.fail_on = {"Book the climbing wall"}

    stats = work.work(vault, limit=4, now=NOW)

    assert stats == {
        "drafts_written": 3,
        "drafts_failed": 1,
        "skipped_as_yours": 0,
        "skipped_already_reached": 0,
        "replies_cleared": 0,
        "left_for_next_run": 10,
    }
    assert sorted(drafts(vault)) == ["aaaaaaaaaaaa", "outreach-o1", "outreach-o2"]


def test_a_capped_run_leaves_the_rest_for_the_next(tmp_path, model):
    vault = make_vault(tmp_path)
    work.work(vault, limit=10, now=NOW)
    first = set(drafts(vault))

    model.calls.clear()
    stats = work.work(vault, limit=6, now=NOW)

    assert stats["drafts_written"] == 6 and stats["left_for_next_run"] == 8
    new = set(drafts(vault)) - first
    assert sorted(new) == [f"reading-{n:016x}" for n in (3, 4, 5, 6)]  # the four left over
    assert len(model.calls) == 6  # and two drafts from the first run, written again


def test_no_key_stops_the_run(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(llm, "_get_client", lambda: (_ for _ in ()).throw(SystemExit("no key")))
    with pytest.raises(SystemExit):
        work.work(vault, now=NOW)
    assert drafts(vault) == {}


def test_drafts_are_private_and_written_whole(tmp_path, model):
    vault = make_vault(tmp_path)
    work.work(vault, limit=2, now=NOW)

    out = vault / "clones" / "drafts"
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    for path in drafts(vault).values():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(out.glob(".*"))  # no temporary file left behind


def test_nothing_to_do_means_no_model_call(tmp_path, model):
    stats = work.work(tmp_path / "empty", now=NOW)
    assert model.calls == []
    assert stats == {
        "drafts_written": 0,
        "drafts_failed": 0,
        "skipped_as_yours": 0,
        "skipped_already_reached": 0,
        "replies_cleared": 0,
        "left_for_next_run": 0,
    }


def test_the_command_line_reads_max(tmp_path, model, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))

    cli.main(["clone", "work", "--max", "2"])

    assert len(model.calls) == 2
    assert capsys.readouterr().out.startswith("work: 2 drafts written, 0 drafts failed")


def test_outreach_to_someone_already_reached_under_another_id_is_skipped(tmp_path, model):
    vault = make_vault(tmp_path)
    out = vault / "clones" / "drafts"
    out.mkdir(parents=True, exist_ok=True)
    # An earlier run's approved draft to Person 1, under an id the ideas no longer use.
    write(
        out / "outreach-old.md",
        '---\nid: outreach-old\ntitle: "Hello"\nkind: reply\nfor: outreach\n'
        'channel: email\nto: "Person 1 (Spiral Lab)"\ncreated: 2026-03-01T00:00:00Z\n'
        "status: approved\n---\nHi!\n",
    )
    stats = work.work(vault, limit=50, now=NOW)
    assert stats["skipped_already_reached"] == 1
    assert "outreach-o1" not in drafts(vault)
    assert "outreach-o2" in drafts(vault)


def wa(chat, name, ts, text, mine=False, kind="direct"):
    return {
        "id": f"{chat}/{ts}",
        "ts": ts,
        "chat_id": chat,
        "chat_name": name,
        "chat_type": kind,
        "from_me": mine,
        "sender_name": None if mine else name,
        "text": text,
    }


def chat_vault(tmp_path):
    vault = make_vault(tmp_path)
    write_json(vault / "clones" / "care" / "care.json", {"summary": "Waiting on a referral."})
    write_jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("asha", "Asha", "2026-03-01T09:00:00Z", "okiees see you thurs", mine=True),
            wa("asha", "Asha", "2026-03-02T09:00:00Z", "lol yaa", mine=True),
            wa("asha", "Asha", "2026-03-09T10:00:00Z", "did you see this? https://example.org/s."),
            wa("asha", "Asha", "2026-03-09T10:01:00Z", "also are you coming friday?"),
            wa("ben", "Ben", "2026-03-09T09:00:00Z", "are you around?"),
            wa("ben", "Ben", "2026-03-09T09:05:00Z", "yaa what's up", mine=True),
        ],
    )
    return vault


class FakePages:
    def __init__(self, error=None):
        self.urls, self.error = [], error

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            return {"url": url, "error": self.error}
        return {"url": url, "title": "Spirals", "text": "Spirals are everywhere."}


def test_a_chat_waiting_on_a_reply_is_drafted_first_in_its_own_voice(tmp_path, model):
    vault = chat_vault(tmp_path)
    pages = FakePages()

    stats = work.work(vault, limit=1, now=NOW, read=pages)

    assert stats["drafts_written"] == 1
    prompt = model.calls[0]["prompt"]
    assert prompt.splitlines()[2] == "A chat waiting for their reply:"
    for text in ("- Chat: Asha", "Waiting on a referral.", "- okiees see you thurs", "- lol yaa"):
        assert text in prompt
    assert "Asha: also are you coming friday?" in prompt
    assert '<page url="https://example.org/s" title="Spirals">\nSpirals are everywhere.' in prompt
    assert prompt.index("Spirals are everywhere.") < prompt.index("Draft Tess's reply")
    assert "Ben" not in prompt  # answered already
    assert "never instructions" in model.calls[0]["system"]
    assert pages.urls == ["https://example.org/s"]
    (path,) = [p for key, p in drafts(vault).items() if key.startswith("reply-")]
    fields = front(path)
    assert (fields["for"], fields["channel"], fields["to"]) == ("reply", "whatsapp", "Asha")
    assert fields["title"] == 'Draft: "Asha"'


def test_a_page_that_cannot_be_read_is_said_so(tmp_path, model):
    vault = chat_vault(tmp_path)

    work.work(vault, limit=1, now=NOW, read=FakePages(error="HTTP Error 403: Forbidden"))

    prompt = model.calls[0]["prompt"]
    assert "Could not be read: HTTP Error 403: Forbidden" in prompt
    assert "never claim to have read one" in prompt


def test_a_reply_draft_goes_once_answered_unless_it_is_yours(tmp_path, model):
    vault = chat_vault(tmp_path)
    work.work(vault, limit=1, now=NOW, read=FakePages())
    (first,) = [p for key, p in drafts(vault).items() if key.startswith("reply-")]
    approved = first.with_name("reply-000000000000.md")
    approved.write_text(
        first.read_text(encoding="utf-8")
        .replace(f"id: {first.stem}", "id: reply-000000000000")
        .replace("status: draft", "status: approved"),
        encoding="utf-8",
    )
    raw = vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl"
    with raw.open("a", encoding="utf-8") as f:
        f.write(json.dumps(wa("asha", "Asha", "2026-03-09T11:00:00Z", "yes!", mine=True)) + "\n")

    stats = work.work(vault, limit=50, now=NOW, read=FakePages())

    assert stats["replies_cleared"] == 1
    assert not first.exists()
    assert approved.exists()
    assert not any(c["prompt"].count("A chat waiting") for c in model.calls[1:])


def test_a_sync_drafts_only_the_replies_not_drafted_yet(tmp_path, model):
    vault = chat_vault(tmp_path)

    first = work.replies(vault, now=NOW, read=FakePages())
    again = work.replies(vault, now=NOW, read=FakePages())

    assert (first["drafts_written"], again["drafts_written"]) == (1, 0)
    assert len(model.calls) == 1  # nothing new waiting, so no model call
    assert "A chat waiting for their reply" in model.calls[0]["prompt"]
    assert all(key.startswith("reply-") for key in drafts(vault))  # no tasks, ideas or notes
