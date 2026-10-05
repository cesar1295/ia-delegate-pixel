"""Registro configurable, ciclo v2, cuota y subagentes."""

import copy
import io
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from aidelegate import claude_status, config, quota, routing, runners, runs, summary
from aidelegate.cli import main
from aidelegate.runners import AgentResult
from aidelegate.ui_server import run_detail
from aidelegate.ui_state import build_state

FAKES = Path(__file__).parent / "fakes"


def last():
    return runs.load(runs.resolve("last"))


def test_generic_routing_run_and_feedback(home, repo):
    with config.config_path().open("a") as fh:
        fh.write(f'\n[agents.opencode]\ntype="generic"\nbin="{FAKES / "fake_generic.py"}"\n'
                 'args=["run", "{prompt}"]\ndisplay="OpenCode"\ncolor="#f0a500"\nquota="none"\n')
    cfg = config.load()
    assert routing.resolve_target("opencode", "feature", cfg) == "opencode"
    cfg["routing"]["feature"] = "opencode"
    assert routing.resolve_target("auto", "feature", cfg) == "opencode"
    assert routing.candidates("auto", "opencode", cfg) == ["opencode", "codex", "agy"]
    assert main(["--to", "opencode", "--dir", str(repo), "--check", "none", "TAREA ORIGINAL"]) == 0
    meta = last()
    assert not runners.get("opencode", cfg).supports_resume
    assert main(["feedback", meta.run_id, "corrige esto"]) == 0
    meta = last()
    sent = (Path(meta.worktree) / "generic-prompt.txt").read_text()
    assert sent.startswith("Tarea original:\nTAREA ORIGINAL\n\n") and "corrige esto" in sent
    events = [json.loads(line) for line in (runs.resolve("last") / "events.jsonl").read_text().splitlines()]
    assert events[0] == {"text": "listo desde generic"}
    assert (runs.resolve("last") / "last.md").read_text() == "listo desde generic\nsegunda línea"
    state = build_state([meta], None, [], datetime.now(), cfg=cfg)
    assert isinstance(state["agents"], list) and state["agents"][0]["name"] == "claude"
    assert state["agents"][-1]["look"] == {"hair": "#3a3a48", "color": "#f0a500"}
    assert state["events"] and run_detail(meta.run_id)["subagents"] == []


def test_delivery_events(home, repo):
    assert main(["--dir", str(repo), "--check", "none", "crea archivo"]) == 0
    meta = last()
    assert [e["type"] for e in meta.events] == ["assigned", "delivered"]
    assert main(["feedback", meta.run_id, "agrega otra línea"]) == 0
    assert main(["merge", meta.run_id]) == 0
    meta = last()
    assert [e["type"] for e in meta.events] == ["assigned", "delivered", "feedback", "delivered", "merged"]
    assert all(set(e) == {"type", "ts", "label", "agent"} for e in meta.events)


def test_no_changes_feedback(home, repo, capsys):
    main(["--dir", str(repo), "--check", "none", "crea archivo"])
    meta = last()
    assert main(["feedback", meta.run_id, "SIN_CAMBIOS"]) == 1
    assert last().status == "sin-cambios"
    assert last().events[-1]["label"] == "sin cambios"
    assert "aviso: la ronda no cambió ningún archivo; revisa o escala" in capsys.readouterr().out
    assert "sin-cambios" in runs.PENDING
    assert main(["discard", meta.run_id]) == 0


def test_codex_quota(tmp_path):
    now = datetime.now()
    folder = tmp_path / ".codex/sessions" / now.strftime("%Y/%m/%d")
    folder.mkdir(parents=True)
    data = {"payload": {"rate_limits": {"primary": {"window_minutes": 300, "used_percent": 25.5,
                                                   "resets_at": now.timestamp()},
                                        "secondary": {"window_minutes": 10080, "used_percent": 40}}}}
    older = folder / "rollout-old.jsonl"
    older.write_text(json.dumps(data))
    latest = folder / "rollout-new.jsonl"
    latest.write_text("x" * (2 * 1024 * 1024 + 1) + "\n" + json.dumps(data) + "\n{}\n")
    os.utime(older, (1, 1))
    result = quota.codex(str(tmp_path), now)
    assert result["remaining_pct"] == 60
    assert [w["label"] for w in result["windows"]] == ["5 h", "7 d"]
    assert datetime.fromisoformat(result["windows"][0]["resets_at"]).tzinfo is not None
    latest.unlink()
    assert quota.codex(str(tmp_path), now) == result  # cache de 30 s


def test_budget_and_exhausted(home):
    now = datetime.now()
    meta = runs.RunMeta("test", "agy", "write", "feature", "repo", "/tmp", "/tmp", "tarea",
                        history=[{"agent": "agy", "ts": now.isoformat(), "usage": {"total_tokens": 20}},
                                 {"agent": "agy", "ts": now.isoformat(), "usage": {"input_tokens": 5, "output_tokens": 5}},
                                 {"agent": "codex", "ts": now.isoformat(), "usage": {"total_tokens": 100}},
                                 {"agent": "agy", "ts": (now - timedelta(days=1)).isoformat(), "usage": {"total_tokens": 100}}])
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["agents"]["agy"]["daily_token_budget"] = 100
    result = quota.get("agy", cfg, [meta], now)
    assert result["remaining_pct"] == 70 and result["estimated"]
    cfg["agents"]["agy"]["daily_token_budget"] = 0
    result = quota.get("agy", cfg, [meta], now)
    assert result["remaining_pct"] is None and result["windows"][0] == {"label": "hoy: 30 tokens", "used_pct": None, "resets_at": None}
    meta.status = "cuota-agotada"
    assert quota.get("agy", cfg, [meta], now)["remaining_pct"] == 0
    assert quota.get("agy", cfg, [meta], now)["source"] == "agotada"
    meta.updated_at = (now - timedelta(minutes=31)).isoformat()
    assert quota.get("agy", cfg, [meta], now)["remaining_pct"] is None
    config.data_dir().mkdir(parents=True)
    (config.data_dir() / "claude-quota.json").write_text(json.dumps({"ts": now.isoformat(), "windows": [{"label": "5 h", "used_pct": 15, "resets_at": None}]}))
    assert quota.get("claude", cfg, [], now)["remaining_pct"] == 85


def test_hook_subagents_private(home, monkeypatch):
    hook = {"hook_event_name": "PreToolUse", "tool_name": "Task", "tool_use_id": "task-1",
            "tool_input": {"subagent_type": "investigador", "description": "PRIVADO", "prompt": "SECRETO"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook)))
    assert claude_status.main(["--from-hook"]) == 0
    path = config.data_dir() / "claude-status.json"
    data = json.loads(path.read_text())
    assert data["subagents"][0]["id"] == "task-1"
    assert "PRIVADO" not in path.read_text() and "SECRETO" not in path.read_text()
    hook["hook_event_name"] = "PostToolUse"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook)))
    claude_status.main(["--from-hook"])
    assert json.loads(path.read_text())["subagents"] == []


def test_runner_subagents(home, tmp_path):
    runner = runners.get("agy", config.load())
    result = AgentResult()
    event = {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "invoke_subagent", "step_index": 3, "state": "ACTIVE"}}
    runner.parse_event(event, result, [])
    assert result.subagents == [{"id": 3, "label": "invoke_subagent"}]
    event["step_update"]["state"] = "DONE"
    runner.parse_event(event, result, [])
    assert result.subagents == []
    progress = []
    result = runner.run("test", "read", tmp_path, None, 10, tmp_path,
                        on_progress=lambda r: progress.append([dict(s) for s in r.subagents]))
    assert progress == [[{"id": 1, "label": "invoke_subagent"}]]
    assert result.subagents == []
    runner = runners.get("codex", config.load())
    for kind, expected in [("item.started", [{"id": "a", "label": "spawn_agent"}]), ("item.completed", [])]:
        runner.parse_event({"type": kind, "item": {"id": "a", "type": "tool", "name": "spawn_agent"}}, result, [])
        assert result.subagents == expected


def test_garbled():
    assert not summary.looks_garbled("Texto normal con palabras claras y cortas. " * 15)
    assert summary.looks_garbled("a" * 300)
    assert not summary.looks_garbled("a" * 200)


def test_generic_placeholders_are_literal():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["agents"]["plain"] = {"type": "generic", "args": ["{cwd}", "{prompt}"]}
    runner = runners.get("plain", cfg)
    assert runner.argv("texto {cwd}", "read", Path("/tmp"), None) == ["plain", "/tmp", "texto {cwd}"]


def test_no_changes_correction(home, repo):
    assert main(["--dir", str(repo), "--check", "echo SIN_CAMBIOS && false", "crea archivo"]) == 1
    meta = last()
    assert meta.status == "sin-cambios" and meta.fix_rounds == 1
    assert meta.events[-1]["type"] == "failed"
    assert meta.events[-1]["label"] == "sin cambios"


def test_no_changes_escalation_and_event_ownership(home, repo):
    main(["--dir", str(repo), "--kind", "test", "--check", "none", "SIN_CAMBIOS"])
    meta = last()
    assert main(["escalate", meta.run_id]) == 1
    meta = last()
    assert meta.status == "sin-cambios"
    assert [(e["type"], e["agent"], e["label"]) for e in meta.events[-3:]] == [
        ("escalated", "agy", "codex"), ("assigned", "codex", "agy"), ("failed", "codex", "sin cambios")]


def test_event_limit_and_order(home):
    cfg = config.load()
    now = datetime.now()
    meta = runs.RunMeta("events", "codex", "read", "review", "repo", "/tmp", "/tmp", "tarea")
    meta.events = [{"type": "feedback", "label": str(i), "agent": "codex",
                    "ts": (now + timedelta(seconds=i)).isoformat()} for i in reversed(range(45))]
    state = build_state([meta], None, [], now, cfg=cfg)
    assert len(state["events"]) == 40
    assert [e["label"] for e in state["events"]] == [str(i) for i in range(5, 45)]
    assert state["events"][0]["id"] == "events:39"


def test_hook_expiration_limit_and_stop(home, monkeypatch):
    now = datetime.now()
    home.mkdir(parents=True)
    path = home / "claude-status.json"
    path.write_text(json.dumps({"subagents": [{"id": "viejo", "label": "viejo",
                                               "ts": (now - timedelta(minutes=31)).isoformat()}]}))
    for i in range(10):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_use_id": str(i), "tool_input": {"subagent_type": "x" * 50}})))
        claude_status.main(["--from-hook"])
    subs = json.loads(path.read_text())["subagents"]
    assert len(subs) == 8 and subs[0]["id"] == "2" and len(subs[0]["label"]) == 24
    for event, size in [("SubagentStop", 7), ("Stop", 0)]:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": event})))
        claude_status.main(["--from-hook"])
        assert len(json.loads(path.read_text())["subagents"]) == size
