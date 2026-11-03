"""The blind comparison of drafting models, on a synthetic vault with every model faked out. No
network, no model, no real data."""

import json
import os
import random
import stat
from datetime import UTC, datetime

import pytest

from proxenos import cli, compare, llm

NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
LOCAL, OTHER = "ollama:drafter", "ollama:other"
# What each fake model writes, which says nothing of which model it is.
WRITES = {LOCAL: "sure, on it", OTHER: "Certainly, I will do that.", "mlx": "hiya, yes"}


@pytest.fixture(autouse=True)
def person(monkeypatch):
    monkeypatch.setenv("PROXENOS_NAME", "Tess")
    monkeypatch.setenv("PROXENOS_MODEL", LOCAL)


def wa(chat, name, ts, text, mine=False):
    return {
        "id": f"{chat}/{ts}",
        "ts": ts,
        "chat_id": chat,
        "chat_name": name,
        "chat_type": "direct",
        "from_me": mine,
        "sender_name": None if mine else name,
        "text": text,
    }


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    write_jsonl(
        vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl",
        [
            wa("ana", "Ana", "2026-03-01T09:00:00Z", "hey ana, long time", mine=True),
            wa("ana", "Ana", "2026-03-01T10:00:00Z", "are you coming to the picnic on sunday?"),
            wa("ana", "Ana", "2026-03-01T10:05:00Z", "yes!! bringing the lemon cake", mine=True),
            wa("ana", "Ana", "2026-03-01T10:06:00Z", "see you there", mine=True),
            # After the reply in the same chat: an "ok" no draft would answer, then more of hers.
            wa("ana", "Ana", "2026-03-02T09:00:00Z", "ok"),
            wa("ana", "Ana", "2026-03-02T09:05:00Z", "AFTERWORD the cake was a hit", mine=True),
            wa("ben", "Ben", "2026-03-04T09:00:00Z", "hi ben, quick one", mine=True),
            wa("ben", "Ben", "2026-03-04T10:00:00Z", "can you send the slides tonight?"),
            wa("ben", "Ben", "2026-03-04T10:10:00Z", "LATER sending them in an hour", mine=True),
        ],
    )
    drafts = vault / "clones" / "drafts"
    drafts.mkdir(parents=True)
    changed = {"source": "whatsapp", "to": "Ana", "closeness": 0.2}
    (drafts / "fidelity.json").write_text(
        json.dumps(
            {
                "drafts": [
                    # A draft of this very reply that the user changed: what they sent is the
                    # reply held out, so it must never be shown.
                    changed
                    | {
                        "sent": "2026-03-01T10:05:00Z",
                        "draft_text": "LATE draft of the picnic reply",
                        "sent_text": "yes!! bringing the lemon cake",
                    },
                    changed
                    | {
                        "sent": "2026-02-20T10:00:00Z",
                        "draft_text": "EARLY draft, very formal",
                        "sent_text": "early words as sent",
                    },
                ]
            }
        )
    )
    # Something put out, and a "right now" note, both after Ana's reply.
    (drafts / "post-1.md").write_text(
        '---\nid: post-1\ntitle: "A post"\nkind: doc\nfor: project\nchannel: other\nto: ""\n'
        "created: 2026-03-02T08:00:00Z\nstatus: sent\n---\n\nLATE POST about cakes\n"
    )
    told = vault / "state" / "told.jsonl"
    told.parent.mkdir(parents=True)
    (vault / "state" / "now.jsonl").write_text(
        json.dumps({"at": "2026-03-01T11:00:00Z", "text": "LATE MOOD"}) + "\n"
    )
    told.write_text(
        json.dumps({"at": "2026-03-01T08:00:00Z", "text": "EARLY NOTE: busy week"})
        + "\n"
        + json.dumps({"at": "2026-03-03T08:00:00Z", "text": "LATE NOTE: the cake went well"})
        + "\n"
    )
    return vault


def many_chats(tmp_path, n):
    vault = tmp_path / "vault"
    records = []
    for i in range(n):
        day = f"2026-03-{1 + i % 18:02d}"
        chat, name = f"c{i}", f"Friend {i}"
        records += [
            wa(chat, name, f"{day}T08:{i:02d}:00Z", f"hello friend number {i}", mine=True),
            wa(chat, name, f"{day}T09:{i:02d}:00Z", f"question number {i}?"),
            wa(chat, name, f"{day}T10:{i:02d}:00Z", f"my answer number {i}", mine=True),
        ]
    write_jsonl(vault / "raw" / "whatsapp" / "messages" / "2026-03.jsonl", records)
    return vault


class Models:
    """Every model call, faked: each model writes what WRITES says. Each call is kept with its
    model, prompt and system prompt."""

    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(llm, "_ask", self.ask)
        monkeypatch.setattr(llm, "_ask_voice", self.voice)

    def ask(self, model, prompt, system, schema, effort, max_tokens, images, keep=()):
        self.calls.append({"model": model, "prompt": prompt, "system": system})
        body = WRITES[model]
        return {"title": "Reply", "kind": "reply", "channel": "whatsapp", "to": "", "body": body}

    def voice(self, model, prompt, system, max_tokens):
        self.calls.append({"model": f"voice:{model}", "prompt": prompt, "system": system})
        return WRITES[model]


@pytest.fixture
def models(monkeypatch):
    return Models(monkeypatch)


def test_a_reply_is_drafted_without_seeing_itself_or_anything_after_it(tmp_path, models):
    vault = make_vault(tmp_path)

    shown = compare.start(vault, OTHER, n=10, now=NOW, rng=random.Random(1))

    assert [item["name"] for item in shown["items"]] == ["Ben", "Ana"]  # newest reply first
    ana = [c for c in models.calls if "Chat: Ana" in c["prompt"]]
    assert {c["model"] for c in ana} == {LOCAL, OTHER}  # both models, one draft each
    assert ana[0]["prompt"] == ana[1]["prompt"] and ana[0]["system"] == ana[1]["system"]
    prompt, system = ana[0]["prompt"], ana[0]["system"]
    assert "are you coming to the picnic on sunday?" in prompt  # the message answered
    assert "- hey ana, long time" in prompt  # their own earlier message in that chat
    assert "EARLY draft, very formal" in prompt  # a draft they changed before then
    replied = datetime(2026, 3, 1, 10, 5, tzinfo=UTC).astimezone()
    assert f"Today is {replied:%A %Y-%m-%d}." in prompt  # drafted as of when they replied
    for later in ("lemon cake", "see you there", "AFTERWORD", "LATER sending", "LATE draft"):
        assert later not in prompt and later not in system
    assert "EARLY NOTE" in system and "LATE NOTE" not in system
    assert "LATE MOOD" not in system and "LATE POST" not in system
    # Ben's reply came after both notes and Ana's chat, so it may see them.
    ben = next(c for c in models.calls if "Chat: Ben" in c["prompt"])
    assert "LATE NOTE" in ben["system"] and "LATE POST" in ben["system"]
    assert "LATER sending" not in ben["prompt"]


def test_what_was_sent_is_the_burst_of_the_users_messages(tmp_path, models):
    vault = make_vault(tmp_path)
    compare.start(vault, OTHER, now=NOW, rng=random.Random(1))

    (path,) = (vault / "state" / "compare").glob("*.json")
    ana = json.loads(path.read_text())["items"][1]
    assert ana["sent"] == ["yes!! bringing the lemon cake", "see you there"]
    assert [m["text"] for m in ana["waiting"]] == ["are you coming to the picnic on sunday?"]
    assert [m["text"] for m in ana["recent"]] == ["hey ana, long time"]


def test_the_order_is_drawn_for_each_reply_and_both_labels_are_kept(tmp_path, models):
    vault = many_chats(tmp_path, 18)

    compare.start(vault, OTHER, n=18, now=NOW, rng=random.Random(7))

    (path,) = (vault / "state" / "compare").glob("*.json")
    doc = json.loads(path.read_text())
    orders = {(i["drafts"]["A"]["model"], i["drafts"]["B"]["model"]) for i in doc["items"]}
    assert orders == {(OTHER, LOCAL), (LOCAL, OTHER)}  # both orders happen
    for item in doc["items"]:
        for side in ("A", "B"):  # each side's text is the one its model wrote
            draft = item["drafts"][side]
            assert draft["text"] == WRITES[draft["model"]]
            assert 0 <= draft["closeness"] <= 1
    assert doc["models"] == [OTHER, LOCAL] and doc["status"] == "ready"


def test_each_model_drafts_all_its_replies_before_the_other(tmp_path, models):
    vault = many_chats(tmp_path, 4)

    compare.start(vault, OTHER, n=4, now=NOW, rng=random.Random(3))

    assert [c["model"] for c in models.calls] == [OTHER] * 4 + [LOCAL] * 4


def test_the_drafts_stay_blind_until_picked_and_a_pick_can_change(tmp_path, models):
    vault = many_chats(tmp_path, 3)
    shown = compare.start(vault, OTHER, n=3, now=NOW, rng=random.Random(2))
    round_id = shown["round"]["id"]

    for item in shown["items"]:
        assert item["state"] == "ready" and item["a"] and item["b"] and item["pick"] is None
        assert not {"a_model", "b_model", "sent", "a_closeness"} & set(item)
    shown_json = json.dumps(shown["items"])  # nothing says which model wrote which
    assert "drafter" not in shown_json and "other" not in shown_json

    shown = compare.pick(vault, round_id, 1, "a", now=NOW)
    first = shown["items"][0]
    assert first["pick"] == "A" and first["picked"] == "2026-03-20T12:00:00Z"
    assert {first["a_model"], first["b_model"]} == {"other", "drafter"}
    assert first["sent"].startswith("my answer number")
    assert "a_model" not in shown["items"][1]  # the others stay blind

    picks = vault / "state" / "compare" / f"{round_id}.picks.jsonl"
    compare.pick(vault, round_id, 1, "A", now=NOW)  # the same pick again changes nothing
    assert len(picks.read_text().splitlines()) == 1
    shown = compare.pick(vault, round_id, 1, "neither", now=NOW)
    assert shown["items"][0]["pick"] == "neither"  # the latest counts
    assert shown["results"]["picks"] == 1 and shown["results"]["neither"] == 1

    with pytest.raises(SystemExit, match="Pick A, B"):
        compare.pick(vault, round_id, 1, "C")
    with pytest.raises(SystemExit, match="no reply 9"):
        compare.pick(vault, round_id, 9, "A")
    with pytest.raises(SystemExit, match="no round"):
        compare.pick(vault, "../elsewhere", 1, "A")


def test_the_results_count_wins_with_wilson_intervals(tmp_path, models):
    vault = many_chats(tmp_path, 4)
    shown = compare.start(vault, OTHER, n=4, now=NOW, rng=random.Random(5))
    round_id = shown["round"]["id"]
    # The draft by OTHER, wherever it was, wins three; the fourth is both fine.
    for item in shown["items"][:3]:
        side = "A" if _model_of(vault, round_id, item["n"], "A") == OTHER else "B"
        compare.pick(vault, round_id, item["n"], side)
    compare.pick(vault, round_id, 4, "both")

    results = compare.results(vault)["results"]

    other, drafter = results["models"]
    assert (results["picks"], results["both"], results["neither"]) == (4, 1, 0)
    assert (other["name"], other["won"], other["share"]) == (OTHER, 3, 0.75)
    assert (drafter["name"], drafter["won"], drafter["share"]) == (LOCAL, 0, 0.0)
    assert (other["low"], other["high"]) == compare.wilson(3, 4)
    assert other["where"] == "this computer" and other["drafted"] == 4 and other["failed"] == 0
    assert 0 <= other["closeness"] <= 1
    assert "Under about 20" in results["note"]


def test_wilson_intervals():
    assert compare.wilson(5, 10) == (0.237, 0.763)
    assert compare.wilson(0, 10) == (0.0, 0.278)
    assert compare.wilson(10, 10) == (0.722, 1.0)
    assert compare.wilson(0, 0) == (None, None)
    low, high = compare.wilson(30, 40)
    assert low < 0.75 < high and high - low < compare.wilson(3, 4)[1] - compare.wilson(3, 4)[0]


def test_the_results_as_json_for_the_page(tmp_path, models, monkeypatch, capsys):
    vault = many_chats(tmp_path, 2)
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))

    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "mlx")
    cli.main(["compare", "results"])
    assert json.loads(capsys.readouterr().out) == {
        "round": None,
        "rounds": [],
        "results": None,
        "pooled": None,
        "items": [],
        "set_up": {
            "drafting": LOCAL,
            "hosted": llm.DEFAULT_MODEL,
            "key": False,
            "voice": "voice:mlx",
        },
    }

    cli.main(["compare", "start", "--model", OTHER, "-n", "2"])
    shown = json.loads(capsys.readouterr().out)
    assert set(shown) == {"round", "rounds", "results", "pooled", "items", "set_up"}
    assert shown["round"] | {"id": "", "started": "", "updated": ""} == {
        "id": "",
        "started": "",
        "updated": "",
        "status": "ready",
        "error": None,
        "models": [
            {"name": OTHER, "label": "other", "where": "this computer"},
            {"name": LOCAL, "label": "drafter", "where": "this computer"},
        ],
        "n": 2,
        "drafted": 4,
    }
    assert shown["rounds"][0]["models"] == ["other", "drafter"]
    assert set(shown["items"][0]) == {
        *("n", "source", "name", "replied", "recent", "waiting", "state", "a", "b"),
        *("pick", "picked"),
    }

    cli.main(["compare", "pick", shown["round"]["id"], "2", "B"])
    picked = json.loads(capsys.readouterr().out)["items"][1]
    assert picked["pick"] == "B" and picked["b_model"] in ("other", "drafter")
    assert isinstance(picked["a_closeness"], float)


def test_a_round_is_private_and_logged_as_compare(tmp_path, models, monkeypatch):
    vault = many_chats(tmp_path, 2)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setattr(llm, "_calls_path", lambda: log)

    shown = compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))
    compare.pick(vault, shown["round"]["id"], 1, "A")

    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert {c["step"] for c in calls} == {"compare"}
    assert {c["model"] for c in calls} == {LOCAL, OTHER}
    if os.name == "nt":
        return
    folder = vault / "state" / "compare"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for path in folder.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_voice_model_drafts_from_the_same_chat(tmp_path, models, monkeypatch):
    vault = many_chats(tmp_path, 1)

    shown = compare.start(vault, "voice:mlx", n=1, now=NOW, rng=random.Random(1))

    voiced = [c for c in models.calls if c["model"] == "voice:mlx"]
    assert len(voiced) == 1 and "question number 0?" in voiced[0]["prompt"]
    item = shown["items"][0]
    assert {item["a"], item["b"]} == {WRITES["mlx"], WRITES[LOCAL]}
    labels = [m["label"] for m in shown["round"]["models"]]
    assert labels == ["voice model mlx", "drafter"]


def test_a_failed_draft_costs_only_itself_and_says_nothing_of_who(tmp_path, models, monkeypatch):
    vault = many_chats(tmp_path, 2)
    asked = models.ask

    def flaky(model, prompt, system, *rest, **kw):
        if model == OTHER and "Friend 1" in prompt:
            raise llm.ModelError("local model other: out of memory")
        return asked(model, prompt, system, *rest, **kw)

    monkeypatch.setattr(llm, "_ask", flaky)

    shown = compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))

    states = {item["name"]: item for item in shown["items"]}
    assert states["Friend 1"]["state"] == "failed" and states["Friend 1"]["a"] is None
    assert "out of memory" not in json.dumps(shown["items"])
    assert states["Friend 0"]["state"] == "ready"
    assert shown["results"]["models"][0]["failed"] == 1
    with pytest.raises(SystemExit, match="both drafts"):
        compare.pick(vault, shown["round"]["id"], states["Friend 1"]["n"], "A")


def test_a_new_round_of_the_same_two_takes_other_replies_and_they_add_up(tmp_path, models):
    vault = many_chats(tmp_path, 4)
    first = compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))
    second = compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))

    names = [i["name"] for i in first["items"]] + [i["name"] for i in second["items"]]
    assert len(set(names)) == 4  # no reply drafted twice
    assert second["round"]["id"] != first["round"]["id"]
    for shown in (first, second):
        compare.pick(vault, shown["round"]["id"], 1, "both")
    pooled = compare.results(vault)["pooled"]
    assert pooled["rounds"] == 2 and pooled["picks"] == 2
    with pytest.raises(SystemExit, match="drafted all of them"):
        compare.start(vault, OTHER, n=2, now=NOW)


def test_models_are_named_as_the_settings_take_them(monkeypatch):
    assert compare.model("ollama:gemma4:26b") == "ollama:gemma4:26b"
    assert compare.model("claude-opus-5-5") == "claude-opus-5-5"
    assert compare.model("voice:mlx:8899") == "voice:mlx:8899"
    for bad in ("two words", "voice:nope", "", "x" * 201):
        with pytest.raises(ValueError):
            compare.model(bad)
    with pytest.raises(ValueError, match="No voice model"):
        compare.model("voice")
    monkeypatch.setenv("PROXENOS_VOICE_MODEL", "ollama:me")
    assert compare.model("voice") == "voice:ollama:me"


def test_a_hosted_model_needs_a_key_and_two_models_must_differ(tmp_path, models):
    vault = many_chats(tmp_path, 1)
    with pytest.raises(SystemExit, match="no Anthropic API key"):
        compare.start(vault, "claude-opus-5-5", now=NOW)
    with pytest.raises(ValueError, match="Both are"):
        compare.start(vault, LOCAL, now=NOW)
    assert models.calls == [] and not (vault / "state" / "compare").exists()


def test_a_round_stopped_partway_says_so_and_frees_its_replies(tmp_path, models, monkeypatch):
    vault = many_chats(tmp_path, 2)
    asked = models.ask

    def stopped(model, *rest, **kw):
        if model == LOCAL:
            raise KeyboardInterrupt
        return asked(model, *rest, **kw)

    monkeypatch.setattr(llm, "_ask", stopped)
    with pytest.raises(KeyboardInterrupt):
        compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))

    shown = compare.results(vault)
    assert shown["round"]["status"] == "failed" and shown["round"]["error"] == "It was stopped."
    assert shown["round"]["drafted"] == 2 and {i["state"] for i in shown["items"]} == {"drafting"}
    monkeypatch.setattr(llm, "_ask", asked)
    again = compare.start(vault, OTHER, n=2, now=NOW, rng=random.Random(1))
    assert [i["name"] for i in again["items"]] == [i["name"] for i in shown["items"]]


def _model_of(vault, round_id, n, side):
    doc = json.loads((vault / "state" / "compare" / f"{round_id}.json").read_text())
    return next(i for i in doc["items"] if i["n"] == n)["drafts"][side]["model"]


def test_models_served_by_another_local_app_run_on_this_computer():
    assert compare.model("local:qwen3-8b@q4_k_m") == "local:qwen3-8b@q4_k_m"
    assert compare.where("local:qwen3-8b") == "this computer"
    assert compare.where("voice:local:my-voice") == "this computer"
    assert compare.label("local:qwen3-8b") == "qwen3-8b"
    assert compare.label("voice:local:my-voice") == "voice model my-voice"
    assert compare.label("ollama:gemma4:26b") == "gemma4:26b"
