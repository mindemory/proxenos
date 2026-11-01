"""`proxenos web`: start the local page and open it in the browser.

Runs the Next.js dev server in web/ on 127.0.0.1:4747, or the port given (installing its
packages the first time), and stays in the foreground until Ctrl-C. If the page is already
running there, it just opens it.

PROXENOS_PORT, when set, is the page's port in place of 4747: the desktop app sets it to the one
it picked, so a command it starts (`proxenos phone`) points at its page.
"""

import shutil
import socket
import subprocess
import time
import webbrowser

from proxenos.config import REPO_ROOT, env

PORT = 4747


def page_port() -> int:
    """The page's port: PROXENOS_PORT when it's a port, else PORT."""
    value = env("PORT").strip()
    return int(value) if value.isdigit() and 0 < int(value) < 65536 else PORT


def serve(port: int = PORT) -> None:
    url = f"http://127.0.0.1:{port}"
    if _listening(port):
        webbrowser.open(url)
        print(f"web: already running at {url}")
        return
    web = REPO_ROOT / "web"
    npm = shutil.which("npm") or "npm"  # npm.cmd on Windows, which a bare "npm" doesn't find
    if not (web / "node_modules").exists():
        subprocess.run([npm, "install"], cwd=web, check=True)
    # The script's own -p is 4747; a second one, after it, wins.
    server = subprocess.Popen([npm, "run", "dev", "--", "-p", str(port)], cwd=web)
    try:
        for _ in range(120):
            if _listening(port):
                webbrowser.open(url)
                print(f"web: running at {url}. Leave this window open; Ctrl-C stops it.")
                break
            time.sleep(0.5)
        server.wait()
    except KeyboardInterrupt:
        server.terminate()


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
