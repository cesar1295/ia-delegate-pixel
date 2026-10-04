"""Pruebas de v4.1: nivel de permisos por agente."""

import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aidelegate import config, permissions, routing, runners
from aidelegate.errors import DelegateError
from aidelegate.runners.agy import AgyRunner
from aidelegate.runners.claude import ClaudeRunner
from aidelegate.runners.codex import CodexRunner
from aidelegate.ui_server import create_server

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture
def perm_server(home, repo):
    orig = os.getcwd()
    os.chdir(repo)
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server.token
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        os.chdir(orig)


# --- 1. Catálogo y sincronización de agy --------------------------------------

def test_agy_catalog_and_sync(tmp_path):
    settings_file = tmp_path / "settings.json"
    initial_data = {
        "permissions": {
            "allow": [
                "command(custom_tool)",
                "command(npm test)",
                "command(ls)",
            ],
            "deny": [
                "command(custom_deny)",
            ],
        },
        "custom_key": 123,
    }
    settings_file.write_text(json.dumps(initial_data))

    # Sincronizar solo con 'lectura'
    data = permissions.sync_agy_settings(["lectura"], settings_path=settings_file)

    # 1. Crea respaldo
    backups = list(tmp_path.glob("settings.json.bak-ai-delegate-*"))
    assert len(backups) >= 1

    # 2. Agrega reglas de lectura
    for cmd in permissions.READ_COMMANDS:
        assert f"command({cmd})" in data["permissions"]["allow"]

    # 3. Quita solo catálogo de grupos inactivos (npm test fuera)
    assert "command(npm test)" not in data["permissions"]["allow"]

    # 4. Conserva reglas ajenas
    assert "command(custom_tool)" in data["permissions"]["allow"]
    assert data["custom_key"] == 123

    # 5. Deny siempre presente con always_denied y conserva ajenos
    for cmd in permissions.ALWAYS_DENIED:
        assert f"command({cmd})" in data["permissions"]["deny"]
    assert "command(custom_deny)" in data["permissions"]["deny"]

    # Sincronizar agregando 'pruebas'
    data2 = permissions.sync_agy_settings(["lectura", "pruebas"], settings_path=settings_file)
    assert "command(npm test)" in data2["permissions"]["allow"]
    assert "command(custom_tool)" in data2["permissions"]["allow"]

    # Volver a quitar 'pruebas'
    data3 = permissions.sync_agy_settings(["lectura"], settings_path=settings_file)
    assert "command(npm test)" not in data3["permissions"]["allow"]
    assert "command(custom_tool)" in data3["permissions"]["allow"]


# --- 2. Doctor detecta desincronización ----------------------------------------

def test_doctor_detects_agy_desynchronization(tmp_path):
    settings_file = tmp_path / "settings.json"
    # Settings solo con lectura
    permissions.sync_agy_settings(["lectura"], settings_path=settings_file)

    # Coincide con grupos = ['lectura']
    assert permissions.check_agy_settings_sync(["lectura"], settings_path=settings_file) is True

    # No coincide si config tiene ['lectura', 'pruebas']
    assert permissions.check_agy_settings_sync(["lectura", "pruebas"], settings_path=settings_file) is False

    # No coincide si falta deny
    broken = json.loads(settings_file.read_text())
    broken["permissions"]["deny"] = []
    settings_file.write_text(json.dumps(broken))
    assert permissions.check_agy_settings_sync(["lectura"], settings_path=settings_file) is False

    # Archivo inexistente
    assert permissions.check_agy_settings_sync(["lectura"], settings_path=tmp_path / "nada.json") is False


def test_doctor_command_detects_desync(home, tmp_path, monkeypatch):
    from aidelegate import install
    from aidelegate.detect import Detected

    monkeypatch.setattr(
        install,
        "detect_all",
        lambda: {
            "codex": Detected("codex", "/bin/codex", "1.0", True),
            "agy": Detected("agy", "/bin/agy", "1.0", True),
            "claude": Detected("claude", "/bin/claude", "1.0", True),
        },
    )

    agy_settings = tmp_path / ".gemini/antigravity-cli/settings.json"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Sin settings.json
    cfg = copy.deepcopy(config.DEFAULTS)
    results = install.run_doctor(live=False, cfg=cfg)
    perm_check = next((r for r in results if r["check"] == "Permisos de agy"), None)
    assert perm_check is not None
    assert perm_check["ok"] is False
    assert perm_check["fix"] == "guarda los permisos de agy en Ajustes"

    # Con settings sincronizado
    permissions.sync_agy_settings(["lectura"], settings_path=agy_settings)
    results_ok = install.run_doctor(live=False, cfg=cfg)
    perm_check_ok = next((r for r in results_ok if r["check"] == "Permisos de agy"), None)
    assert perm_check_ok is not None
    assert perm_check_ok["ok"] is True


# --- 3. API POST /api/permissions: 409 y 200 ----------------------------------

def test_api_permissions_expanding_needs_confirm_409(perm_server):
    url, token = perm_server
    port = url.rsplit(":", 1)[1]

    # Codex: ampliar network false -> true sin confirmación da 409
    payload = json.dumps({"agent": "codex", "changes": {"network": True}, "confirm": False}).encode("utf-8")
    req = Request(
        url + "/api/permissions",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 409
    data = json.load(exc.value)
    assert data["needs_confirm"] is True
    assert "Codex tendrá acceso a internet" in data["message"]

    # Con confirm: True -> 200 y actualiza
    payload_confirm = json.dumps({"agent": "codex", "changes": {"network": True}, "confirm": True}).encode("utf-8")
    req2 = Request(
        url + "/api/permissions",
        data=payload_confirm,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with urlopen(req2) as resp:
        assert resp.status == 200
        res_data = json.load(resp)
        assert res_data["permissions"]["network"] is True
    assert config.load()["agents"]["codex"]["permissions"]["network"] is True


def test_api_permissions_agy_expand_groups_409_and_200(perm_server, tmp_path, monkeypatch):
    url, token = perm_server
    port = url.rsplit(":", 1)[1]

    agy_settings = tmp_path / ".gemini/antigravity-cli/settings.json"
    monkeypatch.setattr(permissions, "default_agy_settings_path", lambda home=None: agy_settings)

    # Ampliar agregando 'pruebas'
    payload = json.dumps({"agent": "agy", "changes": {"groups": ["lectura", "pruebas"]}, "confirm": False}).encode("utf-8")
    req = Request(
        url + "/api/permissions",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 409
    data = json.load(exc.value)
    assert data["needs_confirm"] is True
    assert "agy podrá ejecutar:" in data["message"]

    # Con confirmación
    payload_ok = json.dumps({"agent": "agy", "changes": {"groups": ["lectura", "pruebas"]}, "confirm": True}).encode("utf-8")
    req_ok = Request(
        url + "/api/permissions",
        data=payload_ok,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with urlopen(req_ok) as resp:
        assert resp.status == 200
        res = json.load(resp)
        assert "pruebas" in res["permissions"]["groups"]
    assert agy_settings.exists()
    settings_data = json.loads(agy_settings.read_text())
    assert "command(npm test)" in settings_data["permissions"]["allow"]


def test_api_permissions_edit_false_to_true_expansion(perm_server):
    url, token = perm_server
    port = url.rsplit(":", 1)[1]

    # Reducir edit a False (no amplía -> 200 sin confirmación)
    payload_reduce = json.dumps({"agent": "codex", "changes": {"edit": False}, "confirm": False}).encode("utf-8")
    req = Request(
        url + "/api/permissions",
        data=payload_reduce,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with urlopen(req) as resp:
        assert resp.status == 200
        assert json.load(resp)["permissions"]["edit"] is False

    # Ampliar edit False -> True sin confirmación -> 409
    payload_expand = json.dumps({"agent": "codex", "changes": {"edit": True}, "confirm": False}).encode("utf-8")
    req2 = Request(
        url + "/api/permissions",
        data=payload_expand,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req2)
    assert exc.value.code == 409
    msg = json.load(exc.value)["message"]
    assert "podrá editar archivos en su carpeta de trabajo" in msg


def test_api_permissions_validation_errors(perm_server):
    url, token = perm_server
    port = url.rsplit(":", 1)[1]

    def post(body):
        req = Request(
            url + "/api/permissions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
        )
        return urlopen(req)

    # Clave no permitida para claude
    with pytest.raises(HTTPError) as exc:
        post({"agent": "claude", "changes": {"network": True}})
    assert exc.value.code == 400

    # Grupo desconocido para agy
    with pytest.raises(HTTPError) as exc:
        post({"agent": "agy", "changes": {"groups": ["lectura", "grupo_desconocido"]}})
    assert exc.value.code == 400

    # Agente desconocido
    with pytest.raises(HTTPError) as exc:
        post({"agent": "agente_fantasma", "changes": {"edit": True}})
    assert exc.value.code == 400


# --- 4. Efectos en runners (argv y prompt_hint) ------------------------------

def test_codex_network_changes_argv():
    cfg = copy.deepcopy(config.DEFAULTS)
    runner = runners.get("codex", cfg)
    argv_default = runner.argv("tarea", "write", Path("/repo"), None)
    assert not any("network_access=true" in arg for arg in argv_default)

    cfg["agents"]["codex"]["permissions"]["network"] = True
    runner_net = runners.get("codex", cfg)
    argv_net = runner_net.argv("tarea", "write", Path("/repo"), None)
    assert "-c" in argv_net
    assert "sandbox_workspace_write.network_access=true" in argv_net


def test_edit_false_forces_readonly_and_plan():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["agents"]["codex"]["permissions"]["edit"] = False
    cfg["agents"]["agy"]["permissions"]["edit"] = False
    cfg["agents"]["claude"]["permissions"]["edit"] = False

    codex = runners.get("codex", cfg)
    assert 'sandbox_mode="read-only"' in codex.argv("p", "write", Path("/r"), None)

    agy = runners.get("agy", cfg)
    assert "plan" in agy.argv("p", "write", Path("/r"), None)
    assert "accept-edits" not in agy.argv("p", "write", Path("/r"), None)

    claude = runners.get("claude", cfg)
    claude_argv = claude.argv("p", "write", Path("/r"), None)
    assert "plan" in claude_argv and "acceptEdits" not in claude_argv


def test_agy_prompt_hint_dynamic():
    cfg = copy.deepcopy(config.DEFAULTS)
    agy = runners.get("agy", cfg)
    hint_lectura = agy.prompt_hint
    assert "ls" in hint_lectura and "git status" in hint_lectura
    assert "Los tests los corre la herramienta que te llamó" in hint_lectura

    cfg["agents"]["agy"]["permissions"]["groups"] = ["lectura", "pruebas"]
    agy_pruebas = runners.get("agy", cfg)
    hint_pruebas = agy_pruebas.prompt_hint
    assert "npm test" in hint_pruebas
    assert "pytest" in hint_pruebas
    assert "Puedes correr las pruebas tú mismo." in hint_pruebas


# --- 5. Routing y pick_programmer con edit=false -----------------------------

def test_pick_programmer_skips_agent_without_edit():
    cfg = copy.deepcopy(config.DEFAULTS)
    now = datetime(2026, 10, 4, 15, 0, 0)
    # Por defecto elige agy
    agent, reason = routing.pick_programmer(cfg, {}, {}, now, kind="feature")
    assert agent == "agy"
    assert reason == "agy-first"

    # Si agy tiene edit=False, pick_programmer lo salta y elige codex
    cfg["agents"]["agy"]["permissions"]["edit"] = False
    agent2, reason2 = routing.pick_programmer(cfg, {}, {}, now, kind="feature")
    assert agent2 == "codex"
    assert "sin edición" in reason2


def test_resolve_target_excludes_edit_false_from_write():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["agents"]["agy"]["permissions"]["edit"] = False

    # Para tarea write ('feature'), da error si se destina a agy
    with pytest.raises(DelegateError, match="permiso de edición"):
        routing.resolve_target("agy", "feature", cfg)

    # Para tarea read ('summarize', 'review'), sí lo permite
    assert routing.resolve_target("agy", "summarize", cfg) == "agy"
    assert routing.resolve_target("agy", "review", cfg) == "agy"


# --- 6. POST /api/config rechaza tipo write a agente sin edición -------------

def test_api_post_config_rejects_write_kind_for_agent_without_edit(perm_server):
    url, token = perm_server
    port = url.rsplit(":", 1)[1]

    # Primero quitamos permiso de edición a agy
    payload_perm = json.dumps({"agent": "agy", "changes": {"edit": False}, "confirm": True}).encode("utf-8")
    req_perm = Request(
        url + "/api/permissions",
        data=payload_perm,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with urlopen(req_perm) as resp:
        assert resp.status == 200

    # Ahora intentamos asignar tipo 'feature' (write) a agy via POST /api/config -> debe dar 400
    payload_cfg = json.dumps({"changes": {"routing.feature": "agy"}}).encode("utf-8")
    req_cfg = Request(
        url + "/api/config",
        data=payload_cfg,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req_cfg)
    assert exc.value.code == 400

    # Pero asignar tipo 'review' (read) a agy sí se permite -> 200
    payload_read = json.dumps({"changes": {"routing.review": "agy"}}).encode("utf-8")
    req_read = Request(
        url + "/api/config",
        data=payload_read,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": f"http://127.0.0.1:{port}"},
    )
    with urlopen(req_read) as resp:
        assert resp.status == 200


# --- 7. GET /api/config incluye permissions, catálogo y always_denied --------

def test_api_get_config_includes_permissions_catalog_and_denied(perm_server):
    url, _ = perm_server
    with urlopen(url + "/api/config") as resp:
        assert resp.status == 200
        data = json.load(resp)
        assert "catalog" in data or "agy_catalog" in data
        assert "always_denied" in data
        assert "rm" in data["always_denied"]
        assert "sudo" in data["always_denied"]

        agents = data["config"]["agents"]
        assert "permissions" in agents["codex"]
        assert agents["codex"]["permissions"]["edit"] is True
        assert agents["codex"]["permissions"]["network"] is False
        assert "permissions" in agents["agy"]
        assert agents["agy"]["permissions"]["groups"] == ["lectura"]
