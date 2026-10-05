"""Flujo completo con CLIs falsos: delegar → checks → feedback → merge/discard."""

import json
import subprocess

from aidelegate import config, runs
from aidelegate.cli import main


def run(*argv):
    return main(list(argv))


def last_meta():
    return runs.load(runs.resolve("last"))


def test_dry_run_writes_prompt_and_calls_nothing(home, repo, capsys):
    assert run("--dir", str(repo), "--dry-run", "agrega un endpoint") == 0
    meta = last_meta()
    assert meta.status == "dry-run" and meta.agent == "codex"
    assert "agrega un endpoint" in (runs.resolve("last") / "prompt.md").read_text()
    assert not (runs.resolve("last") / "events.jsonl").exists()
    assert "[dry-run]" in capsys.readouterr().out


def test_secret_in_task_blocks_and_records_meta(home, repo, capsys):
    assert run("--dir", str(repo), "usa GITHUB_TOKEN=abc123 para el deploy") == 2
    meta = last_meta()
    assert meta.status == "bloqueado" and "abc123" not in json.dumps(meta.__dict__)
    assert "abc123" not in capsys.readouterr().err


def test_design_without_spec_is_refused_before_creating_a_run(home, repo, capsys):
    assert run("--dir", str(repo), "--kind", "design", "rediseña el hero") == 2
    assert "--design-spec" in capsys.readouterr().err
    assert runs.recent(5) == []


def test_design_with_spec_is_delegated_with_strict_rules(home, repo, tmp_path):
    design = tmp_path / "hero.md"
    design.write_text("Hero: fondo #0F0F10, título 48px Clash Display 600")
    assert run("--dir", str(repo), "--kind", "design", "--design-spec", str(design),
               "--check", "none", "implementa el hero") == 0
    meta = last_meta()
    sent = (runs.resolve("last") / "prompt.md").read_text()
    assert meta.agent == "codex" and meta.design_spec_path == str(design)
    assert "título 48px Clash Display 600" in sent and "EXACTAMENTE" in sent


def test_security_is_not_delegated(home, repo, capsys):
    assert run("--dir", str(repo), "--kind", "security", "revisa la auth") == 3
    assert "sesión principal" in capsys.readouterr().err


def test_print_env_shows_names_only(home, repo, capsys, monkeypatch):
    monkeypatch.setenv("LANG", "es_MX.UTF-8")
    assert run("--print-env", "x") == 0
    out = capsys.readouterr().out
    assert "LANG" in out and "es_MX" not in out


def test_write_run_uses_worktree_and_leaves_main_copy_untouched(home, repo, capsys):
    check = "mkdir -p __pycache__ && touch __pycache__/x.pyc && test -f hecho.txt"
    code = run("--dir", str(repo), "--check", check, "crea hecho.txt")
    meta = last_meta()
    assert code == 0 and meta.status == "listo-para-revisar"
    assert meta.diffstat.startswith("1 file changed")  # el caché de los checks no cuenta
    assert meta.thread_id == "codex-thread-1" and meta.branch.startswith("ai/")
    assert not (repo / "hecho.txt").exists()
    out = capsys.readouterr().out
    assert "codex | write | mi-repo | listo-para-revisar" in out and "1 file changed" in out


def test_failed_checks_go_back_to_agent_automatically(home, repo):
    assert run("--dir", str(repo), "--check", "test -f hecho.txt", "FALLA_PRIMERO crea hecho.txt") == 0
    meta = last_meta()
    assert meta.fix_rounds == 1 and meta.last_check["ok"]
    assert [h["label"] for h in meta.history] == ["tarea", "corrección 1", "pre-revisión"]


def test_checks_still_failing_after_limit(home, repo):
    assert run("--dir", str(repo), "--check", "false", "--max-fix-rounds", "1", "tarea") == 1
    meta = last_meta()
    assert meta.status == "checks-fallidos" and meta.fix_rounds == 1


def test_long_summary_is_trimmed(home, repo, capsys):
    run("--dir", str(repo), "--check", "none", "LARGO")
    out = capsys.readouterr().out
    assert "línea 14" in out and "línea 15" not in out and "recortado a 15 líneas" in out


def test_feedback_then_merge_records_stats(home, repo, capsys):
    run("--dir", str(repo), "--check", "none", "crea hecho.txt")
    rid = last_meta().run_id
    assert run("feedback", rid, "agrega un salto de línea") == 0
    assert last_meta().review_rounds == 1
    assert run("merge", rid) == 0
    assert (repo / "hecho.txt").exists()
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True).stdout
    assert "ai-delegate(codex)" in log
    run("stats")
    assert "codex" in capsys.readouterr().out


def test_review_round_limit_suggests_escalation(home, repo, capsys):
    cfg_path = config.config_path()
    cfg_path.write_text(cfg_path.read_text() + "escalate_after = 3\n")
    run("--dir", str(repo), "--check", "none", "crea hecho.txt")
    rid = last_meta().run_id
    run("feedback", rid, "uno")
    run("feedback", rid, "dos")
    assert run("feedback", rid, "tres") == 2
    assert "escalate" in capsys.readouterr().err


def test_escalate_from_agy_to_codex_then_main(home, repo, capsys):
    run("--dir", str(repo), "--check", "none", "--kind", "test", "agrega tests")
    meta = last_meta()
    assert meta.agent == "agy"
    assert run("escalate", meta.run_id) == 0
    assert last_meta().agent == "codex" and last_meta().escalated_from == ["agy"]
    assert run("escalate", meta.run_id) == 3
    assert last_meta().status == "escalado-a-main"


def test_discard_removes_worktree_and_branch(home, repo):
    run("--dir", str(repo), "--check", "none", "crea hecho.txt")
    meta = last_meta()
    assert run("discard", meta.run_id) == 0
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert meta.branch not in branches
    assert not config.worktrees_dir().joinpath(meta.run_id).exists()


def test_auto_falls_back_to_agy_when_codex_quota_is_exhausted(home, repo, capsys):
    assert run("--dir", str(repo), "--check", "none", "CUOTA crea hecho.txt") == 0
    meta = last_meta()
    assert meta.agent == "agy" and meta.fallback_from == "codex"
    assert "agotó su cuota" in capsys.readouterr().out


def test_explicit_target_does_not_fall_back(home, repo):
    assert run("--to", "codex", "--dir", str(repo), "--check", "none", "CUOTA") == 1
    assert last_meta().status == "cuota-agotada"


def test_read_mode_runs_in_place_without_worktree(home, repo):
    assert run("--dir", str(repo), "--kind", "review", "revisa el repo") == 0
    meta = last_meta()
    assert meta.mode == "read" and meta.worktree is None and meta.status == "ok"


def test_merge_closes_in_place_write_run(home, repo, capsys):
    assert run("--dir", str(repo), "--no-worktree", "--check", "none", "crea hecho.txt") == 0
    meta = last_meta()
    assert meta.worktree is None and meta.status == "listo-para-revisar"
    assert run("merge", meta.run_id) == 0
    assert last_meta().status == "integrado"
    assert "no había worktree" in capsys.readouterr().out
