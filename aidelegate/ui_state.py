"""Estado de la oficina a partir de corridas y actividad de Claude."""

from __future__ import annotations

import os
from datetime import datetime

from . import config, stats
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
        if status in {"checks-fallidos", "error", "timeout", "bloqueado", "interrumpido"} and elapsed < 600:
            return character("failed", f"falló: {status}", latest)
    if not any(age(m.updated_at, now) < 900 for m in metas):
        return character("sleep")
    return character("idle")


def _claude(metas: list[RunMeta], claude: dict | None, now: datetime) -> dict:
    activity = claude or {}
    escalated = next((m for m in metas if m.status == "escalado-a-main"), None)
    if escalated:
        return character("fixing", f"terminando: {first_line(escalated.task, 50)}", escalated)
    elapsed = age(activity.get("ts"), now)
    if activity.get("state") == "working" and elapsed < 30:
        tool = activity.get("detail") or activity.get("tool")
        return character("working", f"trabajando ({tool})" if tool else "trabajando", since=activity.get("ts"))
    review = next((m for m in metas if m.status == "listo-para-revisar"), None)
    if review:
        return character("reviewing", f"revisando {'-'.join(review.run_id.split('-')[-2:])}", review)
    if activity.get("state") == "waiting" and elapsed < 600:
        return character("waiting", "esperando a Alex", since=activity.get("ts"))
    return character("sleep" if elapsed > 900 else "idle")


def build_state(metas: list[RunMeta], claude: dict | None, ledger_rows: list[dict],
                now: datetime, *, max_fix_rounds: int = config.DEFAULTS["limits"]["max_fix_rounds"]) -> dict:
    """Construye el estado sin modificar las corridas ni leer archivos."""
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
    return {"now": now.isoformat(timespec="seconds"), "agents": {
        "claude": _claude(ordered, claude, now),
        **{agent: _agent([m for m in ordered if m.agent == agent], now, max_fix_rounds)
           for agent in ("codex", "agy")}}, "runs": rows[:30],
        "counts": {"running": sum(r["status"] == "running" for r in rows),
                   "review": sum(r["status"] == "listo-para-revisar" for r in rows),
                   "merged_today": sum(r.get("outcome") == "integrado" and
                                       str(r.get("ts", ""))[:10] == now.date().isoformat() for r in ledger_rows)},
        "stats": stats.aggregate(ledger_rows)}
