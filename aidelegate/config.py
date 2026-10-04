"""Rutas y configuración global (~/.config/ai-delegate/config.toml)."""

from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path
from typing import Any

from .errors import DelegateError

DEFAULTS: dict[str, Any] = {
    # tipo de tarea -> agente. "main" = la sesión principal (Claude) la hace.
    "routing": {
        "design": "main",
        "security": "main",
        "feature": "codex",
        "bugfix": "codex",
        "refactor": "codex",
        "api": "codex",
        "review": "codex",
        # agy lee repos gracias a las reglas permissions.allow de su settings.json
        "summarize": "agy",
        "test": "agy",
        "docs": "agy",
        "mock": "agy",
        "i18n": "agy",
        "chore": "agy",
        "research": "agy",
        "image": "agy",
    },
    "default_kind": "feature",
    "read_kinds": ["review", "research", "summarize"],
    # orden de escalamiento cuando un agente no lo resuelve
    "chain": ["agy", "codex", "main"],
    "limits": {
        "max_fix_rounds": 3,
        "max_review_rounds": 2,
        "timeout_min": 30,
        "check_timeout_min": 15,
        "keep_days": 7,
        "summary_lines": 15,
    },
    # home vacío = tu HOME normal (perfil ya autenticado)
    "agents": {
        "codex": {"bin": "codex", "home": "", "model": ""},
        "agy": {"bin": "agy", "home": "", "model": ""},
    },
    # "/ruta/al/repo" = { check = "npm run lint && npm test" }
    "projects": {},
}


def data_dir() -> Path:
    if custom := os.environ.get("AI_DELEGATE_HOME"):
        return Path(custom)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "ai-delegate"


def runs_dir() -> Path:
    return data_dir() / "runs"


def worktrees_dir() -> Path:
    return data_dir() / "worktrees"


def ledger_path() -> Path:
    return data_dir() / "ledger.jsonl"


def config_path() -> Path:
    if custom := os.environ.get("AI_DELEGATE_CONFIG"):
        return Path(custom)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ai-delegate" / "config.toml"


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or config_path()
    cfg = copy.deepcopy(DEFAULTS)
    if not path.exists():
        return cfg
    try:
        user = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise DelegateError(f"La config {path} no es TOML válido: {exc}") from exc
    _merge(cfg, user)
    return cfg


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
