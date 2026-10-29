"""The `proxenos` command, also installed as `px`."""

import argparse
import importlib
import json
import pkgutil
import sys
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
    connect,
    demo,
    importer,
    lock,
    master,
    memory,
    observe,
    phone,
    schedule,
    setup,
    vectors,
    webapp,
)
from proxenos.config import vault_path

# What `proxenos night` runs after the master, in this order: the feed, then the tasks, where
# their health care stands, and advice that read the fresh self-model, the people index and ideas,
# then what each of those brings to mind from memory, the projects, the errands still waiting on a
# way to reach someone, and last the drafts of them all.
NIGHT_CLONES = (
    "tracker",
    "tasks",
    "care",
    "advisor",
    "network",
    "recall",
    "projects",
    "errands",
    "work",
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
        "sends anything by itself.",
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
    page.add_argument("--port", type=int, default=webapp.PORT, help=f"default {webapp.PORT}")
    trial = commands.add_parser("demo", help="write a made-up vault to try the page on")
    trial.add_argument("path", nargs="?", type=Path, help="where (default: a new temp folder)")
    commands.add_parser("phone", help="open the page to your own phone, privately, over Tailscale")
    asking = commands.add_parser(
        "ask", help="a question or screenshots, answered as you'd think it"
    )
    ask.add_arguments(asking)
    commands.add_parser("connect", help="which sources are connected, as JSON for the page")
    settings = commands.add_parser("setup", help="your settings and which secrets are set, as JSON")
    settings.add_argument(
        "--apply", action="store_true", help="make one change, read as JSON from stdin"
    )
    sign_in = commands.add_parser(
        "auth", help="sign in once in the browser; the token is saved, never shown"
    )
    sign_in.add_argument(
        "service",
        choices=["strava", "slack", "slackdump", "gmail", "gcalendar", "microsoft", "beeper"],
    )
    sign_in.add_argument(
        "account",
        nargs="*",
        help="for gmail, gcalendar and microsoft: NAME ADDRESS, e.g. personal me@x.com; for "
        "slackdump: the workspace",
    )
    args = parser.parse_args(argv)

    if args.command == "web":
        webapp.serve(args.port)
        return
    if args.command == "demo":
        print(demo.run(args.path))
        return
    if args.command == "ask":
        ask.run(vault_path(), args)  # vault_path also loads settings
        return
    if args.command == "phone":
        vault_path()  # loads settings
        print(phone.setup())
        return
    if args.command == "connect":
        print(json.dumps(connect.report(vault_path())))  # vault_path also loads settings
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
        elif args.service in ("gmail", "gcalendar", "microsoft"):
            if len(args.account) != 2:
                raise SystemExit(f"usage: proxenos auth {args.service} NAME ADDRESS")
            print(getattr(auth, args.service)(*args.account))
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
    try:
        with lock.run(vault, job) if job else nullcontext():
            _command(args, vault, groups)
    except lock.Busy as busy:
        print(f"{job}: not started; {busy}", file=sys.stderr)
        raise SystemExit(lock.BUSY) from None


def _exclusive(args: argparse.Namespace) -> str | None:
    """The runs that refresh the whole vault, which never overlap, whoever starts them: the
    scheduler, launchd, the page or a terminal. One that finds another going exits with
    lock.BUSY, and the scheduler, or launchd's next slot, tries again later."""
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
    print(_summary(getattr(args, "name", None) or args.command, stats))


def night(vault: Path, clones: dict[str, ModuleType]) -> bool:
    """The master's run (sync, observe, consolidate), then each of NIGHT_CLONES with its
    default arguments, one summary line each. A step that fails is reported and the rest
    still run. Whether every step worked."""
    print(f"night: started {datetime.now():%Y-%m-%d %H:%M}", flush=True)
    steps: list[tuple[str, Callable[[], dict[str, int]]]] = [("master", lambda: master.run(vault))]
    for name in NIGHT_CLONES:
        steps.append((name, lambda module=clones[name]: module.run(vault, _defaults(module))))
    ok = True
    for name, step in steps:
        try:
            line = _summary(name, step())
        except (Exception, SystemExit) as e:  # noqa: BLE001 - one failed step must not stop the rest
            ok = False
            reason = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
            line = f"{name}: failed ({' '.join(reason.split())[:300]})"
        print(line, flush=True)
    return ok


def _defaults(module: ModuleType) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    if hasattr(module, "add_arguments"):
        module.add_arguments(parser)
    return parser.parse_args([])


def _summary(label: str, stats: dict[str, int]) -> str:
    return f"{label}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items())
