"""`proxenos schedule`: keeps the vault current by itself, the same on macOS, Windows and Linux.

It runs `proxenos sync` every 15 minutes and `proxenos night` once a day at 01:30, local time.
Each run is a child process (`python -m proxenos sync`), so a crash in one never stops the
schedule, with its output appended to <vault>/logs/sync.log or night.log, as the launchd jobs
from scripts/install-*.sh do. The coming Mac and Windows apps run it themselves; from source,
keep it running with a Task Scheduler entry or a systemd user unit (docs/apps.md).

- **Catching up:** a computer that slept, or was off, through a slot runs that job once when it's
  back, not once per slot it missed. The next times are kept in the status file, so a restart
  catches up the same way.
- **Never two at once:** every sync, night and master run holds the vault's run lock (lock.py),
  whoever started it, so nothing starts while one from launchd or a terminal goes on; one of the
  very job that's due counts as its run. sync waits while night runs, and when both are due
  night goes first, since it begins with a sync of its own. A vault has one scheduler at a time.
- **Someone asking:** nothing starts while the page answers a question (llm.waiting).
- **Stopping:** Ctrl-C, SIGTERM, SIGHUP or Ctrl-Break stops a running job cleanly: it's
  interrupted the way Ctrl-C would, given STOP_GRACE seconds, then ended; a second Ctrl-C ends it
  at once. A stopped run doesn't count, so it runs again on the next start; every step of sync
  and night is safe to run twice.
- **Status:** a line per run, in the job's log and on the scheduler's own output, and
  <vault>/state/schedule.json for the page:
  {"pid": the scheduler's while it runs, else null, "since", "updated",
   "running": {"job", "since", "by": "schedule" or "elsewhere"} or null,
   "waiting": why a job that's due hasn't started, or null,
   "sync": {"every_minutes", "last": {"started", "ended", "result"}, "next"},
   "night": {"at", "last", "next"}}

PROXENOS_SYNC_EVERY (minutes, 0 for never) and PROXENOS_NIGHT_AT (HH:MM, or off) set the times,
from the environment, .env or the settings file; --sync-every and --night-at override them.
`--once` runs whatever is due and exits, for trying it out or for an operating system's own
scheduler.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import time as daytime
from pathlib import Path
from typing import Protocol

from proxenos import config, llm, lock
from proxenos.config import env

SYNC_EVERY = 15  # minutes
NIGHT_AT = "01:30"
# The order when both are due: night first, since it begins with a sync of its own.
JOBS = ("night", "sync")
STATUS = Path("state", "schedule.json")
TICK = 60  # seconds: the longest the loop sleeps, so a wake from sleep is seen within a minute
POLL = 2  # seconds between looks at a running job
STOP_GRACE = 20  # seconds a stopped job has to wind down before it's ended
# What stops the schedule, of those this system has: Ctrl-C, a service manager or shutdown, the
# terminal closing, and Ctrl-Break on Windows.
STOP_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sync-every",
        metavar="MINUTES",
        help=f"minutes between syncs, 0 for none (default PROXENOS_SYNC_EVERY, else {SYNC_EVERY})",
    )
    parser.add_argument(
        "--night-at",
        metavar="HH:MM",
        help=f"local time of the nightly run, or off (default PROXENOS_NIGHT_AT, else {NIGHT_AT})",
    )
    parser.add_argument(
        "--once", action="store_true", help="run whatever is due, then exit, instead of staying on"
    )


def run(vault: Path, args: argparse.Namespace) -> int:
    """Keep the schedule for `vault` until stopped, or with --once until nothing is due. The exit
    status: 0; with --once, 1 when a run failed; lock.BUSY when another scheduler keeps this
    vault."""
    scheduler = Scheduler(vault, plan(args), once=args.once)
    with _stop_on_signals(scheduler.stop):
        return scheduler.run()


@dataclass(frozen=True)
class Plan:
    """When each job runs: sync every `sync_every`, night each day at `night_at`, local time.
    None turns one off."""

    sync_every: timedelta | None
    night_at: daytime | None

    @property
    def jobs(self) -> tuple[str, ...]:
        on = {"sync": self.sync_every, "night": self.night_at}
        return tuple(job for job in JOBS if on[job] is not None)

    def following(self, job: str, after: datetime, tz: tzinfo | None = None) -> datetime:
        """When `job` is next due after a run (or a look) at `after`."""
        if job == "sync":
            assert self.sync_every is not None
            return after + self.sync_every
        assert self.night_at is not None
        return next_night(after, self.night_at, tz)

    def fields(self, job: str) -> dict:
        """The job's plan as the status file shows it."""
        if job == "sync":
            every = self.sync_every
            return {"every_minutes": int(every.total_seconds()) // 60 if every else None}
        return {"at": f"{self.night_at:%H:%M}" if self.night_at else None}


def plan(args: argparse.Namespace) -> Plan:
    """The plan from the flags, else the settings, else the defaults."""
    every = args.sync_every if args.sync_every is not None else env("SYNC_EVERY") or SYNC_EVERY
    at = args.night_at if args.night_at is not None else env("NIGHT_AT") or NIGHT_AT
    chosen = Plan(_minutes(str(every)), _local_time(str(at)))
    if not chosen.jobs:
        raise SystemExit("schedule: sync and night are both off, so there's nothing to run")
    return chosen


def next_night(after: datetime, at: daytime, tz: tzinfo | None = None) -> datetime:
    """The first `at` o'clock strictly after `after`, local time (`tz`, else this computer's own
    zone). On the days the clocks change, a time that doesn't happen that day comes an hour
    later, and one that happens twice counts the first time."""
    day = after.astimezone(tz).date()
    while True:
        slot = datetime.combine(day, at)
        if tz is None:
            slot = slot.astimezone()
        else:  # by way of UTC, so a time the clocks skip comes out as the one it means
            slot = slot.replace(tzinfo=tz).astimezone(UTC).astimezone(tz)
        if slot > after:
            return slot
        day += timedelta(days=1)


class Clock:
    """The time, and sleeping; tests bring a fake. `tz` None is this computer's own zone, read
    afresh each time, so moving to another zone counts at once."""

    tz: tzinfo | None = None

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def sleep(self, seconds: float, stop: Callable[[], bool]) -> None:
        """Sleep up to `seconds`, a second at a time so a stop is seen at once. It also ends once
        the wall clock has moved on that far: the computer slept, and what's due should run."""
        start, wall = time.monotonic(), time.time()
        while not stop():
            left = seconds - max(time.monotonic() - start, time.time() - wall)
            if left <= 0:
                return
            time.sleep(min(1.0, left))


class Process(Protocol):
    """A running job, as the scheduler follows it."""

    def poll(self) -> int | None: ...

    def stop(self) -> None: ...

    def kill(self) -> None: ...


class Child:
    """A job running as a child process, in a process group of its own, so a Ctrl-C at the
    terminal reaches the scheduler, which stops the job cleanly, and not the job directly."""

    def __init__(self, popen: subprocess.Popen):
        self.popen = popen

    def poll(self) -> int | None:
        return self.popen.poll()

    def stop(self) -> None:
        """Interrupt it the way Ctrl-C would: SIGINT to its process group, or Ctrl-Break on
        Windows, which `python -m proxenos` turns into the same KeyboardInterrupt."""
        try:
            if os.name == "nt":
                self.popen.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.popen.pid, signal.SIGINT)
        except OSError:
            self.kill()

    def kill(self) -> None:
        with suppress(OSError):
            if os.name == "nt":
                self.popen.kill()
            else:
                os.killpg(self.popen.pid, signal.SIGKILL)


class Runner:
    """Starts each job as `python -m proxenos <job>` with the interpreter running this, so the
    same code runs it however Proxenos was installed."""

    def command(self, job: str) -> list[str]:
        return [sys.executable, "-m", "proxenos", job]

    def environment(self, vault: Path) -> dict[str, str]:
        """The environment the scheduler came with, so each job reads .env, the settings and the
        Keychain afresh and a change saved since counts, on this scheduler's vault."""
        variables = config.environment()
        variables["PROXENOS_VAULT"] = str(vault)
        variables["PYTHONUNBUFFERED"] = "1"  # the log in the order things happened
        if config.FROM_SOURCE:  # this checkout's code, even when the install points at another
            paths = (str(config.REPO_ROOT / "src"), variables.get("PYTHONPATH", ""))
            variables["PYTHONPATH"] = os.pathsep.join(p for p in paths if p)
        return variables

    def start(self, job: str, vault: Path, log: Path) -> Process:
        log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            # Windows' append is this process's own, not the file's, so the child starts at the end.
            os.lseek(fd, 0, os.SEEK_END)
            popen = subprocess.Popen(
                self.command(job),
                stdin=subprocess.DEVNULL,
                stdout=fd,
                stderr=subprocess.STDOUT,
                env=self.environment(vault),
                **_own_group(),
            )
        finally:
            os.close(fd)
        return Child(popen)


@dataclass
class _Running:
    job: str
    process: Process
    started: datetime
    stopping: datetime | None = None
    killed: bool = False


class Scheduler:
    """The loop: what's due, what holds it off, running it, and what the status file says."""

    def __init__(
        self,
        vault: Path,
        plan: Plan,
        *,
        once: bool = False,
        clock: Clock | None = None,
        runner: Runner | None = None,
        say: Callable[[str], None] | None = None,
    ):
        self.vault = vault
        self.plan = plan
        self.once = once
        self.clock = clock or Clock()
        self.runner = runner or Runner()
        self.say = say or _print
        self.next: dict[str, datetime] = {}
        self.last: dict[str, dict] = {}
        self.child: _Running | None = None
        self.elsewhere: dict | None = None  # a run another process has going, when last looked
        self.waiting = ""  # why the job that's due hasn't started
        self.ran: set[str] = set()  # with --once, each job runs at most once
        self.failed = False
        self.stops = 0
        self.since: datetime | None = None  # while this keeps the schedule

    def stop(self, *_: object) -> None:
        """Stop: nothing more starts, and a running job is stopped cleanly; a second stop ends it
        at once. It only counts, so it's safe from a signal handler."""
        self.stops += 1

    def run(self) -> int:
        """Keep the schedule until stopped, or with `once` until nothing more is due. 0, or with
        `once` 1 when a run failed, for the scheduler that started it; a schedule that's kept
        says its failures in the logs and the status file, and a clean stop is a clean stop.
        lock.BUSY when another scheduler keeps this vault."""
        mine = lock.Lock(self.vault / lock.SCHEDULER)
        if not mine.acquire():
            pid = self._saved().get("pid")
            other = f" (process {pid})" if isinstance(pid, int) else ""
            self.say(f"schedule: another scheduler already keeps {self.vault}{other}")
            return lock.BUSY
        try:
            self._begin()
            self._loop()
        finally:
            self.since = None
            self._save()
            mine.release()
            if not self.once:
                self.say("schedule: stopped")
        return 1 if self.once and self.failed else 0

    def _begin(self) -> None:
        """Pick up where the last scheduler left off: a slot missed while none ran is due now."""
        now = self.since = self.clock.now()
        saved = self._saved()
        for job in JOBS:
            entry = saved.get(job) if isinstance(saved.get(job), dict) else {}
            if isinstance(entry.get("last"), dict):
                self.last[job] = entry["last"]
            if job not in self.plan.jobs:
                continue
            kept = _parse(entry.get("next"))
            changed = any(entry.get(k) != v for k, v in self.plan.fields(job).items())
            if kept is None:  # never scheduled: a sync now, the night at its time
                kept = now if job == "sync" else self._following(job, now)
            elif changed and kept > now:  # new times: from now on, but a missed slot still runs
                kept = self._following(job, now)
            self.next[job] = kept
        if not self.once:
            plans = {"sync": "sync every {every_minutes} minutes", "night": "night at {at}"}
            said = [
                plans[job].format(**self.plan.fields(job)) + f", next {self._when(self.next[job])}"
                for job in reversed(self.plan.jobs)
            ]
            self.say(f"schedule: keeping {self.vault}: {'; '.join(said)}")
        self._save()

    def _loop(self) -> None:
        while True:
            now = self.clock.now()
            if self.child is not None:
                self._follow(self.child, now)
                continue
            if self.stops:
                return
            job = self._due(now)
            if job is not None:
                self._start(job, now)
                continue
            if self.once:
                return
            if self.elsewhere is not None and lock.holder(self.vault) is None:
                self.elsewhere = None  # the run from elsewhere has ended
                self._save()
            self.clock.sleep(self._wait(now), lambda: self.stops > 0)

    def _due(self, now: datetime) -> str | None:
        """The job to start now, if any. One that's due but held off says why, once."""
        held = ""
        for job in self.plan.jobs:
            if job in self.ran:
                continue
            # A clock set back (by hand, or by the network's time) never leaves a job far off.
            self.next[job] = min(self.next[job], self._following(job, now))
            if now < self.next[job]:
                continue
            self.elsewhere = holder = lock.holder(self.vault)
            if holder is not None and holder.get("job") == job:
                self._counted(job, holder, now)
                continue
            if holder is not None:
                held = f"{job} waits: {lock.describe(holder)}"
            elif llm.waiting(self.vault):
                held = f"{job} waits: someone is asking the page something"
            else:
                self._hold("")
                return job
            break
        self._hold(held)
        return None

    def _hold(self, why: str) -> None:
        if why == self.waiting:
            return
        self.waiting = why
        if why:
            self.say(f"schedule: {why}")
        self._save()

    def _counted(self, job: str, holder: dict, now: datetime) -> None:
        """The very job that's due is already running, started elsewhere: that's its run."""
        started = _parse(holder.get("started")) or now
        self.last[job] = {"started": _iso(started), "ended": None, "result": "started elsewhere"}
        self.next[job] = self._following(job, now)
        self.say(f"schedule: {job} not started, one is already going: {lock.describe(holder)}")
        self._save()

    def _start(self, job: str, now: datetime) -> None:
        if self.once:
            self.ran.add(job)
        try:
            process = self.runner.start(job, self.vault, self._log(job))
        except OSError as e:  # counted, so it's tried at the next slot rather than in a loop
            self.failed = True
            self._record(job, now, now, f"couldn't start ({e})", counts=True)
            return
        self.child = _Running(job, process, now)
        self.elsewhere = None
        self._save()

    def _follow(self, running: _Running, now: datetime) -> None:
        code = running.process.poll()
        if code is not None:
            self._finished(running, code, now)
            return
        if self.stops and running.stopping is None:
            running.stopping = now
            self.say(f"schedule: stopping {running.job}")
            running.process.stop()
        elif running.stopping is not None and not running.killed:
            if self.stops > 1 or now - running.stopping >= timedelta(seconds=STOP_GRACE):
                running.killed = True
                running.process.kill()
        self.clock.sleep(POLL, lambda: False)

    def _finished(self, running: _Running, code: int, now: datetime) -> None:
        self.child = None
        job = running.job
        if running.stopping is not None:  # not counted: it runs again next time
            self._record(job, running.started, now, "stopped", counts=False)
        elif code == lock.BUSY:  # another run took the lock first; the loop waits for it
            self.say(f"schedule: {job} not started: another run had just begun")
            self._save()
        elif code == 0:
            self._record(job, running.started, now, "ok", counts=True)
        else:
            self.failed = True
            self._record(job, running.started, now, f"failed (exit {code})", counts=True)

    def _record(
        self, job: str, started: datetime, ended: datetime, result: str, counts: bool
    ) -> None:
        """One run's end: in the status file, and a line in its log and on the output."""
        self.last[job] = {"started": _iso(started), "ended": _iso(ended), "result": result}
        if counts:
            self.next[job] = self._following(job, started)
        start, end = started.astimezone(self.clock.tz), ended.astimezone(self.clock.tz)
        line = (
            f"schedule: {job} {result}, {start:%Y-%m-%d %H:%M} to {end:%H:%M}"
            f" ({_took(ended - started)})"
        )
        self.say(line)
        _append(self._log(job), line)
        self._save()

    def _wait(self, now: datetime) -> float:
        """Seconds until the next look: a job's time, at most a TICK, and a TICK while one that's
        due is held off."""
        if self.waiting or not self.next:
            return TICK
        soonest = min(self.next.values())
        return max(1.0, min(float(TICK), (soonest - now).total_seconds()))

    def _following(self, job: str, after: datetime) -> datetime:
        return self.plan.following(job, after, self.clock.tz)

    def _when(self, moment: datetime) -> str:
        local = moment.astimezone(self.clock.tz)
        return f"{local:%Y-%m-%d %H:%M}"

    def _log(self, job: str) -> Path:
        return self.vault / "logs" / f"{job}.log"

    def _saved(self) -> dict:
        try:
            status = json.loads((self.vault / STATUS).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return status if isinstance(status, dict) else {}

    def _save(self) -> None:
        if self.child is not None:
            running = {"job": self.child.job, "since": _iso(self.child.started), "by": "schedule"}
        elif self.elsewhere:
            held = self.elsewhere
            running = {"job": held.get("job"), "since": held.get("started"), "by": "elsewhere"}
        else:
            running = None
        status: dict = {
            "pid": os.getpid() if self.since else None,
            "since": _iso(self.since) if self.since else None,
            "updated": _iso(self.clock.now()),
            "running": running,
            "waiting": self.waiting or None,
        }
        for job in reversed(JOBS):
            due = self.next.get(job) if job in self.plan.jobs else None
            status[job] = {
                **self.plan.fields(job),
                "last": self.last.get(job),
                "next": _iso(due) if due else None,
            }
        lock.write_json(self.vault / STATUS, status)


@contextmanager
def _stop_on_signals(stop: Callable[..., None]) -> Iterator[None]:
    """While the schedule runs, each of STOP_SIGNALS this system has asks it to stop."""
    previous = {}
    for name in STOP_SIGNALS:
        number = getattr(signal, name, None)
        if number is None:
            continue
        with suppress(OSError, ValueError):  # not catchable here, or not the main thread
            previous[number] = signal.signal(number, stop)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _print(line: str) -> None:
    """A line on the output, when there is one: a closed pipe (the app that started this has
    gone) or none at all (pythonw on Windows) never stops the schedule."""
    with suppress(OSError, ValueError):
        print(line, flush=True)


def _own_group() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _minutes(value: str) -> timedelta | None:
    text = value.strip().lower()
    if text in ("0", "off"):
        return None
    if not text.isdigit() or not 1 <= int(text) <= 1440:
        raise SystemExit(
            f"schedule: sync every {value!r}? Give whole minutes, 1 to 1440, or 0 for never"
        )
    return timedelta(minutes=int(text))


def _local_time(value: str) -> daytime | None:
    text = value.strip().lower()
    if text == "off":
        return None
    found = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not found or int(found[1]) > 23 or int(found[2]) > 59:
        raise SystemExit(f"schedule: night at {value!r}? Give a local time as HH:MM, or off")
    return daytime(int(found[1]), int(found[2]))


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _took(span: timedelta) -> str:
    seconds = max(0, round(span.total_seconds()))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


def _append(log: Path, line: str) -> None:
    with suppress(OSError):
        log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "ab") as out:
            out.write(f"{line}\n".encode())
