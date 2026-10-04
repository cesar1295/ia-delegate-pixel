"""A quién le toca cada tarea, escalamiento y respaldo cuando se agota una cuota."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from .config import main_name
from .errors import DelegateError, MainSessionTask

MAIN = "main"
T = TypeVar("T")


def kinds(cfg: dict[str, Any]) -> list[str]:
    return sorted(cfg["routing"])


def validate_kind(kind: str | None, cfg: dict[str, Any]) -> str:
    kind = kind or cfg["default_kind"]
    if kind not in cfg["routing"]:
        raise DelegateError(f"Tipo de tarea desconocido: {kind}. Usa uno de: {', '.join(kinds(cfg))}")
    return kind


def default_mode(kind: str, cfg: dict[str, Any]) -> str:
    return "read" if kind in cfg["read_kinds"] else "write"


def resolve_target(to: str, kind: str, cfg: dict[str, Any]) -> str:
    target = cfg["routing"][kind] if to == "auto" else to
    if target in {MAIN, main_name(cfg)}:
        raise MainSessionTask(
            f"Las tareas de tipo '{kind}' las hace la sesión principal ({main_name(cfg)}); no se delegan. "
            "Si de todos modos quieres delegarla, usa --to codex o --to agy."
        )
    if target not in cfg["agents"]:
        raise DelegateError(f"Destino desconocido: {target}. Usa un agente configurado o auto.")
    return target


def candidates(to: str, primary: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Con --to auto, intenta los agentes configurados en fallback_order."""
    if to != "auto":
        return [primary]
    from .config import DEFAULTS
    cfg = cfg or DEFAULTS
    return [primary] + [a for a in dict.fromkeys(cfg["fallback_order"])
                        if a != primary and a != main_name(cfg) and a in cfg["agents"]]


def run_with_fallback(
    names: list[str], attempt: Callable[[str], T], exhausted: Callable[[T], bool]
) -> tuple[str, T]:
    if not names:
        raise DelegateError("No hay agentes disponibles para intentar.")
    for name in names:
        result = attempt(name)
        if not exhausted(result):
            return name, result
    return name, result


def next_in_chain(agent: str, cfg: dict[str, Any]) -> str:
    chain = [a for a in cfg["chain"] if a not in {MAIN, main_name(cfg)}] + [MAIN]
    if agent not in chain or chain.index(agent) == len(chain) - 1:
        return MAIN
    return chain[chain.index(agent) + 1]
