"""Cleanup scanners: games category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanItem, ScanResult, get_dir_size, _make_item,
)

logger = logging.getLogger(__name__)

__all__ = [
]