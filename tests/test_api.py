
from fastapi.testclient import TestClient

import server
from app.services.storage import Storage


def test_api_endpoints_and_configuration(tmp_path, monkeypatch):
    storage = Storage(tmp_path)
    monkeypatch.setattr(server, "storage", storage)
    monkeypatch.setattr(server, "ops", server.Operations(server.registry, storage))
    client = TestClient(server.app)

    assert client.get("/api/health").status_code == 200
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["total"] == 6
    assert {"tools", "system", "dependency_summary"} <= dashboard.keys()
    assert client.get("/api/dependencies").json()["summary"]["total"] >= 0
    diagnostics = client.get("/api/diagnostics").json()
    assert {"operating_system", "architecture", "cpu_percent", "memory_used_percent", "tools", "warnings", "errors"} <= diagnostics.keys()
    assert client.post("/api/tools/python/verify").json()["status"] == "Verified"

    payload = {"tools": [], "preferences": {"theme": "dark"}}
    response = client.post("/api/configuration", json=payload)
    assert response.status_code == 200
    assert client.get("/api/configuration").json()["config"]["preferences"]["theme"] == "dark"
    assert client.get("/api/activity").json()["activity"]


def test_unknown_tool_is_rejected():
    client = TestClient(server.app)
    assert client.post("/api/tools/not-a-tool/verify").status_code == 404
