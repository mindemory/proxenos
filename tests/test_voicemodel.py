"""The voice model's training set, training command and evaluation, on a synthetic vault with
mlx-lm and every model faked out. No network, no real data."""

import json
import stat
from datetime import UTC, datetime
from itertools import pairwise

import pytest

from proxenos import chats, cli, voicemodel

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def person(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")


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


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def make_vault(tmp_path, dana_answered=True):
    vault = tmp_path / "vault"
    dana = [
        wa("dana", "Dana", "2026-03-09T09:00:00Z", "hey dana", mine=True),
        wa("dana", "Dana", "2026-03-09T10:00:00Z", "how was the talk?"),
    ]
    if dana_answered:
        dana.append(wa("dana", "Dana", "2026-03-09T10:02:00Z", "went well!", mine=True))
    write_jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("asha", "Asha", "2026-02-20T09:00:00Z", "coming? https://example.org/p?id=12345678"),
            wa("asha", "Asha", "2026-02-20T09:05:00Z", "yaa coming", mine=True),
            wa("asha", "Asha", "2026-02-20T09:06:00Z", "see you there / bring snacks?", mine=True),
            wa("asha", "Asha", "2026-02-20T10:00:00Z", "much later, its own message", mine=True),
            wa("asha", "Asha", "2026-02-21T09:00:00Z", "ok"),
            wa("asha", "Asha", "2026-02-21T09:01:00Z", "👍", mine=True),
            wa("ben", "Ben", "2019-01-05T08:00:00Z", "an old question?"),
            wa("ben", "Ben", "2019-01-05T08:10:00Z", "an old answer", mine=True),
            wa("ben", "Ben", "2026-03-05T08:00:00Z", "can you send the slides?"),
            wa("ben", "Ben", "2026-03-05T08:10:00Z", "sending now", mine=True),
            wa("lab", "Lab", "2026-03-04T12:00:00Z", "anyone up for lunch today?", kind="group"),
            wa("lab", "Lab", "2026-03-04T12:01:00Z", "me!", mine=True),
            *dana,
        ],
    )
    write_jsonl(
        vault / "raw" / "email" / "personal" / "2026-02.jsonl",
        [
            {
                "id": "e1",
                "ts": "2026-02-10T10:00:00Z",
                "from_me": True,
                "subject": "Lunch next week",
                "to": ["Erin Example <erin@example.com>"],
                "body_new": "Hi Erin,\n\nAre you free for lunch next week?\n\nBest,\nTess",
                "gmail_thread": "t1",
            },
            {
                "id": "e2",
                "ts": "2026-02-11T10:00:00Z",
                "from_me": True,
                "subject": "Re: Lunch next week",
                "to": ["Erin Example <erin@example.com>"],
                "body_new": "Thursday works for me then",
                "gmail_thread": "t1",
            },
        ],
    )
    export = vault / "exports" / "Basic_LinkedInDataExport"
    export.mkdir(parents=True)
    (export / "Shares_123.csv").write_text(
        "Date,ShareLink,ShareCommentary,SharedUrl,MediaUrl,Visibility\n"
        "2026-01-15 10:00:00,https://www.linkedin.com/feed/update/urn:li:share:111,"
        '"Thrilled to share\nour paper",https://doi.org/10.1/x,,MEMBERS\n'
    )
    return vault


def examples(vault):
    data = vault / "voice" / "data"
    return read_jsonl(data / "train.jsonl") + read_jsonl(data / "valid.jsonl")


def test_the_set_is_each_answer_with_its_chat_then_emails_and_posts(tmp_path):
    vault = make_vault(tmp_path)

    stats = voicemodel.build(vault, now=NOW)

    assert stats == {
        "conversations": 3,
        "answers": 3,
        "emails": 1,
        "posts": 1,
        "train": stats["train"],
        "valid": 4 - stats["train"],
        "held_out": 1,
    }
    by_answer = {e["messages"][2]["content"]: e["messages"] for e in examples(vault)}
    asha = by_answer["yaa coming\nsee you there\nbring snacks?"]  # one burst, its lines as lines
    assert asha[0]["content"].startswith("You are Tess. Write Tess's next message")
    assert asha[1]["content"] == (
        "WhatsApp, with Asha:\n[2026-02-20 09:00] Asha: coming? [link: example.org]"
    )
    assert by_answer["sending now"][1]["content"].endswith("Ben: can you send the slides?")
    email = by_answer["Hi Erin,\n\nAre you free for lunch next week?\n\nBest,\nTess"]
    assert email[1]["content"] == "A new email to Erin Example. Subject: Lunch next week"
    post = by_answer["Thrilled to share\nour paper"]
    assert post[1]["content"] == "A LinkedIn post. Sharing a link: [link: doi.org]"
    # Nothing said to answer, a group chat, an email reply with no one's words before it,
    # more than five years ago, and the held-out chat: none of them are trained on.
    for text in ("👍", "me!", "Thursday works", "an old answer", "much later", "went well"):
        assert not any(text in answer for answer in by_answer)


def test_the_newest_conversations_are_held_out_for_evaluation(tmp_path):
    vault = make_vault(tmp_path)
    voicemodel.build(vault, now=NOW)

    (point,) = read_jsonl(vault / "voice" / "eval.jsonl")
    assert (point["conversation"], point["sent"], point["own"]) == (
        "whatsapp/dana",
        "went well!",
        ["hey dana"],
    )
    (test,) = read_jsonl(vault / "voice" / "data" / "test.jsonl")
    assert test["messages"][2]["content"] == "went well!"


def test_the_set_is_readable_only_by_you(tmp_path):
    vault = make_vault(tmp_path)
    voicemodel.build(vault, now=NOW)

    assert stat.S_IMODE((vault / "voice").stat().st_mode) == 0o700
    for path in (vault / "voice").rglob("*.jsonl"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_draft_is_asked_for_just_as_training_saw_it(tmp_path):
    waiting_vault = make_vault(tmp_path / "before", dana_answered=False)
    (chat,) = [c for c in chats.waiting(waiting_vault, NOW) if c["chat"] == "dana"]
    asked = voicemodel.prompt(chat, "Tess")

    answered = make_vault(tmp_path / "after")
    voicemodel.build(answered, now=NOW)
    (point,) = read_jsonl(answered / "voice" / "eval.jsonl")
    assert voicemodel.prompt(point, "Tess") == asked
    assert asked == (
        "WhatsApp, with Dana:\n[2026-03-09 09:00] Tess: hey dana\n"
        "[2026-03-09 10:00] Dana: how was the talk?"
    )


def test_a_long_chat_shows_only_its_newest_lines():
    lines = [
        {"ts": f"2026-03-09T10:{i:02d}:00Z", "mine": False, "sender": "Ann", "text": "x" * 500}
        for i in range(20)
    ]
    shown = voicemodel.prompt({"source": "slack", "name": "#lab", "waiting": lines}, "Tess")
    assert shown.startswith("Slack, with #lab:\n")
    assert shown.count("Ann: ") == 5 and shown.endswith("[2026-03-09 10:19] Ann: " + "x" * 500)


def test_what_the_model_writes_is_cleaned_of_thinking_and_a_copied_label():
    assert voicemodel.clean("<think>hmm</think>\n[2026-03-09 10:05] Tess: went well!", "Tess") == (
        "went well!"
    )
    assert voicemodel.clean("Tess: sure\nsee you", "Tess") == "sure\nsee you"
    assert voicemodel.clean("Re the talk: it went well", "Tess") == "Re the talk: it went well"


def test_training_runs_mlx_lm_on_the_set_into_the_vault(tmp_path):
    vault = make_vault(tmp_path)
    with pytest.raises(SystemExit, match="voice build"):
        voicemodel.train(vault, run=lambda *a, **k: pytest.fail("trained with no set"))
    voicemodel.build(vault, now=NOW)
    ran = []

    def fake_run(command, **kwargs):
        ran.append(command)
        (vault / "voice" / "adapter" / "adapters.safetensors").write_bytes(b"weights")
        return type("Done", (), {"returncode": 0})()

    assert voicemodel.trained(vault) is None
    voicemodel.train(vault, base="some/model-4bit", iters=10, run=fake_run)

    (command,) = ran
    assert command[1:4] == ["-m", "mlx_lm", "lora"]
    flags = {flag: value for flag, value in pairwise(command) if flag.startswith("--")}
    assert flags["--model"] == "some/model-4bit" and flags["--iters"] == "10"
    assert flags["--data"] == str(vault / "voice" / "data")
    assert flags["--adapter-path"] == str(vault / "voice" / "adapter")
    assert "--mask-prompt" in command
    assert voicemodel.trained(vault)["base"] == "some/model-4bit"


def test_the_evaluation_scores_each_model_against_what_was_sent(tmp_path):
    vault = make_vault(tmp_path)
    voicemodel.build(vault, now=NOW)
    drafters = {
        "base": lambda points: ["It went quite well, thank you for asking." for _ in points],
        "tuned": lambda points: [p["sent"] for p in points],
    }

    result = voicemodel.evaluate(vault, n=5, models=("base", "tuned"), drafters=drafters)

    assert result["n"] == 1 and result["by_source"] == {"whatsapp": 1}
    summary = result["summary"]
    assert summary["tuned"]["mean"] == 1.0
    assert summary["base"]["mean"] < summary["tuned"]["mean"]
    assert summary["last message again"]["words"] == 2  # "hey dana", the reference row
    saved = json.loads((vault / "voice" / "eval.json").read_text())
    assert saved["items"][0]["drafts"]["tuned"] == "went well!"
    assert stat.S_IMODE((vault / "voice" / "eval.json").stat().st_mode) == 0o600
    assert "| tuned | 1.00 | 1.00 | 2 |" in voicemodel.table(result)

    # Trained again: only the voice model drafts, and the base model's drafts are kept.
    drafters["base"] = lambda points: pytest.fail("drafted again")
    drafters["tuned"] = lambda points: ["went"]
    again = voicemodel.evaluate(vault, n=5, models=("tuned",), drafters=drafters)
    assert again["summary"]["base"] == summary["base"]
    assert again["summary"]["tuned"]["mean"] < 1.0


def test_the_command_builds_the_set(tmp_path, monkeypatch, capsys):
    vault = make_vault(tmp_path)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    monkeypatch.setattr(
        voicemodel, "datetime", type("Frozen", (datetime,), {"now": lambda tz=None: NOW})
    )

    cli.main(["voice", "build"])

    assert capsys.readouterr().out.startswith("voice: 3 conversations, 3 answers, 1 emails")
