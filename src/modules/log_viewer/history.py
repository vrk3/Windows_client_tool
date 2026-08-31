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

#: Long enough to cover a session's worth of patterns, short enough that the
#: completer's dropdown is still something you can read at a glance.
HISTORY_CAP = 20


def remember(history, text: str) -> list:
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
    kept = [entry for entry in history if entry != text]
    return [text] + kept[:HISTORY_CAP - 1]


def load_history(config) -> list:
    """The stored history, or an empty list.

    Anything that is not a list of strings is discarded rather than trusted:
    config files get hand-edited, and a bad value here would otherwise reach
    a completer during `create_widget`.
    """
    if config is None:
        return []
    try:
        stored = config.get(CONFIG_KEY, [])
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not read %s", CONFIG_KEY, exc_info=True)
        return []
    if not isinstance(stored, list):
        logger.warning("%s is %s, not a list; ignoring it",
                       CONFIG_KEY, type(stored).__name__)
        return []
    if not all(isinstance(entry, str) for entry in stored):
        logger.warning("%s holds non-string entries; ignoring it", CONFIG_KEY)
        return []
    return stored[:HISTORY_CAP]


def save_history(config, history) -> None:
    if config is None:
        return
    try:
        config.set(CONFIG_KEY, list(history)[:HISTORY_CAP])
        config.save()
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not save %s", CONFIG_KEY, exc_info=True)
