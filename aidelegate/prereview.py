"""Revisión acotada del diff en una conversación independiente."""
from __future__ import annotations

import re
from pathlib import Path

from . import prompt, runners, worktree
from .sanitize import sanitize

RULE = ('Revisa SOLO el diff contra esta tarea. Reporta únicamente problemas reales: bugs, '
        'incumplimientos de la especificación o de los criterios, riesgos de seguridad, pruebas que escriben '
        'fuera de su carpeta temporal, código muerto o duplicado evidente. Una línea por problema con el '
        'formato "- [grave|medio|menor] archivo:línea — problema". Si no hay problemas, responde exactamente '
        '"SIN PROBLEMAS". No propongas estilo ni cambios opcionales.')


def parse(text: str) -> dict[str, list[str]]:
    result = {key: [] for key in ('grave', 'medio', 'menor')}
    for line in text.splitlines():
        match = re.fullmatch(r'- \[(grave|medio|menor)\] .+:\d+ — .+', line.strip())
        if match:
            result[match[1]].append(line.strip())
    return result


def run(meta, run_dir: Path, cfg: dict, timeout_s: int):
    settings = cfg.get('review', {})
    name = settings.get('agent', 'codex')
    rounds = (meta.prereview or {}).get('rounds', 0) + 1
    info = dict(agent=name, grave=0, medio=0, menor=0, rounds=rounds)
    try:
        runner = runners.get(name, cfg, kind="review")
        runner.ensure_available()
        runner.edit = False
        text = meta.task + '\n\n' + (prompt.load_design_spec(meta) or '') + '\n\n' + '\n'.join(meta.acceptance_criteria) + '\n\n' + RULE
        diff = worktree.diff(Path(meta.worktree or meta.workdir), meta.base_commit or 'HEAD')
        encoded = diff.encode('utf-8')
        notice = ''
        if len(encoded) > 80 * 1024:
            diff = encoded[:80 * 1024].decode('utf-8', errors='ignore')
            notice = '\n[Diff recortado a 80 KB; consulta el resto en el worktree.]'
        text += '\n\n## Diff contra la base\n\n' + diff + notice
        text = sanitize(text, source='el prompt de pre-revisión', mask_personal=False)
        folder = run_dir / 'review-runner'
        folder.mkdir(exist_ok=True)
        result = runner.run(text, 'read', Path(meta.workdir), None, timeout_s, folder)
        output = sanitize(result.last_message, source='la pre-revisión', on_secret='redact')
        (run_dir / 'review.md').write_text(output or sanitize(result.error, source='la pre-revisión', on_secret='redact'))
        if not result.ok:
            info.update(status='omitida', note=sanitize(result.error, source='la pre-revisión', on_secret='redact'))
            return info, [], result
        findings = parse(output)
        info.update({key: len(lines) for key, lines in findings.items()})
        blocked = [line for key, lines in findings.items() if key in settings.get('block_on', ['grave', 'medio']) for line in lines]
        return info, blocked, result
    except Exception as exc:
        note = sanitize(str(exc), source='la pre-revisión', on_secret='redact')
        info.update(status='omitida', note=note)
        (run_dir / 'review.md').write_text(note)
        return info, [], None
