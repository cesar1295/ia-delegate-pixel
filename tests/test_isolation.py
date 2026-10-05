"""Las pruebas deben aislar también probes de versión y perfiles heredados."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from aidelegate import config, detect, install

ROOT = Path(__file__).resolve().parents[1]
FAKES = ROOT / 'tests/fakes'


def test_home_and_profiles_are_temporary(isolated_home):
    assert Path(os.environ['HOME']) == isolated_home
    assert Path(os.environ['CODEX_HOME']) == isolated_home / '.codex'
    assert Path(os.environ['CLAUDE_CONFIG_DIR']) == isolated_home / '.claude'
    for name in ('codex', 'claude', 'agy'):
        assert Path(shutil.which(name)).resolve() == FAKES / f'fake_{name}.py'


def test_inherited_real_profile_overrides_are_replaced(tmp_path):
    user_profile = tmp_path / 'user-profile'
    user_profile.mkdir()
    cache = user_profile / 'models_cache.json'
    cache.write_text('{"sentinel": true}')
    before = (cache.read_bytes(), cache.stat().st_mtime_ns)
    env = dict(os.environ, CODEX_HOME=str(user_profile), CLAUDE_CONFIG_DIR=str(user_profile))
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q',
         'tests/test_isolation.py::test_home_and_profiles_are_temporary'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (cache.read_bytes(), cache.stat().st_mtime_ns) == before


def test_doctor_and_detection_never_launch_user_clis(isolated_home, tmp_path, monkeypatch):
    # Una instalación real detrás del directorio de dobles no debe ejecutarse.
    installed = tmp_path / 'user-bin'
    installed.mkdir()
    marker = tmp_path / 'real-cli-was-launched'
    for name in ('codex', 'claude', 'agy'):
        executable = installed / name
        executable.write_text(f'#!/bin/sh\ntouch "{marker}"\necho real-cli\n')
        executable.chmod(0o755)
    prefix, _, remainder = os.environ['PATH'].partition(os.pathsep)
    monkeypatch.setenv('PATH', os.pathsep.join((prefix, str(installed), remainder)))
    detected = detect.detect_all()
    for name, item in detected.items():
        assert Path(item.path).resolve() == FAKES / f'fake_{name}.py'
        assert item.version is not None
    checks = install.run_doctor(live=False, cfg=config.DEFAULTS)
    versions = [r for r in checks if 'binario y versión' in r['check']]
    assert len(versions) == 3 and all(r['ok'] for r in versions)
    assert not marker.exists()
