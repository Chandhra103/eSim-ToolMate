# Browser Preview

The repository now includes `server.py`, a FastAPI browser backend, and `web/index.html`, a responsive premium dashboard. The browser view is intentionally separate from the native PySide6 desktop UI while reusing the same registry, diagnostics, dependency, installation, and SQLite storage services.

The preview uses a navy-to-indigo shell, cyan highlights, emerald success states, amber warnings, soft glass panels, and Space Grotesk/DM Sans typography. The hero includes a CSS 3D animated microchip with perspective, depth faces, pins, glow, and continuous rotation. This avoids heavyweight external 3D assets and remains stable in constrained cloud previews.

All metrics are loaded through the API. Browser installations are explicitly scoped to the isolated cloud environment and never claim to modify a visitor's laptop. Start with `uvicorn server:app --host 0.0.0.0 --port 8000`; Swagger API documentation is available at `/docs`.
