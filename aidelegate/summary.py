"""Recorte del mensaje final para no inflar el contexto de la sesión principal."""

from __future__ import annotations


def trim(text: str, max_lines: int) -> tuple[str, bool]:
    """Devuelve (texto recortado, si se recortó)."""
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    return "\n".join(lines[:max_lines]), True
