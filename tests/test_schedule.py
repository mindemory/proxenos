"""`proxenos schedule` on a fake clock with a fake runner: no real sync or night ever starts, and
nothing sleeps. Times are in a fixed zone (no clock changes) unless a test says otherwise."""

import argparse
import itertools
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from datetime import time as daytime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from proxenos import cli, config, llm, lock, schedule

TZ = timezone(timedelta(hours=-4))
PLAN = schedule.Plan(timedelta(minutes=15), daytime(1, 30))


def at(day, hour, minute=0, second=0):
    """A moment in late October 2026, in TZ."""
    return datetime(2026, 10, day, hour, minute, second, tzinfo=TZ)


class FakeClock:
    """Time that moves only when the scheduler sleeps, with things to do at set moments, in the
    order they're given: a computer going to sleep (the clock jumps), a stop, a lock let go of."""

    tz = TZ

    def __init__(self, start):
        self.t = start
        self.events = []

    def now(self):
        return self.t

    def sleep(self, seconds, stop):
        assert seconds > 0
        self.t += timedelta(seconds=seconds)
        while self.events and self.events[0][0] <= self.t:
            _, do = self.events.pop(0)
            do()

    def on(self, when, do):
        self.events.append((when, do))

    def jump(self, to):
        return lambda: setattr(self, "t", to)


class FakeProcess:
    def __init__(self, clock, ends, code, obeys=True):
        self.clock, self.ends, self.code, self.obeys = clock, ends, code, obeys
        self.stopped = self.killed = 0

    def poll(self):
        return self.code if self.clock.now() >= self.ends else None

    def stop(self):
        self.stopped += 1
        if self.obeys:  # winds down in a few seconds, as an interrupted run does
            self.ends, self.code = min(self.ends, self.clock.now() + timedelta(seconds=4)), 130

    def kill(self):
        self.killed += 1
        self.ends, self.code = self.clock.now(), -9


class FakeRunner:
    """Each job "runs" for a set time on the fake clock and ends with a set code."""

    def __init__(self, clock, sync=2, night=50, codes=None, obeys=True):
        self.clock = clock
        self.takes = {"sync": timedelta(minutes=sync), "night": timedelta(minutes=night)}
        self.codes = codes or {}
        self.obeys = obeys
        self.started = []
        self.processes = []

    def start(self, job, vault, log):
        assert log == vault / "logs" / f"{job}.log"
        now = self.clock.now()
        self.started.append((job, now))
        codes = self.codes.get(job, [0])
        code = codes.pop(0) if len(codes) > 1 else codes[0]
        process = FakeProcess(self.clock, now + self.takes[job], code, self.obeys)
        self.processes.append(process)
        return process


def scheduler(vault, clock, runner, plan=PLAN, once=False):
    lines = []
    found = schedule.Scheduler(vault, plan, once=once, clock=clock, runner=runner, say=lines.append)
    return found, lines


def status(vault):
    return json.loads((vault / schedule.STATUS).read_text())


def starts(runner, job=None):
    return [t for name, t in runner.started if job in (None, name)]


# The schedule maths


def test_the_night_is_the_next_time_it_comes_round():
    assert schedule.next_night(at(29, 13), daytime(1, 30), TZ) == at(30, 1, 30)
    assert schedule.next_night(at(29, 1), daytime(1, 30), TZ) == at(29, 1, 30)
    assert schedule.next_night(at(29, 1, 30), daytime(1, 30), TZ) == at(30, 1, 30)  # just ran
    assert PLAN.following("sync", at(29, 13, 2), TZ) == at(29, 13, 17)
    assert PLAN.following("night", at(30, 8), TZ) == at(31, 1, 30)  # a late one, then on time


def test_the_night_on_the_days_the_clocks_change():
    try:
        zone = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        pytest.skip("no time zone database here")
    utc = UTC
    # Spring forward: 02:30 doesn't happen on March 8, so the run comes at 03:30.
    spring = schedule.next_night(datetime(2026, 3, 8, 5, 0, tzinfo=utc), daytime(2, 30), zone)
    assert spring.astimezone(utc) == datetime(2026, 3, 8, 7, 30, tzinfo=utc)
    assert f"{spring.astimezone(zone):%H:%M}" == "03:30"
    # Fall back: 01:30 happens twice on November 1; the first counts, and only once.
    first = schedule.next_night(datetime(2026, 11, 1, 4, 0, tzinfo=utc), daytime(1, 30), zone)
    assert first.astimezone(utc) == datetime(2026, 11, 1, 5, 30, tzinfo=utc)  # EDT's
    again = schedule.next_night(first, daytime(1, 30), zone)
    assert again.astimezone(utc) == datetime(2026, 11, 2, 6, 30, tzinfo=utc)  # not the repeat


def test_the_night_in_this_computers_own_zone():
    for after in (datetime(2026, 1, 14, 12, tzinfo=UTC), datetime(2026, 7, 14, 12)):
        after = after.astimezone()
        slot = schedule.next_night(after, daytime(1, 30))
        assert slot > after and slot - after <= timedelta(days=1)
        assert f"{slot.astimezone():%H:%M}" == "01:30"


# The plan: flags, then settings, then defaults


def args(*argv):
    parser = argparse.ArgumentParser()
    schedule.add_arguments(parser)
    return parser.parse_args(list(argv))


def test_the_plan_comes_from_the_flags_then_the_settings_then_the_defaults(monkeypatch):
    assert schedule.plan(args()) == PLAN
    monkeypatch.setenv("PROXENOS_SYNC_EVERY", "30")
    monkeypatch.setenv("PROXENOS_NIGHT_AT", "2:15")
    assert schedule.plan(args()) == schedule.Plan(timedelta(minutes=30), daytime(2, 15))
    assert schedule.plan(args("--sync-every", "5", "--night-at", "23:45")) == schedule.Plan(
        timedelta(minutes=5), daytime(23, 45)
    )
    assert schedule.plan(args("--night-at", "off")).jobs == ("sync",)
    assert schedule.plan(args("--sync-every", "0")).jobs == ("night",)
    with pytest.raises(SystemExit, match="nothing to run"):
        schedule.plan(args("--sync-every", "off", "--night-at", "off"))
    for bad in (["--sync-every", "-5"], ["--sync-every", "1441"], ["--sync-every", "soon"]):
        with pytest.raises(SystemExit, match="whole minutes"):
            schedule.plan(args(*bad))
    for bad in ("24:00", "1:3", "noon"):
        with pytest.raises(SystemExit, match="HH:MM"):
            schedule.plan(args("--night-at", bad))


def test_the_settings_file_sets_the_times_too():
    config.SETTINGS_FILE.parent.mkdir(parents=True)
    config.SETTINGS_FILE.write_text(json.dumps({"sync_every": "45", "night_at": "03:00"}))
    assert schedule.plan(args()) == schedule.Plan(timedelta(minutes=45), daytime(3, 0))


# The loop


def test_a_day_syncs_every_quarter_hour_and_runs_the_night_once_with_nothing_overlapping(
    tmp_path,
):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    sched, lines = scheduler(vault, clock, runner)
    clock.on(at(30, 13), sched.stop)

    assert sched.run() == 0

    assert runner.started[0] == ("sync", at(29, 13))
    assert starts(runner, "night") == [at(30, 1, 30)]
    syncs = starts(runner, "sync")
    assert [b - a for a, b in itertools.pairwise(syncs)].count(timedelta(minutes=15)) == len(
        syncs
    ) - 2
    # sync waited while night ran, then ran once, right after it.
    assert at(30, 1, 15) in syncs and at(30, 2, 20) in syncs
    assert not [t for t in syncs if at(30, 1, 15) < t < at(30, 2, 20)]
    ends = [(t, t + runner.takes[job]) for job, t in runner.started]
    assert all(end <= start for (_, end), (start, _) in itertools.pairwise(ends))
    assert lines[0] == (
        f"schedule: keeping {vault}: sync every 15 minutes, next 2026-10-29 13:00; "
        "night at 01:30, next 2026-10-30 01:30"
    )
    assert lines[-1] == "schedule: stopped"
    assert "schedule: night ok, 2026-10-30 01:30 to 02:20 (50m 0s)" in lines


def test_after_sleeping_through_the_night_each_job_runs_once_on_wake(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 22))
    runner = FakeRunner(clock)
    sched, _ = scheduler(vault, clock, runner)
    clock.on(at(29, 23, 5), clock.jump(at(30, 8)))  # the lid closes, and opens in the morning
    clock.on(at(30, 9, 30), sched.stop)

    sched.run()

    woke = [(job, t) for job, t in runner.started if t >= at(30, 8)]
    assert woke == [
        ("night", at(30, 8)),  # missed at 01:30: once now, night first as it syncs too
        ("sync", at(30, 8, 50)),  # thirty-six missed syncs: one, after the night
        ("sync", at(30, 9, 5)),
        ("sync", at(30, 9, 20)),
    ]
    assert status(vault)["night"]["next"] == "2026-10-31T01:30:00-04:00"


def test_a_restart_after_the_computer_was_off_catches_up_once(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    first, _ = scheduler(vault, clock, FakeRunner(clock))
    clock.on(at(29, 14), first.stop)
    first.run()
    assert status(vault)["pid"] is None

    clock = FakeClock(at(30, 8))  # off overnight, on again in the morning
    runner = FakeRunner(clock)
    second, _ = scheduler(vault, clock, runner)
    clock.on(at(30, 9), second.stop)
    second.run()

    assert runner.started[:2] == [("night", at(30, 8)), ("sync", at(30, 8, 50))]
    assert starts(runner, "night") == [at(30, 8)]


def test_a_clock_set_back_doesnt_leave_the_next_run_far_off(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    sched, _ = scheduler(vault, clock, runner)
    clock.on(at(29, 13, 5), clock.jump(at(29, 10)))
    clock.on(at(29, 10, 20), sched.stop)

    sched.run()

    assert starts(runner, "sync") == [at(29, 13), at(29, 10, 15)]


def test_new_times_count_from_now_but_a_missed_night_still_runs(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    sched, _ = scheduler(vault, clock, FakeRunner(clock), once=True)
    sched.run()
    assert status(vault)["night"] == {
        "at": "01:30",
        "last": None,
        "next": "2026-10-30T01:30:00-04:00",
    }

    later = schedule.Plan(timedelta(minutes=60), daytime(3, 0))
    clock = FakeClock(at(29, 15))
    sched, _ = scheduler(vault, clock, FakeRunner(clock), plan=later, once=True)
    sched.run()
    saved = status(vault)
    assert saved["night"]["next"] == "2026-10-30T03:00:00-04:00"
    assert saved["sync"]["every_minutes"] == 60

    clock = FakeClock(at(30, 9))  # the 03:00 was missed; moving it back doesn't skip it
    runner = FakeRunner(clock)
    sched, _ = scheduler(vault, clock, runner, plan=PLAN, once=True)
    sched.run()
    assert [job for job, _ in runner.started] == ["night", "sync"]


# Never two at once


def test_nothing_starts_while_a_run_from_elsewhere_goes_on(tmp_path):
    vault = tmp_path / "vault"
    night = lock.run(vault, "night")  # launchd's, or one started by hand
    night.__enter__()
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    sched, lines = scheduler(vault, clock, runner)

    def check_and_let_go():
        saved = status(vault)
        assert saved["running"]["job"] == "night" and saved["running"]["by"] == "elsewhere"
        assert saved["waiting"].startswith("sync waits: night has been running since")
        night.__exit__(None, None, None)

    clock.on(at(29, 13, 40), check_and_let_go)
    clock.on(at(29, 14), sched.stop)

    sched.run()

    assert starts(runner, "sync")[0] == at(29, 13, 40)  # at the next look after it ended
    assert sum("sync waits: night has been running" in line for line in lines) == 1  # said once


def test_a_run_of_the_same_job_from_elsewhere_counts_as_its_run(tmp_path):
    vault = tmp_path / "vault"
    other = lock.run(vault, "sync")
    other.__enter__()
    clock = FakeClock(at(29, 13))
    clock.on(at(29, 13, 3), lambda: other.__exit__(None, None, None))
    runner = FakeRunner(clock)
    sched, lines = scheduler(vault, clock, runner)
    clock.on(at(29, 13, 31), sched.stop)

    sched.run()

    assert starts(runner, "sync") == [at(29, 13, 15), at(29, 13, 30)]
    assert any(
        line.startswith("schedule: sync not started, one is already going") for line in lines
    )
    assert status(vault)["running"] is None


def test_a_vault_has_one_scheduler(tmp_path):
    vault = tmp_path / "vault"
    (vault / "state").mkdir(parents=True)
    (vault / schedule.STATUS).write_text(json.dumps({"pid": 4242}))
    other = lock.Lock(vault / lock.SCHEDULER)
    assert other.acquire()
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    for once in (False, True):
        sched, lines = scheduler(vault, clock, runner, once=once)
        assert sched.run() == lock.BUSY
        assert lines == [f"schedule: another scheduler already keeps {vault} (process 4242)"]
    assert runner.started == []
    other.release()


def test_a_run_that_lost_the_race_for_the_lock_isnt_counted(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock, codes={"sync": [lock.BUSY, 0]})
    sched, lines = scheduler(vault, clock, runner, once=True)

    assert sched.run() == 0

    assert len(starts(runner, "sync")) == 1  # --once: each job once
    assert "schedule: sync not started: another run had just begun" in lines
    assert status(vault)["sync"]["last"] is None
    assert status(vault)["sync"]["next"] == "2026-10-29T13:00:00-04:00"  # still due


def test_nothing_starts_while_someone_is_asking_the_page(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    monkeypatch.setattr(llm, "waiting", lambda v: v == vault and clock.now() < at(29, 13, 5))
    runner = FakeRunner(clock)
    sched, lines = scheduler(vault, clock, runner)
    clock.on(at(29, 13, 10), sched.stop)

    sched.run()

    assert starts(runner) == [at(29, 13, 5)]
    assert "schedule: sync waits: someone is asking the page something" in lines


# --once


def test_once_runs_what_is_due_and_exits(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock, sync=20)  # longer than the gap: still only once
    sched, lines = scheduler(vault, clock, runner, once=True)
    assert sched.run() == 0
    assert runner.started == [("sync", at(29, 13))]
    assert lines == ["schedule: sync ok, 2026-10-29 13:00 to 13:20 (20m 0s)"]

    runner.takes["sync"] = timedelta(minutes=2)
    clock.t = at(29, 13, 30)
    sched, _ = scheduler(vault, clock, runner, once=True)
    sched.run()
    clock.t = at(29, 13, 40)  # nothing due yet
    sched, lines = scheduler(vault, clock, runner, once=True)
    assert sched.run() == 0
    assert lines == []
    assert starts(runner) == [at(29, 13), at(29, 13, 30)]

    clock.t = at(30, 1, 31)
    sched, _ = scheduler(vault, clock, runner, once=True)
    sched.run()
    assert runner.started[2:] == [("night", at(30, 1, 31)), ("sync", at(30, 2, 21))]


def test_once_doesnt_wait_for_a_run_from_elsewhere(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    with lock.run(vault, "night"):
        sched, lines = scheduler(vault, clock, runner, once=True)
        assert sched.run() == 0
    assert runner.started == []
    assert lines[0].startswith("schedule: sync waits: night has been running since")
    assert status(vault)["sync"]["next"] == "2026-10-29T13:00:00-04:00"  # due at the next go


def test_once_from_the_command_line(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock, codes={"sync": [1]})
    monkeypatch.setattr(schedule, "Clock", lambda: clock)
    monkeypatch.setattr(schedule, "Runner", lambda: runner)
    before = signal.getsignal(signal.SIGINT)

    with pytest.raises(SystemExit) as exit_:
        cli.main(["schedule", "--once", "--night-at", "off"])

    assert exit_.value.code == 1  # the sync failed
    assert runner.started == [("sync", at(29, 13))]
    assert signal.getsignal(signal.SIGINT) is before
    saved = status(tmp_path / "vault")
    assert saved["night"] == {"at": None, "last": None, "next": None}
    with pytest.raises(SystemExit, match="nothing to run"):
        cli.main(["schedule", "--once", "--night-at", "off", "--sync-every", "0"])


# Failures, stopping, the status file and the log


def test_a_failed_or_unstartable_run_is_said_and_the_schedule_goes_on(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock, codes={"sync": [1, 0]})
    sched, lines = scheduler(vault, clock, runner)
    clock.on(at(29, 13, 20), sched.stop)

    assert sched.run() == 0  # a clean stop; the failure is in the log and the status file

    assert starts(runner) == [at(29, 13), at(29, 13, 15)]
    assert "schedule: sync failed (exit 1), 2026-10-29 13:00 to 13:02 (2m 0s)" in lines
    log = (vault / "logs" / "sync.log").read_text().splitlines()
    assert log == [
        "schedule: sync failed (exit 1), 2026-10-29 13:00 to 13:02 (2m 0s)",
        "schedule: sync ok, 2026-10-29 13:15 to 13:17 (2m 0s)",
    ]

    class Broken:
        def start(self, job, vault, log):
            raise FileNotFoundError("no python here")

    clock = FakeClock(at(29, 14))
    sched, lines = scheduler(vault, clock, Broken(), once=True)
    assert sched.run() == 1
    assert lines == [
        "schedule: sync couldn't start (no python here), 2026-10-29 14:00 to 14:00 (0s)"
    ]
    assert status(vault)["sync"]["next"] == "2026-10-29T14:15:00-04:00"  # not again at once


def test_the_status_file_says_what_runs_and_what_comes_next(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(29, 13))
    runner = FakeRunner(clock)
    sched, _ = scheduler(vault, clock, runner)
    during = []
    clock.on(at(29, 13, 1), lambda: during.append(status(vault)))
    clock.on(at(29, 13, 5), sched.stop)

    sched.run()

    (now,) = during
    assert now["pid"] == os.getpid()
    assert now["since"] == "2026-10-29T13:00:00-04:00"
    assert now["running"] == {"job": "sync", "since": "2026-10-29T13:00:00-04:00", "by": "schedule"}
    assert now["waiting"] is None
    after = status(vault)
    assert after["pid"] is None and after["since"] is None and after["running"] is None
    if os.name != "nt":
        assert os.name == "nt" or (vault / schedule.STATUS).stat().st_mode & 0o777 == 0o600
    assert after["sync"] == {
        "every_minutes": 15,
        "last": {
            "started": "2026-10-29T13:00:00-04:00",
            "ended": "2026-10-29T13:02:00-04:00",
            "result": "ok",
        },
        "next": "2026-10-29T13:15:00-04:00",
    }
    assert after["night"] == {"at": "01:30", "last": None, "next": "2026-10-30T01:30:00-04:00"}


def test_a_stop_stops_the_running_job_cleanly_and_it_runs_again_next_time(tmp_path):
    vault = tmp_path / "vault"
    clock = FakeClock(at(30, 1, 29))
    runner = FakeRunner(clock)
    sched, lines = scheduler(vault, clock, runner, plan=schedule.Plan(None, daytime(1, 30)))
    clock.on(at(30, 1, 40), sched.stop)

    assert sched.run() == 0

    (night,) = runner.processes
    assert (night.stopped, night.killed) == (1, 0)
    assert lines[-3:] == [
        "schedule: stopping night",
        "schedule: night stopped, 2026-10-30 01:30 to 01:40 (10m 4s)",
        "schedule: stopped",
    ]
    assert status(vault)["night"]["next"] == "2026-10-30T01:30:00-04:00"  # still to do

    clock.t = at(30, 7)
    sched, _ = scheduler(vault, clock, runner, plan=schedule.Plan(None, daytime(1, 30)), once=True)
    sched.run()
    assert starts(runner) == [at(30, 1, 30), at(30, 7)]


def test_a_job_that_wont_stop_is_ended_after_the_grace_or_at_a_second_stop(tmp_path):
    for second_stop, ended_by in ((False, schedule.STOP_GRACE), (True, 2)):
        vault = tmp_path / f"vault-{second_stop}"
        clock = FakeClock(at(29, 13))
        runner = FakeRunner(clock, obeys=False)
        sched, _ = scheduler(vault, clock, runner)
        clock.on(at(29, 13, 1), sched.stop)
        if second_stop:
            clock.on(at(29, 13, 1, 1), sched.stop)

        sched.run()

        (sync,) = runner.processes
        assert (sync.stopped, sync.killed) == (1, 1)
        assert sync.ends - at(29, 13, 1) <= timedelta(seconds=ended_by)
        assert status(vault)["sync"]["last"]["result"] == "stopped"


def test_stop_signals_are_caught_while_it_runs_and_given_back_after():
    caught = []
    before = signal.getsignal(signal.SIGTERM)
    with schedule._stop_on_signals(lambda *_: caught.append(1)):
        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)
    assert caught == [1]
    assert signal.getsignal(signal.SIGTERM) is before


# Starting a real job, without starting one


def test_a_job_is_python_m_proxenos_in_its_own_group_with_its_output_in_the_log(
    tmp_path, monkeypatch
):
    config.SETTINGS_FILE.parent.mkdir(parents=True)
    config.SETTINGS_FILE.write_text(json.dumps({"model": "ollama:x"}))
    config.load()
    assert os.environ["PROXENOS_MODEL"] == "ollama:x"
    started = []

    class FakePopen:
        def __init__(self, command, **options):
            os.write(options["stdout"], f"sync: run {len(started) + 1}\n".encode())
            started.append((command, options))
            self.pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(schedule.subprocess, "Popen", FakePopen)
    vault = tmp_path / "vault"
    log = vault / "logs" / "sync.log"

    child = schedule.Runner().start("sync", vault, log)
    schedule.Runner().start("sync", vault, log)

    (command, options), _ = started
    assert command == [sys.executable, "-m", "proxenos", "sync"]
    assert options["stdin"] == subprocess.DEVNULL and options["stderr"] == subprocess.STDOUT
    variables = options["env"]
    assert variables["PROXENOS_VAULT"] == str(vault)
    assert variables["PYTHONUNBUFFERED"] == "1"
    assert "PROXENOS_MODEL" not in variables  # read afresh by the job, so a change counts
    assert variables["PYTHONPATH"].split(os.pathsep)[0] == str(config.REPO_ROOT / "src")
    if os.name == "nt":
        assert options["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert options["start_new_session"] is True
        assert os.name == "nt" or log.stat().st_mode & 0o777 == 0o600
    assert log.read_text() == "sync: run 1\nsync: run 2\n"  # appended, never over
    assert child.poll() is None


def test_a_stop_reaches_the_jobs_whole_group_as_ctrl_c(monkeypatch):
    sent = []
    monkeypatch.setattr(schedule.os, "killpg", lambda pid, sig: sent.append((pid, sig)))

    class Popen:
        pid = 4242

    child = schedule.Child(Popen())
    if os.name == "nt":
        pytest.skip("Windows sends Ctrl-Break instead")
    child.stop()
    child.kill()
    assert sent == [(4242, signal.SIGINT), (4242, signal.SIGKILL)]
