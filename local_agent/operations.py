from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass

from local_agent.detector import TOOL_SPECS, _find_package_manager, _package_manager_environment, scan_tools

SUPPORTED_TOOLS = frozenset(TOOL_SPECS)
# Removal is intentionally disabled until a per-package uninstall mapping is verified.
UNINSTALL_SUPPORTED: frozenset[str] = frozenset()
MAX_OUTPUT = 4000
OPERATION_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class OperationResult:
    status: str
    message: str
    version: str | None = None


def _package_and_manager(tool_id: str) -> tuple[str, str] | None:
    spec = TOOL_SPECS.get(tool_id)
    if not spec:
        return None
    if platform.system() == "Windows":
        package = spec["packages"].get("winget")
        return ("winget", package) if package else None
    if platform.system() == "Linux":
        package = spec["packages"].get("debian")
        return ("apt", package) if package else None
    return None


def _command(tool_id: str, operation: str) -> list[str] | None:
    if operation not in {"install", "update", "uninstall"}:
        return None
    if operation == "uninstall" and tool_id not in UNINSTALL_SUPPORTED:
        return None
    mapping = _package_and_manager(tool_id)
    if not mapping:
        return None
    manager, package = mapping
    if not package or not isinstance(package, str):
        return None
    if manager == "winget":
        executable = _find_package_manager("winget")
        if not executable:
            return None
        if operation == "install":
            return [executable, "install", "--id", package, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"]
        if operation == "update":
            return [executable, "upgrade", "--id", package, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"]
        return [executable, "uninstall", "--id", package, "--exact", "--disable-interactivity"]
    executable = _find_package_manager("apt-get")
    if not executable:
        return None
    if os.geteuid() != 0:
        pkexec = _find_package_manager("pkexec")
        if not pkexec:
            return None
        prefix = [pkexec, executable]
    else:
        prefix = [executable]
    if operation == "install":
        return [*prefix, "install", "-y", "--", package]
    if operation == "update":
        return [*prefix, "install", "--only-upgrade", "-y", "--", package]
    return [*prefix, "remove", "-y", "--", package]


def execute_operation(tool_id: str, operation: str) -> OperationResult:
    """Execute a supported operation only after the caller has obtained local approval."""
    if tool_id not in SUPPORTED_TOOLS or operation not in {"install", "update", "uninstall"}:
        return OperationResult("unsupported", "The requested tool or operation is not supported.")
    if operation == "uninstall" and tool_id not in UNINSTALL_SUPPORTED:
        return OperationResult("unsupported", "Uninstallation is not enabled because a verified removal policy is not configured.")
    package = _package_and_manager(tool_id)
    if not package:
        return OperationResult("unsupported", "No verified package mapping exists for this tool on this operating system.")
    before = {item["id"]: item for item in scan_tools()}.get(tool_id, {})
    if operation == "install" and before.get("status") in {"Installed", "Outdated"}:
        return OperationResult("failed", "The tool is already installed; no installation was started.", before.get("version"))
    if operation in {"update", "uninstall"} and before.get("status") not in {"Installed", "Outdated"}:
        return OperationResult("failed", "The tool is not confirmed as installed; no operation was started.", before.get("version"))
    command = _command(tool_id, operation)
    if not command:
        return OperationResult("unsupported", "The required verified package manager is unavailable or elevated execution is not available.", before.get("version"))
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=OPERATION_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            env=_package_manager_environment(),
        )
    except subprocess.TimeoutExpired:
        return OperationResult("failed", "The package-manager operation timed out; verify the tool locally before retrying.", before.get("version"))
    except OSError as exc:
        return OperationResult("failed", f"The allowlisted package-manager command could not start: {exc}", before.get("version"))
    after = {item["id"]: item for item in scan_tools()}.get(tool_id, {})
    output = (result.stdout or result.stderr or "").strip()[-MAX_OUTPUT:]
    if operation in {"install", "update"}:
        verified = after.get("status") in {"Installed", "Outdated"} and bool(after.get("version"))
    else:
        verified = after.get("status") == "Missing"
    if result.returncode == 0 and verified:
        if operation == "update":
            message = output or f"Package manager reported success; the local scan confirms {tool_id} version {after.get('version')}. Latest-version availability is not verified."
        else:
            message = output or f"{operation.title()} completed and the local tool scan verified the result."
        return OperationResult("success", message, after.get("version"))
    message = output or f"Package manager exited with code {result.returncode}; post-operation verification did not pass."
    return OperationResult("failed", message, after.get("version"))
