from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from app.core.security import approved_install_command, approved_remove_command, approved_update_command, run_approved


class Operations:
    def __init__(self, registry, storage):
        self.registry, self.storage = registry, storage

    def _run(self, operation, tool, command):
        if not command:
            message = "No verified automated workflow is available for this platform. Use the official source."
            self.storage.log(operation, tool.name, "unsupported", message)
            return {"success": False, "status": "Unsupported", "message": message, "verified": False, "command": None}
        try:
            result = run_approved(command)
            output = (result.stdout or result.stderr or "").strip()[-4000:]
            self.registry.detect(tool)
            verified = tool.installed if operation != "uninstallation" else not tool.installed
            success = result.returncode == 0 and verified
            message = output or ("Operation completed and verified." if success else "Operation finished but verification did not pass.")
            status = "success" if success else "failed"
            self.storage.log(operation, tool.name, status, message, "" if success else message)
            return {"success": success, "status": "Verified" if success else "Failed", "message": message, "verified": verified, "command": command}
        except (OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
            self.storage.log(operation, tool.name, "failed", str(exc), str(exc))
            return {"success": False, "status": "Failed", "message": str(exc), "verified": False, "command": command}

    def install(self, tool):
        return self._run("installation", tool, approved_install_command(tool, platform.system()))

    def uninstall(self, tool):
        return self._run("uninstallation", tool, approved_remove_command(tool, platform.system()))

    def update(self, tool):
        return self._run("update", tool, approved_update_command(tool, platform.system()))

    def verify(self, tool):
        self.registry.detect(tool)
        ok = bool(tool.installed and tool.version)
        message = f"{tool.name}: {tool.version or 'executable/version not detected'}"
        self.storage.log("verification", tool.name, "success" if ok else "failed", message)
        return {"success": ok, "status": "Verified" if ok else "Failed", "message": message, "version": tool.version, "executable": tool.executable}

    def check_dependencies(self):
        self.registry.scan()
        result = []
        for tool in self.registry.tools:
            if not tool.dependencies:
                result.append({"tool": tool.name, "dependency": "Declared requirements", "status": "No declared dependencies", "required": False, "recommended_action": "No action required"})
                continue
            for dependency in tool.dependencies:
                dep_tool = self.registry.get(dependency["id"])
                self.registry.detect(dep_tool)
                status = "Satisfied" if dep_tool.installed else "Missing"
                result.append({"tool": tool.name, "dependency": dep_tool.name, "status": status, "required": dependency.get("required", True), "version": dep_tool.version, "recommended_action": "Verify installation" if status == "Satisfied" else "Install the dependency"})
        missing = sum(x["status"] == "Missing" for x in result)
        self.storage.log("dependency_check", status="success" if not missing else "warning", message=f"Checked {len(result)} dependency entries; {missing} missing")
        return result

    def config_snapshot(self):
        self.registry.scan()
        return {"environment": "isolated cloud preview", "tools": [{"id": t.id, "executable": t.executable, "version": t.version, "valid": bool(t.installed and t.executable)} for t in self.registry.tools]}

    def validate_config(self, config):
        errors = []
        if not isinstance(config, dict): return ["Configuration must be an object"]
        for item in config.get("tools", []):
            path = item.get("executable")
            if path and not Path(path).exists(): errors.append(f"{item.get('id', 'tool')}: executable path does not exist")
        return errors
