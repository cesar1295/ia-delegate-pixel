"""Claude Code en modo no interactivo con stream-json."""

from pathlib import Path
from .base import AgentResult, Runner


class ClaudeRunner(Runner):
    name = "claude"
    supports_resume = True
    prompt_hint = "Trabaja sin pedir confirmaciones: no hay nadie para responderlas. No hagas commits."

    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        perm_mode = "acceptEdits" if (mode == "write" and getattr(self, "edit", True)) else "plan"
        args = [self.binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
                "--permission-mode", perm_mode]
        if resume_id:
            args += ["--resume", resume_id]
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        return args

    def parse_event(self, event: dict, result: AgentResult, deltas: list[str]) -> None:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            result.thread_id = event.get("session_id") or result.thread_id
        if kind in {"assistant", "user"}:
            for block in (event.get("message") or {}).get("content", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in {"Task", "Agent"}:
                    identity = block.get("id")
                    result.subagents = [s for s in result.subagents if s["id"] != identity]
                    result.subagents.append({"id": identity, "label": (block.get("input") or {}).get("subagent_type") or "subagente"})
                elif block.get("type") == "tool_result":
                    result.subagents = [s for s in result.subagents if s["id"] != block.get("tool_use_id")]
                elif block.get("type") == "text":
                    deltas.append(block.get("text", ""))
        if kind == "result":
            result.thread_id = event.get("session_id") or result.thread_id
            result.last_message = event.get("result") or ""
            result.usage = event.get("usage") or {}
            if event.get("is_error"):
                result.error = result.last_message or "Claude terminó con error"
