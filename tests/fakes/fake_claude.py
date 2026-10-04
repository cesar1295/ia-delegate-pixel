#!/usr/bin/env python3
"""CLI falso de Claude: init, subagente y resultado."""
import json
import sys

if "--version" in sys.argv:
    print("Claude 2.1.10")
    sys.exit(0)
identity = sys.argv[sys.argv.index("--resume") + 1] if "--resume" in sys.argv else "claude-test-session"
for event in [
    {"type": "system", "subtype": "init", "session_id": identity},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Agent", "id": "sub-1", "input": {"subagent_type": "Explore"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "sub-1"}]}},
    {"type": "result", "result": "OK", "session_id": identity, "is_error": False, "usage": {"input_tokens": 10, "output_tokens": 2}},
]:
    print(json.dumps(event), flush=True)
