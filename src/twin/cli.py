"""The `twin` command."""

import argparse
import importlib
import pkgutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import ModuleType

import twin.clones
import twin.ingest
from twin import auth, importer, master, observe, webapp
from twin.config import REPO_ROOT, vault_path

# What `twin night` runs after the master, in this order: the feed, then the tasks and advice
# that read the fresh self-model, the people index and ideas, and last the drafts of them all.
NIGHT_CLONES = ("tracker", "tasks", "advisor", "network", "work")


def _modules(package: ModuleType) -> dict[str, ModuleType]:
    modules = {}
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        if hasattr(module, "run"):
            modules[info.name] = module
    return modules


def main(argv: list[str] | None = None) -> None:
    groups = {
        "ingest": ("pull a source into the vault", _modules(twin.ingest)),
        "clone": ("run one worker clone", _modules(twin.clones)),
    }
    parser = argparse.ArgumentParser(prog="twin")
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
    commands.add_parser("sync", help="import downloads and refresh every source; no model")
    commands.add_parser("night", help="the master, then every clone in turn; for a schedule")
    commands.add_parser("web", help="start the local page and open it")
    sign_in = commands.add_parser("auth", help="sign in once in the browser, token goes to .env")
    sign_in.add_argument("service", choices=["strava", "slack"])
    args = parser.parse_args(argv)

    if args.command == "web":
        webapp.serve()
        return
    if args.command == "auth":
        vault = vault_path()  # also loads .env
        if args.service == "slack":
            print(auth.slack(REPO_ROOT / ".env", vault / "state" / "slack_apps.json"))
        else:
            print(auth.strava(REPO_ROOT / ".env"))
        return
    vault = vault_path()
    vault.mkdir(mode=0o700, parents=True, exist_ok=True)
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
