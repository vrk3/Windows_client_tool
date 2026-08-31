r"""Named filters worth keeping.

Knowing what to grep for is the expensive part of reading a servicing log,
and it should not live in one person's head.

**Every shipped preset below was run against the real log it targets and its
hit count recorded in the plan.** A preset that matches nothing is worse than
no preset: it answers "there is no such problem here" when it means "I was
written wrong", and nobody checks a filter that came with the tool.

No Qt.
"""
import logging
from dataclasses import dataclass, field, asdict
from typing import Tuple

logger = logging.getLogger(__name__)

CONFIG_KEY = "log_viewer.presets"


@dataclass(frozen=True)
class Preset:
    """A whole view: every filter axis it names, and nothing it does not."""
    name: str
    needle: str = ""
    exclude: str = ""
    levels: Tuple[str, ...] = field(default_factory=tuple)
    regex: bool = False

    def as_dict(self) -> dict:
        stored = asdict(self)
        stored["levels"] = list(self.levels)
        return stored

    @staticmethod
    def from_dict(stored):
        """A `Preset` from stored data, or None if it is not one.

        A preset with no name is dropped rather than shown as a blank row in
        the menu: config files get hand-edited, and this is read while the
        pane is being built.
        """
        if not isinstance(stored, dict):
            return None
        name = stored.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        levels = stored.get("levels") or []
        if not isinstance(levels, (list, tuple)):
            levels = []
        return Preset(
            name=name,
            needle=str(stored.get("needle") or ""),
            exclude=str(stored.get("exclude") or ""),
            levels=tuple(str(level) for level in levels),
            regex=bool(stored.get("regex")),
        )


#: Shipped with the tool. Each one is checked against the real log it targets
#: before it is added; the counts are in the plan beside this task.
BUILT_IN = (
    Preset(name="Errors only", levels=("Error",)),
    Preset(name="Errors and warnings", levels=("Error", "Warning")),
    # The failing-code prefix: 0x8 covers the whole failure range, and the
    # success codes CBS floods the log with all begin 0x0.
    Preset(name="Failing result codes", needle="0x8"),
    # Component store damage, in the words Windows actually writes.
    Preset(name="Store damage", needle="STATUS_SXS", regex=False),
    # CBS is mostly these two shapes; hiding them is what makes the rest
    # readable.
    Preset(name="Hide servicing boilerplate",
           exclude="Appl: detect|Plan: Package|Planning child", regex=True),
    # Windows Setup writes its phase boundaries as banner lines.
    Preset(name="Setup phase boundaries", needle="phase"),
)


def load_presets(config) -> list:
    """The user's saved presets. Malformed entries are dropped one by one,
    so one bad row does not cost the rest."""
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
    loaded = [Preset.from_dict(row) for row in stored]
    return [preset for preset in loaded if preset is not None]


def save_presets(config, presets) -> None:
    if config is None:
        return
    try:
        config.set(CONFIG_KEY, [preset.as_dict() for preset in presets])
        config.save()
    except Exception:                                       # noqa: BLE001
        logger.warning("Could not save %s", CONFIG_KEY, exc_info=True)
