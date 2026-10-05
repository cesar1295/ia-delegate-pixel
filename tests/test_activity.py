import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aidelegate import activity


def touch(path, when):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


@pytest.mark.parametrize('name,folder', [('codex', '.codex/generated_images'), ('agy', '.gemini/antigravity-cli/brain')])
def test_images(name, folder, isolated_home, monkeypatch):
    now = datetime.now().astimezone()
    root = isolated_home / folder
    fresh = touch(root / 'nested/new.png', now)
    touch(root / 'old.jpg', now - timedelta(days=2))
    touch(root / 'ignored.txt', now)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('contenido leído'))
    assert activity.recent_images(name, now - timedelta(seconds=90)) == [fresh]
    assert activity.recent_images(name, now.replace(hour=0, minute=0, second=0, microsecond=0)) == [fresh]
    touch(root / 'cached.webp', now)
    assert activity.recent_images(name, now - timedelta(seconds=90)) == [fresh]
    activity._CACHE.clear()
    assert len(activity.recent_images(name, now - timedelta(seconds=90))) == 2


@pytest.mark.parametrize('name,relative', [
    ('codex', '.codex/sessions/{day}/nested/rollout-test.jsonl'),
    ('agy', '.gemini/antigravity-cli/conversations/test'),
    ('claude', '.claude/projects/project/test.jsonl'),
])
def test_sessions_and_custom_home(name, relative, isolated_home):
    now = datetime.now().astimezone()
    profile = isolated_home / 'profile'
    touch(profile / relative.format(day=now.strftime('%Y/%m/%d')), now)
    cfg = {'agents': {name: {'home': str(profile)}}}
    assert abs((activity.last_activity(name, cfg=cfg) - now).total_seconds()) < .01
    assert activity.last_activity(name) is None


def test_image_scan_limit(isolated_home):
    root = isolated_home / '.codex/generated_images'
    now = datetime.now()
    for i in range(2005):
        touch(root / f'{i}.png', now)
    assert len(activity.recent_images('codex', now - timedelta(seconds=1))) == 2000


def test_images_custom_home_and_cache_expiry(isolated_home, monkeypatch):
    now = datetime.now()
    profile = isolated_home / 'other'
    cfg = {'agents': {'agy': {'home': str(profile)}}}
    clock = [10.0]
    monkeypatch.setattr(activity.time, 'monotonic', lambda: clock[0])
    first = touch(profile / '.gemini/antigravity-cli/brain/one.JPEG', now)
    assert activity.recent_images('agy', now - timedelta(seconds=1), cfg=cfg) == [first]
    second = touch(profile / '.gemini/antigravity-cli/brain/two.webp', now)
    assert activity.recent_images('agy', now - timedelta(seconds=1), cfg=cfg) == [first]
    clock[0] += 2
    assert set(activity.recent_images('agy', now - timedelta(seconds=1), cfg=cfg)) == {first, second}
    assert activity.recent_images('agy', now - timedelta(seconds=1)) == []
