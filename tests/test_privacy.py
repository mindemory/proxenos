"""The Privacy view's report: what stays here, what went to a model and what's read from
elsewhere. A made-up vault and calls log under tmp_path, with fdesetup and the Connect report
faked out, and never a secret, a prompt or a message in what it prints."""

import json
import os
import subprocess
from datetime import UTC, datetime

import pytest

from proxenos import cli, privacy

SECRET = "s3cret-value-that-must-never-show"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
REAL_FDESETUP = privacy._fdesetup


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder of its own, so the vault shows as ~/... and no real one is read."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("USERPROFILE", str(folder))
    return folder


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """No real fdesetup and no real Connect report: a Mac with FileVault on, and two sources
    connected, each carrying a secret in a field the report should never copy."""
    monkeypatch.setattr(privacy, "_fdesetup", lambda: "FileVault is On.\n")
    sources = [
        {
            "id": "gmail",
            "how": "live",
            "connected": True,
            "last_read": "2026-10-31T08:00:00Z",
            "problem": None,
            "detail": SECRET,
            "accounts": [
                {
                    "name": "personal",
                    "address": "ana@example.com",
                    "sign_in": "google",
                    "token": SECRET,
                }
            ],
            "workspaces": [],
        },
        {
            "id": "whatsapp",
            "how": "live",
            "connected": False,
            "last_read": None,
            "accounts": [],
            "workspaces": [],
        },
        {
            "id": "slack",
            "how": "live",
            "connected": True,
            "last_read": None,
            "accounts": [],
            "workspaces": ["acme"],
        },
        {
            "id": "letterboxd",
            "how": "download",
            "connected": True,
            "last_read": "2026-09-01T00:00:00Z",
            "accounts": [],
            "workspaces": [],
        },
    ]
    monkeypatch.setattr(privacy.connect, "report", lambda vault: {"sources": sources, "phone": {}})


def write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def log(vault, *lines):
    path = vault / "state" / "model-calls.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def call(at, step, where="this computer", ok=True, **counts):
    model = "ollama:gemma4:26b" if where == "this computer" else "claude-opus-5-5"
    return {
        "at": at,
        "step": step,
        "model": model,
        "where": where,
        "sent_chars": 1000,
        "images": 0,
        "answer_chars": 200 if ok else 0,
        "tokens_in": None,
        "tokens_out": None,
        "seconds": 3.21,
        "ok": ok,
    } | counts


def test_what_stays_here_is_the_vault_by_folder_and_secrets_by_name(home, monkeypatch):
    vault = home / "vault"
    for folder, size in {"raw": 4000, "memory": 900, "clones": 300, "self": 50}.items():
        write(vault / folder / "a" / "file.jsonl", size)
    write(vault / "observations" / "2026-10.md", 20)
    write(vault / "state" / "sync.json", 10)
    write(vault / ".git" / "objects" / "ab", 7)
    write(vault / "voice" / "adapter.bin", 3)
    outside = home / "elsewhere.bin"
    write(outside, 10_000)
    try:
        (vault / "raw" / "link").symlink_to(outside)  # a link is never followed
    except OSError:
        pass  # Windows without the right to make one
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"sk-ant-{SECRET}")
    monkeypatch.setenv("GMAIL_PERSONAL", f"ana@example.com:{SECRET}")

    report = privacy.report(vault, NOW)
    here = report["here"]

    folders = here["vault"]["folders"]
    assert folders["raw"] < 5000 and folders["raw"] >= 4000
    assert {k: v for k, v in folders.items() if k != "raw"} == {
        "memory": 900,
        "clones": 300,
        "self": 50,
        "observations": 20,
        "state": 10,
        "other": 10,
    }
    assert here["vault"]["bytes"] == sum(folders.values())
    assert here["vault"]["exists"] is True and here["vault"]["cloud"] is None
    assert here["vault"]["path"] == os.path.join("~", "vault")
    assert here["filevault"] is True
    assert here["secret_store"] == "Keychain"
    assert here["secrets"] == [
        {"name": "ANTHROPIC_API_KEY", "from": "environment"},
        {"name": "GMAIL_PERSONAL", "from": "environment"},
    ]
    assert SECRET not in json.dumps(report)


def test_a_vault_that_isnt_there_is_said_with_nothing_in_it(home):
    here = privacy.report(home / "nowhere", NOW)["here"]
    assert here["vault"]["exists"] is False and here["vault"]["bytes"] == 0
    assert set(here["vault"]["folders"]) == {*privacy.FOLDERS, "other"}


def test_calls_are_totalled_for_thirty_days_by_where_and_step(home, monkeypatch):
    vault = home / "vault"
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    log(
        vault,
        call("2026-09-20T00:00:00Z", "observe"),  # before the 30 days
        call("2026-10-10T01:00:00Z", "observe"),
        call("2026-10-10T02:00:00Z", "observe", ok=False),
        call("2026-10-20T03:00:00Z", "work", tokens_in=300, tokens_out=40),
        '{"at": "2026-10-21',  # a line still being written
        call("2026-10-22T04:00:00Z", "", prompt=SECRET, answer=SECRET),
    )

    sent = privacy.report(vault, NOW)["sent"]

    assert sent["model"] == {"name": "gemma4:26b", "kind": "local", "voice": None}
    assert sent["days"] == 30 and sent["since"] == "2026-10-02T12:00:00Z"
    assert sent["totals"] == {
        "calls": 4,
        "failed": 1,
        "hosted": 0,
        "sent_chars": 4000,
        "images": 0,
        "answer_chars": 600,
        "tokens_in": 300,
        "tokens_out": 40,
    }
    assert sent["by_where"]["Anthropic"]["calls"] == 0  # nothing went to a hosted model
    assert sent["by_where"]["this computer"]["calls"] == 4
    assert [(s["step"], s["part"], s["calls"]) for s in sent["by_step"]] == [
        ("observe", "Observers", 2),
        ("proxenos", None, 1),
        ("work", "Drafts", 1),
    ]
    newest = sent["recent"][0]
    assert newest == {
        "at": "2026-10-22T04:00:00Z",
        "step": "proxenos",
        "model": "ollama:gemma4:26b",
        "where": "this computer",
        "sent_chars": 1000,
        "images": 0,
        "answer_chars": 200,
        "tokens_in": None,
        "tokens_out": None,
        "seconds": 3.2,
        "ok": True,
    }
    assert [c["at"][:10] for c in sent["recent"]] == [
        "2026-10-22",
        "2026-10-20",
        "2026-10-10",
        "2026-10-10",
    ]
    assert SECRET not in json.dumps(sent)


def test_a_call_that_went_away_counts_as_hosted_and_only_the_newest_are_listed(home, monkeypatch):
    vault = home / "vault"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(privacy, "NEWEST", 2)
    log(
        vault,
        call("2026-10-20T00:00:00Z", "care", where="Anthropic", images=2),
        call("2026-10-21T00:00:00Z", "care", where="Anthropic", ok=False),
        {k: v for k, v in call("2026-10-22T00:00:00Z", "ask").items() if k != "where"},
        call("2026-10-23T00:00:00Z", "ask", sent_chars=True, seconds=float("nan")),
    )

    sent = privacy.report(vault, NOW)["sent"]

    assert sent["model"]["kind"] == "api" and sent["model"]["name"] == "claude-opus-5-5"
    assert sent["by_where"]["Anthropic"] == {
        "calls": 3,
        "failed": 1,
        "hosted": 3,
        "sent_chars": 3000,
        "images": 2,
        "answer_chars": 400,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    care = next(s for s in sent["by_step"] if s["step"] == "care")
    assert (care["part"], care["calls"], care["hosted"], care["failed"]) == ("Care", 2, 2, 1)
    assert [c["at"][:10] for c in sent["recent"]] == ["2026-10-23", "2026-10-22"]
    odd = sent["recent"][0]
    assert odd["sent_chars"] is None and odd["seconds"] is None  # not a count, not a number
    json.loads(json.dumps(sent, allow_nan=False))  # the page can read it


def test_each_part_says_what_it_sends_and_every_step_is_one_parts(home):
    sends = privacy.report(home / "vault", NOW)["sent"]["sends"]
    steps = [step for part in sends for step in part["steps"]]
    assert len(steps) == len(set(steps))
    assert {"observe", "work", "care", "tasks", "ask", "calls"} <= set(steps)
    assert all(part["part"] and part["sends"].endswith(".") for part in sends)


def test_what_is_fetched_is_each_connected_source_by_name_and_address(home, monkeypatch):
    fetched = privacy.report(home / "vault", NOW)["fetched"]

    assert fetched["sources"] == [
        {
            "id": "gmail",
            "how": "live",
            "last_read": "2026-10-31T08:00:00Z",
            "accounts": [{"name": "personal", "address": "ana@example.com"}],
            "workspaces": [],
        },
        {
            "id": "slack",
            "how": "live",
            "last_read": None,
            "accounts": [],
            "workspaces": ["acme"],
        },
        {
            "id": "letterboxd",
            "how": "download",
            "last_read": "2026-09-01T00:00:00Z",
            "accounts": [],
            "workspaces": [],
        },
    ]
    assert fetched["links"] is False  # no model, so no replies drafted and no links read
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    assert privacy.report(home / "vault", NOW)["fetched"]["links"] is True
    assert SECRET not in json.dumps(fetched)


def test_filevault_is_read_from_fdesetup_and_never_fails(monkeypatch):
    monkeypatch.setattr(privacy, "_fdesetup", REAL_FDESETUP)  # with subprocess faked below
    ran = []

    def answer(said):
        def run(args, **kwargs):
            ran.append(args)
            if isinstance(said, BaseException):
                raise said
            return subprocess.CompletedProcess(args, 0, said, "")

        return run

    monkeypatch.setattr(privacy.sys, "platform", "linux")
    monkeypatch.setattr(privacy.subprocess, "run", answer("FileVault is On."))
    assert privacy.filevault() is None and ran == []  # only a Mac has it

    monkeypatch.setattr(privacy.sys, "platform", "darwin")
    assert privacy.filevault() is True and ran == [["fdesetup", "status"]]
    monkeypatch.setattr(privacy.subprocess, "run", answer("FileVault is Off.\n"))
    assert privacy.filevault() is False
    monkeypatch.setattr(privacy.subprocess, "run", answer("Something else\n"))
    assert privacy.filevault() is None
    for failure in (FileNotFoundError("fdesetup"), subprocess.TimeoutExpired("fdesetup", 10)):
        monkeypatch.setattr(privacy.subprocess, "run", answer(failure))
        assert privacy.filevault() is None


def test_the_command_prints_the_report_as_json(home, monkeypatch, capsys):
    vault = home / "vault"
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"sk-ant-{SECRET}")
    log(vault, call("2999-01-01T00:00:00Z", "tasks", where="Anthropic", prompt=SECRET))

    cli.main(["privacy"])

    out = capsys.readouterr().out
    printed = json.loads(out)
    assert set(printed) == {"now", "here", "sent", "fetched"}
    assert printed["sent"]["by_where"]["Anthropic"]["calls"] == 1
    assert SECRET not in out
