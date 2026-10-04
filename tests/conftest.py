import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKES = Path(__file__).resolve().parent / "fakes"
sys.path.insert(0, str(ROOT))


(ROOT / "hecho.txt").unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def clean_root_hecho():
    (ROOT / "hecho.txt").unlink(missing_ok=True)
    yield
    if (ROOT / "hecho.txt").exists():
        (ROOT / "hecho.txt").unlink(missing_ok=True)
        raise AssertionError("Se creó hecho.txt en la raíz del repositorio")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Datos y config de ai-delegate aislados; los agentes apuntan a los CLIs falsos."""
    data = tmp_path / "data"
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[agents.codex]\n"
        f'bin = "{FAKES / "fake_codex.py"}"\n'
        "[agents.agy]\n"
        f'bin = "{FAKES / "fake_agy.py"}"\n'
        "[strategy]\n"
        'mode = "routing"\n'
    )
    monkeypatch.setenv("AI_DELEGATE_HOME", str(data))
    monkeypatch.setenv("AI_DELEGATE_CONFIG", str(cfg))
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "Prueba")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "prueba@example.com")
    return data


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "mi-repo"
    path.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "--allow-empty", "-m", "inicio"]):
        subprocess.run(["git", *cmd], cwd=path, check=True, capture_output=True)
    return path
