"""Pruebas de Backend v4: estrategia agy primero, escalamiento, servicio y API."""

import copy
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aidelegate import config, routing, runs
from aidelegate.cli import main
from aidelegate.ui_server import create_server

FAKES = Path(__file__).parent / "fakes"


# --- 1. Estrategia y pick_programmer -----------------------------------------

def test_pick_programmer_agy_default():
    cfg = copy.deepcopy(config.DEFAULTS)
    now = datetime(2026, 10, 4, 15, 0, 0)
    agent, reason = routing.pick_programmer(cfg, {}, {}, now)
    assert agent == "agy"
    assert reason == "agy-first"


def test_pick_programmer_codex_when_agy_under_quota_floor():
    cfg = copy.deepcopy(config.DEFAULTS)
    now = datetime(2026, 10, 4, 15, 0, 0)
    quotas = {"agy": 10, "codex": 80}
    agent, reason = routing.pick_programmer(cfg, quotas, {}, now)
    assert agent == "codex"
    assert reason == "agy sin cuota"


def test_pick_programmer_codex_when_agy_exhausted_30_min_ago():
    cfg = copy.deepcopy(config.DEFAULTS)
    now = datetime(2026, 10, 4, 15, 0, 0)
    recent = {"agy": ("cuota-agotada", now - timedelta(minutes=30))}
    agent, reason = routing.pick_programmer(cfg, {}, recent, now)
    assert agent == "codex"
    assert reason == "agy sin cuota"


def test_pick_programmer_agy_when_exhausted_2_hours_ago():
    cfg = copy.deepcopy(config.DEFAULTS)
    now = datetime(2026, 10, 4, 15, 0, 0)
    recent = {"agy": ("cuota-agotada", now - timedelta(hours=2))}
    agent, reason = routing.pick_programmer(cfg, {}, recent, now)
    assert agent == "agy"
    assert reason == "agy-first"


def test_pick_programmer_mode_routing_respects_routing():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["strategy"]["mode"] = "routing"
    now = datetime(2026, 10, 4, 15, 0, 0)
    agent, reason = routing.pick_programmer(cfg, {}, {}, now, kind="feature")
    assert agent == "codex"
    assert reason == "routing"


def test_read_kinds_unaffected_by_strategy():
    cfg = copy.deepcopy(config.DEFAULTS)
    assert cfg["strategy"]["mode"] == "agy-first"
    assert routing.resolve_target("auto", "review", cfg) == "codex"
    assert routing.resolve_target("auto", "research", cfg) == "agy"
    assert routing.resolve_target("auto", "summarize", cfg) == "agy"


def test_agent_disabled_excluded_from_routing_and_chain():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["agents"]["agy"]["enabled"] = False
    assert routing.resolve_target("auto", "feature", cfg) == "codex"
    assert routing.next_in_chain("agy", cfg) == "codex"
    cfg["agents"]["codex"]["enabled"] = False
    assert routing.next_in_chain("agy", cfg) == routing.MAIN


# --- 2. Escalamiento automático ----------------------------------------------

def test_auto_escalate_after_n_failed_checks(home, repo, capsys):
    cfg_path = config.config_path()
    cfg_path.write_text(
        f'[agents.codex]\nbin = "{FAKES / "fake_codex.py"}"\n'
        f'[agents.agy]\nbin = "{FAKES / "fake_agy.py"}"\n'
        '[strategy]\nmode = "agy-first"\nescalate_after = 2\n'
    )
    code = main(["run", "--dir", str(repo), "--check", "false", "tarea que falla"])
    assert code == 3
    meta = runs.load(runs.resolve("last"))
    assert meta.status == "escalado-a-main"
    assert meta.escalated_from == ["agy", "codex"]
    err = capsys.readouterr().err
    assert "aviso: agy no lo resolvió en 2 correcciones; pasa a codex" in err
    assert "aviso: codex no lo resolvió en 2 correcciones; pasa a main" in err


def test_feedback_auto_escalates_when_corrections_reach_limit(home, repo):
    cfg_path = config.config_path()
    cfg_path.write_text(
        f'[agents.codex]\nbin = "{FAKES / "fake_codex.py"}"\n'
        f'[agents.agy]\nbin = "{FAKES / "fake_agy.py"}"\n'
        '[strategy]\nmode = "agy-first"\nescalate_after = 2\n'
    )
    assert main(["run", "--dir", str(repo), "--check", "none", "crea archivo.txt"]) == 0
    rid = runs.load(runs.resolve("last")).run_id
    assert runs.load(runs.resolve("last")).agent == "agy"

    assert main(["feedback", rid, "primer cambio"]) == 0
    m1 = runs.load(runs.resolve("last"))
    assert m1.agent == "agy"
    assert m1.corrections == 1

    assert main(["feedback", rid, "segundo cambio"]) == 0
    m2 = runs.load(runs.resolve("last"))
    assert m2.agent == "agy"
    assert m2.corrections == 2

    # feedback con correcciones >= escalate_after (2) auto-escala a codex
    assert main(["feedback", rid, "tercer cambio que escala"]) == 0
    m3 = runs.load(runs.resolve("last"))
    assert m3.agent == "codex"
    assert m3.escalated_from == ["agy"]
    sent = (runs.resolve("last") / "prompt.md").read_text()
    assert "tercer cambio que escala" in sent


# --- 3. Servicio del sistema -------------------------------------------------

def test_service_install_uninstall_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    script = bin_dir / "systemctl"
    script.write_text(
        f'#!/bin/sh\necho "$@" >> "{systemctl_log}"\n'
        'if [ "$1" = "--user" ] && [ "$2" = "is-active" ]; then\n'
        '  echo "active"\n'
        'fi\nexit 0\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(sys, "platform", "linux")

    unit = tmp_path / ".config/systemd/user/ai-delegate-ui.service"
    assert main(["ui", "--service", "install", "--port", "8888"]) == 0
    assert unit.exists()
    content = unit.read_text()
    assert sys.executable in content
    assert "ai_delegate.py" in content
    assert "--port 8888" in content
    assert "--no-open" in content
    log_text = systemctl_log.read_text()
    assert "--user daemon-reload" in log_text
    assert "--user enable --now ai-delegate-ui.service" in log_text

    assert main(["ui", "--service", "status", "--port", "8888"]) == 0
    out = capsys.readouterr().out
    assert "activo" in out and "8888" in out

    assert main(["ui", "--service", "uninstall", "--port", "8888"]) == 0
    assert not unit.exists()
    log_after = systemctl_log.read_text()
    assert "--user disable --now ai-delegate-ui.service" in log_after


# --- 4. API de configuración -------------------------------------------------

@pytest.fixture
def v4_server(home, repo):
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


def test_api_token_in_html_meta(v4_server):
    url, token = v4_server
    with urlopen(url + "/") as resp:
        html = resp.read().decode("utf-8")
        assert f'<meta name="ai-delegate-token" content="{token}">' in html


def test_api_post_without_token_returns_403(v4_server):
    url, _ = v4_server
    req = Request(url + "/api/config", data=b'{"changes":{}}', headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 403


def test_api_post_foreign_origin_returns_403(v4_server):
    url, token = v4_server
    req = Request(
        url + "/api/config",
        data=b'{"changes":{}}',
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token, "Origin": "http://evil.com"},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 403


def test_api_post_valid_token_updates_config_and_creates_backup(v4_server):
    url, token = v4_server
    port = url.rsplit(":", 1)[1]
    payload = json.dumps({"changes": {"user_name": "AnaV4"}}).encode("utf-8")
    req = Request(
        url + "/api/config",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-AI-Delegate-Token": token,
            "Origin": f"http://127.0.0.1:{port}",
        },
    )
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.load(resp)
        assert data["config"]["user_name"] == "AnaV4"
    assert config.load()["user_name"] == "AnaV4"
    backups = list(config.config_path().parent.glob(config.config_path().name + ".bak-ai-delegate-*"))
    assert len(backups) >= 1


def test_api_post_disallowed_key_returns_400(v4_server):
    url, token = v4_server
    payload = json.dumps({"changes": {"clave_no_permitida": "valor"}}).encode("utf-8")
    req = Request(
        url + "/api/config",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 400
    body = json.load(exc.value)
    assert "clave_no_permitida" in body.get("invalid", []) or "clave_no_permitida" in body.get("error", "")


def test_api_post_invalid_color_returns_400(v4_server):
    url, token = v4_server
    payload = json.dumps({"changes": {"agents.codex.color": "azul"}}).encode("utf-8")
    req = Request(
        url + "/api/config",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req)
    assert exc.value.code == 400


def test_api_get_config(v4_server):
    url, _ = v4_server
    with urlopen(url + "/api/config") as resp:
        assert resp.status == 200
        data = json.load(resp)
        assert "config" in data
        assert "detected" in data
        assert "kinds" in data
        assert "path" in data


def test_api_post_doctor(v4_server):
    url, token = v4_server
    payload = json.dumps({"live": False}).encode("utf-8")
    req = Request(
        url + "/api/doctor",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token},
    )
    with urlopen(req) as resp:
        assert resp.status == 200
        items = json.load(resp)
        assert isinstance(items, list)
        assert all("check" in it and "ok" in it and "fix" in it for it in items)


def test_api_get_state_includes_strategy_and_ui(v4_server):
    url, _ = v4_server
    with urlopen(url + "/api/state") as resp:
        assert resp.status == 200
        data = json.load(resp)
        assert "strategy" in data
        assert "ui" in data


def test_api_post_master(v4_server, monkeypatch):
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
    monkeypatch.setattr(install, "instructions", lambda *args, **kwargs: None)
    monkeypatch.setattr(install, "hooks", lambda *args, **kwargs: None)

    url, token = v4_server
    # Master valid
    payload = json.dumps({"name": "codex"}).encode("utf-8")
    req = Request(
        url + "/api/master",
        data=payload,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token},
    )
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.load(resp)
        assert data.get("ok") is True

    # Master invalid
    payload_bad = json.dumps({"name": "no-existe"}).encode("utf-8")
    req_bad = Request(
        url + "/api/master",
        data=payload_bad,
        headers={"Content-Type": "application/json", "X-AI-Delegate-Token": token},
    )
    with pytest.raises(HTTPError) as exc:
        urlopen(req_bad)
    assert exc.value.code == 400


def test_report_elegido_printed_in_run(home, repo, capsys):
    cfg_path = config.config_path()
    cfg_path.write_text(
        f'[agents.codex]\nbin = "{FAKES / "fake_codex.py"}"\n'
        f'[agents.agy]\nbin = "{FAKES / "fake_agy.py"}"\n'
        '[strategy]\nmode = "agy-first"\n'
    )
    assert main(["run", "--dir", str(repo), "--check", "none", "crea archivo.txt"]) == 0
    out = capsys.readouterr().out
    assert "elegido: agy (agy-first)" in out


def test_ui_app_browser_selection(monkeypatch):
    from aidelegate.service import open_app
    launched = []
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "chromium" else None)
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kwargs: launched.append(cmd))
    monkeypatch.setattr("aidelegate.service.is_server_responding", lambda port: True)
    assert open_app(9999) == 0
    assert launched and "/usr/bin/chromium" in launched[0][0]
    assert "--app=http://127.0.0.1:9999" in launched[0][1]

