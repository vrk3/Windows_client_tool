r"""Is this widget still alive?

Worker callbacks land whenever they land, and the widget they were going to
update may be gone by then — the user switched modules, a tab was rebuilt,
the app is shutting down. A Qt call on a deleted C++ object is a **dead
process**, not a traceback, so the check has to happen before the touch.

Twelve places in this codebase were asking that question and eight of them
were asking it wrong:

    try:
        import sip                    # <- always raises under PyQt6
        return not sip.isdeleted(w)
    except ImportError:
        return True                   # <- so this ran, every time

**There is no top-level `sip` module under PyQt6.** It is `PyQt6.sip`. Those
eight guards therefore returned "valid" unconditionally: they read as
protection, cost a try/except per call, and protected nothing. The bug is
silent by construction — the fallback is the safe-looking answer — which is
why `tests/test_widget_life.py` asserts that the import RESOLVED, and fails
the build if anyone writes the bare form again.

Found while fixing a crash of exactly this shape in the Cleanup tab: a scan
landing after its tab was destroyed took the process down with
`-1073740791`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from PyQt6 import sip as _sip
except ImportError:                                    # pragma: no cover
    # Only reachable on a PyQt build without sip bindings, which this app
    # does not have. Logged rather than silent: every caller is unprotected
    # from here on, and that is worth saying out loud once.
    _sip = None
    logging.getLogger(__name__).warning(
        "PyQt6.sip is unavailable — widget lifetime checks cannot run, and "
        "a worker callback reaching a destroyed widget will crash the "
        "process rather than be skipped")


def widget_is_valid(widget: Optional[Any]) -> bool:
    """True if `widget` is a live Qt object worth calling into.

    `None` is not valid: callers hold optional references (a tab whose
    widget was never built), and answering True for one only moves the
    crash a line later.
    """
    if widget is None:
        return False
    if _sip is None:                                   # pragma: no cover
        return True
    try:
        return not _sip.isdeleted(widget)
    except (RuntimeError, TypeError):
        # Not a wrapped Qt object, or already torn down past the point
        # sip can answer for. Either way it is not safe to call into.
        logger.debug("Could not determine lifetime of %r", widget,
                     exc_info=True)
        return False
