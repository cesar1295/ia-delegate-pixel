import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aidelegate import runs
from aidelegate.runs import RunMeta
from aidelegate.ui_server import create_server


@pytest.fixture
def server(home):
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_state(server):
    with urlopen(server + "/api/state") as response:
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        assert response.headers["Cache-Control"] == "no-store"
        data = json.load(response)
        assert [a["name"] for a in data["agents"]] == ["claude", "codex", "agy"]
        assert data["events"] == []


@pytest.mark.parametrize("path", ["/static/../cli.py", "/static/%2e%2e/cli.py", "/static//etc/passwd", "/api/run/no-existe"])
def test_missing(server, path):
    with pytest.raises(HTTPError) as exc:
        urlopen(server + path)
    assert exc.value.code == 404
    assert "error" in json.load(exc.value)


def test_run_detail(server):
    meta = RunMeta("test-run", "codex", "write", "feature", "repo", "/tmp", "/tmp", "tarea",
                   history=[{"label": "tarea", "usage": {"secret": 1}}], feedback=["comentario"])
    folder = runs.create(meta)
    (folder / "last.md").write_text("\n".join(str(i) for i in range(50)))
    with urlopen(server + "/api/run/test-run") as response:
        data = json.load(response)
    assert "meta" not in data
    assert data["run_id"] == meta.run_id
    assert data["agent"] == meta.agent
    assert data["kind"] == meta.kind
    assert data["feedback"] == meta.feedback
    assert data["events"] == [] and data["subagents"] == []
    assert "usage" not in data["history"][0]
    assert len(data["summary"].splitlines()) == 40
    assert len(data["commands"]) == 4


@pytest.mark.parametrize("path", ["/api/state", "/api/run/no-existe", "/", "/static/archivo.js"])
def test_forbidden_host(server, path):
    request = Request(server + path, headers={"Host": "evil.example"})
    with pytest.raises(HTTPError) as exc:
        urlopen(request)
    assert exc.value.code == 403
    assert json.load(exc.value) == {"error": "Host no permitido"}


def test_localhost_host(server):
    port = server.rsplit(":", 1)[1]
    request = Request(server + "/api/state", headers={"Host": f"localhost:{port}"})
    with urlopen(request) as response:
        assert response.status == 200
        assert "agents" in json.load(response)
