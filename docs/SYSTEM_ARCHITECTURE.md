# System Architecture

The application uses a shared Python core with Qt Widgets at the presentation layer. The registry loads tool metadata from `data/tools.json`, the detection engine resolves executables using `shutil.which`, and version commands run as argument arrays under a short timeout. The UI never owns installation policy.

Data flow: UI action → manager → registry/security policy → approved subprocess → verification scan → SQLite activity record → refreshed dashboard. Diagnostics are generated from operating-system APIs and selected package-manager availability; personal files are not traversed.

Installation is supported only when the registry contains a verified package identifier and the corresponding local manager is present. Linux currently targets apt-get package installation. Windows targets winget with exact package IDs. Unsupported systems receive a clear manual-installation path and official website from the registry.

The security model rejects arbitrary command strings, uses explicit allowlists, avoids shell invocation, validates backup JSON structure, uses atomic backup writes, asks for confirmation, and records errors without secrets. Environment-variable editing should be extended through a dedicated adapter that backs up the previous value and preserves unrelated entries before enabling system-level changes.
