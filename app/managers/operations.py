from __future__ import annotations

import platform

from app.core.security import approved_install_command, run_approved


class Operations:
    def __init__(self, registry, storage): self.registry,self.storage=registry,storage
    def install(self, tool):
        system=platform.system(); cmd=approved_install_command(tool, system)
        if not cmd: return False, "No verified automated installer is available for this platform. Use the official download page."
        try:
            result=run_approved(cmd); ok=result.returncode==0
            msg=(result.stdout or result.stderr or "").strip()[-2000:]
            self.storage.log("installation",tool.name,"success" if ok else "failed",msg, "" if ok else msg)
            return ok, msg or ("Installation completed; rescan to verify." if ok else "Installation failed")
        except Exception as exc:  # noqa: BLE001 - installation boundary must capture subprocess/platform errors
            self.storage.log("installation",tool.name,"failed",str(exc),str(exc)); return False, str(exc)
    def check_dependencies(self):
        result=[]
        for t in self.registry.tools:
            for dep in t.dependencies:
                dep_tool=self.registry.get(dep["id"]); self.registry.detect(dep_tool)
                result.append({"tool":t.name,"dependency":dep_tool.name,"status":"Satisfied" if dep_tool.installed else "Missing","required":dep.get("required",True)})
        self.storage.log("dependency_check",status="success",message=f"Checked {len(result)} relationships")
        return result
