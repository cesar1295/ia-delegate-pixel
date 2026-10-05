"""Verificación v5 con worktrees y HOME temporales."""
import json
import subprocess
from pathlib import Path

import pytest

from aidelegate import acceptance, config, prereview, report, runs, visual
from aidelegate.cli import main
from aidelegate.errors import DelegateError


def test_acceptance_parse_and_sources():
    block = '```acceptance\n# comentario\ncmd: true\ncontains: src/ :: hola\nnot-contains: src/ :: adiós\nexists: src/a\n```'
    assert len(acceptance.collect(block, '```acceptance\nexists: b\n```', extra=['cmd: false'])) == 6
    for bad in ['bad: a', 'exists:', 'contains: src/ texto', 'contains: src/ ::']:
        with pytest.raises(DelegateError, match=bad.replace('*', r'\*')):
            acceptance.parse(bad)


def test_acceptance_evaluate(repo):
    (repo / 'src').mkdir()
    (repo / 'src/a').write_text('hola')
    (repo / 'src/b').write_bytes(b'\x00hola')
    (repo / 'src/node_modules').mkdir()
    (repo / 'src/node_modules/no').write_text('console.log')
    criteria = acceptance.parse('cmd: true\ncontains: src/ :: hola\nnot-contains: src/ :: console.log\nexists: src/a')
    result, log = acceptance.evaluate(criteria, repo, 5)
    assert result == {'total': 4, 'ok': 4, 'failed': []}
    assert 'OK' in log
    result, _ = acceptance.evaluate(['cmd: false', 'contains: src/a :: ausente', 'exists: perdido'], repo, 5)
    assert len(result['failed']) == 3


def test_acceptance_combined_cli(home, repo, tmp_path):
    task = tmp_path / 'task.md'
    task.write_text('hazlo\n```acceptance\nexists: hecho.txt\n```')
    design = tmp_path / 'spec.md'
    design.write_text('```acceptance\ncontains: hecho.txt :: hecho\n```')
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--task-file', str(task),
                 '--design-spec', str(design), '--accept', 'cmd: true', '--check', 'none', '--no-review',
                 '```acceptance\nnot-contains: hecho.txt :: malo\n```']) == 0
    meta = runs.load(runs.resolve('last'))
    assert meta.acceptance['total'] == meta.acceptance['ok'] == 4
    assert 'Antes de entregar, verifica cada criterio' in (runs.resolve('last') / 'prompt.md').read_text()


def test_acceptance_correction(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', '--no-review',
                 '--accept', 'exists: hecho.txt', 'FALLA_PRIMERO']) == 0
    meta = runs.load(runs.resolve('last'))
    assert meta.fix_rounds == 1
    assert meta.status == 'listo-para-revisar'
    assert meta.acceptance['ok'] == 1


def test_invalid_acceptance_before_agent(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--accept', 'mal escrito', 'hazlo']) == 2
    assert not (repo / 'hecho.txt').exists()
    assert not (runs.resolve('last') / 'events.jsonl').exists()


@pytest.mark.parametrize('keyword,fixes,status', [('REVISION_GRAVE', 1, None),
                                                   ('REVISION_LIMPIA', 0, None),
                                                   ('REVISION_CAIDA', 0, 'omitida')])
def test_review_loop(home, repo, keyword, fixes, status):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', keyword]) == 0
    folder = runs.resolve('last')
    meta = runs.load(folder)
    assert meta.status == 'listo-para-revisar'
    assert meta.fix_rounds == fixes
    assert meta.prereview.get('status') == status
    assert any(h['label'] == 'pre-revisión' for h in meta.history)
    if status is None:
        assert any(h['label'] == 'pre-revisión' and h['usage'] for h in meta.history)
    assert (folder / 'review.md').exists()
    if fixes:
        assert meta.prereview['rounds'] == 2
        assert meta.prereview['grave'] == 1


def test_review_parse():
    parsed = prereview.parse('ruido\n- [grave] src/a:2 — bug\n- [medio] src/b:10 — bug\n- [menor] src/c:1 — duplicado\n- [grave] sin línea\nSIN PROBLEMAS')
    assert {key: len(value) for key, value in parsed.items()} == {'grave': 1, 'medio': 1, 'menor': 1}


def test_visual_detection_and_preview(tmp_path):
    assert visual.applies(['src/page.tsx'])
    assert not visual.applies(['README.md', 'app.py'])
    assert visual.preview_command(tmp_path, {'preview': 'serve {port}'}) == 'serve {port}'
    assert visual.preview_command(tmp_path, {}) is None
    (tmp_path / 'index.html').touch()
    assert 'http.server' in visual.preview_command(tmp_path, {})
    (tmp_path / 'package.json').write_text(json.dumps({'scripts': {'dev': 'vite'}}))
    (tmp_path / 'pnpm-lock.yaml').touch()
    assert visual.preview_command(tmp_path, {}) == 'pnpm run dev -- --port {port}'


def test_visual_missing_tools(repo, tmp_path, monkeypatch):
    (repo / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(visual.shutil, 'which', lambda name: None)
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    assert visual.run(meta, tmp_path, config.load()) == {
        'status': 'omitida', 'shots': [], 'errors': 0, 'note': 'falta node 22 o navegador'}


def test_report_v5(tmp_path, capsys):
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(tmp_path), str(tmp_path), 't')
    meta.acceptance = {'total': 4, 'ok': 4, 'failed': []}
    meta.visual = {'status': 'ok', 'shots': ['a', 'b', 'c', 'd'], 'errors': 0, 'note': ''}
    meta.prereview = {'agent': 'codex', 'grave': 0, 'medio': 0, 'menor': 2, 'rounds': 1}
    report.print_run(meta, tmp_path, 10)
    output = capsys.readouterr().out
    assert 'aceptación: 4/4 ✓' in output
    assert 'vista: 4 capturas, 0 errores' in output
    assert 'pre-revisión (codex): 0 graves · 0 medios · 2 menores' in output


@pytest.mark.parametrize("console_error", [False, True])
def test_visual_real_browser(repo, tmp_path, console_error):
    if not all(visual.tools_available()):
        pytest.skip('falta node 22 o navegador')
    try:
        visual.free_port()
    except PermissionError:
        pytest.skip('el sandbox bloquea sockets locales')
    (repo / 'index.html').write_text('<!doctype html><title>Prueba</title><p>Hola</p>'
                                    + ('<script>console.error("error de prueba"); throw new Error("excepción de prueba")</script>'
                                       if console_error else ''))
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    result = visual.run(meta, tmp_path, config.load())
    assert result['status'] == ('fallo' if console_error else 'ok'), result['note']
    if console_error:
        assert result['errors'] >= 2
    assert len(result['shots']) == 2
    assert all((tmp_path / shot).exists() for shot in result['shots'])


def test_pipeline_order_and_visual_correction(home, repo, monkeypatch):
    order = []
    original = acceptance.evaluate

    def evaluate(*args):
        order.append('aceptacion')
        return original(*args)

    def view(*args):
        order.append('vista')
        return dict(status='fallo' if order.count('vista') == 1 else 'ok', shots=[], errors=1,
                    note='console.error: fallo')

    original_review = prereview.run

    def review(*args):
        order.append('pre-revision')
        return original_review(*args)

    monkeypatch.setattr(acceptance, 'evaluate', evaluate)
    monkeypatch.setattr(visual, 'run', view)
    monkeypatch.setattr(prereview, 'run', review)
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'test -f hecho.txt', 'hazlo']) == 0
    meta = runs.load(runs.resolve('last'))
    assert meta.fix_rounds == 1
    assert order == ['aceptacion', 'vista', 'aceptacion', 'vista', 'pre-revision']
    assert 'console.error: fallo' in (runs.resolve('last') / 'prompt.md').read_text()


def test_acceptance_exhaustion(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', '--max-fix-rounds', '0',
                 '--accept', 'exists: ausente', 'hazlo']) == 1
    meta = runs.load(runs.resolve('last'))
    assert meta.status == 'checks-fallidos'
    assert meta.prereview is None


def test_api_exposes_v5(home, repo):
    from aidelegate.ui_server import run_detail
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', 'REVISION_LIMPIA']) == 0
    meta = runs.load(runs.resolve('last'))
    data = run_detail(meta.run_id)
    assert data['acceptance'] == meta.acceptance
    assert data['visual'] == meta.visual
    assert data['prereview'] == meta.prereview


def test_acceptance_cmd_tail_and_redaction(repo):
    result, log = acceptance.evaluate(["cmd: for i in {1..90}; do echo linea$i; done; exit 1"], repo, 5)
    assert result['failed'][0].endswith('código 1')
    assert 'linea30\n' not in log and 'linea31\n' in log


def test_read_does_not_run_stages(home, repo):
    assert main(['run', '--to', 'codex', '--mode', 'read', '--dir', str(repo), 'REVISION_LIMPIA']) == 0
    meta = runs.load(runs.resolve('last'))
    assert meta.acceptance is meta.visual is meta.prereview is None


def test_acceptance_escalates(home, repo):
    from aidelegate import config
    path = config.config_path()
    with path.open('a') as fh:
        fh.write('escalate_after = 1\n')
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none',
                 '--accept', 'exists: imposible', 'hazlo']) == 3
    meta = runs.load(runs.resolve('last'))
    assert meta.status == 'escalado-a-main'
    assert meta.fix_rounds == 1
    assert 'exists: imposible' in meta.feedback[-1]


def test_review_codex_command_and_new_conversation(home, repo, monkeypatch):
    from aidelegate.runners.codex import CodexRunner
    calls = []
    original = CodexRunner.argv

    def argv(self, text, mode, cwd, resume):
        command = original(self, text, mode, cwd, resume)
        calls.append((text, mode, cwd, resume, command))
        return command

    monkeypatch.setattr(CodexRunner, 'argv', argv)
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', 'REVISION_LIMPIA']) == 0
    text, mode, cwd, resume, command = calls[-1]
    assert mode == 'read' and resume is None
    assert command[1] == 'exec'
    assert 'review' not in command and '--uncommitted' not in command
    assert 'sandbox_mode="read-only"' in command
    assert 'diff --git' in text and '+hecho' in text
    assert 'Revisa SOLO el diff contra esta tarea' in text
    assert str(cwd) == runs.load(runs.resolve('last')).workdir


def test_no_review_skips_reviewer(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', '--no-review', 'REVISION_GRAVE']) == 0
    meta = runs.load(runs.resolve('last'))
    assert meta.prereview is None
    assert len(meta.history) == 1


def test_node_old_is_unavailable(monkeypatch):
    monkeypatch.setattr(visual.shutil, 'which', lambda name: '/bin/' + name)
    monkeypatch.setattr(visual.subprocess, 'check_output', lambda *a, **kw: 'v20.1.0')
    assert visual.tools_available()[0] is None


def test_new_phases_are_checks(tmp_path):
    from datetime import datetime
    from aidelegate.ui_state import _agent
    import os
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(tmp_path), str(tmp_path), 't', pid=os.getpid())
    for phase, detail in [('aceptacion', 'verificando criterios'), ('vista', 'revisando la vista'),
                          ('pre-revision', 'pre-revisión de código')]:
        meta.phase = phase
        state = _agent([meta], datetime.now(), 3)
        assert state['state'] == 'checks'
        assert state['detail'] == detail


def test_acceptance_secret_is_not_saved(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--accept',
                 'cmd: echo GITHUB_TOKEN=abc123', 'hazlo']) == 2
    folder = runs.resolve('last')
    assert 'abc123' not in (folder / 'meta.json').read_text()
    assert not (folder / 'events.jsonl').exists()


def test_master_email_survives_task_spec_context_and_feedback(home, repo, tmp_path, monkeypatch):
    from aidelegate.runners.codex import CodexRunner
    calls = []
    original = CodexRunner.argv

    def argv(self, text, *args):
        calls.append(text)
        return original(self, text, *args)

    monkeypatch.setattr(CodexRunner, 'argv', argv)
    design = tmp_path / 'design.md'
    design.write_text('Enlace mailto:design@example.com')
    context = tmp_path / 'context.md'
    context.write_text('Contacto context@example.com')
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none',
                 '--design-spec', str(design), '--context-file', str(context),
                 'Agrega mailto:task@example.com']) == 0
    assert 'mailto:task@example.com' in calls[0]
    assert 'mailto:design@example.com' in calls[0]
    assert 'context@example.com' in calls[0]
    assert 'mailto:task@example.com' in calls[1]  # revisor independiente
    assert 'mailto:design@example.com' in calls[1]
    assert main(['feedback', runs.resolve('last').name, 'Usa feedback@example.com']) == 0
    assert 'feedback@example.com' in calls[2]
    meta = runs.load(runs.resolve('last'))
    assert 'task@example.com' in meta.task
    assert meta.feedback == ['Usa feedback@example.com']


def test_check_output_email_is_masked_in_correction_and_log(home, repo):
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--no-review',
                 '--check', 'echo external@example.com; test -f hecho.txt', 'FALLA_PRIMERO']) == 0
    folder = runs.resolve('last')
    text = (folder / 'prompt.md').read_text()
    correction_output = text.split('Últimas líneas de la salida:')[1]
    assert 'external@example.com' not in correction_output
    assert '[CORREO]' in correction_output
    assert (folder / 'checks.log').read_text() == '[CORREO]'


def test_failed_criterion_email_is_masked(repo):
    result, log = acceptance.evaluate(['contains: ausente :: person@example.com'], repo, 5)
    assert 'person@example.com' not in log
    assert '[CORREO]' in result['failed'][0]


def test_review_diff_byte_limit(home, repo, monkeypatch):
    from aidelegate import worktree
    from aidelegate.runners.codex import CodexRunner
    original = CodexRunner.argv
    prompts = []

    def argv(self, text, *args):
        prompts.append(text)
        return original(self, text, *args)

    monkeypatch.setattr(CodexRunner, 'argv', argv)
    # Patch only for the reviewer: agent_round and diffstat also call worktree.diff.
    original_review = prereview.run

    def review(*args):
        with monkeypatch.context() as patch:
            patch.setattr(worktree, 'diff', lambda *a: 'á' * (80 * 1024))
            return original_review(*args)

    monkeypatch.setattr(prereview, 'run', review)
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', 'REVISION_LIMPIA']) == 0
    text = prompts[-1]
    payload = text.split('## Diff contra la base\n\n')[1].split('\n[Diff recortado')[0]
    assert len(payload.encode('utf-8')) == 80 * 1024
    assert '[Diff recortado a 80 KB; consulta el resto en el worktree.]' in text


def test_omitted_review_report_has_no_clean_counts(tmp_path, capsys):
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(tmp_path), str(tmp_path), 't')
    meta.prereview = dict(agent='codex', grave=0, medio=0, menor=0, rounds=1,
                          status='omitida', note='error del revisor\nsegunda línea ' + 'x' * 500)
    report.print_run(meta, tmp_path, 10)
    text = capsys.readouterr().out
    lines = [line for line in text.splitlines() if line.startswith('pre-revisión')]
    assert len(lines) == 1
    assert lines[0].startswith('pre-revisión: omitida — error del revisor segunda línea')
    assert '0 graves' not in text
    assert len(lines[0]) <= len('pre-revisión: omitida — ') + 200


def test_visual_masks_external_errors_and_preview_log(repo, tmp_path, monkeypatch):
    from contextlib import nullcontext
    (repo / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(visual, 'tools_available', lambda: ('node', 'browser'))
    monkeypatch.setattr(visual, 'free_port', lambda: 12345)
    monkeypatch.setattr(visual.urllib.request, 'urlopen', lambda *a, **kw: nullcontext())
    monkeypatch.setattr(visual.os, 'killpg', lambda *a: None)

    class Process:
        pid = 123456
        returncode = 0

        def __init__(self, args, **kwargs):
            if args[0] == 'bash':
                kwargs['stdout'].write('preview external@example.com\n')
                kwargs['stdout'].flush()

        def wait(self, **kwargs):
            return 0

        def communicate(self, **kwargs):
            return json.dumps({'shots': ['screens/inicio.png'], 'errors': [
                {'path': '/', 'size': 'movil', 'text': 'error external@example.com'}]}), ''

    from types import SimpleNamespace
    monkeypatch.setattr(visual.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='index.html\n'))
    monkeypatch.setattr(visual.subprocess, 'Popen', Process)
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    result = visual.run(meta, tmp_path, config.load())
    assert result['status'] == 'fallo'
    assert '[CORREO]' in result['note'] and 'external@example.com' not in result['note']
    assert (tmp_path / 'preview.log').read_text() == 'preview [CORREO]\n'


def test_visual_empty_node_modules_is_omitted(repo, tmp_path, monkeypatch):
    def unexpected_tools():
        pytest.fail("no debe intentar arrancar la vista sin dependencias")
    monkeypatch.setattr(visual, "tools_available", unexpected_tools)
    (repo / 'package.json').write_text(json.dumps({'scripts': {'dev': 'vite'}}))
    (repo / 'index.html').write_text('<html></html>')
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    # Sin node_modules
    res = visual.run(meta, tmp_path, config.load())
    assert res['status'] == 'omitida'
    assert 'faltan dependencias: corre npm install (o pnpm/yarn) en el proyecto' in res['note']

    # Con node_modules vacío
    (repo / 'node_modules').mkdir(exist_ok=True)
    res = visual.run(meta, tmp_path, config.load())
    assert res['status'] == 'omitida'
    assert 'faltan dependencias: corre npm install (o pnpm/yarn) en el proyecto' in res['note']


def test_visual_omitted_does_not_trigger_correction(home, repo, monkeypatch):
    calls = []

    def fake_view(*args):
        calls.append('vista')
        return {'status': 'omitida', 'shots': [], 'errors': 0,
                'note': 'faltan dependencias: corre npm install (o pnpm/yarn) en el proyecto'}

    monkeypatch.setattr(visual, 'run', fake_view)
    assert main(['run', '--to', 'codex', '--dir', str(repo), '--check', 'none', 'hazlo']) == 0
    meta = runs.load(runs.resolve('last'))
    assert calls == ['vista']
    assert meta.visual['status'] == 'omitida'
    assert meta.fix_rounds == 0
    assert meta.status == 'listo-para-revisar'


def test_visual_server_fails_to_start_is_omitted(repo, tmp_path, monkeypatch):
    (repo / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(visual, 'tools_available', lambda: ('node', 'browser'))
    monkeypatch.setattr(visual, 'free_port', lambda: 12345)
    monkeypatch.setattr(visual.os, 'killpg', lambda *a: None)

    class FailingProcess:
        pid = 123456
        returncode = 1

        def __init__(self, args, **kwargs):
            if kwargs.get('stdout'):
                kwargs['stdout'].write('línea descartada\nuno\ndos\nerror fatal en servidor\n')
                kwargs['stdout'].flush()

        def poll(self):
            return 1

        def wait(self, **kwargs):
            return 1

    from types import SimpleNamespace
    monkeypatch.setattr(visual.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='index.html\n'))
    monkeypatch.setattr(visual.subprocess, 'Popen', FailingProcess)

    cfg = config.load()
    cfg.setdefault('projects', {})[str(repo)] = {'preview': 'dummy-cmd {port}'}
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    res = visual.run(meta, tmp_path, cfg)
    assert res['status'] == 'omitida'
    assert 'no se pudo levantar el proyecto:' in res['note']
    assert res['note'] == 'no se pudo levantar el proyecto:\nuno\ndos\nerror fatal en servidor'


def test_visual_console_errors_fail(repo, tmp_path, monkeypatch):
    from contextlib import nullcontext
    (repo / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(visual, 'tools_available', lambda: ('node', 'browser'))
    monkeypatch.setattr(visual, 'free_port', lambda: 12345)
    monkeypatch.setattr(visual.urllib.request, 'urlopen', lambda *a, **kw: nullcontext())
    monkeypatch.setattr(visual.os, 'killpg', lambda *a: None)

    class Process:
        pid = 123456
        returncode = 0

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return None

        def wait(self, **kwargs):
            return 0

        def communicate(self, **kwargs):
            return json.dumps({'shots': ['screens/inicio.png'], 'errors': [
                {'path': '/', 'size': 'movil', 'text': 'Uncaught Error: falló la vista'}]}), ''

    from types import SimpleNamespace
    monkeypatch.setattr(visual.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='index.html\n'))
    monkeypatch.setattr(visual.subprocess, 'Popen', Process)
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    result = visual.run(meta, tmp_path, config.load())
    assert result['status'] == 'fallo'
    assert 'Uncaught Error: falló la vista' in result['note']


def test_visual_server_timeout_is_omitted(repo, tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError('servidor no disponible')
    monkeypatch.setattr(visual.urllib.request, 'urlopen', unavailable)
    (repo / 'index.html').write_text('<html></html>')
    monkeypatch.setattr(visual, 'tools_available', lambda: ('node', 'browser'))
    monkeypatch.setattr(visual, 'free_port', lambda: 12345)
    monkeypatch.setattr(visual.os, 'killpg', lambda *a: None)

    class HangingProcess:
        pid = 123456
        returncode = None

        def __init__(self, args, **kwargs):
            if kwargs.get('stdout'):
                kwargs['stdout'].write('iniciando servidor...\n')
                kwargs['stdout'].flush()

        def poll(self):
            return None

        def wait(self, **kwargs):
            return 0

    from types import SimpleNamespace
    monkeypatch.setattr(visual.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='index.html\n'))
    monkeypatch.setattr(visual.subprocess, 'Popen', HangingProcess)
    deadline_reached = [False]

    def fake_monotonic():
        if deadline_reached[0]:
            return 999999999
        deadline_reached[0] = True
        return 0

    monkeypatch.setattr(visual.time, 'monotonic', fake_monotonic)
    monkeypatch.setattr(visual.time, 'sleep', lambda s: None)

    cfg = config.load()
    cfg.setdefault('projects', {})[str(repo)] = {'preview': 'dummy-cmd {port}'}
    meta = runs.RunMeta('x', 'codex', 'write', 'feature', 'r', str(repo), str(repo), 't')
    res = visual.run(meta, tmp_path, cfg)
    assert res['status'] == 'omitida'
    assert 'no se pudo levantar el proyecto:' in res['note']
    assert 'iniciando servidor...' in res['note']
