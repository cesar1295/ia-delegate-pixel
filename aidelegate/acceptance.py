"""Criterios literales y comandos verificables de una tarea."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import checks
from .errors import DelegateError
from .sanitize import sanitize


def parse(text: str) -> list[str]:
    criteria = []
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        match = re.fullmatch(r'(cmd|exists|contains|not-contains):\s*(.+)', value)
        if not match or (match[1] in {'contains', 'not-contains'} and
                         ('::' not in match[2] or not all(part.strip() for part in match[2].split('::', 1)))):
            raise DelegateError(f'Criterio de aceptación inválido: {line}')
        criteria.append(value)
    return criteria


def collect(*sources: str, extra: list[str] | None = None) -> list[str]:
    result = []
    for source in sources:
        for block in re.findall(r'^\s*```acceptance\s*\n(.*?)^\s*```', source or '', re.M | re.S):
            result.extend(parse(block))
    for item in extra or []:
        result.extend(parse(item))
    return result


def evaluate(criteria: list[str], cwd: Path, timeout_s: int) -> tuple[dict, str]:
    failed, log = [], []
    for criterion in criteria:
        kind, value = criterion.split(':', 1)
        value, reason, detail = value.strip(), '', ''
        try:
            if kind == 'cmd':
                check = checks.run(value, cwd, timeout_s)
                detail = sanitize('\n'.join(check.output.splitlines()[-60:]),
                                  source='la salida de los checks', on_secret='redact')
                if not check.ok:
                    reason = f'código {check.exit_code}'
            else:
                raw = value.split('::', 1)[0].strip()
                path = (cwd / raw).resolve()
                if not path.is_relative_to(cwd.resolve()):
                    reason = 'ruta fuera del directorio de trabajo'
                elif kind == 'exists':
                    if not path.exists():
                        reason = 'no existe'
                else:
                    needle = value.split('::', 1)[1].strip()
                    if path.is_dir():
                        proc = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                              cwd=cwd, capture_output=True)
                        files = ([(cwd / p.decode()).resolve() for p in proc.stdout.split(b'\0') if p]
                                 if proc.returncode == 0 else [p.resolve() for p in path.rglob('*')])
                        files = [p for p in files if p.is_relative_to(path) and
                                 not {'node_modules', '.venv', '.git'}.intersection(p.relative_to(cwd.resolve()).parts)]
                    else:
                        files = [path]
                    found = False
                    for file in files:
                        if not file.is_relative_to(cwd.resolve()) or not file.is_file():
                            continue
                        try:
                            content = file.read_text(encoding='utf-8')
                        except (UnicodeError, OSError):
                            continue
                        if '\0' not in content and needle in content:
                            found = True
                            break
                    if not path.exists():
                        reason = 'no existe'
                    elif found != (kind == 'contains'):
                        reason = 'texto ausente' if kind == 'contains' else 'texto encontrado'
        except (OSError, subprocess.SubprocessError) as exc:
            reason = str(exc)
        entry = f'{criterion}: {reason or "OK"}' + ('\n' + detail if detail else '')
        log.append(sanitize(entry, source='los criterios fallidos', on_secret='redact') if reason else entry)
        if reason:
            failed.append(sanitize(f'{criterion}: {reason.splitlines()[0]}', source='los criterios fallidos', on_secret='redact'))
    return {'total': len(criteria), 'ok': len(criteria) - len(failed), 'failed': failed}, '\n'.join(log)
