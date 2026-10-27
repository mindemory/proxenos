"""The `twin` command."""

import argparse
import importlib
import pkgutil
from types import ModuleType

import twin.clones
import twin.ingest
from twin import auth, master, observe
from twin.config import REPO_ROOT, vault_path


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
    sign_in = commands.add_parser("auth", help="sign in once in the browser, token goes to .env")
    sign_in.add_argument("service", choices=["strava"])
    args = parser.parse_args(argv)

    if args.command == "auth":
        vault_path()  # loads .env
        print(auth.strava(REPO_ROOT / ".env"))
        return
    vault = vault_path()
    vault.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.command == "observe":
        stats = observe.observe(vault, args.since, args.dry_run)
    elif args.command == "master":
        actions = {
            "run": lambda: master.run(vault, args.since),
            "consolidate": lambda: master.consolidate(vault),
            "accept": lambda: master.accept(vault),
        }
        stats = actions[args.action]()
    else:
        stats = groups[args.command][1][args.name].run(vault, args)
    label = getattr(args, "name", None) or args.command
    print(f"{label}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in stats.items()))
