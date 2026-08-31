"""What has been filtered on, most recent first.

You retype the same three patterns all day during an investigation. This is
the list behind the Filter box's completer.

Kept as a pure function over a list plus two config calls so the ordering
rules are testable without a widget — the same split `log_reader` and
`log_set` keep. No Qt here.
"""
import logging

logger = logging.getLogger(__name__)

#: Where it lives in the app config.
CONFIG_KEY = "log_viewer.filter_history"

#: The logs and folders opened recently. Same ordering rules, different list:
#: you reopen the same handful of paths for the length of an investigation.
CONFIG_RECENT = "log_viewer.recent"

#: Long enough to cover a session's worth of patterns, short enough that the
#: completer's dropdown is still something you can read at a glance.
HISTORY_CAP = 20

#: Shorter than the filter history: a menu of paths is scanned, not read, and
#: ten is already more than an investigation touches.
RECENT_CAP = 10


def remember(history, text: str, cap: int = None) -> list:
    """`history` with `text` at the front, deduplicated and capped.

    Returns a new list rather than mutating: the caller holds the old one
    while the widgets are being rebuilt from it.

    An empty or blank pattern is not remembered — the box's clear button
    empties it, and that is not a search.
    """
    text = (text or "").strip()
    if not text:
        return list(history)
    # Moved rather than duplicated: repeating yesterday's pattern should
    # bring it back to the top, not give it two rows in the dropdown.
    limit = HISTORY_CAP if cap is None else cap
    kept = [entry for entry in history if entry != text]
    return [text] + kept[:limit - 1]


def _load_list(config, key, cap) -> list:
    """The stored history, or an empty list.

    Anything that is not a list of strings is discarded rather than trusted:
    config files get hand-edited, and a bad value here would otherwise reach
    a completer during `create_widget`.
    """
    if config is None:
        return []
    try:
        stored = config.get(key, [])
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not read %s", key, exc_info=True)
        return []
    if not isinstance(stored, list):
        logger.warning("%s is %s, not a list; ignoring it",
                       key, type(stored).__name__)
        return []
    if not all(isinstance(entry, str) for entry in stored):
        logger.warning("%s holds non-string entries; ignoring it", key)
        return []
    return stored[:cap]


def _save_list(config, key, values, cap) -> None:
    if config is None:
        return
    try:
        config.set(key, list(values)[:cap])
        config.save()
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not save %s", key, exc_info=True)


def load_history(config) -> list:
    """Filter patterns, most recent first."""
    return _load_list(config, CONFIG_KEY, HISTORY_CAP)


def load_recent(config) -> list:
    """Logs and folders opened recently, most recent first."""
    return _load_list(config, CONFIG_RECENT, RECENT_CAP)


def save_recent(config, entries) -> None:
    _save_list(config, CONFIG_RECENT, entries, RECENT_CAP)


def save_history(config, history) -> None:
    _save_list(config, CONFIG_KEY, history, HISTORY_CAP)
