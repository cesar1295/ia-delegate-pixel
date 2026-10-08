"""Resolución y persistencia de modelos por tipo de tarea."""

import copy
import tomllib
from pathlib import Path
from types import SimpleNamespace
import pytest

from aidelegate import config, models, runners, ui_server
from aidelegate.ui_server import Handler, _is_allowed_config_key, _validate_change_value


def configured():
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg['agents']['codex'].update(model='general', effort='low', task_models={
        'imagenes': {'model': 'gpt-6-sol', 'effort': 'high'},
        'codigo': {'model': 'gpt-6-luna'},
        'revision': {'effort': 'medium'},
    })
    cfg['agents']['agy'].update(model='agy-general', task_models={'imagenes': {'model': 'agy-image'}})
    return cfg


def test_resolution_per_field_and_agent():
    cfg = configured()
    assert models.category_of('image') == 'imagenes'
    assert models.category_of('unknown') is None
    assert models.resolve('codex', 'image', cfg) == ('gpt-6-sol', 'high')
    assert models.resolve('codex', 'feature', cfg) == ('gpt-6-luna', 'low')
    assert models.resolve('codex', 'review', cfg) == ('general', 'medium')
    assert models.resolve('codex', 'unknown', cfg) == ('general', 'low')
    assert models.resolve('codex', 'image', cfg, 'cli', '') == ('cli', 'high')
    assert models.resolve('codex', 'image', cfg, '', 'ultra') == ('gpt-6-sol', 'ultra')
    assert models.resolve('agy', 'image', cfg) == ('agy-image', '')
    assert models.resolve('claude', 'image', cfg) == ('', '')


def test_runner_argv_uses_category():
    cfg = configured()
    image = runners.get('codex', cfg, kind='image').argv('task', 'read', Path.cwd(), None)
    code = runners.get('codex', cfg, kind='feature').argv('task', 'read', Path.cwd(), None)
    review = runners.get('codex', cfg, kind='review')
    assert image[image.index('-m') + 1] == 'gpt-6-sol'
    assert 'model_reasoning_effort="high"' in image
    assert code[code.index('-m') + 1] == 'gpt-6-luna'
    assert (review.model, review.effort) == ('general', 'medium')
    assert runners.get('agy', cfg, kind='image').model == 'agy-image'


def test_config_keys_validation_and_deletion(tmp_path):
    cfg = configured()
    model = 'agents.codex.task_models.imagenes.model'
    effort = 'agents.codex.task_models.imagenes.effort'
    assert _is_allowed_config_key(model)
    assert not _is_allowed_config_key('agents.codex.task_models.invalida.model')
    assert _validate_change_value(model, 'gpt-6-sol', cfg) is None
    assert _validate_change_value(model, 'bad model', cfg)
    assert _validate_change_value(effort, 'high', cfg) is None
    path = tmp_path / 'config.toml'
    config.write_config_updates({model: 'gpt-6-sol', effort: 'high'}, path)
    assert tomllib.loads(path.read_text())['agents']['codex']['task_models']['imagenes'] == {
        'model': 'gpt-6-sol', 'effort': 'high'}
    config.write_config_updates({model: ''}, path)
    assert tomllib.loads(path.read_text())['agents']['codex']['task_models']['imagenes'] == {'effort': 'high'}
    config.write_config_updates({effort: ''}, path)
    assert '[agents.codex.task_models.imagenes]' not in path.read_text()


def test_post_config_without_socket(monkeypatch, tmp_path):
    path = tmp_path / 'config.toml'
    monkeypatch.setenv('AI_DELEGATE_CONFIG', str(path))
    handler = Handler.__new__(Handler)
    replies = []
    handler._json = lambda data, status=200: replies.append((data, status))
    key = 'agents.codex.task_models.imagenes.model'
    handler._post_config({'changes': {key: 'gpt-6-sol'}})
    assert replies[-1][1] == 200
    assert config.load()['agents']['codex']['task_models']['imagenes']['model'] == 'gpt-6-sol'
    handler._post_config({'changes': {key: ''}})
    assert replies[-1][1] == 200
    assert 'imagenes' not in config.load()['agents']['codex'].get('task_models', {})
    handler._post_config({'changes': {'agents.codex.task_models.bad.model': 'x'}})
    assert replies[-1][1] == 400
    handler._post_config({'changes': {key: 'bad model'}})
    assert replies[-1][1] == 400


@pytest.mark.parametrize('card_run_id', ['live', 'another', None])
def test_state_uses_live_run_model(monkeypatch, card_run_id):
    from datetime import datetime
    from email.message import Message
    from aidelegate.runs import RunMeta
    meta = RunMeta(run_id='live', agent='codex', mode='write', kind='image', repo='repo',
                   source_dir='/tmp', workdir='/tmp', task='imagen', model='gpt-6-sol', effort='high',
                   updated_at=datetime.now().isoformat(), pid=None)
    cfg = configured()
    monkeypatch.setattr(ui_server.reconcile, 'background', lambda: None)
    monkeypatch.setattr(ui_server.config, 'load', lambda: cfg)
    monkeypatch.setattr(ui_server.runs, 'recent', lambda count: [meta])
    monkeypatch.setattr(ui_server.stats, 'read_rows', lambda: [])
    monkeypatch.setattr(ui_server, 'build_state', lambda *args, **kwargs: {'agents': [
        {'name': 'codex', 'run_id': card_run_id}]})
    monkeypatch.setattr(ui_server, '_catalog', lambda *args, **kwargs: {'models': [
        {'id': 'gpt-6-sol', 'label': 'GPT-6-Sol'}], 'default': {'label': 'default', 'effort': 'low'}})
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(server_port=8765)
    handler.headers = Message()
    handler.headers['Host'] = 'localhost:8765'
    handler.path = '/api/state'
    replies = []
    handler._json = lambda data, status=200: replies.append((data, status))
    handler.do_GET()
    assert replies[0][0]['agents'][0]['model_label'] == 'GPT-6-Sol'
    assert replies[0][0]['agents'][0]['effort'] == 'high'


def test_cli_kind_uses_task_model(home, repo):
    from aidelegate.cli import main
    from aidelegate import runs
    config.write_config_updates({
        'agents.codex.model': 'general',
        'agents.codex.task_models.imagenes.model': 'gpt-6-sol',
        'agents.codex.task_models.imagenes.effort': 'high',
        'agents.codex.task_models.codigo.model': 'gpt-6-luna',
    })
    assert main(['--dir', str(repo), '--to', 'codex', '--kind', 'image', '--dry-run', 'imagen']) == 0
    image = runs.load(runs.resolve('last'))
    assert (image.model, image.effort) == ('gpt-6-sol', 'high')
    assert main(['--dir', str(repo), '--to', 'codex', '--kind', 'feature', '--dry-run', 'código']) == 0
    assert runs.load(runs.resolve('last')).model == 'gpt-6-luna'
