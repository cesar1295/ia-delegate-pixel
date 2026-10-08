"""Catálogo, niveles de razonamiento y validación v5.5."""

import json
import os
import time
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from aidelegate import config, models, runners
from aidelegate.ui_server import Handler, _validate_change_value


def test_codex_catalog_filters_and_reads_default(isolated_home):
    home = Path(os.environ["CODEX_HOME"])
    (home / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-6-sol", "display_name": "GPT-6-Sol", "visibility": "list",
         "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}],
         "default_reasoning_level": "high"},
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"}]}))
    (home / "config.toml").write_text('model = "gpt-6-sol"\nmodel_reasoning_effort = "low"\n')
    result = models.catalog("codex", config.DEFAULTS)
    assert result["source"] == "codex"
    assert result["models"] == [{"id": "gpt-6-sol", "label": "GPT-6-Sol",
                                  "efforts": ["low", "high"], "default_effort": "high"}]
    assert result["default"] == {"model": "gpt-6-sol", "label": "GPT-6-Sol", "effort": "low"}


def test_agy_cache_refresh_failure_and_label(isolated_home, monkeypatch):
    settings = Path.home() / ".gemini/antigravity-cli/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "Gemini 3.8 Flash (High)"}))
    first = models.catalog("agy", config.DEFAULTS)
    assert first["models"][0]["id"] == "gemini-3.8-flash-high"
    assert first["default"]["model"] == "gemini-3.8-flash-high"
    cache = config.data_dir() / "models-agy.json"
    cached = json.loads(cache.read_text())
    cached["ts"] = time.time() - 86401
    cache.write_text(json.dumps(cached))
    broken = {**config.DEFAULTS, "agents": {**config.DEFAULTS["agents"],
              "agy": {**config.DEFAULTS["agents"]["agy"], "bin": "/missing/agy"}}}
    stale = models.catalog("agy", broken)
    assert stale["models"] == first["models"] and stale["error"].startswith("no pude listar")
    cached["ts"] = time.time()
    cache.write_text(json.dumps(cached))
    assert models.catalog("agy", broken)["error"] is None
    assert models.catalog("agy", broken, refresh=True)["error"]


def test_fixed_generic_and_bad_cache(isolated_home):
    claude = models.catalog("claude", config.DEFAULTS)
    assert claude["source"] == "fijo" and len(claude["models"]) == 4
    assert claude["models"][-1]["efforts"] == []
    assert models.catalog("other", {"agents": {"other": {"type": "generic"}}})["models"] == []
    (Path(os.environ["CODEX_HOME"]) / "models_cache.json").write_text("not json")
    assert models.catalog("codex", config.DEFAULTS)["error"]


def test_runner_effort_flags(isolated_home):
    cwd = Path.cwd()
    for name, expected in (("codex", 'model_reasoning_effort="high"'),
                           ("claude", "--effort"), ("agy", "--effort")):
        runner = runners.get(name, config.DEFAULTS, effort="high")
        for resume in (None, "thread"):
            assert expected in runner.argv("prompt", "read", cwd, resume)
        assert expected not in runners.get(name, config.DEFAULTS).argv("prompt", "read", cwd, None)


def test_model_validation(isolated_home):
    cfg = config.DEFAULTS
    assert _validate_change_value("agents.codex.model", "gpt-6/sol:[high]", cfg) is None
    assert _validate_change_value("agents.codex.model", "x" * 81, cfg)
    assert _validate_change_value("agents.codex.model", "bad model", cfg)
    assert _validate_change_value("agents.codex.effort", "ultra", cfg) is None
    assert _validate_change_value("agents.codex.effort", "bad", cfg)


def test_models_api_without_socket(isolated_home):
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = Message()
    handler.headers["Host"] = "localhost:8765"
    handler.path = "/api/models?agent=claude"
    replies = []
    handler._json = lambda data, status=200: replies.append((data, status))
    handler.do_GET()
    assert replies[0][1] == 200 and replies[0][0]["claude"]["source"] == "fijo"


def test_agy_offline_never_runs_cli(isolated_home, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no debe ejecutar agy")
    monkeypatch.setattr(models.subprocess, "run", boom)
    (config.data_dir()).mkdir(parents=True, exist_ok=True)
    (config.data_dir() / "models-agy.json").write_text(json.dumps(
        {"ts": 0, "models": [{"id": "g-high", "label": "G (High)", "efforts": [], "default_effort": ""}]}))
    settings = Path.home() / ".gemini/antigravity-cli/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"model": "G (High)"}))
    result = models.catalog("agy", config.DEFAULTS, offline=True)
    assert result["error"] is None and result["default"] == {"model": "g-high", "label": "G (High)", "effort": ""}
