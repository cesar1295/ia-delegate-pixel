import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKES = Path(__file__).resolve().parent / "fakes"
sys.path.insert(0, str(ROOT))


(ROOT / "hecho.txt").unlink(missing_ok=True)

# --- Guardián: ninguna prueba puede tocar la configuración real del usuario ---
REAL_HOME = Path.home()
PROTECTED_DIRS = [
    REAL_HOME / ".claude", REAL_HOME / ".codex", REAL_HOME / ".gemini",
    REAL_HOME / ".config/ai-delegate", REAL_HOME / ".config/systemd/user", REAL_HOME / ".local/share/ai-delegate",
]
PROTECTED_FILES = [REAL_HOME / ".gitconfig", REAL_HOME / ".local/bin/ai-delegate"]
CONFIG_SUFFIXES = {".json", ".toml", ".md", ".service"}


def _snapshot() -> dict[str, float]:
    """mtime de los archivos de configuración del usuario (sin bajar a carpetas de sesiones/historial)."""
    found: dict[str, float] = {}
    for path in PROTECTED_FILES:
        if path.exists() or path.is_symlink():
            found[str(path)] = path.lstat().st_mtime
    for folder in PROTECTED_DIRS:
        for path in [*folder.glob("*"), *folder.glob("*/*")]:
            # solo configuración: los registros y bases internas (sqlite, logs, auth) los cambian las propias IAs
            if path.suffix in CONFIG_SUFFIXES and path.name != "auth.json" and (path.is_file() or path.is_symlink()):
                found[str(path)] = path.lstat().st_mtime
    return found


_BEFORE = _snapshot()


def pytest_sessionfinish(session, exitstatus):
    after = _snapshot()
    changed = sorted(p for p in set(_BEFORE) | set(after)
                     if _BEFORE.get(p) != after.get(p) and "/runs/" not in p and "/worktrees/" not in p
                     and not p.endswith((".jsonl", "claude-status.json", "claude-quota.json")))
    if changed:
        session.exitstatus = 1
        print("\n\nERROR: las pruebas modificaron archivos reales del usuario:\n  " + "\n  ".join(changed))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Cada prueba corre con un HOME y carpetas XDG falsas; nada escribe en la máquina real."""
    fake = tmp_path_factory.mktemp("home")
    for var, sub in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                     ("XDG_CACHE_HOME", ".cache")):
        target = fake / sub
        target.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(var, str(target))
    monkeypatch.setenv("AI_DELEGATE_HOME", str(fake / ".local/share/ai-delegate"))
    monkeypatch.setenv("AI_DELEGATE_CONFIG", str(fake / ".config/ai-delegate/config.toml"))
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "Prueba")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "prueba@example.com")
    yield fake


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
