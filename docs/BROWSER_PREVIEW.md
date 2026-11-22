# Browser Preview

The repository includes `server.py`, a FastAPI browser backend, and `web/index.html`, a responsive premium dashboard. The browser view is intentionally separate from the native PySide6 desktop UI while reusing the same registry, diagnostics, dependency, installation, update, verification, and SQLite storage services.

The preview uses the formal neutral design system: charcoal `#292929` for navigation and headings, warm ivory `#F5F2EC` for backgrounds and cards, and taupe `#A89B8C` for buttons, borders, and highlights. Saturated colors, gradients, neon effects, and colorful status badges have been removed. Space Grotesk/DM Sans typography, subtle shadows, and a restrained neutral CSS 3D microchip preserve the premium engineering-software character.

All metrics are loaded through the API. The Dependency Checker now presents summary cards and relationship rows; System Diagnostics presents resource cards, environment health, warnings/errors, and tool availability; Tool Manager exposes verify/install/update/uninstall actions where a verified package manager is available; Configuration Manager validates editable JSON profiles, creates a backup before save, restores backups, and records change history; Activity Logs support search.

Browser installations are explicitly scoped to the isolated cloud environment and never claim to modify a visitor's laptop. Start with `uvicorn server:app --host 0.0.0.0 --port 8000`; Swagger API documentation is available at `/docs`.

Validation evidence for this revision: six pytest tests pass, API endpoint smoke checks pass, Ruff passes, Python compilation passes, and both the browser preview and native PySide6 interface have been smoke-tested.
