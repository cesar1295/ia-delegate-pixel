"""Ejecución de un CLI de IA: entorno limpio, streaming a events.jsonl y timeout."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from ..errors import DelegateError

# Lo único que hereda el subproceso. Ninguna llave o token del entorno pasa.
ENV_KEEP = (
    "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "USER", "LOGNAME", "SHELL",
    "TMPDIR", "TZ", "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
)
QUOTA_HINTS = (
    "rate limit", "rate_limit", "ratelimit", "quota", "usage limit", "usage_limit",
    "resource_exhausted", "too many requests", "429",
)


@dataclass
class AgentResult:
    exit_code: int = -1
    thread_id: str | None = None
    last_message: str = ""
    error: str = ""
    timed_out: bool = False
    quota_exhausted: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    subagents: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error


class Runner:
    name = ""
    supports_resume = False
    plain_text = False
    # Regla extra para el prompt según las limitaciones del CLI.
    prompt_hint = ""

    def __init__(self, binary: str, home: str = "", model: str = "") -> None:
        self.binary, self.home, self.model = binary, home, model
        self.edit: bool = True
        self.network: bool = False
        self.groups: list[str] = ["lectura"]
        self.permissions: dict[str, Any] = {}

    # --- a implementar por cada CLI ---
    def argv(self, prompt: str, mode: str, cwd: Path, resume_id: str | None) -> list[str]:
        raise NotImplementedError

    def parse_event(self, event: dict[str, Any], result: AgentResult, deltas: list[str]) -> None:
        raise NotImplementedError

    # --- comunes ---
    def profile_home(self) -> Path:
        if not self.home:
            return Path.home()
        path = Path(self.home).expanduser()
        if not path.is_dir():
            raise DelegateError(
                f"No existe el perfil de {self.name}: {path}. Corrige agents.{self.name}.home "
                "en ~/.config/ai-delegate/config.toml o déjalo vacío para usar tu HOME."
            )
        return path

    def env(self) -> dict[str, str]:
        env = {key: os.environ[key] for key in ENV_KEEP if key in os.environ}
        env["HOME"] = str(self.profile_home())
        return env

    def ensure_available(self) -> None:
        if shutil.which(self.binary, path=os.environ.get("PATH")) is None:
            raise DelegateError(
                f"No encuentro el binario '{self.binary}' de {self.name}. Instálalo o ajusta "
                f"agents.{self.name}.bin en ~/.config/ai-delegate/config.toml."
            )
        self.profile_home()

    def run(
        self, prompt: str, mode: str, cwd: Path, resume_id: str | None, timeout_s: int, run_dir: Path,
        on_progress: Callable[[AgentResult], None] | None = None
    ) -> AgentResult:
        result = AgentResult(thread_id=resume_id)
        start = time.monotonic()
        with open(run_dir / "events.jsonl", "a") as events, open(run_dir / "stderr.log", "a") as errlog:
            proc = subprocess.Popen(
                self.argv(prompt, mode, cwd, resume_id), cwd=cwd, env=self.env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errlog,
                text=True, start_new_session=True,
            )
            timer = threading.Timer(timeout_s, _kill, args=(proc, result))
            timer.start()
            try:
                self._consume(proc.stdout, events, result, on_progress)
                result.exit_code = proc.wait()
            finally:
                timer.cancel()
        result.duration_s = time.monotonic() - start
        self._finalize(result, run_dir / "stderr.log")
        return result

    def _consume(self, stdout: TextIO | None, events: TextIO, result: AgentResult,
                 on_progress: Callable[[AgentResult], None] | None = None) -> None:
        deltas: list[str] = []
        notified: list[dict] = []
        last_progress = float("-inf")
        for line in stdout or []:
            if self.plain_text:
                deltas.append(line)
                events.write(json.dumps({"text": line.rstrip("\r\n")}, ensure_ascii=False) + "\n")
                events.flush()
                continue
            events.write(line)
            events.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                self.parse_event(event, result, deltas)
                if on_progress and result.subagents != notified and time.monotonic() - last_progress >= 1:
                    on_progress(result)
                    notified = [dict(s) for s in result.subagents]
                    last_progress = time.monotonic()
        if not result.last_message and deltas:
            result.last_message = "".join(deltas).strip()

    def _finalize(self, result: AgentResult, stderr_path: Path) -> None:
        if result.timed_out:
            result.error = result.error or "Se agotó el tiempo (--timeout); el proceso fue terminado."
        elif result.exit_code != 0 and not result.error:
            tail = stderr_path.read_text(errors="replace").strip().splitlines()[-5:]
            result.error = " | ".join(tail) or f"{self.name} salió con código {result.exit_code}"
        haystack = result.error.lower()
        result.quota_exhausted = bool(result.error) and any(hint in haystack for hint in QUOTA_HINTS)


def _kill(proc: subprocess.Popen[str], result: AgentResult) -> None:
    result.timed_out = True
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
