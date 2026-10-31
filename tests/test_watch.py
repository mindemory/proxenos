"""Watch clone on a synthetic vault with the model faked out. No network, no real data."""

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest

from proxenos import cli, llm
from proxenos.clones import watch

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records) + '{"torn": \n')


def film(title, year, ts, **kw):
    return {"id": f"{title}-{ts}", "ts": f"{ts}T00:00:00Z", "title": title, "year": year} | kw


def make_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "self").mkdir(parents=True)
    (vault / "self" / "taste.md").write_text("Slow, quiet films; war stories told small.")
    lb = vault / "raw" / "letterboxd"
    write_jsonl(
        lb / "watched" / "2025-01.jsonl",
        [film("Old Favourite", 1997, "2025-01-02"), film("Meh Film", 2010, "2025-01-03")],
    )
    write_jsonl(
        lb / "ratings" / "2025-01.jsonl", [film("Meh Film", 2010, "2025-01-03", rating=1.5)]
    )
    write_jsonl(lb / "likes" / "2025-01.jsonl", [film("Old Favourite", 1997, "2025-01-02")])
    # Logged since the export, from the public feed: the newest rating wins.
    write_jsonl(
        lb / "feed" / "2026-03.jsonl",
        [
            film("Quiet War", 2017, "2026-03-03", rating=5.0, liked=True),
            film("Meh Film", 2010, "2026-03-02", rating=2.0, liked=False),
        ],
    )
    write_jsonl(
        lb / "watchlist" / "2025-02.jsonl",
        [
            film("Long Wait", 1957, "2025-02-01", url="https://boxd.it/w1"),
            film("Quiet War", 2017, "2025-02-02"),  # seen since: off the list
        ],
    )
    return vault


class Model:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, prompt, *, system=None, schema=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return self.answer


def pick(title, year, why="It fits.", because=("F1",)):
    return {"title": title, "year": year, "why": why, "because": list(because)}


ANSWER = {
    "films": [
        pick("Old Favourite", 1997),  # seen
        pick("Quiet War", 2018),  # seen, the year off by one
        pick("Long Wait", 1957),  # already on their watchlist
        pick("New  Find", 2004, because=["F1", "W1", "F99"]),
        pick("New Find", 2004),  # again
        pick("Second Find", 1983, because=[]),
    ],
    "shows": [pick("A Long Show", 2019), pick("Short Show", 2021)],
    "watchlist": [{"ref": "W1", "why": "This week."}, {"ref": "W9", "why": "No such film."}],
}


def test_picks_skip_what_was_seen_and_link_to_where_it_streams(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    model = Model(ANSWER)
    monkeypatch.setattr(llm, "ask", model)
    monkeypatch.setenv("PROXENOS_NAME", "Tess")

    stats = watch.watch(vault, now=NOW)

    assert stats == {"films_seen": 3, "films": 2, "shows": 2, "from_watchlist": 1}
    out = json.loads((vault / "clones" / "watch" / "2026-03-10.json").read_text())
    new, second = out["films"]
    assert (new["title"], new["year"], new["kind"]) == ("New Find", 2004, "film")
    # Only the films they've seen are cited, as they rated them.
    assert new["because"] == ["Quiet War (2017), 5/5, hearted"] and second["because"] == []
    assert new["links"] == [
        {"label": "Letterboxd", "url": "https://letterboxd.com/search/films/New%20Find/"},
        {"label": "Where to watch", "url": "https://www.justwatch.com/us/search?q=New+Find"},
    ]
    assert [s["title"] for s in out["shows"]] == ["A Long Show", "Short Show"]
    assert [link["label"] for link in out["shows"][0]["links"]] == ["Where to watch"]
    (queued,) = out["watchlist"]
    assert (queued["title"], queued["links"][0]["url"]) == ("Long Wait", "https://boxd.it/w1")

    [call] = model.calls
    prompt = call["prompt"]
    assert "Slow, quiet films" in prompt and "Tess" in call["system"]
    assert "[F1] Quiet War (2017), 5/5, hearted" in prompt  # watched lately, and loved
    assert "Meh Film (2010), 2/5" in prompt.split("## Disliked")[1]
    assert "Old Favourite (1997); Quiet War (2017)" in prompt.split("suggest none of these")[1]
    queue = prompt.split("## Their watchlist")[1].split("##")[0]
    assert "[W1] Long Wait (1957)" in queue and "Quiet War" not in queue  # seen since
    enum = call["schema"]["properties"]["watchlist"]["items"]["properties"]["ref"]["enum"]
    assert enum == ["W1"]

    history = json.loads((vault / "clones" / "watch" / "history.json").read_text())
    assert {h["title"] for h in history.values()} == {
        "New Find",
        "Second Find",
        "A Long Show",
        "Short Show",
        "Long Wait",
    }


def test_marks_teach_the_next_week_and_closed_picks_never_come_back(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(llm, "ask", Model(ANSWER))
    watch.watch(vault, now=NOW)
    assert watch.watch(vault, now=NOW + timedelta(days=2)) == {"days_until_next_run": 5}

    later = NOW + timedelta(days=7)
    marks = [
        (watch.key("film", "New Find", 2004), "seen"),
        (watch.key("show", "A Long Show", 2019), "not_me"),
        (watch.key("show", "Short Show", 2021), "want"),
        ("nonsense", "loved"),
    ]
    write_jsonl(
        vault / "clones" / "watch" / "feedback.jsonl",
        [{"item_id": i, "action": a, "ts": "2026-03-12T10:00:00Z"} for i, a in marks],
    )
    again = dict(ANSWER, shows=[pick("A long show", 2019), pick("Short Show", 2021)])
    model = Model(again)
    monkeypatch.setattr(llm, "ask", model)

    assert watch.watch(vault, now=later)["films"] == 1
    out = json.loads((vault / "clones" / "watch" / "2026-03-17.json").read_text())
    assert [f["title"] for f in out["films"]] == ["Second Find"]
    assert [s["title"] for s in out["shows"]] == ["Short Show"]  # wanted: may come again
    prompt = model.calls[0]["prompt"]
    assert "[S1] A Long Show (2019): not_me" in prompt and "[S2] Short Show (2021): want" in prompt
    assert "- film: New Find (2004): seen" in prompt


def test_no_films_logged_says_how_to_bring_them_in(tmp_path):
    with pytest.raises(SystemExit, match="PROXENOS_LETTERBOXD_USER"):
        watch.watch(tmp_path / "vault", now=NOW)


def test_the_command_runs_it_and_the_night_job_includes_it(tmp_path, monkeypatch):
    vault = make_vault(tmp_path)
    monkeypatch.setattr(llm, "ask", Model({"films": [], "shows": [], "watchlist": []}))
    assert watch.run(vault, argparse.Namespace(force=True))["films_seen"] == 3
    assert "watch" in cli.NIGHT_CLONES
