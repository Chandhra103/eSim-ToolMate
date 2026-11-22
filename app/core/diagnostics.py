from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

def collect(registry=None) -> dict:
    disk = shutil.disk_usage(Path.home())
    info = {"operating_system": platform.system(), "os_version": platform.version(), "release": platform.release(), "architecture": platform.machine(), "python": platform.python_version(), "home": str(Path.home()), "path_entries": os.environ.get("PATH", "").split(os.pathsep), "package_managers": {x: bool(shutil.which(x)) for x in ("apt","winget","dnf","pacman")}, "disk_free_bytes": disk.free, "disk_total_bytes": disk.total}
    if psutil:
        info["memory_total_bytes"] = psutil.virtual_memory().total
        info["memory_available_bytes"] = psutil.virtual_memory().available
    if registry is not None:
        info["tools"] = [{"id":t.id,"name":t.name,"installed":t.installed,"version":t.version,"executable":t.executable} for t in registry.tools]
    return info
