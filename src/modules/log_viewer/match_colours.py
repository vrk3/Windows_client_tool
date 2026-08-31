"""The two colours painted INSIDE a message, and the user's choice of them.

The delegate colours exactly two things within the message text: what the
Filter and Find boxes are looking for, and the error codes that mean the line
failed. Both are a text colour and never a background -- the row already
carries a severity tint, and a block behind the match would fight it.

Only those two are choosable here. Every other colour on a row (severity,
component, a highlight rule) is a background and already has its own editor.

An unset colour is stored as ABSENT rather than as its current value: writing
today's dark-theme violet into the config would freeze it there, and the light
theme would then paint a 1.9:1 smear. Absent means "follow the theme", which
is what `semantic()` is for.

Qt-free, like the parser and the reader beside it.
"""
import logging
from typing import Dict

from core.semantic_colors import semantic

from .palette import is_valid_hex_colour

logger = logging.getLogger(__name__)

CONFIG_KEY = "log_viewer.match_colours"

#: The meanings the message delegate actually paints. Anything else would put
#: a swatch in the dialog for a colour nothing reads.
MEANINGS = ("match", "error")

#: What each one is called in the dialog.
LABELS = {
    "match": "Filter and Find matches",
    "error": "Failing error codes",
}


def default_colour(meaning: str) -> str:
    """The themed colour for `meaning` -- what an unset override falls back
    to, resolved at call time so a theme change is followed."""
    return semantic(meaning)


def _clean(mapping) -> Dict[str, str]:
    """Only the meanings we paint, only in a shape that is safe to paint.

    A colour ends up inside `paint`, a reimplemented Qt virtual, where an
    exception is routed to sys.excepthook and then qFatal(): it cannot be
    caught and the process dies. So a malformed value is dropped here, at
    every door, rather than trusted because it came from our own config.
    """
    if not isinstance(mapping, dict):
        return {}
    out = {}
    for meaning in MEANINGS:
        value = mapping.get(meaning)
        if value is None:
            continue
        if is_valid_hex_colour(value):
            out[meaning] = value
        else:
            logger.warning("Ignoring an unusable %s colour: %r",
                           meaning, value)
    return out


def load_colours(config) -> Dict[str, str]:
    """The user's overrides. Missing, malformed and unknown entries are
    dropped -- one bad hand-edit must not cost the whole setting."""
    return _clean(config.get(CONFIG_KEY, {}))


def save_colours(config, colours) -> None:
    """Persist the overrides. An empty mapping means "follow the theme"."""
    config.set(CONFIG_KEY, _clean(colours))
    config.save()
