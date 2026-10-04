"""Actualización silenciosa y mínima del estado de Claude."""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import config

EVENTS = {"UserPromptSubmit": "working", "PreToolUse": "working", "PostToolUse": "working",
          "Notification": "waiting", "Stop": "idle", "SubagentStop": "idle", "SessionEnd": "idle"}


def main(argv: list[str]) -> int:
    """Procesa estado manual o hook sin emitir errores ni contenido del hook."""
    temporary: Path | None = None
    try:
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
        with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False, encoding="utf-8") as fh:
            temporary = Path(fh.name)
            json.dump({"state": state, "detail": detail, "ts": datetime.now().isoformat(timespec="seconds")}, fh)
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
