"""Cuotas reales de Codex y estimaciones por presupuesto diario."""

from __future__ import annotations

import json
import math
import statistics
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import config, usage
from .runs import RunMeta

_CACHE: dict[str, tuple[float, dict]] = {}


def empty() -> dict:
    return {"source": None, "remaining_pct": None, "estimated": False, "stale": False, "windows": []}


def _windows(windows: list[dict], source: str) -> dict:
    used = [w["used_pct"] for w in windows if isinstance(w.get("used_pct"), (int, float))]
    return {"source": source if windows else None,
            "remaining_pct": round(100 - max(used)) if used else None,
            "estimated": False, "stale": False, "windows": windows}


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
    if name == "claude":
        try:
            data = json.loads((config.data_dir() / "claude-quota.json").read_text())
            windows = [w for w in data.get("windows", []) if isinstance(w, dict)
                       and isinstance(w.get("used_pct"), (int, float)) and math.isfinite(w["used_pct"])]
            ts = data.get("ts")
            elapsed = _age(ts, now)
            active = any((reset := usage.parse_ts(w.get("resets_at"), now)) is not None and reset > now
                         for w in windows)
            if windows and (0 <= elapsed < 900 or (elapsed >= 900 and active)):
                return dict(_windows(windows, "claude"), stale=elapsed >= 900, ts=ts)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        limit = cfg.get("agents", {}).get(name, {}).get("five_hour_token_budget", 0)
        limit = limit if limit > 0 else calibration()["budget"]
        if not limit:
            return empty()
        used = 100 * usage.claude_tokens_5h(cfg, now) / limit
        return {"source": "estimado", "remaining_pct": max(0, 100 - used),
                "estimated": True, "stale": False,
                "windows": [{"label": "5 h", "used_pct": used, "resets_at": None}]}
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


def _calibration_samples() -> list[dict]:
    try:
        data = json.loads((config.data_dir() / "claude-calibration.json").read_text())
        return [s for s in data if isinstance(s, dict)
                and isinstance(s.get("budget"), (int, float))
                and math.isfinite(s["budget"]) and s["budget"] > 0][-10:] if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []


def calibration() -> dict:
    samples = _calibration_samples()
    return {"budget": round(statistics.median(s["budget"] for s in samples)) if samples else None,
            "samples": len(samples)}


def _calibration_tokens(now: datetime, deadline: float) -> int | None:
    # A daemon worker keeps a blocked synchronous filesystem read from holding
    # up the statusline or process exit. Only this caller can persist a sample.
    done = threading.Event()
    result: list[int] = []

    def read() -> None:
        try:
            tokens = usage.claude_tokens_5h(config.load(), now, deadline=deadline)
            if time.monotonic() < deadline:
                result.append(tokens)
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=read, daemon=True).start()
    if not done.wait(max(0, deadline - time.monotonic())):
        return None
    return result[0] if result else None


def calibrate(windows: list[dict], now: datetime) -> None:
    """Best effort, bounded transcript scan using usage's shared file cache."""
    temporary = None
    try:
        used = next((w["used_pct"] for w in windows if w.get("label") == "5 h"), 0)
        if not math.isfinite(used) or used < 5:
            return
        deadline = time.monotonic() + 0.3
        tokens = _calibration_tokens(now, deadline)
        if tokens is None or tokens <= 0 or time.monotonic() >= deadline:
            return
        samples = (_calibration_samples() + [{"ts": now.isoformat(timespec="seconds"),
                    "used_pct": used, "tokens_5h": tokens, "budget": tokens / (used / 100)}])[-10:]
        root = config.data_dir()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=root, delete=False, encoding="utf-8") as fh:
            temporary = Path(fh.name)
            json.dump(samples, fh)
        temporary.replace(root / "claude-calibration.json")
    except Exception:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
