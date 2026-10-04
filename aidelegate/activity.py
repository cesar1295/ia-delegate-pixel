"""Actividad reciente de sesiones locales, con búsqueda acotada."""

from datetime import datetime, timedelta
import os
from pathlib import Path
import time

_CACHE: dict = {}


def last_activity(name: str) -> datetime | None:
    home = Path.home()
    key = (str(home), name)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 2:
        return cached[1]
    if name == "claude":
        roots = [(home / ".claude/projects", 2)]
        matches = lambda p: p.suffix == ".jsonl"
    elif name == "codex":
        root = home / ".codex/sessions"
        roots = [(root / (datetime.now() - timedelta(days=n)).strftime("%Y/%m/%d"), None) for n in range(2)]
        matches = lambda p: p.name.startswith("rollout-") and p.suffix == ".jsonl"
    elif name == "agy":
        roots = [(home / ".gemini/antigravity-cli/conversations", 1)]
        matches = lambda p: True
    else:
        return None
    latest = None
    remaining = [2000]
    def scan(root, depth):
        nonlocal latest
        if remaining[0] <= 0 or depth == 0:
            return
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if remaining[0] <= 0:
                        break
                    remaining[0] -= 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            scan(Path(entry.path), None if depth is None else depth - 1)
                        elif entry.is_file(follow_symlinks=False) and matches(Path(entry.path)):
                            stamp = entry.stat().st_mtime
                            latest = max(latest or stamp, stamp)
                    except OSError:
                        pass
        except OSError:
            pass
    for root, depth in roots:
        scan(root, depth)
    value = datetime.fromtimestamp(latest).astimezone() if latest is not None else None
    _CACHE[key] = (time.monotonic(), value)
    return value
