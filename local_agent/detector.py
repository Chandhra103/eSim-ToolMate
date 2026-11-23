from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

TOOL_SPECS = {
    "ngspice": {
        "name": "Ngspice",
        "executables": [("ngspice", ["--version"])],
        "packages": {"debian": "ngspice", "rpm": "ngspice", "pacman": "ngspice", "winget": "ngspice.ngspice"},
    },
    "kicad": {
        "name": "KiCad",
        "executables": [("kicad-cli", ["version"]), ("kicad", ["--version"])],
        "packages": {"debian": "kicad", "rpm": "kicad", "pacman": "kicad", "winget": "KiCad.KiCad"},
    },
    "ghdl": {
        "name": "GHDL",
        "executables": [("ghdl", ["--version"])],
        "packages": {"debian": "ghdl", "rpm": "ghdl", "pacman": "ghdl", "winget": "GHDL.GHDL"},
    },
    "ngveri": {
        "name": "NgVeri",
        "executables": [("ngveri", ["--version"])],
        "packages": {},
    },
    "python": {
        "name": "Python",
        "executables": [("python3", ["--version"]), ("python", ["--version"])],
        "packages": {"debian": "python3", "rpm": "python3", "pacman": "python", "winget": "Python.Python.3.12"},
    },
    "git": {
        "name": "Git",
        "executables": [("git", ["--version"])],
        "packages": {"debian": "git", "rpm": "git", "pacman": "git", "winget": "Git.Git"},
    },
}

VERSION_RE = re.compile(r"(?<![A-Za-z])v?(\d+(?:\.\d+){0,5}(?:[-+~][0-9A-Za-z.-]+)?)")


def _process_environment() -> dict[str, str]:
    allowed = ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update({"LANG": "C", "LC_ALL": "C"})
    return env


def _package_manager_environment() -> dict[str, str]:
    env = _process_environment()
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        paths = [str(Path(system_root) / "System32"), system_root]
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata and Path(local_appdata).is_absolute():
            paths.append(str(Path(local_appdata) / "Microsoft" / "WindowsApps"))
        env["PATH"] = os.pathsep.join(paths)
    else:
        env["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    return env


def _find_package_manager(name: str) -> str | None:
    if os.name == "nt":
        candidates = []
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata and Path(local_appdata).is_absolute():
            candidates.append(Path(local_appdata) / "Microsoft" / "WindowsApps" / f"{name}.exe")
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        if program_files.is_absolute():
            windows_apps = program_files / "WindowsApps"
            try:
                candidates.extend(path / f"{name}.exe" for path in windows_apps.glob("Microsoft.DesktopAppInstaller_*") if path.is_dir())
            except OSError:
                pass
    else:
        candidates = [Path(directory) / name for directory in ("/usr/bin", "/bin", "/usr/sbin", "/sbin")]
    for candidate in candidates:
        try:
            if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return str(candidate.resolve())
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class ToolDetection:
    id: str
    name: str
    status: str
    version: str | None
    executable_path: str | None
    detection_source: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _system_dirs() -> list[Path]:
    if os.name == "nt":
        roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")), Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))]
        dirs = [Path(sys.prefix), Path(sys.prefix) / "Scripts"]
        for root in roots:
            dirs.extend([root / "KiCad" / "bin", root / "ngspice" / "bin", root / "Git" / "cmd", root / "Git" / "bin"])
        dirs.append(Path(os.environ.get("SystemDrive", "C:") + os.sep) / "Spice64" / "bin")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.extend([Path(local) / "Programs" / "Python", Path(local) / "Programs" / "Git" / "cmd"])
        return dirs
    return [Path(x) for x in ("/usr/bin", "/usr/local/bin", "/bin", "/usr/sbin", "/usr/local/sbin", "/opt/kicad/bin", "/usr/lib/kicad/bin", "/usr/local/kicad/bin")]


def _candidate_paths(executable: str) -> list[Path]:
    names = [executable]
    if os.name == "nt" and not executable.lower().endswith(".exe"):
        names = [f"{executable}.exe", executable]
    result: list[Path] = []
    located = shutil.which(executable)
    if located:
        result.append(Path(located))
    for directory in _system_dirs():
        for name in names:
            result.append(directory / name)
    # KiCad keeps major-versioned binaries one directory below its installation root.
    if os.name == "nt":
        for root_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(root_name)
            if root:
                kicad_root = Path(root) / "KiCad"
                try:
                    for version_dir in kicad_root.iterdir():
                        if version_dir.is_dir():
                            result.extend(version_dir / "bin" / name for name in names)
                except OSError:
                    pass
    unique: list[Path] = []
    seen: set[str] = set()
    for path in result:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _find_executable(executable: str) -> Path | None:
    for path in _candidate_paths(executable):
        try:
            if path.is_file() and (os.name == "nt" or os.access(path, os.X_OK)):
                return path.resolve()
        except OSError:
            continue
    return None


def _read_version(executable: Path, arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            shell=False,
            env=_process_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = "\n".join((result.stdout or "", result.stderr or ""))[:8192]
    match = VERSION_RE.search(output)
    return match.group(1) if match else None


def _manager_version(manager: str, package: str) -> str | None:
    commands = {
        "debian": ["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${Version}", package],
        "rpm": ["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", package],
        "pacman": ["pacman", "-Q", package],
    }
    command = commands.get(manager)
    if manager == "winget":
        exe = _find_package_manager("winget")
        if not exe:
            return None
        command = [exe, "list", "--id", package, "--exact", "--accept-source-agreements", "--disable-interactivity"]
    elif command:
        exe = _find_package_manager(command[0])
        if not exe:
            return None
        command[0] = exe
    if not command:
        return None
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8, check=False, shell=False, env=_package_manager_environment())
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    if manager == "debian":
        fields = output.split("\t", 1)
        if len(fields) != 2 or not fields[0].startswith("ii"):
            return None
        output = fields[1]
    elif manager == "pacman":
        fields = output.split()
        if len(fields) < 2 or fields[0] != package:
            return None
        output = fields[1]
    elif manager == "winget":
        output = _parse_winget_version(output, package)
        if not output:
            return None
    match = VERSION_RE.search(output)
    return match.group(1) if match else None


def _parse_winget_version(output: str, package: str) -> str | None:
    for line in output.splitlines():
        if package.casefold() not in line.casefold():
            continue
        if "|" in line:
            columns = [part.strip() for part in line.split("|")]
            try:
                index = next(i for i, value in enumerate(columns) if value.casefold() == package.casefold())
                return columns[index + 1] if index + 1 < len(columns) else None
            except StopIteration:
                continue
        fields = line.split()
        for index, value in enumerate(fields):
            if value.casefold() == package.casefold() and index + 1 < len(fields):
                return fields[index + 1]
    return None


def _installed_from_packages(tool_id: str) -> tuple[str, str] | None:
    spec = TOOL_SPECS[tool_id]
    manager_order = ["winget"] if os.name == "nt" else ["debian", "rpm", "pacman"]
    for manager in manager_order:
        package = spec["packages"].get(manager)
        if package:
            version = _manager_version(manager, package)
            if version:
                return version, f"{manager} package record"
    return None


def _version_key(value: str) -> tuple:
    """Compare numeric release components without guessing a latest version."""
    numbers = re.findall(r"\d+", value)
    if not numbers:
        raise ValueError("version has no numeric components")
    return tuple(int(number) for number in numbers)


def scan_tools(minimum_versions: dict[str, str] | None = None) -> list[dict]:
    minimum_versions = minimum_versions or {}
    detected: list[dict] = []
    for tool_id, spec in TOOL_SPECS.items():
        executable_path: Path | None = None
        version: str | None = None
        source: str | None = None
        for executable, args in spec["executables"]:
            executable_path = _find_executable(executable)
            if executable_path:
                version = _read_version(executable_path, args)
                source = "executable"
                break
        package_result = _installed_from_packages(tool_id)
        if package_result and not version:
            version, source = package_result
        minimum = minimum_versions.get(tool_id)
        if version and minimum:
            try:
                status = "Outdated" if _version_key(version) < _version_key(minimum) else "Installed"
            except ValueError:
                status = "Unknown"
        elif version:
            status = "Installed"
        elif executable_path:
            status = "Unknown"
        else:
            status = "Missing"
        detected.append(ToolDetection(
            tool_id, spec["name"], status, version,
            str(executable_path) if executable_path and source == "executable" else None,
            source,
        ).as_dict())
    return detected


def scan_report(minimum_versions: dict[str, str] | None = None) -> dict:
    return {
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "scanned_at": datetime.now(UTC).isoformat(),
        "tools": scan_tools(minimum_versions),
    }
