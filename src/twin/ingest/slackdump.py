"""Slack workspaces from slackdump archives, with no token or app needed.

slackdump (github.com/rusq/slackdump) saves one SQLite archive per run in a
slackdump_<date>_<time>/ folder: Slack's own API JSON for the workspace, its users, channels
and messages. Records are built with the API ingester's code, so they land in
vault/raw/slack/<team>/messages/ field for field the same and merge with it by id. Every
archive under --root is read on each run; a message saved by several chunks keeps its latest
copy. Archives still being written are read as they stand.
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from twin.ingest import slack
from twin.store import merge_monthly

DEFAULT_ROOT = Path("~/Documents/Personal").expanduser()


def archives(root: Path = DEFAULT_ROOT) -> list[Path]:
    """Every slackdump run under root, plus any dropped into the repo's data/ folder."""
    from twin.config import REPO_ROOT

    found = set(root.glob("slackdump_*/slackdump.sqlite"))
    if root == DEFAULT_ROOT:
        found |= set((REPO_ROOT / "data").glob("slackdump_*/slackdump.sqlite"))
    return sorted(found)


def read_archive(db: Path) -> tuple[str | None, list[dict]]:
    """(team slug, records) from one archive; (None, []) for one without a workspace yet."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        workspace = con.execute(
            "select TEAM, TEAM_ID, USER_ID from WORKSPACE order by LOAD_DTTM desc limit 1"
        ).fetchone()
        if workspace is None:
            return None, []
        team, team_id, me = workspace
        users = {
            uid: slack._user_name(json.loads(data))
            for uid, data in con.execute("select ID, DATA from S_USER order by LOAD_DTTM")
        }
        channels = {
            cid: slack._channel(json.loads(data), users)
            for cid, data in con.execute("select ID, DATA from CHANNEL order by LOAD_DTTM")
        }
        # Later loads of the same message replace earlier ones (edits, new reply counts).
        latest = {
            (cid, ts): data
            for cid, ts, data in con.execute(
                "select CHANNEL_ID, TS, DATA from MESSAGE order by LOAD_DTTM"
            )
        }
    finally:
        con.close()

    records = []
    for (cid, _), data in latest.items():
        channel = channels.get(cid) or {"id": cid, "name": None, "type": "channel"}
        records.append(slack._record(json.loads(data), channel, users, me))
    return slack._slug(team or "") or str(team_id).lower(), records


def ingest(vault: Path, root: Path = DEFAULT_ROOT) -> dict[str, int]:
    stats = Counter()
    for db in archives(root):
        team, records = read_archive(db)
        if team is None:
            continue
        stats.update(merge_monthly(records, vault / "raw" / "slack" / team / "messages"))
        stats["archives"] += 1
    return dict(stats)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="folder holding slackdump_* runs"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.root)
