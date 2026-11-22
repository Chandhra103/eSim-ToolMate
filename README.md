# eSim ToolMate

**Detect. Install. Configure. Update. Verify.**

A cross-platform PySide6 desktop application for discovering and safely managing the external tools used with eSim. The implementation is built around real executable detection, allowlisted package-manager commands, persistent SQLite activity logs, diagnostics, and an extensible JSON tool registry.

## Features

- Professional dashboard inspired by the supplied reference UI, including light/dark themes, sidebar navigation, summary cards, quick actions, search, and activity feed.
- Real detection of Ngspice, KiCad, GHDL, NgVeri, Python, and Git through `PATH` and version commands.
- Verified installation paths for Debian/Ubuntu `apt-get` and Windows `winget` when available; otherwise provides a safe manual-installation fallback instead of inventing a package ID.
- Background system scans so the interface remains responsive.
- Dependency check framework, diagnostics JSON export, activity SQLite database, CSV export, and configuration backup primitives.
- Secure subprocess policy: argument lists only, command allowlisting, timeouts, confirmation dialogs, and no arbitrary AI-generated shell commands.
- Automated tests and GitHub Actions quality checks.

## Setup

Python 3.11+ is supported. On Ubuntu/Debian:

```bash
sudo apt install python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

## Architecture

`app/core` contains the registry, detection, diagnostics, version comparison, and security policy. `app/managers` contains approved installation/dependency workflows. `app/services` contains SQLite storage and backups. `app/ui` contains the Qt Widgets interface. `data/tools.json` is the extensible registry: adding a supported tool does not require changing every UI module.

Application data is stored through `platformdirs` in the user application-data directory and is not written into the repository. No passwords, API keys, or personal files are collected.

## Testing and quality

```bash
pytest -q
ruff check app tests
python -m compileall -q app
```

Normal tests never perform real installations; package-manager operations are allowlisted and should be mocked in integration tests. A graphical smoke test requires a desktop/display server. Headless environments can still run the core and persistence tests.

## Supported operations and limitations

Detection works on systems where the executable is available on `PATH`. Automated installation is deliberately limited to verified package-manager identifiers in the registry and available local package managers. NgVeri has no automated installer because its source and distribution compatibility must be validated per platform. Latest-version metadata retrieval is conservative and is not reported as an update unless an authoritative source integration is configured; the application never fabricates version numbers.

System-level installation and environment-variable changes may require administrator approval. The application does not silently elevate privileges or overwrite unrelated `PATH` entries.

## Project documents

- [System architecture](docs/SYSTEM_ARCHITECTURE.md)
- [User and execution guide](docs/USER_GUIDE.md)
- [Test report](docs/TEST_REPORT.md)
