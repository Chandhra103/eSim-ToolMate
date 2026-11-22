from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def collect(registry=None, dependency_rows=None) -> dict:
    disk = shutil.disk_usage(Path.home())
    info = {
        "environment": "isolated cloud preview",
        "operating_system": platform.system(),
        "os_version": platform.version(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "python_prefix": sys.prefix,
        "home": str(Path.home()),
        "path_entries": os.environ.get("PATH", "").split(os.pathsep),
        "package_managers": {x: bool(shutil.which(x)) for x in ("apt-get", "winget", "dnf", "pacman")},
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "disk_used_percent": round((disk.total - disk.free) / disk.total * 100, 1) if disk.total else 0,
    }
    if psutil:
        memory = psutil.virtual_memory()
        info.update({"cpu_count": psutil.cpu_count(), "cpu_percent": psutil.cpu_percent(interval=0.05), "memory_total_bytes": memory.total, "memory_available_bytes": memory.available, "memory_used_percent": memory.percent})
    else:
        info.update({"cpu_count": None, "cpu_percent": None, "memory_total_bytes": None, "memory_available_bytes": None, "memory_used_percent": None})
    if registry is not None:
        registry.scan()
        info["tools"] = [{"id": t.id, "name": t.name, "installed": t.installed, "version": t.version, "executable": t.executable, "error": t.error} for t in registry.tools]
    dependency_rows = dependency_rows or []
    info["dependency_health"] = {"total": len(dependency_rows), "missing": sum(r.get("status") == "Missing" for r in dependency_rows), "satisfied": sum(r.get("status") == "Satisfied" for r in dependency_rows)}
    info["warnings"] = []
    info["errors"] = []
    if not info["package_managers"].get("apt-get") and platform.system() == "Linux": info["warnings"].append("No supported Linux package manager is available")
    if info.get("memory_used_percent") and info["memory_used_percent"] > 90: info["warnings"].append("Memory usage is above 90%")
    if info["disk_used_percent"] > 90: info["warnings"].append("Disk usage is above 90%")
    if registry is not None:
        info["errors"].extend(f"{t.name}: {t.error}" for t in registry.tools if t.error)
    return info
