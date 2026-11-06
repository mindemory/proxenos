"""This computer's memory and which local models fit it, with each platform's way of reading
the memory faked out."""

import ctypes
import subprocess
from types import SimpleNamespace

import pytest

from proxenos import machine

GB, GIB = 10**9, 2**30


def test_a_mac_says_its_memory_through_sysctl(monkeypatch):
    ran = []

    def run(args, **kwargs):
        ran.append(args)
        return subprocess.CompletedProcess(args, 0, "34359738368\n", "")

    monkeypatch.setattr(machine, "_platform", lambda: "darwin")
    monkeypatch.setattr(machine.subprocess, "run", run)
    assert machine.memory() == 32 * GIB
    assert ran == [["/usr/sbin/sysctl", "-n", "hw.memsize"]]

    def fails(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(machine.subprocess, "run", fails)
    assert machine.memory() is None


def test_linux_says_its_memory_in_proc_meminfo(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       16318708 kB\nMemFree:         1234567 kB\n")
    monkeypatch.setattr(machine, "_platform", lambda: "linux")
    monkeypatch.setattr(machine, "_MEMINFO", meminfo)
    assert machine.memory() == 16318708 * 1024

    meminfo.write_text("MemFree:         1234567 kB\n")
    assert machine.memory() is None
    monkeypatch.setattr(machine, "_MEMINFO", tmp_path / "missing")
    assert machine.memory() is None


def test_windows_says_its_memory_through_global_memory_status_ex(monkeypatch):
    asked = []

    def global_memory_status_ex(ref):
        status = ref._obj  # what ctypes.byref points at
        asked.append(status.dwLength)
        status.ullTotalPhys = 16 * GIB
        return 1

    monkeypatch.setattr(machine, "_platform", lambda: "win32")
    kernel32 = SimpleNamespace(GlobalMemoryStatusEx=global_memory_status_ex)
    monkeypatch.setattr(machine, "_kernel32", lambda: kernel32)
    assert machine.memory() == 16 * GIB
    assert asked == [ctypes.sizeof(machine._MemoryStatus)] and asked[0] == 64

    kernel32.GlobalMemoryStatusEx = lambda ref: 0  # it failed
    assert machine.memory() is None


def test_windows_memory_is_unknown_where_there_is_no_windows(monkeypatch):
    monkeypatch.setattr(machine, "_platform", lambda: "win32")
    found = machine.memory()  # no kernel32 off Windows: unknown, not a crash
    assert found > 0 if hasattr(ctypes, "windll") else found is None


@pytest.mark.parametrize(
    ("memory", "size", "fits"),
    [
        (32 * GIB, 17 * GB, True),  # gemma4:26b on a 32 GB Mac
        (32 * GIB, 22 * GB, False),  # a model a few GB bigger is too tight
        (24 * GIB, 17 * GB, False),
        (16 * GIB, 8 * GB, True),
        (16 * GIB, 9 * GB, False),
        (64 * GIB, 40 * GB, True),
        (None, 17 * GB, None),  # memory unknown
        (32 * GIB, None, None),  # size unknown
    ],
)
def test_a_model_fits_when_it_and_its_context_take_under_seven_tenths(memory, size, fits):
    assert machine.fits(size, memory) is fits
    if memory is not None and size is not None:
        assert fits == (size + machine.CONTEXT_ROOM <= memory * machine.SHARE)


def test_the_list_marks_each_model_and_suggests_the_largest_that_fits():
    models = {"small:4b": 3 * GB, "gemma4:26b": 17 * GB, "big:70b": 42 * GB, "unsized": None}
    assert machine.marked(models, 32 * GIB) == [
        {"name": "big:70b", "bytes": 42 * GB, "fits": False},
        {"name": "gemma4:26b", "bytes": 17 * GB, "fits": True},
        {"name": "small:4b", "bytes": 3 * GB, "fits": True},
        {"name": "unsized", "bytes": None, "fits": None},
    ]
    assert machine.best(models, 32 * GIB) == "gemma4:26b"
    assert machine.best(models, 16 * GIB) == "small:4b"
    assert machine.best(models, 4 * GIB) is None  # none fits
    assert machine.best(models, None) is None  # nothing known to
    assert machine.best({}, 32 * GIB) is None


def test_with_no_model_yet_it_says_which_size_to_get():
    assert machine.advice(32 * GIB) == (
        "This computer has 32 GB of memory, enough for gemma4:26b, about 17 GB. "
        "gemma4:e4b, about 7 GB, is ready sooner."
    )
    assert "enough for gemma4:26b, about 17 GB." in machine.advice(64 * GIB)
    assert machine.advice(16 * GIB) == (
        "This computer has 16 GB of memory, so get a model of 8 GB or less. gemma4:e4b, about "
        "7 GB, fits. gemma4:26b, about 17 GB, needs 32 GB."
    )
    assert "a model of 2 GB or less" in machine.advice(8 * GIB)
    assert "e4b" not in machine.advice(8 * GIB)  # the starter doesn't fit 8 GB
    assert "too little" in machine.advice(4 * GIB)
    assert machine.advice(None).startswith("gemma4:e4b, about 7 GB, fits a computer with 16 GB")
    assert machine.fits(machine.STARTER_BYTES, 16 * GIB) and not machine.fits(
        machine.STARTER_BYTES, 8 * GIB
    )
    assert "70%" in machine.RULE and "4 GB" in machine.RULE
    assert machine.SHARE == 0.7 and machine.CONTEXT_ROOM == 4 * GB  # as RULE says
