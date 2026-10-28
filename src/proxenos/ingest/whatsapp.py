"""WhatsApp messages and group members from the Mac app's local store.

Reads ChatStorage.sqlite and writes monthly JSONL into the vault. The Mac app keeps messages in a
Core Data SQLite store. One query reads everything in a single read transaction, so WhatsApp can
keep writing while this runs. Every run re-reads the whole store and merges by id, which makes
backfill and the nightly sync the same operation and also picks up history that syncs late from
the phone, and deletions.

Who is in each group goes to raw/whatsapp/groups/snapshot.jsonl, one record per group, refreshed
every run: the group's chat id and name, and each member's jid, name and whether they're still in
it. That's everyone in the group, not only those who wrote.

Names. A group member is named as the address book has them (ContactsV2.sqlite, next to the
store), else by the contact name the store keeps, else by the push name they chose. The store's
ZFIRSTNAME holds an encoded blob ("+AbCd...="), never a name, so it's skipped. WhatsApp knows a
person by two jids, a phone one (...@s.whatsapp.net) and a private one (...@lid); the address book
links the two where it can, and a member's other jid is kept as alt_jid.
"""

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from proxenos.store import merge_monthly, merge_snapshot

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
_PHONE = "@s.whatsapp.net"

_PUSH_NAME = "(select p.ZPUSHNAME from ZWAPROFILEPUSHNAME p where p.ZJID = g.ZMEMBERJID limit 1)"

_QUERY = f"""
select m.ZSTANZAID as stanza, m.ZMESSAGEDATE as date, m.ZISFROMME as from_me,
       m.ZMESSAGETYPE as wa_type, m.ZTEXT as text,
       s.ZCONTACTJID as chat_id, s.ZPARTNERNAME as chat_name, s.ZSESSIONTYPE as session_type,
       g.ZMEMBERJID as member_id, g.ZCONTACTNAME as contact_name, g.ZFIRSTNAME as first_name,
       {_PUSH_NAME} as push_name,
       mi.ZTITLE as title
from ZWAMESSAGE m
join ZWACHATSESSION s on s.Z_PK = m.ZCHATSESSION
left join ZWAGROUPMEMBER g on g.Z_PK = m.ZGROUPMEMBER
left join ZWAMEDIAITEM mi on mi.Z_PK = m.ZMEDIAITEM
where m.ZSTANZAID is not null and m.ZMESSAGEDATE is not null
"""

_MEMBERS = f"""
select s.ZCONTACTJID as chat_id, s.ZPARTNERNAME as chat_name,
       g.ZMEMBERJID as jid, g.ZISACTIVE as active, g.ZCONTACTNAME as contact_name,
       g.ZFIRSTNAME as first_name, {_PUSH_NAME} as push_name
from ZWAGROUPMEMBER g
join ZWACHATSESSION s on s.Z_PK = g.ZCHATSESSION
where s.ZSESSIONTYPE = 1 and s.ZCONTACTJID is not null and g.ZMEMBERJID is not null
order by s.ZCONTACTJID, g.Z_PK
"""


def read_messages(db: Path = DEFAULT_DB) -> list[dict]:
    book = _address_book(db.parent)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [_record(row, book) for row in con.execute(_QUERY)]
    finally:
        con.close()


def read_groups(db: Path = DEFAULT_DB) -> list[dict]:
    """One record per group: its chat id and name, and every member, active or not."""
    book = _address_book(db.parent)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(_MEMBERS).fetchall()
    finally:
        con.close()
    groups: dict[str, dict] = {}
    for row in rows:
        group = groups.setdefault(
            row["chat_id"],
            {
                "id": row["chat_id"],
                "chat_id": row["chat_id"],
                "chat_name": row["chat_name"] or None,
                "members": {},
            },
        )
        jid = row["jid"]
        member = group["members"].get(jid)
        active = bool(row["active"])
        if member is not None:
            member["active"] = member["active"] or active  # left and joined again
            continue
        push = _name(row["push_name"])
        group["members"][jid] = {
            "jid": jid,
            "alt_jid": book["other"].get(jid),
            "name": _member_name(row, book),
            "push_name": push,
            "active": active,
        }
    for group in groups.values():
        group["members"] = list(group["members"].values())
    return list(groups.values())


def ingest(vault: Path, db: Path = DEFAULT_DB) -> dict[str, int]:
    stats = merge_monthly(read_messages(db), vault / "raw" / "whatsapp" / "messages")
    stats["groups"] = merge_snapshot(read_groups(db), vault / "raw" / "whatsapp" / "groups")
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)


def store_problem(db: Path = DEFAULT_DB) -> str | None:
    """Why the store can't be read: "missing" (no WhatsApp for Mac signed in here) or "blocked"
    (macOS wants Full Disk Access for whatever runs Proxenos). None when it can be read."""
    try:
        with db.open("rb") as f:
            f.read(1)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "blocked"
    return None


_PROBLEMS = {
    "missing": "no store at {db}. Install WhatsApp for Mac and sign in, or pass --db.",
    "blocked": "macOS won't let Proxenos read the store. Give the app that runs it Full Disk "
    "Access (System Settings, Privacy & Security), then try again.",
}


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    problem = store_problem(args.db)
    if problem:
        raise SystemExit("whatsapp: " + _PROBLEMS[problem].format(db=args.db))
    return ingest(vault, args.db)


def _record(row: sqlite3.Row, book: dict) -> dict:
    from_me = bool(row["from_me"])
    if from_me:
        sender_id = sender_name = None
    elif row["session_type"] == 1:
        sender_id, sender_name = row["member_id"], _member_name(row, book, "member_id")
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


def _member_name(row: sqlite3.Row, book: dict, jid_field: str = "jid") -> str | None:
    """The address book's name for a group member, else the store's contact name, its first
    name when it is one, or their push name."""
    jid = row[jid_field]
    return (
        book["names"].get(jid)
        or _name(row["contact_name"])
        or _name(row["first_name"])
        or _name(row["push_name"])
    )


def _name(value: str | None) -> str | None:
    """A name as the store has it, or None for an empty one or an encoded blob ("+AbCd...=");
    a name never starts with "+"."""
    value = (value or "").strip()
    return value if value and not value.startswith("+") else None


def _address_book(folder: Path) -> dict[str, dict[str, str]]:
    """From ContactsV2.sqlite and LID.sqlite next to the store, when they're there: the
    address book's name for each jid, and each jid's other jid (phone ↔ lid)."""
    names: dict[str, str] = {}
    other: dict[str, str] = {}

    def pair(lid: str | None, phone: str | None) -> None:
        if lid and phone:
            phone = phone if "@" in phone else f"{phone}{_PHONE}"
            other.setdefault(lid, phone)
            other.setdefault(phone, lid)

    contacts = _read_optional(
        folder / "ContactsV2.sqlite",
        "select ZFULLNAME, ZWHATSAPPID, ZLID from ZWAADDRESSBOOKCONTACT",
    )
    for full_name, phone, lid in contacts:
        for jid in (phone, lid):
            if jid and (name := _name(full_name)):
                names.setdefault(jid, name)
        pair(lid, phone)
    for lid, phone in _read_optional(
        folder / "LID.sqlite", "select ZLID, ZPHONENUMBER from ZWAPHONENUMBERLIDPAIR"
    ):
        pair(lid, phone)
    return {"names": names, "other": other}


def _read_optional(path: Path, query: str) -> list[tuple]:
    if not path.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return con.execute(query).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []  # another version's layout: names and links are a bonus, not required
