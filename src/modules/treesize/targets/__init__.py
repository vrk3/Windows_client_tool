"""Scan targets (spec 6). Importing the package registers the backends."""
from . import cloud, outlook, remote  # noqa: F401  -- imported to register
from .base import (  # noqa: F401
    Credentials, ScanTarget, TargetError, available_targets, get_target,
)
