from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Tool:
    id: str; name: str; description: str; category: str; required: bool
    executables: list[str]; version_args: list[str]; website: str; download: str
    platforms: dict[str, Any] = field(default_factory=dict); dependencies: list[dict] = field(default_factory=list)
    installed: bool = False; executable: str | None = None; version: str | None = None; error: str | None = None

class ToolRegistry:
    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.tools = [Tool(id=x["id"], name=x["name"], description=x["description"], category=x["category"], required=x["required"], executables=x["executables"], version_args=x["version_args"], website=x["website"], download=x["download"], platforms={k:x.get(k,{}) for k in ("linux","windows")}, dependencies=x.get("dependencies",[])) for x in raw]
    def get(self, tool_id: str) -> Tool: return next(t for t in self.tools if t.id == tool_id)
    def scan(self) -> list[Tool]:
        for tool in self.tools: self.detect(tool)
        return self.tools
    def detect(self, tool: Tool) -> Tool:
        tool.installed = False; tool.executable = None; tool.version = None; tool.error = None
        for name in tool.executables:
            path = shutil.which(name)
            if path:
                tool.executable = path; tool.installed = True
                try:
                    result = subprocess.run([path, *tool.version_args], capture_output=True, text=True, timeout=8, check=False)
                    output = (result.stdout or result.stderr).strip().splitlines()
                    tool.version = output[0][:160] if output else "Unknown version"
                    if result.returncode != 0 and not output: tool.error = f"version command exited {result.returncode}"
                except (OSError, subprocess.TimeoutExpired) as exc: tool.error = str(exc)
                break
        return tool
    @property
    def system(self) -> dict[str,str]: return {"os": platform.system(), "release": platform.release(), "architecture": platform.machine()}
