"""Locks on the vault that work the same on macOS, Windows and Linux.

A lock is a file in <vault>/state/ that one process at a time holds with the operating system's
own lock on it: `flock` on macOS and Linux, `msvcrt.locking` on Windows. The system lets go of
it when its holder ends, however it ends, so a crash or a pulled plug never leaves a lock behind
to clear by hand, and nothing has to guess from a process id whether the holder is still there.
A lock is never waited for: whoever finds it held decides what to do instead.

Two locks use it:
- **The run lock** (state/run.lock), held by `proxenos sync`, `proxenos night` and
  `proxenos master` while they run, whoever started them (the scheduler, launchd, a terminal),
  so two never refresh the vault at once. Beside it, state/run.json says which run has it and
  since when, for whoever finds it held.
- **The scheduler's lock** (state/schedule.lock), held by `proxenos schedule` for as long as it
  runs, so a vault never has two.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

RUN = Path("state", "run.lock")
RUN_INFO = Path("state", "run.json")
SCHEDULER = Path("state", "schedule.lock")
# The exit status of a run that didn't start because another had the run lock (sysexits'
# EX_TEMPFAIL): nothing is wrong, try again later.
BUSY = 75

# Windows: OpenProcess's right to ask whether a process has ended, and the answer that it hasn't.
_QUERY_LIMITED = 0x1000
_STILL_ACTIVE = 259
_ACCESS_DENIED = 5


class Busy(Exception):
    """Another process has the run lock; `holder` is what run.json says about it ({} if
    nothing)."""

    def __init__(self, holder: dict | None = None):
        self.holder = holder or {}
        super().__init__(describe(self.holder))


class Lock:
    """One lock file, held or not by this object. A second Lock on the same file, even in the
    same process, finds it held."""

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Take the lock if it's free, without waiting. Whether this took it."""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            _unlock(fd)
        except OSError:
            pass  # closing it lets go all the same
        finally:
            os.close(fd)


def taken(path: Path) -> bool:
    """Whether another holds the lock at `path` right now. It takes the lock and lets go at once
    to find out, so a holder that has ended never counts."""
    if not path.exists():
        return False
    probe = Lock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


@contextmanager
def run(vault: Path, job: str) -> Iterator[None]:
    """Hold the vault's run lock while `job` goes on, with run.json saying so. Raises Busy,
    before anything runs, when another run has it."""
    held = Lock(vault / RUN)
    if not held.acquire():
        raise Busy(holder(vault))
    info = vault / RUN_INFO
    try:
        write_json(info, {"job": job, "pid": os.getpid(), "started": _now()})
        yield
    finally:
        with suppress(OSError):  # it's only read while the lock is held, so a stale one is moot
            info.unlink(missing_ok=True)
        held.release()


def holder(vault: Path) -> dict | None:
    """The run that has the vault's run lock now, as run.json says: {"job", "pid", "started"}, or
    {} when it hasn't said yet. None when no run has it."""
    if not taken(vault / RUN):
        return None
    try:
        info = json.loads((vault / RUN_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def describe(holder: dict) -> str:
    """A run lock's holder in words: "night has been running since 2026-10-30 01:30 (process
    4242)"."""
    job = holder.get("job")
    if not isinstance(job, str) or not job:
        return "another run is going"
    words = f"{job} is running"
    try:
        started = datetime.fromisoformat(holder["started"]).astimezone()
        words = f"{job} has been running since {started:%Y-%m-%d %H:%M}"
    except (KeyError, TypeError, ValueError):
        pass
    pid = holder.get("pid")
    return f"{words} (process {pid})" if isinstance(pid, int) else words


def alive(pid: int) -> bool:
    """Whether process `pid` is running. macOS and Linux answer `os.kill(pid, 0)`; on Windows
    signal 0 is CTRL_C_EVENT, which would interrupt the process instead, so Windows is asked
    directly."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # someone else's, and there
        return True
    except OSError:
        return False
    return True


def _alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ACCESS_DENIED  # there, but not ours to look at
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _lock(fd: int) -> None:
    """Lock an open file without waiting; OSError when another has it."""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # its first byte, which is never written
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


def write_json(path: Path, data: dict) -> None:
    """Write a small JSON file in the vault whole, private to you, or not at all: the run's note
    and the scheduler's status are only ever informative, so one that can't be written never
    stops what it's about."""
    tmp = path.with_name(path.name + ".tmp")
    with suppress(OSError):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
