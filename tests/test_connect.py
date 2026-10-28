"""The Connect view's report: what's connected, and never a secret. No real data or account."""

import json
import os

import pytest

from proxenos import auth, cli, connect
from proxenos.ingest import whatsapp

SECRET = "s3cret-value-that-must-never-show"


def month(folder, name="2025-01.jsonl"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text('{"id": "1", "ts": "2025-01-02T00:00:00Z"}\n')


def store(tmp_path):
    db = tmp_path / "ChatStorage.sqlite"
    db.write_bytes(b"SQLite format 3\x00")
    return db


def by_id(report):
    return {s["id"]: s for s in report["sources"]}


def test_every_source_is_listed_once_in_its_group(tmp_path):
    sources = connect.report(tmp_path, store(tmp_path))["sources"]
    assert [s["id"] for s in sources] == [*connect.LIVE, *connect.DOWNLOADS, *connect.FOLDERS]
    assert {s["how"] for s in sources if s["id"] in connect.DOWNLOADS} == {"download"}
    assert not any(s["connected"] for s in sources if s["id"] != "whatsapp")


def test_the_report_names_accounts_and_never_holds_a_secret(tmp_path, monkeypatch):
    for name, value in {
        "GMAIL_PERSONAL": f"me@example.com:oauth:1//{SECRET}",
        "GMAIL_WORK": f"work@example.com:{SECRET}",
        "GOOGLE_CLIENT_ID": f"id-{SECRET}",
        "GOOGLE_CLIENT_SECRET": SECRET,
        "SLACK_USER_TOKEN": f"xoxp-{SECRET}",
        "STRAVA_CLIENT_ID": SECRET,
        "STRAVA_REFRESH_TOKEN": SECRET,
        "ANTHROPIC_API_KEY": f"sk-ant-{SECRET}",
    }.items():
        monkeypatch.setenv(name, value)
    month(tmp_path / "raw" / "email" / "personal")

    report = connect.report(tmp_path, store(tmp_path))

    assert SECRET not in json.dumps(report)
    sources = by_id(report)
    assert sources["gmail"]["connected"] and sources["gmail"]["problem"] is None
    assert [(a["name"], a["address"], a["sign_in"]) for a in sources["gmail"]["accounts"]] == [
        ("personal", "me@example.com", "google"),
        ("work", "work@example.com", "app_password"),
    ]
    assert sources["gmail"]["accounts"][0]["last_read"] == sources["gmail"]["last_read"]
    assert sources["gmail"]["accounts"][1]["last_read"] is None
    assert sources["slack"]["connected"] and sources["strava"]["connected"]


def test_gmail_sign_in_needs_a_google_client(tmp_path, monkeypatch):
    def problem():
        return by_id(connect.report(tmp_path, store(tmp_path)))["gmail"]["problem"]

    assert problem() == "no_google_client"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    assert problem() == "no_google_client"
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert problem() is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_whatsapp_is_connected_when_its_store_can_be_read(tmp_path):
    db = store(tmp_path)
    month(tmp_path / "raw" / "whatsapp" / "messages")
    readable = by_id(connect.report(tmp_path, db))["whatsapp"]
    assert readable["connected"] and readable["problem"] is None and readable["last_read"]

    db.chmod(0)
    try:
        blocked = by_id(connect.report(tmp_path, db))["whatsapp"]
    finally:
        db.chmod(0o600)
    assert not blocked["connected"] and blocked["problem"] == "blocked"
    assert blocked["last_read"] == readable["last_read"]  # what was read before still shows

    missing = by_id(connect.report(tmp_path, tmp_path / "nowhere.sqlite"))["whatsapp"]
    assert not missing["connected"] and missing["problem"] == "missing"


def test_a_download_counts_as_connected_once_read(tmp_path):
    month(tmp_path / "raw" / "linkedin" / "profile")
    sources = by_id(connect.report(tmp_path, store(tmp_path)))
    assert sources["linkedin"]["connected"] and sources["linkedin"]["last_read"].endswith("Z")
    assert not sources["twitter"]["connected"] and sources["twitter"]["last_read"] is None


def test_mail_no_gmail_account_reads_is_other_email(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_PERSONAL", "me@example.com:app-password")
    month(tmp_path / "raw" / "email" / "personal")
    sources = by_id(connect.report(tmp_path, store(tmp_path)))
    assert not sources["email"]["connected"]

    month(tmp_path / "raw" / "email" / "old-mbox")
    assert by_id(connect.report(tmp_path, store(tmp_path)))["email"]["connected"]


def test_settings_connect_live_sources_and_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_BLUESKY_HANDLE", "me.bsky.social")
    monkeypatch.setenv("PROXENOS_NAME", "Ada Lovelace")
    monkeypatch.setenv("PROXENOS_WEBSITE_REPO", str(tmp_path / "site"))
    sources = by_id(connect.report(tmp_path, store(tmp_path)))
    assert sources["bluesky"]["connected"] and sources["bluesky"]["detail"] == "me.bsky.social"
    assert sources["mentions"]["connected"] and sources["mentions"]["detail"] is None
    assert sources["website"]["connected"] and not sources["notes"]["connected"]


def test_strava_needs_its_app_and_a_token(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "1")
    assert not by_id(connect.report(tmp_path, store(tmp_path)))["strava"]["connected"]
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "strava_token.json").write_text("{}")
    assert by_id(connect.report(tmp_path, store(tmp_path)))["strava"]["connected"]


def test_the_command_prints_the_report_as_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    monkeypatch.setattr(whatsapp, "store_problem", lambda db: "missing")
    cli.main(["connect"])
    printed = json.loads(capsys.readouterr().out)
    assert by_id(printed)["whatsapp"]["problem"] == "missing"


def test_the_page_passes_the_account_after_a_double_dash(tmp_path, monkeypatch, capsys):
    # The page runs `proxenos auth gmail -- NAME ADDRESS`, so an address can't pass for an option.
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path))
    seen = []
    monkeypatch.setattr(auth, "gmail", lambda *args: seen.append(args[:2]) or "saved")
    cli.main(["auth", "gmail", "--", "personal", "-me@example.com"])
    assert seen == [("personal", "-me@example.com")]
    assert capsys.readouterr().out.strip() == "saved"
