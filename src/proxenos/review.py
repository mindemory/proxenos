"""`proxenos review`: a project's paper peer-reviewed in rounds, as a journal would, so every paper
gets the reviews the user would otherwise ask colleagues for, with what they ask done as steps the
user accepts.

A project on clones/projects/projects.json with a "repo" and a manuscript (proxenos.manuscript.find,
Markdown or LaTeX) is reviewed when the user asks: `proxenos review ID [--rounds N]`, `proxenos
review --all`, or Review it on the page's Projects view. Never on its own, but for a project with
"autoreview": true, which the night reviews once its manuscript has changed since its last review
and that one is EVERY_DAYS old, with none of its steps still waiting on the user.

A round:
1. The reviews. The first round chooses REVIEWERS reviewers from the paper's field, kind and venue
   (one call reads its opening), each with a lens of their own: someone from its field, someone
   for its methods and statistics, someone for its venue's readers. Each reads the whole
   manuscript, its lines numbered, and the project's code and the files that describe its data,
   read from git at the commit reviewed, and checks the paper's claims against them. Each writes
   alone: no reviewer's prompt holds another's review of the same round. A review is a summary,
   strengths, numbered major and minor concerns (each with where it is, why it matters and what
   would resolve it), questions, a recommendation and a score. A work a reviewer suggests reading
   is looked up at Crossref, DataCite, arXiv and OpenAlex (proxenos.preprint) and kept only as an
   index has it, and a citation in a review's words to a work neither the paper nor those
   suggestions hold is taken out, so no review cites a work that may not exist.
2. The author's response: a plan that sorts every request, each concern still open by its id, into
   change the text, change the analysis or code, plan for later, or decline with a reason. One the
   plan leaves out is the user's to decide, and says so.
3. The revision: the analysis and code changes as one step, then the text's as a step built on it,
   through the steps clone (proxenos.clones.steps), each on a branch of its own waiting for the
   user's Accept or Discard. Then the point-by-point response letter, as the user, from the plan
   and what the steps did.
4. The next round: the same reviewers read the revision (the newest step's branch), the letter and
   their own earlier reviews, mark each concern of theirs still open resolved, partly resolved or
   not resolved, and raise anything new. Up to ROUNDS rounds, stopping after the one that leaves
   no major concern.

A review is clones/projects/<id>/reviews/<when>.json, with its rounds beside it in
<when>/round-<n>/: each reviewer's review (reviewer-<n>.md, and .json), the plan (plan.md and
.json) and the letter (response.md). The folders clone puts the newest letter beside the
manuscript in the project's cloud folder, as a Word file.

The model: PROXENOS_REVIEW_MODEL, else Claude (llm.DEFAULT_MODEL) with the user's key, else Claude
Code where it's installed, which reads the code at the commit itself, with only its Read, Glob and
Grep tools (proxenos.agent.read_only). "claude-code" picks Claude Code; "ollama:<name>" or
"local:<name>" a model on this computer. A paper and its code go to a hosted model only in a review
the user starts or opts into, and nothing else of the vault goes with them: no message and no
status, only the repository at the commit reviewed, the project's name, description and brief.
Every call leaves its line in the model-call log as "review". Nothing is merged, sent or posted.
"""

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from proxenos import agent, llm, lock, manuscript, preprint
from proxenos.clones import projects, steps, work
from proxenos.config import env

ROUNDS = 3
MAX_ROUNDS = 5
REVIEWERS = 3
EVERY_DAYS = 7  # between reviews the night starts, for a project that opts in
CLAUDE_CODE = "claude-code"  # PROXENOS_REVIEW_MODEL's name for Claude Code
OPENING = 12_000  # of the manuscript, read to choose the reviewers
BRIEF_CHARS = 5000
CODE_CHARS = 200_000  # of the code and data descriptions a reviewer reads, where the model has room
OVERHEAD = 60_000  # of a prompt besides the paper: the instructions, the last report, the letter
CODE_FILES = 150
FILE_BYTES = 200_000  # a file bigger than this isn't read
COLUMNS_CHARS = 600  # of a table's first line, its columns
DIFF_CHARS = 60_000  # of what changed in the manuscript since the last round
CONTEXT = 300  # characters of unchanged text kept either side of a change
LITERATURE = 8  # works one reviewer may suggest
STEP_CHARS = 30_000  # of what a revision step is asked to do
ANSWER_TOKENS = 32_000
LETTER_TOKENS = 48_000
RUNS_KEPT = 20  # reviews listed and read back, newest first
STATUSES = ("resolved", "partly resolved", "not resolved")
ACTIONS = ("text", "analysis", "later", "decline")
RECOMMENDATIONS = ("accept", "minor revision", "major revision", "reject")
OPEN = ("open", "partly resolved", "not resolved")  # a concern the author still has to answer
CODE = {".py", ".m", ".r", ".jl", ".sh", ".stan", ".sql", ".c", ".cc", ".cpp", ".h", ".js", ".ts"}
CODE |= {".rs", ".go", ".java", ".scala", ".do", ".sas", ".ipynb", ".rmd", ".qmd", ".mk"}
DESCRIBES = {".md", ".markdown", ".rst", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".bib"}
TABLES = {".csv", ".tsv"}  # only their first line, the columns
_NAMED = {"makefile", "snakefile", "dockerfile", "license", "citation.cff", "environment.yml"}
_SKIP = {"node_modules", ".venv", "venv", "env", "site-packages", "build", "dist", "vendor"}
_SKIP |= {"__pycache__", ".ipynb_checkpoints", "third_party", ".proxenos", ".git"}
_RUN_ID = re.compile(r"([a-z0-9][a-z0-9-]{0,39})/(\d{8}-\d{6})")
# A citation in a review's words: "Smith et al. (2019)", "Smith and Jones, 2019", "(Smith, 2019)",
# "Smith (2019)". Its surname is group 1, or 2 for the parenthesized form.
_NAME = r"[A-Z][A-Za-z'’\-]+"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
_CITATION = re.compile(
    rf"\b({_NAME})(?: et al\.?| (?:and|&) {_NAME})?,? \(({_YEAR})\)"
    rf"|\b({_NAME})(?: et al\.?| (?:and|&) {_NAME}),? ({_YEAR})\b"
    rf"|\(({_NAME})(?: et al\.?| (?:and|&) {_NAME})?,? ({_YEAR})\)"
)
TAKEN_OUT = "[citation taken out: not in the paper, and not checked]"

Ask = Callable[..., object]  # llm.ask's shape: (prompt, *, system, schema, ...) -> str | dict


class ReviewError(RuntimeError):
    """A model's answer that can't be used."""


# The model.


def model() -> str:
    """The review's model: PROXENOS_REVIEW_MODEL, else Claude with the user's key, else Claude
    Code where it's installed. SystemExit saying what to set up when there's none."""
    chosen = env("REVIEW_MODEL").strip()
    if chosen == CLAUDE_CODE and not agent.claude_bin():
        raise SystemExit("review: PROXENOS_REVIEW_MODEL is claude-code, but Claude Code isn't here")
    if chosen:
        return chosen
    if os.environ.get("ANTHROPIC_API_KEY"):
        return llm.DEFAULT_MODEL
    if agent.claude_bin():
        return CLAUDE_CODE
    raise SystemExit(
        "review: there's no model to review with. Save an Anthropic key in Settings, install "
        "Claude Code, or set PROXENOS_REVIEW_MODEL to a model on this computer (ollama:<name>)"
    )


class _Asker:
    """One review's calls, to its model: through llm.ask, logged as "review", or Claude Code
    reading the worktree of the commit reviewed. `ask` stands in for llm.ask in tests."""

    def __init__(self, chosen: str, ask: Ask | None = None, read: Callable | None = None):
        self.model, self.ask, self.read = chosen, ask or llm.ask, read or agent.read_only
        self.folder: Path | None = None  # the worktree Claude Code reads
        self.hidden: list[Path] = []

    @property
    def reads_code(self) -> bool:
        """Whether the model reads the code itself, so the prompt names the files only."""
        return self.model == CLAUDE_CODE

    def room(self, overhead: int) -> int:
        """Characters of manuscript and code a prompt may hold beside `overhead`."""
        if self.reads_code:
            return 10**7
        with llm.using(model=self.model, step="review"):
            return llm.fit(10**7, overhead)

    def __call__(self, prompt: str, system: str, schema: dict | None, tokens: int) -> object:
        if self.reads_code:
            if self.folder is None:
                raise ReviewError("Claude Code has no worktree to read")
            shape = schema or {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            }
            began, ok = time.monotonic(), False
            try:
                answer = self.read(prompt, system, shape, self.folder, self.hidden)
                ok = True
            finally:
                chosen = env("STEP_MODEL").strip()
                llm.log_run(
                    "review",
                    CLAUDE_CODE + (f":{chosen}" if chosen else ""),
                    time.monotonic() - began,
                    ok,
                    runner="claude",
                )
            return answer if schema else str(answer.get("text") or "")
        with llm.using(model=self.model, step="review"):
            return self.ask(prompt, system=system, schema=schema, effort="high", max_tokens=tokens)


# Reviewing a project.


def review(
    vault: Path,
    project: dict,
    rounds: int = ROUNDS,
    reviewers: int = REVIEWERS,
    now: datetime | None = None,
    ask: Ask | None = None,
    check: Callable[[list[dict]], list[dict]] | None = None,
    tried: list | None = None,
    read: Callable | None = None,
) -> dict:
    """The project's manuscript reviewed for up to `rounds` rounds by `reviewers` reviewers, each
    round's revision taken as steps that wait on the user. The review as saved. `ask`, `check`
    (the literature's lookup), `tried` (the steps' runners) and `read` (Claude Code reading) stand
    in for the real ones in tests."""
    now = now or datetime.now(UTC)
    rounds = max(1, min(int(rounds), MAX_ROUNDS))
    reviewers = max(2, min(int(reviewers), REVIEWERS))
    found = manuscript.find(project)
    if found is None:
        raise SystemExit(
            f"review: {project['id']} has no manuscript: no paper.md, manuscript.md or main.tex "
            'on any branch. Name it in projects.json: "manuscript": {"path": ..., "branch": ...}'
        )
    if PurePosixPath(found["path"]).suffix.lower() not in (".md", ".markdown", ".tex", ".txt"):
        raise SystemExit(f"review: {found['path']} isn't Markdown or LaTeX")
    repo = steps._repo(project)
    gate = lock.Lock(vault / "state" / f"review-{project['id']}.lock")
    if not gate.acquire():
        raise SystemExit(f"review: {project['id']} is being reviewed already")
    try:
        _settle(vault, project["id"])
        asker = _Asker(model(), ask, read)
        run = _start(vault, project, found, repo, asker, rounds, now)
        try:
            for n in range(1, rounds + 1):
                if _round(vault, project, run, repo, asker, n, reviewers, check, tried):
                    break
            run["status"] = "stopped" if run["rounds"][-1]["status"] == "stopped" else "done"
            _note(vault, run, "Done" if run["status"] == "done" else "Stopped", _summary(run))
        except BaseException as e:  # the review says how it failed, for the page
            run["status"] = "failed"
            run["error"] = " ".join(str(e).split())[:300] or type(e).__name__
            if run["rounds"] and run["rounds"][-1]["status"] not in ("done", "stopped"):
                run["rounds"][-1]["status"] = "failed"
            _note(vault, run, "Stopped", f"It failed: {run['error']}")
            raise
        finally:
            _drop_worktree(repo, asker)
        return run
    finally:
        gate.release()


def _start(
    vault: Path,
    project: dict,
    found: dict,
    repo: Path,
    asker: _Asker,
    rounds: int,
    now: datetime,
) -> dict:
    when = f"{now:%Y%m%d-%H%M%S}"
    if _path(vault, f"{project['id']}/{when}").exists():
        raise SystemExit("review: a review was started this second; start it again")
    tip = manuscript._tip(repo, found["branch"])
    run = {
        "id": f"{project['id']}/{when}",
        "project": project["id"],
        "created": _iso(now),
        "status": "working",
        "model": asker.model,
        "rounds_max": rounds,
        "manuscript": {"path": found["path"], "branch": found["branch"], "commit": tip},
        "field": "",
        "kind": "",
        "venue": "",
        "reviewers": [],
        "rounds": [],
        "concerns": {},
        "thread": [],
    }
    _note(
        vault,
        run,
        "Started",
        f"{found['path']} on {found['branch']} at {tip[:7]}, for up to {rounds} "
        f"round{'s' * (rounds != 1)}, with {asker.model}.",
    )
    return run


def _round(
    vault: Path,
    project: dict,
    run: dict,
    repo: Path,
    asker: _Asker,
    n: int,
    count: int,
    check: Callable | None,
    tried: list | None,
) -> bool:
    """One round, from the reviews to the letter. Whether it's the last."""
    path = run["manuscript"]["path"]
    where = _reading(vault, run, repo)
    if where is None:
        return True
    branch, commit = where
    text = manuscript.text_at(repo, commit, path)
    record = {
        "n": n,
        "status": "reviewing",
        "started": _iso(datetime.now(UTC)),
        "reviewed": {"branch": branch, "commit": commit},
        "reviews": [],
        "open_major": 0,
        "open_minor": 0,
        "plan": {},
        "steps": [],
        "response": False,
    }
    run["rounds"].append(record)
    _save(vault, run)
    if asker.reads_code:
        _worktree(repo, asker, run, commit, n)
        asker.hidden = steps.hidden(vault)
    paper = _context(project, run, repo, commit, text, asker)
    if n == 1:
        _choose(vault, project, run, text, asker, count)
    earlier = _changes(run, repo, text, n)
    reviews = _reviews(vault, project, run, paper, earlier, asker, check, n)
    for reviewer, answer in reviews:
        _keep_review(vault, run, reviewer, answer, n, text)
    open_ = [c for c in _open(run)]
    record["open_major"] = sum(run["concerns"][c]["kind"] == "major" for c in open_)
    record["open_minor"] = len(open_) - record["open_major"]
    last = n >= run["rounds_max"] or record["open_major"] == 0
    _note(
        vault,
        run,
        f"Round {n}: the reviews are in",
        f"{record['open_major']} major and {record['open_minor']} minor concerns open.",
    )
    if not open_:
        record["status"] = "done"
        _note(vault, run, f"Round {n}: nothing left to answer", "No concern is open.")
        return True

    record["status"] = "planning"
    _save(vault, run)
    plan = _plan(vault, run, paper, asker, n, open_)
    record["status"] = "revising"
    _save(vault, run)
    made = _revise(vault, project, run, plan, n, tried)
    if any(m.get("status") != "ready" for m in made):  # no letter for a revision not made
        record["status"] = "stopped"
        _save(vault, run)
        return True
    record["status"] = "writing"
    _save(vault, run)
    _letter(vault, run, paper, asker, n, plan, made)
    record["response"] = True
    record["status"] = "done"
    _save(vault, run)
    return last


def _reading(vault: Path, run: dict, repo: Path) -> tuple[str, str] | None:
    """Where this round reads the manuscript: its branch's tip in the first round, then the newest
    step's branch the last round made, or where the last round read when it made none. None when
    that's gone, which ends the review."""
    if not run["rounds"]:
        found = run["manuscript"]
        return found["branch"], found["commit"]
    last = run["rounds"][-1]
    for step_id in reversed(last["steps"]):
        step = steps._load_quietly(vault, step_id)
        head = manuscript._tip(repo, str(step.get("branch") or ""))
        if step.get("status") == "ready" and head:
            return step["branch"], head
        _note(vault, run, "Stopped", f"{step_id} isn't waiting on you any more, so it ends here.")
        return None
    return last["reviewed"]["branch"], last["reviewed"]["commit"]


# What a reviewer reads.


def _context(project: dict, run: dict, repo: Path, commit: str, text: str, asker: _Asker) -> str:
    """The paper as every reviewer and the author read it this round: the project, the manuscript
    with its lines numbered, and its code and data descriptions at the commit, to the room the
    model has."""
    path = run["manuscript"]["path"]
    about = [f"The project: {project['name']}"]
    if project.get("about"):
        about.append(f"What it is: {project['about']}")
    if project.get("brief"):
        about.append(f"What's known around it, from its brief:\n{project['brief'][:BRIEF_CHARS]}")
    numbered = _numbered(text)
    room = asker.room(OVERHEAD)
    if len(numbered) > room:
        numbered = numbered[:room] + "\n[the rest of the manuscript doesn't fit here]"
    parts = [
        "\n".join(about),
        f"The manuscript, {path} at commit {commit[:7]}, its lines numbered:\n\n{numbered}",
    ]
    if asker.reads_code:
        parts.append(
            "Its code and data descriptions are in this folder, the repository at that commit: "
            "read what you need to check the paper's claims, and give file and line."
        )
    else:
        code, left = _code(repo, commit, path, text, min(CODE_CHARS, room - len(numbered)))
        if code:
            parts.append(f"Its code and the files describing its data at that commit:\n\n{code}")
        if left:
            shown = ", ".join(left[:40]) + (f" and {len(left) - 40} more" if len(left) > 40 else "")
            parts.append(f"Not shown, for room: {shown}.")
    return "\n\n".join(parts)


def _numbered(text: str) -> str:
    return "\n".join(f"{i:>5}| {line}" for i, line in enumerate(text.splitlines(), start=1))


def _code(repo: Path, commit: str, paper: str, text: str, room: int) -> tuple[str, list[str]]:
    """The project's code and the files that describe its data, read from git at `commit`: those
    the manuscript names first, then the descriptions, then the code, shallowest and smallest
    first, each with its lines numbered, to `room` characters; of a table only its columns.
    (the text, the files left out for room)."""
    listed = []
    for line in manuscript._git(repo, "ls-tree", "-r", "-l", "--full-tree", commit).splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) != 4 or fields[1] != "blob" or not fields[3].isdigit() or path == paper:
            continue
        pure = PurePosixPath(path)
        if {p.lower() for p in pure.parts[:-1]} & _SKIP or int(fields[3]) > FILE_BYTES:
            continue
        suffix, name = pure.suffix.lower(), pure.name.lower()
        if suffix in TABLES:
            kind = 3
        elif suffix in DESCRIBES or name in _NAMED:
            kind = 0
        elif suffix in CODE:
            kind = 1
        else:
            continue
        named = pure.name in text or path in text
        listed.append((not named, kind, len(pure.parts), int(fields[3]), path))
    listed.sort()
    out, left, used = [], [], 0
    for *_, path in listed[:CODE_FILES]:
        shown = _shown(repo, commit, path)
        if not shown:
            continue
        if used + len(shown) > room:
            left.append(path)
            continue
        out.append(shown)
        used += len(shown)
    left += [p for *_, p in listed[CODE_FILES:]]
    return "\n\n".join(out), left


def _shown(repo: Path, commit: str, path: str) -> str:
    """One file as a reviewer reads it: numbered lines, a notebook's cells, a table's columns."""
    data = manuscript._blob(repo, commit, path)
    if data is None or b"\0" in data:
        return ""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in TABLES:
        return f"=== {path}: its columns ===\n{text.partition(chr(10))[0][:COLUMNS_CHARS]}"
    if suffix == ".ipynb":
        text = _cells(text)
        if not text:
            return ""
    return f"=== {path} ===\n{_numbered(text)}"


def _cells(text: str) -> str:
    """A notebook's cells, as text: its code and its notes, never its outputs."""
    try:
        cells = json.loads(text).get("cells") or []
    except (ValueError, AttributeError):
        return ""
    out = []
    for i, cell in enumerate(c for c in cells if isinstance(c, dict)):
        source = cell.get("source")
        body = "".join(source) if isinstance(source, list) else str(source or "")
        out.append(f"# [cell {i + 1}, {cell.get('cell_type', 'code')}]\n{body}")
    return "\n\n".join(out)


def _changes(run: dict, repo: Path, text: str, n: int) -> str:
    """What changed since the last round, for its reviewers: the manuscript word by word, with a
    little unchanged text around each change, and the other files the revision changed."""
    if n == 1:
        return ""
    before = run["rounds"][-2]["reviewed"]["commit"]
    now = run["rounds"][-1]["reviewed"]["commit"]
    if before == now:
        return "The manuscript and its code haven't changed since the last round."
    old = manuscript.text_at(repo, before, run["manuscript"]["path"])
    shown, used = [], 0
    for op in manuscript.diff(old, text):
        if op["op"] == "same":
            piece = op["text"]
            if len(piece) > 2 * CONTEXT:
                piece = piece[:CONTEXT] + " […] " + piece[-CONTEXT:]
        else:
            piece = ("[-" if op["op"] == "del" else "{+") + op["text"]
            piece += "-]" if op["op"] == "del" else "+}"
        if used + len(piece) > DIFF_CHARS:
            shown.append("\n[more changes than fit here]")
            break
        shown.append(piece)
        used += len(piece)
    files = manuscript._git(repo, "diff", "--name-only", before, now).splitlines()
    others = [f for f in files if f != run["manuscript"]["path"]]
    lines = [
        "What changed in the manuscript since the last round, [-taken out-] and {+put in+}:",
        "".join(shown),
    ]
    if others:
        lines.append("Other files the revision changed: " + ", ".join(others[:60]) + ".")
    return "\n\n".join(lines)


# The reviewers.

_CHOOSE = """\
You choose the peer reviewers for a manuscript, as a journal's editor would. From its opening, its \
headings and what the project is, say its field, its kind (an empirical study, a methods paper, a \
system, a theory paper, a review, a dataset) and the venue it's written for (a journal, a \
conference, or a preprint server, as it says; else the likeliest kind of venue). Then choose \
{count} reviewers, each with a different lens on it, as a good editor would for this paper: \
someone expert in its field and question; someone for its methods, statistics and analysis \
(for a system, its engineering and security); someone who reads for the venue's audience, its \
clarity, framing and contribution. Each: lens (a few words), expertise (a sentence, as a reviewer \
states theirs), focus (what they'll check most, a sentence or two). No names."""

_CHOOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "field": {"type": "string"},
        "kind": {"type": "string"},
        "venue": {"type": "string"},
        "reviewers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lens": {"type": "string"},
                    "expertise": {"type": "string"},
                    "focus": {"type": "string"},
                },
                "required": ["lens", "expertise", "focus"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["field", "kind", "venue", "reviewers"],
    "additionalProperties": False,
}

# Lenses for a reviewer the choice didn't name, in turn.
_LENSES = (
    (
        "the field",
        "Expert in the paper's field and its question.",
        "Whether the question, the claims and their framing hold up against what's known.",
    ),
    (
        "methods and statistics",
        "Expert in study design, statistics and analysis code.",
        "Whether the analysis supports each claim, and whether the code does what the paper says.",
    ),
    (
        "the venue's readers",
        "A reader for the venue's audience.",
        "Whether the contribution is clear, the paper reads well and its figures carry it.",
    ),
)


def _choose(vault: Path, project: dict, run: dict, text: str, asker: _Asker, count: int) -> None:
    headings = [s.title for s in agent.sections(text, run["manuscript"]["path"])][:60]
    prompt = "\n\n".join(
        part
        for part in (
            f"The project: {project['name']}"
            + (f"\n{project['about']}" if project["about"] else ""),
            "Its headings: " + "; ".join(headings) if headings else "",
            f"Its opening:\n{text[:OPENING]}",
        )
        if part
    )
    answer = asker(prompt, _CHOOSE.format(count=count), _CHOOSE_SCHEMA, 4000)
    if not isinstance(answer, dict):
        raise ReviewError("the choice of reviewers wasn't one")
    chosen = [r for r in answer.get("reviewers") or [] if isinstance(r, dict)]
    run |= {k: _text(answer.get(k))[:200] for k in ("field", "kind", "venue")}
    run["reviewers"] = []
    for i in range(count):
        given = chosen[i] if i < len(chosen) else {}
        lens, expertise, focus = _LENSES[i % len(_LENSES)]
        run["reviewers"].append(
            {
                "n": i + 1,
                "lens": _text(given.get("lens"))[:120] or lens,
                "expertise": _text(given.get("expertise"))[:600] or expertise,
                "focus": _text(given.get("focus"))[:600] or focus,
            }
        )
    lenses = "; ".join(f"Reviewer {r['n']}, {r['lens']}" for r in run["reviewers"])
    _note(vault, run, "Chose the reviewers", f"{run['field'] or 'Its field'}: {lenses}.")


_REVIEWER = """\
You are Reviewer {n}, one of {count} independent peer reviewers of a manuscript{venue}. Your \
expertise: {expertise} Your lens: {lens}. {focus}

You review alone: you haven't seen any other reviewer's report. Read the whole manuscript, and \
where its code and the files describing its data are given, check its claims against them: \
whether the analysis does what the text says, whether the numbers could come from it, whether \
what's claimed of the code is so. Be specific, fair and demanding, as the best referee for this \
venue would, and useful: say what is strong, and for each concern where it is (section and line, \
or file and line), why it matters and the concrete change or analysis that would resolve it.

Never invent a citation. Name another work only in literature, with its title, authors, year and \
DOI where you know it: each is looked up in the scholarly indexes and any not found is dropped. \
In your text, cite only works the manuscript itself cites. Never invent a fact about the \
manuscript or its code: what you couldn't check, say you couldn't.

Return:
- summary: what the paper does and claims and your overall view, a paragraph or two.
- strengths: what is good about it, each a sentence or two.
- major: concerns that must be resolved before it's sound, most serious first, each with title \
(a line), where, why (it matters), request (what to do).
- minor: smaller ones, the same way; why may be "".
- questions: what you'd ask the authors.
- literature: up to {literature} works the paper should engage with and doesn't, each with why; \
none when there are none you're sure of.
- recommendation: accept, minor revision, major revision or reject.
- score: 1 to 10, where 10 is ready to publish as it is.
- confidence: 1 to 5 in your own judgment.
- checked: what you read and checked against the code, in a few sentences."""

_AGAIN = """\

This is round {round}. You reviewed an earlier version: your concerns still open are listed with \
their ids, beside the author's response letter, your last report and what changed since. Judge \
from the revised manuscript and code, not from what the letter says was done. In earlier, give \
each listed id once, with status (resolved, partly resolved or not resolved) and said (why, a \
sentence or two, with where). Then major and minor hold only what's new: anything the revision \
introduced, or you missed before. Don't raise again what you've marked, nor lower your bar."""


def _review_schema(again: bool) -> dict:
    concern = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "where": {"type": "string"},
            "why": {"type": "string"},
            "request": {"type": "string"},
        },
        "required": ["title", "where", "why", "request"],
        "additionalProperties": False,
    }
    work_ = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "authors": {"type": "array", "items": {"type": "string"}},
            "year": {"type": "integer"},
            "doi": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["title", "authors", "year", "doi", "why"],
        "additionalProperties": False,
    }
    strings = {"type": "array", "items": {"type": "string"}}
    properties = {
        "summary": {"type": "string"},
        "strengths": strings,
        "major": {"type": "array", "items": concern},
        "minor": {"type": "array", "items": concern},
        "questions": strings,
        "literature": {"type": "array", "items": work_},
        "recommendation": {"type": "string", "enum": list(RECOMMENDATIONS)},
        "score": {"type": "integer"},
        "confidence": {"type": "integer"},
        "checked": {"type": "string"},
    }
    if again:
        properties["earlier"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": list(STATUSES)},
                    "said": {"type": "string"},
                },
                "required": ["id", "status", "said"],
                "additionalProperties": False,
            },
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _reviews(
    vault: Path,
    project: dict,
    run: dict,
    paper: str,
    earlier: str,
    asker: _Asker,
    check: Callable | None,
    n: int,
) -> list[tuple[dict, dict]]:
    """Each reviewer's report for this round, written alone: on a hosted model at the same time,
    each prompt with only that reviewer's own earlier reports. [(reviewer, answer)]."""
    venue = f" for {run['venue']}" if run.get("venue") else ""
    letter = _read(_folder(vault, run["id"]) / f"round-{n - 1}" / "response.md") if n > 1 else ""

    def one(reviewer: dict) -> tuple[dict, dict]:
        system = _REVIEWER.format(
            n=reviewer["n"],
            count=len(run["reviewers"]),
            venue=venue,
            expertise=reviewer["expertise"],
            lens=reviewer["lens"],
            focus=reviewer["focus"],
            literature=LITERATURE,
        ) + (_AGAIN.format(round=n) if n > 1 else "")
        parts = [paper]
        if n > 1:
            mine = [c for c in _open(run) if run["concerns"][c]["reviewer"] == reviewer["n"]]
            last = _read(
                _folder(vault, run["id"]) / f"round-{n - 1}" / f"reviewer-{reviewer['n']}.md"
            )
            parts += [
                f"Your last report, round {n - 1}:\n\n{last}",
                "Your concerns still open:\n"
                + ("\n".join(_concern_line(run, c) for c in mine) or "None."),
                f"The author's response letter:\n\n{letter or '(none)'}",
                earlier,
            ]
        prompt = "\n\n---\n\n".join(p for p in parts if p)
        _note(vault, run, f"Round {n}: Reviewer {reviewer['n']} is reading", reviewer["lens"])
        answer = _asked(asker, prompt, system, _review_schema(n > 1), ANSWER_TOKENS)
        return reviewer, _checked(answer, check, paper)

    if asker.model.startswith(llm.LOCAL):  # a model on this computer takes one at a time anyway
        return [one(r) for r in run["reviewers"]]
    with ThreadPoolExecutor(max_workers=len(run["reviewers"])) as pool:
        return list(pool.map(one, run["reviewers"]))


def _asked(asker: _Asker, prompt: str, system: str, schema: dict, tokens: int) -> dict:
    """An answer that fits the schema, asked again once when it doesn't."""
    for attempt in (1, 2):
        try:
            answer = asker(prompt, system, schema, tokens)
        except (ValueError, llm.ModelError, agent.AgentError) as e:
            if attempt == 2 or isinstance(e, agent.AgentUnavailable):
                raise ReviewError(f"the model didn't answer as asked ({e})") from e
            continue
        if isinstance(answer, dict):
            return answer
    raise ReviewError("the model didn't answer as asked")


def _checked(answer: dict, check: Callable | None, paper: str) -> dict:
    """The review with only the works an index found in its literature, each as the index has
    it, and any citation in its words to a work neither the paper nor those hold taken out."""
    works = [
        w for w in answer.get("literature") or [] if isinstance(w, dict) and _text(w.get("title"))
    ][:LITERATURE]
    looked = (check or _look_up)(works) if works else []
    kept, dropped = [], 0
    for work_, found in zip(works, looked, strict=False):
        if not isinstance(found, dict) or found.get("status") not in ("found", "differs"):
            dropped += 1
            continue
        record = found.get("found") if isinstance(found.get("found"), dict) else {}
        said = [_text(a) for a in work_.get("authors") or [] if _text(a)][:6]
        first = _text(record.get("author"))
        rid = _text(record.get("id"))
        kept.append(  # as the index has it, where the reviewer's differs
            {
                "title": _text(record.get("title")) or _text(work_.get("title")),
                "authors": said if found["status"] == "found" or not first else [first],
                "year": record.get("year") or work_.get("year"),
                "doi": rid if rid.startswith("10.") else "",
                "url": _text(record.get("url")),
                "why": _text(work_.get("why")),
            }
        )
    dropped += len(works) - len(looked) if len(looked) < len(works) else 0
    known = {w.lower() for w in re.findall(r"[A-Za-z'’\-]+", paper)}
    for work_ in kept:
        for author in work_["authors"]:
            known |= {w.lower() for w in re.findall(r"[A-Za-z'’\-]+", author)}
    taken = 0

    def scrub(text: str) -> str:
        nonlocal taken

        def one(match: re.Match) -> str:
            nonlocal taken
            name = match[1] or match[3] or match[5]
            if name.lower() in known:
                return match[0]
            taken += 1
            return TAKEN_OUT

        return _CITATION.sub(one, text)

    out = dict(answer)
    for key in ("summary", "checked"):
        out[key] = scrub(str(answer.get(key) or ""))
    for key in ("strengths", "questions"):
        out[key] = [scrub(str(s)) for s in answer.get(key) or [] if _text(s)]
    for key in ("major", "minor"):
        out[key] = [
            {f: scrub(str(c.get(f) or "")) for f in ("title", "where", "why", "request")}
            for c in answer.get(key) or []
            if isinstance(c, dict) and (_text(c.get("title")) or _text(c.get("request")))
        ]
    out["earlier"] = [
        {
            "id": _text(e.get("id")),
            "status": e.get("status"),
            "said": scrub(str(e.get("said") or "")),
        }
        for e in answer.get("earlier") or []
        if isinstance(e, dict)
    ]
    out["literature"] = kept
    out["dropped"], out["taken_out"] = dropped, taken
    return out


def _look_up(works: list[dict]) -> list[dict]:
    """The works looked up where `proxenos preprint refs` looks a reference up."""
    from proxenos.config import vault_path  # only here: the cache is the vault's

    try:
        cache = vault_path() / preprint.CACHE
    except ValueError:
        cache = None
    return preprint.look_up(works, cache=cache)


def _keep_review(vault: Path, run: dict, reviewer: dict, answer: dict, n: int, text: str) -> None:
    """One reviewer's report saved, its new concerns numbered, its earlier ones marked."""
    r = reviewer["n"]
    concerns = run["concerns"]
    marked = Counter()
    for given in answer.get("earlier") or []:
        cid = given["id"]
        if cid in concerns and concerns[cid]["reviewer"] == r and given["status"] in STATUSES:
            if concerns[cid]["status"] not in OPEN:
                continue
            concerns[cid]["status"] = given["status"]
            concerns[cid]["history"].append({"round": n, "status": given["status"]})
            marked[given["status"]] += 1
    for cid, concern in concerns.items():  # one the reviewer didn't mark stays as it was
        mine = concern["reviewer"] == r and concern["status"] in OPEN and n > concern["round"]
        if mine and not any(h["round"] == n for h in concern["history"]):
            concern["history"].append({"round": n, "status": "not marked"})
    for kind, letter in (("major", "M"), ("minor", "m")):
        had = sum(1 for c in concerns.values() if c["reviewer"] == r and c["kind"] == kind)
        for i, given in enumerate(answer.get(kind) or [], start=had + 1):
            cid = f"R{r}-{letter}{i}"
            given["id"] = cid
            concerns[cid] = {
                "reviewer": r,
                "kind": kind,
                "round": n,
                "title": _text(given["title"])[:300] or _text(given["request"])[:120],
                "where": _text(given["where"])[:300],
                "why": str(given["why"])[:3000],
                "request": str(given["request"])[:3000],
                "status": "open",
                "history": [{"round": n, "status": "raised"}],
            }
    score = answer.get("score")
    confidence = answer.get("confidence")
    summary = {
        "n": r,
        "recommendation": answer.get("recommendation")
        if answer.get("recommendation") in RECOMMENDATIONS
        else "",
        "score": max(1, min(10, score)) if isinstance(score, int) else None,
        "confidence": max(1, min(5, confidence)) if isinstance(confidence, int) else None,
        "major": len(answer.get("major") or []),
        "minor": len(answer.get("minor") or []),
        "resolved": marked["resolved"],
        "partly": marked["partly resolved"],
        "unresolved": marked["not resolved"],
        "dropped": answer.get("dropped", 0),
        "taken_out": answer.get("taken_out", 0),
    }
    run["rounds"][-1]["reviews"].append(summary)
    run["rounds"][-1]["reviews"].sort(key=lambda s: s["n"])
    folder = _kept(vault, run["id"], n)
    work._write(folder / f"reviewer-{r}.json", json.dumps(answer, ensure_ascii=False, indent=1))
    work._write(folder / f"reviewer-{r}.md", _review_md(run, reviewer, answer, n))
    _save(vault, run)


def _review_md(run: dict, reviewer: dict, answer: dict, n: int) -> str:
    r = reviewer["n"]
    lines = [f"# Round {n}: Reviewer {r}", ""]
    lines += [f"**Lens.** {reviewer['lens']}. **Expertise.** {reviewer['expertise']}", ""]
    said = []
    if answer.get("recommendation") in RECOMMENDATIONS:
        said.append(f"**Recommendation:** {answer['recommendation']}")
    if isinstance(answer.get("score"), int):
        said.append(f"**Score:** {max(1, min(10, answer['score']))}/10")
    if isinstance(answer.get("confidence"), int):
        said.append(f"**Confidence:** {max(1, min(5, answer['confidence']))}/5")
    if said:
        lines += [" · ".join(said), ""]
    lines += ["## Summary", "", str(answer.get("summary") or "").strip(), ""]
    if answer.get("earlier"):
        lines += ["## Concerns from before", ""]
        for e in answer["earlier"]:
            title = run["concerns"].get(e["id"], {}).get("title", "")
            lines.append(f"- **{e['id']}** ({e['status']}). {title}: {e['said']}".rstrip(": "))
        lines.append("")
    if answer.get("strengths"):
        lines += ["## Strengths", ""]
        lines += [f"{i}. {s}" for i, s in enumerate(answer["strengths"], start=1)] + [""]
    for kind, heading in (("major", "Major concerns"), ("minor", "Minor concerns")):
        if not answer.get(kind):
            continue
        lines += [f"## {heading}{' raised now' if n > 1 else ''}", ""]
        for c in answer[kind]:
            lines += [f"### {c['id']}. {c['title']}", ""]
            for label, key in (
                ("Where", "where"),
                ("Why it matters", "why"),
                ("Request", "request"),
            ):
                if str(c.get(key) or "").strip():
                    lines.append(f"- **{label}.** {str(c[key]).strip()}")
            lines.append("")
    if answer.get("questions"):
        lines += ["## Questions", ""]
        lines += [f"{i}. {q}" for i, q in enumerate(answer["questions"], start=1)] + [""]
    if answer.get("literature") or answer.get("dropped"):
        lines += ["## Reading suggested", ""]
        for w in answer.get("literature") or []:
            who = ", ".join(w["authors"][:3]) + (" et al." if len(w["authors"]) > 3 else "")
            link = f" https://doi.org/{w['doi']}" if w.get("doi") and "/" in str(w["doi"]) else ""
            link = link or (f" {w['url']}" if w.get("url") else "")
            lines.append(f"- {who} ({w.get('year') or 'n.d.'}). {w['title']}.{link} {w['why']}")
        if answer.get("dropped"):
            lines.append(
                f"- {answer['dropped']} more suggested, left out: not found at Crossref, "
                "DataCite, arXiv or OpenAlex, or not checked."
            )
        lines.append("")
    if str(answer.get("checked") or "").strip():
        lines += ["## What I read and checked", "", str(answer["checked"]).strip(), ""]
    return "\n".join(lines)


def _open(run: dict) -> list[str]:
    """The concerns the author still has to answer, by reviewer, then major first."""
    concerns = run["concerns"]
    order = {"major": 0, "minor": 1}
    return sorted(
        (c for c in concerns if concerns[c]["status"] in OPEN),
        key=lambda c: (concerns[c]["reviewer"], order[concerns[c]["kind"]], _number(c)),
    )


def _number(cid: str) -> int:
    digits = re.sub(r"\D", "", cid.split("-")[-1])
    return int(digits) if digits else 0


def _concern_line(run: dict, cid: str) -> str:
    c = run["concerns"][cid]
    state = "" if c["status"] == "open" else f", {c['status']} in round {c['history'][-1]['round']}"
    line = (
        f"- {cid} ({c['kind']}, Reviewer {c['reviewer']}, round {c['round']}{state}): {c['title']}."
    )
    if c["where"]:
        line += f" Where: {c['where']}."
    if c["why"]:
        line += f" Why: {_text(c['why'])}"
    return line + f" Request: {_text(c['request'])}"


# The author's response.

_PLAN = """\
You are {person}, the first author of this manuscript, answering its peer reviews as a careful \
author would before revising. Sort every request, each concern by its id, into one action:
- text: change the manuscript's text (rewrite a claim, add a limitation, fix a figure's caption, \
report what the code already gives);
- analysis: change the analysis or the code, to be run (a new test, a fix, a figure redone); the \
text then reports it;
- later: needs new data, other people or more time than a revision: say what's planned;
- decline: say why, with a reason a reviewer would accept.
Agree where the reviewer is right, which is most of the time; decline only with a reason. Never \
plan to invent data, results or citations. Each item: id, action, change (for text and analysis \
what changes and where, concretely enough to make it; for later the plan; for decline the reason). \
summary: how you'll answer the round, in a few sentences."""

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "change": {"type": "string"},
                },
                "required": ["id", "action", "change"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "items"],
    "additionalProperties": False,
}

_HEADINGS = {
    "text": "A. Changes to the text",
    "analysis": "B. Changes to the analysis and code",
    "later": "C. Planned, not in this revision",
    "decline": "D. Declined, with the reason",
}


def _plan(vault: Path, run: dict, paper: str, asker: _Asker, n: int, open_: list[str]) -> dict:
    """The round's plan, every open concern sorted into ACTIONS; one the plan left out is the
    user's to decide. Saved as plan.json and plan.md."""
    person = env("NAME", "the author")
    folder = _kept(vault, run["id"], n)
    reports = "\n\n".join(_read(folder / f"reviewer-{r['n']}.md") for r in run["reviewers"])
    prompt = "\n\n---\n\n".join(
        [
            paper,
            f"The reviews of round {n}:\n\n{reports}",
            "Every concern to answer, by id:\n" + "\n".join(_concern_line(run, c) for c in open_),
        ]
    )
    _note(vault, run, f"Round {n}: planning the response", f"{len(open_)} concerns to answer.")
    answer = _asked(asker, prompt, _PLAN.format(person=person), _PLAN_SCHEMA, ANSWER_TOKENS)
    sorted_: dict[str, dict] = {}
    for item in answer.get("items") or []:
        cid = _text(item.get("id")) if isinstance(item, dict) else ""
        if cid in open_ and cid not in sorted_ and item.get("action") in ACTIONS:
            sorted_[cid] = {"id": cid, "action": item["action"], "change": str(item["change"])}
    for cid in open_:
        sorted_.setdefault(
            cid,
            {
                "id": cid,
                "action": "later",
                "change": "Not sorted by the plan: yours to decide.",
                "unsorted": True,
            },
        )
    plan = {
        "summary": str(answer.get("summary") or "").strip(),
        "items": [sorted_[c] for c in open_],
    }
    counts = Counter(i["action"] for i in plan["items"])
    run["rounds"][-1]["plan"] = {a: counts[a] for a in ACTIONS}
    work._write(folder / "plan.json", json.dumps(plan, ensure_ascii=False, indent=1))
    work._write(folder / "plan.md", _plan_md(run, plan, n))
    _save(vault, run)
    return plan


def _plan_md(run: dict, plan: dict, n: int) -> str:
    lines = [f"# Round {n}: what the author will do", ""]
    if plan["summary"]:
        lines += [plan["summary"], ""]
    for action in ACTIONS:
        items = [i for i in plan["items"] if i["action"] == action]
        if not items:
            continue
        lines += [f"## {_HEADINGS[action]}", ""]
        for item in items:
            title = run["concerns"][item["id"]]["title"]
            lines.append(f"- **{item['id']}** {title}: {_text(item['change'])}")
        lines.append("")
    return "\n".join(lines)


def _revise(
    vault: Path, project: dict, run: dict, plan: dict, n: int, tried: list | None
) -> list[dict]:
    """The plan's changes as steps: the analysis and code's first, then the text's, built on it,
    each waiting on the user. The steps made, as saved; one that failed ends the review."""
    record = run["rounds"][-1]
    branch = record["reviewed"]["branch"]
    paper = {"path": run["manuscript"]["path"], "branch": run["manuscript"]["branch"]}
    made: list[dict] = []
    for action in ("analysis", "text"):
        items = [i for i in plan["items"] if i["action"] == action]
        if not items:
            continue
        text = _step_text(vault, run, items, action, n, made)
        asked = steps.asked_for(
            vault,
            project["id"],
            text,
            base=branch,
            manuscript=paper if action == "text" else None,
            by="review",
            approved=True,
            chars=STEP_CHARS,
        )
        _note(vault, run, f"Round {n}: revising", f"A step for the {action}: {len(items)} changes.")
        try:
            with llm.using(model=None if run["model"] == CLAUDE_CODE else run["model"]):
                step = steps.take(vault, project, _tick(), tried, asked=asked)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - said in the review, which stops
            steps.unqueue(vault, project["id"], asked["id"])  # a review's step isn't the night's
            why = " ".join(str(e).split())[:300]
            made.append({"status": "failed", "error": why})
            record["error"] = f"The {action} step failed: {why}"
            _note(vault, run, f"Round {n}: the {action} step failed", why)
            return made
        made.append(step)
        record["steps"].append(step["id"])
        branch = step["branch"]
        _save(vault, run)
    return made


def _step_text(
    vault: Path, run: dict, items: list[dict], action: str, n: int, made: list[dict]
) -> str:
    path = run["manuscript"]["path"]
    lines = []
    for i, item in enumerate(items, start=1):
        c = run["concerns"][item["id"]]
        where = f" (where: {c['where']})" if c["where"] else ""
        lines.append(f"{i}. {item['id']}{where}: {_text(item['change'])}")
    if action == "analysis":
        head = (
            f"Round {n} of the manuscript's peer review asks for these changes to the analysis "
            "and code. Make each, run what you change, and report the numbers and figures it gives "
            f"in found, each with the change's id. Don't change {path}: a step after this one "
            "revises its text from what you report."
        )
        return _clip("\n\n".join([head, "\n".join(lines)]), STEP_CHARS)
    head = (
        f"Revise the manuscript, {path}, as round {n} of its peer review planned: make each change "
        "below where it says, in the manuscript's own style and markup, and nothing else. Never "
        "invent a number, a result or a citation: where a number isn't known, leave a marked "
        "placeholder."
    )
    parts = [head, "\n".join(lines)]
    if made and made[-1].get("found"):
        parts.append(
            "The analysis step before this one, whose branch this builds on, found:\n"
            + str(made[-1]["found"])[:6000]
            + (
                f"\nIt couldn't: {str(made[-1]['couldnt'])[:1500]}"
                if made[-1].get("couldnt")
                else ""
            )
        )
    works = _works(vault, run, n)
    if works:
        parts.append(
            "Cite a work the paper doesn't cite yet only from these, which the scholarly indexes "
            "hold (add its entry as the paper keeps them):\n" + "\n".join(works)
        )
    else:
        parts.append("Cite no work the paper doesn't already cite.")
    return _clip("\n\n".join(parts), STEP_CHARS)


def _works(vault: Path, run: dict, n: int) -> list[str]:
    """The round's suggested reading the indexes found, one line each."""
    found = []
    for r in run["reviewers"]:
        answer = _json(_folder(vault, run["id"]) / f"round-{n}" / f"reviewer-{r['n']}.json")
        for w in answer.get("literature") or []:
            found.append(
                f"- {'; '.join(w.get('authors') or [])} ({w.get('year')}). {w.get('title')}."
                + (f" DOI {w['doi']}." if w.get("doi") else "")
            )
    return list(dict.fromkeys(found))


_LETTER = """\
You are {person}, the first author, writing the point-by-point response to the reviewers of round \
{round}, in your own voice: first person, plain and courteous, as the manuscript itself is written. \
Open with thanks and a short account of what changed. Then, for each reviewer in turn, each concern \
by its id and title in bold, then your answer: what changed and where for the text and the \
analysis, what's planned and why for later, and why not for declined. Answer the reviewers' \
questions too. Say only what the plan and the steps' reports say was done: where a step couldn't \
do something, say so plainly. Never invent a number, a result or a citation. Markdown, with a \
heading for each reviewer. No em dashes, no stock phrases, no closing summary."""


def _letter(
    vault: Path, run: dict, paper: str, asker: _Asker, n: int, plan: dict, made: list[dict]
) -> None:
    person = env("NAME", "the author")
    folder = _kept(vault, run["id"], n)
    reports = "\n\n".join(_read(folder / f"reviewer-{r['n']}.md") for r in run["reviewers"])
    did = []
    for step in made:
        if step.get("status") != "ready":
            did.append(f"A step failed and changed nothing: {step.get('error')}")
            continue
        did.append(
            f"Step {step['id']} ({step.get('step')}), on branch {step['branch']}, waiting for the "
            f"author to accept it:\nDid: {step.get('did')}\nFound: {step.get('found') or '-'}\n"
            f"Couldn't: {step.get('couldnt') or '-'}"
        )
    prompt = "\n\n---\n\n".join(
        [
            paper,
            f"The reviews of round {n}:\n\n{reports}",
            "The plan:\n\n" + _read(folder / "plan.md"),
            "What the revision's steps did:\n\n" + ("\n\n".join(did) or "No step was needed."),
        ]
    )
    _note(vault, run, f"Round {n}: writing the response", "The point-by-point letter.")
    text = ""
    for attempt in (1, 2):
        try:
            text = str(asker(prompt, _LETTER.format(person=person, round=n), None, LETTER_TOKENS))
        except (llm.ModelError, agent.AgentError) as e:
            if attempt == 2 or isinstance(e, agent.AgentUnavailable):
                raise ReviewError(f"the letter wasn't written ({e})") from e
            continue
        if text.strip():
            break
    if not text.strip():
        raise ReviewError("the letter came back empty")
    work._write(folder / "response.md", text.strip() + "\n")


# Where it's kept.


def _folder(vault: Path, run_id: str) -> Path:
    project_id, when = run_id.split("/")
    return vault / "clones" / "projects" / project_id / "reviews" / when


def _kept(vault: Path, run_id: str, n: int) -> Path:
    """A round's folder, made private at every level a review adds: mkdir's parents take the
    default mode."""
    folder = _folder(vault, run_id) / f"round-{n}"
    for level in (folder.parent.parent, folder.parent, folder):
        level.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def _path(vault: Path, run_id: str) -> Path:
    return _folder(vault, run_id).with_suffix(".json")


# Reviewers read at the same time, each saying so: one write of the review at a time.
_saving = threading.RLock()


def _save(vault: Path, run: dict) -> None:
    with _saving:
        run["updated"] = _iso(datetime.now(UTC))
        run["summary"] = _summary(run)
        work._write(_path(vault, run["id"]), json.dumps(run, ensure_ascii=False, indent=1))


def _note(vault: Path, run: dict, title: str, detail: str) -> None:
    with _saving:
        run["thread"].append({"at": _iso(datetime.now(UTC)), "title": title, "detail": detail})
        run["thread"] = run["thread"][-200:]
        _save(vault, run)


def _summary(run: dict) -> str:
    """Where the review stands, in a sentence or two."""
    if not run["rounds"]:
        return "Choosing the reviewers." if run["status"] == "working" else run.get("error") or ""
    last = run["rounds"][-1]
    n, of = last["n"], run["rounds_max"]
    if run["status"] == "failed":
        return f"Round {n} failed: {run.get('error') or 'it stopped before it finished.'}"
    if run["status"] == "working":
        doing = {
            "reviewing": "the reviewers are reading",
            "planning": "planning the response",
            "revising": "the revision's steps are being taken",
            "writing": "writing the response letter",
        }.get(last["status"], last["status"])
        return f"Round {n} of {of}: {doing}."
    waiting = sum(len(r["steps"]) for r in run["rounds"])
    majors = last["open_major"]
    said = f"{n} round{'s' * (n != 1)}: " + (
        "no major concern left"
        if majors == 0
        else f"{majors} major concern{'s' * (majors != 1)} open"
    )
    if run["status"] == "stopped":
        said += f". It stopped: {last.get('error') or 'a step is no longer waiting on you'}"
    if waiting:
        said += f". {waiting} step{'s' * (waiting != 1)} of revision wait on you"
    return said + "."


def runs(vault: Path, project_id: str, limit: int = RUNS_KEPT) -> list[dict]:
    """The project's reviews, newest first."""
    found = []
    folder = vault / "clones" / "projects" / project_id / "reviews"
    for path in sorted(folder.glob("*.json"), reverse=True)[:limit]:
        run = _json(path)
        if run.get("id") == f"{project_id}/{path.stem}":
            found.append(run)
    return found


def letter(vault: Path, project_id: str) -> tuple[int, str] | None:
    """The newest response letter of the project's reviews, (its round, its text), for the
    project's cloud folder; None when there's none."""
    for run in runs(vault, project_id):
        for record in reversed(run.get("rounds") or []):
            if record.get("response"):
                text = _read(_folder(vault, run["id"]) / f"round-{record['n']}" / "response.md")
                if text.strip():
                    return record["n"], text
    return None


def _settle(vault: Path, project_id: str) -> None:
    """A review still "working" while no one holds its project's lock ended without saying so."""
    for run in runs(vault, project_id, 5):
        if run.get("status") == "working":
            run["status"] = "failed"
            run["error"] = "It stopped before it finished."
            run.setdefault("thread", [])
            _note(vault, run, "Stopped", "It stopped before it finished.")


def _worktree(repo: Path, asker: _Asker, run: dict, commit: str, n: int) -> None:
    """A worktree of the commit reviewed, for Claude Code to read, the last round's gone."""
    _drop_worktree(repo, asker)
    when = run["id"].split("/")[1]
    folder = steps.worktrees() / run["project"] / f"review-{when}-{n}"
    folder.parent.mkdir(parents=True, exist_ok=True)
    steps._git(repo, "worktree", "add", "-q", "--detach", str(folder), commit)
    asker.folder = folder


def _drop_worktree(repo: Path, asker: _Asker) -> None:
    if asker.folder is not None:
        steps.remove_worktree(repo, asker.folder)
        if asker.folder.exists() and asker.folder.is_relative_to(steps.worktrees()):
            shutil.rmtree(asker.folder, ignore_errors=True)
        asker.folder = None


_last_tick: datetime | None = None


def _tick() -> datetime:
    """Now, at least a second after the last step this process made, so no two share an id."""
    global _last_tick
    now = datetime.now(UTC).replace(microsecond=0)
    if _last_tick is not None and now <= _last_tick:
        now = _last_tick + timedelta(seconds=1)
    _last_tick = now
    return now


# Small helpers.


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _clip(text: str, chars: int) -> str:
    return text if len(text) <= chars else text[: chars - 1] + "…"


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# The night, for a project that opts in.


def night(vault: Path, now: datetime | None = None, **given) -> dict[str, int]:
    """A review of each project with "autoreview": true whose manuscript changed since its last
    review, when that's EVERY_DAYS old and none of its steps still waits on the user. Nothing
    is reviewed otherwise."""
    now = now or datetime.now(UTC)
    stats: Counter = Counter(reviews_done=0, reviews_failed=0, reviews_waiting=0)
    for project in projects.listed_projects(vault):
        if not project.get("autoreview") or project["paused"] or not project["repo"]:
            continue
        last = next(iter(runs(vault, project["id"], 1)), None)
        if last and _waiting(vault, last):
            stats["reviews_waiting"] += 1
            continue
        try:
            if last:
                age = now - datetime.fromisoformat(last["created"])
                found = manuscript.find(project)
                tip = manuscript._tip(steps._repo(project), found["branch"]) if found else ""
                if age < timedelta(days=EVERY_DAYS) or tip == last["manuscript"].get("commit"):
                    stats["reviews_unchanged"] += 1
                    continue
            review(vault, project, now=now, **given)
            stats["reviews_done"] += 1
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one project must not stop the rest
            stats["reviews_failed"] += 1
            print(
                f"review: {project['id']} failed ({' '.join(str(e).split())[:200]})",
                file=sys.stderr,
            )
    return dict(stats)


def _waiting(vault: Path, run: dict) -> bool:
    """Whether the review is going, or a step it made still waits on the user."""
    if run.get("status") == "working":
        return True
    made = [s for r in run.get("rounds") or [] for s in r.get("steps") or []]
    return any(steps._load_quietly(vault, s).get("status") == "ready" for s in made)


# The command.


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "id", nargs="?", help="the project's id, as in clones/projects/projects.json"
    )
    parser.add_argument(
        "--all", action="store_true", help="every project with a repo and a manuscript, in turn"
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=ROUNDS,
        choices=range(1, MAX_ROUNDS + 1),
        metavar="N",
        help=f"up to this many rounds, stopping once no major concern is left (default {ROUNDS})",
    )
    parser.add_argument(
        "--reviewers",
        type=int,
        default=REVIEWERS,
        choices=(2, 3),
        metavar="N",
        help=f"two or three reviewers (default {REVIEWERS})",
    )


def run(vault: Path, args: argparse.Namespace) -> list[str]:
    """Review the project, or with --all each one with a manuscript, but those kept out of the
    cloud ("cloud": false, an immigration petition, say), whose papers go to a hosted model only
    when named. A line for each, the last saying where the review stands, for the page's job."""
    listed = projects.listed_projects(vault)
    if bool(args.id) == bool(args.all):
        raise SystemExit("review: name a project, or give --all")
    if args.id:
        chosen = [p for p in listed if p["id"] == args.id]
        if not chosen:
            raise SystemExit(f"review: no project {args.id!r} in clones/projects/projects.json")
    else:
        chosen = [p for p in listed if p["repo"] and not p["paused"]]
    said, failed = [], 0
    for project in chosen:
        if args.all and not project["cloud"]:
            said.append(
                f'review: {project["id"]}: kept out of the cloud ("cloud": false), so '
                "only when you name it"
            )
            continue
        if args.all:
            try:
                if manuscript.find(project) is None:
                    said.append(f"review: {project['id']}: no manuscript, so no review")
                    continue
            except SystemExit as e:
                said.append(f"review: {project['id']}: {e}")
                continue
        try:
            done = review(vault, project, rounds=args.rounds, reviewers=args.reviewers)
        except (Exception, SystemExit) as e:
            if not args.all:
                raise
            failed += 1
            said.append(f"review: {project['id']} failed ({' '.join(str(e).split())[:200]})")
            continue
        said.append(f"review: {project['id']}: {done['summary']}")
    if args.all and not said:
        said.append("review: no project has a repo and a manuscript")
    if failed and failed == len(said):
        raise SystemExit("\n".join(said))
    return said
