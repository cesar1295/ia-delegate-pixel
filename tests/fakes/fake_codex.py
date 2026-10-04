#!/usr/bin/env python3
"""Codex falso: emite eventos JSONL como `codex exec --json`.

Comportamiento según palabras en el prompt:
  CUOTA         -> falla por límite de uso
  FALLA_PRIMERO -> la primera ronda no crea hecho.txt (los checks fallan)
  LARGO         -> mensaje final de 40 líneas
"""

import json
import sys
from pathlib import Path

if "--version" in sys.argv:
    print("codex 0.1.0")
    sys.exit(0)

args = sys.argv[1:]
prompt = args[-1]
resume = "resume" in args


def emit(event):
    print(json.dumps(event), flush=True)


if not resume:
    emit({"type": "thread.started", "thread_id": "codex-thread-1"})
emit({"type": "turn.started"})
if "CUOTA" in prompt:
    print("ERROR: You've hit your usage limit (429)", file=sys.stderr)
    sys.exit(1)
if resume or "FALLA_PRIMERO" not in prompt:
    if "SIN_CAMBIOS" not in prompt:
        path = Path("hecho.txt")
        path.write_text((path.read_text() if resume and path.exists() else "") + "hecho\n")
lines = 40 if "LARGO" in prompt else 2
emit({"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "\n".join(f"línea {i}" for i in range(lines))}})
emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
