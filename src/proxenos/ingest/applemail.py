"""Email from Apple Mail's local store, so any account added to Mail comes in with no sign-in.

Gmail, Google Workspace, Outlook and Microsoft 365 accounts all work once they are in System
Settings, Internet Accounts. Mail has to run (open at login is enough) to fetch, and macOS keeps
~/Library/Mail private until the Python that runs Proxenos has Full Disk Access.

Reads the .emlx and .partial.emlx files under ~/Library/Mail/V*/<account>/<mailbox>.mbox/ (the
highest version) and writes vault/raw/email/<account>/, one stream per address. Records come from
the mbox ingester's parser, so they match its fields and Message-ID keys, and a message that is
also in a Takeout export or a Gmail sync merges with it. <account> is the address made
path-safe, as for Takeout. Mail's account folders don't name their address, so it is the one in
PROXENOS_EMAILS that appears most in that account's From, To and Cc; an account with none is
skipped and counted, and --full retries it once PROXENOS_EMAILS is fixed. The mailbox's path
("INBOX", "[Gmail]/Sent Mail") goes in gmail_labels. Junk, spam and trash are left out.

The first run reads messages saved in the last 180 days. Later runs read only files changed since
the newest one seen, kept with each account's address in vault/state/applemail.json; --full reads
everything. It only reads: it never changes Mail's files.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from proxenos.config import env
from proxenos.ingest import email
from proxenos.store import merge_monthly

DEFAULT_ROOT = Path("~/Library/Mail").expanduser()
FIRST_RUN_DAYS = 180
SAMPLE = 500  # messages read to tell which address an account is
BATCH = 2000  # records per merge

_VERSION = re.compile(r"V\d+")
_ACCOUNT = re.compile(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", re.IGNORECASE)
# Mailbox names, whatever the provider calls them: [Gmail]/Spam, Junk Email, Deleted Items ...
_UNWANTED = re.compile(r"junk( e-?mail)?|spam|trash|bin|deleted (items|messages)", re.IGNORECASE)


def available(root: Path = DEFAULT_ROOT) -> bool:
    """Whether Mail's store can be listed here: not before Mail has an account, and not while
    macOS keeps it private (no Full Disk Access)."""
    try:
        _store(root)
    except OSError:
        return False
    return True


def ingest(vault: Path, store: Path, me: Iterable[str], full: bool = False) -> dict[str, int]:
    mine = {a.strip().lower() for a in me if a.strip()}
    state_path = vault / "state" / "applemail.json"
    state = json.loads(state_path.read_text()) if state_path.exists() and not full else {}
    since = 0.0 if full else state.get("newest", time.time() - FIRST_RUN_DAYS * 86400)
    addresses = state.get("accounts", {})  # account folder → the address it is
    stats = Counter(read=0, added=0, updated=0, months_written=0, skipped=0, accounts_skipped=0)
    newest = 0.0

    for account in sorted(p for p in store.iterdir() if _ACCOUNT.fullmatch(p.name) and p.is_dir()):
        files = _changed(account, since)
        if not files:
            continue
        newest = max(newest, files[-1][0])
        address = addresses.get(account.name)
        if address not in mine:
            address = _address(files[-SAMPLE:], mine)
        if address is None:
            stats["accounts_skipped"] += 1
            continue
        addresses[account.name] = address
        stream = re.sub(r"[^\w-]", "-", address)

        out = vault / "raw" / "email" / stream
        batch = {}
        for _, path, mailbox in files:
            record = _record(path, stream, mine)
            if record is None:
                stats["skipped"] += 1
                continue
            record["gmail_labels"] = [mailbox] if mailbox else None
            batch[record["id"]] = record
            if len(batch) >= BATCH:
                stats.update(merge_monthly(batch.values(), out))
                batch = {}
        if batch:
            stats.update(merge_monthly(batch.values(), out))

    if newest:
        state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"newest": newest, "accounts": addresses}))
    return dict(stats)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--full", action="store_true", help="read every message, not what changed")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Mail's folder")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    try:
        store = _store(args.root)
    except FileNotFoundError:
        raise SystemExit(
            f"applemail: no Mail store in {args.root}. Add an account in System Settings, "
            "Internet Accounts, and open Mail."
        ) from None
    except OSError:
        raise SystemExit(
            f"applemail: macOS won't let Proxenos read Mail's folder. Give {sys.executable} "
            "Full Disk Access in System Settings, Privacy & Security, Full Disk Access."
        ) from None
    me = env("EMAILS").split(",")
    if not any(a.strip() for a in me):
        raise SystemExit(
            "applemail: set PROXENOS_EMAILS to your addresses, so each Mail account can be "
            "matched to one."
        )
    return ingest(vault, store, me, args.full)


def _store(root: Path) -> Path:
    """The highest version folder in Mail's folder (V10 ...). OSError when it can't be listed,
    FileNotFoundError when there is none."""
    versions = [p for p in root.iterdir() if _VERSION.fullmatch(p.name) and p.is_dir()]
    if not versions:
        raise FileNotFoundError(root)
    return max(versions, key=lambda p: int(p.name[1:]))


def _changed(account: Path, since: float) -> list[tuple[float, Path, str]]:
    """(mtime, path, mailbox) of each message file changed after `since`, oldest first. The
    mailbox is its path from the account, as "[Gmail]/Sent Mail". Junk and trash are left out."""
    found = []
    for path in account.rglob("*.emlx"):  # .partial.emlx ends the same way
        names = [
            part.removesuffix(".mbox")
            for part in path.relative_to(account).parts
            if part.endswith(".mbox")
        ]
        if any(_UNWANTED.fullmatch(name) for name in names):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:  # Mail moved or deleted it since the listing
            continue
        if mtime > since:
            found.append((mtime, path, "/".join(names)))
    return sorted(found)


def _address(files: list[tuple[float, Path, str]], mine: set[str]) -> str | None:
    """The address of yours that appears most in these messages' From, To and Cc."""
    seen = Counter()
    for _, path, _ in files:
        if record := _record(path, "", mine):
            found = [record["from_address"], *(record["to"] or []), *(record["cc"] or [])]
            seen.update(a for a in found if a in mine)
    return seen.most_common(1)[0][0] if seen else None


def _record(path: Path, account: str, me: set[str]) -> dict | None:
    raw = _message(path)
    if raw is None:
        return None
    try:
        # The mbox parser expects a From_ line first; this one carries no date of its own.
        return email._record(b"From applemail\n" + raw, account, me)
    except Exception:  # noqa: BLE001  one unreadable message must not stop the sync
        return None


def _message(path: Path) -> bytes | None:
    """The message in an .emlx: a byte count on the first line, then that many bytes of RFC 822
    text. A plist of flags follows, which isn't read."""
    try:
        with path.open("rb") as f:
            size = int(f.readline())
            raw = f.read(size)
    except (OSError, ValueError):
        return None
    return raw if size > 0 and len(raw) == size else None
