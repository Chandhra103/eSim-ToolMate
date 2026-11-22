from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.registry import ToolRegistry
from app.managers.operations import Operations
from app.services.storage import Storage
from app.ui.main_window import MainWindow


def main():
    app=QApplication(sys.argv); app.setApplicationName("eSim ToolMate")
    try:
        registry=ToolRegistry(Path(__file__).parents[1]/"data"/"tools.json"); storage=Storage(); window=MainWindow(registry,storage,Operations(registry,storage)); window.show(); return app.exec()
    except Exception as exc:  # noqa: BLE001 - startup boundary must surface any initialization failure
        QMessageBox.critical(None,"Startup error",str(exc)); return 1
if __name__ == "__main__": raise SystemExit(main())
