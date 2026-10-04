#!/usr/bin/env python3
"""CLI falso que responde texto plano y guarda el prompt recibido."""

import sys
from pathlib import Path

prompt = sys.argv[-1]
Path("generic-prompt.txt").write_text(prompt)
if "SIN_CAMBIOS" not in prompt:
    path = Path("hecho.txt")
    path.write_text((path.read_text() if path.exists() else "") + "hecho generic\n")
print("listo desde generic")
print("segunda línea")
