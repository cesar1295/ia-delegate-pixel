"""Registro de runners por destino."""

from __future__ import annotations

from typing import Any

from ..errors import DelegateError
from .agy import AgyRunner
from .base import AgentResult, Runner
from .claude import ClaudeRunner
from .codex import CodexRunner
from .generic import GenericRunner

_RUNNERS: dict[str, type[Runner]] = {"claude": ClaudeRunner, "codex": CodexRunner, "agy": AgyRunner, "generic": GenericRunner}

__all__ = ["AgentResult", "Runner", "get"]


def get(name: str, cfg: dict[str, Any], model: str | None = None, effort: str | None = None,
        *, kind: str = "") -> Runner:
    agent_cfg = cfg["agents"].get(name)
    if agent_cfg is None:
        raise DelegateError(f"Agente desconocido: {name}")
    runner_kind = agent_cfg.get("type", name)
    if runner_kind not in _RUNNERS:
        raise DelegateError(f"Tipo de runner desconocido: {runner_kind}")
    binary = agent_cfg.get("bin", name)
    if binary == "auto":
        from ..detect import detect_all
        detected = detect_all().get(runner_kind)
        if not detected or not detected.path:
            raise DelegateError(f"No encuentro el binario de {name}")
        binary = detected.path
    from ..models import resolve
    chosen_model, chosen_effort = resolve(name, kind or cfg.get("_task_kind", ""), cfg, model or "", effort or "")
    runner = _RUNNERS[runner_kind](binary=binary, home=agent_cfg.get("home", ""),
                            model=chosen_model, effort=chosen_effort)
    runner.name = name
    if isinstance(runner, GenericRunner):
        runner.args = agent_cfg.get("args", [])
    from ..permissions import get_effective_permissions
    perms = get_effective_permissions(agent_cfg, runner_kind)
    runner.permissions = perms
    runner.edit = perms.get("edit", True)
    runner.network = perms.get("network", False)
    runner.groups = perms.get("groups", ["lectura"])
    return runner
