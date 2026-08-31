"""An investigation, saved.

Which logs were open, every filter axis, the time range, folding and the
column choice -- in one small file. Coming back to a piece of work tomorrow
otherwise means rebuilding it from memory.

Three rules, each of which exists because the alternative is a quiet lie:

* **Every axis is written.** One missing field and the view you reopen is not
  the view you saved, with nothing to say so.
* **Missing logs are named, not skipped.** A view whose sources have rolled
  away must say which, rather than opening a smaller version of itself.
* **A file from a newer version is refused outright.** Half-applying
  something we do not understand produces a view that is neither the saved
  one nor the current one, and blames neither.

No Qt.
"""
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Bumped when a field changes meaning. A file claiming a HIGHER version is
#: refused; a lower one loads, with anything it lacks taking its default.
VERSION = 1


@dataclass
class View:
    """Everything needed to put the pane back the way it was."""
    sources: List[str] = field(default_factory=list)
    needle: str = ""
    exclude: str = ""
    regex: bool = False
    levels: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    thread: str = ""
    log: str = ""
    time_from: str = ""
    time_to: str = ""
    fold: bool = True
    hidden_columns: List[str] = field(default_factory=list)

    def missing(self) -> list:
        """Sources that are no longer on disk, in the order they were saved.

        A log rolls away between sessions; opening the rest without saying
        which are gone would present a partial investigation as a whole one.
        """
        return [path for path in self.sources if not os.path.exists(path)]


def save_view(path: str, view: View) -> str:
    """Write `view` to `path`. Returns a problem, or ""."""
    stored = asdict(view)
    stored["version"] = VERSION
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, indent=2)
    except OSError as problem:
        logger.warning("Could not save the view to %s", path, exc_info=True)
        return f"could not write {os.path.basename(path)}: {problem}"
    return ""


def load_view(path: str):
    """`(View, problem)`. Exactly one of the two is meaningful."""
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
    except OSError as problem:
        return None, f"could not read {os.path.basename(path)}: {problem}"
    except json.JSONDecodeError:
        return None, f"{os.path.basename(path)} is not a saved view"

    if not isinstance(stored, dict):
        return None, f"{os.path.basename(path)} is not a saved view"

    version = stored.get("version", VERSION)
    if isinstance(version, int) and version > VERSION:
        return None, (f"{os.path.basename(path)} was written by a newer "
                      f"version of this tool (format {version}, this "
                      f"understands {VERSION})")

    known = {name for name in View().__dict__}
    fields = {name: value for name, value in stored.items() if name in known}
    try:
        return View(**fields), ""
    except TypeError as problem:
        return None, f"{os.path.basename(path)} is not a saved view: {problem}"
