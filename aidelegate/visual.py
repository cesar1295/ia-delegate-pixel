"""Servidor temporal y capturas CDP; sin dependencias Python externas."""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from .checks import _node_manager
from .sanitize import sanitize

EXTENSIONS = {'.html', '.css', '.scss', '.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte', '.astro'}
BROWSERS = ('brave-browser', 'google-chrome', 'chromium', 'chromium-browser', 'microsoft-edge')


def applies(files: list[str]) -> bool:
    return any(Path(file).suffix.lower() in EXTENSIONS for file in files)


def preview_command(cwd: Path, project: dict) -> str | None:
    if project.get('preview'):
        return project['preview']
    try:
        scripts = json.loads((cwd / 'package.json').read_text()).get('scripts', {})
        for script in ('dev', 'preview'):
            if scripts.get(script):
                return f'{_node_manager(cwd)} run {script} -- --port {{port}}'
    except (OSError, ValueError):
        pass
    if (cwd / 'index.html').is_file():
        return 'python3 -m http.server {port} --bind 127.0.0.1'
    return None


def tools_available() -> tuple[str | None, str | None]:
    node = shutil.which('node')
    try:
        if not node or int(subprocess.check_output([node, '--version'], text=True).strip().lstrip('v').split('.')[0]) < 22:
            node = None
    except (OSError, ValueError, subprocess.SubprocessError):
        node = None
    return node, next((p for name in BROWSERS if (p := shutil.which(name))), None)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run(meta, run_dir: Path, cfg: dict) -> dict:
    cwd = Path(meta.workdir)
    project = cfg.get('projects', {}).get(meta.project_root or meta.source_dir, {})
    proc = subprocess.run(['git', 'diff', '--name-only', meta.base_commit or 'HEAD'], cwd=cwd, capture_output=True, text=True)
    new = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard'], cwd=cwd, capture_output=True, text=True)
    command = preview_command(cwd, project)
    info = dict(status='omitida', shots=[], errors=0, note='sin cambios web o sin servidor de preview')
    if not applies((proc.stdout + '\n' + new.stdout).splitlines()) or not command:
        return info
    node_modules = cwd / 'node_modules'
    try:
        has_nm = node_modules.is_dir() and any(node_modules.iterdir())
    except OSError:
        has_nm = False
    if (cwd / 'package.json').is_file() and not has_nm:
        info['note'] = 'faltan dependencias: corre npm install (o pnpm/yarn) en el proyecto'
        return info
    node, browser = tools_available()
    if not node or not browser:
        info['note'] = 'falta node 22 o navegador'
        return info
    paths = project.get('preview_paths', ['/'])
    server = None
    try:
        port = free_port()
        with (run_dir / 'preview.log').open('w') as log:
            server = subprocess.Popen(['bash', '-c', command.replace('{port}', str(port))], cwd=cwd,
                                      env={**os.environ, 'PORT': str(port)}, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 60
            server_ok = False
            for path in paths:
                while True:
                    if hasattr(server, 'poll') and server.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=1):
                            break
                    except (OSError, ValueError):
                        if (hasattr(server, 'poll') and server.poll() is not None) or time.monotonic() >= deadline:
                            break
                        time.sleep(.2)
                if (hasattr(server, 'poll') and server.poll() is not None) or time.monotonic() >= deadline:
                    break
            else:
                server_ok = True
            if not server_ok:
                log.flush()
                log_lines = (run_dir / 'preview.log').read_text(errors='replace').strip().splitlines()[-3:]
                tail = '\n'.join(log_lines)
                note = f"no se pudo levantar el proyecto:\n{tail}" if '\n' in tail else f"no se pudo levantar el proyecto: {tail}".strip()
                info.update(status='omitida', note=sanitize(note, source='la vista', on_secret='redact'))
                return info
            capture = subprocess.Popen([node, str(Path(__file__).with_name('visual_cdp.mjs')), browser,
                                      str(port), str(run_dir.resolve()), json.dumps(paths)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = capture.communicate(timeout=180)
            finally:
                try:
                    os.killpg(capture.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                capture.wait()
            if capture.returncode:
                raise RuntimeError(stderr[-4000:])
            result = json.loads(stdout)
            info.update(status='fallo' if result['errors'] else 'ok', shots=result['shots'],
                        errors=len(result['errors']), note=sanitize('\n'.join(str(e) for e in result['errors'][:20]),
                                                                  source='la vista', on_secret='redact'))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        info.update(status='omitida', note=sanitize(str(exc), source='la vista', on_secret='redact'))
    finally:
        if server:
            try:
                os.killpg(server.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                if hasattr(server, 'wait'):
                    server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(server.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                try:
                    if hasattr(server, 'wait'):
                        server.wait()
                except OSError:
                    pass
            except OSError:
                pass
        log_path = run_dir / 'preview.log'
        if log_path.exists():
            log_path.write_text(sanitize(log_path.read_text(errors='replace'), source='los logs de la vista', on_secret='redact'))
    return info
