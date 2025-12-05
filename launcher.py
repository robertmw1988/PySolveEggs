#!/usr/bin/env python
"""
PyInstaller entry point for Virtue Mission Solver.

This script serves as the main entry point for the frozen executable.
It properly sets up the import path and launches the GUI.
"""
import sys
import os

# When frozen, ensure the bundle's root is in the path
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    bundle_dir = sys._MEIPASS
    # Add the bundle directory to sys.path so imports work
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)

# Now import and run the GUI
from Solver.gui_app import main

if __name__ == '__main__':
    sys.exit(main())
