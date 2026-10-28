"""Observers and the master, on a synthetic vault with the model faked out."""

import json
import subprocess
from types import SimpleNamespace

from proxenos import llm, master, observe


def write_month(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def chat(ts, from_me, text, chat_name="Asha"):
    return {
        "id": f"c/{ts}",
        "ts": ts,
        "chat_name": chat_name,
        "chat_type": "direct",
        "from_me": from_me,
        "text": text,
        "caption": None,
    }


def slack_msg(ts, from_me, text):
    return {
        "id": f"s/{ts}",
        "ts": ts,
        "channel_name": "lab",
        "is_reply": False,
        "from_me": from_me,
        "text": text,
    }


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    mine = "thinking about working memory models again " * 20
    write_month(
        vault / "raw/whatsapp/messages/2025-01.jsonl",
        [chat("2025-01-03T10:00:00Z", True, mine), chat("2025-01-03T10:01:00Z", False, "SECRET")],
    )
    write_month(
        vault / "raw/whatsapp/messages/2025-02.jsonl", [chat("2025-02-01T09:00:00Z", True, "ok")]
    )
    write_month(
        vault / "raw/slack/acme/messages/2025-01.jsonl",
        [slack_msg("2025-01-05T15:00:00Z", True, mine)],
    )
    return vault


def fake_llm(monkeypatch, answer):
    calls = []

    def ask(prompt, **kwargs):
        calls.append(SimpleNamespace(prompt=prompt, **kwargs))
        return answer(prompt, kwargs) if callable(answer) else answer

    monkeypatch.setattr("proxenos.llm.ask", ask)
    return calls


def test_observers_see_only_my_side_and_skip_thin_months(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    assert [name for name, _ in observe.streams(vault)] == ["slack/acme", "whatsapp"]

    calls = fake_llm(monkeypatch, "## Focus\nworking memory")
    stats = observe.observe(vault)
    assert (stats["observed"], stats["too_little"]) == (2, 1)
    assert all("SECRET" not in c.prompt for c in calls)
    assert (
        (vault / "observations/whatsapp/2025-01.md").read_text().startswith("# whatsapp, 2025-01")
    )
    assert (vault / "observations/slack/acme/2025-01.md").exists()

    # Nothing changed, so nothing is redone.
    assert observe.observe(vault)["est_input_tokens"] == 0
    assert len(calls) == 2


def test_dry_run_counts_without_calling_the_model(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    calls = fake_llm(monkeypatch, "unused")
    stats = observe.observe(vault, dry_run=True)
    assert stats["would_observe"] == 2 and stats["est_input_tokens"] > 0
    assert calls == []


def model_answer(identity):
    def answer(prompt, kwargs):
        files = {name: f"{name} text" for name in master.SELF_FILES}
        return {**files, "identity": identity, "changelog": "- something"}

    return answer


def test_first_build_writes_everything_later_slow_changes_wait_for_approval(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    fake_llm(monkeypatch, "## Focus\nworking memory")
    observe.observe(vault)

    calls = fake_llm(monkeypatch, model_answer("a researcher"))
    assert master.consolidate(vault) == {"self_files_written": 6, "self_files_proposed": 0}
    assert (vault / "self/identity.md").read_text() == "a researcher\n"
    assert "working memory" in calls[0].prompt

    fake_llm(monkeypatch, model_answer("a researcher who runs"))
    assert master.consolidate(vault) == {"self_files_written": 0, "self_files_proposed": 1}
    assert (vault / "self/identity.md").read_text() == "a researcher\n"

    assert master.accept(vault) == {"accepted": 1}
    assert (vault / "self/identity.md").read_text() == "a researcher who runs\n"

    log = subprocess.run(
        ["git", "-C", str(vault), "log", "--format=%s"], capture_output=True, text=True, check=True
    )
    assert log.stdout.splitlines()[0] == "accept 1 proposal(s)"
    tracked = subprocess.run(
        ["git", "-C", str(vault), "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    assert "raw/" not in tracked and "self/identity.md" in tracked


def test_reactions_to_clone_picks_reach_the_master(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    fake_llm(monkeypatch, "## Focus\nworking memory")
    observe.observe(vault)
    write_month(
        vault / "tracker/items/2025-02.jsonl",
        [{"id": "i1", "ts": "2025-02-01T00:00:00Z", "title": "Crypto tips", "interest": "finance"}],
    )
    now = "2999-01-01T00:00:00Z"
    (vault / "tracker/feedback.jsonl").write_text(
        json.dumps({"item_id": "i1", "action": "not_me", "ts": now}) + "\n"
    )
    calls = fake_llm(monkeypatch, model_answer("a researcher"))
    master.consolidate(vault)
    assert "- not_me: Crypto tips [finance]" in calls[0].prompt


def test_a_broken_source_does_not_stop_the_run(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)

    def broken(vault, args):
        raise SystemExit("no token")

    monkeypatch.setattr(
        master,
        "_UNATTENDED",
        [
            (SimpleNamespace(run=broken), lambda: True),
            (SimpleNamespace(run=lambda v, a: {}), lambda: True),
        ],
    )
    fake_llm(
        monkeypatch,
        lambda prompt, kwargs: (
            model_answer("x")(prompt, kwargs) if "schema" in kwargs else "## Focus\nx"
        ),
    )
    stats = master.run(vault)
    assert (stats["sources_synced"], stats["sources_failed"]) == (1, 1)
    assert stats["self_files_written"] == 6


def test_spotify_and_website_sync_only_when_their_settings_are_set(monkeypatch):
    def synced():
        return {
            module.__name__.rsplit(".", 1)[-1]
            for module, configured in master._UNATTENDED
            if module in (master.spotify, master.website) and configured()
        }

    assert synced() == set()
    monkeypatch.setenv("PROXENOS_WEBSITE_REPO", "~/site")
    assert synced() == {"website"}
    monkeypatch.setenv("PROXENOS_SPOTIFY_EXPORT", "~/history")
    assert synced() == {"spotify", "website"}


def test_sync_drafts_new_replies_only_with_a_key(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(master, "_UNATTENDED", [])
    calls = []
    monkeypatch.setattr(master.work, "replies", lambda v: calls.append(v) or {"drafts_written": 2})

    assert "replies_drafted" not in master.sync(vault)
    assert calls == []

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert master.sync(vault)["replies_drafted"] == 2

    def broken(vault):
        raise llm.ModelError("model declined")

    monkeypatch.setattr(master.work, "replies", broken)
    stats = master.sync(vault)
    assert stats["replies_failed"] == 1
    assert "records_indexed" in stats  # the rest of the sync still ran
