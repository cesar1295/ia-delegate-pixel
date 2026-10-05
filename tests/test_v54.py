import io
import json
import subprocess
import threading
from email.message import Message
from types import SimpleNamespace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pytest

from aidelegate import cli, config, install, reconcile, runs, stats, worktree
from aidelegate.runs import RunMeta
from aidelegate.ui_server import Handler
from aidelegate.ui_state import build_state


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def meta(repo, **kwargs):
    m = RunMeta('v54-run', 'codex', 'write', 'feature', repo.name, str(repo), str(repo), 'Una tarea',
                project_root=str(repo), status='listo-para-revisar', **kwargs)
    runs.create(m)
    return m


def persist(m):
    # Mantiene fechas sintéticas para pruebas de antigüedad; en producción save
    # siempre publica el instante real de la modificación.
    with runs.state_lock():
        (config.runs_dir() / m.run_id / 'meta.json').write_text(json.dumps(vars(m)))


def wt_meta(repo):
    m = meta(repo)
    wt = worktree.create(repo, m.run_id)
    m.worktree, m.branch, m.base_commit, m.base_branch = str(wt.path), wt.branch, wt.base_commit, wt.base_branch
    runs.save(m, config.runs_dir() / m.run_id)
    return m


def test_touched(repo):
    (repo / 'previo').write_text('inicio')
    (repo / 'intacto').write_text('sin tocar')
    m = meta(repo)
    runs.capture_start(m)
    (repo / 'previo').write_text('otro')
    (repo / 'nuevo con espacios').write_text('nuevo')
    runs.track_touched(m)
    assert m.touched_files == ['nuevo con espacios', 'previo']
    assert m.diffstat == '2 archivos tocados'
    (repo / 'intacto').unlink()
    runs.track_touched(m)
    assert 'intacto' in m.touched_files


@pytest.mark.parametrize('action,outcome', [('commit', 'integrado'), ('revert', 'descartado'), ('dirty', None)])
def test_folder(repo, action, outcome):
    m = meta(repo)
    runs.capture_start(m)
    (repo / 'nuevo').write_text('cambio')
    runs.track_touched(m)
    if action == 'commit':
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'manual')
    elif action == 'revert':
        (repo / 'nuevo').unlink()
    persist(m)
    results = reconcile.reconcile([m])
    assert m.status == (outcome or 'listo-para-revisar')
    assert bool(results) == bool(outcome)
    if outcome:
        loaded = runs.load(config.runs_dir() / m.run_id)
        assert loaded.closed_reason and loaded.events[-1]['type'] == 'auto-cerrada'
        assert stats.read_rows()[-1]['outcome'] == outcome
        assert reconcile.reconcile([m]) == []


@pytest.mark.parametrize('dirty', [False, True])
def test_integrated_worktree(repo, dirty):
    m = wt_meta(repo)
    wt = Path(m.worktree)
    (wt / 'nuevo').write_text('cambio')
    git(wt, 'add', '.')
    git(wt, 'commit', '-qm', 'agente')
    git(repo, 'merge', '--no-edit', m.branch)
    if dirty:
        (wt / 'nuevo').write_text('otro')
    result = reconcile.reconcile([m])
    assert bool(result) is not dirty
    assert wt.exists() is dirty
    assert m.status == ('listo-para-revisar' if dirty else 'integrado')


def test_removed_worktree(repo):
    m = wt_meta(repo)
    worktree.remove(repo, Path(m.worktree), m.branch)
    assert reconcile.reconcile([m])[0][1] == 'descartado'


def test_legacy_commit(repo):
    m = meta(repo)
    m.updated_at = (datetime.now() - timedelta(hours=1)).isoformat()
    persist(m)
    assert reconcile.reconcile([m])[0][1] == 'integrado'


@pytest.mark.parametrize('status,expected', [('sin-cambios', 'descartado'), ('running', 'running')])
def test_old_empty(tmp_path, status, expected):
    m = meta(tmp_path, start_head='abc')
    m.project_root = None
    m.status = status
    m.updated_at = (datetime.now() - timedelta(hours=25)).isoformat()
    persist(m)
    reconcile.reconcile([m])
    assert m.status == expected


def test_git_error(repo, monkeypatch):
    m = meta(repo, touched_files=['archivo'])
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired('git', 3)
    monkeypatch.setattr(reconcile, 'git', fail)
    assert reconcile.reconcile([m]) == []
    assert m.status == 'listo-para-revisar'


@pytest.mark.parametrize('same', [True, False])
def test_pending_hook(repo, tmp_path, monkeypatch, capsys, same):
    m = meta(repo, start_head=git(repo, 'rev-parse', 'HEAD'))
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'cwd': str(repo if same else tmp_path)})))
    assert cli.main(['pending', '--hook']) == 0
    output = capsys.readouterr().out
    assert bool(output) is same
    if same:
        assert 'ai-delegate: corridas abiertas en este proyecto' in output
        assert m.run_id in output


def test_bad_hook(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin', io.StringIO('basura'))
    assert cli.main(['pending', '--hook']) == 0
    assert capsys.readouterr().out == ''


def test_hooks(isolated_home):
    writer = install.Writer()
    install.hooks(writer, True)
    path = isolated_home / '.claude/settings.json'
    first = json.loads(path.read_text())
    install.hooks(writer, True)
    assert json.loads(path.read_text()) == first
    entries = first['hooks']['UserPromptSubmit']
    assert [install._hook_args(g['hooks'][0]['command']) for g in entries] == ['claude-status --from-hook', 'pending --hook']
    assert 'async' not in entries[1]['hooks'][0]
    install.hooks(writer, False)
    assert not any(json.loads(path.read_text())['hooks'].values())


def test_pending_review(repo, monkeypatch):
    now = datetime.now()
    m = meta(repo)
    m.updated_at = (now - timedelta(hours=1)).isoformat()
    monkeypatch.setattr('aidelegate.activity.last_activity', lambda *a, **k: None)
    state = build_state([m], None, [], now)['agents'][0]
    assert state['pending']['run_id'] == m.run_id
    assert state['detail'] == f'revisión pendiente desde {(now - timedelta(hours=1)):%H:%M}'


@pytest.fixture
def server(home):
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(server_port=8765, token='test-token')
    def capture(data, status=200):
        handler.response = (status, data)
    handler._json = capture
    return handler


def post(server, m, body, token=True):
    raw = json.dumps(body).encode()
    headers = Message()
    headers['Host'] = '127.0.0.1:8765'
    headers['Content-Type'] = 'application/json'
    headers['Content-Length'] = str(len(raw))
    if token:
        headers['X-AI-Delegate-Token'] = server.server.token
    server.headers = headers
    server.rfile = io.BytesIO(raw)
    server.path = f'/api/run/{m.run_id}/close'
    server.do_POST()
    code, data = server.response
    if code >= 400:
        raise HTTPError(server.path, code, data['error'], None, None)
    return io.StringIO(json.dumps(data))


@pytest.mark.parametrize('case,code', [('token', 403), ('confirm', 400), ('closed', 409), ('worktree', 409)])
def test_close_errors(server, repo, case, code):
    m = wt_meta(repo) if case == 'worktree' else meta(repo)
    if case == 'closed':
        m.status = 'integrado'
        runs.save(m, config.runs_dir() / m.run_id)
    body = {'outcome': 'integrado', 'confirm': True}
    if case == 'confirm':
        body.pop('confirm')
    with pytest.raises(HTTPError) as exc:
        post(server, m, body, case != 'token')
    assert exc.value.code == code


def test_close_discard(server, repo):
    m = wt_meta(repo)
    (Path(m.worktree) / 'sucio').write_text('cambio')
    with post(server, m, {'outcome': 'descartado', 'confirm': True}) as response:
        data = json.load(response)
    assert data['status'] == 'descartado'
    assert data['events'][-1]['type'] == 'cerrada-desde-oficina'
    assert not Path(m.worktree).exists()


@pytest.mark.parametrize('outcome', [None, [], {}, 'otro'])
def test_close_invalid_outcome(server, repo, outcome):
    m = meta(repo)
    with pytest.raises(HTTPError) as exc:
        post(server, m, {'outcome': outcome, 'confirm': True})
    assert exc.value.code == 400


def test_close_integrated_folder(server, repo):
    m = meta(repo)
    (repo / 'manual').write_text('guardado')
    with post(server, m, {'outcome': 'integrado', 'confirm': True}) as response:
        assert json.load(response)['status'] == 'integrado'
    assert (repo / 'manual').read_text() == 'guardado'
    assert stats.read_rows()[-1]['outcome'] == 'integrado'


def test_tidy_and_pending(home, repo, capsys):
    assert cli.main(['tidy']) == 0
    assert capsys.readouterr().out == 'nada que cerrar\n'
    m = meta(repo, start_head=git(repo, 'rev-parse', 'HEAD'))
    assert cli.main(['pending']) == 0
    assert str(repo) in capsys.readouterr().out
    m.project_root = None
    m.status = 'sin-cambios'
    m.updated_at = (datetime.now() - timedelta(hours=25)).isoformat()
    folder = config.runs_dir() / m.run_id
    data = vars(m).copy()
    (folder / 'meta.json').write_text(json.dumps(data))
    assert cli.main(['tidy']) == 0
    assert f'{m.run_id} → descartado: sin cambios, cerrada sola' in capsys.readouterr().out
    assert cli.main(['pending']) == 0
    assert capsys.readouterr().out == 'sin corridas abiertas\n'


def test_reconcile_limit(tmp_path):
    metas = []
    for i in range(31):
        m = RunMeta(f'run-{i}', 'codex', 'write', 'feature', 'repo', str(tmp_path), str(tmp_path), 'tarea',
                    status='sin-cambios')
        runs.create(m)
        m.updated_at = (datetime.now() - timedelta(hours=25)).isoformat()
        persist(m)
        metas.append(m)
    assert len(reconcile.reconcile(metas)) == 30
    assert sum(m.status == 'sin-cambios' for m in metas) == 1


def test_hook_deadline(monkeypatch, capsys, repo):
    import time
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'cwd': str(repo)})))
    def slow(*args, **kwargs):
        assert kwargs['timeout'] <= .75
        raise subprocess.TimeoutExpired('worker', kwargs['timeout'])
    monkeypatch.setattr(cli.subprocess, 'run', slow)
    start = time.monotonic()
    assert cli.main(['pending', '--hook']) == 0
    assert time.monotonic() - start < 1
    assert capsys.readouterr().out == ''


def test_hook_reconciles(repo, monkeypatch, capsys):
    m = meta(repo, start_head=git(repo, 'rev-parse', 'HEAD'))
    (repo / 'nuevo').write_text('cambio')
    runs.track_touched(m)
    runs.save(m, config.runs_dir() / m.run_id)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'manual')
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'cwd': str(repo)})))
    assert cli.main(['pending', '--hook']) == 0
    assert capsys.readouterr().out == ''
    assert runs.load(config.runs_dir() / m.run_id).status == 'integrado'


def test_defaults_for_old_runs(repo):
    m = meta(repo)
    data = vars(m).copy()
    for name in ('start_head', 'start_snapshot', 'touched_files', 'closed_reason'):
        data.pop(name)
    old = RunMeta.from_dict(data)
    assert old.start_head is old.closed_reason is None
    assert old.start_snapshot == {} and old.touched_files == []


def test_tracked_snapshot_deleted_and_untouched(repo):
    for name in ('modificado', 'intacto', 'borrado'):
        (repo / name).write_text('base')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'archivos')
    (repo / 'modificado').write_text('antes')
    (repo / 'intacto').write_text('antes')
    (repo / 'borrado').unlink()
    m = meta(repo)
    runs.capture_start(m)
    assert m.start_snapshot['borrado'] is None
    (repo / 'modificado').write_text('después')
    runs.track_touched(m)
    assert m.touched_files == ['modificado']
    git(repo, 'restore', 'intacto')
    runs.track_touched(m)
    assert m.touched_files == ['intacto', 'modificado']


def test_in_place_cli_capture(home, repo):
    (repo / 'intacto').write_text('antes')
    assert cli.main(['run', '--to', 'codex', '--dir', str(repo), '--no-worktree',
                     '--check', 'none', '--no-review', 'crea hecho.txt']) == 0
    m = runs.recent(1)[0]
    assert m.start_head == git(repo, 'rev-parse', 'HEAD')
    assert list(m.start_snapshot) == ['intacto']
    assert m.touched_files == ['hecho.txt']
    assert m.diffstat == '1 archivos tocados'


def test_hook_five_oldest(repo, monkeypatch, capsys):
    now = datetime.now()
    for i in range(7):
        m = RunMeta(f'run-{i}', 'codex', 'write', 'feature', repo.name, str(repo), str(repo), 'tarea',
                    status='running', project_root=str(repo))
        folder = runs.create(m)
        data = vars(m).copy()
        data['updated_at'] = (now - timedelta(minutes=i)).isoformat()
        (folder / 'meta.json').write_text(json.dumps(data))
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'cwd': str(repo)})))
    assert cli.main(['pending', '--hook']) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 6
    assert [line.split()[1] for line in lines[1:]] == [f'run-{i}' for i in (6, 5, 4, 3, 2)]


def test_background_cache_and_latency(monkeypatch):
    import time
    gate = threading.Event()
    called = []
    def slow():
        called.append(True)
        gate.wait(1)
    monkeypatch.setattr(reconcile, 'reconcile', slow)
    monkeypatch.setattr(reconcile, '_last', {})
    monkeypatch.setattr(reconcile, '_worker', None)
    try:
        start = time.monotonic()
        reconcile.background()
        assert time.monotonic() - start < .3
        reconcile.background()
        assert len(called) == 1
    finally:
        gate.set()
        reconcile._worker.join()
    reconcile.background()
    assert len(called) == 1


def test_unborn_repository_reverted(tmp_path):
    git(tmp_path, 'init', '-q')
    m = meta(tmp_path)
    runs.capture_start(m)
    assert m.start_head is None
    (tmp_path / 'nuevo').write_text('cambio')
    runs.track_touched(m)
    (tmp_path / 'nuevo').unlink()
    persist(m)
    assert reconcile.reconcile([m])[0][1:] == ('descartado', 'cambios revertidos')


def test_other_dirty_files_do_not_prevent_resolution(repo):
    m = meta(repo)
    runs.capture_start(m)
    (repo / 'nuevo').write_text('cambio')
    runs.track_touched(m)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'manual')
    (repo / 'ajeno').write_text('otro cambio')
    persist(m)
    assert reconcile.reconcile([m])[0][1] == 'integrado'
    assert (repo / 'ajeno').read_text() == 'otro cambio'


def test_dirty_submodule_snapshot_and_agent_round(home, repo, tmp_path):
    child = tmp_path / 'child'
    child.mkdir()
    git(child, 'init', '-q')
    (child / 'archivo').write_text('base')
    git(child, 'add', '.')
    git(child, 'commit', '-qm', 'inicio')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(child), 'modulo')
    git(repo, 'commit', '-qam', 'submodulo')
    (repo / 'modulo/archivo').write_text('sucio inicial')
    assert cli.main(['run', '--to', 'codex', '--dir', str(repo), '--no-worktree',
                     '--check', 'none', '--no-review', 'crea hecho.txt']) == 0
    m = runs.recent(1)[0]
    assert m.status == 'listo-para-revisar'
    assert 'modulo' in m.start_snapshot
    assert 'modulo' not in m.touched_files
    (repo / 'modulo/archivo').write_text('otro cambio')
    runs.track_touched(m)
    assert 'modulo' in m.touched_files
    (repo / 'modulo/archivo').write_text('sucio inicial')
    runs.track_touched(m)
    assert 'modulo' in m.touched_files  # se acumula entre rondas


def test_reconcile_uses_latest_touched_files(repo):
    m = meta(repo)
    runs.capture_start(m)
    (repo / 'primero').write_text('cambio')
    runs.track_touched(m)
    persist(m)
    stale = runs.load(config.runs_dir() / m.run_id)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'manual')
    # Terminó otra ronda después de cargar la lista usada por la oficina.
    (repo / 'segundo').write_text('pendiente')
    runs.track_touched(m)
    persist(m)
    assert reconcile.reconcile([stale]) == []
    assert stale.touched_files == ['primero', 'segundo']
    fresh = runs.load(config.runs_dir() / m.run_id)
    assert fresh.status == 'listo-para-revisar'
    assert stats.read_rows() == []


def test_reconcile_latest_status_running(repo):
    m = meta(repo)
    stale = runs.load(config.runs_dir() / m.run_id)
    m.status = 'running'
    persist(m)
    assert reconcile.reconcile([stale]) == []
    assert stale.status == 'running'


def test_reconcile_rotates_across_processes(tmp_path):
    import os
    import sys
    root = Path(__file__).resolve().parents[1]
    for i in range(31):
        m = RunMeta(f'run-{i:02}', 'codex', 'write', 'feature', 'repo', str(tmp_path), str(tmp_path), 'tarea',
                    status='listo-para-revisar' if i < 30 else 'sin-cambios')
        runs.create(m)
        if i == 30:
            m.updated_at = (datetime.now() - timedelta(hours=25)).isoformat()
            persist(m)
    env = dict(os.environ, PYTHONPATH=str(root))
    command = [sys.executable, '-c', 'from aidelegate.reconcile import reconcile; reconcile()']
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert runs.load(config.runs_dir() / 'run-30').status == 'sin-cambios'
    # El cursor sobrevive al proceso: la siguiente llamada no repite el lote.
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert runs.load(config.runs_dir() / 'run-30').status == 'descartado'


@pytest.mark.parametrize('worktree_run', [False, True])
def test_reconcile_serializes_processes(repo, tmp_path, worktree_run):
    import os
    import sys
    if worktree_run:
        m = wt_meta(repo)
        wt = Path(m.worktree)
        (wt / 'nuevo').write_text('cambio')
        git(wt, 'add', '.')
        git(wt, 'commit', '-qm', 'agente')
        git(repo, 'merge', '--no-edit', m.branch)
    else:
        m = meta(repo)
        runs.capture_start(m)
        (repo / 'nuevo').write_text('cambio')
        runs.track_touched(m)
        persist(m)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'manual')
    barrier = tmp_path / 'go'
    ready = [tmp_path / f'ready-{i}' for i in range(2)]
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root))
    script = """
import sys, time
from pathlib import Path
from aidelegate import reconcile, runs
metas = runs.recent(100)
Path(sys.argv[1]).touch()
while not Path(sys.argv[2]).exists():
    time.sleep(.01)
# Ambos cargaron los mismos metadatos antes de comenzar.
reconcile.reconcile(metas)
"""
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path), str(barrier)],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for path in ready]
    try:
        import time
        deadline = time.monotonic() + 5
        while not all(path.exists() for path in ready):
            assert time.monotonic() < deadline
            time.sleep(.01)
        with runs.state_lock():
            barrier.touch()
            for process in processes:
                with pytest.raises(subprocess.TimeoutExpired):
                    process.wait(timeout=.1)
        for process in processes:
            out, err = process.communicate(timeout=5)
            assert process.returncode == 0, err.decode()
        assert runs.load(config.runs_dir() / m.run_id).status == 'integrado'
        assert len(stats.read_rows()) == 1
        events = runs.load(config.runs_dir() / m.run_id).events
        assert sum(e['type'] == 'auto-cerrada' for e in events) == 1
        assert not (config.runs_dir() / m.run_id / 'meta.json.tmp').exists()
        if worktree_run:
            assert not Path(m.worktree).exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def test_reconcile_reloads_updated_at(repo):
    m = meta(repo, start_head=git(repo, 'rev-parse', 'HEAD'))
    m.status = 'sin-cambios'
    m.updated_at = (datetime.now() - timedelta(hours=25)).isoformat()
    persist(m)
    stale = runs.load(config.runs_dir() / m.run_id)
    m.updated_at = datetime.now().isoformat()
    persist(m)
    assert reconcile.reconcile([stale]) == []
    assert stale.updated_at == m.updated_at
    assert stale.status == 'sin-cambios'
