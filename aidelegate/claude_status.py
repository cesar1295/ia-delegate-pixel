"""Actualización silenciosa y mínima del estado de Claude."""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import config
from .ui_state import age

EVENTS = {"UserPromptSubmit": "working", "PreToolUse": "working", "PostToolUse": "working",
          "Notification": "waiting", "Stop": "idle", "SubagentStop": "idle", "SessionEnd": "idle"}


def main(argv: list[str]) -> int:
    """Procesa estado manual o hook sin emitir errores ni contenido del hook."""
    temporary: Path | None = None
    try:
        hook = {}
        now = datetime.now()
        if argv == ["--from-hook"]:
            hook = json.load(sys.stdin)
            state = EVENTS[hook["hook_event_name"]]
            detail = hook.get("tool_name", "") if state == "working" else ""
        else:
            state = argv[0]
            detail = ""
            if len(argv) > 1:
                if len(argv) != 3 or argv[1] != "--detail":
                    return 0
                detail = argv[2]
        if state not in {"working", "waiting", "idle"} or not isinstance(detail, str):
            return 0
        root = config.data_dir()
        root.mkdir(parents=True, exist_ok=True)
        try:
            previous = json.loads((root / "claude-status.json").read_text())
        except (OSError, ValueError):
            previous = {}
        subagents = [{"id": s["id"], "label": s["label"], "ts": s["ts"]}
                     for s in previous.get("subagents", []) if age(s.get("ts"), now) < 1800]
        event = hook.get("hook_event_name")
        identity = hook.get("tool_use_id") or now.isoformat()
        if event in {"Stop", "SessionEnd"}:
            subagents = []
        elif event == "SubagentStop":
            subagents = sorted(subagents, key=lambda s: s["ts"])[1:]
        elif hook.get("tool_name") in {"Task", "Agent"}:
            if event == "PreToolUse":
                subagents = [s for s in subagents if s["id"] != identity]
                label = (hook.get("tool_input") or {}).get("subagent_type") or "subagente"
                subagents.append({"id": identity, "label": str(label)[:24], "ts": now.isoformat(timespec="seconds")})
            elif event == "PostToolUse":
                subagents = [s for s in subagents if s["id"] != identity]
        subagents = subagents[-8:]
        with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False, encoding="utf-8") as fh:
            temporary = Path(fh.name)
            json.dump({"state": state, "detail": detail, "ts": now.isoformat(timespec="seconds"), "subagents": subagents}, fh)
        temporary.replace(root / "claude-status.json")
    except Exception:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return 0
