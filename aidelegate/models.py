"""Catálogos de modelos disponibles sin leer credenciales."""

from __future__ import annotations

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

from .config import data_dir


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _codex_home(cfg: dict) -> Path:
    custom = cfg.get("agents", {}).get("codex", {}).get("home") or os.environ.get("CODEX_HOME")
    return Path(custom).expanduser() if custom else Path.home() / ".codex"


def _model(item: dict, efforts: list[str] | None = None) -> dict:
    return {"id": item["id"], "label": item["label"], "efforts": efforts if efforts is not None else [],
            "default_effort": item.get("default_effort", "")}


def catalog(name: str, cfg: dict, refresh: bool = False, offline: bool = False) -> dict:
    """offline=True nunca ejecuta el CLI (agy usa solo su caché en disco)."""
    result = {"models": [], "default": {"model": "", "label": "", "effort": ""},
              "source": "ninguno", "error": None}
    try:
        agent = cfg.get("agents", {}).get(name, {})
        kind = agent.get("type", name)
        if kind == "codex":
            result["source"] = "codex"
            home = _codex_home(cfg)
            try:
                raw = _read_json(home / "models_cache.json")
                result["models"] = [_model({"id": row["slug"], "label": row["display_name"],
                    "default_effort": row.get("default_reasoning_level", "")},
                    [level["effort"] for level in row.get("supported_reasoning_levels", [])])
                    for row in raw.get("models", []) if row.get("visibility") == "list"]
            except FileNotFoundError:
                pass
            try:
                settings = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
                result["default"]["model"] = settings.get("model", "")
                result["default"]["effort"] = settings.get("model_reasoning_effort", "")
            except FileNotFoundError:
                pass
        elif kind == "agy":
            result["source"] = "agy"
            cache_path = data_dir() / "models-agy.json"
            try:
                cached = _read_json(cache_path)
            except (OSError, ValueError):
                cached = {}
            rows = cached.get("models", []) if isinstance(cached.get("models"), list) else []
            if not offline and (refresh or time.time() - cached.get("ts", 0) >= 86400):
                try:
                    binary = agent.get("bin", "agy")
                    proc = subprocess.run([binary, "models"], capture_output=True, text=True, timeout=15,
                                          check=True)
                    rows = [_model({"id": parts[0], "label": parts[1]})
                            for line in proc.stdout.splitlines() if len(parts := line.split("\t", 1)) == 2]
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps({"ts": time.time(), "models": rows}), encoding="utf-8")
                except (OSError, subprocess.SubprocessError) as exc:
                    reason = str(exc).splitlines()[0][:120] or type(exc).__name__
                    result["error"] = f"no pude listar los modelos de agy: {reason}"
            result["models"] = rows
            try:
                label = _read_json(Path.home() / ".gemini/antigravity-cli/settings.json").get("model", "")
                match = next((row for row in rows if row.get("label") == label), None)
                if match:
                    result["default"].update(model=match["id"], label=label)
            except (OSError, ValueError):
                pass
        elif kind == "claude":
            result["source"] = "fijo"
            result["models"] = [_model({"id": mid, "label": label},
                [] if "haiku" in mid else ["low", "medium", "high", "xhigh", "max"])
                for mid, label in (("claude-fable-5-1", "Claude Fable 5.1"),
                                   ("claude-opus-5-5", "Claude Opus 5.5"),
                                   ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
                                   ("claude-haiku-4-5", "Claude Haiku 4.5"))]
            try:
                result["default"]["model"] = _read_json(Path.home() / ".claude/settings.json").get("model", "")
            except (OSError, ValueError):
                pass
        default = result["default"]
        default["label"] = next((m["label"] for m in result["models"] if m["id"] == default["model"]),
                                default["model"])
    except Exception as exc:
        result["models"] = []
        result["error"] = str(exc).splitlines()[0][:160] or type(exc).__name__
    return result
