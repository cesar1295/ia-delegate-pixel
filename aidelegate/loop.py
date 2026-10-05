"""Ciclo de una corrida: agente → checks → corrección automática → estado final."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from . import acceptance, visual, prereview, checks, config, escalation, prompt, report, routing, runners, runs, stats, summary, usage, worktree
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
    escalate_after: int = 3
    cfg: dict | None = None


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
    cfg = session.cfg or config.load()
    escalate_after = session.escalate_after

    while meta.status != "sin-cambios" and result.ok and meta.mode == "write":
        failure = ""
        if meta.check_cmd:
            meta.phase = "checks"
            runs.save(meta, session.run_dir)
            check = checks.run(meta.check_cmd, Path(meta.workdir), session.check_timeout_s)
            meta.last_check = {"cmd": meta.check_cmd, "ok": check.ok, "exit_code": check.exit_code}
            runs.write_text(session.run_dir, "checks.log", sanitize(check.output, source="la salida de los checks", on_secret="redact"))
            if not check.ok:
                failure = prompt.compose_check_failure(meta.check_cmd, sanitize(check.output, source="la salida de los checks", on_secret="redact"))
        if not failure:
            meta.phase = "aceptacion"
            runs.save(meta, session.run_dir)
            meta.acceptance, output = acceptance.evaluate(meta.acceptance_criteria, Path(meta.workdir), session.check_timeout_s)
            runs.write_text(session.run_dir, "acceptance.log", output)
            if meta.acceptance["failed"]:
                failure = "Los criterios de aceptación fallaron; corrígelos:\n" + "\n".join(meta.acceptance["failed"]) + "\n\nSalida de aceptación:\n" + output
        if not failure:
            meta.phase = "vista"
            runs.save(meta, session.run_dir)
            meta.visual = visual.run(meta, session.run_dir, cfg)
            runs.write_text(session.run_dir, "visual.log", str(meta.visual))
            if meta.visual["status"] == "fallo":
                failure = "La revisión visual falló; corrige estos errores:\n" + meta.visual["note"]
        review_failure = False
        if not failure and cfg.get("review", {}).get("enabled", True) and not meta.no_review:
            meta.phase = "pre-revision"
            runs.save(meta, session.run_dir)
            meta.prereview, blocked, reviewer = prereview.run(meta, session.run_dir, cfg, session.timeout_s)
            if reviewer:
                meta.duration_s = round(meta.duration_s + reviewer.duration_s, 1)
                ts = datetime.now().isoformat(timespec="seconds")
                meta.history.append({"label": "pre-revisión", "agent": meta.prereview["agent"],
                                     "exit_code": reviewer.exit_code, "seconds": round(reviewer.duration_s, 1),
                                     "ts": ts, "usage": reviewer.usage, "error": reviewer.error or None})
                usage.record_work_round(meta.prereview["agent"], reviewer.duration_s, meta.kind, meta.repo, meta.run_id, ts=ts)
            if blocked and meta.prereview["rounds"] < cfg.get("review", {}).get("max_rounds", 2) and meta.corrections < escalate_after:
                review_failure = True
                failure = "La pre-revisión automática encontró estos problemas; corrígelos:\n" + "\n".join(blocked)
        if not failure:
            break
        if not review_failure and fixes > 0 and meta.corrections >= escalate_after:
            meta.feedback.append(failure)
            result = escalation.escalate_run(meta, session.run_dir, cfg, session=session)
            if meta.status == "escalado-a-main":
                break
            fixes = 0
            continue
        if fixes >= session.max_fix_rounds:
            meta.status = "checks-fallidos"
            break
        fixes += 1
        result = agent_round(session, failure, f"corrección {fixes}")
        meta.fix_rounds += 1

    if meta.status not in {"sin-cambios", "escalado-a-main"}:
        meta.status = final_status(meta, result)
    if meta.worktree and meta.mode == "write" and Path(meta.worktree).exists():
        meta.diffstat = worktree.diffstat_line(Path(meta.worktree), meta.base_commit or "HEAD")
    if meta.status != "escalado-a-main":
        runs.add_event(meta, "delivered" if meta.status in {"ok", "listo-para-revisar"} else "failed",
                       "" if meta.status in {"ok", "listo-para-revisar"} else
                       "sin cambios" if meta.status == "sin-cambios" else meta.status)
    runs.save(meta, session.run_dir)
    return result


DENIED_PREFIX = "agy no respondió: le negaron permisos"
MAX_PERMISSION_RETRIES = 2
PERMISSION_NUDGE = (
    "Ese comando o lectura no está permitido en este modo y se canceló. No ejecutes comandos de terminal salvo "
    "los de lectura permitidos y no leas fuera del directorio de trabajo; usa view_file, list_dir, grep_search y "
    "edición de archivos, y continúa la tarea donde ibas."
)


def _run_with_permission_retries(session: Session, text: str, progress) -> AgentResult:
    """Sin interfaz, un permiso negado termina el turno de agy en blanco: se retoma la conversación."""
    meta = session.meta
    result = session.runner.run(text, meta.mode, Path(meta.workdir), meta.thread_id,
                                session.timeout_s, session.run_dir, on_progress=progress)
    for _ in range(MAX_PERMISSION_RETRIES):
        if not (result.error.startswith(DENIED_PREFIX) and result.thread_id):
            break
        retry_ts = datetime.now().isoformat(timespec="seconds")
        meta.history.append({
            "label": "reintento permisos", "agent": meta.agent, "exit_code": result.exit_code,
            "seconds": round(result.duration_s, 1), "ts": retry_ts, "usage": result.usage, "error": result.error,
        })
        usage.record_work_round(meta.agent, result.duration_s, meta.kind, meta.repo, meta.run_id, ts=retry_ts)
        runs.append_prompt(session.run_dir, PERMISSION_NUDGE, f"reintento permisos → {meta.agent}")
        elapsed = result.duration_s
        result = session.runner.run(PERMISSION_NUDGE, meta.mode, Path(meta.workdir), result.thread_id,
                                    session.timeout_s, session.run_dir, on_progress=progress)
        result.duration_s += elapsed
    return result


def agent_round(session: Session, text: str, label: str) -> AgentResult:
    meta, run_dir = session.meta, session.run_dir
    before = diff_hash(meta) if label != "tarea" else None
    if label != "tarea" and not session.runner.supports_resume:
        text = f"Tarea original:\n{meta.task}\n\n" + text
    meta.phase, meta.phase_label, meta.pid = "agente", label, os.getpid()
    meta.phase_started_at = datetime.now().isoformat(timespec="seconds")
    runs.save(meta, run_dir)
    runs.append_prompt(run_dir, text, f"{label} → {meta.agent}")

    def progress(result: AgentResult) -> None:
        meta.subagents = [dict(s) for s in result.subagents]
        runs.save(meta, run_dir)

    try:
        result = _run_with_permission_retries(session, text, progress)
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
    ts = datetime.now().isoformat(timespec="seconds")
    meta.history.append({
        "label": label, "agent": meta.agent, "exit_code": result.exit_code,
        "seconds": round(result.duration_s, 1), "ts": ts,
        "usage": result.usage, "error": result.error or None,
    })
    usage.record_work_round(meta.agent, result.duration_s, meta.kind, meta.repo, meta.run_id, ts=ts)
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
    if (meta.last_check and not meta.last_check["ok"]) or (meta.acceptance and meta.acceptance["failed"]) or (meta.visual and meta.visual["status"] == "fallo"):
        return "checks-fallidos"
    return "listo-para-revisar"


def diff_hash(meta: RunMeta) -> str | None:
    if meta.worktree and Path(meta.worktree).exists():
        return hashlib.sha256(worktree.diff(Path(meta.worktree), meta.base_commit or "HEAD").encode()).hexdigest()
    return None
