import os
from datetime import datetime, timedelta

import pytest

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
    assert result["agents"][agent]["state"] == state
    assert result["agents"][agent]["detail"] == detail
    if changes.get("pid") == 999999999:
        assert result["runs"][0]["status"] == "interrumpido"


@pytest.mark.parametrize("metas,activity,state,detail", [
    ([meta(status="escalado-a-main")], None, "fixing", "terminando: tarea"),
    ([], {"state": "working", "detail": "Read", "ts": NOW.isoformat()}, "working", "trabajando (Read)"),
    ([], {"state": "working", "ts": NOW.isoformat()}, "working", "trabajando"),
    ([meta(status="listo-para-revisar")], None, "reviewing", "revisando repo-codex"),
    ([], {"state": "waiting", "ts": NOW.isoformat()}, "waiting", "esperando a Alex"),
    ([], None, "sleep", ""),
    ([], {"state": "working", "ts": (NOW - timedelta(minutes=16)).isoformat()}, "sleep", ""),
    ([], {"state": "idle", "ts": NOW.isoformat()}, "idle", ""),
])
def test_claude(metas, activity, state, detail):
    result = build_state(metas, activity, [], NOW)["agents"]["claude"]
    assert (result["state"], result["detail"]) == (state, detail)


def test_old_meta_and_no_mutation():
    old = meta(pid=None)
    data = vars(old).copy()
    for field in ("pid", "phase", "phase_label", "updated_at"):
        data.pop(field)
    loaded = RunMeta.from_dict(data)
    assert loaded.updated_at == loaded.created_at
    assert build_state([loaded], None, [], NOW)["agents"]["codex"]["state"] == "working"
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
    assert result["agents"]["codex"]["state"] == "checks"
    assert result["agents"]["claude"]["state"] == "reviewing"
    assert result["counts"] == {"running": 1, "review": 1, "merged_today": 1}
    assert result["stats"][0]["primera_pct"] == 100
