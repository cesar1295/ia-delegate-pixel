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


class _PromptHintProperty:
    def __get__(self, instance: Any, owner: Any = None) -> str:
        from ..permissions import agy_prompt_hint
        if instance is None:
            return agy_prompt_hint(["lectura"])
        return agy_prompt_hint(getattr(instance, "groups", ["lectura"]))


class AgyRunner(Runner):
    name = "agy"
    supports_resume = True
    prompt_hint = _PromptHintProperty()  # type: ignore[assignment]

    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        effective_mode = "read" if (mode == "read" or not getattr(self, "edit", True)) else "write"
        argv = [self.binary, "--output-format", "stream-json", "--print-timeout", "0", *MODE_FLAGS[effective_mode]]
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
            if step.get("step_type") == "tool" and "subagent" in str(step.get("tool_name", "")).lower():
                identity = step.get("step_index", event.get("step_index"))
                result.subagents = [s for s in result.subagents if s["id"] != identity]
                if step.get("state") == "ACTIVE":
                    result.subagents.append({"id": identity, "label": str(step["tool_name"])[:24]})
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
