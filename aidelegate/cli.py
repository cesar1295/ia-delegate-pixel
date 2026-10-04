"""Comandos de ai-delegate."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import checks, config, loop, prompt, report, routing, runners, runs, stats, worktree
from .args import parse, parse_duration
from .errors import DelegateError, SecretFound
from .runners import AgentResult, Runner
from .runs import RunMeta
from .sanitize import sanitize

SUCCESS = {"ok", "listo-para-revisar", "dry-run"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "claude-status":
        from .claude_status import main as status_main
        return status_main(argv[1:])
    args = parse(argv)
    try:
        if args.command == "doctor":
            from .install import doctor
            return doctor(args)
        try:
            cfg = config.load()
        except DelegateError:
            if args.command != "setup":
                raise
            import copy
            cfg = copy.deepcopy(config.DEFAULTS)
        if args.command in {"setup", "master"}:
            from . import install
            return getattr(install, args.command)(args, cfg)
        return COMMANDS[args.command](args, cfg)
    except DelegateError as exc:
        print(f"ai-delegate: {exc}", file=sys.stderr)
        return exc.exit_code


# --- run ---------------------------------------------------------------------

def cmd_run(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    runs.cleanup_old(cfg["limits"]["keep_days"])
    task = _read_task(args)
    kind = routing.validate_kind(args.kind, cfg)
    _require_design_spec(args, kind, cfg)
    mode = args.mode or routing.default_mode(kind, cfg)
    agent = routing.resolve_target(args.to, kind, cfg)
    runner = runners.get(agent, cfg, args.model)
    if args.print_env:
        print("\n".join(sorted(runner.env())))
        return 0
    source = _existing_dir(args.dir)
    if not args.dry_run:
        runner.ensure_available()
    root = worktree.repo_root(source)
    # En disco y hacia el agente solo va la versión limpia de la tarea.
    safe_task = sanitize(task, source="la tarea", on_secret="redact")
    meta = _new_meta(agent, mode, kind, safe_task, source, root, args.resume)
    run_dir = runs.create(meta)
    try:
        sanitize(task, source="la tarea")  # bloquea si trae secretos
        return _execute(args, cfg, meta, run_dir, runner)
    except BaseException as exc:
        _record_failure(meta, run_dir, exc)
        raise


def _execute(args: argparse.Namespace, cfg: dict[str, Any], meta: RunMeta, run_dir: Path, runner: Runner) -> int:
    source, root = Path(meta.source_dir), worktree.repo_root(Path(meta.source_dir))
    spec = _prompt_spec(args, meta, source)
    sanitize(prompt.compose(spec), source="el prompt")  # bloquea antes de crear nada
    if meta.mode == "write":
        meta.check_cmd = checks.resolve(args.check, source, root or source, cfg)
    use_worktree = _wants_worktree(args, meta, root)
    if args.dry_run:
        text = prompt.compose(replace(spec, agent_hint=runner.prompt_hint))
        return _dry_run(meta, run_dir, runner, text, use_worktree)
    if use_worktree and root:
        _attach_worktree(meta, run_dir, root, source)
    spec = replace(spec, directory=Path(meta.workdir))
    runs.add_event(meta, "assigned")
    session = _session(meta, run_dir, cfg, runner, args.timeout, args.max_fix_rounds)
    routing.run_with_fallback(
        routing.candidates(args.to, meta.agent, cfg),
        lambda name: _attempt(session, cfg, args.model, name, spec),
        lambda res: res.quota_exhausted,
    )
    report.print_run(meta, run_dir, cfg["limits"]["summary_lines"])
    return 0 if meta.status in SUCCESS else 1


def _attempt(session: loop.Session, cfg: dict[str, Any], model: str | None, name: str,
             spec: prompt.PromptSpec) -> AgentResult:
    meta = session.meta
    if name != meta.agent:
        print(f"aviso: {meta.agent} agotó su cuota; reintentando con {name}", file=sys.stderr)
        session.runner = runners.get(name, cfg, model)
        session.runner.ensure_available()
        meta.fallback_from, meta.agent, meta.thread_id = meta.agent, name, None
        runs.add_event(meta, "assigned", meta.fallback_from)
    text = prompt.compose(replace(spec, agent_hint=session.runner.prompt_hint))
    return loop.drive(session, sanitize(text, source="el prompt"), "tarea")


def _new_meta(agent: str, mode: str, kind: str, task: str, source: Path, root: Path | None, resume: str | None) -> RunMeta:
    repo = (root or source).name
    return RunMeta(
        run_id=runs.new_run_id(repo, agent), agent=agent, mode=mode, kind=kind, repo=repo,
        source_dir=str(source), workdir=str(source), task=task,
        project_root=str(root) if root else None, thread_id=resume,
    )


def _prompt_spec(args: argparse.Namespace, meta: RunMeta, source: Path) -> prompt.PromptSpec:
    issue = prompt.fetch_issue(args.issue, source) if args.issue else None
    context = prompt.read_context_file(Path(args.context_file).expanduser()) if args.context_file else None
    design = None
    if args.design_spec:
        path = Path(args.design_spec).expanduser().resolve()
        design, meta.design_spec_path = prompt.read_context_file(path), str(path)
    return prompt.PromptSpec(meta.task, meta.mode, source, meta.kind, issue, context, design_spec=design)


def _require_design_spec(args: argparse.Namespace, kind: str, cfg: dict[str, Any]) -> None:
    if kind in cfg["spec_required_kinds"] and not args.design_spec:
        raise DelegateError(
            f"Las tareas '{kind}' necesitan la especificación de diseño de la sesión principal: "
            "escríbela (plantilla en ~/Documentos/Proyectos/ai-delegate/templates/design-spec.md) "
            "y pásala con --design-spec <archivo>."
        )


def _wants_worktree(args: argparse.Namespace, meta: RunMeta, root: Path | None) -> bool:
    if args.worktree is False or (meta.mode == "read" and not args.worktree):
        return False
    if root is None:
        if args.worktree:
            raise DelegateError(
                f"{meta.source_dir} no es un repo git; --worktree necesita git "
                "('git init' y un primer commit) o usa --no-worktree."
            )
        print(f"aviso: {meta.source_dir} no es un repo git; el agente trabajará directo ahí.", file=sys.stderr)
        return False
    return True


def _attach_worktree(meta: RunMeta, run_dir: Path, root: Path, source: Path) -> None:
    wt = worktree.create(root, meta.run_id)
    meta.worktree, meta.branch = str(wt.path), wt.branch
    meta.base_commit, meta.base_branch = wt.base_commit, wt.base_branch
    meta.workdir = str(wt.path / source.relative_to(root))
    runs.save(meta, run_dir)
    if wt.dirty_base:
        print("aviso: tu copia tiene cambios sin commit; el worktree parte del último commit.", file=sys.stderr)


def _dry_run(meta: RunMeta, run_dir: Path, runner: Runner, text: str, use_worktree: bool) -> int:
    runs.append_prompt(run_dir, text, f"dry-run → {meta.agent}")
    argv = runner.argv("<prompt>", meta.mode, Path(meta.workdir), meta.thread_id)
    meta.status = "dry-run"
    runs.save(meta, run_dir)
    print(f"[dry-run] {meta.agent} | {meta.mode} | {meta.kind} | {meta.repo}")
    print(f"[dry-run] comando: {' '.join(argv)}  (prompt de {len(text)} caracteres)")
    print(f"[dry-run] variables heredadas: {', '.join(sorted(runner.env()))}")
    where = f"rama ai/{meta.run_id}" if use_worktree else "directo en la carpeta"
    print(f"[dry-run] trabajo: {where}")
    print(f"[dry-run] checks: {meta.check_cmd or 'ninguno'}")
    print(f"[dry-run] prompt: {report.short(run_dir / 'prompt.md')}")
    return 0


def _record_failure(meta: RunMeta, run_dir: Path, exc: BaseException) -> None:
    if meta.status == "running":
        meta.status = (
            "bloqueado" if isinstance(exc, SecretFound)
            else "interrumpido" if isinstance(exc, KeyboardInterrupt) else "error"
        )
    meta.error = meta.error or str(exc) or type(exc).__name__
    runs.save(meta, run_dir)


# --- revisión ----------------------------------------------------------------

def cmd_diff(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, _ = _load(args.run)
    path = _require_worktree(meta)
    print(worktree.diff(path, meta.base_commit or "HEAD", stat=args.stat) or "(sin cambios)")
    return 0


def cmd_feedback(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, run_dir = _load(args.run)
    _require_open(meta)
    limit = cfg["limits"]["max_review_rounds"]
    if meta.review_rounds >= limit and not args.force:
        raise DelegateError(
            f"Ya van {meta.review_rounds} rondas de revisión con {meta.agent}. "
            f"Escala con 'ai-delegate escalate {meta.run_id}' o usa --force."
        )
    text = sanitize(" ".join(args.text), source="el feedback")
    meta.review_rounds += 1
    meta.feedback.append(text)
    runs.add_event(meta, "feedback")
    return _continue(meta, run_dir, cfg, prompt.compose_feedback(text, meta.review_rounds), f"revisión {meta.review_rounds}")


def cmd_escalate(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, run_dir = _load(args.run)
    _require_open(meta)
    previous, nxt = meta.agent, routing.next_in_chain(meta.agent, cfg)
    runs.add_event(meta, "escalated", nxt)
    stats.record(meta, "escalado")
    meta.escalated_from.append(previous)
    if nxt == routing.MAIN:
        return _escalate_to_main(meta, run_dir)
    meta.agent, meta.thread_id, meta.review_rounds, meta.fix_rounds = nxt, None, 0, 0
    runs.add_event(meta, "assigned", previous)
    design = _reload_design_spec(meta)
    text = prompt.compose_escalation(meta.task, previous, meta.feedback, meta.diffstat or "", design)
    return _continue(meta, run_dir, cfg, sanitize(text, source="el prompt de escalamiento"), "escalamiento")


def _reload_design_spec(meta: RunMeta) -> str | None:
    if not meta.design_spec_path:
        return None
    path = Path(meta.design_spec_path)
    if not path.is_file():
        raise DelegateError(f"La especificación de diseño ya no existe: {path}. Restáurala antes de escalar.")
    return prompt.read_context_file(path)


def _escalate_to_main(meta: RunMeta, run_dir: Path) -> int:
    previous = meta.agent
    meta.agent, meta.status = routing.MAIN, "escalado-a-main"
    runs.add_event(meta, "assigned", previous)
    runs.save(meta, run_dir)
    where = f"{report.short(meta.worktree)} (rama {meta.branch})" if meta.worktree else meta.workdir
    print(f"Te toca a ti (sesión principal). Trabaja en: {where}")
    print(f"Cuando termines: ai-delegate merge {meta.run_id}")
    return 3


def _continue(meta: RunMeta, run_dir: Path, cfg: dict[str, Any], text: str, label: str) -> int:
    meta.status = "running"
    runner = runners.get(meta.agent, cfg)
    runner.ensure_available()
    loop.drive(_session(meta, run_dir, cfg, runner, None, None), text, label)
    report.print_run(meta, run_dir, cfg["limits"]["summary_lines"])
    return 0 if meta.status in SUCCESS else 1


def cmd_merge(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, run_dir = _load(args.run)
    path = _require_worktree(meta)
    message = args.message or f"ai-delegate({meta.agent}): {meta.task.strip().splitlines()[0][:72]}"
    worktree.merge(Path(meta.project_root or ""), path, meta.branch or "", meta.base_branch or "", message)
    meta.status = "integrado"
    runs.add_event(meta, "merged")
    stats.record(meta, "integrado")
    print(f"integrado en {meta.base_branch} ({report.short(meta.project_root or '')}); worktree eliminado")
    return 0


def cmd_discard(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, run_dir = _load(args.run)
    if meta.worktree and meta.project_root:
        worktree.remove(Path(meta.project_root), Path(meta.worktree), meta.branch or "")
    if meta.status in ("listo-para-revisar", "checks-fallidos", "escalado-a-main", "sin-cambios"):
        stats.record(meta, "descartado")
    meta.status = "descartado"
    runs.add_event(meta, "discarded")
    print(f"descartada {meta.run_id}")
    return 0


# --- consulta ----------------------------------------------------------------

def cmd_show(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    meta, run_dir = _load(args.run)
    report.print_run(meta, run_dir, cfg["limits"]["summary_lines"])
    return 0


def cmd_list(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    rows = runs.recent(args.n)
    if not rows:
        print("Sin corridas todavía.")
    for meta in rows:
        task = meta.task.strip().splitlines()[0][:50] if meta.task.strip() else ""
        print(f"{meta.run_id:<48} {meta.status:<19} {meta.kind:<9} {task}")
    return 0


def cmd_ui(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    """Abre la oficina local."""
    from .ui_server import serve
    return serve(args.port, args.no_open)


def cmd_stats(args: argparse.Namespace, cfg: dict[str, Any]) -> int:
    print(stats.table())
    return 0


# --- utilidades --------------------------------------------------------------

def _read_task(args: argparse.Namespace) -> str:
    if args.task_file:
        path = Path(args.task_file).expanduser()
        if not path.is_file():
            raise DelegateError(f"No existe --task-file: {path}")
        return path.read_text()
    if not args.task:
        raise DelegateError('Falta la tarea. Ej.: ai-delegate --kind test "agrega tests para utils/price.ts"')
    return " ".join(args.task)


def _existing_dir(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise DelegateError(f"--dir no existe o no es carpeta: {path}")
    return path


def _session(meta: RunMeta, run_dir: Path, cfg: dict[str, Any], runner: Runner,
             timeout: str | None, max_fix: int | None) -> loop.Session:
    limits = cfg["limits"]
    return loop.Session(
        meta=meta, run_dir=run_dir, runner=runner,
        timeout_s=parse_duration(timeout, limits["timeout_min"] * 60),
        check_timeout_s=limits["check_timeout_min"] * 60,
        max_fix_rounds=limits["max_fix_rounds"] if max_fix is None else max_fix,
    )


def _load(ref: str) -> tuple[RunMeta, Path]:
    run_dir = runs.resolve(ref)
    return runs.load(run_dir), run_dir


def _require_worktree(meta: RunMeta) -> Path:
    if not meta.worktree or not Path(meta.worktree).exists():
        raise DelegateError(f"La corrida {meta.run_id} no tiene worktree activo (estado: {meta.status}).")
    return Path(meta.worktree)


def _require_open(meta: RunMeta) -> None:
    if meta.status in ("integrado", "descartado", "dry-run"):
        raise DelegateError(f"La corrida {meta.run_id} ya está cerrada ({meta.status}).")
    if meta.mode != "write":
        raise DelegateError("feedback/escalate solo aplican a corridas en modo write.")


COMMANDS = {
    "ui": cmd_ui, "run": cmd_run, "diff": cmd_diff, "feedback": cmd_feedback, "escalate": cmd_escalate,
    "merge": cmd_merge, "discard": cmd_discard, "show": cmd_show, "list": cmd_list, "stats": cmd_stats,
}
