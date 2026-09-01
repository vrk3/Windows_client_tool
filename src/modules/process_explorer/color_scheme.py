"""Row colours for the process tree, following Process Explorer's scheme.

Process Explorer tints every row by category, and the tint is most of what
makes a list of 270 processes readable at a glance. The categories, and
where each fact comes from:

| Colour | Meaning | Source |
|---|---|---|
| green | started within the highlight window | the collector's diff |
| red | exited within the highlight window | the collector's diff |
| grey | suspended | threads but no cycles, from the syscall |
| cyan | immersive (packaged/Store app) | `GetPackageFamilyName` |
| purple | image looks packed | section entropy -- a GUESS |
| yellow | .NET runtime loaded | loaded modules |
| pink | hosts a service | the service pid set |
| light blue | session 0 (a Windows process) | the syscall |
| blue | runs as us | the token, via the snapshot |

**The order matters and is not arbitrary.** A row can be several of these
at once -- a suspended .NET service owned by us is all four -- so the
question every row asks is "which one fact do I most need to know about
this process". Transience wins first: that a process just appeared or just
died is the most perishable thing about it and the reason the eye is
drawn there at all. Then state (suspended), then what KIND of image it is,
then whose it is.

`is_packed` is a heuristic and the only entry here that can be wrong about
a healthy process -- it flags OneNote on this machine. It sits below the
factual categories deliberately, so a .NET process that merely has
compressed resources still reads as .NET.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtGui import QColor

from modules.process_explorer.process_node import ProcessNode


class ProcessColor:
    NEW       = QColor(144, 238, 144)   # light green
    DELETED   = QColor(255, 160, 160)   # light red
    SUSPENDED = QColor(200, 200, 200)   # grey
    IMMERSIVE = QColor(175, 238, 238)   # pale cyan
    PACKED    = QColor(216, 191, 216)   # light purple
    DOTNET    = QColor(255, 255, 153)   # yellow
    SERVICE   = QColor(255, 182, 193)   # pink
    SYSTEM    = QColor(173, 216, 230)   # light blue
    OWN       = QColor(176, 196, 222)   # steel blue
    DEFAULT   = QColor(0, 0, 0, 0)      # transparent = default palette
    # The category colours above are light pastels; on the app's dark theme
    # the default light text is unreadable on them, so coloured rows use
    # dark text.
    TEXT_ON_COLOR = QColor(20, 20, 20)  # readable on every pastel above


#: (attribute, colour, label), in the order they are tested. The labels are
#: the legend, so the pane can explain itself rather than making someone
#: guess what pink means.
CATEGORIES: List[Tuple[str, QColor, str]] = [
    ("is_new",       ProcessColor.NEW,       "Started just now"),
    ("is_deleted",   ProcessColor.DELETED,   "Exited just now"),
    ("is_suspended", ProcessColor.SUSPENDED, "Suspended"),
    ("is_immersive", ProcessColor.IMMERSIVE, "Packaged (immersive)"),
    ("is_dotnet",    ProcessColor.DOTNET,    ".NET"),
    ("is_service",   ProcessColor.SERVICE,   "Hosts a service"),
    ("is_system",    ProcessColor.SYSTEM,    "Windows process"),
    # Below every factual category, because it is the only entry here that
    # can be WRONG about a healthy process. Above "your process" so that
    # the case worth seeing still shows: an unrecognised binary that is
    # not a service, not .NET, not packaged and not a Windows process.
    ("is_packed",    ProcessColor.PACKED,    "Image looks packed"),
    ("is_own",       ProcessColor.OWN,       "Your process"),
]


def category_of(node: ProcessNode) -> Optional[Tuple[str, QColor, str]]:
    """The one category this row is shown as, or `None` for an ordinary row."""
    for attribute, colour, label in CATEGORIES:
        if getattr(node, attribute, False):
            return attribute, colour, label
    return None


def get_row_color(node: ProcessNode) -> QColor:
    """Background colour for a process row."""
    found = category_of(node)
    return found[1] if found is not None else ProcessColor.DEFAULT


def get_row_text_color(node: ProcessNode) -> QColor:
    """Text colour for a process row.

    Rows with a pastel background need dark text; ordinary rows return
    transparent so the palette decides.
    """
    if get_row_color(node).alpha() > 0:
        return ProcessColor.TEXT_ON_COLOR
    return ProcessColor.DEFAULT


def describe(node: ProcessNode) -> str:
    """Every category the row qualifies for, not only the one it is shown
    as -- the tooltip, so a colour is never the only way to learn a fact.

    A row shows one colour but can be four things at once, and the three it
    is not showing are exactly the ones nobody would otherwise discover.
    """
    hits = [label for attribute, _colour, label in CATEGORIES
            if getattr(node, attribute, False)]
    if node.is_packed and node.packed_entropy is not None:
        hits = [f"{label} (entropy {node.packed_entropy:.2f} — a heuristic, "
                f"not a verdict)" if label.startswith("Image looks") else label
                for label in hits]
    return " · ".join(hits)
