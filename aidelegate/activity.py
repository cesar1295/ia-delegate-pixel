"""Actividad local: solo nombres y fechas, con búsqueda acotada y caché."""

from datetime import datetime, timedelta
import os
from pathlib import Path
import time

from . import config

_CACHE: dict = {}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _scan(name: str, images: bool, cfg: dict | None = None) -> list[tuple[Path, float]]:
    cfg = config.load() if cfg is None else cfg
    home_raw = cfg.get("agents", {}).get(name, {}).get("home")
    home = Path(home_raw).expanduser() if home_raw else Path.home()
    today = datetime.now().date()
    key = (str(home), name, images, today)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 2:
        return cached[1]
    if images:
        folder = {"codex": ".codex/generated_images", "agy": ".gemini/antigravity-cli/brain"}.get(name)
        if folder is None:
            return []
        roots = [(home / folder, None)]
        matches = lambda p: p.suffix.lower() in _IMAGE_SUFFIXES
    elif name == "claude":
        roots = [(home / ".claude/projects", 2)]
        matches = lambda p: p.suffix == ".jsonl"
    elif name == "codex":
        root = home / ".codex/sessions"
        roots = [(root / (today - timedelta(days=n)).strftime("%Y/%m/%d"), None) for n in range(2)]
        matches = lambda p: p.name.startswith("rollout-") and p.suffix == ".jsonl"
    elif name == "agy":
        roots = [(home / ".gemini/antigravity-cli/conversations", 1)]
        matches = lambda p: True
    else:
        return []
    found = []
    remaining = 2000
    def scan(root, depth):
        nonlocal remaining
        if remaining <= 0 or depth == 0:
            return
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if remaining <= 0:
                        break
                    remaining -= 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            scan(Path(entry.path), None if depth is None else depth - 1)
                        elif entry.is_file(follow_symlinks=False) and matches(Path(entry.path)):
                            found.append((Path(entry.path), entry.stat(follow_symlinks=False).st_mtime))
                    except OSError:
                        pass
        except OSError:
            pass
    for root, depth in roots:
        scan(root, depth)
    # Conserva solo la caché vigente; no acumula perfiles o días indefinidamente.
    stamp = time.monotonic()
    for old in list(_CACHE):
        if stamp - _CACHE[old][0] >= 2:
            del _CACHE[old]
    _CACHE[key] = (stamp, found)
    return found


def last_activity(name: str, *, cfg: dict | None = None) -> datetime | None:
    latest = max((stamp for _, stamp in _scan(name, False, cfg)), default=None)
    return datetime.fromtimestamp(latest).astimezone() if latest is not None else None


def recent_images(name: str, since: datetime, *, cfg: dict | None = None) -> list[Path]:
    """Imágenes modificadas desde la fecha indicada; nunca abre su contenido."""
    return [path for path, stamp in _scan(name, True, cfg) if stamp >= since.timestamp()]
