from __future__ import annotations

import shutil
import subprocess

from packaging.version import InvalidVersion, Version

ALLOWED_MANAGERS = {"apt": ("apt-get",), "winget": ("winget",)}

def compare_versions(installed: str | None, latest: str | None) -> str:
    if not installed or not latest: return "Unknown Version"
    def clean(v):
        for token in v.replace("=", " ").split():
            try: Version(token.lstrip("v")); return token.lstrip("v")
            except InvalidVersion: pass
        return None
    a,b=clean(installed),clean(latest)
    if not a or not b: return "Unknown Version"
    return "Up to Date" if Version(a) >= Version(b) else "Update Available"

def approved_install_command(tool, system: str) -> list[str] | None:
    target = tool.platforms.get(system.lower(), {})
    manager, package = target.get("manager"), target.get("package")
    if not manager or not package or manager not in ALLOWED_MANAGERS: return None
    executable = ALLOWED_MANAGERS[manager][0]
    if not shutil.which(executable): return None
    if manager == "apt": return [executable, "install", "-y", package]
    return [executable, "install", "--id", package, "--exact", "--accept-source-agreements", "--accept-package-agreements"]

def approved_remove_command(tool, system: str) -> list[str] | None:
    target = tool.platforms.get(system.lower(), {})
    manager, package = target.get("manager"), target.get("package")
    if not manager or not package or manager not in ALLOWED_MANAGERS or not shutil.which(ALLOWED_MANAGERS[manager][0]): return None
    if manager == "apt": return ["apt-get", "remove", "-y", package]
    return ["winget", "uninstall", "--id", package, "--exact"]

def approved_update_command(tool, system: str) -> list[str] | None:
    target = tool.platforms.get(system.lower(), {})
    manager, package = target.get("manager"), target.get("package")
    if not manager or not package or manager not in ALLOWED_MANAGERS or not shutil.which(ALLOWED_MANAGERS[manager][0]): return None
    if manager == "apt": return ["apt-get", "install", "--only-upgrade", "-y", package]
    return ["winget", "upgrade", "--id", package, "--exact", "--accept-source-agreements", "--accept-package-agreements"]

def run_approved(command: list[str], timeout=900):
    if not command or command[0] not in {"apt-get","winget"}: raise ValueError("Command is not allowlisted")
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
