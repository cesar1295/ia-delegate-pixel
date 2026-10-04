"""Registro de runners por destino."""

from __future__ import annotations

from typing import Any

from ..errors import DelegateError
from .agy import AgyRunner
from .base import AgentResult, Runner
from .codex import CodexRunner

_RUNNERS: dict[str, type[Runner]] = {"codex": CodexRunner, "agy": AgyRunner}

__all__ = ["AgentResult", "Runner", "get"]


def get(name: str, cfg: dict[str, Any], model: str | None = None) -> Runner:
    if name not in _RUNNERS:
        raise DelegateError(f"No hay runner para '{name}'. Destinos válidos: {', '.join(_RUNNERS)}")
    agent_cfg = cfg["agents"].get(name, {})
    return _RUNNERS[name](
        binary=agent_cfg.get("bin", name),
        home=agent_cfg.get("home", ""),
        model=model or agent_cfg.get("model", ""),
    )
