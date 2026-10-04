"""Carpetas de corrida: prompt.md, events.jsonl, last.md, meta.json."""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .errors import DelegateError

# Estados que todavía esperan una decisión: no se limpian aunque sean viejos.
PENDING = {"running", "listo-para-revisar", "checks-fallidos", "escalado-a-main"}


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
    exit_code: int | None = None
    duration_s: float = 0.0
    thread_id: str | None = None
    project_root: str | None = None
    worktree: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    base_branch: str | None = None
    check_cmd: str | None = None
    last_check: dict[str, Any] | None = None
    diffstat: str | None = None
    fix_rounds: int = 0
    review_rounds: int = 0
    feedback: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    fallback_from: str | None = None
    escalated_from: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMeta":
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
    tmp = run_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False))
    tmp.replace(run_dir / "meta.json")


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
