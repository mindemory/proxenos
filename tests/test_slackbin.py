"""slackdump fetched on first use, and its login run under a pseudo-terminal. A fake archive and a
fake slackdump script: no network, no Slack, no browser."""

import hashlib
import io
import os
import stat
import sys
import tarfile
import textwrap

import pytest

from proxenos import auth, slackbin

NAME = "slackdump_macOS_arm64.tar.gz"


def archive(members):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    return out.getvalue()


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def serving(data, seen):
    def opener(request, timeout):
        seen.append(request.full_url)
        return Response(data)

    return opener


@pytest.fixture
def pinned(monkeypatch):
    """The release's asset for this test's archive, with its real hash, and no slackdump on the PATH."""
    monkeypatch.setattr(slackbin.shutil, "which", lambda name: None)

    def pin(data):
        monkeypatch.setitem(slackbin.ASSETS, "arm64", (NAME, hashlib.sha256(data).hexdigest()))

    return pin


def test_the_pinned_release_is_for_each_mac_and_a_known_version():
    assert slackbin.VERSION == "v4.5.4"
    assert {a: n for a, (n, _) in slackbin.ASSETS.items()} == {
        "arm64": "slackdump_macOS_arm64.tar.gz",
        "x86_64": "slackdump_macOS_x86_64.tar.gz",
    }
    assert all(len(h) == 64 and int(h, 16) >= 0 for _, h in slackbin.ASSETS.values())


def test_it_is_downloaded_checked_and_unpacked_privately_when_not_on_the_path(pinned):
    data = archive({"slackdump": b"#!/bin/sh\n", "LICENSE": b"AGPL", "README.md": b"x"})
    pinned(data)
    seen, said = [], []
    got = slackbin.ensure(said.append, serving(data, seen), "Darwin", "arm64")

    assert seen == [f"https://github.com/rusq/slackdump/releases/download/v4.5.4/{NAME}"]
    assert got == str(slackbin.downloaded())
    assert slackbin.downloaded().read_bytes() == b"#!/bin/sh\n"
    assert (slackbin.folder() / "LICENSE").read_bytes() == b"AGPL"
    assert not (slackbin.folder() / "README.md").exists()  # only what's wanted, by name
    if os.name != "nt":
        assert stat.S_IMODE(slackbin.downloaded().stat().st_mode) == 0o700
        assert stat.S_IMODE(slackbin.folder().stat().st_mode) == 0o700
    assert said[0].startswith("Downloading slackdump v4.5.4") and said[-1].endswith("ready.")

    # Used from then on, with no more downloads.
    assert slackbin.find() == got
    assert slackbin.ensure(said.append, lambda *a, **k: pytest.fail("downloaded again")) == got


def test_a_download_that_isnt_the_pinned_file_is_refused_and_nothing_is_unpacked(pinned):
    pinned(archive({"slackdump": b"the real one"}))
    with pytest.raises(SystemExit, match="isn't the file Proxenos expects"):
        slackbin.ensure(
            lambda line: None, serving(archive({"slackdump": b"other"}), []), "Darwin", "arm64"
        )
    assert not slackbin.folder().exists()


def test_a_failed_or_odd_download_is_said_in_a_sentence(pinned):
    def down(request, timeout):
        raise OSError("no route to host")

    with pytest.raises(SystemExit, match="Couldn't download slackdump: no route to host"):
        slackbin.ensure(lambda line: None, down, "Darwin", "arm64")

    data = archive({"README.md": b"no program here"})
    pinned(data)
    with pytest.raises(SystemExit, match="holds no slackdump"):
        slackbin.ensure(lambda line: None, serving(data, []), "Darwin", "arm64")


def test_the_path_wins_and_other_computers_are_told_to_install_it(monkeypatch):
    monkeypatch.setattr(slackbin.shutil, "which", lambda name: "/opt/homebrew/bin/slackdump")
    assert slackbin.ensure() == "slackdump"
    monkeypatch.setattr(slackbin.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="brew install slackdump"):
        slackbin.ensure(system="Windows", machine="AMD64")


FAKE = textwrap.dedent(
    """\
    #!{python}
    # A slackdump that needs a terminal, shows its login menu and waits for Enter, as the real one's does.
    import os, sys
    if not (os.isatty(0) and os.isatty(1)):
        sys.exit(7)  # browser auth is not supported in dumb terminals
    if os.path.exists({marker!r}):
        sys.stdout.write("Workspace 'acme' already exists. Overwrite? (y/N) ")
        sys.stdout.flush()
        if sys.stdin.readline().strip() != "y":
            sys.exit(3)
    sys.stdout.write("\\x1b[2KSelect login type for [acme]\\r\\n> Interactive\\r\\n")
    sys.stdout.flush()
    keys = b""
    while not keys.endswith(b"\\n"):  # Enter, which the terminal hands on as a newline
        keys += os.read(0, 16)
    picked = {{0: "interactive", 2: "user-browser"}}.get(keys.count(b"\\x1b[B"), "other")
    open({log!r}, "w").write(picked + " " + " ".join(sys.argv[1:]))
    sys.exit(0)
    """
)


@pytest.mark.skipif(os.name == "nt", reason="pseudo-terminals are for Macs and Linux")
@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("google", [False, True])
def test_the_login_runs_under_a_pseudo_terminal_and_picks_the_browser_login(
    tmp_path, known, google
):
    log, marker = tmp_path / "log", tmp_path / "known"
    if known:
        marker.write_text("")
    script = tmp_path / "slackdump"
    script.write_text(FAKE.format(python=sys.executable, log=str(log), marker=str(marker)))
    script.chmod(0o700)
    said = []

    status = auth._slack_pty_login(str(script), "acme", seconds=20, say=said.append, google=google)

    assert status == 0
    # Interactive's clean browser can't sign in with Google; User Browser, two down, can.
    picked = "user-browser" if google else "interactive"
    assert log.read_text() == f"{picked} workspace new acme"
    assert said == ["A browser window is opening. Sign in to acme there."]


@pytest.mark.skipif(os.name == "nt", reason="pseudo-terminals are for Macs and Linux")
def test_a_login_left_open_too_long_is_stopped(tmp_path):
    script = tmp_path / "slackdump"
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    script.chmod(0o700)
    said = []
    assert auth._slack_pty_login(str(script), "acme", seconds=1, say=said.append) == 1
    assert said == ["Slack's login window was open too long; try again."]


def test_without_a_terminal_the_sign_in_uses_the_pseudo_terminal(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from proxenos.ingest import slackdump

    monkeypatch.setattr(slackbin.shutil, "which", lambda name: "/bin/slackdump")
    monkeypatch.setattr(slackdump, "archives", list)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    seen = []
    monkeypatch.setattr(
        auth,
        "_slack_pty_login",
        lambda binary, ws, google=False: seen.append((binary, ws, google)) or 0,
    )
    monkeypatch.setattr(slackdump, "FROM_SOURCE", False)
    monkeypatch.setenv("PROXENOS_VAULT", str(tmp_path / "vault"))
    auth.slackdump("acme", run=lambda command: SimpleNamespace(returncode=0))
    auth.slackdump("acme", run=lambda command: SimpleNamespace(returncode=0), google=True)
    assert seen == [("slackdump", "acme", False), ("slackdump", "acme", True)]


def test_slackdumps_own_failures_become_plain_sentences():
    missing = "ERROR 004 (Authentication Error): failed to initialise the\n   auth provider: workspace not found: 404."
    with pytest.raises(SystemExit, match=r"no Slack workspace at acme\.slack\.com"):
        auth._slack_status(4, missing, "acme")
    with pytest.raises(SystemExit, match="needs Chrome or Firefox"):
        auth._slack_status(
            4, "ERROR 004: failed to initialise the auth provider: no browsers found.", "acme"
        )
    assert auth._slack_status(3, "something else went wrong", "acme") == 3
    assert (
        auth._slack_status(0, missing, "acme") == 0
    )  # it signed in: what it said earlier doesn't count
