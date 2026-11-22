# Browser Preview

The repository includes `server.py`, a FastAPI browser backend, and `web/index.html`, a responsive premium dashboard. The browser view is intentionally separate from the native PySide6 desktop UI while reusing the same registry, diagnostics, dependency, installation, update, verification, and SQLite storage services.

The preview uses a navy-to-indigo shell, cyan highlights, emerald success states, amber warnings, soft glass panels, and Space Grotesk/DM Sans typography. The hero includes a CSS 3D animated microchip with perspective, depth faces, pins, glow, and continuous rotation. This avoids heavyweight external 3D assets and remains stable in constrained cloud previews.

All metrics are loaded through the API. The Dependency Checker now presents summary cards and relationship rows; System Diagnostics presents resource cards, environment health, warnings/errors, and tool availability; Tool Manager exposes verify/install/update/uninstall actions where a verified package manager is available; Configuration Manager validates editable JSON profiles, creates a backup before save, restores backups, and records change history; Activity Logs support search.

Browser installations are explicitly scoped to the isolated cloud environment and never claim to modify a visitor's laptop. Start with `uvicorn server:app --host 0.0.0.0 --port 8000`; Swagger API documentation is available at `/docs`.

Validation evidence for this revision: six pytest tests pass, API endpoint smoke checks pass, Ruff passes, Python compilation passes, and both the browser preview and native PySide6 interface have been smoke-tested.
