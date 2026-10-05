"""Conciliación conservadora de corridas resueltas fuera de ai-delegate."""
from __future__ import annotations

import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from . import runs, stats, worktree
from .runs import RunMeta
from .errors import DelegateError

OPEN = runs.PENDING - {"running"}
_schedule_lock = threading.Lock()
_last: dict[str, float] = {}
_worker: threading.Thread | None = None


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.stdout.strip()


def exists(root: Path, branch: str) -> bool:
    result = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                            cwd=root, capture_output=True, timeout=3)
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.returncode == 0


def close(meta: RunMeta, outcome: str, event: str, reason: str | None = None) -> None:
    meta.status = outcome
    meta.closed_reason = reason
    runs.add_event(meta, event, reason or "")
    stats.record(meta, outcome)


def _date(value: str, now: datetime) -> datetime:
    date = datetime.fromisoformat(value)
    if date.tzinfo is None and now.tzinfo is not None:
        date = date.replace(tzinfo=now.tzinfo)
    elif date.tzinfo is not None and now.tzinfo is None:
        date = date.astimezone().replace(tzinfo=None)
    return date


def _resolved(meta: RunMeta, now: datetime) -> tuple[str, str] | None:
    if meta.project_root:
        root = Path(meta.project_root)
        if meta.worktree:
            branch = meta.branch or f"ai/{meta.run_id}"
            present = exists(root, branch)
            if present and meta.base_branch and exists(root, meta.base_branch):
                tip = git(root, "rev-parse", branch)
                if tip != meta.base_commit:
                    result = subprocess.run(["git", "merge-base", "--is-ancestor", branch, meta.base_branch],
                                            cwd=root, capture_output=True, timeout=3)
                    if result.returncode not in (0, 1):
                        raise subprocess.CalledProcessError(result.returncode, result.args)
                    if result.returncode == 0 and (not Path(meta.worktree).exists() or
                                                   not git(Path(meta.worktree), "status", "--porcelain")):
                        worktree.remove(root, Path(meta.worktree), branch, timeout=3)
                        return "integrado", "integrada fuera de ai-delegate"
            if not present and not Path(meta.worktree).exists():
                return "descartado", "worktree y rama borrados fuera de ai-delegate"
        elif meta.mode == "write":
            if meta.touched_files:
                if not git(root, "--literal-pathspecs", "status", "--porcelain", "--untracked-files=all", "--", *meta.touched_files):
                    head = runs.head(root)
                    return (("integrado", f"cambios en el commit {head[:7]}") if head and head != meta.start_head
                            else ("descartado", "cambios revertidos"))
            elif meta.start_head is None:
                committed = _date(git(root, "log", "-1", "--format=%cI"), now)
                if committed > _date(meta.updated_at, now) and not git(root, "status", "--porcelain"):
                    return "integrado", f"cambios en el commit {git(root, 'rev-parse', 'HEAD')[:7]}"
    if meta.status == "sin-cambios" and (now - _date(meta.updated_at, now)).total_seconds() > 86400:
        return "descartado", "sin cambios, cerrada sola"
    return None


def reconcile(metas: list[RunMeta] | None = None, now: datetime | None = None) -> list[tuple[str, str, str]]:
    results = []
    now = now or datetime.now()
    with runs.state_lock():
        metas = runs.recent(1_000_000) if metas is None else metas
        candidates = sorted((m for m in metas if m.status in OPEN), key=lambda m: m.run_id)
        cursor = runs.config.runs_dir() / ".reconcile-cursor"
        previous = cursor.read_text() if cursor.exists() else ""
        start = next((i for i, m in enumerate(candidates) if m.run_id > previous), 0)
        batch = (candidates[start:] + candidates[:start])[:30]
        for candidate in batch:
            try:
                # Avanza antes de git: un hook interrumpido tampoco debe impedir
                # que la siguiente invocación llegue a corridas más antiguas.
                cursor.write_text(candidate.run_id)
                folder = runs.config.runs_dir() / candidate.run_id
                meta = runs.load(folder)
                candidate.__dict__.update(vars(meta))
                if meta.status not in OPEN:
                    continue
                resolved = _resolved(meta, now)
                if resolved:
                    outcome, reason = resolved
                    close(meta, outcome, "auto-cerrada", reason)
                    candidate.__dict__.update(vars(meta))
                    results.append((meta.run_id, outcome, reason))
            except (OSError, ValueError, TypeError, DelegateError, subprocess.SubprocessError):
                continue
    return results


def background() -> None:
    """Inicia a lo más una conciliación por minuto; espera como máximo 200 ms."""
    global _worker
    key = str(runs.config.runs_dir())
    with _schedule_lock:
        tick = time.monotonic()
        if tick - _last.get(key, float("-inf")) < 60 or (_worker and _worker.is_alive()):
            return
        _last[key] = tick
        _worker = threading.Thread(target=reconcile, daemon=True)
        _worker.start()
        thread = _worker
    thread.join(.2)
