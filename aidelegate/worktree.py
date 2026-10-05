"""Git worktrees aislados: el agente trabaja en una rama propia, nunca en tu copia."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config
from .errors import DelegateError

# Carpetas pesadas sin versionar que se enlazan desde tu copia para que los checks corran.
LINKED_DIRS = ("node_modules", ".venv", "venv")
# Basura que generan los checks; nunca entra al diff ni al commit.
_JUNK = ("**/__pycache__/**", "**/*.pyc", "**/.pytest_cache/**", "**/.DS_Store")
_EXCLUDES = [f":(exclude){name}" for name in LINKED_DIRS] + [f":(exclude,glob){p}" for p in _JUNK]


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base_commit: str
    base_branch: str
    linked: tuple[str, ...]
    dirty_base: bool


def git(cwd: Path, *args: str, check: bool = True, timeout: float | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise DelegateError(f"git {' '.join(args[:3])} falló en {cwd}: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path | None:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True, text=True)
    return Path(proc.stdout.strip()) if proc.returncode == 0 else None


def create(root: Path, run_id: str) -> Worktree:
    if not git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False):
        raise DelegateError(f"{root} no tiene commits todavía; haz un primer commit o usa --no-worktree.")
    branch = f"ai/{run_id}"
    path = config.worktrees_dir() / run_id
    path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-q", "-b", branch, str(path), "HEAD")
    return Worktree(
        path=path,
        branch=branch,
        base_commit=git(root, "rev-parse", "HEAD"),
        base_branch=git(root, "branch", "--show-current"),
        linked=tuple(_link_deps(root, path)),
        dirty_base=bool(git(root, "status", "--porcelain")),
    )


def _link_deps(root: Path, path: Path) -> list[str]:
    linked = []
    for name in LINKED_DIRS:
        if (root / name).is_dir() and not (path / name).exists():
            (path / name).symlink_to(root / name)
            linked.append(name)
    return linked


def stage_all(path: Path) -> None:
    git(path, "add", "-A", "--", ".", *_EXCLUDES)


def diff(path: Path, base_commit: str, stat: bool = False) -> str:
    stage_all(path)
    args = ["diff", "--cached", *(["--stat"] if stat else []), base_commit, "--", ".", *_EXCLUDES]
    return git(path, *args)


def diffstat_line(path: Path, base_commit: str) -> str:
    lines = diff(path, base_commit, stat=True).splitlines()
    return lines[-1].strip() if lines else "sin cambios"


def merge(root: Path, path: Path, branch: str, base_branch: str, message: str) -> None:
    stage_all(path)
    if not git(path, "diff", "--cached", "--name-only"):
        raise DelegateError("No hay cambios para integrar. Usa 'discard' si quieres descartar la corrida.")
    current = git(root, "branch", "--show-current")
    if current != base_branch:
        raise DelegateError(
            f"Tu copia está en la rama '{current}' y la corrida salió de '{base_branch}'. "
            f"Cambia con 'git switch {base_branch}' o integra a mano: git merge {branch}"
        )
    git(path, "commit", "-q", "-m", message)
    proc = subprocess.run(["git", "merge", "--no-ff", "--no-edit", branch], cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DelegateError(
            f"Conflicto al integrar {branch} en {root}. Resuélvelo ahí (o 'git merge --abort') y luego "
            f"corre 'ai-delegate discard' para limpiar el worktree.\n{proc.stdout.strip()[-400:]}"
        )
    remove(root, path, branch)


def remove(root: Path, path: Path, branch: str, timeout: float | None = None) -> None:
    if path.exists():
        git(root, "worktree", "remove", "--force", str(path), timeout=timeout)
    git(root, "worktree", "prune", check=timeout is not None, timeout=timeout)
    git(root, "branch", "-D", branch, check=timeout is not None, timeout=timeout)
