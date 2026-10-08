"""Escalamiento unificado entre loop, cmd_escalate y cmd_feedback."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import loop, prompt, report, routing, runners, runs, stats, worktree
from .runners import AgentResult
from .runs import RunMeta
from .sanitize import sanitize


def escalate_run(
    meta: RunMeta,
    run_dir: Path,
    cfg: dict[str, Any],
    session: loop.Session | None = None,
    extra_feedback: str | None = None,
) -> AgentResult | int:
    """Escala una corrida al siguiente agente en la cadena o a la sesión principal."""
    previous = meta.agent
    nxt = routing.next_in_chain(previous, cfg)
    runs.add_event(meta, "escalated", nxt)
    stats.record(meta, "escalado")
    meta.escalated_from.append(previous)

    if session is not None:
        print(f"aviso: {previous} no lo resolvió en {meta.corrections} correcciones; pasa a {nxt}", file=sys.stderr)

    if extra_feedback:
        text = sanitize(extra_feedback, source="el feedback", mask_personal=False)
        meta.feedback.append(text)
        runs.add_event(meta, "feedback")

    if nxt == routing.MAIN:
        meta.agent, meta.status = routing.MAIN, "escalado-a-main"
        meta.model, meta.effort = "", ""
        runs.add_event(meta, "assigned", previous)
        runs.save(meta, run_dir)
        where = f"{report.short(meta.worktree)} (rama {meta.branch})" if meta.worktree else meta.workdir
        print(f"Te toca a ti (sesión principal). Trabaja en: {where}")
        print(f"Cuando termines: ai-delegate merge {meta.run_id}")
        if session is not None:
            return AgentResult(exit_code=3)
        return 3

    meta.agent, meta.thread_id, meta.review_rounds, meta.fix_rounds = nxt, None, 0, 0
    runs.add_event(meta, "assigned", previous)
    if meta.worktree and Path(meta.worktree).exists():
        meta.diffstat = worktree.diffstat_line(Path(meta.worktree), meta.base_commit or "HEAD")
    design = prompt.load_design_spec(meta)
    esc_text = prompt.compose_escalation(meta.task, previous, meta.feedback, meta.diffstat or "", design)
    if meta.acceptance_criteria:
        esc_text += "\n## Criterios de aceptación (se verificarán automáticamente)\n" + "\n".join(meta.acceptance_criteria) + "\nAntes de entregar, verifica cada criterio; si puedes correr comandos, córrelos.\n"
    prompt_text = sanitize(esc_text, source="el prompt de escalamiento", mask_personal=False)

    if session is not None:
        session.runner = runners.get(nxt, cfg, kind=meta.kind)
        meta.model, meta.effort = session.runner.model, session.runner.effort
        session.runner.ensure_available()
        return loop.agent_round(session, prompt_text, "escalamiento")

    meta.status = "running"
    runner = runners.get(nxt, cfg, kind=meta.kind)
    meta.model, meta.effort = runner.model, runner.effort
    runner.ensure_available()
    sess = loop.Session(
        meta=meta,
        run_dir=run_dir,
        runner=runner,
        timeout_s=cfg["limits"]["timeout_min"] * 60,
        check_timeout_s=cfg["limits"]["check_timeout_min"] * 60,
        max_fix_rounds=cfg["limits"]["max_fix_rounds"],
        escalate_after=cfg.get("strategy", {}).get("escalate_after", 3),
        cfg=cfg,
    )
    loop.drive(sess, prompt_text, "escalamiento")
    report.print_run(meta, run_dir, cfg["limits"]["summary_lines"])
    return 0 if meta.status in {"ok", "listo-para-revisar"} else 1
