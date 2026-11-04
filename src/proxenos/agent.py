"""The one place Proxenos lets a model work in a folder: a project's own code, checked out on a
branch of its own (a git worktree), to take one step of the project's work and report it.

Two runners, picked by PROXENOS_STEP_RUNNER: "claude", "local", or empty for Claude Code where
it's installed, then the local model.
- Claude Code, headless (`claude -p`): it reads the code, runs it, changes it and runs it again,
  with only the tools in TOOLS, inside Claude Code's sandbox, which must start or Claude Code
  stops (failIfUnavailable) rather than run a command outside it. Its commands can write only in
  the worktree and reach no network, this computer's own servers included, and read nothing in
  the home folder but what a step needs (see _settings); nothing it does can read the vault, the
  user's keys and credentials, their mail and messages or their browsers' profiles (Task.hidden),
  and it may not run the Keychain's or AppleScript's commands (DENIED_COMMANDS). It
  runs on the account Claude Code is signed in to, never on Proxenos's own API key, which is kept
  from it, within MINUTES, TURNS and a spending budget (PROXENOS_STEP_BUDGET, in dollars).
- The local model, through llm.ask, for anyone without Claude Code. It can't run anything: it
  reads a few of the project's files, a long document only by the sections the step needs, and
  writes a new or short file whole and changes a longer one by edits, each replacing text found
  in it exactly once, so its answer stays short enough for a local model to write. Its report
  says plainly that nothing was run, and names any edit it couldn't make.

Each takes a Task and returns the report REPORT describes. Neither commits, merges or pushes;
proxenos.clones.steps does what comes after. Each run, either runner's, leaves one line in the
model-call log as every model call does (`logged`), since Claude Code's goes through no llm.ask.

`read_only` lets Claude Code read a folder and answer, with nothing to run or write: a reviewer of
a paper reading its code (proxenos.review).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from proxenos import llm
from proxenos.config import env

OUT = Path(".proxenos", "out")  # in the worktree: the figures and tables for the report
CACHE = Path(".proxenos", "cache")  # in the worktree: caches its commands would keep elsewhere
MINUTES = 30
TURNS = 100
BUDGET_USD = "5"
TOOLS = "Read,Edit,Write,Glob,Grep,Bash"
READ_TOOLS = "Read,Glob,Grep"  # all a reader has: nothing it does runs or writes
# Commands a step may not run, by name or from /usr/bin: the Keychain's, AppleScript's (which
# drives other apps, Mail and Messages among them, outside the sandbox), the clipboard's, and
# opening an app or a page. A rule doesn't catch one run another way (`sh -c`); the sandbox is
# what holds, and these are a second lock.
DENIED_COMMANDS = ("security", "osascript", "pbpaste", "open")
# What a step's commands may read in the home folder, which is otherwise closed to them, when
# it's there: the toolchains a step runs with, git's own settings, which git stops without, and
# Claude Code's snapshot of the user's shell, which each of its commands starts from.
_HOME_TOOLS = ("miniforge3", "miniconda3", "anaconda3", "mambaforge", "micromamba", ".conda")
_HOME_TOOLS += (".pyenv", ".local/bin", ".local/lib", "Library/Python", ".julia", ".juliaup")
_HOME_TOOLS += ("Library/R", "Library/TinyTeX", ".TinyTeX", "Library/Fonts")
_HOME_TOOLS += (".gitconfig", ".config/git/config", ".config/git/ignore", ".config/git/attributes")
_HOME_TOOLS += (".claude/shell-snapshots",)
_MATLAB_HOME = "Library/Application Support/MathWorks"  # its licence, for a step that runs it
_CLAUDE_PLACES = ("/opt/homebrew/bin/claude", "/usr/local/bin/claude", "~/.local/bin/claude")
_CLAUDE_PLACES += ("~/.claude/local/claude",)
# What Claude Code's environment keeps from Proxenos's: no API key, no host app's settings.
_KEEP_ENV = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SHELL", "TERM")
_SYSTEM_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
LISTED = 400  # of the repository's files, the local model reads the names of
READ_FILES = 6  # the local model reads at most these
FILE_CHARS = 12_000  # a file this long or shorter is read whole, a longer one in part
READ_CHARS = 72_000  # read in all, or less where a local model has no room for it
OUTLINED = 12  # long documents whose sections the local model sees as it picks the step
OUTLINE_CHARS = 8_000
EDIT_OVER = 4_000  # a file longer than this is changed by edits, not written whole
WRITE_FILES = 3  # written whole
WRITE_CHARS = 60_000
EDITS = 40
ANSWER_TOKENS = 16_000  # the local model's answer, its thinking too: within llm.fit's quarter

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


def logged(runner: Runner, project: str, seconds: float, ok: bool) -> None:
    """A run of `runner` on `project` as one line in the model-call log (llm.log_run), never
    any words: Claude Code on the model PROXENOS_STEP_MODEL names, or its own default, at
    Anthropic; the local runner on the model llm.ask goes to, wherever that runs. The local
    runner's own calls through llm.ask leave their lines too."""
    if runner.name == "claude":
        model = "claude-code" + (f":{chosen}" if (chosen := env("STEP_MODEL").strip()) else "")
    else:
        model = llm.current()
    llm.log_run("steps", model, seconds, ok, runner=runner.name, project=project)


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


def read_only(
    prompt: str,
    system: str,
    schema: dict,
    folder: Path,
    hidden: list[Path],
    run: Run | None = None,
) -> dict:
    """A question Claude Code answers by reading a folder, a worktree of a project's code at one
    commit, with only READ_TOOLS: it runs nothing, writes nothing, fetches nothing, and reads
    nothing outside the folder or in `hidden`. On the account it's signed in to, never
    Proxenos's API key, within MINUTES, TURNS and PROXENOS_REVIEW_BUDGET dollars. The answer,
    matching `schema`; AgentUnavailable when Claude Code can't start."""
    binary = claude_bin()
    if not binary:
        raise AgentUnavailable("Claude Code isn't installed here")
    settings = {
        "permissions": {
            "deny": [
                *(f"Read({_rule(p)})" for p in hidden),
                "Bash",
                "Edit",
                "Write",
                "WebFetch",
                "WebSearch",
            ],
            "blockReadsOutsideWorkingDirectories": True,
        }
    }
    args = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--append-system-prompt",
        system,
        "--tools",
        READ_TOOLS,
        "--allowedTools",
        READ_TOOLS,
        "--permission-mode",
        "dontAsk",
        "--settings",
        json.dumps(settings),
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--max-turns",
        str(TURNS),
        "--max-budget-usd",
        env("REVIEW_BUDGET", BUDGET_USD),
    ]
    if model := env("STEP_MODEL").strip():
        args += ["--model", model]
    environment = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    environment["PATH"] = os.pathsep.join(_SYSTEM_PATH)
    code, stdout, stderr = (run or _run)(args, folder, environment, prompt, MINUTES * 60)
    answer, _ = _structured(code, stdout, stderr)
    if not isinstance(answer, dict):
        raise AgentError("Claude Code finished without an answer")
    return answer


def _settings(task: Task) -> dict:
    """The sandbox: commands write only in the worktree and reach no network; nothing reads the
    hidden folders, and nothing edits the data or hidden ones. If the sandbox can't start, Claude
    Code stops instead of running commands without it. The hidden folders are denied twice: as
    Read rules, which bind the Read tool, and to the sandbox itself, which binds commands.

    Commands also may not read the home folder at all but what a step needs (_readable): a
    narrower allowRead opens a path inside a denyRead, as Claude Code's sandbox settings document
    it (since v2.1.77), and a narrower deny inside that stays shut. No host is allowed, and
    allowLocalBinding stays off, as by default, so on macOS a command can't reach a server on
    this computer either (the page, Ollama, Beeper's API); on Linux a command's localhost is its
    own. The Read tool reads only the working folders: in dontAsk mode anything else would ask,
    so it's refused, and blockReadsOutsideWorkingDirectories says so in every mode (v2.1.257)."""
    hidden = [f"Read({_rule(p)})" for p in task.hidden]
    kept = [f"Edit({_rule(p)})" for p in [*task.data, *task.hidden]]
    commands = [
        rule
        for name in DENIED_COMMANDS
        for command in (name, f"/usr/bin/{name}")
        for rule in (f"Bash({command})", f"Bash({command} *)")
    ]
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "network": {"allowedDomains": [], "allowLocalBinding": False},
            "filesystem": {
                "denyRead": [
                    str(Path.home().resolve()),
                    *(str(p.expanduser().resolve()) for p in task.hidden),
                ],
                "allowRead": _readable(task),
            },
        },
        "permissions": {
            "deny": [
                *hidden,
                *kept,
                *commands,
                "Bash(git push:*)",
                "Bash(git remote:*)",
                "WebFetch",
            ],
            "blockReadsOutsideWorkingDirectories": True,
        },
    }


def _readable(task: Task) -> list[str]:
    """What a step's commands may read in the home folder, closed to them otherwise: the
    worktree, the data folders, the repository's git folders the worktree's commits go to, the
    project's Python and MATLAB, and the toolchains, git settings and shell snapshot in
    _HOME_TOOLS. Only what's there."""
    home = Path.home()
    found = [task.folder, *task.data, *_git_folders(task.folder)]
    for tool in (task.python, task.matlab):
        if tool:  # its install: …/envs/<name>, a venv and the Python it was made from, MATLAB.app
            path = Path(tool).expanduser()
            found += [path.parent.parent, path.resolve().parent.parent]
    found += [home / p for p in _HOME_TOOLS]
    if task.matlab:
        found.append(home / _MATLAB_HOME)
    return list(dict.fromkeys(str(p.resolve()) for p in found if p.exists()))


def _git_folders(worktree: Path) -> list[Path]:
    """Where a worktree's git keeps its state, in the repository it was made from: its own folder
    under .git/worktrees, and the repository's .git, which holds the commits. None for a whole
    checkout, whose .git is inside it."""
    try:
        line = (worktree / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not line.startswith("gitdir:"):
        return []
    own = (worktree / line.removeprefix("gitdir:").strip()).resolve()
    try:
        common = (own / (own / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        common = own.parent.parent
    return [own, common]


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
    """Run it in a process group of its own (on Windows, as the root of its process tree), so
    on timeout its commands stop with it."""
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
        if os.name == "nt":
            tree = ["taskkill", "/F", "/T", "/PID", str(proc.pid)]
            subprocess.run(tree, check=False, capture_output=True)
            proc.wait(timeout=10)
        else:
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
    report, meta = _structured(code, stdout, stderr)
    if not isinstance(report, dict) or not _text(report.get("step")):
        raise AgentError("Claude Code finished without a report")
    return report | {"meta": meta}


def _structured(code: int, stdout: str, stderr: str) -> tuple[object, dict]:
    """What Claude Code answered in the shape it was asked for, and its turns and cost; why it
    gave none as AgentError, or AgentUnavailable when it couldn't start."""
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
            raise AgentUnavailable(why)
        raise AgentError(f"Claude Code stopped: {why}")
    report = answer.get("structured_output")
    if not isinstance(report, dict):
        report = _json_in(str(answer.get("result") or ""))
    return report, meta


# The local model.

LOCAL_LIMITS = (
    "The local model can't run code, so nothing was run: what it wrote is untested, and there "
    "are no numbers or figures of its own."
)

_PICK = """\
You are {person}'s digital twin, working on one of their research projects while they're away. \
You can read a few of the project's files and change some: write a new script, fix one, or \
draft or revise a section of the paper. You can't run anything. Pick the one step that helps \
most and that writing alone can finish, and the files to read for it.

Return the step in one line, why it's the one in a sentence or two, and up to {read} files to \
read, by their paths in the list. A file over {chars} characters is read in part: for a long \
document listed with its sections, name in sections the ones the step needs, each by the \
document's path and the heading as listed."""

_PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "step": {"type": "string"},
        "why": {"type": "string"},
        "read": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "heading": {"type": "string"}},
                "required": ["path", "heading"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["step", "why", "read"],
    "additionalProperties": False,
}

_WRITE = """\
You are {person}'s digital twin, taking one step of a research project's work: the step below. \
You have the files it needs, or the parts of them it needs. Change them in the project's own \
style:
- A new file, or one of {edit_over} characters or fewer, can be written whole: its path in the \
repository and its full new content. At most {files} files whole.
- Any longer file, and any file shown only in part, is changed by edits, never written whole. \
An edit is the file's path; find, text copied exactly from the file, a line or a few, enough \
that it appears in the file only once; and replace, the text to put in its place. Edits apply \
in order, and one whose find isn't in the file exactly once isn't made.
In the JSON, write each backslash twice: LaTeX's \\section is "\\\\section".
You can't run anything, so claim no result, number or figure: say what to run to check it.

Return:
- files: the files written whole, each {{path, content}}; [] when none.
- edits: the edits, each {{path, find, replace}}; [] when none.
- did: what you changed and why, in short markdown.
- couldnt: what's left unchecked or undone; "" when nothing.
- next: the step after this one, in a sentence or two.
- commit: a commit message for it, one plain sentence."""

# Neither files nor edits is required, so an answer with either alone fits, as answers did
# before there were edits.
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
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["path", "find", "replace"],
                "additionalProperties": False,
            },
        },
        "did": {"type": "string"},
        "couldnt": {"type": "string"},
        "next": {"type": "string"},
        "commit": {"type": "string"},
    },
    "required": ["did", "couldnt", "next", "commit"],
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
        listing = "\n\nThe files in the repository:\n" + "\n".join(files[:LISTED])
        if outlines := _outlines(task.folder, files):
            listing += (
                f"\n\nThe long documents, by section, with lengths in characters:\n{outlines}"
            )
        pick = self.model(
            task.brief + listing,
            system=_PICK.format(person=task.person, read=READ_FILES, chars=FILE_CHARS),
            schema=_PICK_SCHEMA,
            effort="medium",
            max_tokens=2000,
        )
        step = _text(pick.get("step"))
        if not step:
            raise AgentError("the local model picked no step")
        wanted: dict[str, list[str]] = {}
        for s in [s for s in pick.get("sections") or [] if isinstance(s, dict)]:
            wanted.setdefault(str(s.get("path") or ""), []).append(str(s.get("heading") or ""))
        listed = set(files)
        read = [p for p in pick.get("read") or [] if isinstance(p, str)]
        read = [p for p in dict.fromkeys([*read, *wanted]) if p in listed][:READ_FILES]
        system = _WRITE.format(person=task.person, files=WRITE_FILES, edit_over=EDIT_OVER)
        # Room for the files beside the rest of the prompt, so a local model's prompt and its
        # answer of ANSWER_TOKENS fit its context together (llm.fit leaves it a quarter).
        overhead = len(task.brief) + len(step) + len(system) + len(json.dumps(_WRITE_SCHEMA))
        shown, whole = _read(task.folder, read, wanted, step, llm.fit(READ_CHARS, overhead + 2000))
        answer = self.model(
            "\n\n".join([task.brief, f"The step: {step}", *shown]),
            system=system,
            schema=_WRITE_SCHEMA,
            effort="high",
            max_tokens=ANSWER_TOKENS,
        )
        changed, made, refused = _apply(task.folder, answer, whole)
        couldnt = _text(answer.get("couldnt"))
        not_applied = f"Not applied: {'; '.join(refused)}." if refused else ""
        return {
            "step": step,
            "why": _text(pick.get("why")),
            "did": str(answer.get("did") or "").strip()
            or (f"Changed {', '.join(changed)}." if changed else "Changed nothing."),
            "found": "",
            "figures": [],
            "couldnt": " ".join(filter(None, (LOCAL_LIMITS, not_applied, couldnt))),
            "next": _text(answer.get("next")),
            "commit": _text(answer.get("commit")),
            "meta": {"files_read": len(shown), "edits": made, "not_applied": len(refused)},
        }


def _read(
    folder: Path, read: list[str], wanted: dict[str, list[str]], step: str, room: int
) -> tuple[list[str], set[Path]]:
    """The files to show the model, in `room` characters all told, and those shown whole, the
    only ones it may write whole. A short file is shown whole; a long document by the sections
    asked for, else the ones the step names; anything else long by its start."""
    shown: list[str] = []
    whole: set[Path] = set()
    for rel in read:
        path = inside(folder, rel)
        if path is None or room <= 0:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) <= min(FILE_CHARS, room):
            shown.append(f'<file path="{rel}">\n{text}\n</file>')
            whole.add(path)
            room -= len(text)
            continue
        chosen = _chosen(sections(text, rel), wanted.get(rel, []), step)
        spans = [(s.start, s.end) for s in chosen] or [(0, len(text))]
        part = _part(text, spans, room if chosen else min(room, FILE_CHARS))
        told = f"part of its {len(text):,} characters; change it by edits"
        shown.append(f'<file path="{rel}" shown="{told}">\n{part}\n</file>')
        room -= len(part)
    return shown, whole


def _apply(folder: Path, answer: dict, whole: set[Path]) -> tuple[list[str], int, list[str]]:
    """The answer's files and edits, made in the worktree: the files changed, how many edits were
    made, and what wasn't done and why, a phrase each. A file is written whole only when it's
    new or was read whole, so nothing it didn't read is lost, and an edit is made only where
    its text to find is in the file exactly once, so it can't land in the wrong place."""
    root = folder.resolve()
    changed: list[str] = []
    refused: list[str] = []
    written = 0
    for f in [f for f in answer.get("files") or [] if isinstance(f, dict)]:
        rel, content = str(f.get("path") or ""), _unslipped(str(f.get("content") or ""))
        path = inside(folder, rel)
        if not content.strip():
            continue
        if path is None:
            refused.append(f"{_code(rel)}, outside the files it may change")
        elif len(content) > WRITE_CHARS:
            refused.append(f"{_code(rel)} in full, past {WRITE_CHARS:,} characters")
        elif path.exists() and path not in whole:
            refused.append(f"{_code(rel)} in full, as it was read in part or not at all")
        elif written >= WRITE_FILES:
            refused.append(f"{_code(rel)}, past the {WRITE_FILES} files written whole")
        else:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content if content.endswith("\n") else content + "\n", "utf-8")
            except OSError:
                refused.append(f"{_code(rel)}, which couldn't be written")
                continue
            written += 1
            changed.append(path.relative_to(root).as_posix())
    edits = [
        e
        for e in answer.get("edits") or []
        if isinstance(e, dict)
        and isinstance(e.get("find"), str)
        and isinstance(e.get("replace"), str)
    ]
    if len(edits) > EDITS:
        refused.append(f"{len(edits) - EDITS} edits past the {EDITS} a step makes")
    by_file: dict[str, list[dict]] = {}
    for e in edits[:EDITS]:
        by_file.setdefault(str(e.get("path") or ""), []).append(e)
    made = 0
    for rel, these in by_file.items():
        path = inside(folder, rel)
        try:
            was = path.read_bytes().decode("utf-8") if path and path.is_file() else None
        except (OSError, UnicodeDecodeError):
            was = None
        if path is None or was is None:
            many = "an edit" if len(these) == 1 else f"{len(these)} edits"
            refused.append(f"{many} to {_code(rel)}, not a text file in the repository")
            continue
        # Matched with plain line ends, and written back with the file's own.
        text = before = was.replace("\r\n", "\n")
        for e in these:
            find, replace = (_unslipped(e[k]).replace("\r\n", "\n") for k in ("find", "replace"))
            at = text.find(find) if find else -1
            if at != -1 and text.rfind(find) == at:
                text = text[:at] + replace + text[at + len(find) :]
                made += 1
                continue
            why = "is in it more than once" if at != -1 else "isn't in it"
            what = f"whose text to find, {_code(find)}, {why}" if find else "with nothing to find"
            refused.append(f"an edit to {_code(rel)} {what}")
        if text != before:
            path.write_bytes((text.replace("\n", "\r\n") if "\r\n" in was else text).encode())
            if (name := path.relative_to(root).as_posix()) not in changed:
                changed.append(name)
    return changed, made, refused


# A backslash left single before b, f or r is a JSON escape all the same, so LaTeX's \begin,
# \frac and \ref come back as a control character and letters, which no text file has.
_SLIPPED = re.compile(r"[\x08\x0c\r](?=[A-Za-z])")


def _unslipped(text: str) -> str:
    """The text with each such control character the backslash and letter it was."""
    return _SLIPPED.sub(lambda m: "\\" + {"\x08": "b", "\x0c": "f", "\r": "r"}[m[0]], text)


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


# Long documents, by section.

START = "(before the first heading)"
_TEX = {".tex", ".ltx"}
_MARKDOWN = {".md", ".markdown", ".rmd", ".qmd"}
_LATEX_HEADING = re.compile(
    r"^[ \t]*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[ \t]*"
    r"(?:\[[^\]\n]*\][ \t]*)?\{",
    re.MULTILINE,
)
_LATEX_LEVELS = {"part": 0, "chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}
_LATEX_LEVELS["paragraph"] = 5
_ABSTRACT = re.compile(r"^[ \t]*\\begin\{abstract\}", re.MULTILINE)
_MARKDOWN_HEADING = re.compile(r"(#{1,6})[ \t]+(.+?)[ \t#]*$")


class Section(NamedTuple):
    title: str
    level: int  # 2 for LaTeX's \section, 3 for \subsection; in Markdown, the number of #s
    start: int
    end: int  # where the next heading at its level or above starts, so it holds its subsections


def sections(text: str, path: str) -> list[Section]:
    """A LaTeX or Markdown document's sections, by heading, in order, with what comes before the
    first heading as START; none for another kind of file, or one without headings."""
    heads = _headings(text, Path(path).suffix.lower())
    if not heads:
        return []
    top = min(level for _, level, _ in heads)
    found = [Section(START, top, 0, heads[0][0])] if text[: heads[0][0]].strip() else []
    for i, (at, level, title) in enumerate(heads):
        end = next((a for a, lv, _ in heads[i + 1 :] if lv <= level), len(text))
        found.append(Section(title, level, at, end))
    return found


def _headings(text: str, suffix: str) -> list[tuple[int, int, str]]:
    """Where each heading starts, its level and its title: LaTeX's sectioning commands and its
    abstract, or Markdown's # lines outside fenced code."""
    if suffix in _TEX:
        found = [
            (m.start(), _LATEX_LEVELS[m[1]], _braced(text, m.end()))
            for m in _LATEX_HEADING.finditer(text)
        ]
        found += [
            (m.start(), _LATEX_LEVELS["section"], "Abstract") for m in _ABSTRACT.finditer(text)
        ]
        return sorted(found)
    if suffix not in _MARKDOWN:
        return []
    found, at, fenced = [], 0, False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and (m := _MARKDOWN_HEADING.match(line)):
            found.append((at, len(m[1]), m[2].strip()))
        at += len(line)
    return found


def _braced(text: str, at: int) -> str:
    """The title in the braces opened just before `at`, as a LaTeX heading has it."""
    depth = 1
    for end in range(at, min(len(text), at + 300)):
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        if not depth:
            return " ".join(text[at:end].split())
    return " ".join(text[at : at + 80].split())


def _outlines(folder: Path, files: list[str]) -> str:
    """The sections of the repository's longest documents, the longest first, each section with
    its length, so the model can name the ones a step needs."""
    found = []
    for rel in files:
        path = inside(folder, rel)
        if path is None or path.suffix.lower() not in _TEX | _MARKDOWN:
            continue
        try:
            if path.stat().st_size <= FILE_CHARS:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > FILE_CHARS and (parts := sections(text, rel)):
            found.append((len(text), rel, parts))
    told = []
    for length, rel, parts in sorted(found, key=lambda f: (-f[0], f[1]))[:OUTLINED]:
        top = min(s.level for s in parts)
        lines = [f"{'  ' * (s.level - top)}- {s.title} ({s.end - s.start:,})" for s in parts]
        told.append("\n".join([f"{rel} ({length:,}):", *lines]))
    outline = "\n\n".join(told)
    return outline if len(outline) <= OUTLINE_CHARS else outline[:OUTLINE_CHARS].rsplit("\n", 1)[0]


def _chosen(found: list[Section], headings: list[str], step: str) -> list[Section]:
    """The sections asked for, by heading, else those whose heading the step names."""
    asked = {_key(h) for h in headings} - {""}
    if chosen := [s for s in found if _key(s.title) in asked]:
        return chosen
    named = f" {_key(step)} "
    return [
        s for s in found if s.title != START and _key(s.title) and f" {_key(s.title)} " in named
    ]


def _key(heading: str) -> str:
    """A heading as compared: its words in lower case, without a length after it, as the
    outline gives one."""
    return " ".join(re.findall(r"\w+", re.sub(r"\([\d,]+\)\s*$", "", heading).lower()))


def _part(text: str, spans: list[tuple[int, int]], room: int) -> str:
    """The spans of a text in order, those that overlap merged, in at most `room` characters cut
    at a line's end, with each stretch left out marked by its length."""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, at = [], 0
    for start, end in merged:
        if room <= 0:
            break
        if end - start > room:
            end = text.rfind("\n", start, start + room) + 1 or start + room
        if start > at:
            out.append(f"\n[{start - at:,} characters not shown]\n\n")
        out.append(text[start:end])
        room -= end - start
        at = end
    if at < len(text):
        out.append(f"\n[{len(text) - at:,} characters not shown]\n")
    return "".join(out)


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


def _code(text: str, chars: int = 60) -> str:
    """Text a model gave, in short, as inline code in a report."""
    said = _text(text).replace("`", "'")
    if not said:
        return '""'
    return f"`{said[:chars]}…`" if len(said) > chars else f"`{said}`"
