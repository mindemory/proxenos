"""Secrets in the macOS Keychain, one item per secret, through the `security` command.

Each is a generic password in the login keychain: service "Proxenos", account the variable's
name (ANTHROPIC_API_KEY, GMAIL_PERSONAL, ...). Only `security` itself, which made the item, can
read it without macOS asking first. A secret never goes on a command line, which any process on
the Mac can read: it's written through `security -i`, which takes its commands on stdin, and read
back from stdout.
"""

import re
import shutil
import subprocess
import sys

SERVICE = "Proxenos"
# A variable's name: what an item's account is, and what's safe on `security -i`'s command line.
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")
_NOT_FOUND = 44  # errSecItemNotFound, as `security` exits
_TIMEOUT = 30  # seconds; a locked keychain asks for the password, which takes a person


class KeychainError(RuntimeError):
    pass


def available() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def get(name: str) -> str | None:
    """The secret saved as `name`, or None when there's no such item."""
    found = _security(["find-generic-password", "-s", SERVICE, "-a", _checked(name), "-w"])
    if found.returncode == _NOT_FOUND:
        return None
    if found.returncode != 0:
        raise KeychainError(f"the Keychain didn't give {name}: {_said(found)}")
    return found.stdout.removesuffix("\n")


def put(name: str, value: str) -> None:
    """Save `value` as `name`, replacing what was there."""
    if not value or "\0" in value:
        raise KeychainError(f"nothing to save as {name}")
    # As hex, so the value needs no quoting on `security -i`'s line.
    command = (
        f"add-generic-password -U -s {SERVICE} -a {_checked(name)} -X {value.encode().hex()}\n"
    )
    added = _security(["-i"], command)
    # `security -i` exits 0 whatever its commands did, so read the item back.
    if added.returncode != 0 or get(name) != value:
        raise KeychainError(f"the Keychain didn't save {name}: {_said(added)}")


def delete(name: str) -> bool:
    """Remove the item for `name`. Whether there was one."""
    gone = _security(["delete-generic-password", "-s", SERVICE, "-a", _checked(name)])
    if gone.returncode == _NOT_FOUND:
        return False
    if gone.returncode != 0:
        raise KeychainError(f"the Keychain didn't remove {name}: {_said(gone)}")
    return True


def _checked(name: str) -> str:
    if not NAME.fullmatch(name):
        raise KeychainError(f"{name!r} isn't a variable's name")
    return name


def _said(done: subprocess.CompletedProcess) -> str:
    return " ".join((done.stderr or "").split())[:200] or f"exit {done.returncode}"


def _security(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    command = ["security", *args]
    try:
        return subprocess.run(
            command, check=False, input=stdin, capture_output=True, text=True, timeout=_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, -1, "", "it took too long")
