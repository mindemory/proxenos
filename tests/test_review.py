"""Peer review in rounds, on a small paper made here, with the model, the scholarly indexes and the
step runner faked out. No real model, no network, no real data and no real repository."""

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from proxenos import agent, cli, llm, preprint, privacy, review
from proxenos.clones import projects, steps

NOW = datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
LATER = datetime(2026, 3, 20, 2, 0, tzinfo=UTC)
PAPER = """\
# When birds sing

## Abstract

Birds sang 12% earlier in warm weeks (Lee et al. (2020) saw the same).

## Methods

We counted songs with analysis.py.

## Results

Songs rose at dawn.
"""


def git(where, *args):
    return subprocess.run(
        ["git", "-C", str(where), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def write_list(vault, *items):
    path = vault / "clones" / "projects" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": list(items)}))


def make_repo(where: Path, files: dict) -> Path:
    where.mkdir()
    git(where, "init", "-q", "-b", "main")
    git(where, "config", "user.name", "Joe")
    git(where, "config", "user.email", "joe@example.org")
    for name, text in files.items():
        (where / name).parent.mkdir(parents=True, exist_ok=True)
        (where / name).write_text(text)
    git(where, "add", "-A")
    git(where, "commit", "-q", "-m", "First")
    return where


class Model:
    """The review model, faked: it answers by the shape it's asked for, as each reviewer, the
    author or the letter, and keeps every prompt it was given."""

    def __init__(self):
        self.prompts: list[tuple[str, str, str]] = []  # (who, system, prompt)

    def __call__(self, prompt, *, system=None, schema=None, effort="medium", max_tokens=0, **_):
        props = (schema or {}).get("properties", {})
        if "reviewers" in props:
            self.prompts.append(("editor", system, prompt))
            return {
                "field": "Ornithology",
                "kind": "an empirical study",
                "venue": "a journal of animal behaviour",
                "reviewers": [
                    {"lens": "birdsong", "expertise": "Songbirds.", "focus": "The claims."},
                    {"lens": "statistics", "expertise": "Models.", "focus": "The analysis."},
                    {"lens": "readers", "expertise": "The venue.", "focus": "Clarity."},
                ],
            }
        if "recommendation" in props:
            n = int(re.search(r"You are Reviewer (\d)", system)[1])
            again = re.search(r"This is round (\d)", system)
            k = int(again[1]) if again else 1
            self.prompts.append((f"R{n}.{k}", system, prompt))
            return self.review(n, k, prompt)
        if "items" in props:
            self.prompts.append(("plan", system, prompt))
            ids = re.findall(
                r"^- (R\d-[Mm]\d+) \(", prompt.split("Every concern")[-1], re.MULTILINE
            )
            items = []
            for cid in ids:
                if cid == "R2-m1":
                    continue  # one the plan leaves out
                action = "analysis" if cid == "R1-M1" else "decline" if cid == "R3-m1" else "text"
                items.append({"id": cid, "action": action, "change": f"Answer {cid}."})
            items.append({"id": "R9-M9", "action": "text", "change": "Not a concern."})
            return {"summary": "Agree with most.", "items": items}
        self.prompts.append(("letter", system, prompt))
        return (
            f"Thank you all.\n\n## Reviewer 1\n\n**R1-M1** done. MARK-LETTER-{len(self.prompts)}\n"
        )

    @staticmethod
    def review(n, k, prompt):
        mine = re.findall(rf"^- (R{n}-[Mm]\d+) \(", prompt, re.MULTILINE)
        if k == 1:
            return {
                "summary": f"MARK-R{n}-{k}. As Nobody et al. (2021) showed, and Lee et al. (2020).",
                "strengths": ["Clear question."],
                "major": [
                    {
                        "title": f"Weeks aren't independent ({n})",
                        "where": "Results, line 11",
                        "why": "Pseudo-replication.",
                        "request": "Model the weeks.",
                    }
                ],
                "minor": [{"title": "Typo", "where": "line 3", "why": "", "request": "Fix it."}],
                "questions": ["Which site?"],
                "literature": [
                    {
                        "title": "A Real Work on Song",
                        "authors": ["Ana Real"],
                        "year": 2019,
                        "doi": "",
                        "why": "It counts songs.",
                    },
                    {
                        "title": "A Work That Was Never Written",
                        "authors": ["Bo Ghost"],
                        "year": 2022,
                        "doi": "10.9999/ghost",
                        "why": "Made up.",
                    },
                ],
                "recommendation": "major revision",
                "score": 14,
                "confidence": 4,
                "checked": "analysis.py against Methods.",
                "earlier": [],
            }
        return {
            "summary": f"MARK-R{n}-{k}. Better.",
            "strengths": [],
            "major": [],
            "minor": [{"title": "One more", "where": "line 5", "why": "", "request": "Say n."}]
            if n == 3
            else [],
            "questions": [],
            "literature": [],
            "recommendation": "minor revision",
            "score": 8,
            "confidence": 4,
            "checked": "The revision.",
            "earlier": [{"id": cid, "status": "resolved", "said": "Done."} for cid in mine]
            + [{"id": "R1-M1", "status": "resolved", "said": "Not mine to mark."}] * (n != 1),
        }


def index(works):
    """The scholarly indexes, faked: only "A Real Work on Song" is there."""
    return [
        {
            "status": "found",
            "found": {
                "source": "Crossref",
                "id": "10.5555/real",
                "url": "https://doi.org/10.5555/real",
                "title": "A Real Work on Song",
                "author": "Real",
                "year": 2019,
            },
        }
        if "Real" in w["title"]
        else {"status": "not found", "found": None}
        for w in works
    ]


class Runner:
    """A step's runner, faked: an analysis step changes the script, a text step the paper."""

    name, label = "claude", "Claude Code"

    def __init__(self):
        self.briefs: list[str] = []

    def __call__(self, task):
        self.briefs.append(task.brief)
        if "Revise the manuscript" in task.brief:
            paper = task.folder / "paper.md"
            paper.write_text(paper.read_text() + f"\nRevised {len(self.briefs)}.\n")
            step, found = "Revise the text", ""
        else:
            (task.folder / "analysis.py").write_text("print('mixed model')\n")
            step, found = "Model the weeks", "The effect holds: 11% (95% CI 6 to 16)."
        return {
            "step": step,
            "why": "The review asked.",
            "did": "Changed it.",
            "found": found,
            "figures": [],
            "couldnt": "",
            "next": "",
            "commit": step,
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A vault with one paper project, a key for the hosted model, and the model, the indexes and
    the runner faked."""
    vault = tmp_path / "vault"
    monkeypatch.setenv("PROXENOS_VAULT", str(vault))
    monkeypatch.setenv("PROXENOS_WORKTREES", str(tmp_path / "worktrees"))
    monkeypatch.setenv("PROXENOS_NAME", "Joe")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    repo = make_repo(
        tmp_path / "code",
        {
            "paper.md": PAPER,
            "analysis.py": "print('mean')\n",
            "data/README.md": "One row per week.\n",
            "data/weeks.csv": "week,songs,temp\n1,12,8\n",
        },
    )
    write_list(
        vault,
        {
            "id": "birds",
            "name": "Birds",
            "about": "When birds sing",
            "repo": str(repo),
            "manuscript": "paper.md",
        },
    )
    model, runner = Model(), Runner()
    monkeypatch.setattr(
        llm,
        "_ask",
        lambda m, prompt, system, schema, effort, max_tokens, images, keep=(): model(
            prompt, system=system, schema=schema
        ),
    )
    monkeypatch.setattr(review, "_look_up", index)
    monkeypatch.setattr(llm, "_calls_path", lambda: vault / llm.CALLS)  # this vault's log
    monkeypatch.setattr(agent, "runners", lambda *a, **k: [runner])
    return vault, repo, model, runner


def project(vault, pid="birds"):
    return next(p for p in projects.listed_projects(vault) if p["id"] == pid)


def private(path: Path) -> bool:
    if os.name == "nt":
        return True
    return (path.stat().st_mode & 0o777) == (0o700 if path.is_dir() else 0o600)


def test_a_paper_is_reviewed_in_rounds_until_no_major_concern_is_left(setup, capsys):
    vault, repo, model, runner = setup
    head = git(repo, "rev-parse", "HEAD")

    cli.main(["review", "birds", "--rounds", "3"])

    said = capsys.readouterr().out.strip().splitlines()
    assert said[-1].startswith("review: birds: 2 rounds: no major concern left")
    run = review.runs(vault, "birds")[0]
    assert run["status"] == "done" and run["model"] == llm.DEFAULT_MODEL
    assert [r["n"] for r in run["reviewers"]] == [1, 2, 3]
    assert run["field"] == "Ornithology"
    first, second = run["rounds"]
    assert first["open_major"] == 3 and first["open_minor"] == 3
    # Round two marked every concern of round one resolved, and raised one minor one.
    assert second["open_major"] == 0 and second["open_minor"] == 1
    assert [s["resolved"] for s in second["reviews"]] == [2, 2, 2]
    assert run["concerns"]["R1-M1"]["history"] == [
        {"round": 1, "status": "raised"},
        {"round": 2, "status": "resolved"},
    ]
    assert run["concerns"]["R3-m2"]["status"] == "open"
    # Scores are kept within their scale.
    assert {s["score"] for s in first["reviews"]} == {10}

    # Each reviewer wrote alone: no prompt held another's report of the same round.
    reviews = [(who, prompt) for who, _, prompt in model.prompts if who.startswith("R")]
    assert len(reviews) == 6
    for who, prompt in reviews:
        n, k = who[1:].split(".")
        for other in ("1", "2", "3"):
            if other != n:
                assert f"MARK-R{other}-{k}" not in prompt
                assert f"MARK-R{other}-1" not in prompt  # nor anyone else's earlier one
    # The second round read the revision, the letter and its own last report.
    r1_again = next(p for who, p in reviews if who == "R1.2")
    assert "Revised" in r1_again and "MARK-R1-1" in r1_again and "MARK-LETTER" in r1_again
    assert "{+" in r1_again  # what changed, word by word
    # Each read the manuscript with its lines numbered, and the code and data descriptions,
    # but of a table only its columns.
    assert "   11| Songs rose at dawn." in r1_again or "Songs rose at dawn." in r1_again
    first_prompt = next(p for who, p in reviews if who == "R1.1")
    assert "    1| # When birds sing" in first_prompt
    assert "=== analysis.py ===" in first_prompt and "One row per week." in first_prompt
    assert "week,songs,temp" in first_prompt and "1,12,8" not in first_prompt

    folder = next((vault / "clones" / "projects" / "birds" / "reviews").glob("*/round-1"))
    for name in ("reviewer-1.md", "reviewer-1.json", "plan.md", "plan.json", "response.md"):
        assert private(folder / name), name
    assert private(folder) and private(folder.parent)

    # Only the work an index has is kept, as the index has it, and a citation to a work neither
    # the paper nor the indexes hold is taken out; one the paper holds stays.
    kept = json.loads((folder / "reviewer-1.json").read_text())
    assert [w["title"] for w in kept["literature"]] == ["A Real Work on Song"]
    assert kept["literature"][0]["doi"] == "10.5555/real" and kept["dropped"] == 1
    assert "Nobody et al. (2021)" not in kept["summary"] and review.TAKEN_OUT in kept["summary"]
    assert "Lee et al. (2020)" in kept["summary"]
    text = (folder / "reviewer-1.md").read_text()
    assert "### R1-M1. Weeks aren't independent (1)" in text and "Never Written" not in text

    # The plan sorts every open concern, the one it left out as the user's to decide, and none
    # that isn't one.
    plan = json.loads((folder / "plan.json").read_text())
    assert [i["id"] for i in plan["items"]] == [
        "R1-M1", "R1-m1", "R2-M1", "R2-m1", "R3-M1", "R3-m1"
    ]  # fmt: skip
    unsorted = next(i for i in plan["items"] if i["id"] == "R2-m1")
    assert unsorted["action"] == "later" and unsorted.get("unsorted")
    assert first["plan"] == {"text": 3, "analysis": 1, "later": 1, "decline": 1}

    # The revision is steps: the analysis first, then the text built on it, then round two's
    # text built on that, each waiting on the user. Their checkout isn't touched.
    made = [steps.load(vault, s) for r in run["rounds"] for s in r["steps"]]
    assert [s["status"] for s in made] == ["ready", "ready", "ready"]
    assert made[0]["base"] == "main" and "builds_on" not in made[0]
    assert made[1]["builds_on"] == made[0]["id"] and made[2]["builds_on"] == made[1]["id"]
    assert made[1]["manuscript"] == {"path": "paper.md", "branch": "main"}
    assert "R1-M1" in runner.briefs[0] and "Don't change paper.md" in runner.briefs[0]
    assert "11% (95% CI 6 to 16)" in runner.briefs[1]  # the text step reads what it found
    # The author's name stays in the title block: the text step keeps to it, reviewers flag a
    # breach, and the plan makes it a change to the text.
    assert steps.AUTHOR_RULES in runner.briefs[1] and steps.AUTHOR_RULES not in runner.briefs[0]
    systems = {who: system for who, system, _ in model.prompts}
    assert steps.AUTHOR_RULES in systems["R1.1"] and "(Joe)" in systems["R1.1"]
    assert steps.AUTHOR_RULES in systems["plan"]
    assert "A Real Work on Song" in runner.briefs[1] and "Ghost" not in runner.briefs[1]
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "status", "--porcelain") == ""

    # Accepting the last merges them all, and settles every step it built on.
    steps.accept(vault, made[2]["id"])
    assert [steps.load(vault, s["id"])["status"] for s in made] == ["accepted"] * 3
    assert "Revised" in (repo / "paper.md").read_text()
    assert (repo / "analysis.py").read_text() == "print('mixed model')\n"

    # Every call is in the model-call log as the review's, at Anthropic, never with its words.
    calls = [c for c in llm.calls(vault) if c["step"] == "review"]
    assert len(calls) == 1 + 3 + 1 + 1 + 3 + 1 + 1  # choose, reviews, plan, letter, twice
    assert {c["where"] for c in calls} == {"Anthropic"}
    assert not any("birds sing" in json.dumps(c) for c in calls)


def test_a_review_stops_after_its_last_round_and_says_whats_open(setup, monkeypatch):
    vault, _repo, _model, _runner = setup

    run = review.review(vault, project(vault), rounds=1, reviewers=2, now=NOW)

    assert run["id"] == "birds/20260310-020000" and len(run["rounds"]) == 1
    assert [r["n"] for r in run["reviewers"]] == [1, 2]
    assert run["summary"] == ("1 round: 2 major concerns open. 2 steps of revision wait on you.")
    assert review.letter(vault, "birds")[0] == 1


def test_a_failed_step_stops_the_review_and_leaves_nothing_queued(setup, monkeypatch):
    vault, _repo, model, _runner = setup

    def broken(task):
        raise agent.AgentError("it fell over")

    broken.name, broken.label = "claude", "Claude Code"
    monkeypatch.setattr(agent, "runners", lambda *a, **k: [broken])

    run = review.review(vault, project(vault), rounds=3, now=NOW)

    assert run["status"] == "stopped" and len(run["rounds"]) == 1
    assert "it fell over" in run["rounds"][0]["error"]
    assert not any(who == "letter" for who, *_ in model.prompts)
    assert steps.queued(vault, "birds") == []  # a review's step isn't left for the night


def test_without_a_manuscript_or_a_model_there_is_no_review(setup, tmp_path, monkeypatch):
    vault, repo, _model, _runner = setup
    bare = make_repo(tmp_path / "bare", {"run.py": "print(1)\n"})
    write_list(vault, {"id": "bare", "name": "Bare", "repo": str(bare)})
    with pytest.raises(SystemExit, match="no manuscript"):
        review.review(vault, project(vault, "bare"))

    write_list(vault, {"id": "birds", "name": "Birds", "repo": str(repo)})
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(agent, "claude_bin", lambda: None)
    with pytest.raises(SystemExit, match="no model to review with"):
        review.review(vault, project(vault))
    monkeypatch.setenv("PROXENOS_REVIEW_MODEL", "claude-code")
    with pytest.raises(SystemExit, match="Claude Code isn't here"):
        review.model()
    monkeypatch.setenv("PROXENOS_REVIEW_MODEL", "ollama:gemma4:26b")
    assert review.model() == "ollama:gemma4:26b"


def test_all_reviews_every_project_with_a_manuscript_and_says_why_not_the_rest(
    setup, tmp_path, capsys
):
    vault, repo, _model, _runner = setup
    bare = make_repo(tmp_path / "bare", {"run.py": "print(1)\n"})
    write_list(
        vault,
        {"id": "birds", "name": "Birds", "repo": str(repo)},
        {"id": "bare", "name": "Bare", "repo": str(bare)},
        {"id": "notes", "name": "Notes only"},
        {"id": "resting", "name": "Resting", "repo": str(repo), "paused": True},
        {"id": "petition", "name": "Petition", "repo": str(repo), "cloud": False},
    )

    cli.main(["review", "--all", "--rounds", "1"])

    said = capsys.readouterr().out.strip().splitlines()
    assert said[0].startswith("review: birds: 1 round: 3 major concerns open")
    assert said[1] == "review: bare: no manuscript, so no review"
    assert said[2].startswith("review: petition: kept out of the cloud")  # only when named
    assert len(said) == 3
    with pytest.raises(SystemExit, match="name a project, or give --all"):
        review.run(vault, argparse.Namespace(id=None, all=False, rounds=1, reviewers=3))


def test_the_night_reviews_only_projects_that_opt_in_once_the_paper_changed(setup):
    vault, repo, _model, _runner = setup
    assert review.night(vault, NOW) == {
        "reviews_done": 0,
        "reviews_failed": 0,
        "reviews_waiting": 0,
    }
    write_list(
        vault,
        {"id": "birds", "name": "Birds", "repo": str(repo), "autoreview": True},
    )
    assert review.night(vault, NOW, rounds=1)["reviews_done"] == 1
    # Its steps wait on the user, so the next night leaves it.
    assert review.night(vault, LATER)["reviews_waiting"] == 1
    for s in review.runs(vault, "birds")[0]["rounds"][0]["steps"]:
        steps.discard(vault, s)
    # Decided, but the paper is as it was: nothing to review.
    assert review.night(vault, LATER)["reviews_unchanged"] == 1


def test_claude_code_reviews_by_reading_a_worktree_of_the_commit(setup, monkeypatch):
    vault, _repo, model, _runner = setup
    monkeypatch.setenv("PROXENOS_REVIEW_MODEL", "claude-code")
    monkeypatch.setattr(agent, "claude_bin", lambda: "/usr/local/bin/claude")
    read = []

    def reader(prompt, system, schema, folder, hidden):
        read.append((folder, (folder / "paper.md").read_text(), hidden))
        answer = model(prompt, system=system, schema=schema if "required" in schema else None)
        return {"text": answer} if isinstance(answer, str) else answer

    run = review.review(vault, project(vault), rounds=1, now=NOW, read=reader)

    assert run["model"] == "claude-code" and run["status"] == "done"
    folders = {folder for folder, *_ in read}
    assert len(folders) == 1 and not next(iter(folders)).exists()  # gone again
    assert all(text == PAPER for _, text, _ in read)
    assert vault in read[0][2]  # it may not read the vault
    first = next(p for who, _, p in model.prompts if who == "R1.1")
    assert "Its code and data descriptions are in this folder" in first
    assert "=== analysis.py ===" not in first
    calls = [c for c in llm.calls(vault) if c["step"] == "review"]
    assert {c["model"] for c in calls} == {"claude-code"} and len(calls) == 6


def test_read_only_gives_claude_code_nothing_to_run_or_write(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "claude_bin", lambda: "/usr/local/bin/claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "kept-from-it")
    given = {}

    def run(args, cwd, environment, stdin, timeout):
        given.update(args=args, cwd=cwd, env=environment, stdin=stdin)
        answer = {"subtype": "success", "structured_output": {"ok": True}, "num_turns": 3}
        return 0, json.dumps(answer), ""

    answer = agent.read_only(
        "Read it.", "You review.", {"type": "object"}, tmp_path, [tmp_path / "v"], run
    )

    assert answer == {"ok": True}
    args = given["args"]
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep"
    settings = json.loads(args[args.index("--settings") + 1])
    assert {"Bash", "Edit", "Write", "WebFetch"} <= set(settings["permissions"]["deny"])
    assert any(rule.startswith("Read(") for rule in settings["permissions"]["deny"])
    assert given["cwd"] == tmp_path and given["stdin"] == "Read it."
    assert "ANTHROPIC_API_KEY" not in given["env"]


def test_suggested_reading_is_looked_up_where_a_papers_references_are():
    def fetch(url):
        if "/works/10.5555%2Freal" in url or "/works/10.5555/real" in url:
            item = {"DOI": "10.5555/real", "title": ["A Real Work on Song"],
                    "author": [{"family": "Real"}], "issued": {"date-parts": [[2019]]}}  # fmt: skip
            return "application/json", json.dumps({"message": item}).encode()
        if "api.crossref.org" in url:
            return "application/json", json.dumps({"message": {"items": []}}).encode()
        if "api.openalex.org" in url:
            return "application/json", json.dumps({"results": []}).encode()
        raise AssertionError(url)

    found = preprint.look_up(
        [
            {
                "title": "A Real Work on Song",
                "authors": ["Ana Real"],
                "year": 2019,
                "doi": "10.5555/real",
            },
            {"title": "A Work That Was Never Written", "authors": ["Bo Ghost"], "year": 2022},
        ],
        fetch=fetch,
        wait=lambda s: None,
    )

    assert [f["status"] for f in found] == ["found", "not found"]
    assert found[0]["found"]["id"] == "10.5555/real"


def test_the_privacy_view_names_what_a_review_sends():
    part = next(p for p in privacy.SENDS if "review" in p[1])
    assert part[0] == "Peer review" and "Never a message" in part[2]
