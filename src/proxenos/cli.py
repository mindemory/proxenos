"""The `proxenos` command, also installed as `px`."""

import argparse
import importlib
import json
import pkgutil
import sys
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import ModuleType

import proxenos.clones
import proxenos.ingest
from proxenos import (
    ask,
    auth,
    callserver,
    compare,
    connect,
    demo,
    forms,
    importer,
    lock,
    lookup,
    manuscript,
    master,
    memory,
    notify,
    observe,
    paperdoc,
    phone,
    preprint,
    privacy,
    review,
    schedule,
    setup,
    speech,
    think,
    vectors,
    voice,
    voicemodel,
    webapp,
)
from proxenos.config import vault_path

NIGHT_WAIT = 3600  # seconds a night waits for a running sync before it gives up

# What `proxenos night` runs after the master, in this order: the feed, then the tasks, where
# their health care stands, and advice that read the fresh self-model, the people index and ideas,
# the week's choices (once a week) that read the tasks and ideas, the job leads, which read the
# people index and the openings kept from Ask, and what to watch (once a week), then what each of
# those brings to mind from memory, the projects, the errands still waiting on a way to reach
# someone, the drafts of them all, a step of each project's own work, which takes longest, a
# review of each paper whose project opts in (proxenos.review, after the steps), then each
# project's folder in the user's cloud drive, with what those wrote and the manuscript's
# changes there brought back, the journal of the day that just ended, which reads them all, the
# stories of the months, which read the journal, and last the weeks over time, counted, with more
# artists labelled and looked up for their genres and moods, and the month cards due.
NIGHT_CLONES = (
    "tracker",
    "tasks",
    "care",
    "advisor",
    "network",
    "choices",
    "jobs",
    "watch",
    "recall",
    "projects",
    "errands",
    "work",
    "steps",
    "folders",
    "journal",
    "life",
    "rhythms",
)


def _modules(package: ModuleType) -> dict[str, ModuleType]:
    modules = {}
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        if hasattr(module, "run"):
            modules[info.name] = module
    return modules


def main(argv: list[str] | None = None) -> None:
    groups = {
        "ingest": ("pull a source into the vault", _modules(proxenos.ingest)),
        "clone": ("run one worker clone", _modules(proxenos.clones)),
    }
    parser = argparse.ArgumentParser(
        prog="px" if Path(sys.argv[0]).name == "px" else "proxenos",
        description="Proxenos keeps a private model of you from your own data and works on your "
        "behalf: a research feed, tasks, advice, your network, memories and drafts. It never "
        "sends anything by itself, and calls only when you start the call.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, (help_text, modules) in groups.items():
        names = commands.add_parser(command, help=help_text).add_subparsers(
            dest="name", required=True
        )
        for name, module in modules.items():
            sub = names.add_parser(name, help=(module.__doc__ or "").strip().splitlines()[0])
            if hasattr(module, "add_arguments"):
                module.add_arguments(sub)
    notes = commands.add_parser("observe", help="write notes on new or changed months")
    notes.add_argument("--since", metavar="YYYY-MM", help="skip months before this one")
    notes.add_argument("--dry-run", action="store_true", help="count what would be sent")
    boss = commands.add_parser("master", help="sync, observe and update the self-model")
    boss.add_argument("action", nargs="?", default="run", choices=["run", "consolidate", "accept"])
    boss.add_argument("--since", metavar="YYYY-MM", help="observe only months from this one")
    drop = commands.add_parser("import", help="import downloaded exports from the inboxes")
    drop.add_argument("paths", nargs="*", type=Path, help="zips or folders (default: inboxes)")
    commands.add_parser(
        "sync", help="import downloads and refresh every source; with a key, draft new replies"
    )
    index = commands.add_parser("index", help="index the raw data for search; no model")
    index.add_argument("--rebuild", action="store_true", help="start the index over")
    index.add_argument(
        "--vectors",
        action="store_true",
        help="also embed the last year for search by meaning, with the local embedding model",
    )
    commands.add_parser("night", help="the master, then every clone in turn; for a schedule")
    timing = commands.add_parser(
        "schedule", help="sync every 15 minutes and run the night at 01:30, until stopped"
    )
    schedule.add_arguments(timing)
    page = commands.add_parser("web", help="start the local page and open it")
    page.add_argument("--port", type=int, help=f"default PROXENOS_PORT, else {webapp.PORT}")
    trial = commands.add_parser("demo", help="write a made-up vault to try the page on")
    trial.add_argument("path", nargs="?", type=Path, help="where (default: a new temp folder)")
    commands.add_parser("phone", help="open the page to your own phone, privately, over Tailscale")
    notices = commands.add_parser(
        "notify", help="notices on your phone through ntfy when something new waits on you"
    )
    notices.add_argument("action", choices=["test"], help="test: send a test notice now")
    phoning = commands.add_parser(
        "call", help="place a phone call that waits on hold for you, from a call sheet"
    )
    callserver.add_arguments(phoning)
    asking = commands.add_parser(
        "ask", help="a question or screenshots, answered as you'd think it"
    )
    ask.add_arguments(asking)
    thinking = commands.add_parser(
        "think", help="think anything through with Proxenos, from your own goals and records"
    )
    think.add_arguments(thinking)
    tune = commands.add_parser(
        "voice", help="a small model trained here on your own writing, for reply drafts"
    )
    voicemodel.add_arguments(tune)
    speaking = commands.add_parser(
        "speech", help="Listen's natural voice or your own, made on this Mac; nothing is sent"
    )
    speech.add_arguments(speaking)
    comparing = commands.add_parser(
        "compare", help="which of two models writes replies most like you, judged blind by you"
    )
    compare.add_arguments(comparing)
    form = commands.add_parser(
        "form", help="a PDF form filled in from your records, for you to check, sign and send"
    )
    forms.add_arguments(form)
    finding = commands.add_parser(
        "lookup", help="a person's public email address, from their organization's own pages"
    )
    lookup.add_arguments(finding)
    paper = commands.add_parser(
        "project", help="a project's manuscript, its versions, their changes and its Google Doc"
    ).add_subparsers(dest="what", required=True)
    manuscript.add_arguments(
        paper.add_parser("manuscript", help="its versions and their changes, as JSON")
    )
    paperdoc.add_arguments(
        paper.add_parser(
            "gdocs", help="it as a Google Doc: make it, bring back its changes, read its comments"
        )
    )
    reviewing = commands.add_parser(
        "review",
        help="a project's paper peer-reviewed in rounds: reviews, a plan, the revision as steps, "
        "a response letter",
    )
    review.add_arguments(reviewing)
    posting = commands.add_parser(
        "preprint", help="a LaTeX paper ready for arXiv: its references checked, its source bundled"
    )
    preprint.add_arguments(posting)
    commands.add_parser("connect", help="which sources are connected, as JSON for the page")
    commands.add_parser(
        "privacy", help="what stays here, what went to a model and what's read, as JSON"
    )
    settings = commands.add_parser("setup", help="your settings and which secrets are set, as JSON")
    settings.add_argument(
        "--apply", action="store_true", help="make one change, read as JSON from stdin"
    )
    sign_in = commands.add_parser(
        "auth", help="sign in once in the browser; the token is saved, never shown"
    )
    sign_in.add_argument(
        "service",
        choices=[
            "strava",
            "spotify",
            "slack",
            "slackdump",
            "gmail",
            "gcalendar",
            "gdocs",
            "microsoft",
            "beeper",
        ],
    )
    sign_in.add_argument(
        "account",
        nargs="*",
        help="for gmail, gcalendar, gdocs and microsoft: NAME ADDRESS, e.g. personal me@x.com; "
        "for slackdump: the workspace",
    )
    args = parser.parse_args(argv)

    if args.command == "web":
        webapp.serve(args.port or webapp.page_port())
        return
    if args.command == "demo":
        print(demo.run(args.path))
        return
    if args.command == "ask":
        ask.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "think":
        think.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "voice":
        voicemodel.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "speech":  # its own server; works alongside a sync
        speech.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "compare":  # JSON for the page; nothing is sent to anyone
        print(json.dumps(compare.run(vault_path(), args), ensure_ascii=False))
        return
    if args.command == "form":
        print(_summary("form", forms.run(vault_path(), args)))
        return
    if args.command == "lookup":  # needs no vault; sends only the name and the place
        print(json.dumps(lookup.run(args), ensure_ascii=False, indent=1))
        return
    if args.command == "phone":
        vault_path()  # loads settings
        print(phone.setup())
        return
    if args.command == "notify":
        vault_path()  # loads settings and secrets
        sent, said = notify.test()
        print(said)
        if not sent:
            raise SystemExit(1)
        return
    if args.command == "call":  # a call can go on while a sync runs, so it takes no lock
        callserver.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "preprint":  # sends only references' DOIs, titles and links; no model
        preprint.run(vault_path(), args)  # the vault, when there is one, keeps what was found
        return
    if args.command == "review":  # the paper and its code to the review model; a lock per project
        for line in review.run(vault_path(), args):  # vault_path also loads settings
            print(line)
        return
    if args.command == "project":  # reads the code's history; writes only what the user asks for
        module = paperdoc if args.what == "gdocs" else manuscript
        print(json.dumps(module.run(vault_path(), args), ensure_ascii=False))
        return
    if args.command == "connect":
        print(json.dumps(connect.report(vault_path())))  # vault_path also loads settings
        return
    if args.command == "privacy":
        print(json.dumps(privacy.report(vault_path())))  # vault_path also loads settings
        return
    if args.command == "setup":  # works before there's a vault, and with one in the wrong place
        if not args.apply:
            print(json.dumps(setup.status()))
            return
        try:
            request = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            request = None
        print(json.dumps(setup.apply(request)))
        return
    if args.command == "auth":
        vault = vault_path()  # also loads settings and secrets
        if args.service == "slack":
            print(auth.slack(vault / "state" / "slack_apps.json"))
        elif args.service == "beeper":
            print(auth.beeper())
        elif args.service == "slackdump":
            if len(args.account) != 1:
                raise SystemExit("usage: proxenos auth slackdump WORKSPACE, e.g. acme")
            print(auth.slackdump(args.account[0]))
        elif args.service in ("gmail", "gcalendar", "gdocs", "microsoft"):
            if len(args.account) != 2:
                raise SystemExit(f"usage: proxenos auth {args.service} NAME ADDRESS")
            print(getattr(auth, args.service)(*args.account))
        elif args.service == "spotify":
            print(auth.spotify())
        else:
            print(auth.strava())
        return
    vault = vault_path()
    vault.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.command == "schedule":
        if code := schedule.run(vault, args):
            raise SystemExit(code)
        return
    job = _exclusive(args)
    if job == "night":
        _wait_for_sync(vault)
    try:
        with lock.run(vault, job) if job else nullcontext():
            _command(args, vault, groups)
    except lock.Busy as busy:
        print(f"{job}: not started; {busy}", file=sys.stderr)
        raise SystemExit(lock.BUSY) from None


def _wait_for_sync(vault: Path, wait: float = NIGHT_WAIT, every: float = 30) -> None:
    """Let a sync that's running finish before the night starts, for up to `wait` seconds. The
    night has one slot a day under launchd, so giving up on a sync that ran long would lose the
    whole day; a sync is minutes. Anything else holding the lock still turns the night away."""
    deadline = time.monotonic() + wait
    said = False
    while (held := lock.holder(vault)) and held.get("job") == "sync":
        if time.monotonic() >= deadline:
            return
        if not said:
            print(f"night: waiting; {lock.describe(held)}", file=sys.stderr, flush=True)
            said = True
        time.sleep(every)


def _exclusive(args: argparse.Namespace) -> str | None:
    """The runs that refresh the whole vault, which never overlap, whoever starts them: the
    scheduler, launchd, the page or a terminal. One that finds another going exits with
    lock.BUSY, and the scheduler, or launchd's next slot, tries again later; a night first waits
    out a sync that's running (`_wait_for_sync`), since its next slot is a day away."""
    if args.command in ("sync", "night"):
        return args.command
    if args.command == "master" and args.action == "run":
        return "master"
    return None


def _command(
    args: argparse.Namespace, vault: Path, groups: dict[str, tuple[str, dict[str, ModuleType]]]
) -> None:
    if args.command == "night":
        if not night(vault, groups["clone"][1]):
            raise SystemExit(1)
        return
    if args.command == "observe":
        stats = observe.observe(vault, args.since, args.dry_run)
    elif args.command == "import":
        stats = importer.run(vault, args.paths or None)
    elif args.command == "sync":
        stats = master.sync(vault)
        stats |= notify.run(vault)  # last, once what the sync brought in is counted
    elif args.command == "index":
        stats = memory.build(vault, args.rebuild)
        if args.vectors:
            stats |= vectors.update(vault)
    elif args.command == "master":
        actions = {
            "run": lambda: master.run(vault, args.since),
            "consolidate": lambda: master.consolidate(vault),
            "accept": lambda: master.accept(vault),
        }
        stats = actions[args.action]()
    else:
        stats = groups[args.command][1][args.name].run(vault, args)
    if stats is not None:  # None: the clone printed its whole answer, JSON for the page
        print(_summary(getattr(args, "name", None) or args.command, stats))


def night(vault: Path, clones: dict[str, ModuleType]) -> bool:
    """The master's run (sync, observe, consolidate), then each of NIGHT_CLONES with its
    default arguments, then the voice model trained again where it's due, then the writing
    rules learned from drafts the user changed (proxenos.voice.lessons, nothing until enough are
    new), and last, with notices on, one to the user's phone when something new waits on them
    (proxenos.notify, held through quiet hours), one summary line each with how long it took, so
    a slow step shows in the log. A step that fails is reported and the rest still run. Whether
    every step worked."""
    print(f"night: started {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    steps: list[tuple[str, Callable[[], dict[str, int]]]] = [("master", lambda: master.run(vault))]
    for name in NIGHT_CLONES:
        steps.append((name, lambda module=clones[name]: module.run(vault, _defaults(module))))
        if name == "steps":  # only projects that opt in; before folders takes the letter
            steps.append(("review", lambda: review.night(vault)))
    steps.append(("voice", lambda: voicemodel.refresh(vault)))
    steps.append(("lessons", lambda: voice.lessons(vault)))
    if notify.configured():
        steps.append(("notify", lambda: notify.run(vault)))  # never fails the night
    ok = True
    for name, step in steps:
        began = time.monotonic()
        try:
            line = _summary(name, step())
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one failed step must not stop the rest
            ok = False
            reason = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
            line = f"{name}: failed ({' '.join(reason.split())[:300]})"
        print(f"{line} [{_took(time.monotonic() - began)}]", flush=True)
    return ok


def _took(seconds: float) -> str:
    """A step's time as the log shows it: "8s", "4m 12s", "1h 03m"."""
    s = round(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s" if s < 3600 else f"{s // 3600}h {s % 3600 // 60:02d}m"


def _defaults(module: ModuleType) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    if hasattr(module, "add_arguments"):
        module.add_arguments(parser)
    return parser.parse_args([])


def _summary(label: str, stats: dict[str, int]) -> str:
    return f"{label}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items())
