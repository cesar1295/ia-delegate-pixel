"""Servicio del sistema (systemd / launchd) y modo aplicación para la oficina."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import config
from .errors import DelegateError

ROOT = Path(__file__).resolve().parent.parent


def linux_unit_path() -> Path:
    return Path.home() / ".config/systemd/user/ai-delegate-ui.service"


def macos_plist_path() -> Path:
    return Path.home() / "Library/LaunchAgents/com.ai-delegate.ui.plist"


def handle_service(action: str, port: int) -> int:
    """Gestiona el servicio en segundo plano de la UI según el sistema operativo."""
    if sys.platform.startswith("linux"):
        return _service_linux(action, port)
    elif sys.platform == "darwin":
        return _service_macos(action, port)
    raise DelegateError("El servicio en segundo plano no está soportado en este sistema; ejecuta 'ai-delegate ui' a mano.")


def _service_linux(action: str, port: int) -> int:
    unit_path = linux_unit_path()
    service_name = "ai-delegate-ui.service"
    url = f"http://127.0.0.1:{port}"

    if action == "install":
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        py_bin = str(Path(sys.executable).resolve())
        cli_bin = str((ROOT / "ai_delegate.py").resolve())
        content = (
            "[Unit]\n"
            "Description=ai-delegate UI\n"
            "After=network.target\n\n"
            "[Service]\n"
            f"ExecStart={py_bin} {cli_bin} ui --no-open --port {port}\n"
            "Restart=on-failure\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        unit_path.write_text(content, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", service_name], check=True)
        print(f"Servicio instalado y activo en {url}")
        return 0

    elif action == "uninstall":
        subprocess.run(["systemctl", "--user", "disable", "--now", service_name], check=False)
        unit_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        print("Servicio desinstalado.")
        return 0

    elif action == "status":
        proc = subprocess.run(["systemctl", "--user", "is-active", service_name], capture_output=True, text=True)
        active = proc.returncode == 0 and proc.stdout.strip() == "active"
        state = "activo" if active else "inactivo"
        print(f"{state} - {url}")
        return 0

    raise DelegateError(f"Acción de servicio desconocida: {action}")


def _service_macos(action: str, port: int) -> int:
    plist_path = macos_plist_path()
    label = "com.ai-delegate.ui"
    url = f"http://127.0.0.1:{port}"
    py_bin = str(Path(sys.executable).resolve())
    cli_bin = str((ROOT / "ai_delegate.py").resolve())

    if action == "install":
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py_bin}</string>
        <string>{cli_bin}</string>
        <string>ui</string>
        <string>--no-open</string>
        <string>--port</string>
        <string>{port}</string>
    </array>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
        plist_path.write_text(content, encoding="utf-8")
        subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=True)
        print(f"Servicio instalado y activo en {url}")
        return 0

    elif action == "uninstall":
        subprocess.run(["launchctl", "unload", "-w", str(plist_path)], check=False)
        plist_path.unlink(missing_ok=True)
        print("Servicio desinstalado.")
        return 0

    elif action == "status":
        proc = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
        state = "activo" if proc.returncode == 0 else "inactivo"
        print(f"{state} - {url}")
        return 0

    raise DelegateError(f"Acción de servicio desconocida: {action}")


def is_server_responding(port: int) -> bool:
    """Comprueba si el servidor de UI responde en el puerto."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def open_app(port: int) -> int:
    """Inicia el servidor si no responde y abre una ventana de aplicación."""
    url = f"http://127.0.0.1:{port}"
    if not is_server_responding(port):
        log_dir = config.data_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ui.log"
        fh = log_file.open("a", encoding="utf-8")
        py_bin = str(Path(sys.executable).resolve())
        cli_bin = str((ROOT / "ai_delegate.py").resolve())
        subprocess.Popen(
            [py_bin, cli_bin, "ui", "--no-open", "--port", str(port)],
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )
        for _ in range(30):
            time.sleep(0.1)
            if is_server_responding(port):
                break

    browsers = ["brave-browser", "google-chrome", "chromium", "chromium-browser", "microsoft-edge"]
    found_bin = next((path for b in browsers if (path := shutil.which(b))), None)
    if found_bin:
        subprocess.Popen([found_bin, f"--app={url}", "--window-size=480,860"])
    else:
        webbrowser.open(url)
    return 0
