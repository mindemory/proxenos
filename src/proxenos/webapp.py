"""`proxenos web`: start the local page and open it in the browser.

Runs the Next.js dev server in web/ on 127.0.0.1:4747 (installing its packages the first time)
and stays in the foreground until Ctrl-C. If the page is already running, it just opens it.
"""

import socket
import subprocess
import time
import webbrowser

from proxenos.config import REPO_ROOT

PORT = 4747
URL = f"http://127.0.0.1:{PORT}"


def serve() -> None:
    if _listening():
        webbrowser.open(URL)
        print(f"web: already running at {URL}")
        return
    web = REPO_ROOT / "web"
    if not (web / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=web, check=True)
    server = subprocess.Popen(["npm", "run", "dev"], cwd=web)
    try:
        for _ in range(120):
            if _listening():
                webbrowser.open(URL)
                print(f"web: running at {URL}. Leave this window open; Ctrl-C stops it.")
                break
            time.sleep(0.5)
        server.wait()
    except KeyboardInterrupt:
        server.terminate()


def _listening() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0
