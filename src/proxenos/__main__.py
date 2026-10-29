"""`python -m proxenos`: the `proxenos` command, the way the scheduler starts each of its jobs.

A stop from outside (Ctrl-Break on Windows, where a job has a process group of its own, or
SIGTERM from a service manager) unwinds the run the way Ctrl-C does, so files and the vault's run
lock are let go of in order, and the run ends with 130, as an interrupted command does.
"""

import signal
import sys

from proxenos.cli import main

if __name__ == "__main__":
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.default_int_handler)
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
