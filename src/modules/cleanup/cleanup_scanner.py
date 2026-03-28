import os
import shutil
import glob
import string
from dataclasses import dataclass, field
from typing import List, Callable, Optional, Tuple
from pathlib import Path


@dataclass
class ScanItem:
    path: str
    size: int        # bytes
    is_dir: bool
    selected: bool = True


@dataclass
class ScanResult:
    items: List[ScanItem] = field(default_factory=list)
    total_size: int = 0

    def selected_size(self) -> int:
        return sum(i.size for i in self.items if i.selected)


def get_dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _make_item(path: str) -> Optional[ScanItem]:
    """Return ScanItem for path if it exists, else None."""
    if not os.path.exists(path):
        return None
    is_dir = os.path.isdir(path)
    size = get_dir_size(path) if is_dir else os.path.getsize(path)
    return ScanItem(path=path, size=size, is_dir=is_dir)


def scan_temp_files() -> ScanResult:
    result = ScanResult()
    targets = [
        os.environ.get("TEMP", ""),
        r"C:\Windows\Temp",
    ]
    for t in targets:
        if not t:
            continue
        item = _make_item(t)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_browser_caches() -> ScanResult:
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Google\Chrome\User Data\Default\Cache"),
        os.path.join(local, r"Microsoft\Edge\User Data\Default\Cache"),
    ]
    # Firefox: detect profiles
    ff_profiles = glob.glob(os.path.join(appdata, r"Mozilla\Firefox\Profiles\*\cache2"))
    targets.extend(ff_profiles)
    for t in targets:
        item = _make_item(t)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wu_cache() -> ScanResult:
    result = ScanResult()
    path = r"C:\Windows\SoftwareDistribution\Download"
    item = _make_item(path)
    if item:
        result.items.append(item)
        result.total_size = item.size
    return result


def scan_prefetch() -> ScanResult:
    result = ScanResult()
    pf_dir = r"C:\Windows\Prefetch"
    for pf in glob.glob(os.path.join(pf_dir, "*.pf")):
        try:
            size = os.path.getsize(pf)
            result.items.append(ScanItem(path=pf, size=size, is_dir=False))
            result.total_size += size
        except OSError:
            pass
    return result


def scan_recycle_bin() -> ScanResult:
    result = ScanResult()
    for drive in string.ascii_uppercase:
        rb = f"{drive}:\\$Recycle.Bin"
        if os.path.exists(rb):
            item = _make_item(rb)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_event_logs() -> ScanResult:
    result = ScanResult()
    logs_dir = r"C:\Windows\System32\winevt\Logs"
    for evtx in glob.glob(os.path.join(logs_dir, "*.evtx")):
        try:
            size = os.path.getsize(evtx)
            result.items.append(ScanItem(path=evtx, size=size, is_dir=False))
            result.total_size += size
        except OSError:
            pass
    return result


def delete_items(items: List[ScanItem],
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 stop_wuauserv: bool = False) -> Tuple[int, int]:
    """Delete selected items. Returns (deleted_count, error_count).
    If stop_wuauserv=True, wraps deletions in _ServiceStopped("wuauserv")."""

    class _ServiceStopped:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            try:
                import win32serviceutil
                win32serviceutil.StopService(self.name)
            except Exception:
                pass

        def __exit__(self, *_):
            try:
                import win32serviceutil
                win32serviceutil.StartService(self.name)
            except Exception:
                pass

    def _do_delete():
        deleted = 0
        errors = 0
        selected = [i for i in items if i.selected]
        total = len(selected)
        for idx, item in enumerate(selected):
            if on_progress:
                on_progress(idx + 1, total)
            try:
                if not os.path.exists(item.path):
                    continue  # already gone — not an error
                if item.is_dir:
                    shutil.rmtree(item.path, ignore_errors=True)
                else:
                    os.remove(item.path)
                deleted += 1
            except OSError:
                errors += 1
        return deleted, errors

    if stop_wuauserv:
        with _ServiceStopped("wuauserv"):
            return _do_delete()
    else:
        return _do_delete()
