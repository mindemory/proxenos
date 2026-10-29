"""Secrets in this computer's own secure store, one item per secret: the macOS Keychain, Windows
Credential Manager, or the Secret Service on Linux.

Each item is service "Proxenos", account the variable's name (ANTHROPIC_API_KEY, GMAIL_PERSONAL,
...), on every platform.

On a Mac it's a generic password in the login keychain, through the `security` command and only
that: macOS lets the program that made an item read it without asking, and `security` made every
item Proxenos has saved, so anything else (a library calling the Keychain itself) would be asked
about each one. A secret never goes on a command line, which any process on the Mac can read: it's
written through `security -i`, which takes its commands on stdin, and read back from stdout.

On Windows and Linux it goes through the `keyring` library, to a backend named here rather than
keyring's own pick, which could be a file of plain text: Windows Credential Manager (keyring is a
dependency there), and on Linux the Secret Service, which GNOME Keyring and KDE Wallet provide,
when keyring is installed and one of them is running. Without one, `available()` is False, as on
a Mac without `security`, and secrets go to .env from source.
"""

import importlib
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable

SERVICE = "Proxenos"
# A variable's name: what an item's account is, and what's safe on `security -i`'s command line.
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")
_NOT_FOUND = 44  # errSecItemNotFound, as `security` exits
_TIMEOUT = 30  # seconds; a locked keychain asks for the password, which takes a person
# keyring's backend for each platform's store, as (module, class); any other platform's is the
# Secret Service.
_BACKENDS = {"win32": ("keyring.backends.Windows", "WinVaultKeyring")}
_SECRET_SERVICE = ("keyring.backends.SecretService", "Keyring")


class KeychainError(RuntimeError):
    pass


def store() -> str:
    """This computer's secure store, as messages name it after "the"."""
    if sys.platform == "darwin":
        return "Keychain"
    return "Credential Manager" if sys.platform == "win32" else "Secret Service"


def available() -> bool:
    """Whether secrets can be kept here: on a Mac, whether there's `security`; elsewhere, whether
    keyring is installed and its store answers."""
    if sys.platform == "darwin":
        return shutil.which("security") is not None
    return _keyring() is not None


def get(name: str) -> str | None:
    """The secret saved as `name`, or None when there's no such item."""
    if sys.platform != "darwin":
        return _in_store("give", _checked(name), lambda kept: kept.get_password(SERVICE, name))
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
    if sys.platform != "darwin":
        _in_store(
            "save", _checked(name), lambda kept: kept.set_password(SERVICE, name, value), value
        )
        # Read back, as on a Mac, so a store that drops what it's given is caught here.
        if get(name) != value:
            raise KeychainError(f"the {store()} didn't save {name}: it gave back something else")
        return
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
    if sys.platform != "darwin":

        def removed(kept) -> bool:
            # Each backend says "not there" with an error of its own, so look first.
            if kept.get_password(SERVICE, name) is None:
                return False
            kept.delete_password(SERVICE, name)
            return True

        return _in_store("remove", _checked(name), removed)
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


def _keyring():
    """keyring's backend for this platform's store, or None when it can't be used here: keyring
    isn't installed, or the store doesn't answer (no Secret Service running, say)."""
    module, backend = _BACKENDS.get(sys.platform, _SECRET_SERVICE)
    try:
        found = getattr(importlib.import_module(module), backend)
        return found() if found.viable else None
    except Exception:  # noqa: BLE001 - not installed, or broken: either way, no store to use
        return None


def _in_store(doing: str, name: str, call: Callable, value: str = ""):
    """What `call` gives on keyring's backend, or a KeychainError saying why not, in at most
    _TIMEOUT: a locked Secret Service asks for its password first, which takes a person. The call
    can't be stopped once it's waiting, so it waits on a thread of its own that's left behind."""
    kept = _keyring()
    failed = f"the {store()} didn't {doing} {name}"
    if kept is None:
        raise KeychainError(f"{failed}: it can't be reached here")
    outcome: list[tuple[bool, object]] = []

    def run() -> None:
        try:
            outcome.append((True, call(kept)))
        except Exception as e:  # noqa: BLE001 - each store raises its own kinds
            said = " ".join(str(e).split())
            outcome.append((False, (said.replace(value, "[hidden]") if value else said)[:200]))

    waiting = threading.Thread(target=run, daemon=True)
    waiting.start()
    waiting.join(_TIMEOUT)
    if not outcome:
        raise KeychainError(f"{failed}: it took too long")
    done, result = outcome[0]
    if not done:
        raise KeychainError(f"{failed}: {result or 'it failed'}")
    return result
