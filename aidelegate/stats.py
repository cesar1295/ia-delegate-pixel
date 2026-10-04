"""Bitácora de resultados por agente y tipo de tarea (sobrevive a la limpieza de corridas)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from . import config
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


def table() -> str:
    path = config.ledger_path()
    if not path.exists():
        return "Todavía no hay corridas cerradas (integradas, descartadas o escaladas)."
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for line in path.read_text().splitlines():
        entry = json.loads(line)
        row = groups[(entry["agent"], entry["kind"])]
        row["total"] += 1
        row[entry["outcome"]] += 1
        if entry["outcome"] == "integrado" and entry["review_rounds"] == 0:
            row["primera"] += 1
    return _render(groups)


def _render(groups: dict[tuple[str, str], dict[str, int]]) -> str:
    lines = [f"{'agente':<7} {'tipo':<10} {'total':>5} {'integr':>6} {'1ª vez':>7} {'descart':>7} {'escal':>5}"]
    for (agent, kind), row in sorted(groups.items()):
        first = f"{100 * row['primera'] // row['total']}%"
        lines.append(
            f"{agent:<7} {kind:<10} {row['total']:>5} {row['integrado']:>6} {first:>7} "
            f"{row['descartado']:>7} {row['escalado']:>5}"
        )
    return "\n".join(lines)
