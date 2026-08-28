"""Detached helper used by the admin restart action on Windows."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    time.sleep(1.5)
    output = (root / "dashboard-server-restarted.out.log").open("a", encoding="utf-8")
    errors = (root / "dashboard-server-restarted.err.log").open("a", encoding="utf-8")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, "-m", "dashboard.api"], cwd=root, stdout=output, stderr=errors, creationflags=flags, close_fds=True)


if __name__ == "__main__":
    main()
