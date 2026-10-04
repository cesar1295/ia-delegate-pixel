"""Cálculo de uso de tokens y tiempo de desarrollo para todas las IAs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config, runs
from .runs import RunMeta

_FILE_CACHE: dict[tuple[str, float, int], tuple[list[tuple[datetime, int]], list[datetime]]] = {}


def normalize_tz(dt: datetime, ref: datetime) -> datetime:
    if dt.tzinfo is None and ref.tzinfo is not None:
        return dt.replace(tzinfo=ref.tzinfo)
    elif dt.tzinfo is not None and ref.tzinfo is None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def parse_ts(val: Any, ref: datetime | None = None) -> datetime | None:
    if val is None or val == "":
        return None
    ref = ref or datetime.now()
    if isinstance(val, (int, float)):
        sec = val / 1000.0 if val > 1e11 else float(val)
        try:
            dt = datetime.fromtimestamp(sec)
            return normalize_tz(dt, ref)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(val, str):
        try:
            s = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return normalize_tz(dt, ref)
        except (ValueError, TypeError):
            return None
    if isinstance(val, datetime):
        return normalize_tz(val, ref)
    return None


def format_time(seconds: int | float | None) -> str:
    if seconds is None:
        return "sin dato"
    s = round(float(seconds))
    if s >= 3600:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h} h {m} min"
    if s >= 60:
        return f"{s // 60} min"
    return f"{s} s"


def format_tokens(tokens: int | None) -> str:
    if tokens is None:
        return "sin dato"
    t = int(tokens)
    if t >= 1_000_000:
        return f"{t / 1_000_000:.1f} M"
    if t >= 1_000:
        k = t / 1000.0
        if k >= 100 or k.is_integer() or t % 1000 == 0:
            return f"{round(k)} k"
        return f"{k:.1f}".rstrip("0").rstrip(".") + " k"
    return str(t)


def ensure_work_log() -> Path:
    """Rellena work.jsonl desde history de corridas existentes si no existe."""
    path = config.data_dir() / "work.jsonl"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    root = config.runs_dir()
    if root.exists():
        dirs = sorted(p for p in root.glob("*") if (p / "meta.json").exists())
        for run_dir in dirs:
            try:
                meta = runs.load(run_dir)
                for entry in meta.history:
                    ts = entry.get("ts") or meta.created_at
                    agent = entry.get("agent") or meta.agent
                    sec = round(float(entry.get("seconds", 0.0)), 1)
                    entries.append({
                        "ts": ts,
                        "agent": agent,
                        "seconds": sec,
                        "kind": meta.kind,
                        "repo": meta.repo,
                        "run_id": meta.run_id,
                    })
            except Exception:
                continue
    with open(path, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def record_work_round(agent: str, seconds: float, kind: str, repo: str, run_id: str,
                      ts: str | None = None) -> None:
    """Registra una ronda de trabajo en work.jsonl."""
    ensure_work_log()
    ts = ts or datetime.now().isoformat(timespec="seconds")
    entry = {
        "ts": ts,
        "agent": agent,
        "seconds": round(float(seconds), 1),
        "kind": kind,
        "repo": repo,
        "run_id": run_id,
    }
    path = config.data_dir() / "work.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_work_rows() -> list[dict[str, Any]]:
    """Lee todas las filas de work.jsonl."""
    ensure_work_log()
    path = config.data_dir() / "work.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _read_claude_transcripts(home_path: Path, now: datetime, days: int = 30) -> tuple[list[tuple[datetime, int]], list[datetime]]:
    projects_dir = home_path / ".claude/projects"
    usage_entries: list[tuple[datetime, int]] = []
    timestamps: list[datetime] = []
    if not projects_dir.exists():
        return usage_entries, timestamps

    cutoff = (now - timedelta(days=days)).timestamp()
    candidates: list[Path] = []
    for pattern in ("*/*.jsonl", "*.jsonl"):
        for p in projects_dir.glob(pattern):
            if p.is_file() and p not in candidates:
                try:
                    if p.stat().st_mtime >= cutoff:
                        candidates.append(p)
                except OSError:
                    pass

    for p in candidates:
        try:
            stat = p.stat()
            key = (str(p.resolve()), stat.st_mtime, stat.st_size)
            if key in _FILE_CACHE:
                cached_usage, cached_ts = _FILE_CACHE[key]
                usage_entries.extend(cached_usage)
                timestamps.extend(cached_ts)
                continue

            file_usage: list[tuple[datetime, int]] = []
            file_ts: list[datetime] = []
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    ts_raw = event.get("timestamp") or event.get("ts")
                    if not ts_raw and isinstance(event.get("message"), dict):
                        ts_raw = event["message"].get("timestamp")
                    ts = parse_ts(ts_raw, now)
                    if ts is not None:
                        file_ts.append(ts)

                    is_assistant = (
                        event.get("type") == "assistant"
                        or (isinstance(event.get("message"), dict) and event["message"].get("type") == "assistant")
                    )
                    if is_assistant:
                        msg = event.get("message") if isinstance(event.get("message"), dict) else event
                        u = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
                        if u:
                            input_tokens = u.get("input_tokens") or 0
                            cache_creation = u.get("cache_creation_input_tokens") or 0
                            output_tokens = u.get("output_tokens") or 0
                            tokens = input_tokens + cache_creation + output_tokens
                            if ts is not None and tokens > 0:
                                file_usage.append((ts, tokens))

            _FILE_CACHE[key] = (file_usage, file_ts)
            usage_entries.extend(file_usage)
            timestamps.extend(file_ts)
        except OSError:
            pass

    return usage_entries, timestamps


def _read_codex_rollouts(home_path: Path, now: datetime, days: int = 30) -> tuple[list[tuple[datetime, int]], list[datetime]]:
    sessions_dir = home_path / ".codex/sessions"
    usage_entries: list[tuple[datetime, int]] = []
    timestamps: list[datetime] = []
    if not sessions_dir.exists():
        return usage_entries, timestamps

    candidates: list[Path] = []
    for offset in range(days):
        folder = sessions_dir / (now - timedelta(days=offset)).strftime("%Y/%m/%d")
        if folder.exists():
            for p in folder.glob("rollout-*.jsonl"):
                if p.is_file() and p not in candidates:
                    candidates.append(p)

    for p in candidates:
        try:
            stat = p.stat()
            key = (str(p.resolve()), stat.st_mtime, stat.st_size)
            if key in _FILE_CACHE:
                cached_usage, cached_ts = _FILE_CACHE[key]
                usage_entries.extend(cached_usage)
                timestamps.extend(cached_ts)
                continue

            file_usage: list[tuple[datetime, int]] = []
            file_ts: list[datetime] = []
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    ts_raw = event.get("timestamp") or event.get("ts")
                    if not ts_raw and isinstance(event.get("item"), dict):
                        ts_raw = event["item"].get("timestamp")
                    ts = parse_ts(ts_raw, now)
                    if ts is not None:
                        file_ts.append(ts)

                    if event.get("type") == "turn.completed":
                        u = event.get("usage")
                        if isinstance(u, dict):
                            inp = u.get("input_tokens") or 0
                            cached = u.get("cached_input_tokens") or 0
                            outp = u.get("output_tokens") or 0
                            tokens = max(0, inp - cached) + outp
                            if ts is not None:
                                file_usage.append((ts, int(tokens)))

            _FILE_CACHE[key] = (file_usage, file_ts)
            usage_entries.extend(file_usage)
            timestamps.extend(file_ts)
        except OSError:
            pass

    return usage_entries, timestamps


def _calculate_active_time(timestamps: list[datetime], now: datetime) -> dict[str, int]:
    """Calcula tiempo activo sumando huecos consecutivos <= 300 s."""
    stamps = sorted(ts for ts in timestamps if ts is not None)
    today_s = 0.0
    week_s = 0.0
    total_s = 0.0
    week_cutoff = now - timedelta(days=7)
    total_cutoff = now - timedelta(days=30)
    today_date = now.date()

    for i in range(len(stamps) - 1):
        gap = (stamps[i + 1] - stamps[i]).total_seconds()
        if 0 < gap <= 300:
            target = stamps[i + 1]
            if target >= total_cutoff:
                total_s += gap
            if target >= week_cutoff:
                week_s += gap
            if target.date() == today_date:
                today_s += gap

    return {
        "today_s": round(today_s),
        "week_s": round(week_s),
        "total_s": round(total_s),
    }


def get_usage(name: str, role: str, cfg: dict, metas: list[RunMeta],
              now: datetime | None = None) -> dict[str, Any]:
    """Calcula uso en tokens y rondas para una IA."""
    now = now or datetime.now()
    if role == "main" and name == "agy":
        return {"tokens_5h": None, "tokens_today": None, "tokens_week": None, "rounds_today": 0}

    if role == "main" and name == "claude":
        home_raw = cfg.get("agents", {}).get(name, {}).get("home") or ""
        home_path = Path(home_raw).expanduser() if home_raw else Path.home()
        usage_entries, _ = _read_claude_transcripts(home_path, now, days=7)
        tokens_5h = 0
        tokens_today = 0
        tokens_week = 0
        cutoff_5h = now - timedelta(hours=5)
        cutoff_week = now - timedelta(days=7)
        today_date = now.date()
        for ts, tokens in usage_entries:
            if cutoff_5h <= ts <= now:
                tokens_5h += tokens
            if ts.date() == today_date:
                tokens_today += tokens
            if cutoff_week <= ts <= now:
                tokens_week += tokens
        return {
            "tokens_5h": tokens_5h,
            "tokens_today": tokens_today,
            "tokens_week": tokens_week,
            "rounds_today": 0,
        }

    if role == "main" and name == "codex":
        home_raw = cfg.get("agents", {}).get(name, {}).get("home") or ""
        home_path = Path(home_raw).expanduser() if home_raw else Path.home()
        usage_entries, _ = _read_codex_rollouts(home_path, now, days=7)
        tokens_5h = 0
        tokens_today = 0
        tokens_week = 0
        cutoff_5h = now - timedelta(hours=5)
        cutoff_week = now - timedelta(days=7)
        today_date = now.date()
        for ts, tokens in usage_entries:
            if cutoff_5h <= ts <= now:
                tokens_5h += tokens
            if ts.date() == today_date:
                tokens_today += tokens
            if cutoff_week <= ts <= now:
                tokens_week += tokens
        return {
            "tokens_5h": tokens_5h,
            "tokens_today": tokens_today,
            "tokens_week": tokens_week,
            "rounds_today": 0,
        }

    # Agentes (codex, agy, generic, claude como agente)
    tokens_5h = 0
    tokens_today = 0
    tokens_week = 0
    rounds_today = 0
    cutoff_5h = now - timedelta(hours=5)
    cutoff_week = now - timedelta(days=7)
    today_date = now.date()

    for meta in metas:
        for entry in meta.history:
            if entry.get("agent", meta.agent) != name:
                continue
            ts = parse_ts(entry.get("ts") or meta.created_at, now)
            if not ts:
                continue
            u = entry.get("usage") or {}
            if name == "codex":
                inp = u.get("input_tokens") or 0
                cached = u.get("cached_input_tokens") or 0
                outp = u.get("output_tokens") or 0
                tokens = max(0, inp - cached) + outp
            else:
                total = u.get("total_tokens")
                tokens = total if total is not None else (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
            if cutoff_5h <= ts <= now:
                tokens_5h += tokens
            if ts.date() == today_date:
                tokens_today += tokens
                rounds_today += 1
            if cutoff_week <= ts <= now:
                tokens_week += tokens

    return {
        "tokens_5h": tokens_5h,
        "tokens_today": tokens_today,
        "tokens_week": tokens_week,
        "rounds_today": rounds_today,
    }


def get_time(name: str, role: str, cfg: dict, metas: list[RunMeta],
             now: datetime | None = None) -> dict[str, Any]:
    """Calcula tiempo de desarrollo activo para una IA."""
    now = now or datetime.now()
    if role == "main" and name == "agy":
        return {"today_s": None, "week_s": None, "total_s": None}

    if role == "main" and name == "claude":
        home_raw = cfg.get("agents", {}).get(name, {}).get("home") or ""
        home_path = Path(home_raw).expanduser() if home_raw else Path.home()
        _, timestamps = _read_claude_transcripts(home_path, now, days=30)
        return _calculate_active_time(timestamps, now)

    if role == "main" and name == "codex":
        home_raw = cfg.get("agents", {}).get(name, {}).get("home") or ""
        home_path = Path(home_raw).expanduser() if home_raw else Path.home()
        _, timestamps = _read_codex_rollouts(home_path, now, days=30)
        return _calculate_active_time(timestamps, now)

    # Agentes: todo el historial de work.jsonl
    rows = read_work_rows()
    today_s = 0.0
    week_s = 0.0
    total_s = 0.0
    cutoff_week = now - timedelta(days=7)
    today_date = now.date()

    for row in rows:
        if row.get("agent") != name:
            continue
        sec = float(row.get("seconds", 0.0))
        total_s += sec
        ts = parse_ts(row.get("ts"), now)
        if ts is not None:
            if cutoff_week <= ts <= now:
                week_s += sec
            if ts.date() == today_date:
                today_s += sec

    return {
        "today_s": round(today_s),
        "week_s": round(week_s),
        "total_s": round(total_s),
    }
