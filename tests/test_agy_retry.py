"""agy sin interfaz: un permiso negado no debe tirar la ronda; se retoma la conversación."""

from aidelegate import runs
from aidelegate.cli import main


def test_denied_permission_is_retried_in_same_conversation(home, repo):
    assert main(["--to", "agy", "--dir", str(repo), "--check", "none", "NIEGA_PRIMERO crea hecho.txt"]) == 0
    meta = runs.load(runs.resolve("last"))
    assert meta.status == "listo-para-revisar"
    assert [h["label"] for h in meta.history] == ["reintento permisos", "tarea"]
    assert "no está permitido" in (runs.resolve("last") / "prompt.md").read_text()
