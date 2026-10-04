"""Cuotas reales de Codex y estimaciones por presupuesto diario."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .runs import RunMeta

_CACHE: dict[str, tuple[float, dict]] = {}


def empty() -> dict:
    return {"source": None, "remaining_pct": None, "estimated": False, "windows": []}


def _windows(windows: list[dict], source: str) -> dict:
    used = [w["used_pct"] for w in windows if isinstance(w.get("used_pct"), (int, float))]
    return {"source": source if windows else None,
            "remaining_pct": round(100 - max(used)) if used else None,
            "estimated": False, "windows": windows}


def codex(home: str = "", now: datetime | None = None) -> dict:
    now = now or datetime.now()
    root = (Path(home).expanduser() if home else Path.home()) / ".codex/sessions"
    key = str(root)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    result = empty()
    files = []
    for offset in range(7):
        date = now - timedelta(days=offset)
        folder = root / date.strftime("%Y/%m/%d")
        try:
            files.extend(folder.rglob("rollout-*.jsonl"))
        except OSError:
            continue
    try:
        latest = max(files, key=lambda p: p.stat().st_mtime) if files else None
        if latest:
            with latest.open("rb") as fh:
                if latest.stat().st_size > 2 * 1024 * 1024:
                    fh.seek(-512 * 1024, 2)
                    fh.readline()  # omite la primera línea truncada
                lines = fh.read().decode(errors="replace").splitlines()
            for line in reversed(lines):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                limits = _rate_limits(event)
                if limits is None:
                    continue
                windows = []
                for name in ("primary", "secondary"):
                    window = limits.get(name)
                    if not isinstance(window, dict):
                        continue
                    minutes = window.get("window_minutes")
                    reset = window.get("resets_at")
                    windows.append({"label": {300: "5 h", 10080: "7 d"}.get(minutes, f"{minutes} min"),
                                    "used_pct": window.get("used_percent", window.get("used_pct")),
                                    "resets_at": datetime.fromtimestamp(reset).astimezone().isoformat()
                                    if isinstance(reset, (int, float)) else None})
                result = _windows(windows, "codex")
                break
    except (OSError, ValueError, OverflowError, TypeError):
        pass
    _CACHE[key] = (time.monotonic(), result)
    return result


def _rate_limits(event: object) -> dict | None:
    if isinstance(event, dict):
        if isinstance(event.get("rate_limits"), dict):
            return event["rate_limits"]
        for value in event.values():
            found = _rate_limits(value)
            if found is not None:
                return found
    return None


def budget(name: str, agent: dict, metas: list[RunMeta], now: datetime) -> dict:
    used = 0
    for meta in metas:
        for entry in meta.history:
            if entry.get("agent", meta.agent) != name:
                continue
            if str(entry.get("ts", meta.created_at))[:10] != now.date().isoformat():
                continue
            usage = entry.get("usage") or {}
            total = usage.get("total_tokens")
            used += total if total is not None else (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
    limit = agent.get("daily_token_budget", 0)
    pct = 100 * used / limit if limit > 0 else None
    return {"source": "budget", "remaining_pct": round(max(0, 100 - pct)) if pct is not None else None,
            "estimated": True, "windows": [{"label": "hoy" if limit > 0 else f"hoy: {used} tokens",
                                              "used_pct": pct, "resets_at": None}]}


def get(name: str, cfg: dict, metas: list[RunMeta], now: datetime | None = None) -> dict:
    now = now or datetime.now()
    if name == cfg["main"]["name"]:
        try:
            data = json.loads((config.data_dir() / "claude-quota.json").read_text())
            return _windows(data["windows"], "archivo")
        except (OSError, ValueError, KeyError, TypeError):
            return empty()
    agent = cfg["agents"].get(name, {})
    source = agent.get("quota", "none")
    if source == "codex":
        result = dict(codex(agent.get("home", ""), now))
    elif source == "budget":
        result = budget(name, agent, metas, now)
    else:
        result = empty()
    latest = max((m for m in metas if m.agent == name), key=lambda m: m.created_at, default=None)
    if latest and latest.status == "cuota-agotada" and 0 <= _age(latest.updated_at, now) < 1800:
        result.update(remaining_pct=0, source="agotada")
    return result


def _age(ts: str, now: datetime) -> float:
    try:
        date = datetime.fromisoformat(ts)
        if date.tzinfo is None and now.tzinfo is not None:
            date = date.replace(tzinfo=now.tzinfo)
        elif date.tzinfo is not None and now.tzinfo is None:
            date = date.astimezone().replace(tzinfo=None)
        return (now - date).total_seconds()
    except (ValueError, TypeError):
        return float("inf")
