"""The step runners, with Claude Code's process and the local model faked out. Nothing runs a
model or Claude Code."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from proxenos import agent, llm

REPORT = {
    "step": "Count the notes per species",
    "why": "The paper's table 1 needs them.",
    "did": "Ran `count.py`.",
    "found": "1,204 notes.",
    "figures": [],
    "couldnt": "",
    "next": "Table 1.",
    "commit": "",
}


def task(tmp_path, **kw):
    folder = tmp_path / "worktree"
    folder.mkdir(exist_ok=True)
    return agent.Task(person="Joe", brief="The project: Calls", folder=folder, **kw)


class Claude:
    """Claude Code's process, faked: what it was started with, and what it answers."""

    def __init__(self, answer=None, code=0, stderr=""):
        self.calls = []
        self.answer = answer if answer is not None else self.done(REPORT)
        self.code, self.stderr = code, stderr

    @staticmethod
    def done(report, **kw):
        return {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 9,
            "total_cost_usd": 0.4321,
            "result": "Done.",
            "structured_output": report,
        } | kw

    def __call__(self, args, cwd, environment, stdin, timeout):
        self.calls.append(
            {"args": args, "cwd": cwd, "env": environment, "stdin": stdin, "timeout": timeout}
        )
        out = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return self.code, out, self.stderr


def test_claude_code_works_in_its_sandbox_on_its_own_account(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-for-claude-code")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("CLAUDE_CODE_SIMPLE", "1")
    monkeypatch.setenv("PROXENOS_STEP_BUDGET", "2")
    vault, data = tmp_path / "vault", tmp_path / "data"
    vault.mkdir()
    data.mkdir()
    secrets = tmp_path / "settings.json"
    secrets.write_text("{}")
    claude = Claude()
    t = task(tmp_path, data=[data], hidden=[vault, secrets], python="/envs/calls/bin/python")

    report = agent.ClaudeCode("/bin/claude", run=claude)(t)

    assert report == REPORT | {"meta": {"turns": 9, "cost_usd": 0.43}}
    [call] = claude.calls
    args = call["args"]
    assert args[:2] == ["/bin/claude", "-p"] and call["cwd"] == t.folder
    flag = {a: args[i + 1] for i, a in enumerate(args[:-1]) if a.startswith("--")}
    assert flag["--tools"] == flag["--allowedTools"] == "Read,Edit,Write,Glob,Grep,Bash"
    assert flag["--permission-mode"] == "dontAsk" and flag["--setting-sources"] == ""
    assert flag["--max-turns"] == str(agent.TURNS) and flag["--max-budget-usd"] == "2"
    assert flag["--add-dir"] == str(data) and json.loads(flag["--json-schema"]) == agent.REPORT
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    assert "Run Python with /envs/calls/bin/python." in flag["--append-system-prompt"]
    settings = json.loads(flag["--settings"])
    sandbox = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True}
    assert settings["sandbox"] | sandbox == settings["sandbox"]  # never a command outside it
    assert settings["sandbox"]["network"] == {"allowedDomains": []}
    assert settings["sandbox"]["filesystem"]["denyRead"] == [
        str(vault.resolve()),
        str(secrets.resolve()),
    ]
    deny = settings["permissions"]["deny"]
    assert f"Read(/{vault.resolve()}/**)" in deny and f"Read(/{secrets.resolve()})" in deny
    assert f"Edit(/{data.resolve()}/**)" in deny and "Bash(git push:*)" in deny
    # The brief goes on stdin, never on the command line, which other processes can read.
    assert call["stdin"] == "The project: Calls" and "The project: Calls" not in args
    assert call["timeout"] == agent.MINUTES * 60
    # Its own account: no API key, nor a host app's settings; caches kept in the worktree.
    env = call["env"]
    assert not any(k.startswith(("ANTHROPIC_", "CLAUDE")) for k in env)
    assert env["PATH"].split(os.pathsep)[0] == str(Path("/envs/calls/bin"))
    assert env["PROXENOS_OUT"] == str(t.folder.resolve() / ".proxenos" / "out")
    assert env["MPLBACKEND"] == "Agg"
    assert env["MPLCONFIGDIR"].startswith(str(t.folder.resolve()))


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        (
            {
                "subtype": "success",
                "is_error": True,
                "result": "Credit balance is too low",
                "terminal_reason": "api_error",
                "modelUsage": {},
            },
            agent.AgentUnavailable,
            "^Credit balance is too low$",
        ),
        (
            {"subtype": "error_max_turns", "is_error": True, "modelUsage": {"m": {}}},
            agent.AgentError,
            "used its 100 turns",
        ),
        (
            {"subtype": "error_max_budget_usd", "is_error": True, "modelUsage": {"m": {}}},
            agent.AgentError,
            "spending budget",
        ),
        (Claude.done({"step": ""}), agent.AgentError, "without a report"),
        ("Not logged in", agent.AgentError, "gave no answer"),
    ],
)
def test_claude_code_that_stops_short_says_why(tmp_path, answer, error, message):
    with pytest.raises(error, match=message):
        agent.ClaudeCode("/bin/claude", run=Claude(answer))(task(tmp_path))


def test_a_report_given_as_text_is_read_too(tmp_path):
    answer = Claude.done(None, result="Here it is:\n" + json.dumps(REPORT))
    assert agent.ClaudeCode("/bin/claude", run=Claude(answer))(task(tmp_path))["step"] == (
        "Count the notes per species"
    )


def test_a_run_past_its_time_is_stopped_with_its_commands(tmp_path, monkeypatch):
    # A command that starts another and waits, in Python so it runs the same on every system.
    child = "import time; time.sleep(30)"
    slow = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); "
    slow += "time.sleep(30)"
    with pytest.raises(agent.AgentError, match="ran past its 0 minutes"):
        agent._run([sys.executable, "-c", slow], tmp_path, dict(os.environ), "", 1)


class Model:
    def __init__(self, files):
        self.calls = []
        self.files = files
        self.read = ["count.py", "../outside.py", "missing.py"]

    def __call__(self, prompt, *, system=None, schema=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
        if "read" in schema["properties"]:
            return {"step": "Draft the methods", "why": "Reviewers asked.", "read": self.read}
        return {
            "files": self.files,
            "did": "Wrote `methods.md`.",
            "couldnt": "The sample sizes need checking.",
            "next": "Check them.",
            "commit": "Draft the methods section.",
        }


def test_the_local_model_writes_but_runs_nothing_and_says_so(tmp_path):
    t = task(tmp_path)
    subprocess.run(["git", "init", "-q", str(t.folder)], check=True)
    (t.folder / "count.py").write_text("print(len(notes))\n")
    subprocess.run(["git", "-C", str(t.folder), "add", "count.py"], check=True)
    model = Model(
        [
            {"path": "docs/methods.md", "content": "# Methods\n\nWe counted notes."},
            {"path": "../escape.md", "content": "no"},
            {"path": ".git/hooks/pre-commit", "content": "no"},
            {"path": "/etc/hosts", "content": "no"},
            {"path": "empty.md", "content": "  "},
        ]
    )

    report = agent.Local(model)(t)

    assert report["step"] == "Draft the methods" and report["why"] == "Reviewers asked."
    assert report["found"] == "" and report["figures"] == []
    assert report["couldnt"].startswith(agent.LOCAL_LIMITS)
    assert report["couldnt"].endswith("The sample sizes need checking.")
    assert (t.folder / "docs" / "methods.md").read_text() == "# Methods\n\nWe counted notes.\n"
    assert not (tmp_path / "escape.md").exists() and not (t.folder / "empty.md").exists()
    assert "count.py" in model.calls[0]["prompt"]  # the repository's files, by name
    # It read the file it asked for, and nothing outside the repository.
    assert '<file path="count.py">\nprint(len(notes))' in model.calls[1]["prompt"]
    assert "outside.py" not in model.calls[1]["prompt"]


def test_which_runners_are_tried(monkeypatch):
    monkeypatch.setattr(agent, "claude_bin", lambda: "/bin/claude")
    assert [r.name for r in agent.runners()] == ["claude", "local"]
    monkeypatch.setenv("PROXENOS_STEP_RUNNER", "local")
    assert [r.name for r in agent.runners()] == ["local"]
    monkeypatch.setenv("PROXENOS_STEP_RUNNER", "claude")
    assert [r.name for r in agent.runners()] == ["claude"]
    monkeypatch.setenv("PROXENOS_STEP_RUNNER", "gpt")
    with pytest.raises(SystemExit, match="give claude or local"):
        agent.runners()
    monkeypatch.setattr(agent, "claude_bin", lambda: None)
    monkeypatch.setenv("PROXENOS_STEP_RUNNER", "claude")
    with pytest.raises(SystemExit, match="isn't here"):
        agent.runners()
    monkeypatch.delenv("PROXENOS_STEP_RUNNER")
    assert [r.name for r in agent.runners()] == ["local"]


def test_a_path_from_a_model_stays_in_the_folder(tmp_path):
    assert agent.inside(tmp_path, "a/b.md") == tmp_path.resolve() / "a" / "b.md"
    for bad in ("", ".", "../x", "a/../../x", "/etc/x", ".git/config", ".proxenos/out/x"):
        assert agent.inside(tmp_path, bad) is None


# The local model on a long document: it reads the sections a step needs and changes it by edits.


def paper() -> str:
    """A made-up LaTeX paper of about 64,000 characters, in four sections of numbered lines."""
    parts = ["\\documentclass{article}\n\\begin{document}\n"]
    parts.append("\\begin{abstract}\nCalls rise at dusk.\n\\end{abstract}\n")
    for name in ("Introduction", "Methods", "Results", "Discussion"):
        parts.append(f"\\section{{{name}}}\n\\label{{sec:{name.lower()}}}\n")
        if name == "Methods":
            parts.append("\\subsection{Recordings}\n")
        parts += [f"{name} line {i}: the squirrels call.\n" for i in range(400)]
    return "".join([*parts, "\\end{document}\n"])


def repo(t, files):
    subprocess.run(["git", "init", "-q", str(t.folder)], check=True)
    for rel, text in files.items():
        (t.folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (t.folder / rel).write_bytes(text.encode())
    subprocess.run(["git", "-C", str(t.folder), "add", "."], check=True)


class Held:
    """The local model, faked: it answers the pick and then the write, each held to its schema
    as a local model's answer is, and keeps what it was asked."""

    def __init__(self, pick, write):
        self.answers = [pick, write]
        self.calls = []

    def __call__(self, prompt, *, system=None, schema=None, **kw):
        self.calls.append({"prompt": prompt, "system": system, **kw})
        answer = llm._object(json.dumps(self.answers[len(self.calls) - 1]), schema)
        assert answer is not None, "the answer doesn't fit the schema"
        return answer


def write(**kw):
    said = {"did": "Tightened it.", "couldnt": "", "next": "Read it.", "commit": "Tighten it."}
    return said | kw


def test_a_long_document_is_read_by_the_sections_asked_for_and_changed_by_edits(tmp_path):
    t = task(tmp_path)
    text = paper()
    repo(t, {"paper/main.tex": text, "count.py": "print(1)\n"})
    pick = {
        "step": "Tighten the discussion",
        "why": "It runs long.",
        "read": ["paper/main.tex"],
        "sections": [{"path": "paper/main.tex", "heading": "Discussion"}],
    }
    find = "Discussion line 7: the squirrels call.\n"
    edit = {"path": "paper/main.tex", "find": find, "replace": "Discussion line 7, tightened.\n"}
    model = Held(pick, write(edits=[edit]))

    report = agent.Local(model)(t)

    # It saw the paper's outline when it picked, each section with its length.
    outline = model.calls[0]["prompt"]
    assert f"paper/main.tex ({len(text):,}):" in outline
    assert "\n- Discussion (" in outline and "\n  - Recordings (" in outline
    # It read the Discussion alone, the rest marked as not shown.
    shown = model.calls[1]["prompt"]
    assert "Discussion line 399" in shown and "Methods line 5:" not in shown
    assert "characters not shown]" in shown and len(shown) < 20_000
    assert model.calls[1]["max_tokens"] == agent.ANSWER_TOKENS
    # One line changed, and nothing else.
    assert (t.folder / "paper/main.tex").read_text() == text.replace(
        find, "Discussion line 7, tightened.\n"
    )
    assert report["couldnt"] == agent.LOCAL_LIMITS
    assert report["meta"] == {"files_read": 1, "edits": 1, "not_applied": 0}


def test_an_edit_whose_text_to_find_isnt_there_exactly_once_isnt_made(tmp_path):
    t = task(tmp_path)
    text = paper()
    repo(t, {"paper/main.tex": text})
    # No section asked for: those the step names are read.
    pick = {"step": "Rename the results section", "why": "Clearer.", "read": ["paper/main.tex"]}
    edits = [
        {"path": "paper/main.tex", "find": "the squirrels call.", "replace": "they call."},
        {"path": "paper/main.tex", "find": "\\label{sec:results}", "replace": "\\label{sec:found}"},
        {"path": "paper/main.tex", "find": "a line it made up", "replace": "x"},
        {"path": "paper/missing.tex", "find": "x", "replace": "y"},
    ]
    model = Held(pick, write(edits=edits, couldnt="Check the cross-references."))

    report = agent.Local(model)(t)

    assert "Results line 0:" in model.calls[1]["prompt"]
    after = (t.folder / "paper/main.tex").read_text()
    assert after == text.replace("\\label{sec:results}", "\\label{sec:found}")
    assert report["couldnt"].startswith(agent.LOCAL_LIMITS + " Not applied: ")
    assert report["couldnt"].endswith("Check the cross-references.")
    once = "an edit to `paper/main.tex` whose text to find, `the squirrels call.`, is in it more"
    assert once + " than once" in report["couldnt"]
    assert "`a line it made up`, isn't in it" in report["couldnt"]
    assert "an edit to `paper/missing.tex`, not a text file in the repository" in report["couldnt"]
    assert report["meta"]["edits"] == 1 and report["meta"]["not_applied"] == 3


def test_new_files_and_edits_together_and_no_part_read_file_is_written_whole(tmp_path):
    t = task(tmp_path)
    text = paper()
    notes = "# Notes\r\n\r\n- todo: methods\r\n- todo: figures\r\n"
    repo(t, {"paper/main.tex": text, "notes.md": notes, "count.py": "print(1)\n"})
    pick = {
        "step": "Describe the recordings",
        "why": "Reviewers asked.",
        "read": ["notes.md"],
        "sections": [{"path": "paper/main.tex", "heading": "Methods (16,000)"}],
    }
    added = "\\subsection{Recordings}\nWe recorded at dawn and dusk.\n"
    # \begin and \frac with their backslashes left single, which JSON reads as control characters.
    slipped = {"find": "\begin{abstract}\n", "replace": "\begin{abstract}\n\frac{1}{2} call.\n"}
    answer = write(
        files=[
            {"path": "scripts/plot_calls.py", "content": "import sys\nprint(sys.argv)"},
            {"path": "paper/main.tex", "content": "\\documentclass{article}\n"},
            {"path": "count.py", "content": "print(2)\n"},
        ],
        edits=[
            {"path": "paper/main.tex", "find": "\\subsection{Recordings}\n", "replace": added},
            {"path": "notes.md", "find": "- todo: methods\n", "replace": "- done: methods\n"},
            {"path": "paper/main.tex", **slipped},
        ],
    )
    model = Held(pick, answer)

    report = agent.Local(model)(t)

    # The section asked for came with its subsection, and the file it named was read too.
    assert "Recordings}\nMethods line 0:" in model.calls[1]["prompt"]
    assert (t.folder / "scripts/plot_calls.py").read_text() == "import sys\nprint(sys.argv)\n"
    assert (t.folder / "paper/main.tex").read_text() == text.replace(
        "\\subsection{Recordings}\n", added
    ).replace("\\begin{abstract}\n", "\\begin{abstract}\n\\frac{1}{2} call.\n")
    # The notes keep their own line ends.
    assert (t.folder / "notes.md").read_bytes() == notes.replace(
        "todo: methods", "done: methods"
    ).encode()
    assert (t.folder / "count.py").read_text() == "print(1)\n"  # never read, so never replaced
    assert "`paper/main.tex` in full, as it was read in part or not at all" in report["couldnt"]
    assert "`count.py` in full" in report["couldnt"]
    assert report["meta"] == {"files_read": 2, "edits": 3, "not_applied": 2}


def test_an_answer_of_whole_files_alone_is_still_taken(tmp_path):
    t = task(tmp_path)
    repo(t, {"count.py": "print(len(notes))\n"})
    pick = {"step": "Count by species", "why": "Table 1.", "read": ["count.py"]}
    answer = {  # as answers were before there were edits
        "files": [
            {"path": "count.py", "content": "print(len(set(notes)))"},
            {"path": "docs/methods.md", "content": "# Methods\n"},
        ],
        "did": "Changed `count.py`.",
        "couldnt": "",
        "next": "Run it.",
        "commit": "Count by species.",
    }
    model = Held(pick, answer)

    report = agent.Local(model)(t)

    assert (t.folder / "count.py").read_text() == "print(len(set(notes)))\n"
    assert (t.folder / "docs/methods.md").read_text() == "# Methods\n"
    assert report["couldnt"] == agent.LOCAL_LIMITS and report["commit"] == "Count by species."


def test_a_local_models_prompt_and_answer_fit_its_context_whatever_the_files(tmp_path, monkeypatch):
    assert agent.ANSWER_TOKENS <= llm.LOCAL_CONTEXT // 4  # the room llm.fit leaves the answer
    monkeypatch.setenv("PROXENOS_MODEL", "ollama:gemma4:26b")
    t = task(tmp_path)
    t.brief = "The project: Calls. " + "Where it stands. " * 6000  # about 100,000 characters
    long = {f"paper/part{i}.tex": paper() for i in range(4)}
    repo(t, long | {"paper/main.tex": paper()})
    pick = {
        "step": "Revise the paper",
        "why": "It's due.",
        "read": ["paper/main.tex", *long],
        "sections": [
            {"path": p, "heading": h}
            for p in ["paper/main.tex", *long]
            for h in ("Introduction", "Methods", "Results", "Discussion")
        ],
    }
    answers = iter([pick, write(edits=[])])
    sent = []

    def chat(model, body, answer_room):
        sent.append((body, answer_room))
        return json.dumps(next(answers))

    monkeypatch.setattr(llm, "_chat", chat)

    agent.Local(llm.ask)(t)  # the real llm.ask, which refuses a prompt past the context

    body, answer_room = sent[1]
    assert answer_room == agent.ANSWER_TOKENS == body["options"]["num_predict"]
    said = sum(len(m["content"]) for m in body["messages"])
    assert said // 3 <= llm.LOCAL_CONTEXT - answer_room
    assert said > 140_000  # the files filled what room there was
