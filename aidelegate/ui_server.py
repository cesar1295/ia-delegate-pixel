"""Servidor local para la oficina pixel y API de configuración."""

from __future__ import annotations

import errno
import hmac
import json
import mimetypes
import re
import secrets
import time
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import reconcile, config, detect, install, models, quota, routing, runs, stats, worktree
from .errors import DelegateError
from .ui_state import build_state

STATIC = Path(__file__).parent / "ui" / "static"
_MODEL_CACHE: dict[tuple, tuple[float, dict]] = {}
_AGY_STATE_CACHE: dict[tuple, tuple[float, dict]] = {}


def _catalog(name: str, cfg: dict, *, refresh: bool = False, state: bool = False) -> dict:
    now = time.monotonic()
    agent = cfg.get("agents", {}).get(name, {})
    key = (name, agent.get("type"), agent.get("bin"), agent.get("home"),
           str(Path.home()), str(config.data_dir()))
    cached = _MODEL_CACHE.get(key)
    if not refresh and cached and now - cached[0] < 60:
        return cached[1]
    if state and cfg.get("agents", {}).get(name, {}).get("type", name) == "agy":
        # La consulta periódica de estado nunca ejecuta agy: solo lee su caché en disco.
        state_cached = _AGY_STATE_CACHE.get(key)
        if state_cached and now - state_cached[0] < 60:
            return state_cached[1]
        value = models.catalog(name, cfg, offline=True)
        _AGY_STATE_CACHE[key] = (now, value)
        return value
    else:
        value = models.catalog(name, cfg, refresh=refresh)
    _MODEL_CACHE[key] = (now, value)
    return value


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


def _is_allowed_config_key(k: str) -> bool:
    exact = {
        "user_name", "strategy.mode", "strategy.first", "strategy.then",
        "strategy.escalate_after", "strategy.quota_floor_pct",
        "limits.timeout_min", "limits.max_review_rounds", "limits.keep_days",
        "ui.time_mode", "ui.fixed_hour",
    }
    if k == "agents.claude.five_hour_token_budget":
        return True
    if k in exact:
        return True
    if k.startswith("routing.") and len(k) > len("routing."):
        return True
    if k.startswith("agents."):
        parts = k.split(".")
        if len(parts) == 3 and parts[2] in {"enabled", "display", "color", "model", "effort", "daily_token_budget"}:
            return True
    return False


def _validate_change_value(k: str, v: Any, cfg: dict[str, Any]) -> str | None:
    agents = cfg.get("agents", {})
    if k == "user_name":
        if not isinstance(v, str) or not (1 <= len(v) <= 40):
            return "user_name debe ser string de 1 a 40 caracteres"
    elif k == "strategy.mode":
        if v not in ("agy-first", "routing"):
            return "strategy.mode debe ser 'agy-first' o 'routing'"
    elif k in ("strategy.first", "strategy.then"):
        if not isinstance(v, str) or v not in agents:
            return f"{k} debe ser un agente configurado"
    elif k == "strategy.escalate_after":
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 10):
            return "strategy.escalate_after debe ser entero entre 1 y 10"
    elif k == "strategy.quota_floor_pct":
        if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 90):
            return "strategy.quota_floor_pct debe ser entero entre 0 y 90"
    elif k.startswith("routing."):
        kind = k.removeprefix("routing.")
        if not (v in agents or v in ("main", "claude")):
            return f"routing.{kind} debe ser un agente configurado o 'main'"
        if v in agents and routing.default_mode(kind, cfg) == "write":
            agent_perms = agents[v].get("permissions", {})
            if agent_perms.get("edit", True) is False:
                return f"No se puede asignar '{v}' a '{kind}' porque no tiene permiso de edición"
    elif k.startswith("agents."):
        parts = k.split(".")
        if len(parts) != 3:
            return f"Clave de agente inválida: {k}"
        agent_name, field = parts[1], parts[2]
        if field == "enabled":
            if not isinstance(v, bool):
                return f"agents.{agent_name}.enabled debe ser booleano"
        elif field == "display":
            if not isinstance(v, str) or not (1 <= len(v) <= 20):
                return f"agents.{agent_name}.display debe ser string de 1 a 20 caracteres"
        elif field == "color":
            if not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                return f"agents.{agent_name}.color debe tener formato #rrggbb"
        elif field == "model":
            if not isinstance(v, str) or len(v) > 80 or not re.fullmatch(r"[A-Za-z0-9._:/\[\]-]*", v):
                return f"agents.{agent_name}.model debe tener hasta 80 caracteres válidos"
        elif field == "effort":
            if not isinstance(v, str) or v not in ("", "low", "medium", "high", "xhigh", "max", "ultra"):
                return f"agents.{agent_name}.effort inválido"
        elif field in {"daily_token_budget", "five_hour_token_budget"}:
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                return f"agents.{agent_name}.{field} debe ser entero >= 0"
    elif k == "limits.timeout_min":
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 240):
            return "limits.timeout_min debe ser entero entre 1 y 240"
    elif k == "limits.max_review_rounds":
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 10):
            return "limits.max_review_rounds debe ser entero entre 1 y 10"
    elif k == "limits.keep_days":
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 90):
            return "limits.keep_days debe ser entero entre 1 y 90"
    elif k == "ui.time_mode":
        if v not in ("auto", "fixed"):
            return "ui.time_mode debe ser 'auto' o 'fixed'"
    elif k == "ui.fixed_hour":
        if not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 23):
            return "ui.fixed_hour debe ser entero entre 0 y 23"
    return None


class Handler(BaseHTTPRequestHandler):
    """Atiende las rutas públicas y la API de configuración protegida."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, content: bytes, mime: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data: Any, status: int = 200) -> None:
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
                reconcile.background()
                cfg = config.load()
                state = build_state(runs.recent(1_000_000), _claude_status(), stats.read_rows(), datetime.now(),
                                    max_fix_rounds=cfg["limits"]["max_fix_rounds"], cfg=cfg)
                for agent in state["agents"]:
                    name = agent["name"]
                    model = cfg["agents"].get(name, {}).get("model", "")
                    catalog = _catalog(name, cfg, state=True)
                    default = catalog.get("default", {})
                    agent["model_label"] = (next((row["label"] for row in catalog["models"] if row["id"] == model), model)
                                            if model else default.get("label") or "predeterminado")
                    agent["effort"] = cfg["agents"].get(name, {}).get("effort", "") or default.get("effort", "")
                self._json(state)
            elif path == "/api/models":
                cfg = config.load()
                query = parse_qs(urlsplit(self.path).query)
                name = query.get("agent", [""])[0]
                if name and name not in cfg.get("agents", {}):
                    self._json({"error": f"Agente desconocido: {name}"}, 404)
                else:
                    refresh = query.get("refresh", [""])[0] == "1"
                    self._json({n: _catalog(n, cfg, refresh=refresh and n == name)
                                for n in ([name] if name else cfg.get("agents", {}))})
            elif path == "/api/config":
                cfg = config.load()
                detected = detect.detect_all()
                det_data = {
                    k: {"path": v.path, "version": v.version, "logged_in": v.logged_in, "note": v.note}
                    for k, v in detected.items()
                }
                from . import permissions
                for name, ag in cfg.get("agents", {}).items():
                    ag["permissions"] = permissions.get_effective_permissions(ag, name)
                self._json({
                    "config": cfg,
                    "claude_calibration": quota.calibration(),
                    "detected": det_data,
                    "kinds": routing.kinds(cfg),
                    "path": str(config.config_path()),
                    "catalog": permissions.AGY_CATALOG,
                    "agy_catalog": permissions.AGY_CATALOG,
                    "always_denied": permissions.ALWAYS_DENIED,
                })
            elif path.startswith("/api/run/"):
                self._json(run_detail(path.removeprefix("/api/run/")))
            elif path == "/":
                index = STATIC / "index.html"
                content = index.read_text(encoding="utf-8") if index.is_file() else "<!doctype html><meta charset='utf-8'><head></head><p>Frontend pendiente</p>"
                token = getattr(self.server, "token", "")
                meta_tag = f'<meta name="ai-delegate-token" content="{token}">'
                if "<head>" in content:
                    content = content.replace("<head>", f"<head>\n    {meta_tag}", 1)
                elif "</head>" in content:
                    content = content.replace("</head>", f"    {meta_tag}\n</head>", 1)
                else:
                    content = meta_tag + content
                self._send(content.encode("utf-8"), "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                self._static(path.removeprefix("/static/"))
            else:
                self._json({"error": "Ruta inexistente"}, 404)
        except DelegateError as exc:
            self._json({"error": str(exc)}, 404)
        except (OSError, ValueError, TypeError) as exc:
            self._json({"error": f"No se pudieron leer los datos: {exc}"}, 500)

    def do_POST(self) -> None:
        port = self.server.server_port
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self._json({"error": "Host no permitido"}, 403)
            return

        token = self.headers.get("X-AI-Delegate-Token", "")
        expected = getattr(self.server, "token", "")
        if not token or not hmac.compare_digest(token, expected):
            self._json({"error": "Token inválido o ausente"}, 403)
            return

        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            self._json({"error": "Origin no permitido"}, 403)
            return

        ct = self.headers.get("Content-Type", "")
        if ct.split(";")[0].strip().lower() != "application/json":
            self._json({"error": "Content-Type debe ser application/json"}, 403)
            return

        cl = self.headers.get("Content-Length")
        if not cl:
            self._json({"error": "Falta Content-Length"}, 403)
            return
        try:
            length = int(cl)
        except ValueError:
            self._json({"error": "Content-Length inválido"}, 403)
            return
        if length > 65536:
            self._json({"error": "Cuerpo supera 64 KB"}, 403)
            return

        body_bytes = self.rfile.read(length)
        if len(body_bytes) > 65536:
            self._json({"error": "Cuerpo supera 64 KB"}, 403)
            return

        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self._json({"error": "JSON inválido"}, 400)
            return

        path = unquote(urlsplit(self.path).path)
        try:
            if path.startswith("/api/run/") and path.endswith("/close"):
                self._post_close(path[len("/api/run/"):-len("/close")], body)
            elif path == "/api/config":
                self._post_config(body)
            elif path == "/api/permissions":
                self._post_permissions(body)
            elif path == "/api/master":
                self._post_master(body)
            elif path == "/api/doctor":
                self._post_doctor(body)
            else:
                self._json({"error": "Ruta inexistente"}, 404)
        except DelegateError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": f"Error procesando petición: {exc}"}, 500)

    def _post_close(self, ref: str, body: dict) -> None:
        if not isinstance(body, dict) or body.get("confirm") is not True or body.get("outcome") not in ("integrado", "descartado"):
            self._json({"error": "Falta confirm o outcome inválido"}, 400)
            return
        if not ref or ref in {".", ".."} or "/" in ref or "\\" in ref:
            raise DelegateError("Id de corrida inválido")
        if not (config.runs_dir() / ref / "meta.json").is_file():
            self._json({"error": "Corrida inexistente"}, 404)
            return
        with runs.state_lock():
            meta = runs.load(config.runs_dir() / ref)
            outcome = body["outcome"]
            if meta.status not in reconcile.OPEN:
                self._json({"error": "La corrida no está abierta"}, 409)
                return
            if outcome == "integrado" and meta.worktree:
                self._json({"error": "intégrala desde la terminal con merge"}, 409)
                return
            if outcome == "descartado" and meta.worktree and meta.project_root:
                worktree.remove(Path(meta.project_root), Path(meta.worktree), meta.branch or "")
            reconcile.close(meta, outcome, "cerrada-desde-oficina")
        self._json(run_detail(ref))

    def _post_permissions(self, body: dict) -> None:
        if not isinstance(body, dict):
            self._json({"error": "Cuerpo debe ser objeto JSON"}, 400)
            return

        agent = body.get("agent")
        if not agent or not isinstance(agent, str):
            self._json({"error": "Falta el campo 'agent'"}, 400)
            return

        cfg = config.load()
        if agent not in cfg.get("agents", {}):
            self._json({"error": f"Agente desconocido: {agent}"}, 400)
            return

        agent_cfg = cfg["agents"][agent]
        agent_type = agent_cfg.get("type", agent)

        if "changes" not in body or not isinstance(body["changes"], dict):
            self._json({"error": "Falta el campo 'changes' con las modificaciones"}, 400)
            return

        changes = body["changes"]

        from . import permissions
        allowed_keys = permissions.ALLOWED_CHANGE_KEYS.get(agent_type, set())
        invalid_keys = [k for k in changes if k not in allowed_keys]
        if invalid_keys or (agent_type == "generic" and changes):
            self._json({"error": f"Claves no permitidas para {agent} ({agent_type}): {invalid_keys}", "invalid": invalid_keys}, 400)
            return

        if "edit" in changes and not isinstance(changes["edit"], bool):
            self._json({"error": "edit debe ser booleano"}, 400)
            return

        if "network" in changes and not isinstance(changes["network"], bool):
            self._json({"error": "network debe ser booleano"}, 400)
            return

        if "groups" in changes:
            groups_val = changes["groups"]
            if not isinstance(groups_val, list) or not all(isinstance(g, str) for g in groups_val):
                self._json({"error": "groups debe ser una lista de strings"}, 400)
                return
            unknown_groups = [g for g in groups_val if g not in permissions.AGY_CATALOG]
            if unknown_groups:
                self._json({"error": f"Grupos desconocidos: {unknown_groups}", "unknown_groups": unknown_groups}, 400)
                return

        # Comprobar si amplía permisos y requiere confirmación
        current_perms = permissions.get_effective_permissions(agent_cfg, agent)
        display = agent_cfg.get("display", agent)
        confirm = bool(body.get("confirm", False))
        messages = permissions.check_expansion(agent_type, display, current_perms, changes)
        if messages and not confirm:
            self._json({"needs_confirm": True, "message": "\n\n".join(messages)}, 409)
            return

        # Guardar en config.toml con respaldo
        updates = {f"agents.{agent}.permissions.{k}": v for k, v in changes.items()}
        new_cfg = config.write_config_updates(updates) if updates else cfg

        # Si es agy, sincronizar settings.json con respaldo
        effective = permissions.get_effective_permissions(new_cfg["agents"][agent], agent)
        if agent_type == "agy":
            settings_home = Path(agent_cfg["home"]) if agent_cfg.get("home") else None
            permissions.sync_agy_settings(effective.get("groups", ["lectura"]), home=settings_home)

        self._json({"ok": True, "agent": agent, "permissions": effective})

    def _post_config(self, body: dict) -> None:
        if not isinstance(body, dict) or "changes" not in body or not isinstance(body["changes"], dict):
            self._json({"error": "Falta el campo 'changes' con las modificaciones"}, 400)
            return

        changes = body["changes"]
        invalid_keys = [k for k in changes if not _is_allowed_config_key(k)]
        if invalid_keys:
            self._json({"error": f"Claves no permitidas: {', '.join(invalid_keys)}", "invalid": invalid_keys}, 400)
            return

        cfg = config.load()
        for k, v in changes.items():
            err = _validate_change_value(k, v, cfg)
            if err:
                self._json({"error": err}, 400)
                return

        new_cfg = config.write_config_updates(changes)
        self._json({"config": new_cfg})

    def _post_master(self, body: dict) -> None:
        name = body.get("name") if isinstance(body, dict) else None
        if not name:
            self._json({"error": "Falta el nombre de la maestra"}, 400)
            return
        try:
            install.set_master(name, config.load(), yes=True)
            self._json({"ok": True, "master": name})
        except Exception as exc:
            self._json({"error": str(exc)}, 400)

    def _post_doctor(self, body: dict) -> None:
        live = bool(body.get("live", False)) if isinstance(body, dict) else False
        results = install.run_doctor(live=live, timeout_s=120.0)
        self._json(results)

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
    """Crea el servidor limitado a la interfaz local con token en memoria."""
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        server.token = secrets.token_urlsafe(32)
        return server
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
