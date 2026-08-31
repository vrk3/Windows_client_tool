"""Shared PyInstaller Analysis() inputs for all three .spec files
(WinClientTool.spec, WinClientTool-console.spec, WinClientTool-portable.spec).

Kept as plain data here instead of copy-pasted into each spec so the three
builds' datas/hiddenimports lists can't silently drift out of sync — the
folder/console/portable builds are meant to differ only in EXE/COLLECT
packaging options, not in what gets analyzed and bundled.

Each .spec file adds itself to sys.path (spec files aren't run as part of a
package) before importing this module — see any of the three for the pattern.
"""
import os


def get_main_script(project_root: str) -> str:
    return os.path.join(project_root, "src", "main.py")


def get_datas(project_root: str) -> list:
    return [
        (os.path.join(project_root, "config"), "config"),
        (os.path.join(project_root, "src", "ui", "styles"), "ui/styles"),
        (os.path.join(project_root, "src", "modules", "tweaks", "definitions"), "modules/tweaks/definitions"),
        # The Security Dashboard's baselines. JSON beside the catalog, loaded
        # by profile.py relative to its own __file__ -- so without this entry
        # the frozen build RUNS, the Baselines menu opens, and it says "No
        # baselines are installed". Same trap as the hidden imports below:
        # nothing looks broken, the feature is just quietly missing.
        (os.path.join(project_root, "src", "modules", "security_dashboard",
                      "catalog", "baselines"),
         "modules/security_dashboard/catalog/baselines"),
    ]


HIDDEN_IMPORTS = [
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
    "pywin32", "pywin32_bootstrap",
    "win32api", "win32con", "win32gui", "win32process", "win32service", "win32evtlog",
    "win32com", "win32com.client",
    # TreeSize. All of these are imported lazily, inside functions, and
    # win32com.shell is loaded dynamically by pywin32 -- PyInstaller finds
    # none of them by static analysis. Without them the frozen build still
    # RUNS, which is the trap: IFileOperation silently drops to the ctypes
    # fallback (no per-item errors), the remote targets report themselves
    # unavailable, owners come back blank, and the Excel and PDF exports
    # vanish from the menu. Nothing looks broken; things are just quietly
    # missing.
    "win32com.server", "win32com.server.util", "win32com.server.policy",
    "win32com.shell", "win32com.shell.shell", "win32com.shell.shellcon",
    "pythoncom", "pywintypes", "win32security",
    # Composite children. A CompositeModule imports its children inside
    # __init__ so a host module's import does not drag four panes' worth of
    # Qt in at startup. main.py therefore names only the hosts, and these are
    # reachable only through those function-level imports. Listed explicitly
    # for the same reason as the TreeSize block above: if PyInstaller misses
    # one, the frozen build still runs and the tab is simply not there.
    "modules.store_apps.store_apps_module",
    "modules.boot_analyzer.boot_analyzer_module",
    "modules.power_boot.power_module",
    "modules.wifi_analyzer.wifi_module",
    "modules.hosts_editor.hosts_editor_module",
    "modules.network_extras.net_extras_module",
    "modules.event_viewer.event_viewer_module",
    "modules.cbs_log.cbs_module",
    "modules.dism_log.dism_module",
    "modules.windows_update.wu_module",
    "modules.reliability.reliability_module",
    "modules.crash_dumps.crash_dump_module",
    # Group Policy. The pane imports these four inside its button handlers,
    # so a pane that is only ever read does not drag two dialogs and the
    # snapshot machinery in with it. Same trap once more: without them the
    # frozen build opens the pane and reports policy perfectly well, and
    # Snapshot, Compare and Refresh Policy raise ImportError the moment
    # someone clicks them.
    "modules.gpresult.rsop_snapshot",
    "modules.gpresult.snapshot_dialog",
    "modules.gpresult.gpupdate",
    "modules.gpresult.gpupdate_dialog",
    # Log Viewer. The module imports these two dialogs inside button handlers,
    # so a log that is only being read does not drag the error lookup and
    # highlight editor in. Without them the frozen build opens the log and
    # filters it perfectly well, and Error Lookup and Highlight Rules raise
    # ImportError the moment someone clicks them.
    "modules.log_viewer.error_lookup_dialog",
    "modules.log_viewer.highlight_dialog",
    # Both reached only from the "Message colours..." button handler, so
    # the frozen build runs fine until someone clicks it.
    "modules.log_viewer.match_colour_dialog",
    "modules.log_viewer.match_colours",
    # Imported inside DashboardModule.__init__, so PyInstaller's static
    # analysis can miss them and the tabs would be silently absent.
    "modules.dashboard.details_module",
    "modules.dashboard.processes_module",
    "modules.dashboard.processes_tab",
    "modules.dashboard.procengine.grouping",
    "modules.dashboard.details_tab",
    "modules.dashboard.details_model",
    "modules.dashboard.process_menu",
    "modules.dashboard.procengine.ntquery",
    "modules.dashboard.procengine.rates",
    "modules.dashboard.procengine.details",
    "modules.dashboard.procengine.snapshot",
    "modules.dashboard.procengine.columns",
    "modules.dashboard.procengine.actions",
    "modules.process_explorer.process_explorer_module",
    # The Security Dashboard's elevated helper. main.py imports it inside
    # main(), so that the ordinary GUI start does not pay for it, which means
    # PyInstaller cannot see it. The trap here is worse than a missing tab:
    # the frozen build launches its own exe with --apply-security-batch to get
    # a single UAC prompt, and without this the ELEVATED child is the process
    # that dies with ImportError — after the user has granted the prompt, in a
    # window they cannot read, having written no result file. The pane would
    # correctly report the outcome as unknown, forever.
    "modules.security_dashboard.elevated_helper",
    # Imported inside a function in all five of its consumers — Hardware
    # Info, Reliability, Security Dashboard, Services and System Report —
    # every one of them behind a `try:` that degrades silently. Same trap as
    # the TreeSize block above: miss it and the build still runs, with five
    # panes quietly empty and the Security Dashboard scoring a TPM it could
    # not read as absent.
    "wmi",
    "httpx", "paramiko",
    "openpyxl", "reportlab",
    "PIL", "PIL._imaging",
    "requests", "urllib3", "charset_normalizer", "idna",
]
