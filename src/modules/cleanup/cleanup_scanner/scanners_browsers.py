"""Cleanup scanners: browsers category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item,
)

logger = logging.getLogger(__name__)

__all__ = [
]