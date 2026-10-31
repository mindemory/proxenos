"""The step runners, with Claude Code's process and the local model faked out. Nothing runs a
model or Claude Code."""

import json
import subprocess

import pytest

from proxenos import agent

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
    assert (
        settings["sandbox"] | {"enabled": True, "allowUnsandboxedCommands": False}
        == settings["sandbox"]
    )
    assert settings["sandbox"]["network"] == {"allowedDomains": []}
    deny = settings["permissions"]["deny"]
    assert f"Read(/{vault.resolve()}/**)" in deny and f"Read(/{secrets.resolve()})" in deny
    assert f"Edit(/{data.resolve()}/**)" in deny and "Bash(git push:*)" in deny
    # The brief goes on stdin, never on the command line, which other processes can read.
    assert call["stdin"] == "The project: Calls" and "The project: Calls" not in args
    assert call["timeout"] == agent.MINUTES * 60
    # Its own account: no API key, nor a host app's settings; caches kept in the worktree.
    env = call["env"]
    assert not any(k.startswith(("ANTHROPIC_", "CLAUDE")) for k in env)
    assert env["PATH"].split(":")[0] == "/envs/calls/bin"
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
            "couldn't start: Credit balance is too low",
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
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 30 &\nsleep 30\n")
    script.chmod(0o755)
    with pytest.raises(agent.AgentError, match="ran past its 0 minutes"):
        agent._run([str(script)], tmp_path, {"PATH": "/bin:/usr/bin"}, "", 1)


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
