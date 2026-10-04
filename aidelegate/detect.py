"""Detección portátil de los CLIs instalados."""

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys


@dataclass
class Detected:
    name: str
    path: str | None
    version: str | None
    logged_in: bool | None
    note: str = ""



def agy_logged_in(home: Path) -> bool | None:
    """Busca solo el marcador de autenticación, sin leer su contenido privado."""
    logs = []
    for path in (home / ".gemini/antigravity-cli/log").glob("*.log"):
        try:
            logs.append((path.stat().st_mtime, path))
        except OSError:
            continue
    marker = b"AuthResult:"
    for _, path in sorted(logs, reverse=True)[:3]:
        try:
            # Sin buffering: al encontrar el marcador no se lee el correo que sigue.
            with path.open("rb", buffering=0) as stream:
                matched = 0
                while byte := stream.read(1):
                    if byte[0] == marker[matched]:
                        matched += 1
                        if matched == len(marker):
                            return True
                    else:
                        matched = int(byte == marker[:1])
        except OSError:
            continue
    return None

def detect_all() -> dict[str, Detected]:
    home = Path.home()
    result = {}
    for name in ("claude", "codex", "agy"):
        path = shutil.which(name)
        note = ""
        if name == "claude" and not path:
            root = home / ("Library/Application Support/Claude/claude-code" if sys.platform == "darwin"
                           else ".config/Claude/claude-code")
            binaries = [p for p in root.glob("*/claude") if p.is_file()]
            def version_key(p):
                numbers = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", p.parent.name)
                return (*map(int, numbers.groups()[:3]), not bool(numbers[4]), numbers[4]) if numbers else (-1, 0, 0, False, p.parent.name)
            if binaries:
                path = str(max(binaries, key=version_key))
                note = "incluido en Claude Desktop; para delegarle tareas conviene instalar la CLI oficial"
        logged = ((home / ".codex/auth.json").exists() if name == "codex"
                  else agy_logged_in(home) if name == "agy" else None)
        version = None
        if path:
            try:
                proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5, check=True)
                version = (proc.stdout.splitlines() or [None])[0]
            except (OSError, subprocess.SubprocessError):
                pass
        result[name] = Detected(name, path, version, logged, note)
    return result
