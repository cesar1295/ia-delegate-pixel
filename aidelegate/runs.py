"""Carpetas de corrida: prompt.md, events.jsonl, last.md, meta.json."""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .errors import DelegateError

# Estados que todavía esperan una decisión: no se limpian aunque sean viejos.
PENDING = {"running", "listo-para-revisar", "checks-fallidos", "escalado-a-main", "sin-cambios"}


_state_lock = threading.RLock()
_lock_local = threading.local()


@contextmanager
def state_lock():
    """Serializa cambios de corridas entre hilos y procesos (Linux/macOS).

    flock se libera incluso si el hook termina por timeout. La profundidad local
    permite que save/add_event se llamen dentro de una conciliación o cierre.
    """
    with _state_lock:
        if getattr(_lock_local, "depth", 0):
            _lock_local.depth += 1
            try:
                yield
            finally:
                _lock_local.depth -= 1
            return
        root = config.runs_dir()
        root.mkdir(parents=True, exist_ok=True)
        with (root / ".state.lock").open("a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            _lock_local.depth = 1
            try:
                yield
            finally:
                _lock_local.depth = 0
                fcntl.flock(lock_file, fcntl.LOCK_UN)


@dataclass
class RunMeta:
    run_id: str
    agent: str
    mode: str
    kind: str
    repo: str
    source_dir: str
    workdir: str
    task: str
    status: str = "running"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    pid: int | None = None
    phase: str | None = None
    phase_label: str | None = None
    phase_started_at: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    exit_code: int | None = None
    duration_s: float = 0.0
    thread_id: str | None = None
    project_root: str | None = None
    worktree: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    base_branch: str | None = None
    design_spec_path: str | None = None
    check_cmd: str | None = None
    last_check: dict[str, Any] | None = None
    acceptance_criteria: list[str] = field(default_factory=list)
    acceptance: dict | None = None
    visual: dict | None = None
    prereview: dict | None = None
    no_review: bool = False
    start_head: str | None = None
    start_snapshot: dict[str, str | None] = field(default_factory=dict)
    touched_files: list[str] = field(default_factory=list)
    closed_reason: str | None = None
    diffstat: str | None = None
    fix_rounds: int = 0
    review_rounds: int = 0
    feedback: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    fallback_from: str | None = None
    escalated_from: list[str] = field(default_factory=list)
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    subagents: list[dict] = field(default_factory=list)
    target_reason: str | None = None

    @property
    def corrections(self) -> int:
        return self.fix_rounds + self.review_rounds

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMeta":
        data = dict(data)
        data.setdefault("updated_at", data.get("created_at", ""))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def new_run_id(repo: str, agent: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"
    base = f"{datetime.now():%Y%m%d-%H%M%S}-{slug}-{agent}"
    run_id, n = base, 2
    while (config.runs_dir() / run_id).exists():
        run_id, n = f"{base}-{n}", n + 1
    return run_id


def create(meta: RunMeta) -> Path:
    run_dir = config.runs_dir() / meta.run_id
    run_dir.mkdir(parents=True)
    save(meta, run_dir)
    return run_dir


def save(meta: RunMeta, run_dir: Path) -> None:
    with state_lock():
        meta.updated_at = datetime.now().isoformat(timespec="seconds")
        tmp = run_dir / "meta.json.tmp"
        tmp.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False))
        tmp.replace(run_dir / "meta.json")


def add_event(meta: RunMeta, type: str, label: str = "") -> None:
    meta.events.append({"type": type, "ts": datetime.now().isoformat(timespec="seconds"),
                        "label": label, "agent": meta.agent})
    save(meta, config.runs_dir() / meta.run_id)


def load(run_dir: Path) -> RunMeta:
    return RunMeta.from_dict(json.loads((run_dir / "meta.json").read_text()))


def append_prompt(run_dir: Path, prompt: str, label: str) -> None:
    with open(run_dir / "prompt.md", "a") as fh:
        fh.write(f"<!-- {label} -->\n{prompt}\n\n")


def write_text(run_dir: Path, name: str, text: str) -> None:
    (run_dir / name).write_text(text)


def resolve(ref: str) -> Path:
    """Acepta el id completo, un prefijo único o 'last'."""
    root = config.runs_dir()
    candidates = sorted(p for p in root.glob("*") if (p / "meta.json").exists()) if root.exists() else []
    if ref == "last" and candidates:
        return candidates[-1]
    matches = [p for p in candidates if p.name == ref] or [p for p in candidates if p.name.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise DelegateError(f"No encuentro la corrida '{ref}'. Mira las disponibles con: ai-delegate list")
    raise DelegateError(f"'{ref}' coincide con {len(matches)} corridas; usa más caracteres del id.")


def recent(limit: int) -> list[RunMeta]:
    root = config.runs_dir()
    if not root.exists():
        return []
    dirs = sorted((p for p in root.glob("*") if (p / "meta.json").exists()), reverse=True)
    return [load(p) for p in dirs[:limit]]


def cleanup_old(keep_days: int) -> int:
    root = config.runs_dir()
    if not root.exists():
        return 0
    limit = time.time() - keep_days * 86400
    removed = 0
    for run_dir in root.glob("*"):
        if run_dir.is_dir() and run_dir.stat().st_mtime < limit and not _is_pending(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)
            removed += 1
    return removed


def _is_pending(run_dir: Path) -> bool:
    try:
        meta = load(run_dir)
    except (OSError, ValueError, TypeError):
        return False
    return meta.status in PENDING or bool(meta.worktree and Path(meta.worktree).exists())


def snapshot(root: Path) -> dict[str, str | None]:
    result = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                            cwd=root, capture_output=True, check=True, timeout=3)
    entries = result.stdout.decode(errors="surrogateescape").split("\0")
    paths = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        paths.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            paths.append(entries[i])
            i += 1
    hashes = {}
    for path in paths:
        file = root / path
        try:
            if file.is_symlink():
                content = str(file.readlink()).encode()
            elif file.is_dir():
                content = _directory_snapshot(file)
            else:
                content = file.read_bytes()
            hashes[path] = hashlib.sha1(content).hexdigest()
        except FileNotFoundError:
            hashes[path] = None
    return hashes


def _directory_snapshot(path: Path) -> bytes:
    # Los gitlinks aparecen como directorios. Incluye también cambios sin commit,
    # porque el HEAD por sí solo no detecta ediciones dentro del submódulo.
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path,
                            capture_output=True, text=True, timeout=3)
    if result.returncode or Path(result.stdout.strip()).resolve() != path.resolve():
        return b"directory"  # Submódulo desinicializado: no tiene árbol que leer.
    return json.dumps({"head": head(path), "dirty": snapshot(path)},
                      sort_keys=True, ensure_ascii=True).encode()


def head(root: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                            cwd=root, capture_output=True, text=True, timeout=3)
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(result.returncode, result.args)
    return result.stdout.strip() if result.returncode == 0 else None


def capture_start(meta: RunMeta) -> None:
    if meta.mode != "write" or meta.worktree or not meta.project_root:
        return
    root = Path(meta.project_root)
    meta.start_head = head(root)
    meta.start_snapshot = snapshot(root)


def track_touched(meta: RunMeta) -> None:
    if meta.mode != "write" or meta.worktree or not meta.project_root:
        return
    current = snapshot(Path(meta.project_root))
    changed = {p for p in current.keys() | meta.start_snapshot.keys()
               if p not in current or p not in meta.start_snapshot or current[p] != meta.start_snapshot[p]}
    meta.touched_files = sorted(set(meta.touched_files) | changed)
    meta.diffstat = f"{len(meta.touched_files)} archivos tocados"
