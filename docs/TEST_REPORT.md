# Test Report

## Automated checks

| Area | Expected result | Method |
|---|---|---|
| Registry loading | Six declared tools load | pytest |
| Version comparison | Up-to-date/update/unknown states are distinguished | pytest |
| Security policy | Unsupported managers produce no command | pytest |
| Storage | Activity records and backups round-trip | pytest |
| Compilation | All application modules compile | `python -m compileall -q app` |
| Lint | Ruff reports no configured violations | `ruff check app tests` |

Tests use temporary directories and do not install software. A full GUI smoke test is environment-dependent and should be run on a machine with a display server. Windows package-manager verification must be performed on Windows because the current development environment is Linux.
