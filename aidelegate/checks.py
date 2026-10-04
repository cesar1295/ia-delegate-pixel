"""Detección y ejecución de los checks del proyecto (tests, lint, tipos).

Corren localmente sin gastar tokens; si fallan, la salida vuelve al agente.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAIL_LINES = 120
NPM_SCRIPTS = ("lint", "typecheck", "test")


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    exit_code: int
    output: str
    duration_s: float


def resolve(flag: str | None, directory: Path, project_root: Path, cfg: dict[str, Any]) -> str | None:
    if flag == "none":
        return None
    if flag and flag != "auto":
        return flag
    project = cfg["projects"].get(str(project_root), {})
    return project.get("check") or detect(directory)


def detect(directory: Path) -> str | None:
    return _detect_node(directory) or _detect_python(directory)


def _detect_node(directory: Path) -> str | None:
    pkg = directory / "package.json"
    if not pkg.is_file():
        return None
    try:
        scripts = json.loads(pkg.read_text()).get("scripts", {})
    except json.JSONDecodeError:
        return None
    manager = _node_manager(directory)
    steps = [f"{manager} run {name}" for name in NPM_SCRIPTS if _real_script(scripts.get(name))]
    return " && ".join(steps) or None


def _real_script(script: str | None) -> bool:
    return bool(script) and "no test specified" not in script


def _node_manager(directory: Path) -> str:
    for lockfile, manager in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun")):
        if (directory / lockfile).exists():
            return manager
    return "npm"


def _detect_python(directory: Path) -> str | None:
    markers = ("pytest.ini", "conftest.py", "tests")
    pyproject = directory / "pyproject.toml"
    has_pytest = any((directory / m).exists() for m in markers) or (
        pyproject.is_file() and "pytest" in pyproject.read_text()
    )
    if not has_pytest:
        return None
    python = ".venv/bin/python" if (directory / ".venv/bin/python").exists() else "python3"
    return f"{python} -m pytest -q"


def run(cmd: str, cwd: Path, timeout_s: int) -> CheckResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["bash", "-c", cmd], cwd=cwd, env=os.environ.copy(), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout_s,
        )
        code, output = proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        code, output = 124, f"{exc.stdout or ''}{exc.stderr or ''}\n[checks cancelados tras {timeout_s}s]"
    tail = "\n".join(str(output).splitlines()[-TAIL_LINES:])
    return CheckResult(code == 0, code, tail, time.monotonic() - start)
