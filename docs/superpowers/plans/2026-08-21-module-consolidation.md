# Module Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a `CompositeModule` that hosts other modules as tabs, then use it to collapse the sidebar from 41 entries to 34 while reviving six dead diagnostic modules and restoring six search providers that are currently unreachable.

**Architecture:** One new core class (`CompositeModule`) plus two small extensions to existing core plumbing (`BaseModule.get_search_providers`, a name→(host, tab) route map consulted by `MainWindow`). Every consolidation is then a declaration of a `children` list on an existing module. Nothing about parsers, readers, scanners or search providers changes behaviour.

**Tech Stack:** Python 3.12, PyQt6, pytest. Windows 10/11 only.

**Spec:** `docs/superpowers/specs/2026-08-21-module-consolidation-design.md`

## Global Constraints

- Run everything with the project venv: `.venv\Scripts\python.exe`. PowerShell refuses a relative executable without `.\`.
- Test baseline to preserve: **1332 passed, 3 skipped, 1 warning**. The 1 warning is a pre-existing `PytestCollectionWarning` at `tests/test_integration.py:16` — the baseline is 1, not 0. Counting warnings requires clearing `__pycache__` first.
- `worker.is_cancelled` is a `@property`, not a method. Cancel via `worker.cancel()`, never `worker._cancelled = True`.
- `on_start` runs BEFORE `create_widget`. Never touch `_widget`, `_table` or any UI element in `on_start`.
- Modules are registered in `src/main.py::register_all_modules`. A module class is imported there and registered with `app.module_registry.register(Cls())`.
- Tests import from `core.*` / `modules.*` directly; `tests/conftest.py` puts `src/` on the path and provides a session-scoped `qapp` fixture. Any test that constructs a QWidget needs no extra setup — the fixture is `autouse=True`.
- A green suite proves nothing on its own. Every phase that changes UI ends by running the app and looking at the pane.
- Commit after each task.

---

## File Structure

**Created:**
- `src/core/composite_module.py` — `CompositeModule`: tab host, lifecycle forwarding, lazy child widgets, admin gating, route map.
- `src/ui/log_pane.py` — `LogPane`: the log table + detail + error banner + progress + Refresh widget extracted from `DiagnoseModule`, parameterised by a loader.
- `tests/test_composite_module.py`, `tests/test_log_pane.py`, `tests/test_module_inventory.py`, `tests/test_log_retention_count.py`.

**Modified:**
- `src/core/base_module.py` — add `get_search_providers()`.
- `src/core/module_registry.py:44-46` — register every provider a module returns.
- `src/core/log_rotation.py` — add `keep_newest()`.
- `src/app.py:73-84` — call `keep_newest` on the session log dir.
- `config/default_config.json` — add `app.log_retention_count`.
- `src/ui/main_window.py:342` — route a name miss through the composite route map.
- `src/modules/debloat/debloat_module.py`, `startup_manager/startup_module.py`, `network_diagnostics/network_module.py`, `diagnose/diagnose_module.py` — become composites.
- `src/modules/network_extras/net_extras_module.py:100` — drop the duplicate HOSTS tab.
- The six diagnostic `*_module.py` files — rebuilt on `LogPane`.
- `src/main.py` — registration list.

**Deleted:**
- `src/modules/duplicate_finder/`, `tests/test_duplicate_finder.py`.

---

# Phase 1 — The mechanism

### Task 1: `BaseModule.get_search_providers()` and registry fan-out

**Files:**
- Modify: `src/core/base_module.py` (after `get_search_provider`, ~line 165)
- Modify: `src/core/module_registry.py:44-46`
- Test: `tests/test_composite_module.py` (new)

**Interfaces:**
- Consumes: `SearchProvider` from `core.search_provider`.
- Produces: `BaseModule.get_search_providers() -> List[SearchProvider]`. `CompositeModule` (Task 2) overrides it. `ModuleRegistry.start_all` calls it instead of `get_search_provider`.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_composite_module.py"""
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.module_registry import ModuleRegistry
from core.search_provider import FilterField, SearchProvider


class _Provider(SearchProvider):
    def __init__(self, module_name):
        self.module_name = module_name

    def search(self, query):
        return []

    def get_filterable_fields(self):
        return [FilterField(name="x", label="X")]


class _Leaf(BaseModule):
    name = "Leaf"
    icon = "L"
    description = "leaf"
    group = ModuleGroup.TOOLS

    def __init__(self, provider=None):
        super().__init__()
        self._provider = provider

    def get_search_provider(self):
        return self._provider


class _FakeSearch:
    def __init__(self):
        self.registered = []

    def register_provider(self, provider):
        self.registered.append(provider)


class _FakeApp:
    def __init__(self):
        self.search = _FakeSearch()


def test_get_search_providers_defaults_to_the_single_provider():
    p = _Provider("Leaf")
    assert _Leaf(p).get_search_providers() == [p]


def test_get_search_providers_is_empty_when_there_is_no_provider():
    assert _Leaf(None).get_search_providers() == []


def test_registry_registers_every_provider_a_module_returns():
    a, b = _Provider("A"), _Provider("B")

    class _Multi(_Leaf):
        def get_search_providers(self):
            return [a, b]

    registry = ModuleRegistry()
    registry.register(_Multi())
    app = _FakeApp()
    registry.start_all(app)

    assert app.search.registered == [a, b]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: FAIL — `AttributeError: '_Leaf' object has no attribute 'get_search_providers'`

- [ ] **Step 3: Add the method to BaseModule**

In `src/core/base_module.py`, directly after `get_search_provider`:

```python
    def get_search_providers(self) -> List["SearchProvider"]:
        """Return every search provider this module contributes.

        A plain module contributes at most one, so the default wraps
        `get_search_provider()`. A module that hosts others (see
        `core.composite_module.CompositeModule`) overrides this to return its
        children's providers.

        This is a list rather than a single provider because
        `SearchEngine.execute` filters per provider on `provider.module_name`
        — one provider standing in for several would have to re-implement that
        filtering and could drift from it.
        """
        provider = self.get_search_provider()
        return [provider] if provider is not None else []
```

- [ ] **Step 4: Fan out in the registry**

In `src/core/module_registry.py`, replace lines 44-46:

```python
                provider = module.get_search_provider()
                if provider is not None:
                    app.search.register_provider(provider)
```

with:

```python
                for provider in module.get_search_providers():
                    app.search.register_provider(provider)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 1335 passed, 3 skipped (the 3 new tests on top of the 1332 baseline)

- [ ] **Step 7: Commit**

```bash
git add src/core/base_module.py src/core/module_registry.py tests/test_composite_module.py
git commit -m "feat(core): a module may contribute more than one search provider"
```

---

### Task 2: `CompositeModule` — tabs, lazy children, lifecycle

**Files:**
- Create: `src/core/composite_module.py`
- Test: `tests/test_composite_module.py` (append)

**Interfaces:**
- Consumes: `BaseModule`, `BaseModule.get_search_providers()` (Task 1).
- Produces:
  - `CompositeModule.children: list[BaseModule]` — declared by subclasses, in tab order.
  - `CompositeModule.create_widget() -> QWidget`
  - `CompositeModule.wrap(tabs: QTabWidget) -> QWidget` — overridable chrome hook, returns `tabs` by default. `DiagnoseModule` (Task 12) overrides it to keep its search bar and results tree above the tabs; without this hook a composite could only ever be a bare tab widget.
  - `CompositeModule.route_map() -> dict[str, tuple[str, int]]` — `{child.name: (host.name, tab_index)}`, consumed by Task 4.
  - `CompositeModule.select_child(name: str) -> bool` — select that child's tab, returns False if unknown.
  - Class attribute `requires_admin = False` always; per-child gating is internal.

Two things this design gets wrong if written the obvious way, both found while drafting:

- **A disabled tab needs the right reason.** A child can be disabled because it needs elevation *or* because it raised in `on_start`. Showing "requires administrator privileges" for a crash is a lie that costs someone an elevated relaunch to disprove. Reasons are stored per index.
- **Never `removeTab` to swap in a lazily-built widget.** `removeTab` on the current index fires `currentChanged` again, re-entering the handler that called it. Each tab page is instead a permanent container whose layout the child widget is added into on first show.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_composite_module.py`:

```python
import pytest
from PyQt6.QtWidgets import QLabel, QTabWidget

from core.composite_module import CompositeModule


class _Recorder(_Leaf):
    """A child that records every lifecycle call it receives."""

    def __init__(self, name, provider=None, requires_admin=False, fail_on_start=False):
        super().__init__(provider)
        self.name = name
        self.requires_admin = requires_admin
        self._fail_on_start = fail_on_start
        self.calls = []
        self.widgets_built = 0

    def create_widget(self):
        self.widgets_built += 1
        return QLabel(self.name)

    def on_start(self, app):
        self.calls.append("start")
        if self._fail_on_start:
            raise RuntimeError("boom")

    def on_activate(self):
        self.calls.append("activate")

    def on_deactivate(self):
        self.calls.append("deactivate")

    def on_stop(self):
        self.calls.append("stop")


def _host(*children, admin=True):
    class _Host(CompositeModule):
        name = "Host"
        icon = "H"
        description = "host"
        group = ModuleGroup.TOOLS

        def __init__(self):
            super().__init__()
            self.children = list(children)

    host = _Host()
    host._is_admin = lambda: admin
    return host


def test_only_the_first_child_widget_is_built_upfront():
    a, b, c = _Recorder("A"), _Recorder("B"), _Recorder("C")
    host = _host(a, b, c)
    host.on_start(_FakeApp())

    widget = host.create_widget()

    assert isinstance(widget, QTabWidget)
    assert widget.count() == 3
    assert (a.widgets_built, b.widgets_built, c.widgets_built) == (1, 0, 0)


def test_showing_a_tab_builds_exactly_that_child():
    a, b, c = _Recorder("A"), _Recorder("B"), _Recorder("C")
    host = _host(a, b, c)
    host.on_start(_FakeApp())
    widget = host.create_widget()

    widget.setCurrentIndex(2)

    assert (a.widgets_built, b.widgets_built, c.widgets_built) == (1, 0, 1)


def test_switching_tabs_deactivates_the_outgoing_child_then_activates_the_incoming():
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    widget = host.create_widget()
    host.on_activate()
    a.calls.clear()
    b.calls.clear()

    widget.setCurrentIndex(1)

    assert a.calls == ["deactivate"]
    assert b.calls == ["activate"]


def test_on_stop_reaches_children_whose_tab_was_never_shown():
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    host.create_widget()

    host.on_stop()

    assert "stop" in a.calls
    assert "stop" in b.calls


def test_a_child_that_raises_on_start_disables_only_its_own_tab():
    a, bad, c = _Recorder("A"), _Recorder("Bad", fail_on_start=True), _Recorder("C")
    host = _host(a, bad, c)

    host.on_start(_FakeApp())
    tabs = host.create_widget()

    assert tabs.isTabEnabled(0) is True
    assert tabs.isTabEnabled(1) is False
    assert tabs.isTabEnabled(2) is True
    assert "start" in c.calls


def test_a_crashed_child_does_not_claim_it_needs_admin():
    """The wrong reason here costs someone an elevated relaunch to disprove."""
    bad = _Recorder("Bad", fail_on_start=True)
    host = _host(_Recorder("A"), bad)
    host.on_start(_FakeApp())
    host.create_widget()

    assert "administrator" not in host.disabled_reason("Bad").lower()
    assert "log" in host.disabled_reason("Bad").lower()


def test_an_admin_child_is_a_disabled_tab_when_unelevated():
    plain, admin_child = _Recorder("Plain"), _Recorder("Admin", requires_admin=True)
    host = _host(plain, admin_child, admin=False)

    host.on_start(_FakeApp())
    tabs = host.create_widget()

    assert tabs.isTabEnabled(0) is True
    assert tabs.isTabEnabled(1) is False
    assert "administrator" in host.disabled_reason("Admin").lower()
    assert "start" not in admin_child.calls
    assert host.requires_admin is False


def test_wrap_lets_a_host_keep_its_own_chrome_around_the_tabs():
    from PyQt6.QtWidgets import QVBoxLayout, QWidget as _QW

    class _Chromed(CompositeModule):
        name = "Chromed"
        icon = "C"
        description = "chromed"
        group = ModuleGroup.TOOLS

        def __init__(self):
            super().__init__()
            self.children = [_Recorder("A")]

        def wrap(self, tabs):
            root = _QW()
            layout = QVBoxLayout(root)
            layout.addWidget(QLabel("search bar"))
            layout.addWidget(tabs)
            return root

    host = _Chromed()
    host._is_admin = lambda: True
    host.on_start(_FakeApp())

    widget = host.create_widget()

    assert not isinstance(widget, QTabWidget)
    assert widget.findChild(QTabWidget) is not None
    assert host.select_child("A") is True


def test_the_host_gathers_its_children_search_providers():
    pa, pb = _Provider("A"), _Provider("B")
    host = _host(_Recorder("A", pa), _Recorder("B", pb))

    assert host.get_search_providers() == [pa, pb]


def test_the_route_map_resolves_each_child_to_its_host_and_tab():
    host = _host(_Recorder("A"), _Recorder("B"), _Recorder("C"))

    assert host.route_map() == {
        "A": ("Host", 0),
        "B": ("Host", 1),
        "C": ("Host", 2),
    }


def test_select_child_switches_the_tab_and_reports_unknown_names():
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    widget = host.create_widget()

    assert host.select_child("B") is True
    assert widget.currentIndex() == 1
    assert host.select_child("Nope") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.composite_module'`

- [ ] **Step 3: Write the implementation**

Create `src/core/composite_module.py`:

```python
"""A module that hosts other modules as tabs.

Several features in this app are three or four sibling views of one subject —
the network tools, the boot tools, the six diagnostic log readers. Each used to
be its own sidebar entry, which made the sidebar long and made `TOOLS` a drawer.

A `CompositeModule` presents its children as tabs and forwards the module
lifecycle to them, so a child stays an ordinary `BaseModule` that knows nothing
about being hosted. That matters for two reasons: a child can be tested on its
own, and a child can be moved between hosts without being rewritten.

The forwarding rule that earns its keep is on tab change: the outgoing child is
deactivated before the incoming one is activated. Children stop their refresh
timers in `on_deactivate`, so without it a host with three children polls WMI
three times over for as long as the app is open — invisible in tests, obvious
in Task Manager.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt

from core.admin_utils import is_admin
from core.base_module import BaseModule

if TYPE_CHECKING:
    from core.search_provider import SearchProvider

logger = logging.getLogger(__name__)


class CompositeModule(BaseModule):
    """Hosts `children` as tabs. Subclasses set `children` in `__init__`."""

    #: Always False. The host itself is never gated, so it keeps its sidebar
    #: entry when only *some* children need elevation; each gated child becomes
    #: a disabled tab explaining itself (see `_gate_reason`).
    requires_admin = False

    def __init__(self) -> None:
        super().__init__()
        self.children: List[BaseModule] = []
        self._tabs: Optional[QTabWidget] = None
        #: index -> child, for tabs that are live (started, not gated)
        self._live: Dict[int, BaseModule] = {}
        #: index -> why this tab is disabled. Admin gating and a crash in
        #: on_start both disable a tab, and they are not the same thing to
        #: whoever is reading the tab.
        self._disabled: Dict[int, str] = {}
        #: index -> the permanent page a child's widget gets added into
        self._pages: Dict[int, QWidget] = {}
        #: indices whose real widget has been built
        self._built: set = set()
        self._current: int = -1

    # -- seam so tests can pretend to be elevated ------------------------
    def _is_admin(self) -> bool:
        return is_admin()

    # -- lifecycle -------------------------------------------------------
    def on_start(self, app) -> None:
        self.app = app
        elevated = self._is_admin()
        for index, child in enumerate(self.children):
            if child.requires_admin and not elevated:
                logger.info(
                    "%s: child '%s' requires admin — tab disabled",
                    self.name, child.name,
                )
                self._disabled[index] = (
                    f"⚠️ {child.name} requires administrator privileges.\n\n"
                    "Restart the application as Administrator to enable this tab."
                )
                continue
            try:
                child.on_start(app)
            except Exception:
                logger.exception(
                    "%s: child '%s' failed to start — tab disabled",
                    self.name, child.name,
                )
                self._disabled[index] = (
                    f"⚠️ {child.name} could not start.\n\n"
                    "The details are in the application log."
                )
                continue
            self._live[index] = child

    def on_stop(self) -> None:
        for child in self._live.values():
            try:
                child.on_stop()
            except Exception:
                logger.exception("%s: child '%s' failed to stop", self.name, child.name)
        self.cancel_all_workers()

    def on_activate(self) -> None:
        child = self._live.get(self._current)
        if child is not None:
            child.on_activate()

    def on_deactivate(self) -> None:
        child = self._live.get(self._current)
        if child is not None:
            child.on_deactivate()

    def refresh_data(self) -> None:
        child = self._live.get(self._current)
        if child is not None:
            child.refresh_data()

    # -- widget ----------------------------------------------------------
    def create_widget(self) -> QWidget:
        self._tabs = QTabWidget()
        for index, child in enumerate(self.children):
            label = f"{getattr(child, 'icon', '')} {child.name}".strip()
            # Every tab gets a permanent page with a layout. A lazily built
            # child widget is ADDED to that layout later; the page itself is
            # never swapped out. Swapping (removeTab/insertTab) on the current
            # index fires currentChanged again and re-enters the handler that
            # asked for the build.
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            self._pages[index] = page
            self._tabs.addTab(page, label)
            if index not in self._live:
                layout.addWidget(self._notice(self._disabled.get(
                    index, f"{child.name} is unavailable.")))
                self._tabs.setTabEnabled(index, False)

        # Connect only after every tab is in place: addTab() fires
        # currentChanged(0) synchronously for the first tab, and connecting
        # first would build a child during create_widget(). DiagnoseModule
        # learned this the hard way — see its comment at create_widget.
        self._tabs.currentChanged.connect(self._on_tab_changed)

        first = self._first_live_index()
        if first is not None:
            self._current = first
            self._tabs.setCurrentIndex(first)
            self._ensure_built(first)
        return self.wrap(self._tabs)

    def wrap(self, tabs: QTabWidget) -> QWidget:
        """Return the widget the shell should show. Override to add chrome.

        Default is the bare tab widget. `DiagnoseModule` overrides this to keep
        its unified search bar and results tree above the tabs.
        """
        return tabs

    def disabled_reason(self, child_name: str) -> str:
        """Why that child's tab is disabled, or "" if it is live."""
        for index, child in enumerate(self.children):
            if child.name == child_name:
                return self._disabled.get(index, "")
        return ""

    def _first_live_index(self) -> Optional[int]:
        for index in range(len(self.children)):
            if index in self._live:
                return index
        return None

    def _notice(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def _ensure_built(self, index: int) -> None:
        if index in self._built:
            return
        child = self._live.get(index)
        page = self._pages.get(index)
        if child is None or page is None or self._tabs is None:
            return
        self._built.add(index)  # set first: a failed build must not retry
        try:
            widget = child.create_widget()
        except Exception:
            logger.exception(
                "%s: child '%s' failed to build its widget", self.name, child.name
            )
            self._disabled[index] = (
                f"⚠️ {child.name} could not be displayed.\n\n"
                "The details are in the application log."
            )
            widget = self._notice(self._disabled[index])
            self._tabs.setTabEnabled(index, False)
            self._live.pop(index, None)
        page.layout().addWidget(widget)

    def _on_tab_changed(self, index: int) -> None:
        if index == self._current:
            return
        outgoing = self._live.get(self._current)
        self._current = index
        if outgoing is not None:
            try:
                outgoing.on_deactivate()
            except Exception:
                logger.exception("%s: on_deactivate failed", self.name)
        self._ensure_built(index)
        incoming = self._live.get(index)
        if incoming is not None:
            try:
                incoming.on_activate()
            except Exception:
                logger.exception("%s: on_activate failed", self.name)

    # -- search and navigation -------------------------------------------
    def get_search_providers(self) -> List["SearchProvider"]:
        providers: List["SearchProvider"] = []
        for child in self.children:
            providers.extend(child.get_search_providers())
        return providers

    def route_map(self) -> Dict[str, Tuple[str, int]]:
        """`{child name: (this host's name, tab index)}` for name-based nav."""
        return {child.name: (self.name, i) for i, child in enumerate(self.children)}

    def select_child(self, name: str) -> bool:
        for index, child in enumerate(self.children):
            if child.name == name:
                if self._tabs is not None:
                    self._tabs.setCurrentIndex(index)
                return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: 14 passed

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 1346 passed, 3 skipped

- [ ] **Step 6: Commit**

```bash
git add src/core/composite_module.py tests/test_composite_module.py
git commit -m "feat(core): CompositeModule hosts modules as tabs"
```

---

### Task 3: Registry exposes the merged route map

**Files:**
- Modify: `src/core/module_registry.py`
- Test: `tests/test_composite_module.py` (append)

**Interfaces:**
- Consumes: `CompositeModule.route_map()` (Task 2).
- Produces: `ModuleRegistry.route_map() -> dict[str, tuple[str, int | None]]` — merges every composite's map plus `ModuleRegistry.ALIASES`. The int is a tab index, or `None` for an alias that names a whole module.
- `ModuleRegistry.ALIASES: dict[str, tuple[str, None]]` — retired names kept navigable. Starts as `{"Duplicate Finder": ("TreeSize", None)}` (added in Task 7, when Duplicate Finder is actually deleted).

- [ ] **Step 1: Write the failing test**

```python
def test_registry_route_map_merges_every_composite():
    host_a = _host(_Recorder("A1"), _Recorder("A2"))
    host_b = _host(_Recorder("B1"))
    host_b.name = "Host B"

    registry = ModuleRegistry()
    registry.register(host_a)
    registry.register(host_b)
    registry.register(_Leaf(None))

    routes = registry.route_map()

    assert routes["A2"] == ("Host", 1)
    assert routes["B1"] == ("Host B", 0)
    assert "Leaf" not in routes  # a plain module is found by the sidebar itself


def test_registry_route_map_includes_aliases():
    registry = ModuleRegistry()
    registry.ALIASES = {"Old Name": ("New Home", None)}

    assert registry.route_map()["Old Name"] == ("New Home", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -k route_map -v`
Expected: FAIL — `AttributeError: 'ModuleRegistry' object has no attribute 'route_map'`

- [ ] **Step 3: Implement**

In `src/core/module_registry.py`, add the import and the method:

```python
from typing import Dict, List, Optional, Tuple
```

```python
class ModuleRegistry:
    #: Names that outlived their module. A retired sidebar entry stays
    #: navigable — from the command palette, from a NAV_REQUEST_MODULE — by
    #: pointing at whatever absorbed it. `None` means "the whole module",
    #: as opposed to a composite child's tab index.
    ALIASES: Dict[str, Tuple[str, Optional[int]]] = {}
```

```python
    def route_map(self) -> Dict[str, Tuple[str, Optional[int]]]:
        """Names that are not sidebar entries, mapped to where they now live.

        `MainWindow` consults this only when a name misses the sidebar, so a
        real module always wins over a route of the same name.
        """
        routes: Dict[str, Tuple[str, Optional[int]]] = {}
        for module in self._modules:
            get_routes = getattr(module, "route_map", None)
            if callable(get_routes):
                routes.update(get_routes())
        routes.update(self.ALIASES)
        return routes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add src/core/module_registry.py tests/test_composite_module.py
git commit -m "feat(core): registry merges composite route maps and aliases"
```

---

### Task 4: `MainWindow` navigates through the route map

**Files:**
- Modify: `src/ui/main_window.py:342-344`
- Test: `tests/test_composite_module.py` (append)

**Interfaces:**
- Consumes: `ModuleRegistry.route_map()` (Task 3), `CompositeModule.select_child()` (Task 2).
- Produces: `MainWindow._navigate_to_module(name)` resolves child and alias names. No new public API.

Read `src/ui/main_window.py:342` before editing — the current body is three lines and both the `NAV_REQUEST_MODULE` handler (`main_window.py:123`) and the command palette (`main_window.py:333`) call it.

- [ ] **Step 1: Write the failing test**

The test drives the resolution logic without building a `MainWindow` (which needs the full `App` singleton). Extract the decision into a helper that the window calls, and test the helper:

```python
def test_resolving_a_child_name_yields_its_host_and_tab():
    from ui.navigation import resolve_target

    routes = {"Wi-Fi Analyzer": ("Network Diagnostics", 1)}

    assert resolve_target("Network Diagnostics", {"Network Diagnostics"}, routes) == (
        "Network Diagnostics", None)
    assert resolve_target("Wi-Fi Analyzer", {"Network Diagnostics"}, routes) == (
        "Network Diagnostics", 1)


def test_a_sidebar_entry_wins_over_a_route_of_the_same_name():
    from ui.navigation import resolve_target

    routes = {"Debloat": ("Somewhere Else", 3)}

    assert resolve_target("Debloat", {"Debloat"}, routes) == ("Debloat", None)


def test_an_unknown_name_resolves_to_nothing():
    from ui.navigation import resolve_target

    assert resolve_target("Nope", {"Debloat"}, {}) == (None, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -k resolve -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.navigation'`

- [ ] **Step 3: Write the helper**

Create `src/ui/navigation.py`:

```python
"""Where a module name should take you.

Kept apart from MainWindow so the rule can be tested without an App singleton
and a real window: this is pure name resolution, no Qt.
"""
from typing import Dict, Optional, Set, Tuple


def resolve_target(
    name: str,
    sidebar_names: Set[str],
    routes: Dict[str, Tuple[str, Optional[int]]],
) -> Tuple[Optional[str], Optional[int]]:
    """Resolve `name` to `(module to select, tab index or None)`.

    A real sidebar entry always wins, so a composite child cannot shadow a
    module that still has its own entry. Anything unknown resolves to
    `(None, None)` and the caller does nothing — the same as today's miss.
    """
    if name in sidebar_names:
        return name, None
    host, tab = routes.get(name, (None, None))
    if host is None:
        return None, None
    return host, tab
```

- [ ] **Step 4: Wire it into MainWindow**

Replace `_navigate_to_module` at `src/ui/main_window.py:342`:

```python
    def _navigate_to_module(self, name: str) -> None:
        from ui.navigation import resolve_target

        target, tab = resolve_target(
            name,
            set(self._module_map),
            self._app.module_registry.route_map(),
        )
        if target is None:
            logger.warning("Navigation: nothing named %r", name)
            return
        self._sidebar.select(target)
        self._on_module_selected(target)
        if tab is not None:
            module = self._module_map.get(target)
            select_child = getattr(module, "select_child", None)
            if callable(select_child):
                select_child(name)
```

Check that `logger` exists in `main_window.py`; if not, add `logger = logging.getLogger(__name__)` beside the imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_composite_module.py -v`
Expected: 19 passed

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 1351 passed, 3 skipped

- [ ] **Step 7: Commit**

```bash
git add src/ui/navigation.py src/ui/main_window.py tests/test_composite_module.py
git commit -m "feat(ui): navigate to a name that now lives inside a composite"
```

---

# Phase 2 — Session log retention

### Task 5: `keep_newest` and the config key

**Files:**
- Modify: `src/core/log_rotation.py`, `src/app.py:73-84`, `config/default_config.json`
- Test: `tests/test_log_retention_count.py` (new)

**Interfaces:**
- Produces: `keep_newest(directory: str, glob_pattern: str, keep: int) -> int` — deletes all but the `keep` newest matches by mtime, returns how many it deleted. `keep <= 0` is a no-op.
- Config key `app.log_retention_count`, default `20`.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_log_retention_count.py

101 session logs accumulated in the repo root in two days: one file per
launch, and rotation was 30-day only.
"""
import os
import time

from core.log_rotation import keep_newest, rotate_old_files


def _write(tmp_path, name, age_days=0):
    path = tmp_path / name
    path.write_text("x", encoding="utf-8")
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
    return path


def test_keeps_the_newest_and_deletes_the_rest(tmp_path):
    for i in range(10):
        _write(tmp_path, f"VRK_{i}.log", age_days=10 - i)

    deleted = keep_newest(str(tmp_path), "*.log", 3)

    assert deleted == 7
    survivors = sorted(p.name for p in tmp_path.iterdir())
    assert survivors == ["VRK_7.log", "VRK_8.log", "VRK_9.log"]


def test_is_a_no_op_when_there_are_fewer_files_than_the_cap(tmp_path):
    _write(tmp_path, "a.log")
    _write(tmp_path, "b.log")

    assert keep_newest(str(tmp_path), "*.log", 20) == 0
    assert len(list(tmp_path.iterdir())) == 2


def test_zero_keeps_everything(tmp_path):
    for i in range(5):
        _write(tmp_path, f"{i}.log", age_days=i)

    assert keep_newest(str(tmp_path), "*.log", 0) == 0
    assert len(list(tmp_path.iterdir())) == 5


def test_only_touches_the_pattern(tmp_path):
    for i in range(5):
        _write(tmp_path, f"{i}.log", age_days=i)
    _write(tmp_path, "keep-me.txt", age_days=99)

    keep_newest(str(tmp_path), "*.log", 1)

    assert (tmp_path / "keep-me.txt").exists()


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert keep_newest(str(tmp_path / "nope"), "*.log", 5) == 0


def test_the_two_rules_compose(tmp_path):
    """Old AND within the newest N still goes: either rule may delete."""
    for i in range(30):
        _write(tmp_path, f"{i:02d}.log", age_days=40)

    rotate_old_files(str(tmp_path), "*.log", 30)

    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_log_retention_count.py -v`
Expected: FAIL — `ImportError: cannot import name 'keep_newest'`

- [ ] **Step 3: Implement `keep_newest`**

Append to `src/core/log_rotation.py`:

```python
def keep_newest(directory: str, glob_pattern: str, keep: int) -> int:
    """Delete all but the `keep` newest files matching `glob_pattern`.

    The age rule alone is not enough for the session log, which gets one file
    per launch: a development day produces dozens, all of them well inside the
    30-day window. Both rules run and either may delete.

    `keep <= 0` means "keep everything", matching `rotate_old_files`'
    convention for `retention_days`. Returns the number deleted.
    """
    if keep <= 0:
        return 0
    if not directory or not os.path.isdir(directory):
        return 0

    try:
        candidates = [p for p in glob.glob(os.path.join(directory, glob_pattern))
                      if os.path.isfile(p)]
    except Exception:
        logger.warning("Log rotation: failed to list %s", directory, exc_info=True)
        return 0

    if len(candidates) <= keep:
        return 0

    # Newest first, so everything past `keep` is what we drop.
    try:
        candidates.sort(key=os.path.getmtime, reverse=True)
    except Exception:
        logger.warning("Log rotation: failed to sort %s", directory, exc_info=True)
        return 0

    deleted = 0
    for path in candidates[keep:]:
        try:
            os.remove(path)
            deleted += 1
        except Exception:
            logger.warning("Log rotation: could not remove %s", path, exc_info=True)

    if deleted:
        logger.info(
            "Log rotation: removed %d file(s) past the newest %d in %s",
            deleted, keep, directory,
        )
    return deleted
```

- [ ] **Step 4: Call it at startup**

In `src/app.py`, inside the existing rotation `try:` block, after the two `rotate_old_files` calls:

```python
            from core.log_rotation import keep_newest, rotate_old_files
```

```python
            # The session log gets one file per launch, so the age rule alone
            # never catches a busy day. 101 files piled up in two days.
            keep_newest(
                self.logger.session_log_dir,
                "*.log",
                self.config.get("app.log_retention_count", 20),
            )
```

- [ ] **Step 5: Add the config default**

In `config/default_config.json`, beside `"log_retention_days": 30`:

```json
    "log_retention_count": 20,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_log_retention_count.py -v`
Expected: 6 passed

- [ ] **Step 7: Verify against the real pile**

The repo root holds ~101 `VRK_*.log` files. Count them, run the app once from source, count again:

```bash
ls VRK_*.log | wc -l
.venv/Scripts/python.exe src/main.py   # close the window once it opens
ls VRK_*.log | wc -l
```

Expected: the second count is 20 (19 survivors plus the log the run just wrote). This is the check that the wiring in `app.py` is real, which the unit tests cannot tell you.

- [ ] **Step 8: Commit**

```bash
git add src/core/log_rotation.py src/app.py config/default_config.json tests/test_log_retention_count.py
git commit -m "feat(logging): cap session logs by count, not just age"
```

---

# Phase 3 — Delete Duplicate Finder

### Task 6: Remove the module and its tests

**Files:**
- Delete: `src/modules/duplicate_finder/`, `tests/test_duplicate_finder.py`
- Modify: `src/main.py` (import + registration), `src/modules/treesize/treesize_module.py` (description)
- Test: `tests/test_module_inventory.py` (new)

**Interfaces:**
- Consumes: `ModuleRegistry.ALIASES` (Task 3).
- Produces: nothing new.

Confirm the test file name first — `ls tests | grep -i duplicate` — the duplicate tests may live under a TreeSize name too. Only delete the ones that import `modules.duplicate_finder`.

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_module_inventory.py — what the sidebar is made of."""
import pytest

import main as app_main


class _FakeRegistry:
    def __init__(self):
        self.modules = []

    def register(self, module):
        self.modules.append(module)


class _FakeApp:
    def __init__(self):
        self.module_registry = _FakeRegistry()


@pytest.fixture
def registered():
    app = _FakeApp()
    app_main.register_all_modules(app)
    return app.module_registry.modules


def test_duplicate_finder_is_gone(registered):
    assert "Duplicate Finder" not in {m.name for m in registered}


def test_nothing_imports_the_duplicate_finder_package():
    with pytest.raises(ModuleNotFoundError):
        __import__("modules.duplicate_finder.duplicate_finder_module")


def test_module_names_are_unique(registered):
    names = [m.name for m in registered]
    assert len(names) == len(set(names))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: FAIL — Duplicate Finder is still registered and still importable

- [ ] **Step 3: Delete it**

```bash
git rm -r src/modules/duplicate_finder
git rm tests/test_duplicate_finder.py
```

Remove from `src/main.py` both the import line (`from modules.duplicate_finder.duplicate_finder_module import DuplicateFinderModule`) and `app.module_registry.register(DuplicateFinderModule())`.

- [ ] **Step 4: Keep the name navigable**

In `src/core/module_registry.py`, fill in the alias table declared in Task 3:

```python
    ALIASES: Dict[str, Tuple[str, Optional[int]]] = {
        # Duplicate Finder was deleted: it full-MD5-hashed every file, where
        # TreeSize groups by size first and hashes almost nothing. The name
        # stays navigable so anyone who reaches for it lands somewhere useful.
        "Duplicate Finder": ("TreeSize", None),
    }
```

- [ ] **Step 5: Say where it went**

In `src/modules/treesize/treesize_module.py`, extend `description` to name duplicate files, e.g.:

```python
    description = "Disk space analyzer — sizes, duplicate files, and file search"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: 3 passed

- [ ] **Step 7: Check nothing else referenced it**

```bash
grep -rn "duplicate_finder\|DuplicateFinder" --include=*.py --include=*.spec --include=*.md src tests tools *.spec
```

Expected: only the alias comment and the CHANGELOG. Fix any hit in `hooks/` or the PyInstaller specs — a stale hidden-import there breaks the build, not the suite.

- [ ] **Step 8: Full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: green, with the duplicate-finder tests gone from the count

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: delete Duplicate Finder in favour of TreeSize's"
```

---

# Phase 4 — Debloat ← Store Apps

### Task 7: Make Debloat a composite

**Files:**
- Modify: `src/modules/debloat/debloat_module.py`, `src/main.py`
- Test: `tests/test_module_inventory.py` (append)

**Interfaces:**
- Consumes: `CompositeModule` (Task 2).
- Produces: `DebloatModule.children == [_DebloatOwnModule(), StoreAppsModule()]`.

The shape here is the one every remaining merge uses: the host's existing widget becomes a child in its own right, so the host class holds *no* UI of its own.

- [ ] **Step 1: Write the failing test**

```python
def test_store_apps_is_a_debloat_tab_not_a_sidebar_entry(registered):
    names = {m.name for m in registered}
    assert "Store Apps" not in names
    debloat = next(m for m in registered if m.name == "Debloat")
    assert [c.name for c in debloat.children] == ["Debloat", "Store Apps"]


def test_store_apps_is_still_reachable_by_name(registered):
    from core.module_registry import ModuleRegistry

    registry = ModuleRegistry()
    for module in registered:
        registry.register(module)

    assert registry.route_map()["Store Apps"] == ("Debloat", 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: FAIL — "Store Apps" is still its own entry

- [ ] **Step 3: Split the existing Debloat into a child**

In `src/modules/debloat/debloat_module.py`, rename the current class to `DebloatToolsModule` and leave it otherwise untouched — same widget, same `create_widget`, same lifecycle. Change only its `name`:

```python
class DebloatToolsModule(BaseModule):
    name = "Debloat"          # the tab label
    icon = "⚡"
    description = "Remove bloatware, disable telemetry, and harden privacy"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE
```

- [ ] **Step 4: Add the host**

At the bottom of the same file:

```python
class DebloatModule(CompositeModule):
    """Debloat's own tools plus the full AppX package list beside them.

    Store Apps used to be its own sidebar entry two groups away, which is a
    strange place to put the list you want open while deciding what a curated
    blocklist should contain.
    """

    name = "Debloat"
    icon = "⚡"
    description = "Remove bloatware and manage installed Store apps"
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        from modules.store_apps.store_apps_module import StoreAppsModule

        self.children = [DebloatToolsModule(), StoreAppsModule()]
```

Add `from core.composite_module import CompositeModule` to the imports.

- [ ] **Step 5: Drop Store Apps from the registration list**

In `src/main.py`, remove the `StoreAppsModule` import and its `register(...)` line. `DebloatModule` stays registered exactly as it is.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: 5 passed

- [ ] **Step 7: Run the app and look at it**

```bash
.venv/Scripts/python.exe src/main.py
```

Check, in the window: Debloat shows two tabs; its own tabs (Apps / Privacy & Telemetry / AI & Navigation) are intact inside the first; Store Apps lists packages in the second; switching away and back does not re-run the scan twice; Store Apps is gone from MANAGE. A green suite does not tell you any of this.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(debloat): Store Apps becomes a Debloat tab"
```

---

# Phase 5 — Startup & Boot

### Task 8: Startup Manager hosts Boot Analyzer and Power & Boot

**Files:**
- Modify: `src/modules/startup_manager/startup_module.py`, `src/main.py`
- Test: `tests/test_module_inventory.py` (append)

**Interfaces:**
- Consumes: `CompositeModule` (Task 2).
- Produces: `StartupBootModule` with `name = "Startup & Boot"`, `group = ModuleGroup.SYSTEM`, children `["Startup Manager", "Boot Analyzer", "Power & Boot"]`.

- [ ] **Step 1: Write the failing test**

```python
def test_startup_and_boot_hosts_the_three_boot_modules(registered):
    names = {m.name for m in registered}
    assert "Boot Analyzer" not in names
    assert "Power & Boot" not in names
    host = next(m for m in registered if m.name == "Startup & Boot")
    assert [c.name for c in host.children] == [
        "Startup Manager", "Boot Analyzer", "Power & Boot",
    ]
    assert host.group == "SYSTEM"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -k startup -v`
Expected: FAIL — no module named "Startup & Boot"

- [ ] **Step 3: Implement**

In `src/modules/startup_manager/startup_module.py`, rename the existing class to `StartupItemsModule` (keeping `name = "Startup Manager"` and everything else), then add:

```python
class StartupBootModule(CompositeModule):
    """Everything that decides what happens between power-on and a desktop.

    These were three sidebar entries in two different groups: what starts, how
    fast it started, and the power/boot settings that govern both.
    """

    name = "Startup & Boot"
    icon = "🚀"
    description = "Startup items, boot timing, and power and boot configuration"
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        from modules.boot_analyzer.boot_analyzer_module import BootAnalyzerModule
        from modules.power_boot.power_module import PowerBootModule

        self.children = [StartupItemsModule(), BootAnalyzerModule(), PowerBootModule()]
```

- [ ] **Step 4: Update registration**

In `src/main.py`: import `StartupBootModule` instead of `StartupModule`, register it, and delete the `BootAnalyzerModule` and `PowerBootModule` imports and registrations.

If anything else imports `StartupModule` by name, point it at `StartupItemsModule`:

```bash
grep -rn "StartupModule" --include=*.py src tests tools
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: 6 passed

- [ ] **Step 6: Run the app and look at it**

Check: three tabs; the Startup Manager tab still shows its own inner tabs; Boot Analyzer's timing loads; Power & Boot's plan list is populated; MANAGE lost an entry and SYSTEM gained one.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: one Startup & Boot module instead of three entries"
```

---

# Phase 6 — Network Diagnostics

### Task 9: Drop the duplicate HOSTS tab from Network Extras

**Files:**
- Modify: `src/modules/network_extras/net_extras_module.py`
- Test: `tests/test_module_inventory.py` (append)

**Interfaces:**
- Produces: `NetExtrasModule` with three tabs — DNS Switcher, Proxy Settings, Quick Actions.

Do this before the merge, so the "two HOSTS editors" problem is gone before three modules move at once.

- [ ] **Step 1: Write the failing test**

```python
def test_network_extras_no_longer_carries_its_own_hosts_editor(qapp):
    from modules.network_extras.net_extras_module import NetExtrasModule

    widget = NetExtrasModule().create_widget()
    labels = [widget.tabText(i) for i in range(widget.count())]

    assert labels == ["DNS Switcher", "Proxy Settings", "Quick Actions"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -k hosts -v`
Expected: FAIL — the first tab is still "HOSTS Editor"

- [ ] **Step 3: Remove the tab**

In `net_extras_module.py`, delete the `tabs.addTab(self._make_hosts_tab(), "HOSTS Editor")` line (~line 100) and the `_make_hosts_tab` method. Then check whether `_backup_file`, `parse_hosts` and `save_hosts` (lines 28-71) are still used by anything in this file or elsewhere:

```bash
grep -rn "parse_hosts\|save_hosts\|_backup_file" --include=*.py src tests
```

Delete the ones nothing calls. If `hosts_editor` imports them, leave them and note it — do not move code between modules in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -k hosts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(network): one HOSTS editor, not two"
```

---

### Task 10: Network Diagnostics hosts the network tools

**Files:**
- Modify: `src/modules/network_diagnostics/network_module.py`, `src/main.py`
- Test: `tests/test_module_inventory.py` (append)

**Interfaces:**
- Consumes: `CompositeModule` (Task 2).
- Produces: `NetworkDiagnosticsModule` (composite) with children `["Network Diagnostics", "Wi-Fi Analyzer", "Hosts Editor", "Network Extras"]`.

`network_module.py` does not use tabs today (`create_widget` at line 967 returns one widget), so its existing class becomes the first child unchanged.

- [ ] **Step 1: Write the failing test**

```python
def test_the_network_tools_are_tabs_of_network_diagnostics(registered):
    names = {m.name for m in registered}
    for gone in ("Wi-Fi Analyzer", "Hosts Editor", "Network Extras"):
        assert gone not in names
    host = next(m for m in registered if m.name == "Network Diagnostics")
    assert [c.name for c in host.children] == [
        "Network Diagnostics", "Wi-Fi Analyzer", "Hosts Editor", "Network Extras",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -k network -v`
Expected: FAIL — the three are still their own entries

- [ ] **Step 3: Implement**

In `network_module.py`, rename the existing module class to `NetworkToolsModule` (keep `name = "Network Diagnostics"`), then add:

```python
class NetworkDiagnosticsModule(CompositeModule):
    """The network tools in one place: diagnostics, Wi-Fi, HOSTS, DNS/proxy."""

    name = "Network Diagnostics"
    icon = "🌐"
    description = "Connectivity diagnostics, Wi-Fi, HOSTS, DNS and proxy"
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        from modules.hosts_editor.hosts_editor_module import HostsEditorModule
        from modules.network_extras.net_extras_module import NetExtrasModule
        from modules.wifi_analyzer.wifi_module import WifiAnalyzerModule

        self.children = [
            NetworkToolsModule(),
            WifiAnalyzerModule(),
            HostsEditorModule(),
            NetExtrasModule(),
        ]
```

Note `HostsEditorModule` has `requires_admin = True`, so unelevated it becomes a disabled tab while the other three still work — the Task 2 behaviour, now exercised for real.

- [ ] **Step 4: Update registration**

In `src/main.py`, remove the `WifiAnalyzerModule`, `HostsEditorModule` and `NetExtrasModule` imports and registrations. `NetworkDiagnosticsModule` stays.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: 8 passed

- [ ] **Step 6: Run the app twice — unelevated, then elevated**

Unelevated: four tabs, Hosts Editor disabled with the admin message, the other three working.
Elevated (via `launch_admin.bat`): all four live, HOSTS loads and saves.
Also confirm the diagnostics tab's own long-running actions (ping, tracert) still stream, and that leaving the module stops them.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(network): Wi-Fi, HOSTS and extras become network tabs"
```

---

# Phase 7 — LogPane and the six diagnostic modules

### Task 11: Extract `LogPane` from Diagnose

**Files:**
- Create: `src/ui/log_pane.py`
- Modify: `src/modules/diagnose/diagnose_module.py` (replace `_build_tab_widget`, lines ~100-160)
- Modify: `src/ui/error_banner.py` (add `text()`)
- Test: `tests/test_log_pane.py` (new)

**Interfaces:**
- Consumes: `LogTableWidget`, `DetailPanel`, `ErrorBanner`, `core.worker.Worker`.
- Produces:

```python
class LogPane(QWidget):
    def __init__(self, loader, *, empty_text="No data — click Refresh",
                 extra_controls=None, parent=None): ...
    def load(self) -> None: ...        # runs `loader` on a Worker, fills the table
    def set_entries(self, entries) -> None: ...
    def show_error(self, message: str) -> None: ...
    entry_selected: pyqtSignal        # emits the selected LogEntry
```

`loader` is `Callable[[Worker], list[LogEntry]]` — the same worker-function shape the rest of the app uses (`worker.is_cancelled` is a property; emit progress via `worker.signals.progress`).

Read the current `_build_tab_widget` and the six `_load_*` methods in `diagnose_module.py` before writing this. The extraction must preserve: Refresh button, progress bar, error banner, the empty-state page in a `QStackedWidget`, the table/detail splitter at 700/300, and the extra-controls hook (Event Viewer's hours combo).

- [ ] **Step 1: Write the failing test**

```python
"""tests/test_log_pane.py"""
from datetime import datetime

from core.types import LogEntry
from ui.log_pane import LogPane


def _entry(message="hello"):
    # LogEntry's real fields, from core/types.py:7
    return LogEntry(
        timestamp=datetime(2026, 8, 21, 12, 0, 0),
        source="test",
        level="Information",
        message=message,
    )


def test_it_starts_on_the_empty_page(qapp):
    pane = LogPane(loader=lambda worker: [])
    assert pane.is_showing_empty_state() is True


def test_set_entries_fills_the_table_and_leaves_the_empty_page(qapp):
    pane = LogPane(loader=lambda worker: [])

    pane.set_entries([_entry("first"), _entry("second")])

    assert pane.is_showing_empty_state() is False
    assert pane.row_count() == 2


def test_an_error_shows_the_banner_and_keeps_the_pane_usable(qapp):
    pane = LogPane(loader=lambda worker: [])

    pane.show_error("C:\\Windows\\Logs\\CBS\\CBS.log not found")

    assert pane.is_showing_error() is True
    assert "CBS.log" in pane.error_text()
    assert pane.row_count() == 0  # an error must not wipe what is on screen


def test_extra_controls_land_in_the_toolbar(qapp):
    from PyQt6.QtWidgets import QComboBox

    seen = {}

    def add_controls(toolbar, extra):
        combo = QComboBox()
        combo.addItems(["24", "48"])
        toolbar.addWidget(combo)
        extra["hours"] = combo
        seen["called"] = True

    pane = LogPane(loader=lambda worker: [], extra_controls=add_controls)

    assert seen["called"] is True
    assert pane.extra["hours"].count() == 2
```

`LogEntry`'s fields above are the real ones (`core/types.py:7`): `timestamp`, `source`, `level`, `message`, `raw`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_log_pane.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.log_pane'`

- [ ] **Step 3: Write `LogPane`**

Create `src/ui/log_pane.py`. This is `_build_tab_widget` (`diagnose_module.py:100-158`) plus the load/progress/error plumbing from `_do_tab_load`, `_on_tab_loaded` and `_on_tab_error` (`diagnose_module.py:452-520`), with the per-tab `dict` state replaced by attributes:

```python
"""One log-reading pane: toolbar, table, detail panel, error banner.

Six diagnostic tabs and six standalone modules were two implementations of
this widget. The Diagnose one had a Refresh button, an empty state, lazy
loading and an error banner; the module one had none of them. This is the
Diagnose one, extracted so there is exactly one.

The pane knows nothing about what it is reading. `loader` is an ordinary
worker function — it receives the `Worker` and returns a list of `LogEntry` —
so a caller supplies a parser and nothing else.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.worker import Worker
from ui.detail_panel import DetailPanel
from ui.error_banner import ErrorBanner
from ui.log_table_widget import LogTableWidget

logger = logging.getLogger(__name__)

_PAGE_TABLE = 0
_PAGE_EMPTY = 1


class LogPane(QWidget):
    """A table of log entries with a detail panel, fed by `loader`."""

    entry_selected = pyqtSignal(object)
    entry_activated = pyqtSignal(object)
    entries_loaded = pyqtSignal(object)

    def __init__(
        self,
        loader: Callable[[Worker], list],
        *,
        empty_text: str = "No data — click Refresh",
        extra_controls: Optional[Callable[[QHBoxLayout, dict], None]] = None,
        thread_pool=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._loader = loader
        self._thread_pool = thread_pool
        self._worker: Optional[Worker] = None
        self._entries: List[object] = []
        self.extra: dict = {}
        self.loaded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        if extra_controls is not None:
            extra_controls(toolbar, self.extra)
        toolbar.addStretch()

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        toolbar.addWidget(self._progress)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.clicked.connect(lambda: self.load(force=True))
        toolbar.addWidget(self._refresh_btn)
        root.addLayout(toolbar)

        self._error_banner = ErrorBanner(parent=self)
        root.addWidget(self._error_banner)

        splitter = QSplitter()
        self._table = LogTableWidget()
        splitter.addWidget(self._table)
        self._detail = DetailPanel()
        splitter.addWidget(self._detail)
        splitter.setSizes([700, 300])

        self._stack = QStackedWidget()
        self._stack.addWidget(splitter)
        empty = QLabel(empty_text)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: #888; font-size: 14px;")
        self._stack.addWidget(empty)
        self._stack.setCurrentIndex(_PAGE_EMPTY)
        root.addWidget(self._stack, 1)

        self._table.row_selected.connect(self._on_row_selected)
        self._table.row_double_clicked.connect(self.entry_activated.emit)

    # -- loading ---------------------------------------------------------
    def load(self, force: bool = False) -> None:
        """Run `loader` on a worker and fill the table with what it returns."""
        if self.loaded and not force:
            return
        if self._worker is not None:
            self._worker.cancel()

        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._error_banner.clear()

        worker = Worker(self._loader)
        worker.signals.progress.connect(self._progress.setValue)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        pool = self._thread_pool
        if pool is None:
            from PyQt6.QtCore import QThreadPool
            pool = QThreadPool.globalInstance()
        pool.start(worker)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    def _on_result(self, entries) -> None:
        self._worker = None
        self.loaded = True
        self.set_entries(entries or [])
        self.entries_loaded.emit(self._entries)

    def _on_error(self, error_info) -> None:
        self._worker = None
        self.show_error(str(error_info))

    # -- content ---------------------------------------------------------
    def set_entries(self, entries) -> None:
        self._entries = list(entries or [])
        self._progress.setVisible(False)
        self._table.set_entries(self._entries)
        self._stack.setCurrentIndex(_PAGE_TABLE if self._entries else _PAGE_EMPTY)

    def show_error(self, message: str) -> None:
        self._progress.setVisible(False)
        self._error_banner.set_error(message)

    def _on_row_selected(self, entry) -> None:
        self._detail.show_entry(entry)
        self.entry_selected.emit(entry)

    # -- introspection, for tests and for get_status_info ----------------
    def entries(self) -> List[object]:
        return list(self._entries)

    def row_count(self) -> int:
        return len(self._entries)

    def is_showing_empty_state(self) -> bool:
        return self._stack.currentIndex() == _PAGE_EMPTY

    def is_showing_error(self) -> bool:
        # isHidden(), NOT isVisible(). A child of a parent that has never been
        # shown is not "visible" no matter what you call on it, so isVisible()
        # is False even right after set_error(). show() clears the explicit
        # hide flag, which is what isHidden() reports — and it is what the
        # tests can see without a real window.
        return not self._error_banner.isHidden()

    def error_text(self) -> str:
        return self._error_banner.text()
```

The widget APIs used above were checked against the real files, not assumed:

| Call | Defined at |
|---|---|
| `LogTableWidget.set_entries(List[LogEntry])` | `log_table_widget.py:78` |
| `LogTableWidget.row_selected` / `row_double_clicked` | `log_table_widget.py:40-41`, both emit `LogEntry` |
| `DetailPanel.show_entry(entry)` | `detail_panel.py:26` |
| `ErrorBanner.set_error(message)` / `clear()` | `error_banner.py:35`, `:40` |
| `LogEntry(timestamp, source, level, message, raw={})` | `core/types.py:7` |

`ErrorBanner` has no way to read its text back, so add one — it is two lines and it is what makes the error path testable:

```python
    def text(self) -> str:
        """The message currently shown, without the warning glyph."""
        return self._label.text().lstrip("⚠ ").strip()
```

- [ ] **Step 4: Point Diagnose at it**

Replace `_build_tab_widget` calls in `diagnose_module.py` with `LogPane(...)`, one per tab def, keeping each tab's existing loader function as the `loader`. Delete `_build_tab_widget`. Do not touch the cross-tab search bar.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_log_pane.py tests/test_cbs_parser.py tests/test_dism_parser.py tests/test_event_viewer.py tests/test_reliability.py tests/test_crash_dumps.py tests/test_wu_parser.py -v`
Expected: all pass

- [ ] **Step 6: Run the app and compare against the old build**

Open Diagnose, click through all six tabs. Each must load, show its Refresh button and progress, and populate. Event Viewer must still have its hours combo. Trigger an error path deliberately — rename `C:\Windows\Logs\DISM\dism.log` is not worth it; instead point `DISM_LOG_PATH` at a missing file temporarily and confirm the banner appears rather than a traceback.

- [ ] **Step 7: Commit**

```bash
git add src/ui/log_pane.py src/modules/diagnose/diagnose_module.py tests/test_log_pane.py
git commit -m "refactor(diagnose): one LogPane behind all six tabs"
```

---

### Task 12: Rebuild the six modules on `LogPane` and make Diagnose their host

**Files:**
- Modify: `src/modules/cbs_log/cbs_module.py`, `dism_log/dism_module.py`, `event_viewer/event_viewer_module.py`, `reliability/reliability_module.py`, `crash_dumps/crash_dump_module.py`, `windows_update/wu_module.py`, `diagnose/diagnose_module.py`
- Test: `tests/test_module_inventory.py` (append)

**Interfaces:**
- Consumes: `LogPane` (Task 11), `CompositeModule` (Task 2).
- Produces: `DiagnoseModule` (composite) with the six as children; each child returns its existing search provider from `get_search_provider()`.

Each of the six becomes: metadata + a `LogPane` around its existing parser/reader + its existing search provider. Their old hand-rolled widgets are replaced entirely — those are the thin, older implementation the spec §1.2 describes.

**The loaders move verbatim.** `DiagnoseModule._load_cbs` (`diagnose_module.py:556-618`) is not one line around a parser: it falls back to finding the newest `CbsPersist_*.cab`, extracting it with 7-Zip into a temp dir, parsing that, and cleaning up — because Windows 11 usually has no plain `CBS.log`. Retyping these from the parser's signature would silently drop that. Cut each `do_work` body out of its `_load_*` method and paste it in as the new module's `_load`, changing nothing inside it. The same goes for the other five.

The one call the loaders make that you must keep intact is `worker.signals.progress.emit(...)` — `LogPane` wires that to its progress bar exactly as `_do_tab_load` did.

- [ ] **Step 1: Write the failing test**

```python
def test_diagnose_hosts_the_six_log_readers(registered):
    diagnose = next(m for m in registered if m.name == "Diagnose")
    assert [c.name for c in diagnose.children] == [
        "Event Viewer", "CBS Log", "DISM Log",
        "Windows Update", "Reliability", "Crash Dumps",
    ]


def test_every_diagnostic_source_is_back_in_global_search(registered):
    """The regression: Diagnose returned None, so these six reached nothing."""
    diagnose = next(m for m in registered if m.name == "Diagnose")
    names = {p.module_name for p in diagnose.get_search_providers()}
    assert names == {
        "EventViewer", "CBS", "DISM", "WindowsUpdate", "Reliability", "CrashDumps",
    }


def test_the_filter_panel_offers_no_source_that_cannot_answer(registered):
    """filter_panel listed six sources whose providers were wired to nothing."""
    from ui.filter_panel import _ALL_SOURCES

    reachable = set()
    for module in registered:
        reachable.update(p.module_name for p in module.get_search_providers())

    assert set(_ALL_SOURCES) <= reachable


def test_the_sidebar_is_34_entries(registered):
    assert len(registered) == 34
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: FAIL — Diagnose has no `children`, and `get_search_providers()` returns `[]`

- [ ] **Step 3: Rewrite one module as the pattern**

`src/modules/cbs_log/cbs_module.py` in full — the other five follow it exactly, differing only in name/icon/loader/provider:

```python
"""The CBS log as a Diagnose tab.

The widget is a plain `LogPane`; everything specific to CBS lives in
`cbs_parser`, which this module only feeds a path to.
"""
import logging
from typing import Optional

from PyQt6.QtWidgets import QWidget

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from ui.log_pane import LogPane

from modules.cbs_log.cbs_parser import CBSParser
from modules.cbs_log.cbs_search_provider import CBSSearchProvider

logger = logging.getLogger(__name__)

CBS_LOG_PATH = r"C:\Windows\Logs\CBS\CBS.log"


class CBSLogModule(BaseModule):
    name = "CBS Log"
    icon = "📝"
    description = "Component-Based Servicing log parser"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self):
        super().__init__()
        self._pane: Optional[LogPane] = None
        self._search_provider = CBSSearchProvider()

    def create_widget(self) -> QWidget:
        self._pane = LogPane(loader=self._load)
        self._pane.entries_loaded.connect(self._feed_provider)
        return self._pane

    def _load(self, worker):
        # VERBATIM from DiagnoseModule._load_cbs's do_work — including the
        # CbsPersist_*.cab fallback, which is the path that actually runs on
        # Windows 11, where a plain CBS.log usually does not exist.
        ...

    def _feed_provider(self, entries) -> None:
        # The provider answers global search out of the entries the pane
        # loaded, so it stays empty until this tab has been opened once.
        # That is how Diagnose already behaved; it is not new.
        try:
            self._search_provider.set_entries(entries)
        except Exception:
            logger.debug("Could not hand entries to the CBS provider", exc_info=True)

    def on_activate(self) -> None:
        if self._pane is not None:
            self._pane.load()   # no-op once loaded; force=True is the Refresh button

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def get_status_info(self) -> str:
        if self._pane is None:
            return ""
        return f"CBS Log — {self._pane.row_count()} entries"
```

`CBSParser`'s real shape is `CBSParser(file_path)` then `.parse(progress_callback=...)` (`cbs_parser.py:19`) — not a classmethod and not `progress_cb`. The `_feed_provider` hop replaces `_on_tab_loaded`'s `provider.set_entries(entries)` (`diagnose_module.py:504`); without it the six providers register but answer nothing, which would look exactly like the bug this phase is fixing.

- [ ] **Step 4: Repeat for the other five**

Same shape, using each one's existing reader and provider:

| Module | Loader | Provider |
|---|---|---|
| `event_viewer_module.py` | `read_all_logs` (+ its hours combo via `extra_controls`) | `EventViewerSearchProvider` |
| `dism_module.py` | `DISMParser` on `DISM_LOG_PATH` | `DISMSearchProvider` |
| `wu_module.py` | `WUParser` on `WU_LOG_PATH` | `WUSearchProvider` |
| `reliability_module.py` | `read_reliability_records` | `ReliabilitySearchProvider` |
| `crash_dump_module.py` (`requires_admin = True`) | `read_crash_dumps` | `CrashDumpSearchProvider` |

- [ ] **Step 5: Make Diagnose the host**

Rewrite `DiagnoseModule` as a `CompositeModule` whose `children` are the six, in the `TAB_DEFS` order. Delete `TAB_DEFS`, the six `_load_*` methods, `_do_tab_load`, `_on_tab_load_*`, `_on_tab_loaded`, `_on_tab_error`, `_load_tab`, `_on_tab_changed`, `_tab_state` and `_make_provider` — the children and `LogPane` own all of it now. Delete `get_search_provider`'s `return None`; `CompositeModule.get_search_providers` replaces it.

Its unified search bar, debounce timer, results tree and `_open_event_dialog` stay. They move into the `wrap` hook from Task 2, since Diagnose's widget is a search bar and results tree *above* the tabs, not a bare tab widget:

```python
    def wrap(self, tabs: QTabWidget) -> QWidget:
        self._widget = QWidget()
        root = QVBoxLayout(self._widget)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addLayout(self._build_search_row())   # unchanged, from create_widget
        root.addWidget(self._results_tree, 1)      # unchanged, starts hidden
        root.addWidget(tabs, 1)
        return self._widget
```

Wire each child's `entry_activated` to `_open_event_dialog` so double-clicking a row still opens the detail dialog — `diagnose_module.py:285` does this today via `table.row_double_clicked`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_module_inventory.py -v`
Expected: 12 passed

- [ ] **Step 7: Full suite, cold**

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} +
.venv/Scripts/python.exe -m pytest -q
```

Expected: green, 3 skipped, **1 warning** (the pre-existing collection warning). A second warning means a new file has a `SyntaxWarning` that only shows on a cold compile.

- [ ] **Step 8: Run the app and search**

Open Diagnose, load all six tabs, then use the global search bar with the filter panel: tick each of the six sources in turn and confirm each returns results. That is the regression this whole phase exists to fix, and only the running app proves it.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(diagnose): six real modules behind the six tabs"
```

---

### Task 13: Documentation and the build

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `CHANGELOG.md`
- Check: `WinClientTool.spec`, `WinClientTool-portable.spec`, `hooks/`

- [ ] **Step 1: Update CLAUDE.md**

Document `CompositeModule` in the Architecture section beside the plugin system: what it is, that children stay ordinary `BaseModule`s, the tab-change deactivate/activate rule, and that `get_search_providers()` — not `get_search_provider()` — is what the registry calls.

- [ ] **Step 2: Update README and CHANGELOG**

README: the module list and count (34). CHANGELOG: the merges, the Duplicate Finder removal and where it went, the restored diagnostic search, the session-log cap.

- [ ] **Step 3: Check the PyInstaller specs**

```bash
grep -rn "duplicate_finder\|store_apps\|wifi_analyzer\|hosts_editor\|network_extras\|power_boot\|boot_analyzer" *.spec hooks/ pyinstaller_common.py
```

A module that is now imported lazily inside a composite's `__init__` may no longer be found by PyInstaller's static analysis. Add any missing ones to `hiddenimports`.

- [ ] **Step 4: Build and deploy the portable**

```bash
rm -f build/WinClientTool-portable/PYZ-00.toc build/WinClientTool-portable/PKG-00.toc
.venv/Scripts/pyinstaller WinClientTool-portable.spec -y --distpath dist
cp "dist/WinClientTool-Portable.exe" "C:/Users/iorda/OneDrive/1 Personal/Aplicații/WinClientTool-Portable.exe"
```

The deploy step is mandatory per CLAUDE.md — the user runs the app from `Aplicații/`, not from `dist/`.

- [ ] **Step 5: Run the built exe**

Open it, walk every group in the sidebar, open each composite and each of its tabs. A frozen build resolves imports differently from source; a composite whose child is imported lazily is exactly the shape that works from source and fails frozen.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: CompositeModule, and the sidebar as it now stands"
```

---

## Verification checklist

Before calling this done:

- [ ] `.venv\Scripts\python.exe -m pytest -q` — green, 3 skipped, 1 warning on a cold `__pycache__`
- [ ] The app runs from source, unelevated and elevated
- [ ] Every composite's every tab has been opened and looked at
- [ ] The six diagnostic sources each return results through the global search filter
- [ ] `ls VRK_*.log | wc -l` is 20, not 101
- [ ] The portable build runs and its composites work frozen
- [ ] The portable is deployed to `Aplicații/`
