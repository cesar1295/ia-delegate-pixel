import json
from pathlib import Path

from aidelegate import config, runners
from aidelegate.runners.base import AgentResult

CODEX_EVENTS = [
    {"type": "thread.started", "thread_id": "01a1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "OK"}},
    {"type": "turn.completed", "usage": {"input_tokens": 16474, "output_tokens": 5}},
]
AGY_EVENTS = [
    {"event": "init", "conversation_id": "692e"},
    {"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "OK"}},
    {"event": "result", "result": {"status": "SUCCESS", "response": "OK\n", "usage": {"total_tokens": 12871}}},
]


def parse(name, events):
    runner, result, deltas = runners.get(name, config.DEFAULTS), AgentResult(), []
    for event in events:
        runner.parse_event(event, result, deltas)
    return result


def test_parse_codex_events():
    result = parse("codex", CODEX_EVENTS)
    assert result.thread_id == "01a1" and result.last_message == "OK" and result.usage["output_tokens"] == 5


def test_parse_agy_events():
    result = parse("agy", AGY_EVENTS)
    assert result.thread_id == "692e" and result.last_message == "OK\n"


def test_agy_failure_status_is_error():
    result = parse("agy", [{"event": "result", "result": {"status": "ERROR", "error": "quota exceeded"}}])
    assert "quota exceeded" in result.error


def test_codex_argv_sandbox_and_resume():
    codex = runners.get("codex", config.DEFAULTS)
    first = codex.argv("p", "read", Path("/r"), None)
    assert 'sandbox_mode="read-only"' in first and first[-3:] == ["-C", "/r", "p"]
    again = codex.argv("p", "write", Path("/r"), "t1")
    assert again[:3] == ["codex", "exec", "resume"] and again[-2:] == ["t1", "p"]
    assert 'sandbox_mode="workspace-write"' in again


def test_agy_argv_modes_never_skip_permissions():
    agy = runners.get("agy", config.DEFAULTS)
    write = agy.argv("p", "write", Path("/r"), None)
    read = agy.argv("p", "read", Path("/r"), "c1")
    assert "accept-edits" in write and "plan" in read
    assert not any("dangerously" in arg for arg in write + read)
    assert read[-4:] == ["--conversation", "c1", "-p", "p"]


def test_agy_empty_answer_with_denied_permissions_is_error():
    result = parse("agy", [{"event": "result", "result": {
        "status": "SUCCESS", "response": "", "denied_actions": [{"action": "command", "display_name": "RunCommand"}]}}])
    assert not result.ok and "RunCommand" in result.error


def test_env_is_clean(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "no-debe-pasar")
    monkeypatch.setenv("GITHUB_TOKEN", "tampoco")
    env = runners.get("codex", config.DEFAULTS).env()
    assert "OPENAI_API_KEY" not in env and "GITHUB_TOKEN" not in env
    assert {"PATH", "HOME"} <= set(env)
    assert json.dumps(env).count("no-debe-pasar") == 0
