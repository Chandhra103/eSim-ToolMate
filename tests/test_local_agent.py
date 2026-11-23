from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import server
from app.services.storage import Storage
from local_agent import cli as agent_cli
from local_agent import detector
from local_agent import operations as local_operations
from local_agent.cli import scan_is_due
from local_agent.client import _SafeRedirectHandler, validate_backend_url
from local_agent.detector import _version_key
from local_agent.operations import execute_operation


@pytest.fixture
def agent_client(tmp_path, monkeypatch):
    storage = Storage(tmp_path)
    monkeypatch.setattr(server, "storage", storage)
    monkeypatch.setattr(server, "ops", server.Operations(server.registry, storage))
    monkeypatch.setenv("ESIM_PAIRING_SECRET", "test-secret-that-is-at-least-32-characters-long")
    monkeypatch.setenv("ESIM_AGENT_ADMIN_KEY", "different-test-admin-key-that-is-at-least-32")
    return TestClient(server.app, base_url="https://testserver")


def test_version_comparison_is_numeric_and_conservative():
    assert _version_key("3.12.10") > _version_key("3.12.9")
    with pytest.raises(ValueError):
        _version_key("unknown")


def test_initial_scheduled_scan_is_immediately_due():
    assert scan_is_due(None, now=12.0, interval=1800)
    assert not scan_is_due(10.0, now=12.0, interval=1800)
    assert scan_is_due(10.0, now=1810.0, interval=1800)


def test_detector_distinguishes_outdated_missing_and_unknown(monkeypatch):
    fake = Path("/mock/ngspice")
    monkeypatch.setattr(detector, "_find_executable", lambda name: fake if name == "ngspice" else None)
    monkeypatch.setattr(detector, "_read_version", lambda path, args: "0.9" if path == fake else None)
    monkeypatch.setattr(detector, "_installed_from_packages", lambda tool_id: None)
    results = {item["id"]: item for item in detector.scan_tools({"ngspice": "1.0"})}
    assert results["ngspice"]["status"] == "Outdated"
    assert results["ngspice"]["executable_path"] == str(fake)
    assert results["kicad"]["status"] == "Missing"

    monkeypatch.setattr(detector, "_read_version", lambda path, args: None)
    results = {item["id"]: item for item in detector.scan_tools()}
    assert results["ngspice"]["status"] == "Unknown"


def test_backend_url_requires_https_outside_loopback():
    assert validate_backend_url("https://toolmate.example/") == "https://toolmate.example"
    assert validate_backend_url("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(ValueError):
        validate_backend_url("http://toolmate.example")
    with pytest.raises(ValueError):
        validate_backend_url("https://user:password@toolmate.example")


def test_agent_client_rejects_downgrade_and_cross_origin_redirects():
    handler = _SafeRedirectHandler()
    request = urllib.request.Request("https://toolmate.example/api")
    with pytest.raises(urllib.error.URLError, match="unsafe or cross-origin"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://toolmate.example/api")
    with pytest.raises(urllib.error.URLError, match="unsafe or cross-origin"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://attacker.example/collect")
    assert handler.redirect_request(request, None, 302, "Found", {}, "https://toolmate.example/api/v2") is not None


def test_subprocess_environment_keeps_windows_runtime_paths_and_excludes_unrelated_variables(monkeypatch):
    monkeypatch.setenv("PATH", "/system/path")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    env = detector._process_environment()
    assert env["PATH"] == "/system/path"
    assert env["SystemRoot"] == "C:\\Windows"
    assert "GIT_CONFIG_COUNT" not in env
    assert detector._package_manager_environment()["PATH"] == "/usr/sbin:/usr/bin:/sbin:/bin"


def test_operation_command_uses_trusted_package_manager_path_not_path_search(monkeypatch):
    monkeypatch.setattr(local_operations.platform, "system", lambda: "Linux")
    monkeypatch.setattr(local_operations.os, "geteuid", lambda: 0)
    monkeypatch.setattr(local_operations, "_package_and_manager", lambda _tool: ("apt", "git"))
    monkeypatch.setattr(local_operations, "_find_package_manager", lambda name: f"/usr/bin/{name}")
    command = local_operations._command("git", "install")
    assert command == ["/usr/bin/apt-get", "install", "-y", "--", "git"]


def test_remote_plain_http_cannot_pair_or_use_agent_admin_routes(tmp_path, monkeypatch):
    storage = Storage(tmp_path)
    monkeypatch.setattr(server, "storage", storage)
    client = TestClient(server.app, base_url="http://toolmate.example")
    response = client.post("/api/local-agents/pair", json={})
    assert response.status_code == 426
    operation = client.post("/api/tools/git/update", json={"approved": True, "device_id": str(uuid4())})
    assert operation.status_code == 426


def test_pairing_report_auth_admin_list_and_revocation(agent_client):
    client = agent_client
    device_id = str(uuid4())
    secret = "test-secret-that-is-at-least-32-characters-long"
    pairing = client.post("/api/local-agents/pair", json={
        "pairing_secret": secret,
        "device_id": device_id,
        "device_name": "test-device",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test-release",
    })
    assert pairing.status_code == 200
    token = pairing.json()["access_token"]
    assert client.get("/api/local-agents").status_code == 401
    admin_key = "different-test-admin-key-that-is-at-least-32"
    assert client.get("/api/local-agents", headers={"X-ToolMate-Admin-Key": secret}).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    tools = [
        {"id": tool_id, "name": tool_id.title(), "status": "Installed", "version": "1.0", "detection_source": "executable"}
        for tool_id in ("ngspice", "kicad", "ghdl", "ngveri", "python", "git")
    ]
    report = {
        "operating_system": "Linux",
        "os_release": "test-release",
        "architecture": "x86_64",
        "scanned_at": datetime.now(UTC).isoformat(),
        "tools": tools,
    }
    assert client.post(f"/api/local-agents/{device_id}/report", headers=headers, json=report).status_code == 200
    dashboard = client.get("/api/local-agents", headers={"X-ToolMate-Admin-Key": admin_key})
    assert dashboard.status_code == 200
    data = dashboard.json()
    assert data["status"] == "Connected"
    assert data["devices"][0]["report"]["architecture"] == "x86_64"
    assert len(data["devices"][0]["report"]["tools"]) == 6
    assert client.post(f"/api/local-agents/{device_id}/heartbeat", headers=headers, json={}).status_code == 200
    assert client.post(f"/api/local-agents/{device_id}/revoke", headers={"X-ToolMate-Admin-Key": admin_key}).status_code == 200
    assert client.post(f"/api/local-agents/{device_id}/heartbeat", headers=headers, json={}).status_code == 401


def test_pairing_and_report_reject_bad_input(agent_client):
    client = agent_client
    bad_pair = client.post("/api/local-agents/pair", json={
        "pairing_secret": "incorrect-secret-that-is-at-least-32-characters",
        "device_id": str(uuid4()),
        "device_name": "test-device",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test",
    })
    assert bad_pair.status_code == 401
    wrong_os = client.post("/api/local-agents/pair", json={
        "pairing_secret": "test-secret-that-is-at-least-32-characters-long",
        "device_id": str(uuid4()),
        "device_name": "test-device",
        "operating_system": "Darwin",
        "architecture": "x86_64",
        "os_release": "test",
    })
    assert wrong_os.status_code == 422


def test_install_and_update_jobs_require_admin_and_managed_device_approval(agent_client):
    client = agent_client
    device_id = str(uuid4())
    pairing = client.post("/api/local-agents/pair", json={
        "pairing_secret": "test-secret-that-is-at-least-32-characters-long",
        "device_id": device_id,
        "device_name": "paired-laptop",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test-release",
    })
    token = pairing.json()["access_token"]
    admin = {"X-ToolMate-Admin-Key": "different-test-admin-key-that-is-at-least-32"}
    device = {"Authorization": f"Bearer {token}"}

    assert client.post(f"/api/local-agents/{device_id}/operations", json={"tool_id": "git", "operation": "update"}).status_code == 401
    no_target = client.post("/api/tools/git/update", headers=admin, json={"approved": True})
    assert no_target.status_code == 422
    queued = client.post("/api/tools/git/update", headers=admin, json={"approved": True, "device_id": device_id})
    assert queued.status_code == 200
    assert queued.json()["status"] == "Queued"
    assert queued.json()["environment"] == "paired local device"

    job = client.get(f"/api/local-agents/{device_id}/operations/next")
    assert job.status_code == 401
    job = client.get(f"/api/local-agents/{device_id}/operations/next", headers=device).json()["job"]
    assert job["status"] == "awaiting_approval"
    assert job["operation"] == "update"
    assert client.post(f"/api/local-agents/{device_id}/operations/{job['job_id']}/result", headers=device, json={
        "status": "denied", "message": "Operation denied on the managed computer."
    }).status_code == 200
    replay = client.post(f"/api/local-agents/{device_id}/operations/{job['job_id']}/result", headers=device, json={
        "status": "completed", "message": "Replay must not overwrite a result."
    })
    assert replay.status_code == 409
    history = client.get(f"/api/local-agents/{device_id}/operations", headers=admin).json()["operations"]
    assert history[0]["status"] == "denied"


def test_local_operation_queue_rejects_unsupported_and_disconnected_targets(agent_client):
    client = agent_client
    device_id = str(uuid4())
    pairing = client.post("/api/local-agents/pair", json={
        "pairing_secret": "test-secret-that-is-at-least-32-characters-long",
        "device_id": device_id,
        "device_name": "paired-laptop",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test-release",
    })
    admin = {"X-ToolMate-Admin-Key": "different-test-admin-key-that-is-at-least-32"}
    headers = {**admin, "Authorization": f"Bearer {pairing.json()['access_token']}"}
    bad = client.post(f"/api/local-agents/{device_id}/operations", headers=admin, json={"tool_id": "not-a-tool", "operation": "install"})
    assert bad.status_code == 422
    unsupported = client.post(f"/api/local-agents/{device_id}/operations", headers=admin, json={"tool_id": "ngveri", "operation": "install"})
    assert unsupported.status_code == 422
    server.storage.touch_local_agent(device_id)
    with __import__("sqlite3").connect(server.storage.db) as connection:
        connection.execute("UPDATE local_agents SET last_seen=? WHERE device_id=?", ("2000-01-01T00:00:00+00:00", device_id))
    stale = client.post(f"/api/local-agents/{device_id}/operations", headers=admin, json={"tool_id": "git", "operation": "install"})
    assert stale.status_code == 409
    assert client.get(f"/api/local-agents/{device_id}/operations/next", headers=headers).json()["job"] is None


def test_local_cli_denial_never_runs_package_manager(monkeypatch):
    tools = [{"id": tool_id, "name": tool_id.title()} for tool_id in ("ngspice", "kicad", "ghdl", "ngveri", "python", "git")]
    monkeypatch.setattr(agent_cli, "scan_report", lambda *_: {"tools": tools})
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    monkeypatch.setattr(agent_cli, "execute_operation", lambda *_: pytest.fail("denied operation must not execute"))
    result = agent_cli._process_operation(
        {"job_id": str(uuid4()), "tool_id": "git", "operation": "install"},
        object(),
        {"device_id": str(uuid4()), "access_token": "token"},
    )
    assert result["status"] == "denied"


def test_local_cli_requires_and_honors_console_approval(monkeypatch):
    tools = [{"id": tool_id, "name": tool_id.title()} for tool_id in ("ngspice", "kicad", "ghdl", "ngveri", "python", "git")]
    monkeypatch.setattr(agent_cli, "scan_report", lambda *_: {"tools": tools})
    monkeypatch.setattr("builtins.input", lambda *_: "yes")
    calls = []
    monkeypatch.setattr(agent_cli, "execute_operation", lambda tool, operation: calls.append((tool, operation)) or SimpleNamespace(status="success", message="Post-install scan verified 2.0."))

    class Client:
        def report(self, *_):
            return {"success": True}

    result = agent_cli._process_operation(
        {"job_id": str(uuid4()), "tool_id": "git", "operation": "install"},
        Client(),
        {"device_id": str(uuid4()), "access_token": "token"},
    )
    assert calls == [("git", "install")]
    assert result["status"] == "completed"


def test_package_manager_failure_is_not_reported_as_success(monkeypatch):
    reports = iter([
        [{"id": "git", "status": "Installed", "version": "1.0"}],
        [{"id": "git", "status": "Installed", "version": "1.0"}],
    ])
    monkeypatch.setattr("local_agent.operations.scan_tools", lambda: next(reports))
    monkeypatch.setattr("local_agent.operations._package_and_manager", lambda *_: ("apt", "git"))
    monkeypatch.setattr("local_agent.operations._command", lambda *_: ["apt-get", "install", "git"])

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "package manager failed"

    monkeypatch.setattr("local_agent.operations.subprocess.run", lambda *_args, **_kwargs: Failed())
    result = execute_operation("git", "update")
    assert result.status == "failed"
    assert "failed" in result.message


def test_operations_reject_unmapped_and_unverified_removal():
    assert execute_operation("ngveri", "install").status == "unsupported"
    assert execute_operation("git", "uninstall").status == "unsupported"


def test_operation_success_requires_post_install_scan_verification(monkeypatch):
    calls = iter([
        [{"id": "git", "status": "Missing", "version": None}],
        [{"id": "git", "status": "Installed", "version": "2.0"}],
    ])
    monkeypatch.setattr("local_agent.operations.scan_tools", lambda: next(calls))
    monkeypatch.setattr("local_agent.operations._package_and_manager", lambda *_: ("apt", "git"))
    monkeypatch.setattr("local_agent.operations._command", lambda *_: ["apt-get", "install", "git"])

    class Completed:
        returncode = 0
        stdout = "installed"
        stderr = ""

    def run(*args, **kwargs):
        assert kwargs["shell"] is False
        assert args[0] == ["apt-get", "install", "git"]
        return Completed()

    monkeypatch.setattr("local_agent.operations.subprocess.run", run)
    result = execute_operation("git", "install")
    assert result.status == "success"
    assert result.version == "2.0"


def test_result_delivery_discards_expired_jobs_but_retries_network_errors():
    pending = {"job_id": str(uuid4()), "status": "completed", "message": "ok"}
    current = {"device_id": str(uuid4()), "access_token": "token"}

    class ConflictClient:
        def complete_operation(self, *_):
            from local_agent.client import AgentClientError
            raise AgentClientError("Backend returned HTTP 409: expired")

    class NetworkClient:
        def complete_operation(self, *_):
            from local_agent.client import AgentClientError
            raise AgentClientError("Could not securely communicate with the backend: offline")

    assert agent_cli._deliver_pending(ConflictClient(), current, pending)
    from local_agent.client import AgentClientError
    with pytest.raises(AgentClientError, match="offline"):
        agent_cli._deliver_pending(NetworkClient(), current, pending)


def test_expired_result_is_rejected_and_claim_marks_job_expired(agent_client):
    client = agent_client
    device_id = str(uuid4())
    pairing = client.post("/api/local-agents/pair", json={
        "pairing_secret": "test-secret-that-is-at-least-32-characters-long",
        "device_id": device_id,
        "device_name": "paired-laptop",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test-release",
    })
    token = pairing.json()["access_token"]
    admin = {"X-ToolMate-Admin-Key": "different-test-admin-key-that-is-at-least-32"}
    device = {"Authorization": f"Bearer {token}"}
    queued = client.post(f"/api/local-agents/{device_id}/operations", headers=admin, json={"tool_id": "git", "operation": "verify"})
    job_id = queued.json()["job_id"]
    assert client.get(f"/api/local-agents/{device_id}/operations/next", headers=device).json()["job"]
    with __import__("sqlite3").connect(server.storage.db) as connection:
        connection.execute("UPDATE local_agent_operations SET created_at=? WHERE job_id=?", ("2000-01-01T00:00:00+00:00", job_id))
    assert client.post(f"/api/local-agents/{device_id}/operations/{job_id}/result", headers=device, json={"status": "completed", "message": "late"}).status_code == 409
    assert client.get(f"/api/local-agents/{device_id}/operations/next", headers=device).json()["job"] is None
    history = client.get(f"/api/local-agents/{device_id}/operations", headers=admin).json()["operations"]
    assert history[0]["status"] == "expired"


def test_revoking_agent_cancels_pending_operation(agent_client):
    client = agent_client
    device_id = str(uuid4())
    client.post("/api/local-agents/pair", json={
        "pairing_secret": "test-secret-that-is-at-least-32-characters-long",
        "device_id": device_id,
        "device_name": "paired-laptop",
        "operating_system": "Linux",
        "architecture": "x86_64",
        "os_release": "test-release",
    })
    admin = {"X-ToolMate-Admin-Key": "different-test-admin-key-that-is-at-least-32"}
    client.post(f"/api/local-agents/{device_id}/operations", headers=admin, json={"tool_id": "git", "operation": "verify"})
    assert client.post(f"/api/local-agents/{device_id}/revoke", headers=admin).status_code == 200
    history = client.get(f"/api/local-agents/{device_id}/operations", headers=admin).json()["operations"]
    assert history[0]["status"] == "canceled"
