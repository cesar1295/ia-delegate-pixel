#!/usr/bin/env python3
"""agy falso: emite eventos como `agy --output-format stream-json -p`."""

import json
import sys
from pathlib import Path


def emit(event):
    print(json.dumps(event), flush=True)


if "--version" in sys.argv:
    print("agy 0.1.0")
    sys.exit(0)

if sys.argv[1:] == ["models"]:
    print("gemini-3.8-flash-high\tGemini 3.8 Flash (High)")
    print("gemini-3.8-pro\tGemini 3.8 Pro")
    sys.exit(0)

emit({"event": "init", "conversation_id": "agy-conv-1", "init": {"cwd": str(Path.cwd())}})
if "NIEGA_PRIMERO" in sys.argv[-1] and "--conversation" not in sys.argv:
    emit({"event": "result", "result": {"status": "SUCCESS", "response": "",
                                        "denied_actions": [{"action": "command", "display_name": "RunCommand"}]}})
    sys.exit(0)
if "accept-edits" in sys.argv:
    p = Path("hecho.txt")
    p.write_text((p.read_text() if p.exists() else "") + "hecho por agy\n")
emit({"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "lis"}})
emit({"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "to"}})
for state in ("ACTIVE", "DONE"):
    emit({"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "invoke_subagent",
                                                    "step_index": 1, "state": state}})
emit({"event": "result", "result": {"status": "SUCCESS", "response": "listo desde agy", "usage": {"total_tokens": 7}}})
