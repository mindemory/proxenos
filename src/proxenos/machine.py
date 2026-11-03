"""How much memory this computer has, and which local models fit in it, for the setup page.

A local model sits in memory while it writes, with what it's reading beside it (up to
llm.LOCAL_CONTEXT tokens), and the system, the page and everything else need the rest. So a
model fits when its size plus CONTEXT_ROOM is at most SHARE of the memory: gemma4:26b, about
17 GB, fits a 32 GB Mac, and a model a few GB bigger doesn't, as docs/landscape.md found ("Local
models on a 32 GB Mac"). It's a rule of thumb: a model takes about its size on disk, and what
it's reading takes more for some models than others.

Memory is read with the standard library only: `sysctl -n hw.memsize` on a Mac, /proc/meminfo on
Linux and GlobalMemoryStatusEx on Windows. Sizes are bytes; memory is said in GB the way the
system says it (32 GB is 32 x 2^30 bytes), and a model's size the way Ollama does (17 x 10^9).
"""

import ctypes
import subprocess
import sys
from pathlib import Path

SHARE = 0.7
CONTEXT_ROOM = 4 * 10**9  # bytes beside the model, for what it's reading
SUGGESTED, SUGGESTED_BYTES = "gemma4:26b", 17 * 10**9  # docs/landscape.md's pick, and its size
RULE = (
    "A model fits when its size plus 4 GB for what it's reading stays under 70% of this "
    "computer's memory, leaving the rest for everything else."
)
_SYSCTL = "/usr/sbin/sysctl"
_MEMINFO = Path("/proc/meminfo")


def memory() -> int | None:
    """This computer's memory in bytes, or None where it can't be read."""
    try:
        if _platform() == "darwin":
            return _mac()
        if _platform() == "win32":
            return _windows()
        return _linux()
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None


def room(memory: int | None) -> int | None:
    """The largest model, in bytes, that fits in `memory`; None when the memory isn't known."""
    return None if memory is None else max(0, int(memory * SHARE) - CONTEXT_ROOM)


def fits(size: int | None, memory: int | None) -> bool | None:
    """Whether a model of `size` bytes fits in `memory`; None when either isn't known."""
    most = room(memory)
    return None if not size or most is None else size <= most


def marked(models: dict[str, int | None], memory: int | None) -> list[dict]:
    """Each model by name, with its size and whether it fits, as the setup page lists them."""
    return [{"name": n, "bytes": s, "fits": fits(s, memory)} for n, s in sorted(models.items())]


def best(models: dict[str, int | None], memory: int | None) -> str | None:
    """The model to suggest: the largest that fits, or None when none is known to."""
    fitting = [(size, name) for name, size in models.items() if fits(size, memory)]
    return max(fitting)[1] if fitting else None


def advice(memory: int | None) -> str:
    """Which size of model to get, in plain words, for when none is there yet."""
    if memory is None:
        return f"{SUGGESTED}, about 17 GB, fits a computer with 32 GB of memory."
    have = f"This computer has {round(memory / 2**30)} GB of memory"
    if fits(SUGGESTED_BYTES, memory):
        return f"{have}, enough for {SUGGESTED}, about 17 GB."
    most = (room(memory) or 0) // 10**9
    if most < 1:
        return f"{have}, too little for a model to run beside everything else: use an API key."
    return f"{have}, so get a model of {most} GB or less. {SUGGESTED}, about 17 GB, needs 32 GB."


def _platform() -> str:
    """sys.platform, in one place so tests can pin it."""
    return sys.platform


def _mac() -> int:
    said = subprocess.run(
        [_SYSCTL, "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True
    )
    return _positive(said.stdout)


def _linux() -> int:
    for line in _MEMINFO.read_text().splitlines():
        name, _, value = line.partition(":")
        if name.strip() == "MemTotal":  # "MemTotal:       32790752 kB"
            number, _, unit = value.strip().partition(" ")
            return _positive(number) * (1024 if unit.strip().lower() == "kb" else 1)
    raise ValueError("no MemTotal in /proc/meminfo")


class _MemoryStatus(ctypes.Structure):
    """Windows's MEMORYSTATUSEX, 64 bytes: two DWORDs, then seven DWORDLONGs."""

    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _windows() -> int:
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not _kernel32().GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return _positive(str(status.ullTotalPhys))


def _kernel32():
    return ctypes.windll.kernel32  # only on Windows; elsewhere AttributeError, so None above


def _positive(text: str) -> int:
    number = int(text.strip())
    if number <= 0:
        raise ValueError(f"memory of {number} bytes")
    return number
