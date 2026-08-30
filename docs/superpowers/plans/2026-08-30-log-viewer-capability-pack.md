# Log Viewer Capability Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Log Viewer a thread filter, a time-range filter, regex in Find and Filter, export/copy, an Error Lookup dialog, and three colour systems that share a row without hiding one another.

**Architecture:** All decision logic (which colour, which rows, what text) goes into new Qt-free modules under `src/modules/log_viewer/` so it is testable headless, following the split the parser, reader, `scan/`, `store/` and `gpresult/` already use. Only painting and dialogs import Qt. `LogModel.set_filter` gains three axes following its existing optional-argument pattern; nothing upstream of `LogEntry` changes.

**Tech Stack:** Python 3.12, PyQt6, pytest. Standard library only — `colorsys`, `csv`, `re`, `dataclasses`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-log-viewer-capability-pack-design.md`

## Global Constraints

- **No Qt imports** in `highlight.py`, `palette.py`, `log_export.py`. Qt is allowed only in `log_delegate.py`, `error_lookup_dialog.py`, `log_model.py`, `log_viewer_module.py`.
- **The Log Viewer is not theme-exempt.** `tests/test_theme_light_coverage.py` has `THEME_EXEMPT = {"TreeSize"}` and measures rendered luminance, so it sees colours painted by a delegate. Every colour ships with a light variant.
- **Contrast floor is 4.5:1**, foreground against its own background, asserted by a test that computes the ratio — never by eye.
- **Theme state comes from `core.semantic_colors.current_theme()`**, which `ThemeManager` already keeps in sync (`theme_manager.py:7` imports `set_theme as _set_semantic_theme`). Do not add a second source of theme truth.
- **Config API is `ConfigManager.get(key, default)` / `.set(key, value)` / `.save()`** (`src/core/config_manager.py:76,86,105`).
- **An invalid regex is a typo, not a failure.** It matches nothing, raises nothing, opens no dialog — mirroring `LogSearchProvider.search`, which already does this.
- **Silent exception swallowing is forbidden** (CLAUDE.md). Log with `logger.warning()`.
- **Use the Write tool, not a bash heredoc, for any Python containing backslashes.** Windows paths in test fixtures guarantee them; a heredoc has corrupted escapes in this repo twice.
- Run the suite with `.\.venv\Scripts\python.exe -m pytest`. Qt probes must go through the PowerShell tool, and its working directory is `source\repos`, not the repo — use absolute paths.

---

### Task 1: Component and severity palette

**Files:**
- Create: `src/modules/log_viewer/palette.py`
- Test: `tests/test_log_palette.py`

**Interfaces:**
- Consumes: `core.semantic_colors.current_theme()`, `core.semantic_colors.PANE_BACKGROUND`
- Produces:
  - `component_colour(name: str, theme: str = None) -> tuple[str, str]` returning `(background_hex, foreground_hex)`
  - `severity_row_colour(level: str, theme: str = None) -> Optional[tuple[str, str]]`, `None` for levels with no colour
  - `COMPONENT_SLOTS: int = 16`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_palette.py`:

```python
"""Colours the log viewer paints, in whichever theme is in force.

`ROW_COLOURS` used to be four hex values chosen against the dark sheet by
their own comment. The Log Viewer is NOT in test_theme_light_coverage's
THEME_EXEMPT set, so a colour frozen for one theme is a defect in the other.
"""
import pytest

from modules.log_viewer import palette


def _luminance(hex_colour):
    value = hex_colour.lstrip("#")
    parts = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def channel(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(p) for p in parts)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(a, b):
    first, second = _luminance(a), _luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_component_colour_is_readable_on_itself(theme):
    for slot in range(palette.COMPONENT_SLOTS):
        background, foreground = palette.component_colour(f"c{slot}", theme)
        ratio = _contrast(foreground, background)
        assert ratio >= 4.5, (
            f"{theme}/slot {slot}: {foreground} on {background} "
            f"is {ratio:.2f}:1")


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_severity_colour_is_readable_on_itself(theme):
    for level in ("Error", "Warning"):
        background, foreground = palette.severity_row_colour(level, theme)
        ratio = _contrast(foreground, background)
        assert ratio >= 4.5, (
            f"{theme}/{level}: {foreground} on {background} is {ratio:.2f}:1")


def test_a_component_keeps_its_colour_across_calls_and_logs():
    """CBS must look the same in every log and after a restart, so the slot
    comes from the name, never from the order components were discovered."""
    first = palette.component_colour("CBS", "dark")
    assert palette.component_colour("CBS", "dark") == first
    assert palette.component_colour("CSI", "dark") != first


def test_an_unknown_component_still_gets_a_colour():
    background, foreground = palette.component_colour("NeverSeenBefore",
                                                      "dark")
    assert background.startswith("#") and foreground.startswith("#")


def test_a_level_with_no_colour_says_so_rather_than_guessing():
    assert palette.severity_row_colour("Info", "dark") is None


def test_the_theme_defaults_to_whatever_is_in_force():
    from core import semantic_colors

    semantic_colors.set_theme("light")
    try:
        assert palette.component_colour("CBS") == \
            palette.component_colour("CBS", "light")
    finally:
        semantic_colors.set_theme("dark")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_palette.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.log_viewer.palette'`

- [ ] **Step 3: Write minimal implementation**

Create `src/modules/log_viewer/palette.py`:

```python
"""Colours the log viewer paints, resolved for the theme in force.

Three colour systems share a row and must not hide one another: severity owns
the row background, a highlight rule overrides it, and the component tint owns
the Component column and nothing else.

Component colours are GENERATED from evenly spaced hues rather than written
out as 64 hand-picked hex values. Hand-picking would be guesswork checked by
eye; this is deterministic, and `tests/test_log_palette.py` computes the
contrast ratio of all 32 pairs instead of trusting a comment.

The slot comes from a hash of the component name, not from the order names
were discovered, so CBS is the same colour in every log and after a restart,
and a new component appearing does not reshuffle the others. The measured
maximum on this machine is 15 distinct components, so a collision is a
cosmetic repeat rather than a practical concern.

No Qt here: the model wraps these in QColor. That is what lets the contrast
be asserted with no display.
"""
import colorsys
from typing import Optional, Tuple

from core.semantic_colors import current_theme

#: Enough for the 15 distinct components measured across this machine's logs.
COMPONENT_SLOTS = 16

#: (saturation, lightness) for the tint and for the text on it, per theme.
#: Tuned until every one of the 32 pairs clears 4.5:1; the test is what says
#: whether a change to these still does.
_COMPONENT_TONES = {
    "dark": ((0.45, 0.20), (0.70, 0.80)),
    "light": ((0.50, 0.88), (0.85, 0.22)),
}

#: Severity owns the whole row, so these are row backgrounds with the text
#: that sits on them -- a different job from `semantic_colors`, which colours
#: a word rather than a band.
SEVERITY_ROW_COLOURS = {
    "dark": {
        "Error": ("#5c1a1a", "#ff9999"),
        "Warning": ("#4a3c14", "#f5d576"),
    },
    "light": {
        "Error": ("#ffe3e0", "#8c1d18"),
        "Warning": ("#fff3d6", "#6b4400"),
    },
}


def _hex(hue_index: int, saturation: float, lightness: float) -> str:
    hue = (hue_index % COMPONENT_SLOTS) / COMPONENT_SLOTS
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(
        int(red * 255), int(green * 255), int(blue * 255))


def _theme(theme: Optional[str]) -> str:
    name = theme or current_theme()
    return name if name in _COMPONENT_TONES else "dark"


def slot_for(name: str) -> int:
    """A stable slot for `name`.

    `hash()` is salted per process since Python 3.3, so it would give a
    component a different colour on every launch. A sum of the bytes is
    stable, and for a dozen short names it spreads them well enough.
    """
    return sum(name.encode("utf-8")) % COMPONENT_SLOTS


def component_colour(name: str, theme: str = None) -> Tuple[str, str]:
    """`(background, foreground)` for a component's cell."""
    tint, text = _COMPONENT_TONES[_theme(theme)]
    slot = slot_for(name)
    return _hex(slot, *tint), _hex(slot, *text)


def severity_row_colour(level: str, theme: str = None):
    """`(background, foreground)` for a row, or None when the level has no
    colour of its own -- Info and Debug are deliberately plain, because a log
    where every row is coloured is a log with no colour."""
    return SEVERITY_ROW_COLOURS[_theme(theme)].get(level)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_palette.py -q`
Expected: PASS, 8 tests.

If a contrast assertion fails, adjust the lightness values in
`_COMPONENT_TONES` (raise the gap between tint and text) and re-run. Do not
lower the 4.5 floor.

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_palette.py src/modules/log_viewer/palette.py
git commit -m "feat(log viewer): theme-aware component and severity colours"
```

---

### Task 2: The model paints from the palette

**Files:**
- Modify: `src/modules/log_viewer/log_model.py` (remove `ROW_COLOURS`, rewrite the `BackgroundRole`/`ForegroundRole` branches of `data()`)
- Test: `tests/test_log_model.py` (add)

**Interfaces:**
- Consumes: `palette.component_colour`, `palette.severity_row_colour` (Task 1)
- Produces: the Component column's background is the component tint on every row, whatever the row background is.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_log_model.py`:

```python
def test_severity_colours_follow_the_theme(qapp):
    """The old ROW_COLOURS were dark-sheet values by their own comment, and
    this pane is not in THEME_EXEMPT."""
    from core import semantic_colors
    from PyQt6.QtCore import Qt

    model = _model([_entry("boom", level="Error")])
    index = model.index(0, MESSAGE)
    semantic_colors.set_theme("dark")
    dark = model.data(index, Qt.ItemDataRole.BackgroundRole)
    semantic_colors.set_theme("light")
    try:
        light = model.data(index, Qt.ItemDataRole.BackgroundRole)
    finally:
        semantic_colors.set_theme("dark")
    assert dark != light


def test_the_component_column_keeps_its_tint_on_an_error_row(qapp):
    """Territory, not priority: if severity won the whole row, every Error
    row would lose its component colour."""
    from PyQt6.QtCore import Qt
    from modules.log_viewer import palette

    model = _model([_entry("boom", level="Error", source="CBS")])
    cell = model.data(model.index(0, COMPONENT), Qt.ItemDataRole.BackgroundRole)
    expected, _foreground = palette.component_colour("CBS")
    assert cell.name() == expected


def test_a_blank_component_gets_no_tint(qapp):
    from PyQt6.QtCore import Qt

    model = _model([_entry("x", source="")])
    assert model.data(model.index(0, COMPONENT),
                      Qt.ItemDataRole.BackgroundRole) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py -q -k "theme or tint"`
Expected: FAIL — the component cell returns the severity colour, and both themes return the same value.

- [ ] **Step 3: Write minimal implementation**

In `log_model.py`, delete the `ROW_COLOURS` constant and its comment, add
`from .palette import component_colour, severity_row_colour`, and replace the
two colour branches of `data()` with:

```python
        elif role == Qt.ItemDataRole.BackgroundRole:
            # The Component column is the one place the row background does
            # not apply: its tint wins there, over severity and over a
            # highlight rule. Otherwise every Error row would lose the
            # component colour, which is the whole point of the column.
            if index.column() == COMPONENT and entry.source:
                return QColor(component_colour(entry.source)[0])
            colour = severity_row_colour(entry.level)
            return QColor(colour[0]) if colour else None
        elif role == Qt.ItemDataRole.ForegroundRole:
            if index.column() == COMPONENT and entry.source:
                return QColor(component_colour(entry.source)[1])
            colour = severity_row_colour(entry.level)
            return QColor(colour[1]) if colour else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py tests/test_log_palette.py -q`
Expected: PASS. Any existing test that imported `ROW_COLOURS` must be updated
to call `severity_row_colour` instead — grep for it first:
`grep -rn "ROW_COLOURS" src tests`

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_model.py tests/test_log_model.py
git commit -m "feat(log viewer): component tint owns the Component column"
```

---

### Task 3: Highlight rules

**Files:**
- Create: `src/modules/log_viewer/highlight.py`
- Test: `tests/test_log_highlight.py`

**Interfaces:**
- Produces:
  - `HighlightRule(pattern: str, colour: str, regex: bool = False, enabled: bool = True)` — a frozen dataclass
  - `matching_rule(rules, entry) -> Optional[HighlightRule]`
  - `load_rules(config) -> list[HighlightRule]`
  - `save_rules(config, rules) -> None`
  - `CONFIG_KEY = "log_viewer.highlight_rules"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_highlight.py`:

```python
"""User-defined highlight rules: the one thing allowed to override severity
on a row's background, because the user typed it deliberately."""
from datetime import datetime

from core.types import LogEntry
from modules.log_viewer.highlight import (CONFIG_KEY, HighlightRule,
                                          load_rules, matching_rule,
                                          save_rules)


class _StubConfig:
    """ConfigManager's get/set/save, and nothing else."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = False

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saved = True


def _entry(message, level="Info", source="CBS"):
    return LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0), source=source,
                    level=level, message=message, raw={})


def test_the_first_matching_rule_wins():
    rules = [HighlightRule("turbostack", "#00ff00"),
             HighlightRule("version", "#ff0000")]
    assert matching_rule(rules, _entry("TurboStack version 10")).colour \
        == "#00ff00"


def test_matching_is_case_insensitive():
    rules = [HighlightRule("TURBOSTACK", "#00ff00")]
    assert matching_rule(rules, _entry("turbostack loaded")) is not None


def test_a_disabled_rule_is_skipped_without_being_forgotten():
    rules = [HighlightRule("boom", "#00ff00", enabled=False),
             HighlightRule("boom", "#ff0000")]
    assert matching_rule(rules, _entry("boom")).colour == "#ff0000"


def test_a_rule_can_target_a_component_or_a_level():
    """The haystack is the row as the user sees it, matching the filter."""
    rules = [HighlightRule("CSI", "#00ff00")]
    assert matching_rule(rules, _entry("nothing here", source="CSI"))
    rules = [HighlightRule("Warning", "#00ff00")]
    assert matching_rule(rules, _entry("nothing", level="Warning"))


def test_an_invalid_regex_matches_nothing_and_does_not_raise():
    """A half-typed pattern is a typo, not a failure -- the same rule
    LogSearchProvider.search already follows."""
    rules = [HighlightRule("[unclosed", "#00ff00", regex=True)]
    assert matching_rule(rules, _entry("[unclosed")) is None


def test_a_regex_rule_matches_as_a_regex():
    rules = [HighlightRule(r"HRESULT = 0x8007[0-9a-f]{4}", "#00ff00",
                           regex=True)]
    assert matching_rule(rules, _entry("failed [HRESULT = 0x80070005]"))


def test_no_rules_means_no_match():
    assert matching_rule([], _entry("anything")) is None


def test_rules_round_trip_through_the_config():
    config = _StubConfig()
    rules = [HighlightRule("boom", "#ff0000", regex=True, enabled=False)]
    save_rules(config, rules)
    assert config.saved
    assert load_rules(config) == rules


def test_a_corrupt_rule_does_not_cost_the_user_the_others():
    config = _StubConfig({CONFIG_KEY: [
        {"pattern": "good", "colour": "#00ff00"},
        {"nonsense": True},
        "not even a dict",
    ]})
    assert [rule.pattern for rule in load_rules(config)] == ["good"]


def test_no_stored_rules_is_an_empty_list_not_a_crash():
    assert load_rules(_StubConfig()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_highlight.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.log_viewer.highlight'`

- [ ] **Step 3: Write minimal implementation**

Create `src/modules/log_viewer/highlight.py`:

```python
"""User-defined highlight rules -- CMTrace's Highlight, kept Qt-free.

A rule is the one thing allowed to override severity on a row's background:
the user typed it, so it outranks a colour the log chose for itself. The
Component column is unaffected either way; its tint owns that cell.

Rules are matched in order and the first match wins, so the order in the
editor is meaningful and visible rather than incidental.
"""
import logging
import re
from dataclasses import asdict, dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Global, not per file: "highlight my machine name" should apply to every
#: log that is opened, which is what the user asked for.
CONFIG_KEY = "log_viewer.highlight_rules"


@dataclass(frozen=True)
class HighlightRule:
    pattern: str
    colour: str                 # "#RRGGBB", chosen by the user
    regex: bool = False
    enabled: bool = True


def _haystack(entry) -> str:
    """The row as the user sees it, which is what LogModel._matches uses.

    A rule that could only see the message could not target a component,
    and "colour every CSI row" is one of the obvious things to want.
    """
    return f"{entry.message} {entry.level} {entry.source}"


def matching_rule(rules, entry) -> Optional[HighlightRule]:
    text = _haystack(entry)
    lowered = text.lower()
    for rule in rules or ():
        if not rule.enabled or not rule.pattern:
            continue
        if rule.regex:
            try:
                if re.search(rule.pattern, text, re.IGNORECASE):
                    return rule
            except re.error:
                # A half-typed pattern is a typo, not a failure. The editor
                # flags it; matching just declines.
                continue
        elif rule.pattern.lower() in lowered:
            return rule
    return None


def load_rules(config) -> List[HighlightRule]:
    stored = config.get(CONFIG_KEY, []) or []
    rules = []
    for item in stored:
        try:
            rules.append(HighlightRule(
                pattern=str(item["pattern"]),
                colour=str(item["colour"]),
                regex=bool(item.get("regex", False)),
                enabled=bool(item.get("enabled", True)),
            ))
        except (TypeError, KeyError, ValueError):
            # One hand-edited entry must not cost the user every rule.
            logger.warning("Skipping an unreadable highlight rule: %r", item)
    return rules


def save_rules(config, rules) -> None:
    config.set(CONFIG_KEY, [asdict(rule) for rule in rules])
    config.save()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_highlight.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_highlight.py src/modules/log_viewer/highlight.py
git commit -m "feat(log viewer): user-defined highlight rules"
```

---

### Task 4: The model honours highlight rules

**Files:**
- Modify: `src/modules/log_viewer/log_model.py`
- Test: `tests/test_log_model.py` (add)

**Interfaces:**
- Consumes: `highlight.matching_rule`, `highlight.HighlightRule` (Task 3); `palette.component_colour` (Task 1)
- Produces: `LogModel.set_highlight_rules(rules) -> None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_log_model.py`:

```python
def test_a_highlight_rule_beats_severity_on_the_row(qapp):
    from PyQt6.QtCore import Qt
    from modules.log_viewer.highlight import HighlightRule

    model = _model([_entry("boom", level="Error")])
    model.set_highlight_rules([HighlightRule("boom", "#00ff00")])
    colour = model.data(model.index(0, MESSAGE),
                        Qt.ItemDataRole.BackgroundRole)
    assert colour.name() == "#00ff00"


def test_a_highlight_rule_does_not_take_the_component_column(qapp):
    from PyQt6.QtCore import Qt
    from modules.log_viewer import palette
    from modules.log_viewer.highlight import HighlightRule

    model = _model([_entry("boom", source="CBS")])
    model.set_highlight_rules([HighlightRule("boom", "#00ff00")])
    cell = model.data(model.index(0, COMPONENT),
                      Qt.ItemDataRole.BackgroundRole)
    assert cell.name() == palette.component_colour("CBS")[0]


def test_setting_rules_repaints_without_losing_the_selection(qapp):
    """A reset clears the view's selection, and this pane already learned
    that lesson once with append()."""
    model = _model([_entry("one"), _entry("two")])
    seen = []
    model.dataChanged.connect(lambda *a: seen.append(a))
    model.set_highlight_rules([])
    assert seen, "the view was never told to repaint"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py -q -k highlight`
Expected: FAIL — `AttributeError: 'LogModel' object has no attribute 'set_highlight_rules'`

- [ ] **Step 3: Write minimal implementation**

In `log_model.py`, add `from .highlight import matching_rule` at the top,
`self._rules = []` in `__init__`, this method after `set_filter`:

```python
    def set_highlight_rules(self, rules) -> None:
        """Colouring only -- which rows are VISIBLE does not change, so this
        repaints rather than resetting. A reset would clear the selection,
        the same trap `append` documents."""
        self._rules = list(rules or [])
        if self._visible:
            top = self.index(0, 0)
            bottom = self.index(len(self._visible) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom,
                                  [Qt.ItemDataRole.BackgroundRole,
                                   Qt.ItemDataRole.ForegroundRole])
```

and change the `BackgroundRole` branch so a rule is consulted before severity:

```python
        elif role == Qt.ItemDataRole.BackgroundRole:
            if index.column() == COMPONENT and entry.source:
                return QColor(component_colour(entry.source)[0])
            rule = matching_rule(self._rules, entry)
            if rule is not None:
                return QColor(rule.colour)
            colour = severity_row_colour(entry.level)
            return QColor(colour[0]) if colour else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_model.py tests/test_log_model.py
git commit -m "feat(log viewer): highlight rules override severity on the row"
```

---

### Task 5: Thread, time-range and regex filtering

**Files:**
- Modify: `src/modules/log_viewer/log_model.py` (`set_filter`, `_matches`, add `threads()`, `time_span()`)
- Test: `tests/test_log_model.py` (add)

**Interfaces:**
- Produces:
  - `LogModel.set_filter(levels=None, needle=None, component=None, thread=None, time_from=None, time_to=None, regex=None)`
  - `LogModel.threads() -> list[tuple[str, int]]` ordered by count descending
  - `LogModel.time_span() -> tuple[datetime, datetime] | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_log_model.py`:

```python
def _at(when, message="x", thread="1"):
    return LogEntry(timestamp=when, source="CBS", level="Info",
                    message=message, raw={"thread": thread})


def test_filtering_by_thread(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0), thread="100"),
                    _at(datetime(2026, 8, 30, 12, 1), thread="200")])
    model.set_filter(thread="200")
    assert model.rowCount() == 1


def test_threads_are_offered_by_how_common_they_are(qapp):
    """DISM has 329 distinct thread ids, so the combo has to be ordered by
    something useful -- an alphabetical list of 329 numbers is not."""
    model = _model([_at(datetime(2026, 8, 30, 12, 0), thread="100"),
                    _at(datetime(2026, 8, 30, 12, 1), thread="200"),
                    _at(datetime(2026, 8, 30, 12, 2), thread="200")])
    assert model.threads() == [("200", 2), ("100", 1)]


def test_filtering_by_a_time_range_includes_both_ends(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0)),
                    _at(datetime(2026, 8, 30, 12, 5)),
                    _at(datetime(2026, 8, 30, 12, 9))])
    model.set_filter(time_from=datetime(2026, 8, 30, 12, 0),
                     time_to=datetime(2026, 8, 30, 12, 5))
    assert model.rowCount() == 2


def test_a_record_with_no_timestamp_survives_a_time_filter(qapp):
    """Losing a record is the one outcome a log viewer must never produce,
    and a continuation line has no timestamp of its own."""
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME

    model = _model([_at(UNKNOWN_TIME)])
    model.set_filter(time_from=datetime(2026, 8, 30, 12, 0))
    assert model.rowCount() == 1


def test_the_time_span_is_the_first_and_last_real_timestamp(qapp):
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME

    model = _model([_at(UNKNOWN_TIME),
                    _at(datetime(2026, 8, 30, 12, 0)),
                    _at(datetime(2026, 8, 30, 12, 9))])
    assert model.time_span() == (datetime(2026, 8, 30, 12, 0),
                                 datetime(2026, 8, 30, 12, 9))


def test_the_time_span_of_an_empty_log_is_none(qapp):
    assert _model([]).time_span() is None


def test_filtering_by_a_regular_expression(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0), "HRESULT = 0x80070005"),
                    _at(datetime(2026, 8, 30, 12, 1), "all fine")])
    model.set_filter(needle=r"0x8007[0-9a-f]{4}", regex=True)
    assert model.rowCount() == 1


def test_an_invalid_regex_matches_nothing_and_does_not_raise(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0), "anything")])
    model.set_filter(needle="[unclosed", regex=True)
    assert model.rowCount() == 0


def test_the_regex_is_compiled_once_per_filter_not_once_per_row(qapp):
    import re

    calls = []
    original = re.compile

    def counting(pattern, *args, **kwargs):
        calls.append(pattern)
        return original(pattern, *args, **kwargs)

    model = _model([_at(datetime(2026, 8, 30, 12, i)) for i in range(20)])
    re.compile = counting
    try:
        model.set_filter(needle="x", regex=True)
    finally:
        re.compile = original
    assert len(calls) == 1, f"compiled {len(calls)} times for 20 rows"


def test_find_honours_the_regex_flag_too(qapp):
    """One checkbox governs Find AND Filter, so find() cannot stay
    substring-only while the filter understands patterns."""
    model = _model([_at(datetime(2026, 8, 30, 12, 0), "all fine"),
                    _at(datetime(2026, 8, 30, 12, 1), "HRESULT = 0x80070005")])
    model.set_filter(regex=True)
    assert model.find(r"0x8007[0-9a-f]{4}", start_row=0) == 1


def test_find_with_an_invalid_pattern_finds_nothing(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0), "anything")])
    model.set_filter(regex=True)
    assert model.find("[unclosed", start_row=0) == -1


def test_the_filter_axes_combine(qapp):
    model = _model([_at(datetime(2026, 8, 30, 12, 0), "keep", thread="100"),
                    _at(datetime(2026, 8, 30, 12, 1), "keep", thread="200"),
                    _at(datetime(2026, 8, 30, 13, 0), "keep", thread="100")])
    model.set_filter(thread="100", needle="keep",
                     time_to=datetime(2026, 8, 30, 12, 30))
    assert model.rowCount() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py -q -k "thread or time or regex"`
Expected: FAIL — `TypeError: set_filter() got an unexpected keyword argument 'thread'`

- [ ] **Step 3: Write minimal implementation**

In `log_model.py`, add `import re` and `from .cmtrace_parser import UNKNOWN_TIME` (already imported), extend `__init__` with:

```python
        self._thread = ""
        self._time_from = None
        self._time_to = None
        self._regex = False
        self._matcher = None            # compiled once per set_filter
```

Replace `set_filter` and `_matches`:

```python
    def set_filter(self, levels=None, needle: str = None,
                   component: str = None, thread: str = None,
                   time_from=None, time_to=None, regex: bool = None) -> None:
        """Each argument left as None keeps that axis unchanged.

        `time_from`/`time_to` take the sentinel `False` to mean "clear this
        bound", since None already means "leave it alone" and a range has to
        be removable.
        """
        if levels is not None:
            self._levels = set(levels)
        if needle is not None:
            self._needle = needle.lower()
            self._pattern = needle
        if component is not None:
            self._component = component
        if thread is not None:
            self._thread = thread
        if time_from is not None:
            self._time_from = None if time_from is False else time_from
        if time_to is not None:
            self._time_to = None if time_to is False else time_to
        if regex is not None:
            self._regex = bool(regex)

        # Compiled ONCE here, never inside _matches: at 134,527 records a
        # per-row compile is 134,527 compiles per keystroke.
        self._matcher = None
        if self._regex and getattr(self, "_pattern", ""):
            try:
                self._matcher = re.compile(self._pattern, re.IGNORECASE)
            except re.error:
                # A half-typed pattern is a typo. Nothing matches until it
                # is finished; the pane says so in the status bar.
                self._matcher = False

        self.beginResetModel()
        self._reindex()
        self.endResetModel()

    def _matches(self, entry) -> bool:
        if self._levels and entry.level not in self._levels:
            return False
        if self._component and entry.source != self._component:
            return False
        if self._thread and entry.raw.get("thread", "") != self._thread:
            return False
        # A record with no timestamp of its own -- a continuation line -- is
        # never removed by a time filter. Losing a record is the one outcome
        # a log viewer must not produce.
        if entry.timestamp != UNKNOWN_TIME:
            if self._time_from and entry.timestamp < self._time_from:
                return False
            if self._time_to and entry.timestamp > self._time_to:
                return False
        if self._needle:
            # The whole ROW as the user sees it, not just the message.
            haystack = f"{entry.message} {entry.level} {entry.source}"
            if self._matcher is False:
                return False
            if self._matcher is not None:
                if not self._matcher.search(haystack):
                    return False
            elif self._needle not in haystack.lower():
                return False
        return True

    def threads(self) -> list:
        """`(thread, count)` ordered by count descending.

        DISM carries 329 distinct thread ids; an alphabetical list of 329
        numbers is not a control anyone can use.
        """
        counts = {}
        for entry in self._entries:
            thread = entry.raw.get("thread", "")
            if thread:
                counts[thread] = counts.get(thread, 0) + 1
        return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))

    def time_span(self):
        """`(first, last)` real timestamp, or None. Used to prefill the range
        boxes so they open on the whole log rather than on the year 1752."""
        stamps = [e.timestamp for e in self._entries
                  if e.timestamp != UNKNOWN_TIME]
        if not stamps:
            return None
        return min(stamps), max(stamps)
```

Also add `self._pattern = ""` beside `self._needle = ""` in `__init__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_model.py -q`
Expected: PASS, including the pre-existing filter tests.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_model.py tests/test_log_model.py
git commit -m "feat(log viewer): filter by thread, time range and regex"
```

---

### Task 6: Export writers

**Files:**
- Create: `src/modules/log_viewer/log_export.py`
- Test: `tests/test_log_export.py`

**Interfaces:**
- Produces: `as_text(entries, header: bool = True) -> str`, `as_csv(entries) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_export.py`:

```python
"""Getting the filtered rows out.

Both writers emit the PARSED view, not the original bytes: keeping every
original line would roughly double the model's footprint at its 200,000
cap, and reconstructing one from raw["line"] is unreliable once the file is
tail-capped, followed, or read with a rolled .lo_ sibling. The text writer
says so in its header so nobody mistakes it for a copy of the file.
"""
import csv
import io
from datetime import datetime

from core.types import LogEntry
from modules.log_viewer.log_export import as_csv, as_text


def _entry(message, level="Info", source="CBS", thread="42"):
    return LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0), source=source,
                    level=level, message=message, raw={"thread": thread})


def test_text_carries_the_fields_of_each_row():
    out = as_text([_entry("something happened")])
    assert "2026-08-30 12:00:00" in out
    assert "Info" in out and "CBS" in out and "something happened" in out


def test_the_text_header_says_this_is_the_parsed_view():
    out = as_text([_entry("x")])
    assert out.splitlines()[0].startswith("#")
    assert "parsed" in out.splitlines()[0].lower()


def test_the_clipboard_form_carries_no_header():
    out = as_text([_entry("x")], header=False)
    assert not out.startswith("#")


def test_csv_survives_a_comma_a_quote_and_a_newline():
    nasty = 'a, b "quoted" and\na second line'
    parsed = list(csv.reader(io.StringIO(as_csv([_entry(nasty)]))))
    assert parsed[0] == ["Time", "Severity", "Component", "Thread", "Message"]
    assert parsed[1][4] == nasty


def test_an_unknown_timestamp_exports_blank_rather_than_year_one():
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME

    entry = LogEntry(timestamp=UNKNOWN_TIME, source="", level="Info",
                     message="x", raw={})
    assert "0001-01-01" not in as_text([entry])
    assert "0001-01-01" not in as_csv([entry])


def test_exporting_nothing_is_not_a_crash():
    assert as_csv([]).strip().startswith("Time")
    assert isinstance(as_text([], header=False), str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.log_viewer.log_export'`

- [ ] **Step 3: Write minimal implementation**

Create `src/modules/log_viewer/log_export.py`:

```python
"""Writers that get the filtered rows out of the viewer.

Both emit the PARSED view -- time, severity, component, thread, message --
rather than the original bytes. Keeping every original line would roughly
double the model's footprint at its 200,000-record cap, and rebuilding one
from `raw["line"]` is unreliable the moment the file is tail-capped,
followed, or read together with a rolled `.lo_` sibling. The original file
is always still on disk when a verbatim copy is what is wanted, and the text
header says as much so nobody is misled about what they are holding.

No Qt: the pane decides where the text goes, this decides what it says.
"""
import csv
import io

from .cmtrace_parser import UNKNOWN_TIME

COLUMNS = ("Time", "Severity", "Component", "Thread", "Message")

_HEADER = ("# Parsed view exported from the Log Viewer -- not a byte-for-byte "
           "copy of the log file.")


def _stamp(entry) -> str:
    if entry.timestamp == UNKNOWN_TIME:
        return ""
    if entry.raw.get("subsecond"):
        return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _row(entry):
    return (_stamp(entry), entry.level, entry.source,
            entry.raw.get("thread", ""), entry.message)


def as_text(entries, header: bool = True) -> str:
    """Aligned columns. `header=False` for the clipboard, where a provenance
    note is noise rather than context."""
    lines = [_HEADER] if header else []
    for entry in entries or ():
        stamp, level, component, thread, message = _row(entry)
        lines.append(f"{stamp:<23} {level:<8} {component:<8} "
                     f"{thread:<8} {message}".rstrip())
    return "\n".join(lines)


def as_csv(entries) -> str:
    buffer = io.StringIO()
    # lineterminator explicitly: csv defaults to \r\n, which lands as blank
    # lines between rows once the file is opened as text on Windows.
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for entry in entries or ():
        writer.writerow(_row(entry))
    return buffer.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_export.py -q`
Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_export.py src/modules/log_viewer/log_export.py
git commit -m "feat(log viewer): text and CSV export writers"
```

---

### Task 7: Error-code spans

**Files:**
- Modify: `src/modules/log_viewer/error_codes.py`
- Test: `tests/test_log_error_codes.py` (create if absent; otherwise add)

**Interfaces:**
- Produces: `code_spans(text) -> list[tuple[int, int, int]]` — `(start, end, code)` for every code, in order of appearance

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_error_codes.py`:

```python
"""Where the codes ARE in a line, so the delegate can colour them in place."""
from modules.log_viewer.error_codes import code_spans, find_codes


def test_spans_point_at_the_code_in_the_text():
    text = "Failed to open package. [HRESULT = 0x800f0805 - CBS_E_INVALID]"
    spans = code_spans(text)
    assert len(spans) == 1
    start, end, code = spans[0]
    assert text[start:end] == "0x800f0805"
    assert code == 0x800F0805


def test_every_occurrence_gets_a_span_even_when_the_code_repeats():
    """find_codes de-duplicates because it answers "which codes"; the
    delegate asks "where", and both occurrences must be coloured."""
    text = "0x80070005 then 0x80070005 again"
    assert len(find_codes(text)) == 1
    assert len(code_spans(text)) == 2


def test_no_codes_is_an_empty_list():
    assert code_spans("nothing to see") == []
    assert code_spans("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_error_codes.py -q`
Expected: FAIL — `ImportError: cannot import name 'code_spans'`

- [ ] **Step 3: Write minimal implementation**

Add to `error_codes.py`, directly below `find_codes`:

```python
def code_spans(text: str) -> list:
    """`(start, end, code)` for every code occurrence, in order.

    `find_codes` answers "which codes are here" and de-duplicates. The
    delegate asks "where are they" and must colour both occurrences of a
    code that appears twice, so this one does not.
    """
    return [(match.start(), match.end(), int(match.group(1), 16))
            for match in _CODE.finditer(text or "")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_error_codes.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_error_codes.py src/modules/log_viewer/error_codes.py
git commit -m "feat(log viewer): locate error codes within a line"
```

---

### Task 8: The delegate that colours codes in place

**Files:**
- Create: `src/modules/log_viewer/log_delegate.py`
- Modify: `src/modules/log_viewer/log_viewer_module.py` (install the delegate on the table)
- Test: `tests/test_log_delegate.py`

**Interfaces:**
- Consumes: `error_codes.code_spans` (Task 7), `palette` (Task 1), `log_model.MESSAGE`
- Produces: `LogMessageDelegate(QStyledItemDelegate)` with `needs_rich_text(text) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_delegate.py`:

```python
"""The Message column's delegate.

Only rows whose message actually carries a code take the rich-text path;
Qt paints only the visible rows, so the cost is bounded by the viewport
rather than by the 134,527 records behind it.
"""
from modules.log_viewer.log_delegate import LogMessageDelegate


def test_a_plain_message_keeps_the_fast_path(qapp):
    assert LogMessageDelegate.needs_rich_text("nothing interesting") is False


def test_a_message_with_a_failing_code_is_painted_rich(qapp):
    assert LogMessageDelegate.needs_rich_text(
        "Failed [HRESULT = 0x800f0805]") is True


def test_a_success_code_does_not_earn_rich_text(qapp):
    """97% of the coded lines in a real CBS.log carry nothing but 0x00000000;
    colouring those would put "success" on screen four thousand times."""
    assert LogMessageDelegate.needs_rich_text("done [HRESULT = 0x00000000]") \
        is False


def test_the_delegate_produces_html_marking_the_code(qapp):
    html = LogMessageDelegate.rich_text("Failed [HRESULT = 0x800f0805]")
    assert "0x800f0805" in html
    assert "<span" in html


def test_html_special_characters_in_a_message_are_escaped(qapp):
    """A CBS line can contain <, > and & -- unescaped they would silently
    eat part of the message."""
    html = LogMessageDelegate.rich_text("a <b> & 0x800f0805")
    assert "&lt;b&gt;" in html and "&amp;" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_delegate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.log_viewer.log_delegate'`

- [ ] **Step 3: Write minimal implementation**

Create `src/modules/log_viewer/log_delegate.py`:

```python
"""Paints the Message column, picking out error codes where they sit.

A row can be Info-coloured and still be the failure someone is looking for:
`Info ... InternalOpenPackage failed [HRESULT = 0x800f0805]` is one of 1,156
such lines on this machine. Colouring the code in place makes it findable
without lying about the row's severity.

Only messages that carry a FAILING code take the rich-text path. On a real
CBS.log, 4,553 lines carry a hex code and 4,427 of them carry nothing but
0x00000000 -- painting those would be four thousand successes on screen to
surface nine failures.
"""
from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle

from core.semantic_colors import semantic

from .error_codes import _is_failure, code_spans


class LogMessageDelegate(QStyledItemDelegate):

    @staticmethod
    def needs_rich_text(text: str) -> bool:
        return any(_is_failure(code) for _s, _e, code in code_spans(text))

    @staticmethod
    def rich_text(text: str) -> str:
        """`text` with every failing code wrapped in a coloured span.

        Built by walking the spans backwards so the earlier offsets stay
        valid, and escaped as it goes -- a CBS message can contain < and &.
        """
        colour = semantic("error")
        pieces = []
        cursor = 0
        for start, end, code in code_spans(text):
            if not _is_failure(code):
                continue
            pieces.append(escape(text[cursor:start]))
            pieces.append(
                f'<span style="color:{colour}">{escape(text[start:end])}</span>')
            cursor = end
        pieces.append(escape(text[cursor:]))
        return "".join(pieces)

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not self.needs_rich_text(text):
            super().paint(painter, option, index)
            return

        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else None
        option.text = ""
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option,
                              painter, option.widget)

        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setHtml(self.rich_text(text))
        painter.save()
        painter.translate(option.rect.left() + 4, option.rect.top())
        document.drawContents(painter)
        painter.restore()
```

Then in `log_viewer_module.py`, after the table's header setup:

```python
        from .log_delegate import LogMessageDelegate

        self.table.setItemDelegateForColumn(MESSAGE, LogMessageDelegate(self))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_delegate.py tests/test_log_viewer_module.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_delegate.py src/modules/log_viewer/log_delegate.py src/modules/log_viewer/log_viewer_module.py
git commit -m "feat(log viewer): colour error codes where they sit in the message"
```

---

### Task 9: The filter row

**Files:**
- Modify: `src/modules/log_viewer/log_viewer_module.py`
- Test: `tests/test_log_viewer_module.py` (add)

**Interfaces:**
- Consumes: `LogModel.set_filter`, `.threads()`, `.time_span()` (Task 5)
- Produces: `LogViewerWidget.thread`, `.time_from`, `.time_to`, `.regex_box`, `.clear_range_button`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_log_viewer_module.py`:

```python
# ---- the filter row -----------------------------------------------------

@pytest.fixture
def threaded_log(tmp_path):
    path = tmp_path / "dism.log"
    path.write_text(
        "2026-08-24 21:45:46, Info                  DISM   API: PID=1 "
        "TID=29016 first\n"
        "2026-08-24 21:45:47, Info                  DISM   API: PID=1 "
        "TID=29016 second\n"
        "2026-08-24 22:00:00, Info                  DISM   API: PID=1 "
        "TID=777 third\n", encoding="utf-8")
    return path


def test_the_thread_box_lists_threads_by_how_common_they_are(qapp,
                                                             threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        entries = [widget.thread.itemText(i)
                   for i in range(widget.thread.count())]
        assert entries[0] == "All"
        assert entries[1].startswith("29016")
        assert "(2)" in entries[1]
    finally:
        widget.stop()


def test_choosing_a_thread_filters_the_table(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.thread.setCurrentIndex(widget.thread.findText("777  (1)"))
        assert widget.model.rowCount() == 1
    finally:
        widget.stop()


def test_the_range_boxes_open_on_the_whole_log(qapp, threaded_log):
    """Not on the year 1752, which is what an unset QDateTimeEdit shows."""
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        assert widget.time_from.dateTime().toPyDateTime() == \
            datetime(2026, 8, 24, 21, 45, 46)
        assert widget.time_to.dateTime().toPyDateTime() == \
            datetime(2026, 8, 24, 22, 0, 0)
    finally:
        widget.stop()


def test_narrowing_the_range_filters_the_table(qapp, threaded_log):
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_to.setDateTime(
            QDateTime(datetime(2026, 8, 24, 21, 46, 0)))
        assert widget.model.rowCount() == 2
    finally:
        widget.stop()


def test_clearing_the_range_brings_every_row_back(qapp, threaded_log):
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_to.setDateTime(
            QDateTime(datetime(2026, 8, 24, 21, 46, 0)))
        widget.clear_range_button.click()
        assert widget.model.rowCount() == 3
    finally:
        widget.stop()


def test_the_regex_box_switches_the_filter_to_a_pattern(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.regex_box.setChecked(True)
        widget.filter_box.setText(r"TID=29\d+")
        assert widget.model.rowCount() == 2
    finally:
        widget.stop()


def test_a_backwards_range_says_so_rather_than_emptying_the_table(qapp,
                                                                  threaded_log):
    """An empty table reads as "no such records", which is a lie about the
    log rather than a complaint about the range."""
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_from.setDateTime(
            QDateTime(datetime(2026, 8, 24, 23, 0, 0)))
        assert "range" in widget.status.text().lower()
        assert widget.model.rowCount() == 3, "nothing was filtered away"
    finally:
        widget.stop()


def test_an_invalid_pattern_says_so_instead_of_raising(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.regex_box.setChecked(True)
        widget.filter_box.setText("[unclosed")
        assert "pattern" in widget.status.text().lower()
    finally:
        widget.stop()
```

Add `from datetime import datetime` to the file's imports if absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q -k "thread or range or regex or pattern"`
Expected: FAIL — `AttributeError: 'LogViewerWidget' object has no attribute 'thread'`

- [ ] **Step 3: Write minimal implementation**

In `log_viewer_module.py`, import `QDateTime` from `PyQt6.QtCore` and
`QDateTimeEdit` from `PyQt6.QtWidgets`. Add a third row after `find_row`:

```python
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Thread:", self))
        # Editable with a completer, not a plain dropdown: DISM carries 329
        # distinct thread ids, and an alphabetical list of 329 numbers is not
        # a control anyone can use. Ordered by how common each one is.
        self.thread = QComboBox(self)
        self.thread.setEditable(True)
        self.thread.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.thread.setMinimumWidth(140)
        self.thread.addItem("All")
        self.thread.currentIndexChanged.connect(lambda _i: self._apply_filters())
        range_row.addWidget(self.thread)

        range_row.addSpacing(12)
        range_row.addWidget(QLabel("From:", self))
        self.time_from = QDateTimeEdit(self)
        self.time_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.time_from.dateTimeChanged.connect(lambda _d: self._apply_filters())
        range_row.addWidget(self.time_from)
        range_row.addWidget(QLabel("To:", self))
        self.time_to = QDateTimeEdit(self)
        self.time_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.time_to.dateTimeChanged.connect(lambda _d: self._apply_filters())
        range_row.addWidget(self.time_to)
        self.clear_range_button = QPushButton("Clear range", self)
        self.clear_range_button.clicked.connect(self._reset_range)
        range_row.addWidget(self.clear_range_button)

        range_row.addSpacing(12)
        self.regex_box = QCheckBox("Regex", self)
        self.regex_box.setToolTip("Treat Find and Filter as regular "
                                  "expressions.")
        self.regex_box.toggled.connect(lambda _c: self._apply_filters())
        range_row.addWidget(self.regex_box)
        range_row.addStretch(1)
        layout.addLayout(range_row)
```

Add these methods:

```python
    def _refresh_threads(self) -> None:
        current = self.thread.currentText()
        self.thread.blockSignals(True)
        self.thread.clear()
        self.thread.addItem("All")
        for thread, count in self.model.threads():
            self.thread.addItem(f"{thread}  ({count:,})")
        index = self.thread.findText(current)
        self.thread.setCurrentIndex(max(0, index))
        self.thread.blockSignals(False)

    def _reset_range(self) -> None:
        """Open the boxes on the whole log, and stop filtering by time."""
        span = self.model.time_span()
        for box, value in ((self.time_from, span[0] if span else None),
                           (self.time_to, span[1] if span else None)):
            box.blockSignals(True)
            if value is not None:
                box.setDateTime(QDateTime(value))
            box.blockSignals(False)
        self.model.set_filter(time_from=False, time_to=False)
        self._update_status()
```

In `_apply_filters`, add the three new axes:

```python
        thread = self.thread.currentText()
        thread = "" if thread == "All" else thread.split(" ")[0]
        # A backwards range would hide every row, and an empty table reads
        # as "no such records" -- a lie about the log rather than a
        # complaint about the range. Say so and filter nothing.
        start = self.time_from.dateTime().toPyDateTime()
        end = self.time_to.dateTime().toPyDateTime()
        if start > end:
            self.model.set_filter(time_from=False, time_to=False)
            self.status.setText("That time range ends before it starts.")
            return
        self.model.set_filter(
            levels=levels,
            needle=self.filter_box.text(),
            component="" if component == "All" else component,
            thread=thread,
            time_from=start,
            time_to=end,
            regex=self.regex_box.isChecked())
        if self.model.filter_pattern_is_invalid():
            self.status.setText("That pattern is not finished yet.")
            return
        self._update_status()
```

Add to `LogModel` (Task 5's file):

```python
    def filter_pattern_is_invalid(self) -> bool:
        """The pane asks, so it can say so rather than showing an empty
        table that reads as "no such records"."""
        return self._matcher is False
```

And rewrite `find()` so the one Regex checkbox governs it as well — it is
still substring-only otherwise, which would make the checkbox a half-truth:

```python
    def find(self, needle: str, start_row: int = 0, forwards: bool = True) -> int:
        """The next visible row containing `needle`, or -1.

        Wraps, because a search that stops at the end of a log makes the user
        scroll back to the top to carry on. Honours the same Regex flag the
        filter does: one checkbox governs both boxes.
        """
        if not needle or not self._visible:
            return -1
        matcher = None
        if self._regex:
            try:
                matcher = re.compile(needle, re.IGNORECASE)
            except re.error:
                return -1
        lowered = needle.lower()
        count = len(self._visible)
        step = 1 if forwards else -1
        for offset in range(1, count + 1):
            row = (start_row + offset * step) % count
            entry = self.entry(row)
            if entry is None:
                continue
            if matcher is not None:
                if matcher.search(entry.message):
                    return row
            elif lowered in entry.message.lower():
                return row
        return -1
```

In `reload()`, call `self._refresh_threads()` and `self._reset_range()`
directly after `self._refresh_components()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_viewer_module.py src/modules/log_viewer/log_model.py tests/test_log_viewer_module.py
git commit -m "feat(log viewer): thread, time-range and regex controls"
```

---

### Task 10: Row context menu — anchor the range, look up codes

**Files:**
- Modify: `src/modules/log_viewer/log_viewer_module.py`
- Test: `tests/test_log_viewer_module.py` (add)

**Interfaces:**
- Produces: `LogViewerWidget.anchor_range(row, minutes) -> None`

- [ ] **Step 1: Write the failing test**

```python
def test_anchoring_the_range_on_a_row_shows_what_surrounded_it(qapp,
                                                               threaded_log):
    """You find an error, then ask what happened around it. That is the
    primary way the range is meant to be used."""
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.anchor_range(0, minutes=5)
        assert widget.model.rowCount() == 2      # 21:45:46 and 21:45:47
        assert widget.time_from.dateTime().toPyDateTime() == \
            datetime(2026, 8, 24, 21, 40, 46)
    finally:
        widget.stop()


def test_anchoring_on_a_row_with_no_timestamp_does_nothing(qapp, log):
    widget = LogViewerWidget()
    try:
        widget.open(str(log))
        before = widget.model.rowCount()
        widget.anchor_range(-1, minutes=5)
        assert widget.model.rowCount() == before
    finally:
        widget.stop()


def test_the_context_menu_offers_the_range_and_the_lookup(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        menu = widget.build_row_menu(0)
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert any("minute" in label for label in labels)
        assert any("code" in label.lower() for label in labels)
    finally:
        widget.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q -k "anchor or context"`
Expected: FAIL — `AttributeError: ... has no attribute 'anchor_range'`

- [ ] **Step 3: Write minimal implementation**

```python
    #: Offered on a row. Five minutes is the default because a servicing
    #: operation's related lines land within seconds of each other; the
    #: wider ones are for correlating across a reboot.
    RANGE_MINUTES = (1, 5, 15, 60)

    def anchor_range(self, row: int, minutes: int) -> None:
        entry = self.model.entry(row)
        if entry is None or entry.timestamp == UNKNOWN_TIME:
            return
        span = timedelta(minutes=minutes)
        self.time_from.blockSignals(True)
        self.time_to.blockSignals(True)
        self.time_from.setDateTime(QDateTime(entry.timestamp - span))
        self.time_to.setDateTime(QDateTime(entry.timestamp + span))
        self.time_from.blockSignals(False)
        self.time_to.blockSignals(False)
        self._apply_filters()

    def build_row_menu(self, row: int) -> QMenu:
        menu = QMenu(self)
        for minutes in self.RANGE_MINUTES:
            menu.addAction(
                f"Show ±{minutes} minute{'s' if minutes > 1 else ''} "
                f"around this row",
                lambda _c=False, m=minutes: self.anchor_range(row, m))
        menu.addSeparator()
        menu.addAction("Look up the error codes on this row",
                       lambda _c=False: self.open_error_lookup(row))
        menu.addAction("Copy selected rows", self.copy_selection)
        return menu

    def _on_context_menu(self, point) -> None:
        index = self.table.indexAt(point)
        if index.isValid():
            self.build_row_menu(index.row()).exec(
                self.table.viewport().mapToGlobal(point))
```

Wire in `__init__`, after the table exists:

```python
        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
```

Add `from datetime import timedelta` and
`from .cmtrace_parser import UNKNOWN_TIME` to the imports.

`open_error_lookup` and `copy_selection` arrive in Tasks 11 and 12; until
then, stub each as a one-line `pass` method with a `# Task N` comment so the
menu builds. Both are replaced, not extended, by those tasks.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_viewer_module.py tests/test_log_viewer_module.py
git commit -m "feat(log viewer): anchor the time range on a row"
```

---

### Task 11: Copy and export

**Files:**
- Modify: `src/modules/log_viewer/log_viewer_module.py`
- Test: `tests/test_log_viewer_module.py` (add)

**Interfaces:**
- Consumes: `log_export.as_text`, `.as_csv` (Task 6)
- Produces: `LogViewerWidget.copy_selection()`, `.visible_entries()`, `.export_to(path)`

- [ ] **Step 1: Write the failing test**

```python
def test_copying_the_selection_puts_the_rows_on_the_clipboard(qapp,
                                                              threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.table.selectRow(0)
        widget.copy_selection()
        text = qapp.clipboard().text()
        assert "first" in text
        assert "second" not in text
        assert not text.startswith("#"), "no provenance header on a copy"
    finally:
        widget.stop()


def test_exporting_writes_only_what_the_filter_left_visible(qapp,
                                                            threaded_log,
                                                            tmp_path):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.thread.setCurrentIndex(widget.thread.findText("777  (1)"))
        out = tmp_path / "slice.txt"
        widget.export_to(str(out))
        written = out.read_text(encoding="utf-8")
        assert "third" in written and "first" not in written
        assert written.startswith("#")
    finally:
        widget.stop()


def test_exporting_csv_is_chosen_by_the_extension(qapp, threaded_log,
                                                  tmp_path):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        out = tmp_path / "slice.csv"
        widget.export_to(str(out))
        assert out.read_text(encoding="utf-8").startswith("Time,Severity")
    finally:
        widget.stop()


def test_an_export_that_cannot_be_written_says_why(qapp, threaded_log,
                                                   tmp_path):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.export_to(str(tmp_path / "no-such-dir" / "x.txt"))
        assert "could not" in widget.status.text().lower()
    finally:
        widget.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q -k "copy or export"`
Expected: FAIL — `AttributeError: ... has no attribute 'copy_selection'`

- [ ] **Step 3: Write minimal implementation**

```python
    def visible_entries(self) -> list:
        """Exactly what the filter left on screen, in view order."""
        return [self.model.entry(row) for row in range(self.model.rowCount())]

    def copy_selection(self) -> None:
        rows = sorted({index.row()
                       for index in self.table.selectionModel().selectedRows()}
                      or {self.table.currentIndex().row()})
        entries = [self.model.entry(row) for row in rows
                   if self.model.entry(row) is not None]
        if not entries:
            return
        from .log_export import as_text
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(as_text(entries, header=False))
        self.status.setText(f"{len(entries):,} row(s) copied.")

    def export_to(self, path: str) -> None:
        from .log_export import as_csv, as_text

        entries = self.visible_entries()
        text = (as_csv(entries) if path.lower().endswith(".csv")
                else as_text(entries))
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        except OSError as exc:
            logger.warning("Could not export to %s", path, exc_info=True)
            self.status.setText(f"Could not write the export: {exc}")
            return
        self.status.setText(f"{len(entries):,} row(s) written to "
                            f"{os.path.basename(path)}")

    def choose_export(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export the filtered view", "",
            "Text (*.txt);;CSV (*.csv)")
        if path:
            self.export_to(path)
```

Add an `Export…` button to `range_row`, and a Ctrl+C shortcut in `__init__`:

```python
        self.export_button = QPushButton("Export…", self)
        self.export_button.clicked.connect(self.choose_export)
        range_row.addWidget(self.export_button)
```

```python
        from PyQt6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence.StandardKey.Copy, self.table,
                  activated=self.copy_selection)
```

Delete the `copy_selection` stub left by Task 10.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_viewer_module.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/log_viewer_module.py tests/test_log_viewer_module.py
git commit -m "feat(log viewer): copy the selection and export the filtered view"
```

---

### Task 12: Error Lookup and the highlight-rule editor

**Files:**
- Create: `src/modules/log_viewer/error_lookup_dialog.py`
- Create: `src/modules/log_viewer/highlight_dialog.py`
- Modify: `src/modules/log_viewer/log_viewer_module.py`
- Modify: `pyinstaller_common.py` (`HIDDEN_IMPORTS`)
- Test: `tests/test_log_dialogs.py`

**Interfaces:**
- Consumes: `error_codes.explain`, `.find_codes`, `.describe` (existing); `highlight.load_rules`, `.save_rules`, `.HighlightRule` (Task 3)
- Produces: `ErrorLookupDialog(parent=None)` with `.look_up(text) -> str`; `HighlightDialog(rules, parent=None)` with `.rules() -> list[HighlightRule]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_dialogs.py`:

```python
"""The two dialogs. Both are shells over logic that is tested elsewhere."""
from modules.log_viewer.error_lookup_dialog import ErrorLookupDialog
from modules.log_viewer.highlight_dialog import HighlightDialog
from modules.log_viewer.highlight import HighlightRule


def test_looking_up_a_bare_code_explains_it(qapp):
    dialog = ErrorLookupDialog()
    try:
        assert "denied" in dialog.look_up("0x80070005").lower()
    finally:
        dialog.close()


def test_looking_up_a_whole_pasted_line_finds_the_code_in_it(qapp):
    dialog = ErrorLookupDialog()
    try:
        answer = dialog.look_up("Failed [HRESULT = 0x80070005 - E_DENIED]")
        assert "0x80070005" in answer
    finally:
        dialog.close()


def test_a_code_nobody_knows_says_so_rather_than_guessing(qapp):
    dialog = ErrorLookupDialog()
    try:
        answer = dialog.look_up("0x0ABCDEF1")
        assert "not" in answer.lower() or "unknown" in answer.lower()
    finally:
        dialog.close()


def test_text_with_no_code_at_all_says_so(qapp):
    dialog = ErrorLookupDialog()
    try:
        assert "no " in dialog.look_up("nothing here").lower()
    finally:
        dialog.close()


def test_the_highlight_editor_returns_the_rules_it_was_given(qapp):
    rules = [HighlightRule("boom", "#ff0000")]
    dialog = HighlightDialog(rules)
    try:
        assert dialog.rules() == rules
    finally:
        dialog.close()


def test_adding_a_rule_in_the_editor(qapp):
    dialog = HighlightDialog([])
    try:
        dialog.add_rule(HighlightRule("new", "#00ff00", regex=True))
        assert dialog.rules() == [HighlightRule("new", "#00ff00", regex=True)]
    finally:
        dialog.close()


def test_an_invalid_pattern_is_flagged_rather_than_rejected(qapp):
    """Half a regex is a work in progress, not an error to refuse."""
    dialog = HighlightDialog([])
    try:
        dialog.add_rule(HighlightRule("[unclosed", "#00ff00", regex=True))
        assert dialog.invalid_rows() == [0]
        assert len(dialog.rules()) == 1
    finally:
        dialog.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_dialogs.py -q`
Expected: FAIL — `ModuleNotFoundError: ... error_lookup_dialog`

- [ ] **Step 3: Write minimal implementation**

`error_lookup_dialog.py`:

```python
"""CMTrace's Error Lookup: paste a code or a whole line, get the meaning.

A shell over `error_codes` -- no lookup logic lives here. It exists because
the tooltip and the detail pane can only explain a code that is already on a
visible row, and the code you are chasing is often one someone read out to
you over the phone.
"""
from PyQt6.QtWidgets import (QDialog, QLabel, QLineEdit, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

from .error_codes import describe, find_codes


class ErrorLookupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Error lookup")
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Paste a code, or a whole log line:", self))
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("0x80070005")
        self.input.returnPressed.connect(self._look_up_input)
        layout.addWidget(self.input)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        button = QPushButton("Look up", self)
        button.clicked.connect(self._look_up_input)
        layout.addWidget(button)

    def look_up(self, text: str) -> str:
        codes = find_codes(text)
        if not codes:
            return "No error code found in that text."
        lines = []
        for code in codes:
            meaning = describe(code)
            # Silence beats a guess, which is why `describe` returns "" --
            # but the person asked, so say that nothing is known rather
            # than showing them a blank box.
            lines.append(f"0x{code:08X}  —  "
                         f"{meaning or 'not a code this tool knows.'}")
        return "\n".join(lines)

    def _look_up_input(self) -> None:
        self.output.setPlainText(self.look_up(self.input.text()))

    def show_for(self, text: str) -> None:
        self.input.setText(text)
        self._look_up_input()
        self.show()
        self.raise_()
```

`highlight_dialog.py`:

```python
"""Editor for the highlight rules.

Order matters and is visible: `matching_rule` takes the FIRST rule that
matches, so moving a rule up changes what a row looks like.
"""
import re

from PyQt6.QtWidgets import (QAbstractItemView, QColorDialog, QDialog,
                             QDialogButtonBox, QHBoxLayout, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import Qt

from .highlight import HighlightRule

_COLUMNS = ("Pattern", "Colour", "Regex", "On")


class HighlightDialog(QDialog):
    def __init__(self, rules, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Highlight rules")
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add = QPushButton("Add", self)
        add.clicked.connect(self._add_blank)
        buttons.addWidget(add)
        remove = QPushButton("Remove", self)
        remove.clicked.connect(self._remove_selected)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

        for rule in rules or ():
            self.add_rule(rule)

    def add_rule(self, rule: HighlightRule) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(rule.pattern))
        colour = QTableWidgetItem(rule.colour)
        colour.setBackground(QColor(rule.colour))
        self.table.setItem(row, 1, colour)
        for column, value in ((2, rule.regex), (3, rule.enabled)):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value
                               else Qt.CheckState.Unchecked)
            self.table.setItem(row, column, item)

    def _add_blank(self) -> None:
        colour = QColorDialog.getColor(QColor("#00ff00"), self)
        if colour.isValid():
            self.add_rule(HighlightRule("", colour.name()))

    def _remove_selected(self) -> None:
        for index in sorted(
                {i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def rules(self) -> list:
        out = []
        for row in range(self.table.rowCount()):
            out.append(HighlightRule(
                pattern=self.table.item(row, 0).text(),
                colour=self.table.item(row, 1).text(),
                regex=self.table.item(row, 2).checkState()
                == Qt.CheckState.Checked,
                enabled=self.table.item(row, 3).checkState()
                == Qt.CheckState.Checked,
            ))
        return out

    def invalid_rows(self) -> list:
        """Rows whose pattern will not compile. Flagged, never refused --
        half a regex is a work in progress."""
        bad = []
        for row, rule in enumerate(self.rules()):
            if not rule.regex:
                continue
            try:
                re.compile(rule.pattern)
            except re.error:
                bad.append(row)
        return bad
```

In `log_viewer_module.py`, replace the Task 10 stub and add the button:

```python
    def open_error_lookup(self, row: int = -1) -> None:
        from .error_lookup_dialog import ErrorLookupDialog

        if self._lookup is None:
            self._lookup = ErrorLookupDialog(self)
        entry = self.model.entry(row) if row >= 0 else None
        self._lookup.show_for(entry.message if entry is not None else "")

    def edit_highlight_rules(self) -> None:
        from .highlight import load_rules, save_rules
        from .highlight_dialog import HighlightDialog

        dialog = HighlightDialog(self._rules, self)
        if dialog.exec():
            self._rules = dialog.rules()
            self.model.set_highlight_rules(self._rules)
            if self._config is not None:
                save_rules(self._config, self._rules)
```

with `self._lookup = None`, `self._rules = []` and `self._config = None` in
`__init__`, plus two buttons on `range_row` wired to `edit_highlight_rules`
and `open_error_lookup`.

Load the stored rules in `LogViewerModule.create_widget`, **not** in
`on_start`: `on_start` runs BEFORE `create_widget` (CLAUDE.md), so there is no
widget to give the config to yet.

```python
    def create_widget(self) -> QWidget:
        self._widget = LogViewerWidget()
        self._provider = self._widget.provider
        config = getattr(self.app, "config", None) if self.app else None
        if config is not None:
            from .highlight import load_rules

            self._widget._config = config
            self._widget._rules = load_rules(config)
            self._widget.model.set_highlight_rules(self._widget._rules)
        return self._widget
```

`BaseModule` stores the app on `self.app` in `on_start`; guard for it being
absent so a widget built directly in a test still works, which is how every
existing test in `test_log_viewer_module.py` constructs it.

Add `"modules.log_viewer.error_lookup_dialog"` and
`"modules.log_viewer.highlight_dialog"` to `HIDDEN_IMPORTS` in
`pyinstaller_common.py`: both are imported inside button handlers, so a
frozen build runs fine until someone clicks the button.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_log_dialogs.py tests/test_log_viewer_module.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/log_viewer/ tests/test_log_dialogs.py pyinstaller_common.py
git commit -m "feat(log viewer): error lookup and highlight-rule editor"
```

---

### Task 13: Verify it against the real machine

**Files:**
- Modify: `tools/log_viewer_real_check.py`
- Modify: `.superpowers/sdd/2026-08-30-log-viewer-real-logs/log_qt_probe.py` (git-ignored)

This task writes no feature code. Every defect ever found in this module was
found here, not by the suite.

- [ ] **Step 1: Extend the real check**

Add to each file's report in `tools/log_viewer_real_check.py`:

```python
    threads_seen = collections.Counter(e.raw.get("thread", "")
                                       for e in entries if e.raw.get("thread"))
    print(f"    distinct threads : {len(threads_seen)} "
          f"{dict(threads_seen.most_common(4))}")
```

and a filter-sanity pass that asserts a filter can never return more rows
than it was given:

```python
    from modules.log_viewer.log_model import LogModel

    model = LogModel()
    model.append(entries)
    total = model.rowCount()
    model.set_filter(levels={"Error"})
    errors = model.rowCount()
    print(f"    filter sanity    : {errors:,} errors of {total:,}"
          + ("" if errors <= total else "   *** FILTER GREW THE LOG"))
```

- [ ] **Step 2: Run it and read every line**

Run: `.\.venv\Scripts\python.exe tools\log_viewer_real_check.py`
Expected: all seven logs report, no `***` markers. DISM must report **329**
distinct threads; if it does not, the thread extraction regressed.

- [ ] **Step 3: Render the pane and LOOK at it, in both themes**

Extend the Qt probe to grab a screenshot under each theme:

```python
from core import semantic_colors

for theme in ("dark", "light"):
    semantic_colors.set_theme(theme)
    widget.model.set_highlight_rules([])
    widget.open(r"C:\Windows\Logs\CBS\CBS.log")
    app.processEvents()
    widget.grab().save(os.path.join(OUT, f"pane_cbs_{theme}.png"))
```

Run it through the **PowerShell tool** (a QApplication from the Bash tool
exits 127), with absolute paths:

```
& "<repo>\.venv\Scripts\python.exe" "<repo>\.superpowers\sdd\2026-08-30-log-viewer-real-logs\log_qt_probe.py"
```

Then open both PNGs and check: component tints distinguishable from each
other, codes visible inside Info rows, and nothing illegible on the light
sheet. A contrast test cannot answer inter-colour distinctness — only looking
can.

- [ ] **Step 4: Run the theme test and the full suite cold**

```bash
find . -name "__pycache__" -type d -not -path "./.venv/*" -exec rm -rf {} +
.\.venv\Scripts\python.exe -m pytest tests/test_theme_light_coverage.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the theme test passes with the Log Viewer NOT skipped, and the full
suite is green. The cold warning baseline is 3 if `.venv`'s `__pycache__` is
also cleared, 1 if it is not — count warnings only against a like-for-like run.

- [ ] **Step 5: Measure the two risks the spec named**

Time the regex filter and the delegate rather than assuming:

```python
start = time.perf_counter()
widget.regex_box.setChecked(True)
widget.filter_box.setText(r"HRESULT = 0x8007[0-9a-f]{4}")
app.processEvents()
print(f"regex filter over {widget.model.total:,}: "
      f"{time.perf_counter() - start:.2f}s")
```

The substring filter costs 0.05 s over 134,527 rows. If regex is materially
worse, add a `QTimer`-based debounce to `filter_box.textChanged` — and say so
in the commit rather than quietly leaving it slow.

- [ ] **Step 6: Commit**

```bash
git add tools/log_viewer_real_check.py
git commit -m "test(log viewer): real-log check covers threads and filters"
```

---

## Definition of done

- All 13 tasks committed.
- Full suite green cold; `tests/test_theme_light_coverage.py` passes with the
  Log Viewer not skipped.
- `tools/log_viewer_real_check.py` clean on all seven logs, DISM reporting 329
  distinct threads.
- Both screenshots looked at, in both themes.
- The two named risks measured, with the numbers written into the ledger at
  `.superpowers/sdd/2026-08-30-log-viewer-real-logs/RESUME.md`.
