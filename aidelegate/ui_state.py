"""Estado de la oficina a partir de corridas y actividad de las IAs."""

from __future__ import annotations

import os
from datetime import datetime

from . import activity, config, quota, stats, usage
from .runs import RunMeta


def age(ts: str | None, now: datetime) -> float:
    """Devuelve segundos transcurridos; fechas inválidas cuentan como ausentes."""
    try:
        date = datetime.fromisoformat(ts or "")
        if date.tzinfo is None and now.tzinfo is not None:
            date = date.replace(tzinfo=now.tzinfo)
        elif date.tzinfo is not None and now.tzinfo is None:
            date = date.astimezone().replace(tzinfo=None)
        return (now - date).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def alive(meta: RunMeta, now: datetime) -> bool:
    """Comprueba actividad del proceso o la fecha de una corrida antigua."""
    if meta.status != "running":
        return False
    if meta.pid is None:
        return age(meta.updated_at, now) < 1800
    if meta.pid <= 0:
        return False
    try:
        os.kill(meta.pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False


def first_line(task: str, limit: int) -> str:
    """Recorta la primera línea de la tarea."""
    return (task.strip().splitlines() or [""])[0][:limit]


def character(state: str, detail: str = "", meta: RunMeta | None = None,
              since: str | None = None) -> dict:
    """Arma un estado de personaje uniforme."""
    return {"state": state, "detail": detail, "run_id": meta.run_id if meta else None,
            "since": meta.updated_at if meta else since}


def _agent(metas: list[RunMeta], now: datetime, max_fix: int) -> dict:
    latest = metas[0] if metas else None
    if latest and alive(latest, now):
        if latest.phase == "checks":
            return character("checks", "corriendo checks", latest)
        if (latest.phase_label or "").startswith("corrección"):
            return character("fixing", f"corrigiendo ({latest.fix_rounds + 1}/{max_fix})", latest)
        return character("working", first_line(latest.task, 60), latest)
    review = next((m for m in metas if m.status == "listo-para-revisar"), None)
    if review:
        return character("review", "listo, esperando revisión", review)
    if latest:
        elapsed = age(latest.updated_at, now)
        status = "interrumpido" if latest.status == "running" else latest.status
        if status == "cuota-agotada" and elapsed < 1800:
            return character("quota", "sin cuota", latest)
        if status == "integrado" and elapsed < 120:
            return character("celebrate", "¡integrado!", latest)
        if status in {"checks-fallidos", "error", "timeout", "bloqueado", "interrumpido", "sin-cambios"} and elapsed < 600:
            return character("failed", f"falló: {status}", latest)
    if not any(age(m.updated_at, now) < 900 for m in metas):
        return character("sleep")
    return character("idle")


def _main(metas: list[RunMeta], claude: dict | None, now: datetime,
            name: str = "claude", user_name: str = "usuario") -> dict:
    hook = claude or {}
    escalated = next((m for m in metas if m.status == "escalado-a-main"), None)
    if escalated:
        return character("fixing", f"terminando: {first_line(escalated.task, 50)}", escalated)
    review = next((m for m in metas if m.status == "listo-para-revisar"), None)
    if review:
        return character("reviewing", f"revisando {'-'.join(review.run_id.split('-')[-2:])}", review)
    elapsed = age(hook.get("ts"), now)
    if 0 <= elapsed < 30 and hook.get("state") in {"working", "waiting", "idle"}:
        if hook["state"] == "waiting":
            return character("waiting", f"esperando a {user_name}", since=hook.get("ts"))
        if hook["state"] == "idle":
            return character("idle", since=hook.get("ts"))
        tool = hook.get("detail") or hook.get("tool")
        return character("working", f"trabajando ({tool})" if tool else "trabajando", since=hook.get("ts"))
    session = activity.last_activity(name)
    session_ts = session.isoformat() if session else None
    if not any(m.agent == name and alive(m, now) for m in metas):
        session_age = age(session_ts, now)
        if 0 <= session_age < 20 and elapsed >= 30:
            return character("working", "trabajando", since=session_ts)
        if session_age >= 0:
            elapsed = min(elapsed, session_age)
    if hook.get("state") == "waiting" and elapsed < 600:
        return character("waiting", f"esperando a {user_name}", since=hook.get("ts"))
    return character("sleep" if elapsed > 900 else "idle")


def build_state(metas: list[RunMeta], claude: dict | None, ledger_rows: list[dict],
                now: datetime, *, max_fix_rounds: int = config.DEFAULTS["limits"]["max_fix_rounds"],
                cfg: dict | None = None) -> dict:
    """Construye el contrato v2 sin modificar las corridas."""
    cfg = cfg or config.DEFAULTS
    ordered = sorted(metas, key=lambda m: m.created_at, reverse=True)
    fields = ("run_id", "agent", "kind", "mode", "repo", "status", "phase", "phase_label",
              "created_at", "updated_at", "duration_s", "fix_rounds", "review_rounds", "diffstat")
    rows = []
    for meta in ordered:
        row = {name: getattr(meta, name) for name in fields}
        if meta.status == "running" and not alive(meta, now):
            row["status"] = "interrumpido"
        row.update(task=first_line(meta.task, 80), checks_ok=meta.last_check.get("ok") if meta.last_check else None)
        rows.append(row)
    agents = []
    master = config.main_name(cfg)
    for name, settings, role in [(master, cfg["agents"].get(master, {}), "main"),
                                  *((n, a, "agent") for n, a in cfg["agents"].items() if n != master)]:
        matching = [m for m in ordered if m.agent == name]
        if settings.get("enabled", True) is False:
            state = character("idle", "desactivado")
        elif role == "main":
            state = _main(ordered, claude if name == "claude" else None, now, name, cfg.get("user_name", config.DEFAULTS["user_name"]))
        else:
            state = _agent(matching, now, max_fix_rounds)
        color = settings.get("color", "#3a3a48")
        active = next((m for m in matching if m.run_id == state["run_id"] and alive(m, now)), None)
        if role == "main":
            fresh_hook = name == "claude" and 0 <= age((claude or {}).get("ts"), now) < 30
            subs = (claude or {}).get("subagents", []) if fresh_hook else []
        else:
            subs = active.subagents if active else []
        agents.append({"name": name, "display": settings.get("display", name), "color": color,
                       "role": role, "look": None if role == "main" or name in {"codex", "agy"}
                       else settings.get("look", {"hair": "#3a3a48", "color": color}),
                       **state, "quota": quota.get(name, cfg, ordered, now),
                       "usage": usage.get_usage(name, role, cfg, ordered, now),
                       "time": usage.get_time(name, role, cfg, ordered, now),
                       "subagents": [{"id": s["id"], "label": s["label"]} for s in subs
                                     if role != "main" or age(s.get("ts"), now) < 1800]})
    events = sorted(({**event, "id": f"{meta.run_id}:{i}", "run_id": meta.run_id}
                     for meta in ordered for i, event in enumerate(meta.events)), key=lambda e: e["ts"])[-40:]
    return {"now": now.isoformat(timespec="seconds"), "agents": agents, "events": events, "runs": rows[:30],
        "counts": {"running": sum(r["status"] == "running" for r in rows),
                   "review": sum(r["status"] == "listo-para-revisar" for r in rows),
                   "merged_today": sum(r.get("outcome") == "integrado" and
                                       str(r.get("ts", ""))[:10] == now.date().isoformat() for r in ledger_rows)},
        "stats": stats.aggregate(ledger_rows),
        "strategy": cfg.get("strategy", config.DEFAULTS.get("strategy", {})),
        "ui": cfg.get("ui", config.DEFAULTS.get("ui", {"time_mode": "auto", "fixed_hour": 12}))}
