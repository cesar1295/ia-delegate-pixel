"""Antigravity CLI: `agy -p --output-format stream-json`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentResult, Runner

# Sin interfaz, agy no puede pedir permisos: los comandos de terminal se niegan solos.
# Trabaja con sus herramientas de archivos; ai-delegate corre los checks por él.
MODE_FLAGS = {
    "read": ["--mode", "plan"],
    "write": ["--mode", "accept-edits"],
}


class AgyRunner(Runner):
    name = "agy"
    prompt_hint = (
        "En la terminal solo tienes permitidos comandos de lectura: ls, tree, pwd, cat, head, "
        "tail, wc, grep y git status/log/diff/show/ls-files (sin pipes ni redirecciones); "
        "cualquier otro se niega. Prefiere tus herramientas de archivos: view_file, list_dir, "
        "grep_search y edición de archivos. No lances subagentes: lee tú mismo y responde en "
        "este mismo turno. Los tests los corre la herramienta que te llamó y te devolverá los "
        "errores si fallan."
    )

    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        argv = [self.binary, "--output-format", "stream-json", "--print-timeout", "0", *MODE_FLAGS[mode]]
        if self.model:
            argv += ["--model", self.model]
        if resume_id:
            argv += ["--conversation", resume_id]
        return [*argv, "-p", prompt]

    def parse_event(self, event: dict[str, Any], result: AgentResult, deltas: list[str]) -> None:
        kind = event.get("event")
        if kind == "init":
            result.thread_id = event.get("conversation_id") or result.thread_id
        elif kind == "step_update":
            step = event.get("step_update") or {}
            if step.get("step_type") == "agent_response" and step.get("text_delta"):
                deltas.append(step["text_delta"])
        elif kind == "result":
            self._parse_result(event.get("result") or {}, result)
        elif kind == "error":
            result.error = str(event.get("message") or json.dumps(event, ensure_ascii=False)[:300])

    @staticmethod
    def _parse_result(data: dict[str, Any], result: AgentResult) -> None:
        result.last_message = data.get("response") or result.last_message
        result.usage = data.get("usage") or {}
        status = data.get("status", "SUCCESS")
        denied = [d.get("display_name") or d.get("action", "?") for d in data.get("denied_actions") or []]
        if status != "SUCCESS":
            detail = data.get("error") or data.get("message") or ""
            result.error = f"agy terminó con estado {status}. {detail}".strip()
        elif denied and not result.last_message.strip():
            result.error = f"agy no respondió: le negaron permisos para {', '.join(denied)}."
