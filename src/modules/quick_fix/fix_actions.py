import glob as _glob
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class FixAction:
    key: str                          # unique identifier
    title: str
    description: str
    category: str
    reboot_required: bool = False
    fn: Optional[Callable[[Callable[[str], None]], None]] = field(default=None, repr=False)
    # fn signature: fn(output_cb: Callable[[str], None]) -> None
    # output_cb is called with each line of output


def _run_cmd(cmd: List[str], output_cb: Callable[[str], None],
             input_bytes: bytes = None) -> int:
    """Run a command, streaming output line by line via output_cb. Returns exit code."""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if input_bytes else None,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if input_bytes:
            proc.stdin.write(input_bytes.decode())
            proc.stdin.close()
        for line in proc.stdout:
            output_cb(line.rstrip())
        proc.wait()
        return proc.returncode
    except Exception as e:
        output_cb(f"Error: {e}")
        return -1


def _stop_service(name: str, output_cb: Callable[[str], None]) -> None:
    output_cb(f"Stopping {name}...")
    try:
        import win32serviceutil
        win32serviceutil.StopService(name)
        output_cb(f"{name} stopped.")
    except Exception as e:
        output_cb(f"Could not stop {name}: {e}")


def _start_service(name: str, output_cb: Callable[[str], None]) -> None:
    output_cb(f"Starting {name}...")
    try:
        import win32serviceutil
        win32serviceutil.StartService(name)
        output_cb(f"{name} started.")
    except Exception as e:
        output_cb(f"Could not start {name}: {e}")


def run_sfc(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["sfc", "/scannow"], output_cb)


def run_dism(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["dism", "/online", "/cleanup-image", "/restorehealth"], output_cb)


def run_chkdsk(output_cb: Callable[[str], None]) -> None:
    output_cb("Scheduling CHKDSK for next reboot...")
    _run_cmd(["chkdsk", "C:", "/f", "/r", "/x"], output_cb, input_bytes=b"Y\n")
    output_cb("CHKDSK scheduled. Reboot to run.")


def rebuild_icon_cache(output_cb: Callable[[str], None]) -> None:
    output_cb("Stopping Explorer...")
    subprocess.run(
        ["taskkill", "/f", "/im", "explorer.exe"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(1)
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, "IconCache.db"),
        *_glob.glob(os.path.join(local, r"Microsoft\Windows\Explorer\iconcache*")),
    ]
    for t in targets:
        try:
            os.remove(t)
            output_cb(f"Deleted: {t}")
        except OSError as e:
            output_cb(f"Could not delete {t}: {e}")
    output_cb("Restarting Explorer...")
    subprocess.Popen(["explorer.exe"])
    output_cb("Done.")


def clear_thumbnail_cache(output_cb: Callable[[str], None]) -> None:
    output_cb("Stopping Explorer...")
    subprocess.run(
        ["taskkill", "/f", "/im", "explorer.exe"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(1)
    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(local, r"Microsoft\Windows\Explorer\thumbcache_*.db")
    for f in _glob.glob(pattern):
        try:
            os.remove(f)
            output_cb(f"Deleted: {f}")
        except OSError as e:
            output_cb(f"Skip {f}: {e}")
    output_cb("Restarting Explorer...")
    subprocess.Popen(["explorer.exe"])
    output_cb("Done.")


def restart_explorer(output_cb: Callable[[str], None]) -> None:
    output_cb("Killing Explorer...")
    subprocess.run(
        ["taskkill", "/f", "/im", "explorer.exe"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(1)
    output_cb("Starting Explorer...")
    subprocess.Popen(["explorer.exe"])
    output_cb("Done.")


def flush_dns(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["ipconfig", "/flushdns"], output_cb)


def reset_winsock(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["netsh", "winsock", "reset"], output_cb)
    output_cb("Reboot required to complete.")


def reset_tcpip(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["netsh", "int", "ip", "reset"], output_cb)
    output_cb("Reboot required to complete.")


def ip_release_renew(output_cb: Callable[[str], None]) -> None:
    _run_cmd(["ipconfig", "/release"], output_cb)
    _run_cmd(["ipconfig", "/renew"], output_cb)


def reset_windows_update(output_cb: Callable[[str], None]) -> None:
    services = ["wuauserv", "cryptsvc", "bits", "msiserver"]
    for svc in services:
        _stop_service(svc, output_cb)
    dirs_to_clear = [
        r"C:\Windows\SoftwareDistribution",
        r"C:\Windows\System32\catroot2",
    ]
    for d in dirs_to_clear:
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
                output_cb(f"Deleted: {d}")
            except OSError as e:
                output_cb(f"Error deleting {d}: {e}")
    for svc in services:
        _start_service(svc, output_cb)
    output_cb("Windows Update reset complete.")


def reregister_wu_dlls(output_cb: Callable[[str], None]) -> None:
    dlls = [
        "atl.dll", "urlmon.dll", "mshtml.dll", "shdocvw.dll", "browseui.dll",
        "jscript.dll", "vbscript.dll", "scrrun.dll", "msxml.dll", "msxml3.dll",
        "msxml6.dll", "actxprxy.dll", "softpub.dll", "wintrust.dll", "dssenh.dll",
        "rsaenh.dll", "gpkcsp.dll", "sccbase.dll", "slbcsp.dll", "cryptdlg.dll",
        "oleaut32.dll", "ole32.dll", "shell32.dll", "initpki.dll", "wuapi.dll",
        "wuaueng.dll", "wuaueng1.dll", "wucltui.dll", "wups.dll", "wups2.dll", "wuweb.dll",
    ]
    for dll in dlls:
        rc = _run_cmd(["regsvr32", "/s", dll], output_cb)
        output_cb(f"regsvr32 {dll}: {'OK' if rc == 0 else 'Failed'}")
    output_cb("Done.")


def clear_print_queue(output_cb: Callable[[str], None]) -> None:
    _stop_service("Spooler", output_cb)
    spool_dir = r"C:\Windows\System32\spool\PRINTERS"
    if os.path.isdir(spool_dir):
        for f in os.listdir(spool_dir):
            fpath = os.path.join(spool_dir, f)
            try:
                os.remove(fpath)
                output_cb(f"Deleted: {f}")
            except OSError as e:
                output_cb(f"Skip {f}: {e}")
    _start_service("Spooler", output_cb)
    output_cb("Print queue cleared.")


ALL_ACTIONS: List[FixAction] = [
    # System Repairs
    FixAction("sfc", "SFC Scan", "Scan and repair protected Windows files",
              "System Repairs", fn=run_sfc),
    FixAction("dism", "DISM RestoreHealth", "Repair the Windows component store",
              "System Repairs", fn=run_dism),
    FixAction("chkdsk", "CHKDSK Schedule", "Schedule disk check for next reboot",
              "System Repairs", reboot_required=True, fn=run_chkdsk),
    # Cache & UI
    FixAction("icon_cache", "Rebuild Icon Cache", "Delete and rebuild Windows icon cache",
              "Cache & UI", fn=rebuild_icon_cache),
    FixAction("thumb_cache", "Clear Thumbnail Cache", "Delete Windows thumbnail cache files",
              "Cache & UI", fn=clear_thumbnail_cache),
    FixAction("explorer", "Restart Explorer", "Kill and restart Windows Explorer",
              "Cache & UI", fn=restart_explorer),
    # Network
    FixAction("flush_dns", "Flush DNS", "Clear the DNS resolver cache",
              "Network", fn=flush_dns),
    FixAction("winsock", "Reset Winsock", "Reset network socket catalog (reboot required)",
              "Network", reboot_required=True, fn=reset_winsock),
    FixAction("tcpip", "Reset TCP/IP", "Reset TCP/IP stack (reboot required)",
              "Network", reboot_required=True, fn=reset_tcpip),
    FixAction("ip_renew", "IP Release/Renew", "Release and renew IP address",
              "Network", fn=ip_release_renew),
    # Windows Update
    FixAction("wu_reset", "Reset Windows Update",
              "Stop WU services, clear caches, restart",
              "Windows Update", fn=reset_windows_update),
    FixAction("wu_dlls", "Re-register WU DLLs",
              "Re-register all Windows Update DLL files",
              "Windows Update", fn=reregister_wu_dlls),
    # Print
    FixAction("print_queue", "Clear Print Queue",
              "Stop Spooler, delete print jobs, restart",
              "Print", fn=clear_print_queue),
]
