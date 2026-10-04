"""Ciclo de una corrida: agente → checks → corrección automática → estado final."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import checks, prompt, runs, worktree
from .runners import AgentResult, Runner
from .runs import RunMeta
from .sanitize import sanitize


@dataclass
class Session:
    meta: RunMeta
    run_dir: Path
    runner: Runner
    timeout_s: int
    check_timeout_s: int
    max_fix_rounds: int


def drive(session: Session, text: str, label: str) -> AgentResult:
    """Publica las fases y limpia la fase incluso ante errores."""
    try:
        return _drive(session, text, label)
    finally:
        session.meta.phase = None
        runs.save(session.meta, session.run_dir)


def _drive(session: Session, text: str, label: str) -> AgentResult:
    """Corre una ronda del agente y, en modo escritura, los checks con sus correcciones."""
    meta = session.meta
    result = agent_round(session, text, label)
    fixes = 0
    while result.ok and meta.mode == "write" and meta.check_cmd:
        meta.phase = "checks"
        runs.save(meta, session.run_dir)
        check = checks.run(meta.check_cmd, Path(meta.workdir), session.check_timeout_s)
        meta.last_check = {"cmd": meta.check_cmd, "ok": check.ok, "exit_code": check.exit_code}
        runs.write_text(session.run_dir, "checks.log", check.output)
        if check.ok or fixes >= session.max_fix_rounds:
            break
        fixes += 1
        output = sanitize(check.output, source="la salida de los checks", on_secret="redact")
        result = agent_round(session, prompt.compose_check_failure(meta.check_cmd, output), f"corrección {fixes}")
        meta.fix_rounds += 1
    meta.status = final_status(meta, result)
    if meta.worktree and meta.mode == "write":
        meta.diffstat = worktree.diffstat_line(Path(meta.worktree), meta.base_commit or "HEAD")
    runs.save(meta, session.run_dir)
    return result


def agent_round(session: Session, text: str, label: str) -> AgentResult:
    meta, run_dir = session.meta, session.run_dir
    meta.phase, meta.phase_label, meta.pid = "agente", label, os.getpid()
    runs.save(meta, run_dir)
    runs.append_prompt(run_dir, text, f"{label} → {meta.agent}")
    result = session.runner.run(text, meta.mode, Path(meta.workdir), meta.thread_id, session.timeout_s, run_dir)
    meta.thread_id = result.thread_id or meta.thread_id
    meta.exit_code = result.exit_code
    meta.duration_s = round(meta.duration_s + result.duration_s, 1)
    meta.error = result.error or None
    meta.history.append({
        "label": label, "agent": meta.agent, "exit_code": result.exit_code,
        "seconds": round(result.duration_s, 1), "usage": result.usage, "error": result.error or None,
    })
    runs.write_text(run_dir, "last.md", result.last_message)
    runs.save(meta, run_dir)
    return result


def final_status(meta: RunMeta, result: AgentResult) -> str:
    if result.timed_out:
        return "timeout"
    if result.quota_exhausted:
        return "cuota-agotada"
    if not result.ok:
        return "error"
    if meta.mode == "read":
        return "ok"
    if meta.last_check and not meta.last_check["ok"]:
        return "checks-fallidos"
    return "listo-para-revisar"
