"""The one place Proxenos lets a model work in a folder: a project's own code, checked out on a
branch of its own (a git worktree), to take one step of the project's work and report it.

Two runners, picked by PROXENOS_STEP_RUNNER: "claude", "local", or empty for Claude Code where
it's installed, then the local model.
- Claude Code, headless (`claude -p`): it reads the code, runs it, changes it and runs it again,
  with only the tools in TOOLS, inside Claude Code's sandbox. Its commands can write only in the
  worktree and reach no network, and nothing it does can read the vault or the user's keys. It
  runs on the account Claude Code is signed in to, never on Proxenos's own API key, which is kept
  from it, within MINUTES, TURNS and a spending budget (PROXENOS_STEP_BUDGET, in dollars).
- The local model, through llm.ask, for anyone without Claude Code. It can't run anything: it
  reads a few of the project's files and writes (a script, a fix, a section as markdown), and
  its report says plainly that nothing was run.

Each takes a Task and returns the report REPORT describes. Neither commits, merges or pushes;
proxenos.clones.steps does what comes after.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from proxenos import llm
from proxenos.config import env

OUT = Path(".proxenos", "out")  # in the worktree: the figures and tables for the report
CACHE = Path(".proxenos", "cache")  # in the worktree: caches its commands would keep elsewhere
MINUTES = 30
TURNS = 100
BUDGET_USD = "5"
TOOLS = "Read,Edit,Write,Glob,Grep,Bash"
_CLAUDE_PLACES = ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", "~/.local/bin/claude")
_CLAUDE_PLACES += ("~/.claude/local/claude",)
# What Claude Code's environment keeps from Proxenos's: no API key, no host app's settings.
_KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SHELL", "TERM")
_SYSTEM_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
LISTED = 400  # of the repository's files, the local model reads the names of
READ_FILES = 6  # the local model reads at most these in full
FILE_CHARS = 12_000
WRITE_FILES = 3
WRITE_CHARS = 60_000

REPORT = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "why": {"type": "string"},
        "did": {"type": "string"},
        "found": {"type": "string"},
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"file": {"type": "string"}, "caption": {"type": "string"}},
                "required": ["file", "caption"],
                "additionalProperties": False,
            },
        },
        "couldnt": {"type": "string"},
        "next": {"type": "string"},
        "commit": {"type": "string"},
    },
    "required": ["step", "why", "did", "found", "figures", "couldnt", "next", "commit"],
    "additionalProperties": False,
}

_REPORT_FIELDS = """\
- step: the step you took, in one line.
- why: why this step now, in a sentence or two.
- did: what you did, in short markdown: what you read, what you changed, what you ran.
- found: what it shows, in markdown: the numbers and what they mean, each from what you ran, \
or "" when the step was writing only.
- figures: each figure in {out} worth showing, by file name, with a one-line caption.
- couldnt: what you couldn't do or didn't check, and why; "" when nothing.
- next: the step after this one, in a sentence or two.
- commit: a commit message for what you changed, one plain sentence; "" when you changed no \
file."""

_SYSTEM = """\
You are {person}'s digital twin, working on one of their research projects while they're away. \
You're in a git worktree of the project's code, on a branch of your own. Take one step of the \
project's work, the next one that matters and that you can finish now, and report it, so \
{person} can read what you did and what it shows and accept it as done.

How to work:
- One step, done: run an analysis and read its numbers, fix a script and run it, make a figure, \
or draft a section of the paper as markdown. Not a plan for later. When you can't do it, say \
why in the report.
- Read before you change: the README, the scripts the step touches, how they're run.
- Only this folder is writable; the data folders are read-only. A script that saves into a data \
folder will fail there, so run it with its outputs in {out} instead (a parameter, an \
environment variable or a small runner script), without changing where it saves for {person} \
unless that is the step.
- Every figure and table you make for the report goes in {out} ($PROXENOS_OUT), figures as \
PNG. They're shown with the report and not committed.
- {python}{matlab}
- Small changes, in the project's own style. Don't commit: Proxenos commits what you leave \
here, and {person} accepts or discards it.
- Commands have no network: install, download and send nothing, and contact no one.
- Every number in the report comes from what you ran, never from memory or a guess.

End with the report:
{fields}"""


class AgentError(RuntimeError):
    """The runner stopped without a report."""


class AgentUnavailable(AgentError):
    """The runner couldn't start (not signed in, out of credit), so it changed nothing."""


@dataclass
class Task:
    """One step's work: the brief (the project, where it stands, what to do) and where."""

    person: str
    brief: str
    folder: Path  # the worktree, the only folder it may write in
    data: list[Path] = field(default_factory=list)  # read-only
    hidden: list[Path] = field(default_factory=list)  # not to be read at all
    python: str = ""
    matlab: str = ""


Runner = Callable[[Task], dict]


def runners(model: Callable[..., object] = llm.ask) -> list:
    """The runners to try, in order: the one PROXENOS_STEP_RUNNER names, or Claude Code where
    it's installed and then the local model, which takes over when Claude Code can't start."""
    choice = env("STEP_RUNNER").strip().lower()
    claude = claude_bin()
    if choice == "local":
        return [Local(model)]
    if choice == "claude":
        if not claude:
            raise SystemExit("steps: PROXENOS_STEP_RUNNER is claude, but Claude Code isn't here")
        return [ClaudeCode(claude)]
    if choice:
        raise SystemExit(f"steps: PROXENOS_STEP_RUNNER is {choice!r}: give claude or local")
    return [ClaudeCode(claude), Local(model)] if claude else [Local(model)]


def claude_bin() -> str | None:
    """Claude Code's command, where its sandbox works (macOS, or Linux with bubblewrap); None
    elsewhere, since without the sandbox its commands could write anywhere."""
    if sys.platform == "linux" and not shutil.which("bwrap"):
        return None
    if sys.platform not in ("darwin", "linux"):
        return None
    for place in (env("CLAUDE_BIN"), shutil.which("claude"), *_CLAUDE_PLACES):
        if place and os.access(path := os.path.expanduser(place), os.X_OK):
            return path
    return None


# Claude Code.

# (args, cwd, env, stdin, timeout in seconds) → (exit status, stdout, stderr)
Run = Callable[[list[str], Path, dict[str, str], str, int], tuple[int, str, str]]


class ClaudeCode:
    name = "claude"
    label = "Claude Code"

    def __init__(self, binary: str, run: Run | None = None):
        self.binary = binary
        self.run = run or _run

    def __call__(self, task: Task) -> dict:
        system = _SYSTEM.format(
            person=task.person,
            out=OUT,
            python=f"Run Python with {task.python}." if task.python else "Run Python with python3.",
            matlab=f" MATLAB is {task.matlab}, run as `{task.matlab} -batch`."
            if task.matlab
            else "",
            fields=_REPORT_FIELDS.format(out=OUT),
        )
        args = [
            self.binary,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(REPORT),
            "--append-system-prompt",
            system,
            "--tools",
            TOOLS,
            "--allowedTools",
            TOOLS,
            "--permission-mode",
            "dontAsk",
            "--settings",
            json.dumps(_settings(task)),
            "--setting-sources",
            "",  # none of the user's own settings, hooks or allow rules
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns",
            str(TURNS),
            "--max-budget-usd",
            env("STEP_BUDGET", BUDGET_USD),
        ]
        for folder in task.data:
            args += ["--add-dir", str(folder)]
        if model := env("STEP_MODEL").strip():
            args += ["--model", model]
        code, stdout, stderr = self.run(
            args, task.folder, _environment(task), task.brief, MINUTES * 60
        )
        return _answer(code, stdout, stderr)


def _settings(task: Task) -> dict:
    """The sandbox: commands write only in the worktree and reach no network; nothing reads the
    hidden folders, and nothing edits the data or hidden ones."""
    hidden = [f"Read({_rule(p)})" for p in task.hidden]
    kept = [f"Edit({_rule(p)})" for p in [*task.data, *task.hidden]]
    return {
        "sandbox": {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": []},
        },
        "permissions": {
            "deny": [*hidden, *kept, "Bash(git push:*)", "Bash(git remote:*)", "WebFetch"],
        },
    }


def _rule(path: Path) -> str:
    """A permission rule's form of a file, or of a folder and all in it: //abs/path/**."""
    path = path.expanduser().resolve()
    return "/" + str(path).rstrip("/") + ("/**" if path.is_dir() else "")


def _environment(task: Task) -> dict[str, str]:
    """Claude Code's environment: the user's home and locale, a PATH with the project's Python
    first, caches kept in the worktree, figures drawn without a window; no API key, so it runs
    on the account it's signed in to."""
    folder = task.folder.resolve()
    first = [str(Path(p).parent) for p in (task.python,) if p]
    environment = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    cache = folder / CACHE
    return environment | {
        "PATH": os.pathsep.join([*first, *_SYSTEM_PATH]),
        "PROXENOS_OUT": str(folder / OUT),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(cache / "matplotlib"),
        "XDG_CACHE_HOME": str(cache),
        "MATLAB_PREFDIR": str(cache / "matlab"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(
    args: list[str], cwd: Path, environment: dict[str, str], stdin: str, timeout: int
) -> tuple[int, str, str]:
    """Run it in a process group of its own, so on timeout its commands stop with it."""
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
                proc.wait(timeout=10)
                break
            except (OSError, subprocess.TimeoutExpired):
                continue
        raise AgentError(f"it ran past its {timeout // 60} minutes and was stopped") from None
    return proc.returncode, stdout, stderr


def _answer(code: int, stdout: str, stderr: str) -> dict:
    """The report from Claude Code's answer, or why there's none."""
    try:
        answer = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        why = _last(stderr) or _last(stdout) or f"it exited with status {code}"
        raise AgentError(f"Claude Code gave no answer ({why})")
    meta = {
        "turns": answer.get("num_turns") or 0,
        "cost_usd": round(float(answer.get("total_cost_usd") or 0), 2),
    }
    if answer.get("is_error") or answer.get("subtype") != "success":
        why = _text(answer.get("result")) or {
            "error_max_turns": f"it used its {TURNS} turns before it reported",
            "error_max_budget_usd": "it reached its spending budget before it reported",
        }.get(str(answer.get("subtype")), str(answer.get("subtype") or "it failed"))
        if answer.get("terminal_reason") == "api_error" and not answer.get("modelUsage"):
            raise AgentUnavailable(f"Claude Code couldn't start: {why}")
        raise AgentError(f"Claude Code stopped: {why}")
    report = answer.get("structured_output")
    if not isinstance(report, dict):
        report = _json_in(str(answer.get("result") or ""))
    if not isinstance(report, dict) or not _text(report.get("step")):
        raise AgentError("Claude Code finished without a report")
    return report | {"meta": meta}


# The local model.

LOCAL_LIMITS = (
    "The local model can't run code, so nothing was run: what it wrote is untested, and there "
    "are no numbers or figures of its own."
)

_PICK = """\
You are {person}'s digital twin, working on one of their research projects while they're away. \
You can read a few of the project's files and write up to {files} files: a new script, a fix \
to one, or a section of the paper as markdown. You can't run anything. Pick the one step that \
helps most and that writing alone can finish, and the files to read for it.

Return the step in one line, why it's the one in a sentence or two, and up to {read} files to \
read, by their paths in the list."""

_PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "why": {"type": "string"},
        "read": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["step", "why", "read"],
    "additionalProperties": False,
}

_WRITE = """\
You are {person}'s digital twin, taking one step of a research project's work: the step below. \
You have the files it needs. Write what the step needs, as whole files: at most {files}, each \
with its path in the repository and its full new content (a changed file in full, never a \
diff). Keep to the project's own style. You can't run anything, so claim no result, number or \
figure: say what to run to check it.

Return:
- files: the files, each {{path, content}}.
- did: what you wrote and why, in short markdown.
- couldnt: what's left unchecked or undone; "" when nothing.
- next: the step after this one, in a sentence or two.
- commit: a commit message for it, one plain sentence."""

_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        "did": {"type": "string"},
        "couldnt": {"type": "string"},
        "next": {"type": "string"},
        "commit": {"type": "string"},
    },
    "required": ["files", "did", "couldnt", "next", "commit"],
    "additionalProperties": False,
}


class Local:
    name = "local"
    label = "the local model"

    def __init__(self, model: Callable[..., object] = llm.ask):
        self.model = model

    def __call__(self, task: Task) -> dict:
        if self.model is llm.ask and not llm.configured():
            raise AgentUnavailable("no model is set up (PROXENOS_MODEL, or an API key)")
        files = _tracked(task.folder)
        pick = self.model(
            task.brief + "\n\nThe files in the repository:\n" + "\n".join(files[:LISTED]),
            system=_PICK.format(person=task.person, files=WRITE_FILES, read=READ_FILES),
            schema=_PICK_SCHEMA,
            effort="medium",
            max_tokens=2000,
        )
        step = _text(pick.get("step"))
        if not step:
            raise AgentError("the local model picked no step")
        listed = set(files)
        read = [p for p in pick.get("read") or [] if isinstance(p, str) and p in listed]
        shown = []
        for rel in read[:READ_FILES]:
            try:
                text = (task.folder / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            shown.append(f'<file path="{rel}">\n{text[:FILE_CHARS]}\n</file>')
        answer = self.model(
            "\n\n".join([task.brief, f"The step: {step}", *shown]),
            system=_WRITE.format(person=task.person, files=WRITE_FILES),
            schema=_WRITE_SCHEMA,
            effort="high",
            max_tokens=16000,
        )
        written = []
        for f in [f for f in answer.get("files") or [] if isinstance(f, dict)][:WRITE_FILES]:
            path = inside(task.folder, str(f.get("path") or ""))
            content = str(f.get("content") or "")
            if path is None or not content.strip() or len(content) > WRITE_CHARS:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if content.endswith("\n") else content + "\n", "utf-8")
            written.append(str(path.relative_to(task.folder.resolve())))
        couldnt = _text(answer.get("couldnt"))
        return {
            "step": step,
            "why": _text(pick.get("why")),
            "did": str(answer.get("did") or "").strip()
            or (f"Wrote {', '.join(written)}." if written else "Wrote nothing."),
            "found": "",
            "figures": [],
            "couldnt": f"{LOCAL_LIMITS} {couldnt}".strip(),
            "next": _text(answer.get("next")),
            "commit": _text(answer.get("commit")),
            "meta": {"files_read": len(shown)},
        }


def inside(folder: Path, rel: str) -> Path | None:
    """`rel` as a path in the folder, or None when it would leave it or reach into .git or
    .proxenos."""
    parts = Path(rel).parts
    if not parts or Path(rel).is_absolute() or ".." in parts or parts[0] in (".git", ".proxenos"):
        return None
    root = folder.resolve()
    path = (root / rel).resolve()
    return path if path.is_relative_to(root) and path != root else None


def _tracked(folder: Path) -> list[str]:
    """The repository's files, by path."""
    done = subprocess.run(
        ["git", "-C", str(folder), "ls-files"], capture_output=True, text=True, check=False
    )
    return [line for line in done.stdout.splitlines() if line.strip()]


# Small helpers.


def _json_in(text: str) -> object:
    try:
        return json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError:
        return None


def _last(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:300] if lines else ""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())
