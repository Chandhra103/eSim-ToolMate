from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.core.diagnostics import collect
from app.core.registry import ToolRegistry
from app.managers.operations import Operations
from app.services.storage import Storage

ROOT = Path(__file__).parent
registry = ToolRegistry(ROOT / "data" / "tools.json")
storage = Storage()
ops = Operations(registry, storage)
app = FastAPI(title="eSim ToolMate API", version="1.1.0", description="Safe cloud-environment tool management API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def require_tls_for_local_agent(request: Request, call_next):
    path = request.url.path
    sensitive_operation = path.startswith("/api/local-agents") or (
        path.startswith("/api/tools/") and path.rsplit("/", 1)[-1] in {"install", "update", "uninstall"}
    )
    peer = request.client.host if request.client else ""
    try:
        loopback_peer = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback_peer = False
    if sensitive_operation and request.url.scheme != "https" and not loopback_peer:
        return JSONResponse(status_code=426, content={"detail": "HTTPS is required for Local Agent and privileged tool-operation endpoints."})
    return await call_next(request)


class ConfigurationPayload(BaseModel):
    tools: list[dict] = Field(default_factory=list)
    preferences: dict = Field(default_factory=dict)


class OperationApproval(BaseModel):
    approved: bool
    device_id: str | None = Field(default=None, min_length=36, max_length=36)


class PairingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairing_secret: SecretStr = Field(min_length=32, max_length=512)
    device_id: str = Field(min_length=36, max_length=36)
    device_name: str = Field(min_length=1, max_length=120)
    operating_system: Literal["Windows", "Linux"]
    architecture: str = Field(min_length=1, max_length=64)
    os_release: str = Field(min_length=1, max_length=100)


class LocalToolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Literal["ngspice", "kicad", "ghdl", "ngveri", "python", "git"]
    name: str = Field(min_length=1, max_length=80)
    status: Literal["Installed", "Missing", "Outdated", "Unknown"]
    version: str | None = Field(default=None, max_length=128)
    executable_path: str | None = Field(default=None, max_length=2048)
    detection_source: str | None = Field(default=None, max_length=80)


class LocalReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operating_system: Literal["Windows", "Linux"]
    os_release: str = Field(min_length=1, max_length=100)
    architecture: str = Field(min_length=1, max_length=64)
    scanned_at: datetime
    tools: list[LocalToolPayload] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_exact_tool_set(self):
        expected = {"ngspice", "kicad", "ghdl", "ngveri", "python", "git"}
        ids = [tool.id for tool in self.tools]
        if set(ids) != expected or len(ids) != len(expected):
            raise ValueError("A Local Agent report must contain exactly one result for each supported tool.")
        return self


class HeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scanned_at: datetime | None = None


class LocalOperationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: Literal["ngspice", "kicad", "ghdl", "ngveri", "python", "git"]
    operation: Literal["verify", "install", "update", "uninstall"]


class LocalOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "failed", "denied", "unsupported"]
    message: str = Field(min_length=1, max_length=4000)


def _admin_key(provided: str | None) -> None:
    expected = os.environ.get("ESIM_AGENT_ADMIN_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Local Agent dashboard administration is not configured on this server")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "A valid Local Agent administrator key is required")


def _agent_id(device_id: str) -> str:
    try:
        return str(UUID(device_id))
    except ValueError as exc:
        raise HTTPException(404, "Unknown Local Agent device") from exc


def _authenticated_agent(device_id: str, authorization: str | None) -> str:
    device_id = _agent_id(device_id)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "A paired device bearer token is required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token or len(token) > 256:
        raise HTTPException(401, "Invalid device bearer token")
    record = storage.local_agent_credentials(device_id)
    if not record or record["revoked"] or not hmac.compare_digest(record["token_hash"], storage.token_hash(token)):
        raise HTTPException(401, "Invalid or revoked device bearer token")
    return device_id


def tool_json(tool):
    return {"id": tool.id, "name": tool.name, "description": tool.description, "category": tool.category, "required": tool.required, "installed": tool.installed, "version": tool.version, "executable": tool.executable, "error": tool.error, "website": tool.website, "download": tool.download, "platforms": list(tool.platforms), "dependencies": tool.dependencies}


def dashboard_payload():
    registry.scan()
    dependency_rows = ops.check_dependencies()
    installed = sum(tool.installed for tool in registry.tools)
    updates = None
    dependency_states = {row["status"] for row in dependency_rows}
    if not dependency_states or dependency_states == {"No declared dependencies"}:
        dependency_state = "No declared dependencies"
    elif "Missing" in dependency_states:
        dependency_state = "Warnings"
    elif "Unknown" in dependency_states:
        dependency_state = "Unknown"
    else:
        dependency_state = "Healthy"
    return {"total": len(registry.tools), "installed": installed, "missing": len(registry.tools) - installed, "updates": updates, "update_state": "Unknown — no authoritative latest-version feed is configured", "dependencies": dependency_state, "issues": sum(bool(tool.error) for tool in registry.tools), "tools": [tool_json(tool) for tool in registry.tools], "activity": storage.recent(8), "system": collect(registry, dependency_rows), "dependency_summary": dependency_summary(dependency_rows)}


def dependency_summary(rows):
    return {"total": len(rows), "satisfied": sum(row["status"] == "Satisfied" for row in rows), "no_declared": sum(row["status"] == "No declared dependencies" for row in rows), "missing": sum(row["status"] == "Missing" for row in rows), "outdated": sum(row["status"] == "Outdated" for row in rows), "conflicts": sum(row["status"] == "Conflict" for row in rows), "unknown": sum(row["status"] == "Unknown" for row in rows)}


@app.get("/api/health")
def health(): return {"status": "healthy", "environment": "isolated cloud preview", "version": "1.1.0"}


@app.post("/api/local-agents/pair")
def pair_local_agent(payload: PairingPayload):
    expected = os.environ.get("ESIM_PAIRING_SECRET", "")
    supplied = payload.pairing_secret.get_secret_value()
    if len(expected) < 32:
        raise HTTPException(503, "Local Agent pairing is not configured on this server")
    if not hmac.compare_digest(supplied, expected):
        storage.log("local_agent_pairing", status="denied", message="Rejected Local Agent pairing attempt")
        raise HTTPException(401, "Invalid pairing secret")
    device_id = _agent_id(payload.device_id)
    token = secrets.token_urlsafe(48)
    storage.pair_agent(device_id, payload.device_name.strip(), payload.operating_system, payload.architecture, payload.os_release, storage.token_hash(token))
    storage.log("local_agent_pairing", tool="Local Agent", status="success", message="Paired Local Agent device")
    return {"device_id": device_id, "access_token": token, "token_type": "Bearer"}


@app.post("/api/local-agents/{device_id}/report")
def receive_local_agent_report(device_id: str, report: LocalReportPayload, authorization: str | None = Header(default=None)):
    device_id = _authenticated_agent(device_id, authorization)
    report_data = report.model_dump(mode="json")
    now = datetime.now(UTC)
    scanned_at = report.scanned_at
    if scanned_at.tzinfo is None:
        raise HTTPException(422, "scanned_at must include a timezone")
    if scanned_at > now + timedelta(minutes=5):
        raise HTTPException(422, "scanned_at cannot be in the future")
    storage.save_local_agent_report(device_id, report_data)
    counts = {status: sum(tool.status == status for tool in report.tools) for status in ("Installed", "Missing", "Outdated", "Unknown")}
    storage.log("local_agent_scan", tool="Local Agent", status="success", message=f"Local scan received: {counts}")
    return {"success": True, "device_id": device_id, "received_at": now.isoformat()}


@app.post("/api/local-agents/{device_id}/heartbeat")
def local_agent_heartbeat(device_id: str, payload: HeartbeatPayload, authorization: str | None = Header(default=None)):
    device_id = _authenticated_agent(device_id, authorization)
    if payload.scanned_at and payload.scanned_at.tzinfo is None:
        raise HTTPException(422, "scanned_at must include a timezone")
    last_seen = storage.touch_local_agent(device_id)
    return {"success": True, "last_seen": last_seen}


@app.get("/api/local-agents")
def local_agents(x_toolmate_admin_key: str | None = Header(default=None)):
    _admin_key(x_toolmate_admin_key)
    agents = []
    now = datetime.now(UTC)
    for item in storage.list_local_agents():
        last_seen = item.get("last_seen")
        try:
            connected = bool(last_seen and now - datetime.fromisoformat(last_seen) <= timedelta(minutes=3) and not item["revoked"])
        except ValueError:
            connected = False
        item["status"] = "Connected" if connected else "Disconnected"
        agents.append(item)
    return {"status": "Not Installed" if not agents else ("Connected" if any(x["status"] == "Connected" for x in agents) else "Disconnected"), "devices": agents}


def _queue_local_operation(device_id: str, tool_id: str, operation: str) -> dict:
    device_id = _agent_id(device_id)
    if operation == "uninstall":
        raise HTTPException(422, "Uninstallation is disabled until a verified per-package removal policy is configured")
    if tool_id == "ngveri" and operation in {"install", "update"}:
        raise HTTPException(422, "No verified package-manager mapping exists for NgVeri")
    agent = next((item for item in storage.list_local_agents() if item["device_id"] == device_id), None)
    if not agent or agent["revoked"]:
        raise HTTPException(404, "Unknown or revoked Local Agent device")
    try:
        last_seen = datetime.fromisoformat(agent["last_seen"])
    except (TypeError, ValueError):
        raise HTTPException(409, "Local Agent has not sent a recent heartbeat") from None
    if datetime.now(UTC) - last_seen > timedelta(minutes=3):
        raise HTTPException(409, "Local Agent is disconnected; no operation was queued")
    job = storage.create_local_operation(str(uuid4()), device_id, tool_id, operation)
    storage.log("local_operation_queued", tool=tool_id, status="queued", message=f"Queued {operation} for Local Agent {device_id}; local approval is required.")
    return job


@app.post("/api/local-agents/{device_id}/operations")
def request_local_operation(device_id: str, payload: LocalOperationPayload, x_toolmate_admin_key: str | None = Header(default=None)):
    _admin_key(x_toolmate_admin_key)
    try:
        registry.get(payload.tool_id)
    except StopIteration:
        raise HTTPException(404, "Unknown tool") from None
    return _queue_local_operation(device_id, payload.tool_id, payload.operation)


@app.get("/api/local-agents/{device_id}/operations")
def local_operation_history(device_id: str, x_toolmate_admin_key: str | None = Header(default=None)):
    _admin_key(x_toolmate_admin_key)
    device_id = _agent_id(device_id)
    return {"operations": storage.local_operation_history(device_id)}


@app.get("/api/local-agents/{device_id}/operations/next")
def next_local_operation(device_id: str, authorization: str | None = Header(default=None)):
    device_id = _authenticated_agent(device_id, authorization)
    return {"job": storage.claim_local_operation(device_id)}


@app.post("/api/local-agents/{device_id}/operations/{job_id}/result")
def local_operation_result(device_id: str, job_id: str, payload: LocalOperationResult, authorization: str | None = Header(default=None)):
    device_id = _authenticated_agent(device_id, authorization)
    if not storage.finish_local_operation(device_id, job_id, payload.status, payload.message):
        raise HTTPException(409, "Operation job is missing, expired, or already completed")
    storage.log("local_operation_result", tool="Local Agent", status=payload.status, message=f"Job {job_id}: {payload.message[:3500]}")
    return {"success": True, "job_id": job_id, "status": payload.status}


@app.post("/api/local-agents/{device_id}/revoke")
def revoke_local_agent(device_id: str, x_toolmate_admin_key: str | None = Header(default=None)):
    _admin_key(x_toolmate_admin_key)
    device_id = _agent_id(device_id)
    if not storage.revoke_local_agent(device_id):
        raise HTTPException(404, "Unknown Local Agent device")
    storage.log("local_agent_revocation", tool="Local Agent", status="success", message="Revoked Local Agent device token")
    return {"success": True, "device_id": device_id, "status": "Disconnected"}


@app.get("/api/dashboard")
def dashboard(): return dashboard_payload()


@app.get("/api/tools")
def tools(): registry.scan(); return {"tools": [tool_json(tool) for tool in registry.tools]}


@app.post("/api/scan")
def scan():
    registry.scan(); storage.log("system_scan", status="success", message=f"Detected {sum(tool.installed for tool in registry.tools)}/{len(registry.tools)} tools")
    return dashboard_payload()


@app.get("/api/dependencies")
def dependencies():
    rows = ops.check_dependencies()
    return {"relationships": rows, "summary": dependency_summary(rows), "recommendations": [row["recommended_action"] for row in rows if row["status"] in ("Missing", "Outdated", "Conflict")]}


@app.get("/api/diagnostics")
def diagnostics():
    rows = ops.check_dependencies(); return collect(registry, rows)


@app.get("/api/activity")
def activity(query: str = ""): return {"activity": storage.recent(100, query)}


@app.post("/api/tools/{tool_id}/install")
def install(tool_id: str, approval: OperationApproval, x_toolmate_admin_key: str | None = Header(default=None)):
    return tool_operation(tool_id, "install", approval, x_toolmate_admin_key)


@app.post("/api/tools/{tool_id}/uninstall")
def uninstall(tool_id: str, approval: OperationApproval, x_toolmate_admin_key: str | None = Header(default=None)):
    return tool_operation(tool_id, "uninstall", approval, x_toolmate_admin_key)


@app.post("/api/tools/{tool_id}/update")
def update(tool_id: str, approval: OperationApproval, x_toolmate_admin_key: str | None = Header(default=None)):
    return tool_operation(tool_id, "update", approval, x_toolmate_admin_key)


@app.post("/api/tools/{tool_id}/verify")
def verify(tool_id: str):
    try: tool = registry.get(tool_id)
    except StopIteration: raise HTTPException(404, "Unknown tool")
    return {**ops.verify(tool), "tool": tool.name, "environment": "isolated cloud preview"}


def tool_operation(tool_id, operation, approval: OperationApproval, admin_key: str | None = None):
    if not approval.approved:
        raise HTTPException(403, "Explicit user approval is required for this operation")
    _admin_key(admin_key)
    try: tool = registry.get(tool_id)
    except StopIteration: raise HTTPException(404, "Unknown tool")
    if not approval.device_id:
        raise HTTPException(422, "A connected Local Agent device_id is required; cloud-host execution is disabled")
    job = _queue_local_operation(approval.device_id, tool.id, operation)
    return {"success": True, "status": "Queued", "message": "Queued for the paired computer; the Local Agent will request approval on that computer.", "job_id": job["job_id"], "tool": tool.name, "environment": "paired local device"}


@app.get("/api/configuration")
def configuration():
    config = storage.current_config() or ops.config_snapshot()
    return {"config": config, "valid": not ops.validate_config(config), "errors": ops.validate_config(config), "history": storage.config_history()}


@app.post("/api/configuration")
def save_configuration(payload: ConfigurationPayload):
    config = payload.model_dump(); errors = ops.validate_config(config)
    if errors: raise HTTPException(422, {"message": "Configuration validation failed", "errors": errors})
    storage.backup(storage.current_config() or ops.config_snapshot(), storage.root / "backups" / "before-change.json")
    storage.save_config(config, "save")
    return {"success": True, "config": config, "valid": True, "history": storage.config_history()}


@app.post("/api/configuration/restore")
def restore_configuration():
    backup = storage.root / "backups" / "before-change.json"
    if not backup.exists(): raise HTTPException(404, "No configuration backup is available")
    config = storage.restore(backup)
    return {"success": True, "config": config, "valid": not ops.validate_config(config)}


@app.get("/api/report/diagnostics")
def diagnostics_report():
    return diagnostics()


@app.get("/", include_in_schema=False)
def index(): return FileResponse(ROOT / "web" / "index.html")
