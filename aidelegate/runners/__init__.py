"""Registro de runners por destino."""

from __future__ import annotations

from typing import Any

from ..errors import DelegateError
from .agy import AgyRunner
from .base import AgentResult, Runner
from .codex import CodexRunner
from .generic import GenericRunner

_RUNNERS: dict[str, type[Runner]] = {"codex": CodexRunner, "agy": AgyRunner, "generic": GenericRunner}

__all__ = ["AgentResult", "Runner", "get"]


def get(name: str, cfg: dict[str, Any], model: str | None = None) -> Runner:
    agent_cfg = cfg["agents"].get(name)
    if agent_cfg is None:
        raise DelegateError(f"Agente desconocido: {name}")
    kind = agent_cfg.get("type", name)
    if kind not in _RUNNERS:
        raise DelegateError(f"Tipo de runner desconocido: {kind}")
    runner = _RUNNERS[kind](binary=agent_cfg.get("bin", name), home=agent_cfg.get("home", ""),
                            model=model or agent_cfg.get("model", ""))
    runner.name = name
    if isinstance(runner, GenericRunner):
        runner.args = agent_cfg.get("args", [])
    return runner
