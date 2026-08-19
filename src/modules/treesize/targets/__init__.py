"""Scan targets (spec 6). Importing the package registers the backends."""
from . import remote  # noqa: F401  -- import for the side effect of registering
from .base import (  # noqa: F401
    Credentials, ScanTarget, TargetError, available_targets, get_target,
)
