"""Catálogo de permisos por agente y sincronización con settings de agy."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# Catálogo fijo de agy
READ_COMMANDS = [
    "ls", "tree", "pwd", "cat", "head", "tail", "wc", "grep",
    "git status", "git log", "git diff", "git show", "git ls-files",
    "git grep", "git blame", "git rev-parse",
]

TEST_COMMANDS = [
    "npm test", "npm run test", "npm run lint", "npm run typecheck",
    "pnpm test", "pnpm run lint", "yarn test", "yarn lint",
    "pytest", "python3 -m pytest", "python -m pytest",
]

INSTALL_COMMANDS = [
    "npm install", "npm ci", "pnpm install", "yarn install",
    "pip install", "python3 -m pip install",
]

AGY_CATALOG: dict[str, list[str]] = {
    "lectura": READ_COMMANDS,
    "pruebas": TEST_COMMANDS,
    "instalacion": INSTALL_COMMANDS,
}

ALWAYS_DENIED = [
    "rm", "sudo", "git push", "git commit", "git reset", "git checkout", "git clean",
]

DEFAULT_PERMISSIONS: dict[str, dict[str, Any]] = {
    "codex": {"edit": True, "network": False},
    "agy": {"edit": True, "groups": ["lectura"]},
    "claude": {"edit": True},
    "generic": {},
}

ALLOWED_CHANGE_KEYS: dict[str, set[str]] = {
    "codex": {"edit", "network"},
    "agy": {"edit", "groups"},
    "claude": {"edit"},
    "generic": set(),
}


def get_effective_permissions(agent_dict: dict[str, Any], agent_name: str = "") -> dict[str, Any]:
    """Devuelve los permisos efectivos de un agente aplicando los valores por defecto."""
    agent_type = agent_dict.get("type", agent_name)
    defaults = DEFAULT_PERMISSIONS.get(agent_type, {})
    raw = agent_dict.get("permissions")
    if not isinstance(raw, dict):
        raw = {}
    effective = copy.deepcopy(defaults)
    for k, v in raw.items():
        if k in defaults:
            effective[k] = v
    return effective


def check_expansion(
    agent_type: str,
    display: str,
    current_perms: dict[str, Any],
    changes: dict[str, Any],
) -> list[str]:
    """Detecta si los cambios amplían permisos y genera los mensajes de confirmación correspondientes."""
    messages: list[str] = []

    # 1. edit: false -> true
    if "edit" in changes:
        old_edit = current_perms.get("edit", True)
        new_edit = bool(changes["edit"])
        if not old_edit and new_edit:
            messages.append(f"{display} podrá editar archivos en su carpeta de trabajo.")

    # 2. network: false -> true (codex)
    if "network" in changes and agent_type == "codex":
        old_net = current_perms.get("network", False)
        new_net = bool(changes["network"])
        if not old_net and new_net:
            messages.append("Codex tendrá acceso a internet dentro de su sandbox (por ejemplo para instalar dependencias).")

    # 3. groups: agregar pruebas o instalacion (agy)
    if "groups" in changes and agent_type == "agy":
        old_groups = set(current_perms.get("groups", ["lectura"]))
        new_groups = set(changes["groups"])
        if "pruebas" in new_groups and "pruebas" not in old_groups:
            cmd_list = ", ".join(TEST_COMMANDS)
            messages.append(f"agy podrá ejecutar: {cmd_list}.")
        if "instalacion" in new_groups and "instalacion" not in old_groups:
            cmd_list = ", ".join(INSTALL_COMMANDS)
            messages.append(f"agy podrá instalar dependencias con: {cmd_list}. Esto descarga código de internet.")

    return messages


def default_agy_settings_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".gemini/antigravity-cli/settings.json"


def sync_agy_settings(
    groups: list[str],
    settings_path: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Sincroniza las reglas de agy en settings.json creando respaldo previo."""
    from .config import backup_file

    path = settings_path or default_agy_settings_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_file(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms

    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        allow = []
    deny = perms.get("deny", [])
    if not isinstance(deny, list):
        deny = []

    # Reglas para grupos activos
    active_rules: list[str] = []
    for g in groups:
        for cmd in AGY_CATALOG.get(g, []):
            rule = f"command({cmd})"
            if rule not in active_rules:
                active_rules.append(rule)

    # Reglas del catálogo de grupos inactivos a retirar de allow
    inactive_catalog_rules: set[str] = set()
    for g, cmds in AGY_CATALOG.items():
        if g not in groups:
            for cmd in cmds:
                inactive_catalog_rules.add(f"command({cmd})")

    # Nuevo allow: conserva reglas ajenas y agrega las activas
    new_allow: list[str] = []
    for r in allow:
        if r not in inactive_catalog_rules and r not in new_allow:
            new_allow.append(r)
    for r in active_rules:
        if r not in new_allow:
            new_allow.append(r)

    # Deny: conserva existentes y asegura que los siempre negados estén
    new_deny: list[str] = list(deny)
    for cmd in ALWAYS_DENIED:
        rule = f"command({cmd})"
        if rule not in new_deny:
            new_deny.append(rule)

    perms["allow"] = new_allow
    perms["deny"] = new_deny

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def check_agy_settings_sync(
    groups: list[str],
    settings_path: Path | None = None,
    home: Path | None = None,
) -> bool:
    """Verifica si settings.json coincide con los grupos activos y las reglas denegadas."""
    path = settings_path or default_agy_settings_path(home)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        return False
    allow = set(perms.get("allow", []))
    deny = set(perms.get("deny", []))

    for g in groups:
        for cmd in AGY_CATALOG.get(g, []):
            if f"command({cmd})" not in allow:
                return False

    for g, cmds in AGY_CATALOG.items():
        if g not in groups:
            for cmd in cmds:
                if f"command({cmd})" in allow:
                    return False

    for cmd in ALWAYS_DENIED:
        if f"command({cmd})" not in deny:
            return False

    return True


def agy_prompt_hint(groups: list[str]) -> str:
    """Genera dinámicamente el prompt_hint para agy según los grupos activos."""
    cmds: list[str] = []
    for g in groups:
        for c in AGY_CATALOG.get(g, []):
            if c not in cmds:
                cmds.append(c)

    if len(cmds) > 1:
        cmds_str = ", ".join(cmds[:-1]) + f" y {cmds[-1]}"
    elif cmds:
        cmds_str = cmds[0]
    else:
        cmds_str = "ninguno"

    if "pruebas" in groups:
        test_part = "Puedes correr las pruebas tú mismo."
    else:
        test_part = "Los tests los corre la herramienta que te llamó y te devolverá los errores si fallan."

    return (
        f"En la terminal solo tienes permitidos comandos: {cmds_str} (sin pipes ni redirecciones); "
        "cualquier otro se niega. Prefiere tus herramientas de archivos: view_file, list_dir, "
        "grep_search y edición de archivos. No lances subagentes: lee tú mismo y responde en "
        f"este mismo turno. {test_part}"
    )
