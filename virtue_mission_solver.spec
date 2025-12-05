# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Virtue Mission Solver.

This builds a standalone Windows executable that bundles:
- The PySide6 GUI application
- All required data files (Wasmegg JSON, FetchData, config)
- PuLP CBC solver binaries
- Python runtime and dependencies

Usage:
    pyinstaller virtue_mission_solver.spec

Or use the build script:
    .\build.ps1
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import sys
from pathlib import Path

block_cipher = None

# Collect PuLP solver binaries (includes CBC solver)
pulp_datas = collect_data_files('pulp')

# Collect all PuLP submodules (for solver APIs)
pulp_hiddenimports = collect_submodules('pulp')

a = Analysis(
    ['launcher.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Wasmegg game data files
        ('Wasmegg/*.json', 'Wasmegg'),
        
        # Drop data (mission artifact statistics)
        ('FetchData/egginc_data_All.json', 'FetchData'),
        
        # Solver configuration
        ('Solver/DefaultUserConfig.yaml', 'Solver'),
        
        # PuLP solver binaries
        *pulp_datas,
    ],
    hiddenimports=[
        # PuLP solver APIs
        *pulp_hiddenimports,
        'pulp.apis.coin_api',
        
        # Pandas dependencies that may not be auto-detected
        'pandas._libs.tslibs.timedeltas',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.np_datetime',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'tkinter',
        'matplotlib',
        'notebook',
        'jupyter',
        # Exclude test frameworks (not needed at runtime)
        'pytest',
        'pytest_cov',
        '_pytest',
        'coverage',
        # Exclude development tools
        'setuptools',
        'pip',
        'wheel',
        # Exclude unused optional dependencies
        'jinja2',
        'IPython',
        'ipykernel',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='VirtueMissionSolver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='assets/icon.ico',  # Uncomment when you have an icon
)
