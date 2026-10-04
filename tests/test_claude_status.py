import io
import json

import pytest

from aidelegate.cli import main


@pytest.mark.parametrize("event,state", [("UserPromptSubmit", "working"), ("PreToolUse", "working"),
    ("PostToolUse", "working"), ("Notification", "waiting"), ("Stop", "idle"),
    ("SubagentStop", "idle"), ("SessionEnd", "idle")])
def test_hook(home, monkeypatch, capsys, event, state):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": event,
                        "tool_name": "Read", "prompt": "private"})))
    assert main(["claude-status", "--from-hook"]) == 0
    data = json.loads((home / "claude-status.json").read_text())
    assert data["state"] == state
    assert data["detail"] == ("Read" if state == "working" else "")
    assert set(data) == {"state", "detail", "ts"}
    assert capsys.readouterr() == ("", "")


def test_garbage(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("garbage"))
    assert main(["claude-status", "--from-hook"]) == 0
    assert capsys.readouterr() == ("", "")
    assert not (home / "claude-status.json").exists()
