"""A quién le toca cada tarea, escalamiento y respaldo cuando se agota una cuota."""

from __future__ import annotations

from datetime import datetime
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


def pick_programmer(
    cfg: dict[str, Any],
    quotas: dict[str, int | None],
    recent_status: dict[str, tuple[str, datetime] | None],
    now: datetime,
    kind: str = "feature",
) -> tuple[str, str]:
    """Decide qué programador usar según la estrategia configurada."""
    strat = cfg.get("strategy", {})
    mode = strat.get("mode", "agy-first")
    if mode == "routing":
        return cfg.get("routing", {}).get(kind, "codex"), "routing"

    first = strat.get("first", "agy")
    then = strat.get("then", "codex")
    floor = strat.get("quota_floor_pct", 15)
    master = main_name(cfg)
    agents = cfg.get("agents", {})

    def is_available(name: str) -> bool:
        if name == master or name not in agents:
            return False
        return agents[name].get("enabled", True) is not False

    # (a) first sea la maestra o no esté configurado (o deshabilitado)
    if not is_available(first):
        reason = f"{first} es la maestra" if first == master else f"{first} no disponible"
        return then, reason

    # (b) su cuota conocida esté por debajo de quota_floor_pct
    q = quotas.get(first)
    if q is not None and q < floor:
        return then, f"{first} sin cuota"

    # (c) su corrida más reciente haya terminado en cuota-agotada hace menos de 60 min
    rec = recent_status.get(first)
    if rec is not None:
        status, ts = rec
        if status == "cuota-agotada":
            if ts.tzinfo is not None and now.tzinfo is None:
                ts = ts.astimezone().replace(tzinfo=None)
            elif ts.tzinfo is None and now.tzinfo is not None:
                ts = ts.replace(tzinfo=now.tzinfo)
            diff_min = (now - ts).total_seconds() / 60
            if 0 <= diff_min < 60:
                return then, f"{first} sin cuota"

    return first, f"{first}-first"


def collect_programmer_status(
    cfg: dict[str, Any], now: datetime
) -> tuple[dict[str, int | None], dict[str, tuple[str, datetime] | None]]:
    """Recopila cuotas y estados recientes de los agentes para la estrategia."""
    from . import quota, runs
    try:
        metas = runs.recent(50)
    except Exception:
        metas = []
    quotas: dict[str, int | None] = {}
    recent_status: dict[str, tuple[str, datetime] | None] = {}
    for name in cfg.get("agents", {}):
        try:
            q = quota.get(name, cfg, metas, now)
            quotas[name] = q.get("remaining_pct")
        except Exception:
            quotas[name] = None
        latest = next((m for m in metas if m.agent == name), None)
        if latest:
            try:
                dt = datetime.fromisoformat(latest.updated_at or latest.created_at)
                recent_status[name] = (latest.status, dt)
            except Exception:
                recent_status[name] = (latest.status, now)
        else:
            recent_status[name] = None
    return quotas, recent_status


def resolve_target(
    to: str,
    kind: str,
    cfg: dict[str, Any],
    quotas: dict[str, int | None] | None = None,
    recent_status: dict[str, tuple[str, datetime] | None] | None = None,
    now: datetime | None = None,
) -> str:
    target, _ = resolve_target_with_reason(to, kind, cfg, quotas, recent_status, now)
    return target


def resolve_target_with_reason(
    to: str,
    kind: str,
    cfg: dict[str, Any],
    quotas: dict[str, int | None] | None = None,
    recent_status: dict[str, tuple[str, datetime] | None] | None = None,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    if to != "auto":
        target = to
        reason = None
    else:
        strat = cfg.get("strategy", {})
        mode = strat.get("mode", "agy-first")
        pkinds = strat.get("programmer_kinds", [])
        if mode == "agy-first" and kind in pkinds:
            now = now or datetime.now()
            if quotas is None or recent_status is None:
                q_calc, s_calc = collect_programmer_status(cfg, now)
                quotas = quotas if quotas is not None else q_calc
                recent_status = recent_status if recent_status is not None else s_calc
            target, reason = pick_programmer(cfg, quotas, recent_status, now, kind=kind)
        else:
            target = cfg["routing"][kind]
            reason = "routing"

    if target in {MAIN, main_name(cfg)}:
        raise MainSessionTask(
            f"Las tareas de tipo '{kind}' las hace la sesión principal ({main_name(cfg)}); no se delegan. "
            "Si de todos modos quieres delegarla, usa --to codex o --to agy."
        )
    if target not in cfg["agents"]:
        raise DelegateError(f"Destino desconocido: {target}. Usa un agente configurado o auto.")
    if cfg["agents"][target].get("enabled", True) is False:
        raise DelegateError(f"El agente '{target}' está desactivado.")
    return target, reason


def candidates(to: str, primary: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Con --to auto, intenta los agentes configurados en fallback_order."""
    if to != "auto":
        return [primary]
    from .config import DEFAULTS
    cfg = cfg or DEFAULTS
    return [primary] + [a for a in dict.fromkeys(cfg["fallback_order"])
                        if a != primary and a != main_name(cfg) and a in cfg["agents"]
                        and cfg["agents"][a].get("enabled", True) is not False]


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
    master = main_name(cfg)
    strat = cfg.get("strategy", {})
    default_chain = [strat.get("first", "agy"), strat.get("then", "codex"), master]
    raw_chain = cfg.get("chain", default_chain)

    try:
        idx = raw_chain.index(agent)
    except ValueError:
        return MAIN

    for candidate in raw_chain[idx + 1:]:
        if candidate in {MAIN, master}:
            continue
        if candidate in cfg.get("agents", {}) and cfg["agents"][candidate].get("enabled", True) is not False:
            return candidate

    return MAIN

