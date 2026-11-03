"""Notices on the phone through ntfy: a made-up vault under tmp_path, full of names and words
that must never leave, and the HTTP call faked out, so nothing reaches the network."""

import json
import os
import urllib.error
from datetime import datetime, timedelta

import pytest

from proxenos import cli, master, notify, setup

TOPIC = "proxenos-k3v9q2m8x7w4t1zr5b"
TOKEN = "tk_made_up_for_this_test_only"
# Everything in the vault that could say who or what: none of it may be in a notice.
PRIVATE = (
    "Ana Lee",
    "Ana",
    "Rivera",
    "biopsy",
    "MRI",
    "lease",
    "Cookbook",
    "cookbook",
    "Thursday",
    "results",
    "whatsapp",
    "+1 603",
)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in this computer's own time zone, as quiet hours read it."""
    return datetime(2026, 11, day, hour, minute).astimezone()


NOON = local(2, 12)


class Sent:
    """urlopen standing in for the network: keeps each request, answers ok or raises."""

    def __init__(self):
        self.requests = []
        self.error: Exception | None = None

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return b'{"id":"x"}'

    @property
    def bodies(self):
        return [r.data.decode() for r in self.requests]


@pytest.fixture
def sent(monkeypatch):
    fake = Sent()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", TOPIC)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def draft(vault, key, *, status="draft", kind="reply", to="Ana Lee", created=NOON, body=None):
    text = (
        f"---\nid: {key}\ntitle: Reply to Ana Lee about the biopsy results\nkind: {kind}\n"
        f"for: reply\nchannel: whatsapp\nto: {to}\ncreated: {created.isoformat()}\n"
        f"status: {status}\n---\n\n"
        + (body or "Hi Ana, the MRI is on Thursday; call me on +1 603 555 0100.\n")
    )
    path = write(vault / "clones" / "drafts" / f"{key}.md", text)
    os.utime(path, (created.timestamp(), created.timestamp()))
    return path


def care(vault, items, feedback=()):
    folder = vault / "clones" / "care"
    write(
        folder / "care.json", json.dumps({"summary": "Waiting on Dr. Rivera.", "open_items": items})
    )
    write(folder / "feedback.jsonl", "".join(json.dumps(f) + "\n" for f in feedback))


def tasks(vault, items, feedback=()):
    folder = vault / "clones" / "tasks"
    write(folder / "tasks.json", json.dumps({"generated": "2026-11-02", "tasks": items}))
    write(folder / "feedback.jsonl", "".join(json.dumps(f) + "\n" for f in feedback))


def step(vault, project, when, status):
    path = vault / "clones" / "projects" / project / "steps" / f"{when}.json"
    write(path, json.dumps({"id": f"{project}/{when}", "status": status, "summary": "Cookbook"}))


@pytest.fixture
def vault(tmp_path):
    """One of each kind waiting, beside ones that don't: sent, a note, stale, someone else's
    move, marked on the page, not due yet, paused."""
    vault = tmp_path / "vault"
    draft(vault, "r1")
    draft(vault, "r2", status="sent")
    draft(vault, "n1", kind="doc", to="")
    draft(vault, "old", created=NOON - timedelta(days=10))
    care(
        vault,
        [
            {"id": "c1", "title": "Call Dr. Rivera about the MRI", "waiting_on": "me"},
            {"id": "c2", "title": "Biopsy results", "waiting_on": "provider", "status": "open"},
            {"id": "c3", "title": "Lab bill", "waiting_on": "me", "status": "open"},
        ],
        [{"item_id": "c3", "action": "done", "ts": "2026-11-01T10:00:00Z"}],
    )
    tasks(
        vault,
        [
            {"id": "t1", "title": "Send Ana the lease", "status": "open", "due": "2026-11-03"},
            {"id": "t2", "title": "Renew the lease", "status": "open", "due": "2026-11-20"},
            {"id": "t3", "title": "Call Ana back", "status": "open", "due": "2026-10-30"},
            {"id": "t4", "title": "Pay rent", "status": "done", "due": "2026-11-01"},
        ],
        [{"task_id": "t3", "action": "not_mine", "ts": "2026-11-01T10:00:00Z"}],
    )
    projects_list = {
        "projects": [
            {"id": "cookbook", "name": "Cookbook with Ana Lee"},
            {"id": "thesis", "name": "Thesis", "paused": True},
        ]
    }
    write(vault / "clones" / "projects" / "projects.json", json.dumps(projects_list))
    step(vault, "cookbook", "20261101-090000", "ready")
    step(vault, "cookbook", "20261031-090000", "accepted")
    step(vault, "thesis", "20261101-090000", "ready")
    return vault


def state(vault):
    return json.loads((vault / notify.STATE).read_text(encoding="utf-8"))


def test_nothing_is_sent_or_kept_without_a_topic(vault, sent):
    assert notify.configured() is False
    assert notify.run(vault, NOON) == {}
    assert sent.requests == []
    assert not (vault / notify.STATE).exists()


def test_what_waits_is_counted_as_the_page_counts_it(vault):
    assert notify.counts(vault, NOON) == {"drafts": 1, "care": 1, "steps": 1, "tasks": 1}


def test_a_notice_says_counts_and_kinds_and_nothing_else(vault, sent, on, monkeypatch):
    monkeypatch.setenv("NTFY_TOKEN", TOKEN)

    assert notify.run(vault, NOON) == {"notices_sent": 1}

    [request] = sent.requests
    assert request.full_url == f"https://ntfy.sh/{TOPIC}"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    body = request.data.decode()
    assert body == (
        "1 draft to send, 1 care item, 1 step to review and 1 task due soon wait on you."
    )
    said = body + json.dumps(dict(request.header_items()))
    assert not [word for word in PRIVATE if word in said]
    assert state(vault) == {
        "counts": {"drafts": 1, "care": 1, "steps": 1, "tasks": 1},
        "sent": notify._iso(NOON),
    }
    if os.name != "nt":
        assert (vault / notify.STATE).stat().st_mode & 0o777 == 0o600


def test_the_words_agree_with_how_many(vault):
    assert notify.message({"drafts": 0, "care": 0}) is None
    assert notify.message({"tasks": 1}) == "1 task due soon waits on you."
    assert (
        notify.message({"care": 2, "drafts": 3}) == "3 drafts to send and 2 care items wait on you."
    )
    assert notify.message({"steps": 1, "made_up": 5}) == "1 step to review waits on you."


def test_a_notice_goes_only_when_a_count_went_up(vault, sent, on):
    assert notify.run(vault, NOON)["notices_sent"] == 1
    assert notify.run(vault, NOON + timedelta(minutes=15)) == {"notices_sent": 0}
    assert len(sent.requests) == 1

    draft(vault, "r3")  # a new reply
    assert notify.run(vault, NOON + timedelta(minutes=30))["notices_sent"] == 1
    assert sent.bodies[-1].startswith("2 drafts to send, 1 care item")

    draft(vault, "r1", status="sent")  # the user deals with both
    draft(vault, "r3", status="sent")
    assert notify.run(vault, NOON + timedelta(minutes=45)) == {"notices_sent": 0}
    assert state(vault)["counts"]["drafts"] == 0  # lowered, so the next one is news

    draft(vault, "r4")
    assert notify.run(vault, NOON + timedelta(hours=1))["notices_sent"] == 1
    assert sent.bodies[-1].startswith("1 draft to send, ")
    assert len(sent.requests) == 3  # one a run at most


def test_quiet_hours_hold_a_notice_until_the_first_run_after_them(vault, sent, on):
    assert notify.run(vault, local(2, 23, 30)) == {"notices_sent": 0, "notices_held": 1}
    assert notify.run(vault, local(3, 2)) == {"notices_sent": 0, "notices_held": 1}
    assert sent.requests == []
    assert state(vault) == {"counts": dict.fromkeys(notify.KINDS, 0), "sent": None}  # not heard

    assert notify.run(vault, local(3, 8, 5))["notices_sent"] == 1
    assert len(sent.requests) == 1
    assert notify.run(vault, local(3, 8, 20)) == {"notices_sent": 0}


def test_a_held_notice_is_dropped_when_what_was_new_is_dealt_with_overnight(vault, sent, on):
    notify.run(vault, NOON)
    draft(vault, "r5")
    assert notify.run(vault, local(2, 23))["notices_held"] == 1
    draft(vault, "r5", status="discarded")
    assert notify.run(vault, local(3, 8, 30)) == {"notices_sent": 0}
    assert len(sent.requests) == 1


def test_quiet_hours_can_be_moved_or_switched_off(vault, sent, on, monkeypatch):
    monkeypatch.setenv("PROXENOS_QUIET_HOURS", "21:30-06:00")
    assert notify.quiet(local(2, 21, 45)) and not notify.quiet(local(2, 6, 0))
    assert notify.quiet(local(3, 1)) and not notify.quiet(NOON)
    monkeypatch.setenv("PROXENOS_QUIET_HOURS", "13:00-15:00")
    assert notify.quiet(local(2, 14)) and not notify.quiet(local(2, 23))
    monkeypatch.setenv("PROXENOS_QUIET_HOURS", "off")
    assert notify.run(vault, local(2, 23, 30))["notices_sent"] == 1
    monkeypatch.setenv("PROXENOS_QUIET_HOURS", "late")  # unreadable: the default holds
    assert notify.quiet(local(2, 23)) and not notify.quiet(NOON)
    with pytest.raises(ValueError):
        notify.parse_quiet("25:00-08:00")


def test_a_failed_notice_never_raises_and_is_tried_again(vault, sent, on, capsys):
    sent.error = urllib.error.URLError(f"no route to ntfy.sh/{TOPIC}")
    assert notify.run(vault, NOON) == {"notices_sent": 0, "notify_failed": 1}
    err = capsys.readouterr().err
    assert err.startswith("notify: couldn't reach ntfy.sh") and TOPIC not in err

    sent.error = urllib.error.HTTPError("https://ntfy.sh", 403, "Forbidden", {}, None)
    assert notify.run(vault, NOON + timedelta(minutes=15))["notify_failed"] == 1
    assert "403 (the token isn't allowed to post there)" in capsys.readouterr().err

    sent.error = None
    assert notify.run(vault, NOON + timedelta(minutes=30))["notices_sent"] == 1
    assert len(sent.requests) == 3


def test_a_broken_file_or_a_crash_never_raises(vault, sent, on, monkeypatch, capsys):
    write(vault / "clones" / "projects" / "projects.json", "{not json")
    assert notify.run(vault, NOON)["notices_sent"] == 1  # the rest still counted
    assert "step" not in sent.bodies[0]
    assert "couldn't count the steps" in capsys.readouterr().err

    def crash(vault, now=None):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(notify, "counts", crash)
    assert notify.run(vault, NOON) == {"notices_sent": 0, "notify_failed": 1}


def test_another_server_and_a_bad_one(vault, sent, on, monkeypatch):
    monkeypatch.setenv("PROXENOS_NTFY_SERVER", "https://ntfy.example.org/")
    notify.run(vault, NOON)
    assert sent.requests[0].full_url == f"https://ntfy.example.org/{TOPIC}"
    assert sent.requests[0].get_header("Authorization") is None  # no token, none sent

    monkeypatch.setenv("PROXENOS_NTFY_SERVER", "file:///etc")
    sent_, said = notify.test()
    assert not sent_
    assert said == "The test didn't go through: the ntfy server 'file:///etc' isn't a web " + (
        "address like https://ntfy.sh."
    )
    monkeypatch.setenv("NTFY_TOPIC", "has spaces/and slashes")
    monkeypatch.delenv("PROXENOS_NTFY_SERVER")
    assert "only letters, digits" in notify.test()[1]
    assert len(sent.requests) == 1


def test_a_demo_vault_sends_nothing(vault, sent, on):
    write(vault / "DEMO", "")
    assert notify.run(vault, NOON) == {}
    assert sent.requests == []


def test_sync_and_night_notify_last_and_never_fail_for_it(vault, sent, on, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    monkeypatch.setattr(master, "sync", lambda vault: {"sources_synced": 1})
    monkeypatch.setattr(notify, "quiet", lambda now: False)
    cli.main(["sync"])
    assert capsys.readouterr().out == "sync: 1 sources synced, 1 notices sent\n"
    assert len(sent.requests) == 1

    ran = []
    monkeypatch.setattr(cli, "NIGHT_CLONES", ())
    monkeypatch.setattr(master, "run", lambda vault: ran.append("master") or {"done": 1})
    monkeypatch.setattr(cli.voicemodel, "refresh", lambda vault: {})
    monkeypatch.setattr(cli.voice, "lessons", lambda vault: {})
    sent.error = OSError("offline")
    draft(vault, "r6", created=datetime.now().astimezone())
    cli.main(["night"])  # a failed notice doesn't fail the night: no SystemExit
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("notify: 0 notices sent, 1 notify failed [")
    assert ran == ["master"]


def test_the_test_command_says_whether_it_got_through(sent, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    with pytest.raises(SystemExit) as exit_:
        cli.main(["notify", "test"])
    assert exit_.value.code == 1
    assert capsys.readouterr().out.startswith("No topic is set.")

    monkeypatch.setenv("NTFY_TOPIC", TOPIC)
    cli.main(["notify", "test"])
    out = capsys.readouterr().out
    assert out == "Sent a test through ntfy.sh. It should be on your phone now.\n"
    assert sent.bodies == ["A test from Proxenos: notices reach this phone."]

    sent.error = urllib.error.URLError("timed out")
    with pytest.raises(SystemExit):
        cli.main(["notify", "test"])
    out = capsys.readouterr().out
    assert out.startswith("The test didn't go through: couldn't reach ntfy.sh") and TOPIC not in out


def test_the_topic_and_token_are_secrets_and_the_server_and_hours_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    names = {s["name"] for s in setup.status()["secrets"]}
    assert {"NTFY_TOPIC", "NTFY_TOKEN"} <= names

    saved = setup.apply({"secret": "NTFY_TOPIC", "value": TOPIC})
    assert saved["ok"], saved
    assert TOPIC not in json.dumps(saved)
    assert notify.configured()
    bad = setup.apply({"secret": "NTFY_TOPIC", "value": "my topic"})
    assert not bad["ok"] and "letters, digits" in bad["error"]

    assert setup.apply({"settings": {"ntfy_server": "https://ntfy.example.org/"}})["ok"]
    assert setup.status()["settings"]["ntfy_server"]["value"] == "https://ntfy.example.org"
    assert not setup.apply({"settings": {"ntfy_server": "ntfy.example.org"}})["ok"]
    assert setup.apply({"settings": {"quiet_hours": "off"}})["ok"]
    assert not setup.apply({"settings": {"quiet_hours": "evenings"}})["ok"]


def test_the_privacy_report_says_where_notices_go_never_the_topic(monkeypatch):
    assert notify.report() == {
        "on": False,
        "server": "ntfy.sh",
        "quiet": "22:00-08:00",
        "sends": notify.SENDS,
    }
    monkeypatch.setenv("NTFY_TOPIC", TOPIC)
    monkeypatch.setenv("PROXENOS_NTFY_SERVER", "https://push.example.org")
    monkeypatch.setenv("PROXENOS_QUIET_HOURS", "off")
    said = notify.report()
    assert said["on"] is True and said["server"] == "push.example.org" and said["quiet"] is None
    assert TOPIC not in json.dumps(said)
