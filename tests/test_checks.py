import json

from aidelegate import checks, config


def test_detects_npm_scripts_and_skips_placeholder_test(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "lint": "eslint .", "test": 'echo "Error: no test specified" && exit 1'}}))
    assert checks.detect(tmp_path) == "npm run lint"


def test_uses_lockfile_manager(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert checks.detect(tmp_path) == "pnpm run test"


def test_detects_pytest(tmp_path):
    (tmp_path / "tests").mkdir()
    assert checks.detect(tmp_path) == "python3 -m pytest -q"


def test_static_site_has_no_checks(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hola</h1>")
    assert checks.detect(tmp_path) is None


def test_resolve_priority(tmp_path):
    cfg = {**config.DEFAULTS, "projects": {str(tmp_path): {"check": "make test"}}}
    assert checks.resolve("none", tmp_path, tmp_path, cfg) is None
    assert checks.resolve("npm test", tmp_path, tmp_path, cfg) == "npm test"
    assert checks.resolve("auto", tmp_path, tmp_path, cfg) == "make test"


def test_run_reports_failure_and_tail(tmp_path):
    result = checks.run("echo malo; exit 3", tmp_path, 10)
    assert not result.ok and result.exit_code == 3 and "malo" in result.output
