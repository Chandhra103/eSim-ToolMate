from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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


class ConfigurationPayload(BaseModel):
    tools: list[dict] = Field(default_factory=list)
    preferences: dict = Field(default_factory=dict)


def tool_json(tool):
    return {"id": tool.id, "name": tool.name, "description": tool.description, "category": tool.category, "required": tool.required, "installed": tool.installed, "version": tool.version, "executable": tool.executable, "error": tool.error, "website": tool.website, "download": tool.download, "platforms": list(tool.platforms), "dependencies": tool.dependencies}


def dashboard_payload():
    registry.scan()
    dependency_rows = ops.check_dependencies()
    installed = sum(tool.installed for tool in registry.tools)
    updates = sum(tool_json(tool).get("update_status") == "Update Available" for tool in registry.tools)
    return {"total": len(registry.tools), "installed": installed, "missing": len(registry.tools) - installed, "updates": updates, "dependencies": "Healthy" if not any(row["status"] == "Missing" for row in dependency_rows) else "Warnings", "issues": sum(bool(tool.error) for tool in registry.tools), "tools": [tool_json(tool) for tool in registry.tools], "activity": storage.recent(8), "system": collect(registry, dependency_rows), "dependency_summary": dependency_summary(dependency_rows)}


def dependency_summary(rows):
    return {"total": len(rows), "satisfied": sum(row["status"] in ("Satisfied", "No declared dependencies") for row in rows), "missing": sum(row["status"] == "Missing" for row in rows), "outdated": sum(row["status"] == "Outdated" for row in rows), "conflicts": sum(row["status"] == "Conflict" for row in rows), "unknown": sum(row["status"] == "Unknown" for row in rows)}


@app.get("/api/health")
def health(): return {"status": "healthy", "environment": "isolated cloud preview", "version": "1.1.0"}


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
def install(tool_id: str): return tool_operation(tool_id, "install")


@app.post("/api/tools/{tool_id}/uninstall")
def uninstall(tool_id: str): return tool_operation(tool_id, "uninstall")


@app.post("/api/tools/{tool_id}/update")
def update(tool_id: str): return tool_operation(tool_id, "update")


@app.post("/api/tools/{tool_id}/verify")
def verify(tool_id: str):
    try: tool = registry.get(tool_id)
    except StopIteration: raise HTTPException(404, "Unknown tool")
    return {**ops.verify(tool), "tool": tool.name, "environment": "isolated cloud preview"}


def tool_operation(tool_id, operation):
    try: tool = registry.get(tool_id)
    except StopIteration: raise HTTPException(404, "Unknown tool")
    result = getattr(ops, operation)(tool)
    return {**result, "tool": tool.name, "environment": "isolated cloud preview"}


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
