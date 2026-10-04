"""Pruebas para v4.2: cuota real de Claude vía statusline, uso en tokens, tiempo activo y stats."""

import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aidelegate import config, install, quota, runs, stats, ui_state, usage
from aidelegate.cli import main
from aidelegate.runs import RunMeta


# --- 1. Statusline de Claude -------------------------------------------------

def test_statusline_with_rate_limits(home, monkeypatch, capsys):
    payload = {
        "rate_limits": {
            "five_hour": {"used_percentage": 23.0, "resets_at": 1791158840},
            "seven_day": {"used_percentage": 8.0, "resets_at": 1791580615},
        },
        "extra_junk": "ignorar esto",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = main(["claude-statusline"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out == "ai-delegate · 5h 23% · 7d 8%"

    quota_file = home / "claude-quota.json"
    assert quota_file.exists()
    data = json.loads(quota_file.read_text())
    assert "ts" in data
    assert "extra_junk" not in data
    assert len(data["windows"]) == 2
    assert data["windows"][0]["label"] == "5 h"
    assert data["windows"][0]["used_pct"] == 23.0
    assert "T" in data["windows"][0]["resets_at"]  # ISO string
    assert data["windows"][1]["label"] == "7 d"
    assert data["windows"][1]["used_pct"] == 8.0


def test_statusline_without_rate_limits(home, monkeypatch, capsys):
    payload = {"other_field": 123}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = main(["claude-statusline"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out == "ai-delegate"
    assert not (home / "claude-quota.json").exists()


def test_statusline_with_garbage_stdin(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("este no es un json valido"))
    code = main(["claude-statusline"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    assert out == "ai-delegate"
    assert not (home / "claude-quota.json").exists()


# --- 2. Setup y doctor con statusLine ----------------------------------------

def test_setup_does_not_overwrite_existing_statusline(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir(parents=True)
    custom_sl = {"type": "command", "command": "/usr/local/bin/mi-status", "refreshInterval": 30}
    settings_file = settings_dir / "settings.json"
    settings_file.write_text(json.dumps({"statusLine": custom_sl}, indent=2))

    writer = install.Writer()
    install.statusline(writer, yes=True)

    # Verifica que NO se modificó
    data = json.loads(settings_file.read_text())
    assert data["statusLine"] == custom_sl

    # Doctor debe avisar
    results = install.run_doctor(live=False, cfg=config.DEFAULTS)
    sl_check = next((r for r in results if r["check"] == "Statusline de Claude"), None)
    assert sl_check is not None
    assert sl_check["ok"] is False
    assert "/usr/local/bin/mi-status; ai-delegate claude-statusline" in sl_check["fix"]


def test_setup_adds_statusline_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir(parents=True)
    settings_file = settings_dir / "settings.json"
    settings_file.write_text(json.dumps({"hooks": {}}, indent=2))

    writer = install.Writer()
    install.statusline(writer, yes=True)

    data = json.loads(settings_file.read_text())
    assert "statusLine" in data
    assert "claude-statusline" in data["statusLine"]["command"]

    results = install.run_doctor(live=False, cfg=config.DEFAULTS)
    sl_check = next((r for r in results if r["check"] == "Statusline de Claude"), None)
    assert sl_check is not None
    assert sl_check["ok"] is True


# --- 3. Cuota de Claude y stale ----------------------------------------------

def test_claude_quota_fresh_and_stale(home):
    home.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 4, 15, 0, 0)
    cfg = config.DEFAULTS

    # Menos de 15 minutos: fresca
    fresh_ts = (now - timedelta(minutes=10)).isoformat()
    quota_file = home / "claude-quota.json"
    quota_file.write_text(json.dumps({
        "ts": fresh_ts,
        "windows": [{"label": "5 h", "used_pct": 23.0, "resets_at": None}],
    }))
    res_fresh = quota.get("claude", cfg, [], now=now)
    assert res_fresh["source"] == "claude"
    assert res_fresh["remaining_pct"] == 77
    assert res_fresh["stale"] is False

    # Más de 15 minutos: stale
    stale_ts = (now - timedelta(minutes=25)).isoformat()
    quota_file.write_text(json.dumps({
        "ts": stale_ts,
        "windows": [{"label": "5 h", "used_pct": 23.0, "resets_at": None}],
    }))
    res_stale = quota.get("claude", cfg, [], now=now)
    assert res_stale["source"] == "claude"
    assert res_stale["remaining_pct"] == 77
    assert res_stale["stale"] is True


# --- 4. Transcripciones, suma de tokens, caché y rangos ----------------------

def test_claude_transcripts_usage_and_cache(tmp_path):
    projects = tmp_path / ".claude/projects/repo1"
    projects.mkdir(parents=True)
    t_file = projects / "session1.jsonl"
    now = datetime(2026, 10, 4, 15, 0, 0)

    # Mensaje 1: hace 2 horas (5h, today, week)
    ts1 = (now - timedelta(hours=2)).isoformat()
    # Mensaje 2: hace 10 horas hoy (today, week, pero NO 5h)
    ts2 = (now.replace(hour=2, minute=0, second=0)).isoformat()
    # Mensaje 3: hace 3 días (week, pero NO today ni 5h)
    ts3 = (now - timedelta(days=3)).isoformat()
    # Mensaje 4: hace 10 días (fuera de rango)
    ts4 = (now - timedelta(days=10)).isoformat()

    lines = [
        json.dumps({
            "type": "assistant",
            "timestamp": ts1,
            "message": {
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 50,
                    "output_tokens": 25,
                    "cache_read_input_tokens": 999999,  # debe ser ignorado
                }
            }
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": ts2,
            "message": {
                "usage": {
                    "input_tokens": 200,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 88888,
                }
            }
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": ts3,
            "message": {
                "usage": {
                    "input_tokens": 300,
                    "output_tokens": 100,
                }
            }
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": ts4,
            "message": {
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 1000,
                }
            }
        }),
    ]
    t_file.write_text("\n".join(lines) + "\n")

    cfg = {"agents": {"claude": {"home": str(tmp_path)}}}
    usage_res = usage.get_usage("claude", "main", cfg, [], now=now)

    # ts1 = 175
    # ts2 = 250
    # ts3 = 400
    # ts4 = 2000 (fuera de semana)
    assert usage_res["tokens_5h"] == 175
    assert usage_res["tokens_today"] == 175 + 250
    assert usage_res["tokens_week"] == 175 + 250 + 400
    assert usage_res["rounds_today"] == 0

    # Caché: la clave debe estar en _FILE_CACHE
    stat = t_file.stat()
    cache_key = (str(t_file.resolve()), stat.st_mtime, stat.st_size)
    assert cache_key in usage._FILE_CACHE


# --- 5. work.jsonl: registro por ronda y relleno inicial ---------------------

def test_work_jsonl_backfill_and_recording(home, tmp_path):
    # Crear corrida simulada con 2 rondas en history
    run_dir = config.runs_dir() / "run-001"
    run_dir.mkdir(parents=True)
    meta = RunMeta(
        run_id="run-001", agent="codex", mode="write", kind="feature",
        repo="mi-repo", source_dir=str(tmp_path), workdir=str(tmp_path), task="tarea 1",
        history=[
            {"label": "tarea", "agent": "codex", "seconds": 25.5, "ts": "2026-10-04T10:00:00"},
            {"label": "corrección 1", "agent": "codex", "seconds": 15.0, "ts": "2026-10-04T10:05:00"},
        ]
    )
    runs.save(meta, run_dir)

    work_file = home / "work.jsonl"
    assert not work_file.exists()

    # ensure_work_log debe rellenar work.jsonl
    rows = usage.read_work_rows()
    assert len(rows) == 2
    assert rows[0]["seconds"] == 25.5
    assert rows[0]["agent"] == "codex"
    assert rows[1]["seconds"] == 15.0

    # Registrar nueva ronda
    usage.record_work_round("codex", 10.0, "feature", "mi-repo", "run-002", ts="2026-10-04T11:00:00")
    rows2 = usage.read_work_rows()
    assert len(rows2) == 3
    assert rows2[2]["seconds"] == 10.0


# --- 6. Tiempo activo con huecos > 300 s -------------------------------------

def test_active_time_calculation_with_gaps():
    now = datetime(2026, 10, 4, 15, 0, 0)
    t0 = now - timedelta(minutes=60)
    t1 = t0 + timedelta(seconds=120)  # gap 120s <= 300s -> cuenta 120s
    t2 = t1 + timedelta(seconds=600)  # gap 600s > 300s -> cuenta 0s (pausa)
    t3 = t2 + timedelta(seconds=60)   # gap 60s <= 300s -> cuenta 60s

    result = usage._calculate_active_time([t0, t1, t2, t3], now)
    # Total esperado = 120 + 60 = 180 s
    assert result["today_s"] == 180
    assert result["week_s"] == 180
    assert result["total_s"] == 180


# --- 7. Formato de stats ----------------------------------------------------

def test_stats_format():
    assert usage.format_time(4320) == "1 h 12 min"
    assert usage.format_time(2100) == "35 min"
    assert usage.format_time(40) == "40 s"
    assert usage.format_time(None) == "sin dato"

    assert usage.format_tokens(1_200_000) == "1.2 M"
    assert usage.format_tokens(2_400_000) == "2.4 M"
    assert usage.format_tokens(850_000) == "850 k"
    assert usage.format_tokens(920) == "920"
    assert usage.format_tokens(None) == "sin dato"

    out = stats.time_table(config.DEFAULTS)
    assert "IA" in out
    assert "hoy" in out
    assert "semana" in out
    assert "total" in out
    assert "tokens hoy" in out
    assert "|" in out


# --- 8. Codex rollouts y build_state con usage/time -------------------------

def test_codex_rollouts_usage_and_active_time(tmp_path):
    now = datetime(2026, 10, 4, 15, 0, 0)
    sessions_dir = tmp_path / ".codex/sessions/2026/10/04"
    sessions_dir.mkdir(parents=True)
    rollout_file = sessions_dir / "rollout-session1.jsonl"

    t0 = now - timedelta(minutes=10)
    t1 = t0 + timedelta(seconds=90)

    lines = [
        json.dumps({
            "type": "turn.completed",
            "timestamp": t0.isoformat(),
            "usage": {"input_tokens": 1500, "cached_input_tokens": 500, "output_tokens": 200},
        }),
        json.dumps({
            "type": "turn.completed",
            "timestamp": t1.isoformat(),
            "usage": {"input_tokens": 300, "cached_input_tokens": 100, "output_tokens": 50},
        }),
    ]
    rollout_file.write_text("\n".join(lines) + "\n")

    cfg = {"agents": {"codex": {"home": str(tmp_path)}}}
    usage_res = usage.get_usage("codex", "main", cfg, [], now=now)
    # t0 = 1500 - 500 + 200 = 1200; t1 = 300 - 100 + 50 = 250 -> total = 1450
    assert usage_res["tokens_5h"] == 1450
    assert usage_res["tokens_today"] == 1450
    assert usage_res["tokens_week"] == 1450

    time_res = usage.get_time("codex", "main", cfg, [], now=now)
    assert time_res["today_s"] == 90
    assert time_res["week_s"] == 90
    assert time_res["total_s"] == 90


def test_codex_agent_usage_subtracts_cached_input_tokens():
    now = datetime(2026, 10, 4, 15, 0, 0)
    cfg = config.DEFAULTS
    meta = RunMeta(
        run_id="run-c1", agent="codex", mode="write", kind="feature",
        repo="repo", source_dir="", workdir="", task="test",
        history=[
            {
                "agent": "codex",
                "ts": now.isoformat(),
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 400,
                    "output_tokens": 100,
                },
            }
        ]
    )
    # Codex: 1000 - 400 + 100 = 700 tokens
    res = usage.get_usage("codex", "agent", cfg, [meta], now=now)
    assert res["tokens_today"] == 700
    assert res["tokens_5h"] == 700
    assert res["rounds_today"] == 1


def test_build_state_includes_usage_and_time(home):
    home.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 4, 15, 0, 0)
    state = ui_state.build_state([], None, [], now=now, cfg=config.DEFAULTS)
    assert "agents" in state
    assert len(state["agents"]) > 0
    for agent in state["agents"]:
        assert "usage" in agent
        assert "time" in agent
        u = agent["usage"]
        assert "tokens_5h" in u
        assert "tokens_today" in u
        assert "tokens_week" in u
        assert "rounds_today" in u
        t = agent["time"]
        assert "today_s" in t
        assert "week_s" in t
        assert "total_s" in t

