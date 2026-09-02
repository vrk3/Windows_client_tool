"""cleanup_scanner package facade. Re-exports all scanners and shared types
so existing imports (`from modules.cleanup import cleanup_scanner as cs`,
`from modules.cleanup.cleanup_scanner import ScanResult, ScanItem, format_size`)
keep working unchanged."""
from modules.cleanup.cleanup_scanner._common import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_apps import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_browsers import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_cloud import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_comms import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_dev import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_games import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_media import *  # noqa: F401,F403
from modules.cleanup.cleanup_scanner.scanners_system import *  # noqa: F401,F403

# ── Catalog-defined scanners ───────────────────────────────────────────
#
# The 41 scanners in `definitions/system.json` are data, not code: each was
# the same three lines (expand some environment variables into paths, call
# _make_item, sum the sizes) and they came to 777 lines of this package.
# `catalog.scanner_for` builds a callable with the same
# `scan_x(min_age_days=0)` signature the cleanup tabs pass around, so
# nothing downstream can tell the difference.
#
# Bound AFTER the star-imports above, deliberately: if a hand-written
# scanner of the same name ever reappears, the catalog is what wins, and
# tests/test_cleanup_catalog.py asserts every name resolves.
from modules.cleanup.cleanup_scanner.catalog import (  # noqa: E402
    ScannerSpec, all_scanners, load_catalog, run_spec, scanner_for,
)

globals().update(all_scanners())
