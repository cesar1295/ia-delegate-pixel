"""Rutas y configuración global (~/.config/ai-delegate/config.toml)."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import DelegateError

DEFAULTS: dict[str, Any] = {
    "strategy": {
        "mode": "routing",
        "programmer_kinds": [
            "feature", "bugfix", "refactor", "api", "design", "test",
            "docs", "mock", "i18n", "chore",
        ],
        "first": "agy",
        "then": "codex",
        "escalate_after": 2,
        "quota_floor_pct": 15,
    },
    "ui": {
        "time_mode": "auto",
        "fixed_hour": 12,
    },
    # tipo de tarea -> agente. "main" = la sesión principal (Claude) la hace.
    "routing": {
        # el diseño lo decide la sesión principal y lo pasa en --design-spec; el agente solo lo codifica
        "design": "codex",
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
    "review": {"enabled": True, "agent": "codex", "block_on": ["grave", "medio"], "max_rounds": 2},
    "default_kind": "feature",
    "spec_required_kinds": ["design"],
    "read_kinds": ["review", "research", "summarize"],
    # orden de escalamiento cuando un agente no lo resuelve
    "chain": ["agy", "codex", "claude"],
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
        "claude": {"five_hour_token_budget": 0, "model": "", "effort": "", "type": "claude", "bin": "auto", "display": "Claude", "color": "#d97757", "quota": "none", "role_text": "funcionalidades, especificaciones y revisiones; diseño visual", "permissions": {"edit": True}},
        "codex": {"bin": "codex", "home": "", "model": "", "effort": "", "type": "codex",
                  "display": "Codex", "color": "#3ddc97", "quota": "codex", "role_text": "funcionalidades, bugs, refactors, endpoints, implementar especificaciones de diseño, revisiones de código", "permissions": {"edit": True, "network": False}},
        "agy": {"bin": "agy", "home": "", "model": "", "effort": "", "type": "agy",
                "display": "agy", "color": "#7b8cff", "quota": "budget", "daily_token_budget": 0, "role_text": "tareas acotadas (tests sencillos, docs, datos de prueba, i18n), resumir repos, investigación web e imágenes; en la terminal solo tiene comandos de lectura", "permissions": {"edit": True, "groups": ["lectura"]}},
    },
    # "/ruta/al/repo" = { check = "npm run lint && npm test" }
    "main": "claude",
    "user_name": os.environ.get("USER", "usuario").capitalize(),
    "fallback_order": ["codex", "agy"],
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
    cfg["user_name"] = os.environ.get("USER", "usuario").capitalize()
    if not path.exists():
        first = cfg.get("strategy", {}).get("first", "agy")
        then = cfg.get("strategy", {}).get("then", "codex")
        cfg["chain"] = [first, then, cfg["main"]]
        for name, ag in cfg.get("agents", {}).items():
            if isinstance(ag, dict):
                from .permissions import get_effective_permissions
                ag["permissions"] = get_effective_permissions(ag, name)
        return cfg
    try:
        user = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise DelegateError(f"La config {path} no es TOML válido: {exc}") from exc
    _merge(cfg, user)
    cfg["main"] = main_name(cfg)
    if "chain" not in user:
        first = cfg.get("strategy", {}).get("first", "agy")
        then = cfg.get("strategy", {}).get("then", "codex")
        cfg["chain"] = [first, then, cfg["main"]]
    for name, ag in cfg.get("agents", {}).items():
        if isinstance(ag, dict):
            from .permissions import get_effective_permissions
            ag["permissions"] = get_effective_permissions(ag, name)
    return cfg


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def main_name(cfg: dict) -> str:
    value = cfg.get("main", "claude")
    return value.get("name", "claude") if isinstance(value, dict) else value


def backup_file(path: Path) -> Path:
    """Crea una copia de respaldo con sufijo de fecha."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(str(path) + ".bak-ai-delegate-" + stamp)
    index = 1
    while target.exists() or target.is_symlink():
        target = Path(str(path) + ".bak-ai-delegate-" + stamp + f"-{index}")
        index += 1
    shutil.copy2(path, target, follow_symlinks=False)
    return target


def write_config_updates(changes: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    """Actualiza config.toml conservando comentarios y otras claves, creando respaldo previo."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_file(path)
        original = path.read_text(encoding="utf-8")
    else:
        original = ""

    headers = list(re.finditer(r"(?m)^\s*\[([^\n]+)\]\s*(?:#.*)?$", original))
    sections: dict[str, str] = {"": original[:headers[0].start()] if headers else original}
    order: list[str] = [""]
    for i, header in enumerate(headers):
        sec = header[1].strip()
        order.append(sec)
        sections[sec] = original[header.end():headers[i + 1].start() if i + 1 < len(headers) else len(original)]

    for key, value in changes.items():
        if "." in key:
            parts = key.split(".")
            sec = ".".join(parts[:-1])
            k = parts[-1]
        else:
            sec = ""
            k = key

        if ".task_models." in sec and value == "":
            if sec in sections:
                sections[sec] = re.sub(rf"(?m)^\s*{re.escape(k)}\s*=.*(?:\n|$)", "", sections[sec])
                if not re.search(r"(?m)^\s*(?:model|effort)\s*=", sections[sec]):
                    del sections[sec]
                    order.remove(sec)
            continue

        if sec not in sections:
            sections[sec] = ""
            order.append(sec)

        body = sections[sec]
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        elif isinstance(value, (int, float)):
            val_str = str(value)
        elif isinstance(value, str):
            val_str = json.dumps(value, ensure_ascii=False)
        else:
            val_str = json.dumps(value, ensure_ascii=False)

        pattern = rf"(?m)^\s*{re.escape(k)}\s*=.*$"
        line = f"{k} = {val_str}"
        if re.search(pattern, body):
            body = re.sub(pattern, lambda m: line, body)
        else:
            if body and not body.endswith("\n"):
                body += "\n"
            body += line + "\n"
        sections[sec] = body

    text = sections[""]
    for sec in order:
        if not sec:
            continue
        body = sections[sec].strip()
        text += f"\n[{sec}]\n{body}\n" if body else f"\n[{sec}]\n"

    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DelegateError(f"Error generando TOML válido: {exc}") from exc

    path.write_text(text, encoding="utf-8")
    return load(path)
