"""Recorte del mensaje final para no inflar el contexto de la sesión principal."""

from __future__ import annotations


def trim(text: str, max_lines: int) -> tuple[str, bool]:
    """Devuelve (texto recortado, si se recortó)."""
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    return "\n".join(lines[:max_lines]), True


def looks_garbled(text: str) -> bool:
    if len(text) <= 200:
        return False
    words = text.split()
    return text.count(" ") / len(text) < 0.08 or sum(map(len, words)) / max(1, len(words)) > 14
