r"""How the pane was arranged last time.

Deliberately NOT column widths. The narrow columns are `ResizeToContents` and
cannot be dragged, and that auto-sizing is what stopped the Source column
rendering every CBS archive as "CbsPersist_20…" -- they differ only in the
timestamp at the END of the name, so a clipped one is indistinguishable from
any other. Making the columns draggable in order to make them memorable would
trade a real fix for a preference. Column visibility belongs to the column
chooser, which is its own task.

What is adjustable, and so worth keeping: the splitter between the table and
the detail pane, and the two checkboxes that change what is shown.

Everything here is validated on the way IN, because it is applied while the
widget is being built -- a bad value would take the pane down on open rather
than misbehave later. No Qt.
"""
import logging

logger = logging.getLogger(__name__)

CONFIG_KEY = "log_viewer.layout"

#: The splitter has exactly two panes: the table and the detail view.
_SPLITTER_PANES = 2


def load_layout(config) -> dict:
    """The stored layout, with anything malformed dropped.

    Each key is validated on its own so that one bad value does not discard
    the rest: a hand-edited splitter should not cost you the fold setting.
    """
    if config is None:
        return {}
    try:
        stored = config.get(CONFIG_KEY, {})
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not read %s", CONFIG_KEY, exc_info=True)
        return {}
    if not isinstance(stored, dict):
        logger.warning("%s is %s, not a mapping; ignoring it",
                       CONFIG_KEY, type(stored).__name__)
        return {}

    layout = {}
    for key in ("fold", "regex"):
        if isinstance(stored.get(key), bool):
            layout[key] = stored[key]

    sizes = stored.get("splitter")
    if (isinstance(sizes, list)
            and len(sizes) == _SPLITTER_PANES
            and all(isinstance(size, int) and size >= 0 for size in sizes)):
        layout["splitter"] = list(sizes)
    elif sizes is not None:
        logger.warning("%s.splitter is not %d sizes; ignoring it",
                       CONFIG_KEY, _SPLITTER_PANES)
    return layout


def save_layout(config, layout) -> None:
    if config is None:
        return
    try:
        config.set(CONFIG_KEY, dict(layout))
        config.save()
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not save %s", CONFIG_KEY, exc_info=True)
