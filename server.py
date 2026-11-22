from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.core.diagnostics import collect
from app.core.registry import ToolRegistry
from app.managers.operations import Operations
from app.services.storage import Storage

ROOT = Path(__file__).parent
registry = ToolRegistry(ROOT / "data" / "tools.json")
storage = Storage()
ops = Operations(registry, storage)
app = FastAPI(title="eSim ToolMate API", version="1.0.0", description="Safe cloud-environment tool management API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

@app.get("/api/health")
def health(): return {"status":"healthy", "environment":"isolated cloud preview", "version":"1.0.0"}

@app.get("/api/dashboard")
def dashboard():
    registry.scan(); installed=sum(t.installed for t in registry.tools)
    return {"total":len(registry.tools), "installed":installed, "missing":len(registry.tools)-installed, "updates":0, "dependencies":"OK", "issues":0, "tools":[tool_json(t) for t in registry.tools], "activity":storage.recent(8), "system":collect(registry)}

@app.get("/api/tools")
def tools(): registry.scan(); return {"tools":[tool_json(t) for t in registry.tools]}

@app.post("/api/scan")
def scan():
    registry.scan(); storage.log("system_scan", status="success", message=f"Detected {sum(t.installed for t in registry.tools)}/{len(registry.tools)} tools")
    return dashboard()

@app.get("/api/dependencies")
def dependencies(): return {"relationships":ops.check_dependencies()}

@app.get("/api/diagnostics")
def diagnostics(): registry.scan(); return collect(registry)

@app.get("/api/activity")
def activity(): return {"activity":storage.recent(100)}

@app.post("/api/install/{tool_id}")
def install(tool_id: str):
    try: tool=registry.get(tool_id)
    except StopIteration: raise HTTPException(404, "Unknown tool")
    ok, message=ops.install(tool)
    return {"success":ok,"message":message,"tool":tool.name,"environment":"isolated cloud preview"}

def tool_json(t):
    return {"id":t.id,"name":t.name,"description":t.description,"category":t.category,"required":t.required,"installed":t.installed,"version":t.version,"executable":t.executable,"website":t.website,"download":t.download,"platforms":list(t.platforms)}

@app.get("/", include_in_schema=False)
def index(): return FileResponse(ROOT / "web" / "index.html")
