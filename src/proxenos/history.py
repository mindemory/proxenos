"""The vault's own history of the self-model, read as of a time.

The vault is a local git repository tracking self/ and observations/ (proxenos.master commits
them at every change), so what the self-model said at any moment is there. A reply drafted as
of an earlier time, to compare with what the user sent then (proxenos.compare, `proxenos voice
eval`), reads the self-model and the writing rules the user kept as they stood then, never as
they stand now, which may have learned from that very reply and what came after it.
"""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


def at(vault: Path, rel: str | Path, when: datetime) -> str:
    """The vault's file at `rel` (such as self/identity.md) as the last commit before `when` left
    it; "" where it wasn't there then, or where there's no history to tell (no git, or no
    commit yet), since the file as it is now could hold what came after."""
    if shutil.which("git") is None or not (vault / ".git").exists():
        return ""
    path = PurePosixPath(Path(rel).as_posix())
    before = when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git(vault, "rev-list", "-1", f"--before={before}", "HEAD", "--", str(path))
    if not commit:
        return ""
    return _git(vault, "show", f"{commit}:{path}", strip=False)


def _git(vault: Path, *args: str, strip: bool = True) -> str:
    """What git printed, or "" when it failed: a path the commit doesn't have, say."""
    done = subprocess.run(
        ["git", "-C", str(vault), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode:
        return ""
    return done.stdout.strip() if strip else done.stdout
