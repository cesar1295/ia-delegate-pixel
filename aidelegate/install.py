"""Instalación portátil, cambio de maestra y diagnóstico."""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path

from . import config, quota, runners
from .detect import detect_all
from .errors import DelegateError

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- ai-delegate:start -->", "<!-- ai-delegate:end -->"
FILES = {"claude": ".claude/CLAUDE.md", "codex": ".codex/AGENTS.md", "agy": ".gemini/GEMINI.md"}
LOGIN = {"claude": "claude", "codex": "codex login", "agy": "agy y seguir el flujo"}
INSTALL = {"claude": "curl -fsSL https://claude.ai/install.sh | bash", "codex": "npm i -g @openai/codex", "agy": "ver https://antigravity.google/docs/cli"}
ROLES = {"codex": "funcionalidades, bugs, refactors, endpoints, implementar especificaciones de diseño, revisiones de código", "agy": "tareas acotadas (tests sencillos, docs, datos de prueba, i18n), resumir repos, investigación web e imágenes; en la terminal solo tiene comandos de lectura", "claude": "funcionalidades, especificaciones y revisiones; diseño visual"}


def confirm(question: str, yes: bool) -> bool:
    return yes or input(question + " [S/n] ").strip().lower() not in {"n", "no"}


class Writer:
    def __init__(self, dry: bool = False):
        self.dry = dry

    def backup(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = Path(str(path) + ".bak-ai-delegate-" + stamp)
            index = 1
            while target.exists() or target.is_symlink():
                target = Path(str(path) + ".bak-ai-delegate-" + stamp + f"-{index}")
                index += 1
            shutil.copy2(path, target, follow_symlinks=False)

    def write(self, path: Path, text: str, summary: str = "") -> None:
        action = "actualizar (con respaldo)" if path.exists() else "crear"
        print(f"   → {action} {path}" + (f": {summary}" if summary else ""))
        if self.dry:
            return
        if path.exists() and path.read_text() == text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.backup(path)
        path.write_text(text)


def update_config(writer: Writer, master: str, user: str, agents: dict) -> bool:
    path = config.config_path()
    original = path.read_text() if path.exists() else ""
    updates = {"": {"main": master, "user_name": user}}
    updates.update({f"agents.{name}": values for name, values in agents.items()})
    try:
        tomllib.loads(original)
        # Only simple table headers can be edited without risking unrelated TOML.
        headers = list(re.finditer(r"(?m)^\s*\[([^\n]+)\]\s*(?:#.*)?$", original))
        if any(h[1].startswith("[") or '"' in h[1] or "'" in h[1] for h in headers):
            raise ValueError("tablas complejas")
        sections = {"": original[:headers[0].start()] if headers else original}
        order = [""]
        for i, header in enumerate(headers):
            key = header[1].strip()
            order.append(key)
            sections[key] = original[header.end():headers[i + 1].start() if i + 1 < len(headers) else len(original)]
        if "main" in sections:
            old = tomllib.loads(original).get("main", {})
            if set(old) - {"name", "display", "color"}:
                raise ValueError("tabla main con claves adicionales")
            del sections["main"]
            order.remove("main")
        for section, values in updates.items():
            if section not in sections:
                sections[section] = "\n"
                order.append(section)
            body = sections[section]
            for key, value in values.items():
                if key == "permissions":
                    continue
                pattern = rf"(?m)^\s*{re.escape(key)}\s*=.*$"
                line = f"{key} = {json.dumps(value, ensure_ascii=False)}"
                body = re.sub(pattern, lambda m: line, body) if re.search(pattern, body) else body.rstrip() + "\n" + line + "\n"
            sections[section] = body
        text = sections[""] + "".join(f"\n[{key}]\n{sections[key].strip()}\n" for key in order if key)
        parsed = tomllib.loads(text)
        # Ensure edits preserve every unrelated value, including nested sections.
        expected = tomllib.loads(original)
        expected["main"], expected["user_name"] = master, user
        for name, values in agents.items():
            expected.setdefault("agents", {}).setdefault(name, {}).update(
                {k: v for k, v in values.items() if k != "permissions"}
            )
        if parsed != expected:
            raise ValueError("no se conservan todas las claves")
    except (ValueError, tomllib.TOMLDecodeError):
        text = f'main = {json.dumps(master)}\nuser_name = {json.dumps(user, ensure_ascii=False)}\n'
        for name, values in agents.items():
            text += f"\n[agents.{name}]\n" + "".join(
                f"{k} = {json.dumps(v, ensure_ascii=False)}\n"
                for k, v in values.items() if k != "permissions"
            )
        writer.write(path.with_name(path.name + ".nuevo"), text,
                     "config propuesta: " + ", ".join(
                         f"{section + '.' if section else ''}{key}"
                         for section, values in updates.items() for key in values if key != "permissions"))
        print(f"   ✗ No puedo conservar la config con seguridad; revisar {path}.nuevo")
        return False
    previous = tomllib.loads(original)
    changed = []
    for section, values in updates.items():
        old_values = previous if not section else previous.get("agents", {}).get(section.split(".", 1)[1], {})
        changed.extend(f"{section + '.' if section else ''}{key}" for key, value in values.items()
                       if key != "permissions" and old_values.get(key) != value)
    summary = "claves de config cambiadas: " + (", ".join(changed) or "ninguna")
    writer.write(path, text, summary)
    return True


def instructions(writer: Writer, cfg: dict, yes: bool, remove: str | None = None) -> None:
    if remove:
        path = Path.home() / FILES[remove]
        if path.exists():
            old = path.read_text()
            if START not in old and "# Equipo de IA: Claude dirige" in old:
                if not confirm(f"¿Retirar las instrucciones antiguas de {path}?", yes):
                    raise DelegateError("Migración cancelada")
                old = old.split("# Equipo de IA: Claude dirige", 1)[0]
            writer.write(path, re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", old, flags=re.S))
    master = config.main_name(cfg)
    path = Path.home() / FILES[master]
    old = path.read_text() if path.exists() else ""
    block_status = "actualizado" if START in old else "nuevo"
    if START not in old and "# Equipo de IA: Claude dirige" in old:
        block_status = "migrado"
        if not confirm(f"¿Migrar las instrucciones antiguas de {path}?", yes):
            raise DelegateError("Migración cancelada")
        before, legacy = old.split("# Equipo de IA: Claude dirige", 1)
        old = before + START + "\n# Equipo de IA: Claude dirige" + legacy + "\n" + END
    agents = {n: a for n, a in cfg["agents"].items() if n != master}
    values = {"main_display": cfg["agents"][master].get("display", master), "agents_display": " y ".join(a.get("display", n) for n, a in agents.items()), "user_name": cfg["user_name"], "repo_path": str(ROOT), "agents_table": "| IA | Para qué |\n| --- | --- |\n" + "\n".join(f"| {a.get('display', n)} | {a.get('role_text', ROLES.get(n, 'tareas delegadas'))} |" for n, a in agents.items())}
    rendered = (ROOT / "setup/instructions.md").read_text()
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    block = START + "\n" + rendered.rstrip() + "\n" + END
    if START in old:
        if END not in old or old.count(START) != 1 or old.count(END) != 1:
            raise DelegateError(f"Marcadores inválidos en {path}")
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, old, flags=re.S)
    else:
        text = old.rstrip() + ("\n\n" if old.strip() else "") + block + "\n"
    writer.write(path, text, f"bloque de instrucciones {block_status}")


def merge_json(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict):
            base[key] = merge_json(base.get(key, {}), value)
        elif isinstance(value, list):
            current = []
            for item in base.get(key, []) + value:
                if item not in current:
                    current.append(item)
            base[key] = current
        else:
            base[key] = value
    return base


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, OSError) as exc:
        raise DelegateError(f"No puedo leer {path}: {exc}") from exc


def hook_command() -> str:
    return shlex.quote(str(Path.home() / ".local/bin/ai-delegate")) + " claude-status --from-hook"


def hooks(writer: Writer, enable: bool, yes: bool = True) -> None:
    path = Path.home() / ".claude/settings.json"
    if not path.exists() and not enable:
        return
    if not path.exists() and not confirm(f"¿Crear {path}?", yes):
        return
    data = read_json(path)
    command = hook_command()
    owned = {command, "ai-delegate claude-status --from-hook"}
    new, present, removed = 0, 0, 0
    if enable:
        template = json.loads((ROOT / "setup/claude-hooks.json").read_text())
        for event, groups in template["hooks"].items():
            existing = data.setdefault("hooks", {}).setdefault(event, [])
            count = sum(h.get("command") in owned for g in existing for h in g.get("hooks", []))
            if count:
                present += count
                for g in existing:
                    for h in g.get("hooks", []):
                        if h.get("command") in owned:
                            h["command"] = command
                continue
            for group in groups:
                for h in group["hooks"]:
                    h["command"] = command
                existing.append(group)
                new += len(group["hooks"])
    else:
        for event, groups in data.get("hooks", {}).items():
            kept = []
            for group in groups:
                original = group.get("hooks", [])
                remaining = [h for h in original if h.get("command") not in owned]
                removed += len(original) - len(remaining)
                if remaining or not original:
                    kept.append({**group, "hooks": remaining})
            data["hooks"][event] = kept
    summary = f"{new} hooks nuevos ({present} ya estaban)" if enable else f"{removed} hooks de ai-delegate retirados"
    writer.write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", summary)


def statusline_command() -> str:
    return str(Path.home() / ".local/bin/ai-delegate") + " claude-statusline"


def statusline(writer: Writer, yes: bool = True) -> None:
    path = Path.home() / ".claude/settings.json"
    if not path.exists() and not confirm(f"¿Crear {path}?", yes):
        return
    data = read_json(path)
    if "statusLine" not in data or not data["statusLine"]:
        template_file = ROOT / "setup/claude-statusline.json"
        template = json.loads(template_file.read_text()) if template_file.exists() else {
            "type": "command", "command": "ai-delegate claude-statusline", "refreshInterval": 60
        }
        template["command"] = statusline_command()
        data["statusLine"] = template
        writer.write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", "statusLine de Claude configurado")


def permissions(writer: Writer) -> None:
    path = Path.home() / ".gemini/antigravity-cli/settings.json"
    data = read_json(path)
    template = json.loads((ROOT / "setup/agy-permissions.json").read_text())
    new, present = 0, 0
    for key, values in template["permissions"].items():
        existing = data.get("permissions", {}).get(key, [])
        present += sum(value in existing for value in values)
        new += sum(value not in existing for value in values)
    data = merge_json(data, template)
    writer.write(path, json.dumps(data, indent=2) + "\n", f"{new} permisos nuevos ({present} ya estaban)")


def requirements() -> bool:
    good = sys.version_info >= (3, 11) and bool(shutil.which("git"))
    if shutil.which("git"):
        for key in ("user.name", "user.email"):
            proc = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True)
            good = good and bool(proc.stdout.strip())
    return good



def session_label(logged_in: bool | None) -> str:
    return "sí" if logged_in is True else "no" if logged_in is False else "desconocida (verifica con doctor --live)"


def login_steps(detected: dict, installed: list[str]) -> None:
    pending = [name for name in installed if detected[name].logged_in is not True]
    if not pending:
        print("✓ Todo listo: ai-delegate doctor --live")
        return
    messages = {
        "codex": "→ inicia sesión: codex login",
        "agy": "→ inicia sesión: abre agy y sigue el flujo",
        "claude": "→ claude: abre claude una vez para iniciar sesión (si usas Claude Desktop ya está)",
    }
    for name in pending:
        print(messages[name])
    print("→ verifica: ai-delegate doctor --live")

def setup(args, cfg: dict) -> int:
    writer = Writer(args.dry_run)
    ready = requirements()
    print(f"1. {'✓' if ready else '✗'} Requisitos: Python ≥3.11, git con user.name/user.email; node {'disponible' if shutil.which('node') else 'opcional, no instalado'}")
    if not ready:
        print('   → Instala Python/git y configura git config --global user.name y user.email')
    detected = detect_all()
    print("2. → IAs: IA | ruta | versión | sesión")
    for name, item in detected.items():
        print(f"   {name} | {item.path or 'no instalada'} | {item.version or '?'} | {session_label(item.logged_in)}")
        if item.note:
            print(f"   → {item.note}")
        if not item.path:
            print(f"   → {name}: {INSTALL[name]}")
    installed = [n for n, d in detected.items() if d.path]
    if not installed:
        raise DelegateError("No hay IAs instaladas; usa los comandos indicados")
    default = "claude" if "claude" in installed else installed[0]
    master = args.master or (default if args.yes else input(f"Maestra ({', '.join(installed)}) [{default}]: ").strip() or default)
    if master not in installed:
        raise DelegateError(f"Maestra no instalada: {master}")
    user = args.user_name or (cfg["user_name"] if args.yes else input(f"Tu nombre [{cfg['user_name']}]: ").strip() or cfg["user_name"])
    print(f"3. ✓ Maestra: {master}; usuario: {user}")
    agents = {}
    for name in installed:
        values = copy.deepcopy(cfg["agents"].get(name, config.DEFAULTS["agents"][name]))
        values.pop("permissions", None)
        values.update(bin="auto" if name == "claude" else detected[name].path, role_text=values.get("role_text", ROLES[name]))
        agents[name] = values
    print("4. → Config")
    if not update_config(writer, master, user, agents):
        return 1
    previous = config.main_name(cfg)
    cfg = {**cfg, "main": master, "user_name": user, "agents": agents}
    print("5. → Instrucciones de la maestra")
    instructions(writer, cfg, args.yes, previous if previous != master else None)
    print("6. → Hooks" + (" de Claude" if master == "claude" else " no requeridos"))
    hooks(writer, master == "claude", args.yes)
    if master == "claude":
        statusline(writer, args.yes)
    print("7. → Permisos de agy" + ("" if "agy" in installed else " (no instalado)"))
    if "agy" in installed:
        permissions(writer)
    link = Path.home() / ".local/bin/ai-delegate"
    print(f"8. → Enlace {link} → {ROOT / 'ai_delegate.py'}")
    if not writer.dry:
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink() or link.resolve() != ROOT / "ai_delegate.py":
            writer.backup(link)
            link.unlink(missing_ok=True)
            link.symlink_to(ROOT / "ai_delegate.py")
        target = ROOT / "ai_delegate.py"
        if not target.stat().st_mode & 0o111:
            writer.backup(target)
            target.chmod(target.stat().st_mode | 0o111)
    if str(link.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print('   → Agrega a ~/.bashrc o ~/.zshrc: export PATH="$HOME/.local/bin:$PATH"')
    print("9. → Final")
    login_steps(detected, installed)
    return 0 if ready else 1


def set_master(name: str, cfg: dict | None = None, yes: bool = True) -> None:
    cfg = cfg or config.load()
    detected = detect_all()
    old = config.main_name(cfg)
    if name not in detected or not detected[name].path:
        raise DelegateError(f"IA no instalada: {name}")
    writer = Writer()
    if not update_config(writer, name, cfg["user_name"], {}):
        raise DelegateError("No se pudo actualizar la configuración de la maestra.")
    new_cfg = {**cfg, "main": name}
    instructions(writer, new_cfg, yes, old if old != name else None)
    hooks(writer, name == "claude", yes)
    if name == "claude":
        statusline(writer, yes)


def master(args, cfg: dict) -> int:
    detected = detect_all()
    old = config.main_name(cfg)
    if not getattr(args, "name", None):
        print(f"Maestra: {old}; candidatos instalados: " + ", ".join(n for n, d in detected.items() if d.path))
        return 0
    set_master(args.name, cfg, yes=getattr(args, "yes", True))
    print(f"✓ Maestra: {args.name}")
    return 0


def run_doctor(live: bool = False, cfg: dict | None = None, timeout_s: float = 120.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    results: list[dict[str, Any]] = []

    def check(label: str, ok: bool, fix: str = "", detail: str = "") -> None:
        results.append({"check": label, "ok": ok, "detail": detail, "fix": fix if not ok else ""})

    check("Python ≥3.11", sys.version_info >= (3, 11), "instala Python ≥3.11", sys.version.split()[0])
    git_ok = requirements()
    check("git con identidad", git_ok, "instala git y configura user.name/user.email")

    link = Path.home() / ".local/bin/ai-delegate"
    link_ok = link.is_symlink() and link.resolve() == ROOT / "ai_delegate.py" and shutil.which("ai-delegate") == str(link)
    check("Enlace en PATH", link_ok, "ejecuta setup y agrega ~/.local/bin a PATH")

    try:
        loaded_cfg = config.load()
        valid = config.config_path().exists() and config.main_name(loaded_cfg) in loaded_cfg["agents"]
    except DelegateError:
        loaded_cfg, valid = copy.deepcopy(config.DEFAULTS), False
    cfg = cfg or loaded_cfg
    check("Config válida", valid, "ejecuta ai-delegate setup")

    detected = detect_all()
    name = config.main_name(cfg)
    check("Maestra detectada", bool(detected.get(name) and detected[name].path), "instala la CLI de la maestra", name)

    for agent in cfg.get("agents", {}):
        version = None
        try:
            runner = runners.get(agent, cfg)
            runner.ensure_available()
            proc = subprocess.run([runner.binary, "--version"], capture_output=True, text=True, timeout=5)
            version = proc.stdout.splitlines()[0] if proc.returncode == 0 and proc.stdout.strip() else None
            check(f"{agent}: binario y versión {version or '?'}", bool(version), "instala o corrige agents.<nombre>.bin", version or "")
        except (DelegateError, OSError, subprocess.SubprocessError):
            check(f"{agent}: binario y versión", False, "instala o corrige agents.<nombre>.bin")

        item = detected.get(agent)
        sess_ok = bool(item and item.logged_in is not False)
        sess_label = f"{agent}: sesión" + (" desconocida" if item and item.logged_in is None else "")
        check(sess_label, sess_ok, LOGIN.get(agent, "inicia sesión"))

        try:
            quota.get(agent, cfg, [])
            check(f"{agent}: cuota legible", True, "")
        except (OSError, ValueError, TypeError, KeyError):
            check(f"{agent}: cuota legible", False, "revisa los datos de cuota")

        if live:
            time_left = max(1.0, deadline - time.monotonic())
            if time_left <= 0:
                check(f"{agent}: live", False, "tiempo límite de doctor agotado")
                continue
            start = time.monotonic()
            try:
                with tempfile.TemporaryDirectory() as folder:
                    runner = runners.get(agent, cfg)
                    runner.ensure_available()
                    run_timeout = min(60, int(time_left))
                    result = runner.run("Responde solo: OK", "read", Path(folder), None, run_timeout, Path(folder))
                ok = result.ok and result.last_message.strip() == "OK"
            except (DelegateError, OSError):
                ok = False
            elapsed = time.monotonic() - start
            check(f"{agent}: live {elapsed:.1f} s", ok, "revisa login y CLI")

    path = Path.home() / FILES.get(name, ".claude/CLAUDE.md")
    text = path.read_text() if path.exists() else ""
    check("Bloque de instrucciones", START in text and END in text, "ejecuta setup")

    if name == "claude":
        try:
            data = read_json(Path.home() / ".claude/settings.json")
            expected = json.loads((ROOT / "setup/claude-hooks.json").read_text())["hooks"]
            ok = all(any(h.get("command") == hook_command() for g in data.get("hooks", {}).get(event, []) for h in g.get("hooks", [])) for event in expected)
        except DelegateError:
            ok = False
        check("Hooks de Claude", ok, "ejecuta setup")

        try:
            data = read_json(Path.home() / ".claude/settings.json")
            sl = data.get("statusLine")
            if not sl:
                check("Statusline de Claude", False, "ejecuta setup")
            else:
                cmd = sl.get("command", "") if isinstance(sl, dict) else str(sl)
                if "claude-statusline" in cmd:
                    check("Statusline de Claude", True, "")
                else:
                    check("Statusline de Claude", False,
                          f"Tienes un statusLine propio; para ver la cuota de Claude, encadena: {cmd}; ai-delegate claude-statusline")
        except DelegateError:
            check("Statusline de Claude", False, "ejecuta setup")

    if detected.get("agy") and detected["agy"].path:
        from .permissions import check_agy_settings_sync, get_effective_permissions
        agy_cfg = cfg.get("agents", {}).get("agy", {})
        agy_perms = get_effective_permissions(agy_cfg, "agy")
        agy_groups = agy_perms.get("groups", ["lectura"])
        settings_path = (Path(agy_cfg.get("home")) if agy_cfg.get("home") else Path.home()) / ".gemini/antigravity-cli/settings.json"
        ok = check_agy_settings_sync(agy_groups, settings_path)
        check("Permisos de agy", ok, "guarda los permisos de agy en Ajustes")

    try:
        config.data_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=config.data_dir()):
            pass
        writable = True
    except OSError:
        writable = False
    check("Carpeta de datos escribible", writable, "corrige permisos de la carpeta de datos")

    return results


def doctor(args, cfg: dict | None = None) -> int:
    results = run_doctor(live=getattr(args, "live", False), cfg=cfg)
    failed = False
    for r in results:
        failed |= not r["ok"]
        print(f"{'✓' if r['ok'] else '✗'} {r['check']}" + (f": {r['fix']}" if not r["ok"] else ""))
    return int(failed)
