"""Ciclo de una corrida: agente → checks → corrección automática → estado final."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import checks, prompt, runs, summary, worktree
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
    except BaseException as exc:
        session.meta.status = "interrumpido" if isinstance(exc, KeyboardInterrupt) else "error"
        session.meta.error = str(exc)
        runs.add_event(session.meta, "failed", session.meta.status)
        raise
    finally:
        session.meta.phase = None
        runs.save(session.meta, session.run_dir)


def _drive(session: Session, text: str, label: str) -> AgentResult:
    """Corre una ronda del agente y, en modo escritura, los checks con sus correcciones."""
    meta = session.meta
    result = agent_round(session, text, label)
    fixes = 0
    while meta.status != "sin-cambios" and result.ok and meta.mode == "write" and meta.check_cmd:
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
    if meta.status != "sin-cambios":
        meta.status = final_status(meta, result)
    if meta.worktree and meta.mode == "write":
        meta.diffstat = worktree.diffstat_line(Path(meta.worktree), meta.base_commit or "HEAD")
    runs.add_event(meta, "delivered" if meta.status in {"ok", "listo-para-revisar"} else "failed",
                   "" if meta.status in {"ok", "listo-para-revisar"} else
                   "sin cambios" if meta.status == "sin-cambios" else meta.status)
    runs.save(meta, session.run_dir)
    return result


def agent_round(session: Session, text: str, label: str) -> AgentResult:
    meta, run_dir = session.meta, session.run_dir
    before = diff_hash(meta) if label != "tarea" else None
    if label != "tarea" and not session.runner.supports_resume:
        text = f"Tarea original:\n{meta.task}\n\n" + text
    meta.phase, meta.phase_label, meta.pid = "agente", label, os.getpid()
    runs.save(meta, run_dir)
    runs.append_prompt(run_dir, text, f"{label} → {meta.agent}")

    def progress(result: AgentResult) -> None:
        meta.subagents = [dict(s) for s in result.subagents]
        runs.save(meta, run_dir)

    try:
        result = session.runner.run(text, meta.mode, Path(meta.workdir), meta.thread_id,
                                   session.timeout_s, run_dir, on_progress=progress)
    finally:
        meta.subagents = []
        runs.save(meta, run_dir)
    if before is not None and before == diff_hash(meta):
        meta.status = "sin-cambios"
    meta.thread_id = result.thread_id or meta.thread_id
    meta.exit_code = result.exit_code
    meta.duration_s = round(meta.duration_s + result.duration_s, 1)
    meta.error = result.error or None
    if summary.looks_garbled(result.last_message):
        meta.error = (meta.error + "; " if meta.error else "") + "resumen ilegible: revisa el diff antes de confiar"
    meta.history.append({
        "label": label, "agent": meta.agent, "exit_code": result.exit_code,
        "seconds": round(result.duration_s, 1), "ts": datetime.now().isoformat(timespec="seconds"),
        "usage": result.usage, "error": result.error or None,
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


def diff_hash(meta: RunMeta) -> str | None:
    if meta.worktree and Path(meta.worktree).exists():
        return hashlib.sha256(worktree.diff(Path(meta.worktree), meta.base_commit or "HEAD").encode()).hexdigest()
    return None
