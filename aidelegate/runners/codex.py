"""Codex CLI: `codex exec --json`, sandbox según el modo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentResult, Runner

SANDBOX = {"read": "read-only", "write": "workspace-write"}


class CodexRunner(Runner):
    name = "codex"
    supports_resume = True

    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        effective_mode = "read" if (mode == "read" or not getattr(self, "edit", True)) else "write"
        common = ["--json", "--skip-git-repo-check", "-c", f'sandbox_mode="{SANDBOX[effective_mode]}"']
        if getattr(self, "network", False):
            common += ["-c", "sandbox_workspace_write.network_access=true"]
        if self.model:
            common += ["-m", self.model]
        if self.effort:
            common += ["-c", f'model_reasoning_effort="{self.effort}"']
        if resume_id:
            return [self.binary, "exec", "resume", *common, resume_id, prompt]
        return [self.binary, "exec", *common, "-C", str(cwd), prompt]

    def parse_event(self, event: dict[str, Any], result: AgentResult, deltas: list[str]) -> None:
        kind = event.get("type")
        item = event.get("item") or {}
        identity = item.get("id")
        names = " ".join(str(item.get(k, "")) for k in ("type", "tool", "name")).lower()
        if (kind in {"item.started", "item.completed"} and identity is not None
                and any(word in names for word in ("agent", "subagent", "spawn"))):
            result.subagents = [s for s in result.subagents if s["id"] != identity]
            if kind == "item.started":
                result.subagents.append({"id": identity, "label": str(item.get("name") or item.get("tool") or item.get("type"))[:24]})
        if kind == "thread.started":
            result.thread_id = event.get("thread_id") or result.thread_id
        elif kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                result.last_message = item.get("text", "")
        elif kind == "turn.completed":
            result.usage = event.get("usage") or {}
        elif kind in ("turn.failed", "error"):
            result.error = _error_text(event)


def _error_text(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(event.get("message") or json.dumps(event, ensure_ascii=False)[:300])
