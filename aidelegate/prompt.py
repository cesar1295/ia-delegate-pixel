"""Composición de los prompts que reciben los agentes delegados."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import DelegateError
from .sanitize import sanitize

MAX_CONTEXT_BYTES = 200_000

MODE_RULES = {
    "read": "Modo LECTURA: no modifiques, crees ni borres archivos. Solo analiza y responde.",
    "write": (
        "Modo ESCRITURA: edita archivos solo dentro del directorio de trabajo. "
        "No hagas commits, push ni cambies de rama; la sesión principal integra los cambios."
    ),
}

DESIGN_RULE = (
    "El diseño visual (layout, estilos, clases CSS, colores, tipografía, animaciones) lo define "
    "la sesión principal. No lo cambies; si la tarea lo necesita, deja un comentario "
    "`TODO(diseño): ...` y menciónalo en tu resumen."
)

# Con especificación de diseño, el agente implementa; no diseña.
DESIGN_IMPL_RULE = (
    "Implementa el diseño EXACTAMENTE como dice la especificación de diseño: mismos colores, "
    "tipografías, tamaños, espaciados, radios, sombras, breakpoints, estados y textos. No inventes "
    "estilos, componentes, secciones ni animaciones que no estén ahí, y no 'mejores' el diseño. "
    "Si algo no está especificado, usa los tokens/estilos que ya existen en el proyecto, márcalo "
    "con `TODO(diseño): ...` y lístalo en tu resumen."
)

REPORT_RULE = (
    "Al terminar responde con un resumen de máximo 10 líneas: qué hiciste, archivos tocados, "
    "cómo lo verificaste y qué quedó pendiente. No pegues código completo."
)


@dataclass(frozen=True)
class PromptSpec:
    task: str
    mode: str
    directory: Path
    kind: str
    issue: str | None = None
    context: str | None = None
    agent_hint: str = ""
    design_spec: str | None = None
    acceptance_criteria: tuple[str, ...] = ()


def design_rule(design_spec: str | None) -> str:
    return DESIGN_IMPL_RULE if design_spec else DESIGN_RULE


def design_section(design_spec: str | None) -> list[str]:
    if not design_spec:
        return []
    return [f"## Especificación de diseño (obligatoria, síguela al pie de la letra)\n\n{design_spec.strip()}"]


def compose(spec: PromptSpec) -> str:
    rules = [MODE_RULES[spec.mode], f"Directorio de trabajo: `{spec.directory}`"]
    if spec.mode == "write":
        rules.append(design_rule(spec.design_spec))
    if spec.agent_hint:
        rules.append(spec.agent_hint)
    rules.append(REPORT_RULE)
    parts = [
        f"# Tarea ({spec.kind})\n\n{spec.task.strip()}",
        "## Reglas\n\n" + "\n".join(f"- {rule}" for rule in rules),
        *design_section(spec.design_spec),
    ]
    if spec.acceptance_criteria:
        parts.append("## Criterios de aceptación (se verificarán automáticamente)\n\n" +
                     "\n".join(spec.acceptance_criteria) +
                     "\n\nAntes de entregar, verifica cada criterio; si puedes correr comandos, córrelos.")
    if spec.issue:
        parts.append(f"## Issue de GitHub\n\n{spec.issue.strip()}")
    if spec.context:
        parts.append(f"## Contexto del repo\n\n{spec.context.strip()}")
    return "\n\n".join(parts) + "\n"


def compose_check_failure(check_cmd: str, output: str) -> str:
    return (
        f"Los checks del proyecto fallaron (`{check_cmd}`). Corrige la causa, no ocultes el "
        f"error ni desactives pruebas.\n\nÚltimas líneas de la salida:\n\n```\n{output.strip()}\n```\n\n"
        f"{REPORT_RULE}\n"
    )


def compose_feedback(feedback: str, review_round: int) -> str:
    return (
        f"Revisión #{review_round} de la sesión principal: el cambio todavía no se acepta.\n\n"
        f"{feedback.strip()}\n\nAplica estas correcciones sobre tu trabajo actual. {REPORT_RULE}\n"
    )


def compose_escalation(
    task: str, previous_agent: str, feedback: list[str], diffstat: str, design_spec: str | None = None
) -> str:
    notes = "\n".join(f"- {item}" for item in feedback) or "- (sin comentarios registrados)"
    text = (
        f"# Tarea escalada (antes la tenía {previous_agent})\n\n{task.strip()}\n\n"
        f"El directorio ya contiene un intento previo ({diffstat or 'sin cambios'}). Revísalo, "
        f"conserva lo que sirva y corrige lo que no.\n\n## Comentarios de revisión previos\n\n{notes}\n\n"
        f"## Reglas\n\n- {MODE_RULES['write']}\n- {design_rule(design_spec)}\n- {REPORT_RULE}\n"
    )
    return "\n\n".join([text.rstrip(), *design_section(design_spec)]) + "\n"


def fetch_issue(ref: str, directory: Path) -> str:
    if shutil.which("gh") is None:
        raise DelegateError("--issue necesita GitHub CLI (gh). Instálalo con: sudo apt install gh && gh auth login")
    cmd = ["gh", "issue", "view", ref, "--json", "number,title,body"]
    proc = subprocess.run(cmd, cwd=directory, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DelegateError(f"gh no pudo leer el issue {ref}: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)
    return sanitize(f"#{data['number']} {data['title']}\n\n{data.get('body') or ''}", source="el issue de GitHub")


def read_context_file(path: Path) -> str:
    if not path.is_file():
        raise DelegateError(f"No existe el archivo de contexto: {path}")
    if path.stat().st_size > MAX_CONTEXT_BYTES:
        raise DelegateError(f"{path} pesa más de {MAX_CONTEXT_BYTES // 1000} KB; resume el contexto primero.")
    return path.read_text(errors="replace")


def load_design_spec(meta: Any) -> str | None:
    path_str = getattr(meta, "design_spec_path", None)
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_file():
        raise DelegateError(f"La especificación de diseño ya no existe: {path}. Restáurala antes de escalar.")
    return read_context_file(path)
