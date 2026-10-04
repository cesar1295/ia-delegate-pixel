#!/usr/bin/env python3
"""ai-delegate: delega tareas de código a Codex o Antigravity (agy)."""

import sys

if sys.version_info < (3, 11):
    sys.exit("ai-delegate necesita Python 3.11 o superior.")

from aidelegate.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
