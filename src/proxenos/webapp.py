"""`proxenos web`: start the local page and open it in the browser.

Runs the Next.js dev server in web/ on 127.0.0.1:4747, or the port given (installing its
packages the first time), and stays in the foreground until Ctrl-C. If the page is already
running there, it just opens it.
"""

import socket
import subprocess
import time
import webbrowser

from proxenos.config import REPO_ROOT

PORT = 4747


def serve(port: int = PORT) -> None:
    url = f"http://127.0.0.1:{port}"
    if _listening(port):
        webbrowser.open(url)
        print(f"web: already running at {url}")
        return
    web = REPO_ROOT / "web"
    if not (web / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=web, check=True)
    # The script's own -p is 4747; a second one, after it, wins.
    server = subprocess.Popen(["npm", "run", "dev", "--", "-p", str(port)], cwd=web)
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
