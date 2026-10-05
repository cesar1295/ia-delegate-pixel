"""Regresiones de instalación y maestra intercambiable."""
import copy
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aidelegate import activity, config, detect, routing
from aidelegate.cli import main
from aidelegate.errors import MainSessionTask
from aidelegate.install import END, START, FILES
from aidelegate.runners.claude import ClaudeRunner
from aidelegate.ui_state import build_state

_AGY = json.loads((Path(__file__).parent.parent / "setup/agy-permissions.json").read_text())["permissions"]
AGY_RULES = sum(len(v) for v in _AGY.values())


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AI_DELEGATE_CONFIG", raising=False)
    monkeypatch.delenv("AI_DELEGATE_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = Path(__file__).parent / "fakes/fake_claude.py"
    for name in ("claude", "codex", "agy"):
        (binaries / name).symlink_to(fake.resolve())
    monkeypatch.setenv("PATH", str(binaries) + os.pathsep + str(tmp_path / ".local/bin") + os.pathsep + os.environ["PATH"])
    for name in (".codex/auth.json", ".gemini/antigravity-cli/log/session.log"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("AuthResult: fake@example.test\n" if name.endswith(".log") else "{}")
    subprocess.run(["git", "config", "--global", "user.name", "Test"], check=True)
    subprocess.run(["git", "config", "--global", "user.email", "test@example.com"], check=True)
    return tmp_path


def test_detect(installed):
    result = detect.detect_all()
    assert all(d.path and d.version for d in result.values())
    assert result["claude"].logged_in is None
    assert result["codex"].logged_in and result["agy"].logged_in
    (installed / ".codex/auth.json").unlink()
    (installed / ".gemini/antigravity-cli/log/session.log").unlink()
    assert not detect.detect_all()["codex"].logged_in
    assert detect.detect_all()["agy"].logged_in is None


def test_desktop_semver(installed, monkeypatch):
    (installed / "bin/claude").unlink()
    monkeypatch.setenv("PATH", os.pathsep.join([str(installed / "bin"), "/usr/bin", "/bin"]))
    monkeypatch.setattr(detect.sys, "platform", "linux")
    for version in ("2.1.9", "2.1.10"):
        path = installed / ".config/Claude/claude-code" / version / "claude"
        path.parent.mkdir(parents=True)
        path.symlink_to((Path(__file__).parent / "fakes/fake_claude.py").resolve())
    assert "/2.1.10/" in detect.detect_all()["claude"].path


def test_setup_dry(installed, capsys):
    before = sorted(str(p) for p in installed.rglob("*"))
    assert main(["setup", "--dry-run", "--yes"]) == 0
    assert before == sorted(str(p) for p in installed.rglob("*"))
    output = capsys.readouterr().out
    assert all(f"{n}. " in output for n in range(1, 10))


@pytest.mark.parametrize("master", ["claude", "codex", "agy"])
def test_setup_twice(installed, master):
    path = installed / FILES[master]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Personal\n")
    permissions = installed / ".gemini/antigravity-cli/settings.json"
    permissions.write_text(json.dumps({"custom": 1, "permissions": {"allow": ["command(ls)"]}}))
    for _ in range(2):
        assert main(["setup", "--yes", "--master", master, "--user-name", "Ana"]) == 0
    assert config.load()["main"] == master
    assert path.read_text().count(START) == path.read_text().count(END) == 1
    assert "# Personal" in path.read_text()
    assert list(path.parent.glob(path.name + ".bak-ai-delegate-*"))
    data = json.loads(permissions.read_text())
    assert data["custom"] == 1 and data["permissions"]["allow"].count("command(ls)") == 1
    assert (installed / ".claude/settings.json").exists() == (master == "claude")
    assert main(["doctor"]) == 0


def test_master_move(installed):
    assert main(["setup", "--yes"]) == 0
    assert main(["master", "codex"]) == 0
    assert START not in (installed / FILES["claude"]).read_text()
    assert START in (installed / FILES["codex"]).read_text()
    assert not any(json.loads((installed / ".claude/settings.json").read_text())["hooks"].values())
    with pytest.raises(MainSessionTask):
        routing.resolve_target("codex", "feature", config.load())
    assert routing.resolve_target("claude", "feature", config.load()) == "claude"


def test_migration(installed):
    path = installed / FILES["claude"]
    path.parent.mkdir()
    path.write_text("# Personal\n\n# Equipo de IA: Claude dirige\nViejo\n")
    assert main(["setup", "--yes"]) == 0
    assert "Viejo" not in path.read_text() and "# Personal" in path.read_text()
    assert path.read_text().count(START) == 1


def test_doctor_missing_config(installed):
    assert main(["doctor"]) == 1


@pytest.mark.parametrize("resume", [None, "existing-session"])
def test_claude_runner(tmp_path, resume):
    runner = ClaudeRunner(str((Path(__file__).parent / "fakes/fake_claude.py").resolve()))
    assert "acceptEdits" in runner.argv("test", "write", tmp_path, resume)
    assert "plan" in runner.argv("test", "read", tmp_path, resume)
    result = runner.run("test", "write", tmp_path, resume, 5, tmp_path)
    assert result.ok and result.last_message == "OK" and not result.subagents
    assert result.thread_id == (resume or "claude-test-session")


def test_activity(installed):
    path = installed / ".codex/sessions" / datetime.now().strftime("%Y/%m/%d") / "rollout-test.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    now = datetime.now().astimezone()
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["main"] = "codex"
    activity._CACHE.clear()
    assert build_state([], None, [], now, cfg=cfg)["agents"][0]["state"] == "working"
    stamp = (now - timedelta(seconds=60)).timestamp()
    os.utime(path, (stamp, stamp))
    activity._CACHE.clear()
    assert build_state([], None, [], now, cfg=cfg)["agents"][0]["state"] == "idle"


def test_preserve_config(installed):
    from aidelegate.install import Writer, update_config
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('# Mi comentario\nmain = "claude"\n[limits]\ntimeout_min = 7\n[agents.codex]\nmodel = "special"\n[projects."/mi/repo"]\ncheck = "tests"\n')
    # Quoted headers deliberately take the conservative .nuevo path.
    original = path.read_text()
    assert not update_config(Writer(), "codex", "Ana", {})
    assert path.read_text() == original and path.with_name("config.toml.nuevo").exists()
    path.write_text('# Mi comentario\nmain = "claude"\n[limits]\ntimeout_min = 7\n[agents.codex]\nmodel = "special"\n')
    assert update_config(Writer(), "codex", "Ana", {"codex": {"bin": "codex"}})
    cfg = config.load()
    assert cfg["limits"]["timeout_min"] == 7 and cfg["agents"]["codex"]["model"] == "special"
    assert "# Mi comentario" in path.read_text()


def test_legacy_main_and_chain(installed):
    path = config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('[main]\nname = "codex"\n')
    cfg = config.load()
    assert cfg["main"] == "codex"
    cfg["fallback_order"] = ["codex", "claude", "agy"]
    assert routing.candidates("auto", "agy", cfg) == ["agy", "claude"]
    cfg["chain"] = ["agy", "codex", "claude", "main"]
    assert routing.next_in_chain("agy", cfg) == "claude"
    assert routing.next_in_chain("claude", cfg) == routing.MAIN


def test_live_doctor(installed):
    from aidelegate.install import Writer, update_config
    assert main(["setup", "--yes"]) == 0
    # Todos usan el protocolo stream-json del fake en esta prueba de diagnóstico.
    assert update_config(Writer(), "claude", "Ana", {n: {"type": "claude"} for n in ("codex", "agy")})
    assert main(["doctor", "--live"]) == 0


@pytest.mark.parametrize("auth_index,expected", [(0, True), (2, True), (3, None), (None, None)])
def test_agy_recent_logs(installed, capsys, auth_index, expected):
    root = installed / ".gemini/antigravity-cli/log"
    (root / "session.log").unlink()
    for index in range(4):
        path = root / f"session-{index}.log"
        path.write_text("AuthResult: private@example.test\n" if index == auth_index else "sin autenticación\n")
        os.utime(path, (100 - index, 100 - index))
    # Un archivo de token antiguo no indica el estado del llavero.
    (root.parent / "antigravity-oauth-token").write_text("token antiguo")
    detected = detect.detect_all()["agy"]
    assert detected.logged_in is expected
    assert "private@example.test" not in repr(detected)
    captured = capsys.readouterr()
    assert "private@example.test" not in captured.out + captured.err


def test_agy_stops_at_marker(installed, monkeypatch):
    path = installed / ".gemini/antigravity-cli/log/session.log"
    original_open = Path.open
    class MarkerOnly:
        def __init__(self, stream):
            self.stream = stream
            self.remaining = len(b"AuthResult:")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def read(self, size):
            assert size == 1 and self.remaining > 0, "Leyó el contenido privado después del marcador"
            self.remaining -= 1
            return self.stream.read(size)
    def guarded_open(current, *args, **kwargs):
        stream = original_open(current, *args, **kwargs)
        if current == path:
            assert kwargs["buffering"] == 0
            return MarkerOnly(stream)
        return stream
    monkeypatch.setattr(Path, "open", guarded_open)
    assert detect.agy_logged_in(installed) is True


def test_agy_missing_logs(installed):
    (installed / ".gemini/antigravity-cli/log/session.log").unlink()
    assert detect.agy_logged_in(installed) is None


@pytest.mark.parametrize("dry", [True, False])
def test_setup_login_messages(installed, capsys, dry):
    (installed / ".codex/auth.json").unlink()
    (installed / ".gemini/antigravity-cli/log/session.log").unlink()
    args = ["setup", "--yes"] + (["--dry-run"] if dry else [])
    assert main(args) == 0
    output = capsys.readouterr().out
    final = output.split("9. → Final\n", 1)[1]
    assert final.splitlines() == [
        "→ claude: abre claude una vez para iniciar sesión (si usas Claude Desktop ya está)",
        "→ inicia sesión: codex login",
        "→ inicia sesión: abre agy y sigue el flujo",
        "→ verifica: ai-delegate doctor --live",
    ]
    assert " | no\n" in output
    assert "desconocida (verifica con doctor --live)" in output


def test_setup_only_pending_logins(installed, capsys):
    assert main(["setup", "--yes", "--dry-run"]) == 0
    output = capsys.readouterr().out
    final = output.split("9. → Final\n", 1)[1]
    assert "→ claude:" in final
    assert "inicia sesión:" not in final
    assert " | sí\n" in output


def test_all_logged_in(capsys):
    from aidelegate.detect import Detected
    from aidelegate.install import login_steps
    detected = {name: Detected(name, name, "1", True) for name in ("claude", "codex", "agy")}
    login_steps(detected, list(detected))
    assert capsys.readouterr().out == "✓ Todo listo: ai-delegate doctor --live\n"


@pytest.mark.parametrize("dry", [True, False])
def test_setup_change_summaries(installed, capsys, dry):
    args = ["setup", "--yes"] + (["--dry-run"] if dry else [])
    assert main(args) == 0
    output = capsys.readouterr().out
    assert f"crear {config.config_path()}: claves de config cambiadas: main, user_name" in output
    assert "bloque de instrucciones nuevo" in output
    assert "7 hooks nuevos (0 ya estaban)" in output
    assert f"{AGY_RULES} permisos nuevos (0 ya estaban)" in output
    if dry:
        assert main(["setup", "--yes"]) == 0
        capsys.readouterr()
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "actualizar (con respaldo)" in output
    assert "claves de config cambiadas: ninguna" in output
    assert "bloque de instrucciones actualizado" in output
    assert "0 hooks nuevos (7 ya estaban)" in output
    assert f"0 permisos nuevos ({AGY_RULES} ya estaban)" in output


def test_setup_migration_summary(installed, capsys):
    path = installed / FILES["claude"]
    path.parent.mkdir()
    path.write_text("# Equipo de IA: Claude dirige\nViejo\n")
    assert main(["setup", "--yes", "--dry-run"]) == 0
    assert "bloque de instrucciones migrado" in capsys.readouterr().out
    assert START not in path.read_text()
