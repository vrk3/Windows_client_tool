# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('src/ui/styles/dark.qss', 'ui/styles'), ('src/ui/styles/light.qss', 'ui/styles'), ('config/default_config.json', 'config')]
binaries = []
hiddenimports = ['modules.event_viewer.event_viewer_module', 'modules.cbs_log.cbs_module', 'modules.dism_log.dism_module', 'modules.windows_update.wu_module', 'modules.reliability.reliability_module', 'modules.crash_dumps.crash_dump_module', 'modules.perfmon.perfmon_module', 'modules.process_explorer.process_explorer_module', 'win32service', 'win32serviceutil', 'win32security', 'win32api', 'win32con']
tmp_ret = collect_all('psutil')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['src\\main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    name='WinClientTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
