"""Servidor local de solo lectura para la oficina pixel."""

from __future__ import annotations

import errno
import json
import mimetypes
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import config, runs, stats, worktree
from .errors import DelegateError
from .ui_state import build_state

STATIC = Path(__file__).parent / "ui" / "static"


def _claude_status() -> dict | None:
    try:
        value = json.loads((config.data_dir() / "claude-status.json").read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def run_detail(ref: str) -> dict:
    """Devuelve detalles de una corrida sin datos de uso del agente."""
    if not ref or ref in {".", ".."} or "/" in ref or "\\" in ref:
        raise DelegateError("Id de corrida inválido; usa ai-delegate list")
    folder = config.runs_dir() / ref
    if not (folder / "meta.json").is_file():
        raise DelegateError(f"No encuentro la corrida '{ref}'. Usa ai-delegate list")
    meta = runs.load(folder)
    data = asdict(meta)
    data["history"] = [{k: v for k, v in entry.items() if k != "usage"} for entry in meta.history]
    last = folder / "last.md"
    diffstat = meta.diffstat
    if meta.worktree and Path(meta.worktree).exists():
        diffstat = worktree.diffstat_line(Path(meta.worktree), meta.base_commit or "HEAD")
    return {**data, "summary": "\n".join(last.read_text().splitlines()[:40]) if last.exists() else "",
            "feedback": meta.feedback, "diffstat": diffstat,
            "commands": [f"ai-delegate diff {ref}", f'ai-delegate feedback {ref} "..."',
                         f"ai-delegate merge {ref}", f"ai-delegate discard {ref}"]}


class Handler(BaseHTTPRequestHandler):
    """Atiende las rutas públicas sin registrar cada petición."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, content: bytes, mime: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        port = self.server.server_port
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self._json({"error": "Host no permitido"}, 403)
            return
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/state":
                cfg = config.load()
                self._json(build_state(runs.recent(1_000_000), _claude_status(), stats.read_rows(), datetime.now(),
                                       max_fix_rounds=cfg["limits"]["max_fix_rounds"], cfg=cfg))
            elif path.startswith("/api/run/"):
                self._json(run_detail(path.removeprefix("/api/run/")))
            elif path == "/":
                index = STATIC / "index.html"
                content = index.read_bytes() if index.is_file() else b"<!doctype html><meta charset='utf-8'><p>Frontend pendiente</p>"
                self._send(content, "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                self._static(path.removeprefix("/static/"))
            else:
                self._json({"error": "Ruta inexistente"}, 404)
        except DelegateError as exc:
            self._json({"error": str(exc)}, 404)
        except (OSError, ValueError, TypeError) as exc:
            self._json({"error": f"No se pudieron leer los datos: {exc}"}, 500)

    def _static(self, name: str) -> None:
        file = STATIC / name
        if (not name or Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name
                or not file.resolve().is_relative_to(STATIC.resolve()) or not file.is_file()):
            self._json({"error": "Archivo inexistente"}, 404)
            return
        mime = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8", ".png": "image/png"}.get(file.suffix)
        self._send(file.read_bytes(), mime or mimetypes.guess_type(name)[0] or "application/octet-stream")


def create_server(port: int = 8765) -> ThreadingHTTPServer:
    """Crea el servidor limitado a la interfaz local."""
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise DelegateError(f"El puerto {port} está ocupado; usa --port") from exc
        raise DelegateError(f"No se puede abrir el puerto {port}: {exc}; usa --port") from exc
    except (OverflowError, ValueError) as exc:
        raise DelegateError("Puerto inválido; usa --port entre 0 y 65535") from exc


def serve(port: int = 8765, no_open: bool = False) -> int:
    """Sirve hasta Ctrl+C y cierra el socket al salir."""
    with create_server(port) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"oficina en {url} (Ctrl+C para salir)")
        if not no_open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
