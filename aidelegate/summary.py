"""Recorte del mensaje final para no inflar el contexto de la sesión principal."""

from __future__ import annotations


import re


def trim(text: str, max_lines: int) -> tuple[str, bool]:
    """Devuelve (texto recortado, si se recortó)."""
    lines = text.strip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    return "\n".join(lines[:max_lines]), True


def looks_garbled(text: str) -> bool:
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    cleaned = re.sub(r"(?:https?|file)://\S+", "", cleaned)
    if len(cleaned) <= 200:
        return False
    words = cleaned.split()
    if not words:
        return False
    return cleaned.count(" ") / len(cleaned) < 0.08 or sum(map(len, words)) / max(1, len(words)) > 14
