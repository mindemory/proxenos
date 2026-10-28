"""Slack workspaces from slackdump archives, with no token or app needed.

slackdump (github.com/rusq/slackdump) saves one SQLite archive per run in a
slackdump_<date>_<time>/ folder: Slack's own API JSON for the workspace, its users, channels
and messages. Records are built with the API ingester's code, so they land in
vault/raw/slack/<team>/messages/ field for field the same and merge with it by id. Every
archive under --root is read on each run, oldest first; a message saved by several chunks keeps
its latest copy. Archives still being written are read as they stand.

Who is in each channel (its CHANNEL_USER table) goes to raw/slack/<team>/channels/snapshot.jsonl,
one record per channel or group DM, as the API ingester writes it: every member's user id, name
and profile email, and whether I'm in it.
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from twin.ingest import slack
from twin.store import merge_monthly, merge_snapshot

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
    team, records, _ = read_all(db)
    return team, records


def read_all(db: Path) -> tuple[str | None, list[dict], list[dict]]:
    """(team slug, message records, channel member records) from one archive."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        workspace = con.execute(
            "select TEAM, TEAM_ID, USER_ID from WORKSPACE order by LOAD_DTTM desc limit 1"
        ).fetchone()
        if workspace is None:
            return None, [], []
        team, team_id, me = workspace
        profiles = {
            uid: json.loads(data)
            for uid, data in con.execute("select ID, DATA from S_USER order by LOAD_DTTM")
        }
        users = {uid: slack._user_name(user) for uid, user in profiles.items()}
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
        try:
            members = con.execute(
                "select CHANNEL_ID, USER_ID from CHANNEL_USER order by CHANNEL_ID, IDX"
            ).fetchall()
        except sqlite3.OperationalError:
            members = []  # an archive from before slackdump kept members
    finally:
        con.close()

    records = []
    for (cid, _), data in latest.items():
        channel = channels.get(cid) or {"id": cid, "name": None, "type": "channel"}
        records.append(slack._record(json.loads(data), channel, users, me))
    by_channel: dict[str, list[str]] = {}
    for cid, uid in members:
        if uid not in by_channel.setdefault(cid, []):
            by_channel[cid].append(uid)
    emails = {uid: slack._email(user) for uid, user in profiles.items()}
    unknown = {"name": None, "type": "channel"}
    rosters = [
        slack.roster(channels.get(cid) or {"id": cid} | unknown, uids, users, emails, me)
        for cid, uids in sorted(by_channel.items())
    ]
    team_slug = slack._slug(team or "") or str(team_id).lower()
    return team_slug, records, [r for r in rosters if r is not None]


def ingest(vault: Path, root: Path = DEFAULT_ROOT) -> dict[str, int]:
    stats = Counter()
    rosters: dict[str, dict[str, dict]] = {}
    # Oldest run first, wherever it lives, so a later copy of a message or roster wins.
    for db in sorted(archives(root), key=lambda p: (p.parent.name, str(p))):
        team, records, channels = read_all(db)
        if team is None:
            continue
        stats.update(merge_monthly(records, vault / "raw" / "slack" / team / "messages"))
        rosters.setdefault(team, {}).update((c["id"], c) for c in channels)
        stats["archives"] += 1
    for team, channels in rosters.items():
        stats["channels"] += merge_snapshot(
            channels.values(), vault / "raw" / "slack" / team / "channels"
        )
    return dict(stats)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="folder holding slackdump_* runs"
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.root)
