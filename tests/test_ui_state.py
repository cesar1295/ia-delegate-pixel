import os
from datetime import datetime, timedelta

import pytest

from aidelegate import config
from aidelegate.runs import RunMeta
from aidelegate.ui_state import build_state

NOW = datetime(2026, 10, 4, 14)


def meta(**kwargs):
    values = dict(run_id="20261004-140000-repo-codex", agent="codex", kind="feature", mode="write",
                  repo="repo", source_dir="/tmp", workdir="/tmp", task="tarea\nsegunda línea",
                  created_at=NOW.isoformat(), updated_at=NOW.isoformat(), pid=os.getpid())
    values.update(kwargs)
    return RunMeta(**values)


@pytest.mark.parametrize("agent", ["codex", "agy"])
@pytest.mark.parametrize("changes,state,detail", [
    ({"phase": "checks"}, "checks", "corriendo checks"),
    ({"phase_label": "corrección 2", "fix_rounds": 1}, "fixing", "corrigiendo (2/3)"),
    ({}, "working", "tarea"),
    ({"status": "listo-para-revisar"}, "review", "listo, esperando revisión"),
    ({"status": "cuota-agotada"}, "quota", "sin cuota"),
    ({"status": "integrado"}, "celebrate", "¡integrado!"),
    *[({"status": status}, "failed", f"falló: {status}")
      for status in ("checks-fallidos", "error", "timeout", "bloqueado", "interrumpido")],
    ({"pid": 999999999}, "failed", "falló: interrumpido"),
    ({"status": "ok", "updated_at": (NOW - timedelta(minutes=16)).isoformat()}, "sleep", ""),
    ({"status": "ok"}, "idle", ""),
])
def test_agent(agent, changes, state, detail):
    result = build_state([meta(agent=agent, **changes)], None, [], NOW)
    assert next(a for a in result["agents"] if a["name"] == agent)["state"] == state
    assert next(a for a in result["agents"] if a["name"] == agent)["detail"] == detail
    if changes.get("pid") == 999999999:
        assert result["runs"][0]["status"] == "interrumpido"


@pytest.mark.parametrize("metas,activity,state,detail", [
    ([meta(status="escalado-a-main")], None, "fixing", "terminando: tarea"),
    ([], {"state": "working", "detail": "Read", "ts": NOW.isoformat()}, "working", "trabajando (Read)"),
    ([], {"state": "working", "ts": NOW.isoformat()}, "working", "trabajando"),
    ([meta(status="listo-para-revisar")], None, "reviewing", "revisando repo-codex"),
    ([], {"state": "waiting", "ts": NOW.isoformat()}, "waiting", f"esperando a {config.DEFAULTS['user_name']}"),
    ([], None, "sleep", ""),
    ([], {"state": "working", "ts": (NOW - timedelta(minutes=16)).isoformat()}, "sleep", ""),
    ([], {"state": "idle", "ts": NOW.isoformat()}, "idle", ""),
])
def test_claude(metas, activity, state, detail):
    result = build_state(metas, activity, [], NOW)["agents"][0]
    assert (result["state"], result["detail"]) == (state, detail)


def test_old_meta_and_no_mutation():
    old = meta(pid=None)
    data = vars(old).copy()
    for field in ("pid", "phase", "phase_label", "updated_at"):
        data.pop(field)
    loaded = RunMeta.from_dict(data)
    assert loaded.updated_at == loaded.created_at
    assert build_state([loaded], None, [], NOW)["agents"][1]["state"] == "working"
    loaded.updated_at = (NOW - timedelta(minutes=31)).isoformat()
    result = build_state([loaded], None, [], NOW)
    assert result["runs"][0]["status"] == "interrumpido"
    assert loaded.status == "running"


def test_priority_and_counts():
    ready = meta(status="listo-para-revisar")
    working = meta(run_id="new", created_at=(NOW + timedelta(seconds=1)).isoformat(), phase="checks",
                   phase_label="corrección 1")
    ledger = [{"agent": "codex", "kind": "feature", "outcome": "integrado", "review_rounds": 0,
               "ts": NOW.isoformat()}]
    result = build_state([ready, working], {"state": "waiting", "ts": NOW.isoformat()}, ledger, NOW)
    assert result["agents"][1]["state"] == "checks"
    assert result["agents"][0]["state"] == "reviewing"
    assert result["counts"] == {"running": 1, "review": 1, "merged_today": 1}
    assert result["stats"][0]["primera_pct"] == 100


def test_escalated_timing_and_pending():
    old_run = meta(status="escalado-a-main", task="tarea vieja escalada",
                   updated_at=(NOW - timedelta(hours=2)).isoformat())
    res_old = build_state([old_run], None, [], NOW)["agents"][0]
    assert res_old["state"] != "fixing"
    assert res_old["detail"] == "tarea escalada pendiente desde 12:00"
    assert res_old["pending"] == {
        "run_id": old_run.run_id,
        "task": "tarea vieja escalada",
        "since": (NOW - timedelta(hours=2)).isoformat(),
    }

    recent_run = meta(status="escalado-a-main", task="tarea reciente escalada",
                      updated_at=(NOW - timedelta(minutes=5)).isoformat())
    res_recent = build_state([recent_run], None, [], NOW)["agents"][0]
    assert res_recent["state"] == "fixing"
    assert res_recent["detail"] == "terminando: tarea reciente escalada"
    assert res_recent["pending"] == {
        "run_id": recent_run.run_id,
        "task": "tarea reciente escalada",
        "since": (NOW - timedelta(minutes=5)).isoformat(),
    }


@pytest.mark.parametrize("source", ["hook", "activity"])
@pytest.mark.parametrize("minutes,fixing", [(9, True), (10, False)])
def test_old_escalation_master_activity(monkeypatch, source, minutes, fixing):
    from aidelegate import activity
    stamp = NOW - timedelta(minutes=minutes)
    monkeypatch.setattr(activity, "last_activity", lambda name: stamp if source == "activity" else None)
    hook = {"state": "working", "ts": stamp.isoformat()} if source == "hook" else None
    old = meta(status="escalado-a-main", updated_at=(NOW - timedelta(hours=2)).isoformat())
    result = build_state([old], hook, [], NOW)["agents"][0]
    assert (result["state"] == "fixing") is fixing
    assert result["pending"]["run_id"] == old.run_id


def test_pending_oldest_and_escalation_boundary():
    old = meta(run_id="old", status="escalado-a-main", task="x" * 80,
               updated_at=(NOW - timedelta(hours=2)).isoformat())
    newer = meta(run_id="new", status="escalado-a-main",
                 updated_at=(NOW - timedelta(minutes=30)).isoformat())
    for ordered in ([old, newer], [newer, old]):
        result = build_state(ordered, None, [], NOW)["agents"][0]
        assert result["state"] == "sleep"
        assert result["pending"]["run_id"] == "old"
        assert len(result["pending"]["task"]) == 60
    newer.updated_at = (NOW - timedelta(minutes=5)).isoformat()
    result = build_state([old, newer], None, [], NOW)["agents"][0]
    assert result["state"] == "fixing"
    assert result["run_id"] == "new"
    assert result["pending"]["run_id"] == "old"


@pytest.mark.parametrize('name,folder', [('codex', '.codex/generated_images'), ('agy', '.gemini/antigravity-cli/brain')])
@pytest.mark.parametrize('live,phase,expected', [(False, None, 'drawing'), (True, 'agente', 'drawing'), (True, 'checks', 'checks')])
def test_direct_images(name, folder, live, phase, expected, isolated_home):
    from tests.test_activity import touch
    touch(isolated_home / folder / 'new.png', NOW - timedelta(seconds=5))
    touch(isolated_home / folder / 'earlier.jpg', NOW - timedelta(hours=1))
    touch(isolated_home / folder / 'yesterday.webp', NOW - timedelta(days=1))
    runs = [meta(agent=name, phase=phase, updated_at=(NOW - timedelta(seconds=10)).isoformat())] if live else []
    result = next(a for a in build_state(runs, None, [], NOW)['agents'] if a['name'] == name)
    assert result['state'] == expected
    assert result['images_today'] == 2
    if expected == 'drawing':
        assert result['detail'] == 'generando imágenes'


@pytest.mark.parametrize('name', ['codex', 'agy'])
def test_direct_session(name, monkeypatch):
    from aidelegate import activity
    monkeypatch.setattr(activity, 'last_activity', lambda n: NOW - timedelta(seconds=2) if n == name else None)
    result = next(a for a in build_state([], None, [], NOW)['agents'] if a['name'] == name)
    assert (result['state'], result['detail']) == ('working', 'trabajando fuera de ai-delegate')


def test_round_start_survives_progress(isolated_home):
    from tests.test_activity import touch
    touch(isolated_home / '.codex/generated_images/new.png', NOW - timedelta(seconds=5))
    run = meta(phase='agente', phase_started_at=(NOW - timedelta(seconds=10)).isoformat())
    result = build_state([run], None, [], NOW)['agents'][1]
    assert result['state'] == 'drawing'
