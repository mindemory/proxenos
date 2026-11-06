"""slackdump, fetched the first time it's needed, for people who never open a terminal.

Slack is read with slackdump (github.com/rusq/slackdump), a separate program under the AGPL-3.0.
So it isn't bundled into the desktop app: when `slackdump` isn't on the PATH, the first sign-in
downloads it from the project's own GitHub release, a version pinned here, and checks the archive
against the SHA-256 the release's checksums.txt lists (pinned below too) before unpacking
anything. It's unpacked into `tools/slackdump` in Proxenos's settings folder (private, like the
rest) and used from there. Nothing of the user's goes to GitHub: it's a plain download of a public
file. The archive is read for one member, `slackdump` (and its LICENSE), by name, never by a path
it holds.

Only Macs are fetched for: a release asset for each Mac, with its hash. Elsewhere, install
slackdump yourself (`brew install slackdump`, or the project's releases) and it's found on the PATH.
"""

import hashlib
import io
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from proxenos import config

VERSION = "v4.5.4"
RELEASE = f"https://github.com/rusq/slackdump/releases/download/{VERSION}"
# The release's assets for each Mac, and their SHA-256 from its checksums.txt.
ASSETS = {
    "arm64": (
        "slackdump_macOS_arm64.tar.gz",
        "ca3a0002ab0dc310e36afad9e2ee650408259e27d912a12ac75ec8e7cda5b0e3",
    ),
    "x86_64": (
        "slackdump_macOS_x86_64.tar.gz",
        "a2b141d16104fada9786851362674e949920905980581e673848a3a44b4b4240",
    ),
}
_MAX = 64 * 1024 * 1024  # bytes: the archives are 16 MB; more than this is something else
_TIMEOUT = 60  # seconds without a word from GitHub


def folder() -> Path:
    """Where the downloaded slackdump lives: tools/slackdump beside the settings file."""
    return config.SETTINGS_FILE.parent / "tools" / "slackdump"


def downloaded() -> Path:
    return folder() / "slackdump"


def find() -> str | None:
    """What to run for slackdump: "slackdump" when it's on the PATH, else the downloaded one's
    path, else None."""
    if shutil.which("slackdump"):
        return "slackdump"
    path = downloaded()
    return str(path) if path.is_file() and os.access(path, os.X_OK) else None


def fetchable(system: str | None = None, machine: str | None = None) -> bool:
    """Whether there's a release to download for this computer."""
    return (system or platform.system()) == "Darwin" and (machine or platform.machine()) in ASSETS


def ensure(
    say: Callable[[str], None] | None = None,
    opener: Callable | None = None,
    system: str | None = None,
    machine: str | None = None,
) -> str:
    """slackdump's command: the one on the PATH or already downloaded, else fetched now. SystemExit,
    with a sentence, where there's none to fetch or the download fails or doesn't match its hash."""
    if found := find():
        return found
    if not fetchable(system, machine):
        raise SystemExit("Install slackdump first: brew install slackdump")
    say = say or (lambda line: print(line, flush=True))
    name, expected = ASSETS[machine or platform.machine()]
    say(f"Downloading slackdump {VERSION} (about 16 MB) from its GitHub release.")
    try:
        data = _download(f"{RELEASE}/{name}", opener or urllib.request.urlopen)
    except (OSError, ValueError) as e:
        raise SystemExit(
            f"Couldn't download slackdump: {' '.join(str(e).split())[:150] or 'no answer'}. "
            "Check the connection and try again, or install it: brew install slackdump"
        ) from None
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(
            f"The slackdump download isn't the file Proxenos expects ({name}, {VERSION}), "
            "so it wasn't used."
        )
    _unpack(data)
    say("slackdump is ready.")
    return str(downloaded())


def _download(url: str, opener: Callable) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("not an https address")
    with opener(urllib.request.Request(url), timeout=_TIMEOUT) as response:
        data = response.read(_MAX + 1)
    if len(data) > _MAX:
        raise ValueError("the file is bigger than slackdump's release")
    return data


def _unpack(data: bytes) -> None:
    """Write the archive's `slackdump` (and LICENSE) into the tools folder: private, and whole or
    not at all. Members are picked by their names; no path from the archive is ever used."""
    target = folder()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sys.platform != "win32":
        for parent in (target, target.parent):
            parent.chmod(0o700)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = {m.name.removeprefix("./"): m for m in archive.getmembers() if m.isfile()}
        if "slackdump" not in members:
            raise SystemExit("The slackdump download holds no slackdump program.")
        for name, mode in (("slackdump", 0o700), ("LICENSE", 0o600)):
            if member := members.get(name):
                file = archive.extractfile(member)
                assert file is not None
                part = target / (name + ".part")
                fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
                with os.fdopen(fd, "wb") as out:
                    shutil.copyfileobj(file, out)
                part.chmod(mode)
                os.replace(part, target / name)
