"""Gmail over IMAP with an app password, every account listed in .env.

Each account is one line in .env, `GMAIL_<NAME>=address:app-password`; NAME (lowercased)
names the stream, vault/raw/email/<name>/, which matches the mbox ingester's records field
for field (same parser), so a Takeout import and this sync merge by Message-ID. App
passwords come from myaccount.google.com/apppasswords and need 2-Step Verification.

Reads "All Mail" (Gmail's every-message folder, without spam and trash) read-only. The first
run backfills everything; later runs fetch only UIDs above the last one seen, kept in
vault/state/gmail_<name>.json. Only the first 256 KB of each message is fetched, which holds
the text of nearly all mail and skips most attachment bytes.
"""

import argparse
import contextlib
import imaplib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

from twin.ingest import email
from twin.store import merge_monthly

HOST = "imap.gmail.com"
FETCH_BYTES = 256 * 1024
CHUNK = 100  # UIDs per FETCH
BATCH = 2000  # records per merge

_ENV = re.compile(r"GMAIL_([A-Z0-9_]+)")
_ALL_MAIL = re.compile(rb'\\All\)?.*"(?P<name>[^"]+)"\s*$')
_UID = re.compile(rb"UID (\d+)")
_THREAD = re.compile(rb"X-GM-THRID (\d+)")
_LABELS = re.compile(rb"X-GM-LABELS \(([^)]*)\)")
_LABEL = re.compile(rb'"(?:[^"\\]|\\.)*"|[^\s"]+')


def accounts() -> dict[str, tuple[str, str]]:
    """name → (address, app password) for every GMAIL_<NAME> variable in the environment."""
    found = {}
    for key, value in os.environ.items():
        match = _ENV.fullmatch(key)
        if match and ":" in value:
            address, password = value.split(":", 1)
            found[match.group(1).lower()] = (address.strip(), password.strip())
    return found


def ingest(
    vault: Path,
    name: str,
    address: str,
    password: str,
    me=(),
    full: bool = False,
    connect: Callable[[], imaplib.IMAP4] = lambda: imaplib.IMAP4_SSL(HOST),
) -> dict[str, int]:
    mine = {a.strip().lower() for a in [address, *me] if a.strip()}
    state_path = vault / "state" / f"gmail_{name}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() and not full else {}
    stats = Counter()
    conn = connect()
    try:
        try:
            conn.login(address, password)
        except imaplib.IMAP4.error:
            raise SystemExit(
                f"gmail: {name} refused the login. Check the app password in .env "
                "(myaccount.google.com/apppasswords) and that IMAP is on in Gmail settings."
            ) from None
        conn.select(_all_mail(conn), readonly=True)
        validity = int(conn.response("UIDVALIDITY")[1][0])
        last = state.get("last_uid", 0) if state.get("uidvalidity") == validity else 0

        _, found = conn.uid("SEARCH", None, f"UID {last + 1}:*")
        uids = [int(u) for u in found[0].split() if int(u) > last]
        batch = {}
        for record, uid in _fetch(conn, uids, name, mine):
            last = max(last, uid)
            if record is None:
                stats["skipped"] += 1
                continue
            batch[record["id"]] = record
            if len(batch) >= BATCH:
                stats.update(merge_monthly(batch.values(), vault / "raw" / "email" / name))
                batch = {}
                _save(state_path, validity, last)
        stats.update(merge_monthly(batch.values(), vault / "raw" / "email" / name))
        _save(state_path, validity, last)
    finally:
        # Logging out after a failed login can raise too, and there is nothing left to do.
        with contextlib.suppress(Exception):
            conn.logout()
    return dict(stats)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="only this GMAIL_<NAME> account (default: all)")
    parser.add_argument("--full", action="store_true", help="refetch everything")


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    found = accounts()
    if args.account:
        found = {k: v for k, v in found.items() if k == args.account.lower()}
    if not found:
        raise SystemExit("gmail: no accounts. Add GMAIL_<NAME>=address:app-password to .env.")
    me = os.environ.get("TWIN_EMAILS", "").split(",")
    total = Counter()
    for name, (address, password) in found.items():
        total.update(ingest(vault, name, address, password, me, args.full))
    return dict(total)


def _all_mail(conn: imaplib.IMAP4) -> str:
    """The folder flagged \\All; its name is localized ("[Gmail]/Alle Nachrichten" ...)."""
    _, boxes = conn.list()
    for line in boxes:
        match = _ALL_MAIL.search(line or b"")
        if match:
            return '"' + match.group("name").decode() + '"'
    return '"[Gmail]/All Mail"'


def _fetch(conn: imaplib.IMAP4, uids: list[int], name: str, me: set[str]) -> Iterator:
    query = f"(UID X-GM-THRID X-GM-LABELS BODY.PEEK[]<0.{FETCH_BYTES}>)"
    for start in range(0, len(uids), CHUNK):
        chunk = ",".join(str(u) for u in uids[start : start + CHUNK])
        _, data = conn.uid("FETCH", chunk, query)
        for part in data:
            if not isinstance(part, tuple):
                continue
            meta, raw = part
            uid = int(_UID.search(meta).group(1))
            yield _record(meta, raw, name, me), uid


def _record(meta: bytes, raw: bytes, name: str, me: set[str]) -> dict | None:
    try:
        # The mbox parser expects a From_ line first; this one carries no date of its own.
        record = email._record(b"From gmail\n" + raw, name, me)
    except Exception:  # noqa: BLE001  one unreadable message must not stop the sync
        return None
    if record is None:
        return None
    thread = _THREAD.search(meta)
    labels = _LABELS.search(meta)
    record["gmail_thread"] = thread.group(1).decode() if thread else record["gmail_thread"]
    if labels:
        found = [
            label.decode("utf-8", "replace").strip('"').replace("\\\\", "\\")
            for label in _LABEL.findall(labels.group(1))
        ]
        record["gmail_labels"] = found or None
    return record


def _save(path: Path, validity: int, last: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({"uidvalidity": validity, "last_uid": last}))
