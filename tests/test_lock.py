"""The vault's locks: one holder at a time, let go of when the holder ends, and the run lock that
keeps sync, night and master from overlapping whoever starts them. No real runs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from proxenos import cli, lock, master

SRC = Path(__file__).resolve().parents[1] / "src"


def test_one_holder_at_a_time_even_in_one_process(tmp_path):
    path = tmp_path / "state" / "x.lock"
    first, second = lock.Lock(path), lock.Lock(path)

    assert not lock.taken(path)  # no file yet, and none made by looking
    assert not path.exists()
    assert first.acquire()
    assert first.acquire()  # already its own
    assert not second.acquire()
    assert lock.taken(path)
    first.release()
    assert not lock.taken(path)
    assert second.acquire()
    second.release()
    second.release()  # twice is fine


def test_a_lock_is_let_go_of_when_its_holder_ends_however_it_ends(tmp_path):
    """Another process takes the lock, then dies without letting go: the system lets go."""
    path = tmp_path / "state" / "run.lock"
    code = (
        "import os, sys, pathlib\n"
        "from proxenos.lock import Lock\n"
        f"assert Lock(pathlib.Path({str(path)!r})).acquire()\n"
        "print('held', flush=True)\n"
        "sys.stdin.readline()\n"
        "os._exit(1)\n"  # no clean-up of any kind
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        assert lock.taken(path)
        assert lock.alive(holder.pid)
    finally:
        holder.communicate("\n", timeout=30)
    assert not lock.taken(path)
    assert lock.Lock(path).acquire()
    assert not lock.alive(holder.pid)
    assert lock.alive(os.getpid())
    assert not lock.alive(0)


def test_the_windows_branch_locks_the_first_byte_without_waiting(tmp_path, monkeypatch):
    """msvcrt.locking, faked: locks are by file, the first byte, never waited for."""

    class FakeMsvcrt:
        LK_NBLCK, LK_UNLCK = 2, 0

        def __init__(self):
            self.locked: set[int] = set()
            self.calls = []

        def locking(self, fd, mode, nbytes):
            self.calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))
            inode = os.fstat(fd).st_ino
            if mode == self.LK_UNLCK:
                self.locked.discard(inode)
            elif inode in self.locked:
                raise OSError(36, "Resource deadlock avoided")
            else:
                self.locked.add(inode)

    fake = FakeMsvcrt()
    monkeypatch.setattr(lock, "msvcrt", fake, raising=False)
    monkeypatch.setattr(lock.os, "name", "nt")
    path = tmp_path / "state" / "run.lock"
    first, second = lock.Lock(path), lock.Lock(path)

    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
    assert {(mode, nbytes, at) for mode, nbytes, at in fake.calls} == {(2, 1, 0), (0, 1, 0)}


def test_the_run_lock_says_who_holds_it_and_a_stale_note_counts_for_nothing(tmp_path):
    vault = tmp_path / "vault"
    assert lock.holder(vault) is None

    with lock.run(vault, "night"):
        found = lock.holder(vault)
        assert found["job"] == "night" and found["pid"] == os.getpid()
        assert lock.describe(found).startswith("night has been running since ")
        assert lock.describe(found).endswith(f"(process {os.getpid()})")
        with (
            pytest.raises(lock.Busy, match="night has been running since") as busy,
            lock.run(vault, "sync"),
        ):
            pytest.fail("two runs at once")
        assert busy.value.holder["job"] == "night"
    assert lock.holder(vault) is None
    assert not (vault / lock.RUN_INFO).exists()

    # A note left by a run that crashed doesn't make a holder of it.
    (vault / lock.RUN_INFO).write_text(json.dumps({"job": "night", "pid": 1}))
    assert lock.holder(vault) is None
    assert lock.describe({}) == "another run is going"


def test_sync_doesnt_start_while_night_runs_whoever_started_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    vault = tmp_path / "vault"
    seen = []

    def fake_sync(vault):
        seen.append(lock.holder(vault))  # held by this sync, as it runs
        return {"sources_synced": 1}

    monkeypatch.setattr(master, "sync", fake_sync)
    with lock.run(vault, "night"), pytest.raises(SystemExit) as exit_:
        cli.main(["sync"])
    assert exit_.value.code == lock.BUSY
    err = capsys.readouterr().err
    assert err.startswith("sync: not started; night has been running since ")
    assert seen == []

    cli.main(["sync"])
    assert seen[0]["job"] == "sync"
    assert capsys.readouterr().out == "sync: 1 sources synced\n"
    assert lock.holder(vault) is None


def test_master_runs_take_the_run_lock_and_accepting_proposals_doesnt(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    vault = tmp_path / "vault"
    monkeypatch.setattr(master, "accept", lambda vault: {"accepted": 0})
    with lock.run(vault, "sync"):
        with pytest.raises(SystemExit) as exit_:
            cli.main(["master"])
        assert exit_.value.code == lock.BUSY
        cli.main(["master", "accept"])  # changes no source, so it needn't wait
