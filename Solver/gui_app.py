#!/usr/bin/env python
"""
GUI entry point for the PySolve Eggs mission optimizer.

Usage:
    python -m Solver.gui_app
    pysolve-eggs-gui  (if installed via pip)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .gui import MainWindow


def main(config_path: Optional[Path] = None) -> int:
    """
    Launch the GUI application.
    
    Parameters
    ----------
    config_path : Path, optional
        Path to user config YAML. Defaults to Solver/DefaultUserConfig.yaml
    
    Returns
    -------
    int
        Exit code (0 for success)
    """
    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("PySolve Eggs")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("PySolveEggs")
    
    # Apply a clean style
    app.setStyle("Fusion")
    
    # Create and show main window
    window = MainWindow(config_path)
    window.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
