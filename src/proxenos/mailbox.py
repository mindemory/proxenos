"""Which of the user's own mailboxes an email thread is on, so a reply goes out from it.

A user can have several: a Microsoft 365 or Outlook account, a Google Workspace one, a personal
Gmail. A draft that only names its recipient leaves them to work out which one the thread is in,
and a reply opened in the wrong one starts a new conversation with the wrong address. So a reply
draft records `from_account` (the raw/email stream the thread is in), `from_address` (the user's
own address on it) and `from_provider` (gmail, google-workspace or outlook), and an errand's or
an offer's email records the same for what it will go from.

The address is the user's own one in the To or Cc of the thread's latest inbound mail, else the
From of their latest outbound one. The provider is the account's ingester when it's signed in
(GMAIL_<NAME> or MICROSOFT_<NAME>), else what the records show: Outlook's message ids end in
outlook.com, a Gmail thread id is all digits, and the address's domain says the rest. When none
of that settles it the provider is left out, and the page offers only the Mail app.
"""

import re
from pathlib import Path

from proxenos.config import env
from proxenos.ingest import gmail, microsoft

PROVIDERS = ("gmail", "google-workspace", "outlook")
_OUTLOOK = {"outlook.com", "hotmail.com", "live.com", "msn.com"}
_GMAIL = {"gmail.com", "googlemail.com"}


def me() -> set[str]:
    """The user's own addresses, PROXENOS_EMAILS, lower-cased."""
    return {a.strip().lower() for a in env("EMAILS").split(",") if a.strip()}


def of(messages: list[dict], mine: set[str] | None = None) -> dict | None:
    """The mailbox a thread is on, {account, address, provider}, from its messages as
    chats._email reads them (each with `mail`: its account, From, To and Cc, Gmail thread), or
    None when none of them is mail. The address is "" when the thread names none of the user's."""
    mine = me() if mine is None else mine
    mails = sorted((m for m in messages if m.get("mail")), key=lambda m: m["ts"])
    if not mails:
        return None
    address, chosen = "", mails[-1]
    inbound = [m for m in mails if not m["mine"] and mine & set(m["mail"]["to"])]
    outbound = [m for m in mails if m["mine"] and m["mail"]["from"]]
    if inbound:
        chosen = inbound[-1]
        address = next(a for a in chosen["mail"]["to"] if a in mine)
    elif outbound:
        chosen = outbound[-1]
        address = chosen["mail"]["from"]
    account = chosen["mail"]["account"]
    ids = [m["id"] for m in mails if m["mail"]["account"] == account]
    return {
        "account": account,
        "address": address,
        "provider": provider(account, address, ids, chosen["mail"].get("thread")),
    }


def provider(account: str, address: str, ids: list[str] = (), thread: object = None) -> str:
    """gmail, google-workspace or outlook for an account, or "" when nothing says. A signed-in
    account's ingester says first; then the message ids and the address's domain."""
    domain = address.rpartition("@")[2].lower()
    google = "gmail" if domain in _GMAIL or not domain else "google-workspace"
    if account.lower() in microsoft.accounts():
        return "outlook"
    if account.lower() in gmail.accounts():
        return google
    if any(i.strip("<>").lower().endswith("outlook.com") for i in ids) or domain in _OUTLOOK:
        return "outlook"
    if domain in _GMAIL:
        return "gmail"
    if re.fullmatch(r"\d+", str(thread or "")):  # Gmail's X-GM-THRID; Outlook's is not digits
        return google
    return ""


def toward(vault: Path, address: str) -> dict | None:
    """The mailbox the user's newest email with `address` was on, {account, address, provider},
    for a message to start with them: an errand's or an offer's reply. None when there's none."""
    from proxenos import chats  # chats reads a thread's mailbox from here, so not at the top

    address = address.strip().lower()
    if not address:
        return None
    mine = me()
    months = sorted({p.name for p in (vault / "raw" / "email").glob("*/*.jsonl")})
    found = []
    for path in sorted((vault / "raw" / "email").glob("*/*.jsonl")):
        if path.name not in months[-chats.EMAIL_MONTHS :]:
            continue
        for r in chats._records([path]):
            message = chats._email(r, mine)
            if message and address in message["peers"] and isinstance(r.get("ts"), str):
                found.append(message)
    return of([max(found, key=lambda m: m["ts"])], mine) if found else None
