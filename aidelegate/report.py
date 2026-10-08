"""Salida compacta en pantalla: lo justo para que la sesión principal decida."""

from __future__ import annotations

from pathlib import Path

from .runs import RunMeta
from .summary import trim


def short(path: str | Path) -> str:
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def print_run(meta: RunMeta, run_dir: Path, max_lines: int) -> None:
    print(f"{meta.agent} | {meta.mode} | {meta.repo} | {meta.status} | {round(meta.duration_s)}s")
    print(f"modelo: {meta.model or 'predeterminado'} · {meta.effort}")
    if meta.target_reason:
        print(f"elegido: {meta.agent} ({meta.target_reason})")
    if meta.fallback_from:
        print(f"nota: {meta.fallback_from} agotó su cuota; se usó {meta.agent}")
    print(f"thread: {meta.thread_id or '-'}")
    print(f"corrida: {meta.run_id}  ({short(run_dir)})")
    _print_workspace(meta, run_dir)
    if meta.status == "sin-cambios":
        print("aviso: la ronda no cambió ningún archivo; revisa o escala")
    if meta.error:
        print(f"error: {meta.error}")
    _print_summary(run_dir, max_lines)
    _print_next(meta)


def _print_workspace(meta: RunMeta, run_dir: Path) -> None:
    if meta.worktree:
        print(f"worktree: {short(meta.worktree)}  (rama {meta.branch})")
    if meta.last_check:
        state = "ok" if meta.last_check["ok"] else "FALLAN"
        print(f"checks: {meta.last_check['cmd']} → {state} (correcciones automáticas: {meta.fix_rounds})")
    elif meta.mode == "write":
        print("checks: ninguno — revisa el diff con más cuidado")
    if meta.acceptance:
        a = meta.acceptance
        state = "✓" if not a["failed"] else "✗ — " + a["failed"][0].splitlines()[0]
        print(f"aceptación: {a['ok']}/{a['total']} {state}")
    if meta.visual:
        v = meta.visual
        if v["status"] == "omitida":
            print(f"vista: omitida: {v['note']}")
        else:
            print(f"vista: {len(v['shots'])} capturas, {v['errors']} errores → {short(run_dir / 'screens')}")
            if v["status"] == "fallo":
                print(v["note"])
    if meta.prereview:
        r = meta.prereview
        if r.get("status") == "omitida":
            note = " ".join(r.get("note", "").split())[:200]
            print(f"pre-revisión: omitida — {note}")
        else:
            print(f"pre-revisión ({r['agent']}): {r['grave']} graves · {r['medio']} medios · {r['menor']} menores → {short(run_dir / 'review.md')}")
    if meta.diffstat:
        print(f"cambios: {meta.diffstat}")


def _print_summary(run_dir: Path, max_lines: int) -> None:
    last = run_dir / "last.md"
    text = last.read_text() if last.exists() else ""
    summary, cut = trim(text, max_lines)
    print("--- resumen ---")
    print(summary or "(sin mensaje final)")
    if cut:
        print(f"[recortado a {max_lines} líneas; completo en {short(last)}]")


def _print_next(meta: RunMeta) -> None:
    if not meta.worktree or meta.status not in ("listo-para-revisar", "checks-fallidos", "sin-cambios"):
        return
    rid = meta.run_id
    print(f"siguiente: ai-delegate diff {rid} | feedback {rid} \"...\" | merge {rid} | discard {rid}")
