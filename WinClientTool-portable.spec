# -*- mode: python ; coding: utf-8 -*-
# Portable single-file build — one exe with everything embedded (onefile mode)

import os

project_root = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['C:\\Users\\iorda\\OneDrive\\Documents\\Visual Studio 2022\\TEMP\\Windows_client_tool\\src\\main.py'],
    pathex=[],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'config'), 'config'),
        (os.path.join(project_root, 'src', 'ui', 'styles'), 'ui/styles'),
        (os.path.join(project_root, 'src', 'modules', 'tweaks', 'definitions'), 'modules/tweaks/definitions'),
    ],
    hiddenimports=[
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui',
        'pywin32', 'pywin32_bootstrap',
        'win32api', 'win32con', 'win32gui', 'win32process', 'win32service', 'win32evtlog',
        'win32com', 'win32com.client',
        'PIL', 'PIL._imaging',
        'requests', 'urllib3', 'charset_normalizer', 'idna',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    exclude_binaries=False,  # required for onefile mode
    name='WinClientTool-Portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
