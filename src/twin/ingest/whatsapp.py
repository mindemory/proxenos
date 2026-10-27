"""WhatsApp messages from the Mac app's local store.

Reads ChatStorage.sqlite and writes monthly JSONL into the vault. The Mac app keeps messages in a Core Data SQLite store. One query reads everything in a
single read transaction, so WhatsApp can keep writing while this runs. Every run re-reads
the whole store and merges by id, which makes backfill and the nightly sync the same
operation and also picks up history that syncs late from the phone, and deletions.
"""

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from twin.store import merge_monthly

DEFAULT_DB = Path(
    "~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
).expanduser()

# Core Data stores dates as seconds since 2001-01-01 UTC.
_CORE_DATA_EPOCH = 978307200

# ZMESSAGETYPE values whose meaning is well established. The rest become "other", and the
# raw number is always kept in wa_type.
_KINDS = {
    0: "text",
    1: "image",
    2: "video",
    3: "audio",
    4: "contact",
    5: "location",
    6: "system",
    7: "link",
    8: "document",
    14: "deleted",
    15: "sticker",
}
# Media whose ZWAMEDIAITEM.ZTITLE is the sender's caption. For links it's the preview title.
_CAPTIONED = {1, 2, 8}
_DELETED = 14
_CHAT_TYPES = {0: "direct", 1: "group"}

_QUERY = """
select m.ZSTANZAID as stanza, m.ZMESSAGEDATE as date, m.ZISFROMME as from_me,
       m.ZMESSAGETYPE as wa_type, m.ZTEXT as text,
       s.ZCONTACTJID as chat_id, s.ZPARTNERNAME as chat_name, s.ZSESSIONTYPE as session_type,
       g.ZMEMBERJID as member_id,
       coalesce(nullif(g.ZCONTACTNAME, ''), nullif(g.ZFIRSTNAME, ''),
                (select p.ZPUSHNAME from ZWAPROFILEPUSHNAME p where p.ZJID = g.ZMEMBERJID limit 1)
       ) as member_name,
       mi.ZTITLE as title
from ZWAMESSAGE m
join ZWACHATSESSION s on s.Z_PK = m.ZCHATSESSION
left join ZWAGROUPMEMBER g on g.Z_PK = m.ZGROUPMEMBER
left join ZWAMEDIAITEM mi on mi.Z_PK = m.ZMEDIAITEM
where m.ZSTANZAID is not null and m.ZMESSAGEDATE is not null
"""


def read_messages(db: Path = DEFAULT_DB) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [_record(row) for row in con.execute(_QUERY)]
    finally:
        con.close()


def ingest(vault: Path, db: Path = DEFAULT_DB) -> dict[str, int]:
    return merge_monthly(read_messages(db), vault / "raw" / "whatsapp" / "messages")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    return ingest(vault, args.db)


def _record(row: sqlite3.Row) -> dict:
    from_me = bool(row["from_me"])
    if from_me:
        sender_id = sender_name = None
    elif row["session_type"] == 1:
        sender_id, sender_name = row["member_id"], row["member_name"]
    else:
        sender_id, sender_name = row["chat_id"], row["chat_name"]

    text = row["text"]
    caption = row["title"] if row["wa_type"] in _CAPTIONED else None
    if row["wa_type"] == _DELETED:
        text = caption = None

    ts = datetime.fromtimestamp(row["date"] + _CORE_DATA_EPOCH, UTC)
    return {
        "id": f"{row['chat_id']}/{row['stanza']}",
        "ts": ts.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "chat_id": row["chat_id"],
        "chat_name": row["chat_name"] or None,
        "chat_type": _CHAT_TYPES.get(row["session_type"], "other"),
        "from_me": from_me,
        "sender_id": sender_id,
        "sender_name": sender_name or None,
        "kind": _KINDS.get(row["wa_type"], "other"),
        "wa_type": row["wa_type"],
        "text": text or None,
        "caption": caption or None,
    }
