"""Shared types and helpers for the cleanup scanner package."""
import logging
import os
import time
from core.formatting import format_size
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class ScanItem:
    path: str
    size: int        # bytes
    is_dir: bool
    selected: bool = True
    safety: str = "safe"   # "safe" | "caution" | "danger"

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
                    logger.debug("Ignored OSError", exc_info=True)
    except OSError:
        logger.debug("Ignored OSError", exc_info=True)
    return total

def _make_item(path: str, safety: str = "safe", min_age_days: int = 0) -> Optional[ScanItem]:
    """Return ScanItem for path if it exists, else None. Respects min_age_days."""
    if not os.path.exists(path):
        return None
    if min_age_days > 0:
        try:
            mtime = os.path.getmtime(path)
            age_seconds = time.time() - mtime
            if age_seconds < min_age_days * 86400:
                return None
        except OSError:
            return None
    is_dir = os.path.isdir(path)
    size = get_dir_size(path) if is_dir else os.path.getsize(path)
    return ScanItem(path=path, size=size, is_dir=is_dir, safety=safety)

def _make_item_with_age(path: str, safety: str, min_age_days: int) -> Optional[ScanItem]:
    """Return ScanItem for a file only if it meets the age threshold. Direct file helper."""
    try:
        if min_age_days > 0:
            mtime = os.path.getmtime(path)
            if (time.time() - mtime) < min_age_days * 86400:
                return None
        size = os.path.getsize(path)
        return ScanItem(path=path, size=size, is_dir=False, safety=safety)
    except OSError:
        return None

__all__ = ['ScanItem', 'ScanResult', 'get_dir_size', 'format_size', '_make_item', '_make_item_with_age', 'logger']
