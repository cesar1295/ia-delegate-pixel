"""Argumentos de la línea de comandos."""

from __future__ import annotations

import argparse
import re

from .errors import DelegateError

SUBCOMMANDS = ("run", "diff", "feedback", "escalate", "merge", "discard", "show", "list", "stats", "ui", "claude-status")


def parse(argv: list[str]) -> argparse.Namespace:
    # `ai-delegate --to codex "tarea"` equivale a `ai-delegate run --to codex "tarea"`.
    if argv and argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["run", *argv]
    return _parser().parse_args(argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-delegate",
        description="Delega tareas a Codex o Antigravity (agy) y devuelve un resumen corto.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_run(sub)
    _add_run_ref(sub, "diff", "Muestra el diff del worktree de una corrida.").add_argument(
        "--stat", action="store_true", help="solo el resumen de archivos"
    )
    feedback = _add_run_ref(sub, "feedback", "Regresa la corrida al agente con comentarios de revisión.")
    feedback.add_argument("text", nargs="+", help="comentarios de revisión")
    feedback.add_argument("--force", action="store_true", help="ignora el límite de rondas de revisión")
    _add_run_ref(sub, "escalate", "Pasa la corrida al siguiente de la cadena (agy → codex → principal).")
    _add_run_ref(sub, "merge", "Hace commit en el worktree e integra la rama.").add_argument(
        "-m", "--message", help="mensaje del commit"
    )
    _add_run_ref(sub, "discard", "Descarta el worktree y la rama de la corrida.")
    _add_run_ref(sub, "show", "Muestra el estado y resumen de una corrida.")
    sub.add_parser("list", help="Corridas recientes.").add_argument("-n", type=int, default=15)
    sub.add_parser("stats", help="Tasa de aceptación por agente y tipo de tarea.")
    ui = sub.add_parser("ui", help="Abre la oficina pixel local.")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-open", action="store_true")
    status = sub.add_parser("claude-status", help="Actualiza silenciosamente el estado de Claude.")
    status.add_argument("state", nargs="?", choices=("working", "waiting", "idle"))
    status.add_argument("--detail")
    status.add_argument("--from-hook", action="store_true")
    return parser


def _add_run(sub: argparse._SubParsersAction) -> None:
    run = sub.add_parser("run", help="Delegar una tarea (subcomando por defecto).")
    run.add_argument("task", nargs="*", help="la tarea en texto libre")
    run.add_argument("--task-file", help="lee la tarea de un archivo (especificaciones largas)")
    run.add_argument("--to", choices=("auto", "codex", "agy"), default="auto")
    run.add_argument("--kind", help="tipo de tarea: feature, bugfix, test, docs, research, design…")
    run.add_argument("--dir", default=".", help="repo o carpeta de trabajo (por defecto, la actual)")
    run.add_argument("--mode", choices=("read", "write"), help="por defecto depende de --kind")
    run.add_argument("--issue", help="número o URL de un issue de GitHub (vía gh)")
    run.add_argument("--context-file", help="archivo con contexto del repo")
    run.add_argument("--design-spec", help="especificación de diseño a implementar al pie de la letra "
                                           "(obligatoria con --kind design; ver templates/design-spec.md)")
    run.add_argument("--worktree", action=argparse.BooleanOptionalAction, default=None,
                     help="worktree aislado (por defecto sí en modo write dentro de un repo git)")
    run.add_argument("--check", default="auto", help="comando de checks, 'auto' (detecta) o 'none'")
    run.add_argument("--max-fix-rounds", type=int, help="correcciones automáticas si fallan los checks")
    run.add_argument("--timeout", help="límite por ronda: 90s, 20m, 1h (número solo = minutos)")
    run.add_argument("--resume", metavar="THREAD_ID", help="continúa una conversación existente")
    run.add_argument("--model", help="modelo específico del agente")
    run.add_argument("--dry-run", action="store_true", help="arma todo sin llamar a ningún CLI")
    run.add_argument("--print-env", action="store_true", help="muestra los nombres de variables que se heredan")


def _add_run_ref(sub: argparse._SubParsersAction, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(name, help=help_text)
    parser.add_argument("run", help="id de la corrida, prefijo único o 'last'")
    return parser


def parse_duration(text: str | None, default_s: int) -> int:
    if not text:
        return default_s
    match = re.fullmatch(r"(\d+)\s*([smh]?)", text.strip())
    if not match:
        raise DelegateError(f"--timeout inválido: {text}. Usa por ejemplo 90s, 20m o 1h.")
    value, unit = int(match.group(1)), match.group(2) or "m"
    return value * {"s": 1, "m": 60, "h": 3600}[unit]
