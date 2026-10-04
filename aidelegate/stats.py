"""Bitácora de resultados por agente y tipo de tarea (sobrevive a la limpieza de corridas)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from . import config, runs, usage
from .runs import RunMeta

OUTCOMES = ("integrado", "descartado", "escalado")


def record(meta: RunMeta, outcome: str) -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "agent": meta.agent, "kind": meta.kind, "repo": meta.repo, "outcome": outcome,
        "fix_rounds": meta.fix_rounds, "review_rounds": meta.review_rounds,
    }
    path = config.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def time_table(cfg: dict | None = None, metas: list[RunMeta] | None = None,
               now: datetime | None = None) -> str:
    """Tabla de tiempo de desarrollo y tokens por IA."""
    if cfg is None:
        try:
            cfg = config.load()
        except Exception:
            cfg = config.DEFAULTS
    master = config.main_name(cfg)
    agents_map = cfg.get("agents", {})
    agent_names = [master] + [n for n in agents_map if n != master] if master in agents_map else list(agents_map)
    metas = runs.recent(1_000_000) if metas is None else metas
    now = now or datetime.now()

    lines = [f"{'IA':<8} | {'hoy':<12} | {'semana':<14} | {'total':<14} | {'tokens hoy'}"]
    for name in agent_names:
        role = "main" if name == master else "agent"
        u = usage.get_usage(name, role, cfg, metas, now)
        t = usage.get_time(name, role, cfg, metas, now)
        today_val = t.get("today_s") if t else None
        week_val = t.get("week_s") if t else None
        total_val = t.get("total_s") if t else None
        tokens_val = u.get("tokens_today") if u else None

        hoy_str = usage.format_time(today_val) if today_val is not None else "sin dato"
        semana_str = usage.format_time(week_val) if week_val is not None else "sin dato"
        total_str = usage.format_time(total_val) if total_val is not None else "sin dato"
        tokens_str = usage.format_tokens(tokens_val) if tokens_val is not None else "sin dato"

        lines.append(f"{name:<8} | {hoy_str:<12} | {semana_str:<14} | {total_str:<14} | {tokens_str}")

    return "\n".join(lines)


def table(cfg: dict | None = None) -> str:
    path = config.ledger_path()
    t1 = _render(_groups(read_rows())) if (path.exists() and read_rows()) else "Todavía no hay corridas cerradas (integradas, descartadas o escaladas)."
    t2 = time_table(cfg)
    return f"{t1}\n\ntiempo:\n{t2}"


def read_rows() -> list[dict]:
    """Lee la bitácora de resultados."""
    path = config.ledger_path()
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _groups(entries: list[dict]) -> dict[tuple[str, str], dict[str, int]]:
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in entries:
        row = groups[(entry["agent"], entry["kind"])]
        row["total"] += 1
        row[entry["outcome"]] += 1
        if entry["outcome"] == "integrado" and entry.get("review_rounds", 0) == 0:
            row["primera"] += 1
    return groups


def aggregate(entries: list[dict]) -> list[dict]:
    """Calcula estadísticas sin renderizar ni leer archivos."""
    return [{"agent": agent, "kind": kind, "total": row["total"],
             "integrado": row["integrado"], "primera_pct": 100 * row["primera"] // row["total"],
             "descartado": row["descartado"], "escalado": row["escalado"]}
            for (agent, kind), row in sorted(_groups(entries).items())]


def _render(groups: dict[tuple[str, str], dict[str, int]]) -> str:
    lines = [f"{'agente':<7} {'tipo':<10} {'total':>5} {'integr':>6} {'1ª vez':>7} {'descart':>7} {'escal':>5}"]
    for (agent, kind), row in sorted(groups.items()):
        first = f"{100 * row['primera'] // row['total']}%"
        lines.append(
            f"{agent:<7} {kind:<10} {row['total']:>5} {row['integrado']:>6} {first:>7} "
            f"{row['descartado']:>7} {row['escalado']:>5}"
        )
    return "\n".join(lines)
