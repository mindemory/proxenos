"""Email from mbox exports (Google Takeout or a mail client), one stream per account.

Takeout gives one "All mail Including Spam and Trash.mbox" and mail clients give one mbox
per folder. Either can run to several GB, so messages are parsed one at a time and merged
into vault/raw/email/<account>/ in batches. Records are keyed by Message-ID, so re-running
an export, or feeding in folders that share messages, merges instead of duplicating.
"""

import argparse
import csv
import hashlib
import mailbox
import re
from collections.abc import Iterable, Iterator
from datetime import UTC
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from proxenos.config import env
from proxenos.store import merge_monthly

# Records per merge_monthly call. Each call rewrites the month files it touches, so this
# trades memory for rewrites.
BATCH = 5000

_PARSER = BytesParser(policy=policy.default)

# mbox writers turn body lines starting "From " into ">From " (mboxrd also adds a ">" to
# lines already starting ">From "). Undo it, or body_new would drop those lines as quotes.
_FROM_ESCAPE = re.compile(rb"^>(>*From )", re.MULTILINE)

# Where quoted text starts besides "On <date>, <name> wrote:". Outlook puts a
# "From: ... Sent: ..." block under replies, and forwards bring a banner.
_QUOTE_BANNER = re.compile(r"-{2,}\s*(original|forwarded) message\s*-{2,}", re.IGNORECASE)

_HIDDEN_TAGS = {"script", "style", "title"}
_BLOCK_TAGS = {"blockquote", "dd", "div", "dt", "hr", "li", "ol", "p", "pre", "table", "tr", "ul"}
_BLOCK_TAGS |= {f"h{n}" for n in range(1, 7)}


def read_messages(mbox: Path, account: str, me: Iterable[str] = ()) -> Iterator[dict | None]:
    """Records in file order, one message in memory at a time. None marks a skipped one."""
    mine = {address.strip().lower() for address in me if address.strip()}
    box = mailbox.mbox(mbox, create=False)
    try:
        for key in box.iterkeys():
            raw = box.get_bytes(key, from_=True)
            try:
                record = _record(raw, account, mine)
            except Exception:  # noqa: BLE001  malformed past what the parser tolerates
                record = None
            yield record
    finally:
        box.close()


def ingest(
    vault: Path, mbox: Path, account: str, me: Iterable[str] = (), batch_size: int = BATCH
) -> dict[str, int]:
    if not re.fullmatch(r"[\w-]+", account):
        raise ValueError(f"account {account!r} names a directory: use letters, digits, _ or -")
    out = vault / "raw" / "email" / account
    stats = {"read": 0, "added": 0, "updated": 0, "months_written": 0, "skipped": 0}
    # Keyed by id: exports repeat a Message-ID now and then, and the last copy wins.
    batch: dict[str, dict] = {}
    for record in read_messages(mbox, account, me):
        if record is None:
            stats["skipped"] += 1
            continue
        batch[record["id"]] = record
        if len(batch) >= batch_size:
            _merge(batch.values(), out, stats)
            batch = {}
    if batch:
        _merge(batch.values(), out, stats)
    return stats


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", required=True, help="stream name, e.g. gmail or work")
    parser.add_argument("--mbox", type=Path, required=True)
    parser.add_argument(
        "--me",
        action="append",
        default=[],
        metavar="ADDRESS",
        help="an address of mine, marks from_me (repeatable; default: $PROXENOS_EMAILS)",
    )


def run(vault: Path, args: argparse.Namespace) -> dict[str, int]:
    me = args.me or env("EMAILS").split(",")
    return ingest(vault, args.mbox, args.account, me)


def _merge(batch: Iterable[dict], out: Path, stats: dict[str, int]) -> None:
    for key, value in merge_monthly(batch, out).items():
        stats[key] += value


def _record(raw: bytes, account: str, me: set[str]) -> dict | None:
    from_line, _, content = raw.partition(b"\n")
    msg = _PARSER.parsebytes(_FROM_ESCAPE.sub(rb"\1", content))
    ts = _timestamp(msg, from_line)
    if ts is None:
        return None

    from_name, from_address = next(iter(_addresses(msg, "From")), (None, None))
    subject = _header(msg, "Subject")
    body = _body(msg)
    message_id = _message_id(_raw(msg, "Message-ID"))
    if message_id is None:
        key = "\n".join([ts, _raw(msg, "From") or "", subject or "", (body or "")[:200]])
        message_id = hashlib.sha256(key.encode()).hexdigest()

    return {
        "id": message_id,
        "ts": ts,
        "account": account,
        "from_address": from_address,
        "from_name": from_name,
        "from_me": from_address in me,
        "to": [address for _, address in _addresses(msg, "To") if address] or None,
        "cc": [address for _, address in _addresses(msg, "Cc") if address] or None,
        "subject": subject,
        "in_reply_to": _message_id(_raw(msg, "In-Reply-To")),
        "gmail_labels": _labels(_header(msg, "X-Gmail-Labels")),
        "gmail_thread": _header(msg, "X-GM-THRID"),
        "attachments": [n for part in msg.walk() if (n := _text(part.get_filename()))] or None,
        "body": body,
        "body_new": _new_text(body) if body else None,
    }


def _timestamp(msg: EmailMessage, from_line: bytes) -> str | None:
    """The Date header in UTC, else the date on the mbox From_ line (when it was delivered)."""
    # The From_ line is "From <sender> <date>"; Takeout writes "Wed Mar 12 18:23:45 +0000 2025".
    from_line_date = from_line.decode("ascii", "replace").strip().split(None, 2)[2:]
    for text in [_raw(msg, "Date"), *from_line_date]:
        if not text:
            continue
        try:
            when = parsedate_to_datetime(text)
            if when.tzinfo is None:  # "-0000", or a From_ line with no zone: both mean UTC
                when = when.replace(tzinfo=UTC)
            return when.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (ValueError, OverflowError):
            continue
    return None


def _text(value: object) -> str | None:
    """Stripped text that is safe to write as UTF-8, or None when empty.

    The parser keeps header bytes it couldn't decode as lone surrogates. Raw UTF-8 comes
    back intact and anything else becomes U+FFFD.
    """
    if value is None:
        return None
    text = str(value)
    try:
        text = text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeEncodeError:  # surrogates that didn't come from bytes
        text = text.encode("utf-8", "replace").decode("utf-8")
    return text.strip() or None


def _raw(msg: EmailMessage, name: str) -> str | None:
    """A header as written in the file, unfolded. Ids come from this so they stay stable."""
    for key, value in msg.raw_items():
        if key.lower() == name.lower():
            return _text(" ".join(str(value).split()))
    return None


def _header(msg: EmailMessage, name: str) -> str | None:
    """A header decoded, RFC 2047 included, or its raw value if it won't parse."""
    try:
        return _text(msg[name])
    except Exception:  # noqa: BLE001  the stdlib's header parsers have edge cases that raise
        return _raw(msg, name)


def _addresses(msg: EmailMessage, name: str) -> list[tuple[str | None, str | None]]:
    """(display name, lowercased address) for every address in every copy of a header."""
    try:
        found = [(a.display_name, a.addr_spec) for h in msg.get_all(name, []) for a in h.addresses]
    except Exception:  # noqa: BLE001  a list the strict parser rejects: use the lenient one
        found = getaddresses([str(v) for k, v in msg.raw_items() if k.lower() == name.lower()])
    pairs = []
    for display_name, address in found:
        address = _text(address)
        if address == "<>":  # what the parser makes of a name with no address
            address = None
        pairs.append((_text(display_name), address.lower() if address else None))
    return pairs


def _message_id(value: str | None) -> str | None:
    """'<abc@example.com>' becomes 'abc@example.com'. In-Reply-To may list several: first wins."""
    if not value:
        return None
    match = re.search(r"<([^<>]+)>", value)
    token = match.group(1) if match else value
    return "".join(token.split()).strip("<>") or None


def _labels(value: str | None) -> list[str] | None:
    """Takeout's X-Gmail-Labels, e.g. 'Inbox,Opened,"Trips, 2024"'. Quotes protect commas."""
    if not value:
        return None
    labels = next(csv.reader([value], skipinitialspace=True), [])
    return [label.strip() for label in labels if label.strip()] or None


def _body(msg: EmailMessage) -> str | None:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return None
    text = _decode(part)
    if part.get_content_subtype() == "html":
        text = _html_text(text)
    return _text(text.replace("\r\n", "\n").replace("\r", "\n"))


def _decode(part: EmailMessage) -> str:
    """A text part's content, surviving unknown and mislabeled charsets."""
    payload = part.get_payload(decode=True) or b""
    for charset in (part.get_content_charset() or "utf-8", "utf-8"):
        try:
            return payload.decode(charset)
        except (LookupError, ValueError):
            continue
    return payload.decode("utf-8", "replace")


class _HTMLText(HTMLParser):
    """The visible text of an HTML body, with a line break wherever a block ends."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._hidden = 0
        self._line_is_empty = True

    def _newline(self, force: bool = False) -> None:
        if force or not self._line_is_empty:
            self.chunks.append("\n")
            self._line_is_empty = True

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden += 1
        elif tag == "br":
            self._newline(force=True)
        elif tag in _BLOCK_TAGS:
            self._newline()

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)  # <br/> is one break, not a start and an end

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.chunks.append(re.sub(r"\s+", " ", data))  # source line breaks are spaces
            self._line_is_empty = self._line_is_empty and not data.strip()


def _html_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    text = "\n".join(" ".join(line.split()) for line in "".join(parser.chunks).split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text)


def _new_text(body: str) -> str | None:
    """The body minus quoted lines and everything from the reply attribution on."""
    lines = body.split("\n")
    kept = []
    for i, line in enumerate(lines):
        if _quote_starts(lines, i):
            break
        if not line.lstrip().startswith(">"):
            kept.append(line)
    while kept and not kept[-1].strip(" _-"):  # blank lines and Outlook's ____ separator
        kept.pop()
    return _text("\n".join(kept))


def _quote_starts(lines: list[str], i: int) -> bool:
    line = lines[i].strip()
    if line.startswith("On "):
        # Clients wrap "On <date>, <name> <address> wrote:" onto a second or third line.
        for following in lines[i : i + 3]:
            if following.rstrip().endswith("wrote:"):
                return True
            if not following.strip():
                break
        return False
    if _QUOTE_BANNER.fullmatch(line):
        return True
    following = lines[i + 1].strip() if i + 1 < len(lines) else ""
    return line.startswith("From:") and following.startswith(("Sent:", "Date:"))
