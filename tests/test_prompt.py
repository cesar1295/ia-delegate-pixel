from pathlib import Path

import pytest

from aidelegate import prompt
from aidelegate.errors import DelegateError


def spec(**kw):
    base = dict(task="Agrega validación al formulario", mode="write", directory=Path("/r"), kind="feature")
    return prompt.PromptSpec(**{**base, **kw})


def test_compose_includes_task_mode_and_dir():
    text = prompt.compose(spec())
    assert "Agrega validación al formulario" in text
    assert "Modo ESCRITURA" in text
    assert "`/r`" in text
    assert "# Tarea (feature)" in text


def test_write_mode_protects_design():
    assert "TODO(diseño)" in prompt.compose(spec())


def test_read_mode_forbids_edits_and_skips_design_rule():
    text = prompt.compose(spec(mode="read"))
    assert "Modo LECTURA" in text
    assert "TODO(diseño)" not in text


def test_optional_sections_only_when_present():
    plain = prompt.compose(spec())
    assert "Issue de GitHub" not in plain and "Contexto del repo" not in plain
    full = prompt.compose(spec(issue="#4 Botón roto", context="Usa Next.js 15"))
    assert "#4 Botón roto" in full and "Usa Next.js 15" in full


def test_context_file_limits(tmp_path):
    with pytest.raises(DelegateError, match="No existe"):
        prompt.read_context_file(tmp_path / "nada.md")
    big = tmp_path / "big.md"
    big.write_text("x" * (prompt.MAX_CONTEXT_BYTES + 1))
    with pytest.raises(DelegateError, match="pesa más"):
        prompt.read_context_file(big)


def test_escalation_carries_feedback():
    text = prompt.compose_escalation("tarea", "agy", ["falta manejar null"], "2 files changed")
    assert "antes la tenía agy" in text and "falta manejar null" in text and "2 files changed" in text
