import pytest

from aidelegate import config, routing
from aidelegate.errors import DelegateError, MainSessionTask

CFG = config.DEFAULTS


def test_programming_goes_to_codex_and_simple_tasks_to_agy():
    assert routing.resolve_target("auto", "feature", CFG) == "codex"
    assert routing.resolve_target("auto", "bugfix", CFG) == "codex"
    assert routing.resolve_target("auto", "test", CFG) == "agy"
    assert routing.resolve_target("auto", "docs", CFG) == "agy"


def test_design_is_implemented_by_codex():
    assert routing.resolve_target("auto", "design", CFG) == "codex"


def test_security_stays_with_main_session():
    with pytest.raises(MainSessionTask) as err:
        routing.resolve_target("auto", "security", CFG)
    assert err.value.exit_code == 3


def test_explicit_target_overrides_routing():
    assert routing.resolve_target("agy", "feature", CFG) == "agy"


def test_unknown_kind_lists_options():
    with pytest.raises(DelegateError, match="feature"):
        routing.validate_kind("magia", CFG)


def test_default_mode_by_kind():
    assert routing.default_mode("review", CFG) == "read"
    assert routing.default_mode("feature", CFG) == "write"


def test_candidates_only_fallback_on_auto():
    assert routing.candidates("auto", "codex") == ["codex", "agy"]
    assert routing.candidates("codex", "codex") == ["codex"]


def simulate(quotas):
    """quotas: agente -> True si su cuota está agotada."""
    calls = []

    def attempt(name):
        calls.append(name)
        return {"agent": name, "exhausted": quotas[name]}

    return attempt, calls


def test_fallback_when_primary_quota_is_exhausted():
    attempt, calls = simulate({"codex": True, "agy": False})
    name, _ = routing.run_with_fallback(["codex", "agy"], attempt, lambda r: r["exhausted"])
    assert name == "agy" and calls == ["codex", "agy"]


def test_no_fallback_when_primary_has_quota():
    attempt, calls = simulate({"codex": False, "agy": False})
    name, _ = routing.run_with_fallback(["codex", "agy"], attempt, lambda r: r["exhausted"])
    assert name == "codex" and calls == ["codex"]


def test_all_exhausted_returns_last_attempt():
    attempt, calls = simulate({"codex": True, "agy": True})
    name, result = routing.run_with_fallback(["codex", "agy"], attempt, lambda r: r["exhausted"])
    assert name == "agy" and result["exhausted"] and calls == ["codex", "agy"]


def test_escalation_chain():
    assert routing.next_in_chain("agy", CFG) == "codex"
    assert routing.next_in_chain("codex", CFG) == routing.MAIN
