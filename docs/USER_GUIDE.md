# User Guide

Launch with `python -m app.main`. Use **Scan System** first; all summary counts are derived from the actual executables visible to the current process. The Tool Manager table shows category, installation status, detected version text, executable path, and official website.

To install a missing tool, open Install Tools, select a tool, and confirm. The application uses only the verified package-manager mapping in the registry. If no compatible manager is available, follow the official download link shown in the registry rather than using an untrusted script.

Dependency Checker evaluates declared relationships and reports Satisfied or Missing. System Diagnostics exports a JSON snapshot. Activity Logs are persisted in SQLite and can be exported to CSV. The theme button switches between light and dark presentation styles.

Administrator prompts are controlled by the operating system. Never approve a package installation unless the proposed package name and source shown by the system are expected.
